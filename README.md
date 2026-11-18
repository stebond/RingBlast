# RingBlast

Open-source design tool for ring (fan) blasting in sublevel stoping: burden/spacing from several
published methods, ring geometry, charging with recursive decharging, Kuz-Ram fragmentation by
zone, DXF/CSV/JSON/HTML export. Successor of the Excel/VBA macro `RingBlast.xlsm`.

## Install
    pip install -e .[gui,test]
## Use
    ringblast methods | rocks | explosives
    ringblast compare examples/case_macro_input.json
    ringblast run examples/case_macro_input.json --out out/case1     # DXF, CSV, JSON, HTML
    ringblast sensitivity examples/case_macro_input.json --min 2 --max 4 --step 0.25
    ringblast-gui
    pytest
User databases (rocks, explosives) are stored in `~/.ringblast/*.csv` (portable program: `RingBlast_data` next to it; macOS app: `~/Library/Application Support/RingBlast`) and override/extend the built-in ones.
Missing rock/explosive properties are never guessed: a method that needs them reports `MissingInput`.

Status: 0.1 (alpha). Not validated against field data; the explosive database must be checked against
manufacturer datasheets before any engineering use (see docs/DESIGN.md).

## Windows, non-programmer users
Double-click `RingBlast.bat` (first run: creates `.venv` and installs the dependencies); see `README.txt`.
`launcher/build_exe.bat` builds a stand-alone executable with PyInstaller (run it on Windows).

## GUI tabs
Blast design · Rock properties and Explosives (editable tables, stored per user in `~/.ringblast`, restorable) ·
Muck-pile photos (scale calibration, watershed fragment detection, volume-weighted size distribution, Rosin-Rammler fit,
comparison with the Kuz-Ram design) · Settings (plot colours, fonts, sizes). Projects (`*.ringblast`, one zip file) store the
inputs, the database rows used, the photos themselves and their measurements, so a project can be moved to another computer.

## Levels
The design is computed for every drift level: `n_sublevels` rectangular sublevels plus (optionally) the base
drift, whose block is the trapezoid above the hopper. Each drift is central or at the side
(`drift_position`, or `drift_positions` per level, top to base).

## Layout
`src/` code · `database/` rocks and explosives · `examples/` numerical cases and results · `figures/` · `docs/` · `tests/` · `tools/` · `launcher/`

## Portable programs (no Python needed)

Every release carries three packages, built by the GitHub Actions workflow *Build portable programs*:
`RingBlast-portable-<version>-windows.zip` (start `RingBlast.exe`), `-linux.tar.gz` (`tar xzf`, then `./RingBlast`) and
`-macos.tar.gz` (Apple Silicon; unsigned, first start with right-click > Open or `xattr -cr RingBlast.app`).
To build one locally run `python launcher/build_portable.py` on the target system.
Windows/Linux: settings, user database rows and project photos are kept in `RingBlast_data` next to the program
(or in `~/.ringblast` if that folder is read-only); `projects` and `output` are also next to the program.
macOS: settings in `~/Library/Application Support/RingBlast`, `projects` and `output` in `~/Documents/RingBlast`.
`RINGBLAST_HOME` and `RINGBLAST_WORK` override the data and work folders. `--selftest` checks the bundled data.

## Updates

RingBlast checks GitHub in the background (at most once a day, silently when offline) whether a newer release exists and, if so, asks whether to download it. Use *Help > Check for updates...* for an immediate check; the start-up check can be switched off in the *Settings* tab (or with the environment variable `RINGBLAST_NO_UPDATE_CHECK=1`).

To publish a new version: raise `VERSION` in `src/ringblast/about.py` (and `version` in `pyproject.toml`), commit, then create and push a tag such as `v0.2.0`. The GitHub Actions workflow builds the portable programs (Windows, Linux, macOS) and attaches them to the release; the program compares the tag with its own version.
