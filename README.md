    # SigmaOS-draw2

    Vector drawing app

    Part of the **SigmaOS** sovereign operating-system ecosystem — a multi-repository
    distribution modelled on Linux Mint and Omarchy Linux. See the parent
    [`SigmaOS`](https://github.com/AaryanSinghChauhan09/SigmaOS) repository for the
    full component index.

    ## Upstream inspirations
    - https://github.com/linuxmint/drawing

    ## Design principles applied
    - **Abstraction**
- **Encapsulation**
- **Fail-Fast**
- **KISS**
- **Separation of Concerns**
- **Deterministic Testing**

    ## Usage
    Verbs: `canvas, shape, stroke, export-plan`

    ```
    $ sigma-draw canvas --width 800 --height 600 --bg white --store /tmp/c.json
$ sigma-draw shape rect --x 10 --y 20 --w 100 --h 50 --fill red --store /tmp/c.json
$ sigma-draw stroke --points "10,10 40,50 90,50" --store /tmp/c.json
$ sigma-draw export-plan --store /tmp/c.json

    ```

    ## Build & test
    ```
    make build
    make test
    ```

    ## Licence
    GNU General Public License v3.0 (FOSS).
