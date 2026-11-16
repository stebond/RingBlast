import csv
import json

import ezdxf
import pytest

from ringblast import db
from ringblast.cli import main
from ringblast.design import run_design
from ringblast.export import (export_dxf, export_hole_csv, export_json, export_report_html,
                              summary_dict)
from ringblast.models import DesignParams, StopeGeometry

STOPE = StopeGeometry(25, 80, 2, 5, 5, 55)


@pytest.fixture(scope="module")
def case():
    rocks, expl = db.load_rocks(False), db.load_explosives(False)
    p = DesignParams(c_langefors=0.8, rock_factor_A=10)
    rock, ex = rocks["Limestone"], expl["anfo77"]
    return rock, ex, p, run_design(rock, ex, STOPE, p)


def test_dxf_roundtrip(tmp_path, case):
    rock, ex, p, res = case
    f = export_dxf(tmp_path / "fan.dxf", res, STOPE)
    doc = ezdxf.readfile(f)
    assert doc.audit().errors == []
    msp = doc.modelspace()
    charged = [e for e in msp if e.dxf.layer == "HOLES_CHARGED"]
    assert len(charged) == res.n_holes
    assert {"STOPE", "DRIFTS", "HOLES_CHARGED", "HOLES_STEMMING", "ZONES", "LABELS"} <= \
           {layer.dxf.name for layer in doc.layers}
    base = [e for e in msp if e.dxftype() == "TEXT" and e.dxf.text == "Base"]
    assert len(base) == 1
    xs = [v for e in charged for v in (e.dxf.start.x, e.dxf.end.x)]
    assert min(xs) >= -12.5 - 1e-6 and max(xs) <= 12.5 + 1e-6


def test_csv_json_html(tmp_path, case):
    rock, ex, p, res = case
    rows = list(csv.DictReader(open(export_hole_csv(tmp_path / "h.csv", res, STOPE))))
    assert len(rows) == res.n_holes and {r['level'] for r in rows} == {'Sublevel 1', 'Sublevel 2', 'Base'}
    data = json.loads(export_json(tmp_path / "r.json", res, STOPE, rock, ex, p).read_text())
    assert data["stope_totals"]["n_holes"] == res.n_holes == sum(l["n_holes"] for l in data["levels"])
    assert data["stope_totals"]["powder_factor_kg_m3"] == pytest.approx(res.powder_factor)
    html = export_report_html(tmp_path / "r.html", res, STOPE, rock, ex, p, "T").read_text()
    assert "<h1>T</h1>" in html and "Fragmentation zones" in html


def test_cli_run(tmp_path, capsys):
    cfg = tmp_path / "c.json"
    cfg.write_text(json.dumps({"rock": "Limestone", "explosive": "anfo77",
                               "stope": {"width": 25, "height": 80, "n_sublevels": 2,
                                         "drift_width": 5, "drift_height": 5},
                               "params": {"c_langefors": 0.8, "rock_factor_A": 10}}))
    assert main(["run", str(cfg), "--out", str(tmp_path / "o")]) == 0
    assert (tmp_path / "o.dxf").exists() and "holes=" in capsys.readouterr().out
    assert main(["compare", str(cfg)]) == 0
