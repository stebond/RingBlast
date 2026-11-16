# RingBlast – design notes

## Stack
Python >= 3.10; numpy (numerics), ezdxf (DXF R2010), matplotlib (plots/report), PySide6 (GUI, LGPL),
CLI via argparse, data in CSV/JSON. Core has no GUI dependency, so it can be cited, scripted, tested
and reused (e.g. Jupyter). Packaging: pip; Windows executable with PyInstaller.

## Architecture
models -> burden -> geometry -> charging -> fragmentation -> design -> export -> {cli, gui}
* `burden.py`   registry of methods (Langefors-Kihlstrom, Hustrulid/powder factor, energy, Konya 72/83, Ash, Andersen)
* `geometry.py` ring construction: rays from drift centre, perpendicular-offset stepping, exact closure on corners
* `charging.py` stemming 20 D, recursive decharging (rules i-iii)
* `fragmentation.py` Kuz-Ram, Rosin-Rammler, Cunningham uniformity index, annular zones
* `db.py` built-in + user CSV databases (`~/.ringblast`)

## Levels and drift positions
`geometry.level_specs()` returns one `LevelSpec` per drift: `n_sublevels` rectangular blocks (drift at the top of
each block, toes on both walls and on a bottom line at the block bottom + B/2 overlap) and the base drift, whose
block is the trapezoid between the undercut height and the hopper floor (sloping sides). Drifts are central or at
the side of the stope (`drift_position`, `drift_positions` per level). Every level uses the same burden and spacing;
holes, charging, zones and fragmentation are computed per level and summed in `DesignResult`.
Each toe edge is closed exactly on its two fixed corner holes, marching from its lower end.

### Drift height and arched roof
`StopeGeometry.drift_vertical` ("top" | "center") and `drift_top_distance_m` place the sublevel drifts inside their block
(`drift_roof_y`); "center" is relative to the nominal sublevel height, so the layout drawing does not depend on the burden.
When the drift is at least `MIN_HOLE_LENGTH` below the top of the block, `LevelSpec.top_toes` is set and the ring gets a fourth
toe edge (kind `top`, marched from the upper right corner). `roof_arch_rise_m` makes the top boundary of sublevel 1 a circular arc
(chord = top edge of the rectangle, `rise` = distance from that edge to the crown, <= L/2): `models.arch_points`, the polygon of the
level and the stope outline follow it, and the toes on the arc are marched with `geometry.solve_curve` (same perpendicular-spacing
rule as the straight edges, on a dense polyline, closed exactly on the two corner holes).

### Two drifts per sublevel
`drifts_per_sublevel = 2` gives two `LevelSpec` per sublevel (`side` left / right), each with the half block on its side of the
stope axis (toes on the outer wall, the bottom line, the top, and the axis), so the volumes add up to the full block minus the two
drifts. `twin_position` is `sides` (drifts at the walls, `drift_wall_distance_m` applies) or `halves` (at +-L/4). The roof arch is
shared: a half block takes the arc between its two abscissas (`arch_segment`, flat edge height `arch_base_y`). Toes of the two fans
coincide on the axis (mirror images); staggering them is not implemented.

### Charging check of neighbouring holes
`charging.decharge` thins alternate holes (rule III). Neighbours that are too close can remain next to a protected corner hole (e.g. a hole thinned only with respect to its +-2 neighbours)
or, on a closed contour (drift below the top of the block), between the last and the first hole of the sequence; their collars
are then only decimetres apart. A final check, repeated until no pair is too close, decharges the fuller hole of any pair of neighbours whose charged parts are closer
than S/2 (never a protected corner) until it is at least S/2 from the charged part of its neighbours (`closed=True` makes the neighbours wrap around). This also removes the left/right asymmetry that
the alternating passes left at the end of open rings with an even number of holes (mean size of the reference case 25.2 -> 27.1 cm).

## Photo analysis (imageanalysis.py)
Grey scale, CLAHE, adaptive threshold for the dark gaps, scale-adaptive distance-transform peaks, watershed; equivalent
diameter of each region with the user-supplied scale; volume-weighted cumulative curve (V ~ d^3); Rosin-Rammler fit on
10-90 % passing. Checked on synthetic images of known sizes (D50 within a few percent). Limits: visible surface only,
no fines below the smallest-fragment size, shadows and overlap bias; validate against sieving before quantitative use.

## Database, projects, plot style
`db.py` row API: built-in rows (`database/`) + user rows (`~/.ringblast`, only new or modified rows are stored, custom
parameter columns allowed). `project.py`: JSON project with inputs, used/modified database rows and photo records.
`plotstyle.py`: one global style (colours, fonts, sizes) used by every plot, persisted in `~/.ringblast/plot_style.json`.

## Formulas
See the docstrings; key ones: Langefors B = d/33 sqrt(P s /(c' f S/B)); Kuznetsov
X50 = A K^-0.8 Q^(1/6) (115/RWS)^(19/30); n = (2.2-14B/D) sqrt((1+S/B)/2)(1-W/B)(|BCL-CCL|/L+0.1)^0.1 L/H.

## Validation (engine vs legacy macro, same input)
holes 20 = 20; N_lat/N_bot 6/7; drilled length 346.158 vs 346.154 m; toes within ~4 mm;
zone areas within 1 %; slide examples: Langefors 3.05 m, Hustrulid 2.72 m (tests/test_core.py).
Known macro defects reproduced only in a dedicated test (Q computed over a 0.1 m column, RWS constant, etc.).

## Database schema
rocks.csv: name, density, ucs, tensile, E, nu, vp, frag energy (kJ/m2), c_langefors, rock_factor_A, source, verified.
explosives.csv: name, density, energy (MJ/kg), VOD, RWS (ANFO = 100), source, verified.
Built-in explosive values come from the old macro: replace with manufacturer datasheets (flag `verified`).

## Booster (bottom charge)
`DesignParams.booster` (an `Explosive`) and `booster_length_m` (BCL) put a second explosive at the toe of
every charged hole; the column is the rest of the charged length.  `fragmentation.split_charge` gives
(BCL, CCL); the zone analysis uses the real BCL/CCL in Cunningham's n, a length-weighted RWS for the
mixture and the summed mass (`charge_mass_kg`).  Suggested by F. Tinti; W = 0 is sufficient in ring blasting.

## Roadmap
1. Field validation (blast cases with measured fragmentation, e.g. image analysis). 2. Cunningham
rock-factor module (RMD/JF/RDI/HF). 3. Non-parallel/irregular drift shapes, DXF import of stope outline.
4. Multi-ring / stope-scale reports (PDF). 5. Uncertainty/sensitivity (Monte Carlo on A, S/B, f).
