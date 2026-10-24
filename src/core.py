"""Vector drawing model for SigmaOS-draw (inspired by linuxmint/drawing).

Pure geometry and scene-graph logic: canvas + shapes + strokes, bounding-box
math, an SVG renderer (pure string), and a thin export apply layer tested only
inside a tempdir. No GUI, no pixels, no network.
"""
import argparse, json, math, os, sys, tempfile

ENGINE = {
    "name": "sigma-draw",
    "summary": "Canvas/shape/stroke model with SVG export planning",
    "language": "python",
    "verbs": ["canvas", "shape", "stroke", "export-plan"],
    "principles": ["Abstraction", "Encapsulation", "Fail-Fast", "KISS",
                   "Separation of Concerns", "Deterministic Testing"],
}

cli_doc = """\
$ sigma-draw canvas --width 800 --height 600 --bg white --store /tmp/c.json
$ sigma-draw shape rect --x 10 --y 20 --w 100 --h 50 --fill red --store /tmp/c.json
$ sigma-draw stroke --points "10,10 40,50 90,50" --store /tmp/c.json
$ sigma-draw export-plan --store /tmp/c.json
"""

DEFAULT_STORE = os.path.expanduser("~/.config/sigma-draw/canvas.json")


class DrawError(ValueError):
    pass


def new_canvas(width, height, bg="white"):
    try:
        width, height = int(width), int(height)
    except (TypeError, ValueError):
        raise DrawError(f"bad canvas size: {width!r}x{height!r}")
    if width <= 0 or height <= 0:
        raise DrawError(f"canvas size must be positive, got {width}x{height}")
    return {"width": width, "height": height, "bg": str(bg), "shapes": []}


def load_canvas(path):
    if not os.path.exists(path):
        raise DrawError(f"no canvas at {path} (create one with 'canvas')")
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    return new_canvas(data["width"], data["height"], data.get("bg", "white")) | \
        {"shapes": list(data.get("shapes", []))}


def save_canvas(path, canvas):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".sigma-tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(canvas, fh, indent=2, sort_keys=True)
    os.replace(tmp, path)


def add_shape(canvas, kind, geom):
    """Append a validated shape. Returns its 1-based handle. Fail-fast."""
    try:
        if kind == "rect":
            for k in ("x", "y", "w", "h"):
                if geom.get(k) is None:
                    raise DrawError(f"rect needs --{k}")
            x, y, w, h = (float(geom[k]) for k in ("x", "y", "w", "h"))
            if w <= 0 or h <= 0:
                raise DrawError("rect width/height must be > 0")
            shape = {"kind": "rect", "x": x, "y": y, "w": w, "h": h,
                     "fill": geom.get("fill")}
        elif kind in ("circle", "ellipse"):
            if geom.get("cx") is None or geom.get("cy") is None:
                raise DrawError(f"{kind} needs --cx and --cy")
            cx, cy = float(geom["cx"]), float(geom["cy"])
            if kind == "circle":
                if geom.get("r") is None:
                    raise DrawError("circle needs --r")
                rx = ry = float(geom["r"])
            else:
                if geom.get("rx") is None or geom.get("ry") is None:
                    raise DrawError("ellipse needs --rx and --ry")
                rx, ry = float(geom["rx"]), float(geom["ry"])
            if rx <= 0 or ry <= 0:
                raise DrawError("radii must be > 0")
            shape = {"kind": kind, "cx": cx, "cy": cy, "rx": rx, "ry": ry,
                     "fill": geom.get("fill")}
        elif kind == "line":
            for k in ("x1", "y1", "x2", "y2"):
                if geom.get(k) is None:
                    raise DrawError(f"line needs --{k}")
            x1, y1, x2, y2 = (float(geom[k]) for k in ("x1", "y1", "x2", "y2"))
            if (x1, y1) == (x2, y2):
                raise DrawError("line needs two distinct points")
            shape = {"kind": "line", "x1": x1, "y1": y1, "x2": x2, "y2": y2,
                     "fill": geom.get("fill")}
        else:
            raise DrawError(f"unknown shape kind: {kind!r}")
    except (TypeError, ValueError) as e:
        raise DrawError(f"bad geometry for {kind}: {e}") from e
    canvas["shapes"].append(shape)
    return len(canvas["shapes"])


def add_stroke(canvas, points):
    """Append a polyline stroke. Returns its handle. Fail-fast."""
    if len(points) < 2:
        raise DrawError("stroke needs at least 2 points")
    clean = []
    for p in points:
        try:
            x, y = float(p[0]), float(p[1])
        except (TypeError, ValueError, IndexError):
            raise DrawError(f"bad point: {p!r}")
        clean.append((x, y))
    canvas["shapes"].append({"kind": "stroke", "points": clean,
                             "fill": canvas.get("fill")})
    return len(canvas["shapes"])


def stroke_length(points):
    """Total polyline length. Pure."""
    return sum(math.hypot(b[0] - a[0], b[1] - a[1])
               for a, b in zip(points, points[1:]))


def shape_bbox(shape):
    """(x, y, w, h) bounding box of one shape. Pure."""
    k = shape["kind"]
    if k == "rect":
        return (shape["x"], shape["y"], shape["w"], shape["h"])
    if k in ("circle", "ellipse"):
        return (shape["cx"] - shape["rx"], shape["cy"] - shape["ry"],
                2 * shape["rx"], 2 * shape["ry"])
    pts = _shape_points(shape)
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return (min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))


def _shape_points(shape):
    k = shape["kind"]
    if k == "line":
        return [(shape["x1"], shape["y1"]), (shape["x2"], shape["y2"])]
    if k == "stroke":
        return shape["points"]
    x, y, w, h = shape_bbox(shape)
    return [(x, y), (x + w, y + h)]


def content_bbox(canvas):
    """Union bbox of all shapes, or None when the canvas is empty. Pure."""
    if not canvas["shapes"]:
        return None
    boxes = [shape_bbox(s) for s in canvas["shapes"]]
    x0 = min(b[0] for b in boxes)
    y0 = min(b[1] for b in boxes)
    x1 = max(b[0] + b[2] for b in boxes)
    y1 = max(b[1] + b[3] for b in boxes)
    return (x0, y0, x1 - x0, y1 - y0)


def out_of_bounds(canvas):
    """Handles (1-based) of shapes crossing the canvas edge. Pure."""
    bad = []
    for i, s in enumerate(canvas["shapes"], 1):
        x, y, w, h = shape_bbox(s)
        if x < 0 or y < 0 or x + w > canvas["width"] or y + h > canvas["height"]:
            bad.append(i)
    return bad


def _n(v):
    """Deterministic number formatting for the SVG renderer."""
    return str(int(v)) if float(v) == int(v) else f"{v:g}"


def render_svg(canvas):
    """Pure renderer: canvas -> SVG document string."""
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{canvas["width"]}" '
             f'height="{canvas["height"]}" viewBox="0 0 {canvas["width"]} {canvas["height"]}">',
             f'<rect width="{canvas["width"]}" height="{canvas["height"]}" '
             f'fill="{canvas["bg"]}"/>']
    for s in canvas["shapes"]:
        fill = s.get("fill") or "none"
        k = s["kind"]
        if k == "rect":
            parts.append(f'<rect x="{_n(s["x"])}" y="{_n(s["y"])}" '
                         f'width="{_n(s["w"])}" height="{_n(s["h"])}" fill="{fill}"/>')
        elif k == "circle":
            parts.append(f'<circle cx="{_n(s["cx"])}" cy="{_n(s["cy"])}" '
                         f'r="{_n(s["rx"])}" fill="{fill}"/>')
        elif k == "ellipse":
            parts.append(f'<ellipse cx="{_n(s["cx"])}" cy="{_n(s["cy"])}" '
                         f'rx="{_n(s["rx"])}" ry="{_n(s["ry"])}" fill="{fill}"/>')
        elif k == "line":
            parts.append(f'<line x1="{_n(s["x1"])}" y1="{_n(s["y1"])}" '
                         f'x2="{_n(s["x2"])}" y2="{_n(s["y2"])}" '
                         f'stroke="#000" stroke-width="2"/>')
        elif k == "stroke":
            pts = " ".join(f"{_n(x)},{_n(y)}" for x, y in s["points"])
            parts.append(f'<polyline points="{pts}" fill="none" stroke="#000" '
                         f'stroke-width="2"/>')
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def export_plan(canvas, out_path=None):
    """Pure plan for an export: where it would go and what it would contain."""
    svg = render_svg(canvas)
    target = out_path or "canvas.svg"
    return {"target": target, "format": "svg", "shapes": len(canvas["shapes"]),
            "bytes": len(svg.encode("utf-8")), "bbox": content_bbox(canvas)}


def write_export(canvas, out_path):
    """Execute layer: write the SVG to disk (self_test uses a tempdir)."""
    plan = export_plan(canvas, out_path)
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    tmp = out_path + ".sigma-tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(render_svg(canvas))
    os.replace(tmp, out_path)
    return plan


def parse_points(spec):
    """Parse 'x,y x,y ...' into a point list. Pure."""
    pts = []
    for chunk in str(spec).split():
        try:
            x, y = chunk.split(",")
            pts.append((float(x), float(y)))
        except ValueError:
            raise DrawError(f"bad point: {chunk!r} (want x,y)")
    return pts


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog=ENGINE["name"], description=ENGINE["summary"])
    p.add_argument("--store", default=DEFAULT_STORE, help="canvas store (JSON)")
    sub = p.add_subparsers(dest="cmd", required=True)
    cv = sub.add_parser("canvas", help="create a fresh canvas")
    cv.add_argument("--width", type=int, required=True)
    cv.add_argument("--height", type=int, required=True)
    cv.add_argument("--bg", default="white")
    sh = sub.add_parser("shape", help="add a shape (rect|circle|ellipse|line)")
    sh.add_argument("kind", choices=("rect", "circle", "ellipse", "line"))
    for flag in ("x", "y", "w", "h", "cx", "cy", "r", "rx", "ry", "x1", "y1", "x2", "y2"):
        sh.add_argument(f"--{flag}", type=float, default=None)
    sh.add_argument("--fill", default=None)
    st = sub.add_parser("stroke", help="add a polyline stroke")
    st.add_argument("--points", required=True, help='e.g. "10,10 40,50 90,50"')
    ep = sub.add_parser("export-plan", help="plan (or write) an SVG export")
    ep.add_argument("--out", default=None, help="write the SVG here")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.cmd == "canvas":
            canvas = new_canvas(args.width, args.height, args.bg)
            save_canvas(args.store, canvas)
            print(f"canvas {canvas['width']}x{canvas['height']} bg={canvas['bg']}")
            return 0
        canvas = load_canvas(args.store)
        if args.cmd == "shape":
            geom = {k: getattr(args, k) for k in
                    ("x", "y", "w", "h", "cx", "cy", "r", "rx", "ry", "x1", "y1", "x2", "y2")}
            geom["fill"] = args.fill
            handle = add_shape(canvas, args.kind, geom)
            save_canvas(args.store, canvas)
            print(f"shape #{handle} {args.kind} added ({len(canvas['shapes'])} total)")
        elif args.cmd == "stroke":
            handle = add_stroke(canvas, parse_points(args.points))
            save_canvas(args.store, canvas)
            print(f"stroke #{handle} added ({len(canvas['shapes'])} total)")
        elif args.cmd == "export-plan":
            plan = export_plan(canvas, args.out)
            if args.out:
                write_export(canvas, args.out)
            print(f"target={plan['target']} format={plan['format']} "
                  f"shapes={plan['shapes']} bytes={plan['bytes']} bbox={plan['bbox']}")
        return 0
    except (DrawError, OSError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


def self_test() -> None:
    c = new_canvas(800, 600, "white")
    h = add_shape(c, "rect", {"x": 10, "y": 20, "w": 100, "h": 50, "fill": "red"})
    assert h == 1
    assert shape_bbox(c["shapes"][0]) == (10.0, 20.0, 100.0, 50.0)
    add_shape(c, "circle", {"cx": 100, "cy": 100, "r": 25})
    assert shape_bbox(c["shapes"][1]) == (75.0, 75.0, 50.0, 50.0)
    add_shape(c, "line", {"x1": 0, "y1": 0, "x2": 30, "y2": 40})
    assert shape_bbox(c["shapes"][2]) == (0.0, 0.0, 30.0, 40.0)
    assert len(c["shapes"]) == 3
    # geometry: stroke length (3-4-5 triangle), union bbox
    assert stroke_length([(0, 0), (30, 40)]) == 50.0
    assert stroke_length([(0, 0), (3, 4), (3, 4)]) == 5.0     # zero segment ok
    assert content_bbox(c) == (0.0, 0.0, 125.0, 125.0)
    assert content_bbox(new_canvas(10, 10)) is None
    # out-of-bounds detection
    assert out_of_bounds(c) == []
    add_shape(c, "rect", {"x": 790, "y": 0, "w": 100, "h": 10})
    assert out_of_bounds(c) == [4]
    # SVG rendering is pure & deterministic
    svg = render_svg(c)
    assert svg == render_svg(c)
    assert svg.startswith("<svg ") and svg.rstrip().endswith("</svg>")
    assert svg.count("<rect") == 3        # bg + 2 rects
    assert 'fill="red"' in svg
    # fail-fast geometry validation
    for bad in (lambda: add_shape(c, "rect", {"x": 0, "y": 0, "w": 0, "h": 5}),
                lambda: add_shape(c, "rect", {"x": 0, "y": 0}),
                lambda: add_shape(c, "circle", {"cx": 1, "cy": 1}),
                lambda: add_shape(c, "blob", {}),
                lambda: add_stroke(c, [(1, 1)]),
                lambda: new_canvas(0, 10),
                lambda: parse_points("1;2")):
        try:
            bad()
        except DrawError:
            pass
        else:
            raise AssertionError("expected DrawError")
    # export plan + write (tempdir only)
    plan = export_plan(c, "/tmp/x.svg")
    assert plan["shapes"] == 4 and plan["format"] == "svg"
    assert plan["bytes"] == len(svg.encode("utf-8"))
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "art.svg")
        write_export(c, out)
        assert open(out, encoding="utf-8").read() == svg
        store = os.path.join(d, "canvas.json")
        save_canvas(store, c)
        again = load_canvas(store)
        assert render_svg(again) == svg
        try:
            load_canvas(os.path.join(d, "none.json"))
        except DrawError:
            pass
        else:
            raise AssertionError("missing canvas not caught")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
