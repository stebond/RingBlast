"""Regenerates figures/ and examples/output/ from examples/*.json  (python tools/make_figures.py)"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from ringblast import db  # noqa: E402
from ringblast.design import run_design  # noqa: E402
from ringblast.export import (export_dxf, export_hole_csv, export_json, export_report_html,  # noqa: E402
                              plot_fragmentation, plot_pattern)
from ringblast.models import DesignParams, StopeGeometry  # noqa: E402

for cfg_path in sorted((ROOT / "examples").glob("*.json")):
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    rock, ex = db.load_rocks()[cfg["rock"]], db.load_explosives()[cfg["explosive"]]
    stope, p = StopeGeometry(**cfg["stope"]), DesignParams(**cfg.get("params", {}))
    res = run_design(rock, ex, stope, p)
    out = ROOT / "examples" / "output" / cfg_path.stem
    export_dxf(out.with_suffix(".dxf"), res, stope, params=p)
    export_hole_csv(out.with_suffix(".holes.csv"), res, stope, p)
    export_json(out.with_suffix(".json"), res, stope, rock, ex, p)
    export_report_html(out.with_suffix(".html"), res, stope, rock, ex, p, cfg_path.stem)
    for name, fig in (("pattern", plot_pattern(res, stope)), ("fragmentation", plot_fragmentation(res))):
        fig.savefig(ROOT / "figures" / f"{cfg_path.stem}_{name}.png", dpi=200, bbox_inches="tight")
    print(cfg_path.stem, "OK")
