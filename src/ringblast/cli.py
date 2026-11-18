"""Command line interface:  python -m ringblast.cli --help"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import db
from .burden import METHODS, BurdenInputs, compare_methods
from .design import run_design, sensitivity
from .export import export_dxf, export_hole_csv, export_json, export_report_docx, export_report_html
from .geometry import mean_hole_length
from .models import DesignParams, StopeGeometry


def _load(cfg: dict):
    rocks, expl = db.load_rocks(), db.load_explosives()
    rock, ex = rocks[cfg["rock"]], expl[cfg["explosive"]]
    stope = StopeGeometry(**cfg["stope"])
    params = DesignParams(**cfg.get("params", {}))
    if cfg.get("booster"):                       # name of the bottom-charge explosive
        params.booster = expl[cfg["booster"]]
    return rock, ex, stope, params


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="ringblast", description="Ring blast design")
    sub = ap.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run", help="run a design from a JSON file")
    run.add_argument("config")
    run.add_argument("--out", default="ringblast_out", help="output prefix")
    sub.add_parser("methods", help="list burden methods")
    sub.add_parser("rocks", help="list rocks")
    sub.add_parser("explosives", help="list explosives")
    cmp_ = sub.add_parser("compare", help="burden from every method")
    cmp_.add_argument("config")
    sens = sub.add_parser("sensitivity", help="burden scan")
    sens.add_argument("config")
    sens.add_argument("--min", type=float, required=True)
    sens.add_argument("--max", type=float, required=True)
    sens.add_argument("--step", type=float, default=0.2)
    a = ap.parse_args(argv)

    if a.cmd == "methods":
        for m in METHODS.values():
            print(f"{m.key:22s} {m.reference:42s} {m.note}")
        return 0
    if a.cmd == "rocks":
        for r in db.load_rocks().values():
            print(f"{r.name:28s} rho={r.density}  UCS={r.ucs_mpa}")
        return 0
    if a.cmd == "explosives":
        for e in db.load_explosives().values():
            print(f"{e.name:12s} rho={e.density} E={e.energy_mj_kg} VOD={e.vod_ms} RWS={e.rws_anfo}")
        return 0

    cfg = json.loads(Path(a.config).read_text(encoding="utf-8"))
    rock, ex, stope, params = _load(cfg)
    if a.cmd == "compare":
        x = BurdenInputs(rock, ex, params, mean_hole_length(stope, 3.0))
        for k, v in compare_methods(x).items():
            print(f"{k:22s} {'n/a (missing data)' if v is None else f'{v:.3f} m'}")
        return 0
    if a.cmd == "sensitivity":
        n = int(round((a.max - a.min) / a.step)) + 1
        rows = sensitivity(rock, ex, stope, params, [a.min + i * a.step for i in range(n)])
        print("burden  spacing  holes  drilled_m  charge_kg   PF   (whole stope, all levels)")
        for r in rows:
            if "error" in r:
                print(f"{r['burden_m']:.2f}  error: {r['error']}")
            else:
                print(f"{r['burden_m']:.2f}  {r['spacing_m']:.2f}    {r['n_holes']:3d}   "
                      f"{r['drilled_length_m']:8.1f}  {r['charge_kg']:8.0f}   {r['powder_factor']:.2f}")
        return 0
    res = run_design(rock, ex, stope, params)
    out = Path(a.out)
    export_dxf(out.with_suffix(".dxf"), res, stope, params=params)
    export_hole_csv(out.with_suffix(".holes.csv"), res, stope, params)
    export_json(out.with_suffix(".json"), res, stope, rock, ex, params)
    export_report_html(out.with_suffix(".html"), res, stope, rock, ex, params, project=out.name)
    try:
        export_report_docx(out.with_suffix(".docx"), res, stope, rock, ex, params, project=out.name)
    except ImportError:
        pass                                              # python-docx not installed (pip install python-docx)
    print(f"B={res.burden_m:.2f} m  S={res.spacing_m:.2f} m  holes={res.n_holes}  "
          f"drilled={res.drilled_length_m:.1f} m  charge={res.charge_kg:.0f} kg  "
          f"PF={res.powder_factor:.2f} kg/m3  mean size={res.weighted_mean_size_cm:.1f} cm")
    for lv in res.levels:
        print(f"  {lv.spec.name:11s} drift {lv.spec.position:6s} holes={lv.n_holes:3d} "
              f"drilled={lv.drilled_length_m:7.1f} m  charge={lv.charge_kg:6.0f} kg  PF={lv.powder_factor:.2f}")
    for w in res.warnings:
        print("warning:", w)
    print("written:", ", ".join(str(out.with_suffix(s)) for s in (".dxf", ".holes.csv", ".json", ".html")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
