# Database

* `rocks.csv` - 65 rocks (from `rock_properties_for_RingBlast.xlsx` plus the legacy macro data).
* `explosives.csv` - 14 explosives: 7 legacy macro values (**verify against manufacturer datasheets**) and 7 boosters (pentolite and Pentex/Trojan cast boosters, Dynomax Pro) from public datasheets; see the `source` and `notes` columns. Energies of the PETN/TNT cast boosters are estimates (not published by the makers), and RWS = 100·E/3.7 MJ/kg.
* `legacy_soils.csv` - 10 soils from the old table, excluded from the calculations.

To add your own materials use the *Add rock...* button of the program, or append rows to the
`rocks.csv` / `explosives.csv` files in `%USERPROFILE%\.ringblast` (same columns; they take precedence
over the files in this folder, so project updates never overwrite user data).
An empty field means "not available": methods that need it report the problem instead of guessing.
