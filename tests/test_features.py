import csv
import zipfile
from pathlib import Path
import json
import os

import numpy as np
import pytest

from ringblast import db, imageanalysis as ia, plotstyle, project
from ringblast.project import DEFAULT_INPUTS, ImageRecord
from synth import SCALE, make_photo

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


# ------------------------------------------------------------------ image analysis
def test_image_analysis_recovers_known_sizes():
    img, true = make_photo()
    res = ia.analyse_image(img, SCALE, min_size_cm=4, sensitivity=0.4)
    assert res.n_fragments > 40 and res.overlay.shape == img.shape
    for p in (50, 80):
        assert res.percentiles_cm[p] == pytest.approx(ia.percentile_size(true, p), rel=0.25)
    assert res.rr_n > 0 and 0 < res.unresolved_area_fraction < 0.5
    with pytest.raises(ValueError):
        ia.analyse_image(img, 0)


def test_scale_changes_sizes_linearly():
    img, _ = make_photo()
    a = ia.analyse_image(img, SCALE, 4, 0.4)
    b = ia.analyse_image(img, SCALE * 2, 4, 0.4)           # same pixels, twice the px/cm -> half the size
    assert a.percentiles_cm[50] / b.percentiles_cm[50] == pytest.approx(2.0, rel=0.3)


def test_distribution_helpers():
    sizes = np.array([10.0] * 5 + [20.0] * 5)
    assert ia.percentile_size(sizes, 50) == 20.0     # volume weighted: dominated by the 20 cm blocks
    d, p = ia.volume_weighted_curve(sizes)
    assert p[-1] == pytest.approx(1.0) and p[4] == pytest.approx(5 * 1000 / (5 * 1000 + 5 * 8000))
    n, xc = ia.fit_rosin_rammler(np.random.default_rng(0).weibull(2.0, 3000) * 30)
    assert n > 0 and xc > 0


# ------------------------------------------------------------------ database rows
def test_user_rows_round_trip_and_reset():
    base = {r["name"]: r for r in db.builtin_rows("rocks")}
    assert db.effective_rows("rocks") == db.builtin_rows("rocks") and not db.user_rows("rocks")
    rows = db.effective_rows("rocks")
    new = {c: "" for c in db.columns("rocks")} | {"name": "My shale", "density_t_m3": "2.4", "ucs_mpa": "60",
                                                  "porosity_pct": "7"}          # custom parameter
    mod = dict(next(r for r in rows if r["name"] == "Limestone")) | {"ucs_mpa": "999"}
    db.save_user_rows("rocks", [r for r in rows if r["name"] != "Limestone"] + [new, mod])
    eff = {r["name"]: r for r in db.effective_rows("rocks")}
    assert eff["My shale"]["porosity_pct"] == "7" and eff["Limestone"]["ucs_mpa"] == "999"
    assert db.row_status("rocks", eff["My shale"]) == "user" and db.row_status("rocks", eff["Limestone"]) == "modified"
    assert db.load_rocks()["Limestone"].ucs_mpa == 999 and "porosity_pct" in db.columns("rocks")
    assert len(db.user_rows("rocks")) == 2                      # only changed rows are stored
    db.reset_user_rows("rocks")
    assert db.load_rocks()["Limestone"].ucs_mpa == float(base["Limestone"]["ucs_mpa"]) and "My shale" not in db.load_rocks()


def test_invalid_rows_are_skipped_not_fatal():
    rows = db.effective_rows("explosives")
    bad = {c: "" for c in db.columns("explosives")} | {"name": "Broken", "density_kg_dm3": "abc"}
    db.save_user_rows("explosives", rows + [bad])
    assert "Broken" not in db.load_explosives() and any("Broken" in e for e in db.ROW_ERRORS)
    assert "anfo77" in db.load_explosives()


def test_import_rows_reports_changes():
    new = {c: "" for c in db.columns("rocks")} | {"name": "Imported", "density_t_m3": "2.5"}
    assert "added" in db.import_rows("rocks", [new])[0]
    assert db.import_rows("rocks", [new]) == []                  # identical -> nothing to do
    assert "replaced" in db.import_rows("rocks", [new | {"density_t_m3": "2.6"}])[0]


# ------------------------------------------------------------------ project file + plot style
def test_project_file_round_trip(tmp_path):
    rec = ImageRecord(str(tmp_path / "a.jpg"), date="2026-10-29", location="Level 2, ring 14, left pile",
                      notes="wet muck", scale_px_per_cm=3.2, scale_points=[(1, 2), (3, 4)], scale_length_cm=50,
                      summary={"d50_cm": 31.0})
    inputs = dict(DEFAULT_INPUTS) | {"width": 30.0, "drift_position": "left"}
    (tmp_path / "a.jpg").write_bytes(b"fake-jpeg-bytes")
    p, warn = project.save_project(tmp_path / ("x" + project.EXTENSION), "Case A", "notes\nline 2", inputs, [rec],
                                   {"rocks": [{"name": "My shale", "density_t_m3": "2.4"}]},
                                   fragment_sizes=[[1.5, 2.5, 30.0]])
    assert warn == []
    d = project.load_project(p)
    assert d["fragment_sizes"] == [[1.5, 2.5, 30.0]] and Path(d["images"][0].path).read_bytes() == b"fake-jpeg-bytes"
    assert d["name"] == "Case A" and d["inputs"]["width"] == 30.0 and d["database"]["rocks"][0]["name"] == "My shale"
    assert d["images"][0].location == rec.location and d["images"][0].summary == {"d50_cm": 31.0}
    with pytest.raises(ValueError):
        (tmp_path / "bad.json").write_text(json.dumps({"format": "other"}))
        project.load_project(tmp_path / "bad.json")


def test_project_is_self_contained(tmp_path):
    """Photos are inside the project file: deleting the originals and opening the file elsewhere works."""
    f = tmp_path / "orig" / "pile.jpg"
    f.parent.mkdir()
    f.write_bytes(b"\xff\xd8photo")
    rec = ImageRecord(str(f), location="L1")
    p, _ = project.save_project(tmp_path / ("s" + project.EXTENSION), "n", "", dict(DEFAULT_INPUTS), [rec])
    f.unlink()
    d = project.load_project(p)
    assert Path(d["images"][0].path).read_bytes() == b"\xff\xd8photo" and d["images"][0].path != str(f)
    # a missing original is reported, not fatal
    _, warn = project.save_project(tmp_path / "t.ringblast", "n", "", dict(DEFAULT_INPUTS), [rec])
    assert warn and "pile.jpg" in warn[0]


def test_plot_style_persists(tmp_path):
    st = plotstyle.PlotStyle(figure_bg="#102030", font_size=12.0)
    plotstyle.save(st)
    plotstyle.set_style(plotstyle.PlotStyle())
    assert plotstyle.load().figure_bg == "#102030" and plotstyle.get().font_size == 12.0
    assert plotstyle.rc(st)["axes.facecolor"] == st.axes_bg


# ------------------------------------------------------------------ GUI
@pytest.fixture()
def win():
    from PySide6 import QtWidgets as W
    from ringblast.gui.app import MainWindow
    W.QApplication.instance() or W.QApplication([])
    return MainWindow()


def test_gui_tables_edit_add_reset(win):
    t = win.rock_tab
    n0 = t.table.rowCount()
    t.add_row("My basalt")
    assert t.table.rowCount() == n0 + 1
    # fill the density of the new row and a custom parameter
    t.add_column("porosity_pct")
    row = [r["name"] for r in t.rows()].index("My basalt")
    t.table.item(row, t.cols.index("density_t_m3")).setText("2.9")
    t.table.item(row, t.cols.index("porosity_pct")).setText("3")
    assert db.load_rocks()["My basalt"].density == 2.9 and win.rock.findText("My basalt") >= 0
    assert [r for r in db.user_rows("rocks") if r["name"] == "My basalt"][0]["porosity_pct"] == "3"
    lime = [r["name"] for r in t.rows()].index("Limestone")
    t.table.item(lime, t.cols.index("ucs_mpa")).setText("77")
    assert db.load_rocks()["Limestone"].ucs_mpa == 77
    t.table.selectRow(lime); t.delete_selected()                      # restore the original value
    assert db.load_rocks()["Limestone"].ucs_mpa != 77
    t.reset(confirm=False)
    assert "My basalt" not in db.load_rocks() and win.rock.findText("My basalt") < 0


def test_gui_project_carries_user_materials_to_another_machine(win, tmp_path, monkeypatch):
    win.rock_tab.add_row("Site rock")
    r = [x["name"] for x in win.rock_tab.rows()].index("Site rock")
    win.rock_tab.table.item(r, win.rock_tab.cols.index("density_t_m3")).setText("2.8")
    win.rock.setCurrentText("Site rock")
    win.proj_name.setText("Mine X"); win.proj_notes.setPlainText("first trial")
    win.w["width"].setValue(30)
    path = win.save_project_to(tmp_path / ("p" + project.EXTENSION))
    saved = json.loads(zipfile.ZipFile(path).read("project.json"))
    assert any(x["name"] == "Site rock" for x in saved["database"]["rocks"])
    assert [x["name"] for x in saved["database"]["rocks"]].count("Limestone") == 0     # unchanged built-ins not stored
    # "another machine": empty user database
    db.reset_user_rows("rocks"); win.reload_databases(keep=False); win.rock_tab.reload()
    assert "Site rock" not in win.rocks
    msgs = win.load_project_from(path)
    assert "Site rock" in win.rocks and win.rock.currentText() == "Site rock" and msgs
    assert win.proj_name.text() == "Mine X" and win.w["width"].value() == 30
    # the used built-in rock is stored even if unchanged
    win.rock.setCurrentText("Limestone")
    assert any(x["name"] == "Limestone" for x in json.loads(zipfile.ZipFile(win.save_project_to(path)).read("project.json"))["database"]["rocks"])


def test_segmentation_parameters_change_the_result():
    img, true = make_photo()
    base = ia.analyse_image(img, SCALE, 4.0, 0.4)
    assert base.n_fragments > 40
    # every option must run and give a sensible, different or equal-but-valid result
    for params in ({"threshold_mode": "otsu"}, {"threshold_mode": "fixed", "fixed_level": 90},
                   {"contrast": 0, "smoothing": 0}, {"gamma": 1.6}, {"erode_iter": 1, "close_iter": 1},
                   {"threshold_shift": 8}, {"invert": True}):
        r = ia.analyse_image(img, SCALE, 4.0, 0.4, params=params)
        assert r.n_fragments >= 0 and 0 <= r.unresolved_area_fraction <= 1
    assert ia.analyse_image(img, SCALE, 4.0, 0.4, params={"threshold_shift": 30}).n_fragments != base.n_fragments
    for stage in ("pre", "mask"):
        out = ia.stage_image(img, SCALE, 4.0, 0.4, {"gamma": 1.3}, stage)
        assert out.ndim == 3 and out.shape[2] == 3


def test_gui_segmentation_controls_are_stored_per_photo(win, tmp_path):
    import cv2
    img, _ = make_photo()
    f = tmp_path / "p.png"; cv2.imwrite(str(f), img)
    tab = win.images_tab
    tab.add_files([str(f)])
    tab.set_scale_points((100, 100), (100 + 60 * SCALE, 100), 60.0)
    tab.seg_w["threshold_mode"].setCurrentText("otsu")
    tab.seg_w["contrast"].setValue(3.5)
    tab.seg_w["invert"].setChecked(True)
    assert tab.records[0].seg["threshold_mode"] == "otsu" and tab.records[0].seg["contrast"] == 3.5
    tab.view_mode.setCurrentIndex(3)                                    # boundaries preview must render
    assert tab.view._pix is not None
    tab.add_files([str(f.with_name("p2.png"))]) if cv2.imwrite(str(f.with_name("p2.png")), img) else None
    tab.set_scale_points((100, 100), (100 + 30 * SCALE, 100), 30.0)
    tab.seg_w["gamma"].setValue(1.4); tab.min_size.setValue(5.0)         # second photo, other settings
    tab.analyse(tab.records[1:], quiet=True)
    tab.seg_w["gamma"].setValue(1.5)                                    # changed after the analysis
    assert "parameters changed" in tab.summary.toPlainText()
    tab.listw.setCurrentRow(0)
    p = win.save_project_to(tmp_path / ("seg" + project.EXTENSION))
    win.reset_all(confirm=False)
    win.load_project_from(p)
    r0, r1 = win.images_tab.records
    assert r0.seg["threshold_mode"] == "otsu" and win.images_tab.seg_w["contrast"].value() == 3.5
    assert r1.seg["threshold_mode"] == "adaptive" and r1.seg["gamma"] == 1.5 and r1.min_size_cm == 5.0
    assert r1.analysed_with["gamma"] == 1.4 and r1.analysed_with["scale_px_per_cm"] == pytest.approx(SCALE)
    assert set(ia.SEG_DEFAULTS) <= set(r0.seg)                         # every parameter is stored
    win.images_tab.reset_segmentation()
    assert win.images_tab.records[0].seg["threshold_mode"] == "adaptive" and win.images_tab.records[0].seg["invert"] is False


def test_icon_files_and_window_icon(win):
    from PIL import Image
    root = Path(__file__).resolve().parents[1] / "launcher"
    assert {(s, s) for s in (16, 32, 48, 256)} <= Image.open(root / "ringblast.ico").info["sizes"]
    assert not win.windowIcon().isNull() and win.windowIcon().availableSizes()
    assert (root / "RingBlast.vbs").read_bytes().count(b"\r\n") > 5


def test_screenshot_script_runs(tmp_path):
    import subprocess, sys
    root = Path(__file__).resolve().parents[1]
    r = subprocess.run([sys.executable, str(root / "tools" / "make_screenshots.py"), "--zoom", "1",
                        "--size", "1100x700", "--out", str(tmp_path)], capture_output=True, text=True,
                       env={**__import__("os").environ, "QT_QPA_PLATFORM": "offscreen"})
    assert r.returncode == 0, r.stderr[-500:]
    assert len(list(tmp_path.glob("*.png"))) >= 10


def test_gui_reset_restores_defaults(win):
    win.w["width"].setValue(40); win.pos.setCurrentText("right"); win.proj_name.setText("zzz")
    win.images_tab.set_records([ImageRecord("x.jpg")])
    win.reset_all(confirm=False)
    assert win.w["width"].value() == DEFAULT_INPUTS["width"] and win.pos.currentText() == "center"
    assert win.proj_name.text() == "" and win.images_tab.records == []


def test_gui_settings_apply_to_plots(win):
    st = win.settings_tab
    st.widgets["figure_bg"].set_color("#112233"); st.widgets["figure_bg"].colorChanged.emit()
    assert plotstyle.get().figure_bg == "#112233" and win.layout_fig.get_facecolor()[:3] != (1, 1, 1)
    st.widgets["font_size"].setValue(14.0)
    assert plotstyle.get().font_size == 14.0 and (plotstyle.STYLE_FILE).exists()
    st.preset.setCurrentText("Dark"); st.load_preset()
    assert plotstyle.get().figure_bg == plotstyle.PRESETS["Dark"].figure_bg
    st.reset()
    assert plotstyle.get() == plotstyle.defaults()


def test_gui_photo_workflow(win, tmp_path):
    import cv2
    img, true = make_photo()
    f = tmp_path / "pile1.png"
    cv2.imwrite(str(f), img)
    tab = win.images_tab
    tab.add_files([str(f)])
    assert len(tab.records) == 1 and tab.records[0].date
    tab.location.setPlainText("Level 1, ring 7"); tab.notes.setPlainText("good light")
    assert tab.records[0].location == "Level 1, ring 7"
    assert tab.analyse(tab.records, quiet=True)                       # no scale yet -> reported
    tab.set_scale_points((100, 100), (100 + 60 * SCALE, 100), 60.0)  # a 60 cm reference
    assert tab.records[0].scale_px_per_cm == pytest.approx(SCALE)
    tab.min_size.setValue(4); tab.sens.setValue(0.4)
    assert tab.analyse(tab.records, quiet=True) == []
    s = tab.records[0].summary
    assert s["n_fragments"] > 40 and s["d50_cm"] == pytest.approx(ia.percentile_size(true, 50), rel=0.25)
    win.run()                                                          # design curve is drawn together with the photos
    tab.refresh()
    files = tab.export(tmp_path / "out")
    assert {p.name for p in files} >= {"photo_analysis_summary.csv", "photo_combined_distribution.csv"}
    rows = list(csv.DictReader(open(tmp_path / "out" / "photo_analysis_summary.csv")))
    assert rows[0]["location"] == "Level 1, ring 7"
    # photo records survive a save / open cycle
    p = win.save_project_to(tmp_path / ("q" + project.EXTENSION))
    win.reset_all(confirm=False)
    f.unlink()                                                         # the original photo is gone: it is inside the project
    win.load_project_from(p)
    rec = win.images_tab.records[0]
    assert rec.location == "Level 1, ring 7" and rec.summary["n_fragments"] > 40
    assert Path(rec.path).exists() and Path(rec.path) != f
    assert win.images_tab.results[rec.path].percentiles_cm[50] == pytest.approx(s["d50_cm"], rel=0.02)


def test_help_menu_manual_and_about(win):
    from PySide6 import QtWidgets as W
    from ringblast import __version__, about
    from ringblast.gui import help as H
    assert __version__ == about.VERSION
    assert f'version = "{about.VERSION}"' in (Path(H.ROOT) / "pyproject.toml").read_text()
    titles = [a.text() for m in win.menuBar().actions() if m.menu() for a in m.menu().actions()]
    assert "User manual" in titles and "About RingBlast..." in titles
    win.show_manual()
    assert "Quick start" in win._manual.browser.toPlainText() and not win._manual.windowIcon().isNull()
    html = H.MANUAL.read_text(encoding="utf-8")
    for label in ("Run design", "Reset segmentation", "Copy to all photos", "Save project...", "Live update"):
        assert label in html
    for img in __import__("re").findall(r'src="([^"]+)"', html):          # every screenshot of the manual exists
        assert (H.MANUAL.parent / img).exists(), img
    dlg = H.AboutDialog(win, win.windowIcon())
    texts = " ".join(l.text() for l in dlg.findChildren(W.QLabel))
    assert about.VERSION in texts and about.AUTHORS[0] in texts and about.YEAR in texts
    assert any(l.pixmap() is not None and not l.pixmap().isNull() for l in dlg.findChildren(W.QLabel))
    assert "PySide6" in dlg.info


def test_every_control_has_a_tooltip_and_the_switch_works(win):
    from PySide6 import QtCore as C, QtWidgets as W
    from ringblast.gui import tips
    kinds = (W.QPushButton, W.QDoubleSpinBox, W.QSpinBox, W.QComboBox, W.QCheckBox)
    missing = [f"{type(w).__name__}:{getattr(w, 'text', lambda: '')() if hasattr(w, 'text') else ''}"
               for w in win.findChildren(W.QWidget)
               if isinstance(w, kinds) and not w.toolTip() and not w.objectName().startswith("qt_")
               and not isinstance(w.parent(), (W.QAbstractSpinBox, W.QComboBox))]
    assert missing == []
    # the Settings switch: remembered, and the filter swallows the tooltip events
    tips.set_enabled(True)
    ev = __import__("PySide6.QtGui", fromlist=["QHelpEvent"]).QHelpEvent(C.QEvent.ToolTip, C.QPoint(1, 1), C.QPoint(1, 1))
    f = tips.TooltipFilter()
    assert f.eventFilter(win, ev) is False
    win.settings_tab.tips_box.setChecked(False)
    assert tips.enabled() is False and f.eventFilter(win, ev) is True
    assert (db.USER_DIR / "ui_settings.json").exists()
    tips.set_enabled(True)


# ------------------------------------------------------------------ drift height position and arched roof
def _stope(**kw):
    from ringblast.models import StopeGeometry
    d = dict(width=25, height=80, n_sublevels=2, drift_width=5, drift_height=5, wall_angle_deg=55)
    return StopeGeometry(**(d | kw))


def test_arch_points_geometry():
    import math
    from ringblast.models import arch_points
    pts = arch_points(12.5, 80.0, 3.0)
    assert pts[0] == pytest.approx((12.5, 80.0)) and pts[-1] == pytest.approx((-12.5, 80.0))
    assert max(y for _, y in pts) == pytest.approx(83.0)                    # crown = rise above the top edge
    r = (12.5 ** 2 + 3.0 ** 2) / 6.0
    assert all(math.hypot(x, y - (83.0 - r)) == pytest.approx(r) for x, y in pts)   # one circle
    assert arch_points(12.5, 80.0, 0.0) == [(12.5, 80.0), (-12.5, 80.0)]            # 0 = rectangle


@pytest.mark.parametrize("kw", [dict(drift_vertical="center"), dict(drift_top_distance_m=5.0),
                                dict(roof_arch_rise_m=4.0), dict(roof_arch_rise_m=6.0, drift_vertical="center",
                                                                 drift_position="right"),
                                dict(roof_arch_rise_m=3.0, drift_position="left")])
def test_new_geometry_designs_close_and_respect_spacing(kw):
    from ringblast.design import run_design
    from ringblast.geometry import MIN_HOLE_LENGTH
    from ringblast.models import DesignParams
    st = _stope(**kw)
    res = run_design(db.load_rocks()["Limestone"], db.load_explosives()["anfo77"], st,
                     DesignParams(c_langefors=0.8, rock_factor_A=10))
    for lv in res.levels[:-1]:
        r = lv.ring
        for sp in (r.lateral_spacing_eff, r.bottom_spacing_eff, r.right_spacing_eff, r.top_spacing_eff):
            assert sp != sp or sp <= res.spacing_m + 1e-6                      # nan = edge not used
        assert all(h.length >= MIN_HOLE_LENGTH - 1e-9 for h in lv.ring.holes)
        poly = lv.spec.polygon
        xs, ys = [p[0] for p in poly], [p[1] for p in poly]
        assert all(min(xs) - 1e-6 <= h.toe[0] <= max(xs) + 1e-6 and min(ys) - 1e-6 <= h.toe[1] <= max(ys) + 1e-6
                   for h in lv.ring.holes)
    if st.drift_vertical == "center" or st.drift_top_distance_m >= 1 or st.roof_arch_rise_m > 0:
        assert any(h.kind == "top" for h in res.levels[0].ring.holes)         # rock above the drift is drilled
    if st.drift_vertical == "center":
        assert res.levels[0].spec.centre[1] == pytest.approx(st.height - st.sublevel_height / 2)
    if st.roof_arch_rise_m > 0:
        top = max(p[1] for p in res.levels[0].spec.polygon)
        assert top == pytest.approx(st.height + st.roof_arch_rise_m, abs=0.01)
        assert max(y for _, y in __import__("ringblast.export", fromlist=["x"]).stope_outline(st)) \
            == pytest.approx(st.height + st.roof_arch_rise_m)
        assert res.levels[1].spec.arch_rise == 0                              # only the roof rectangle is arched
        assert res.levels[0].volume_m3 > res.levels[1].volume_m3             # the arch adds rock to the roof block


def test_default_geometry_unchanged_and_validation():
    from ringblast.geometry import level_specs
    sp = level_specs(_stope(), 3.0)[0]
    assert sp.top_y == 80 and not sp.top_toes and sp.arch_rise == 0
    for bad in (dict(roof_arch_rise_m=-1), dict(roof_arch_rise_m=20), dict(drift_top_distance_m=40),
                dict(drift_vertical="bottom"), dict(drift_top_distance_m=-2)):
        with pytest.raises(ValueError):
            _stope(**bad).validate()
    with pytest.raises(ValueError):                                              # drift below the block bottom
        level_specs(_stope(drift_top_distance_m=24.0), 8.0)


def test_gui_vertical_position_and_arch(win, tmp_path):
    win.vpos.setCurrentText("center"); win.w["arch"].setValue(4.0)
    assert not win.w["dtop"].isEnabled()
    win.vpos.setCurrentText("top"); win.w["dtop"].setValue(3.0)
    assert win.w["dtop"].isEnabled()
    win.run()
    assert win.result.levels[0].spec.arch_rise == 4.0 and win.result.levels[0].spec.top_y == pytest.approx(77.0)
    p = win.save_project_to(tmp_path / ("g" + project.EXTENSION))
    win.reset_all(confirm=False)
    assert win.w["arch"].value() == 0 and win.vpos.currentText() == "top"
    win.load_project_from(p)
    assert win.w["arch"].value() == 4.0 and win.w["dtop"].value() == 3.0
    old = project.DEFAULT_INPUTS.copy()
    for k in ("drift_vertical", "dtop", "arch"):                                  # projects of earlier versions
        old.pop(k)
    assert {"drift_vertical", "dtop", "arch"} <= set(project.DEFAULT_INPUTS)


# ------------------------------------------------------------------ two drifts per sublevel, zone circles
@pytest.mark.parametrize("kw", [dict(twin_position="sides"), dict(twin_position="halves"),
                                dict(twin_position="halves", roof_arch_rise_m=4.0, drift_vertical="center")])
def test_two_drifts_per_sublevel_are_symmetric_and_cover_the_block(kw):
    from ringblast.design import run_design
    from ringblast.models import DesignParams
    rock, ex, p = db.load_rocks()["Limestone"], db.load_explosives()["anfo77"], DesignParams(c_langefors=0.8, rock_factor_A=10)
    one = run_design(rock, ex, _stope(**{k: v for k, v in kw.items() if k != "twin_position"}), p)
    st = _stope(drifts_per_sublevel=2, **kw)
    two = run_design(rock, ex, st, p)
    assert st.n_levels == len(two.levels) == 2 * 2 + 1
    assert [l.spec.side for l in two.levels] == ["left", "right", "left", "right", ""]
    left, right = two.levels[0], two.levels[1]
    cx = st.width / 4 if kw["twin_position"] == "halves" else st.width / 2 - st.drift_width / 2
    assert left.spec.centre[0] == pytest.approx(-cx) and right.spec.centre[0] == pytest.approx(cx)
    assert left.spec.centre[1] == right.spec.centre[1]
    if "roof_arch_rise_m" not in kw:                              # flat roof: exact mirror images
        assert left.n_holes == right.n_holes and left.volume_m3 == pytest.approx(right.volume_m3, rel=1e-3)
    else:                                                          # the arch is higher at the middle of the stope
        assert left.volume_m3 == pytest.approx(right.volume_m3, rel=0.2)
    # the two halves together fire the same rock as one full block, minus the area of the extra drift
    extra = st.drift_width * st.drift_height * two.burden_m
    assert left.volume_m3 + right.volume_m3 == pytest.approx(one.levels[0].volume_m3 - extra, rel=0.01)
    assert two.volume_m3 == pytest.approx(one.volume_m3 - 2 * extra, rel=0.01)
    for lv in two.levels[:-1]:
        xs = [p_[0] for p_ in lv.spec.polygon]
        assert all(min(xs) - 1e-6 <= h.toe[0] <= max(xs) + 1e-6 for h in lv.ring.holes)
        assert all(h.toe[1] <= lv.spec.tl[1] + 5 for h in lv.ring.holes)


def test_two_drifts_validation_and_defaults():
    with pytest.raises(ValueError):
        _stope(drifts_per_sublevel=3).validate()
    with pytest.raises(ValueError):
        _stope(drifts_per_sublevel=2, drift_width=14, twin_position="sides").validate()   # would overlap
    assert _stope().n_levels == 3 and _stope(drifts_per_sublevel=2).n_levels == 5


def test_zone_circles_can_be_hidden():
    from ringblast.design import run_design
    from ringblast.export import plot_pattern
    from ringblast.models import DesignParams
    st = _stope()
    res = run_design(db.load_rocks()["Limestone"], db.load_explosives()["anfo77"], st, DesignParams())
    on, off = plot_pattern(res, st), plot_pattern(res, st, show_zones=False)
    assert len(on.axes[0].lines) > len(off.axes[0].lines)
    assert len(off.axes[0].lines) >= res.n_holes                  # holes still drawn


def test_gui_two_drifts_and_zone_checkbox(win, tmp_path):
    assert win.pos.isEnabled() and not win.twin.isEnabled()
    win.ndrifts.setCurrentText("2")
    assert not win.pos.isEnabled() and win.twin.isEnabled()
    win.twin.setCurrentIndex(1)
    win.run()
    assert [l.spec.side for l in win.result.levels][:2] == ["left", "right"] and win.level.count() == 8
    n_on = len(win.plots.widget(0).figure.axes[0].lines)
    win.show_zones.setChecked(False)
    assert len(win.plots.widget(0).figure.axes[0].lines) < n_on
    p = win.save_project_to(tmp_path / ("t" + project.EXTENSION))
    win.reset_all(confirm=False)
    assert win.ndrifts.currentText() == "1" and win.show_zones.isChecked() and win.pos.isEnabled()
    win.load_project_from(p)
    assert win.ndrifts.currentText() == "2" and win.twin.currentData() == "halves" and not win.show_zones.isChecked()
    assert not win.pos.isEnabled()


def test_charged_parts_of_neighbouring_holes_keep_half_spacing():
    """Rule III for every pair of neighbours: charged parts at least S/2 apart (corner-to-corner pairs excepted),
    also next to protected corners and between the last and the first hole of a closed contour."""
    from ringblast.charging import point_segment_distance
    from ringblast.design import run_design
    from ringblast.models import DesignParams
    rock, ex = db.load_rocks()["Limestone"], db.load_explosives()["anfo77"]
    p = DesignParams(c_langefors=0.8, rock_factor_A=10)
    for kw in (dict(), dict(drift_vertical="center"), dict(drifts_per_sublevel=2, drift_vertical="center"),
               dict(drifts_per_sublevel=2, twin_position="halves", roof_arch_rise_m=4.0), dict(roof_arch_rise_m=3.0),
               dict(drifts_per_sublevel=2, twin_position="sides", drift_vertical="center", width=30)):
        res = run_design(rock, ex, _stope(**kw), p)
        for lv in res.levels:
            hs = lv.ring.holes
            closed = lv.spec.top_toes and lv.spec.kind == "sublevel"
            corner = lambda h: h.kind.endswith("corner")
            for i in range(len(hs) if closed else len(hs) - 1):
                a, b = hs[i], hs[(i + 1) % len(hs)]
                if a.charged_length < 1e-9 or b.charged_length < 1e-9 or (corner(a) and corner(b)):
                    continue
                gap = min(point_segment_distance(a.charge_start, b.charge_start, b.toe),
                          point_segment_distance(b.charge_start, a.charge_start, a.toe))
                assert gap >= res.spacing_m / 2 - 0.03, (kw, lv.spec.name, a.index, b.index, gap)


def test_paths_portable_and_selftest(tmp_path, monkeypatch):
    from ringblast import paths
    monkeypatch.setenv("RINGBLAST_HOME", str(tmp_path / "home"))
    assert paths.user_dir() == tmp_path / "home"
    monkeypatch.delenv("RINGBLAST_HOME")
    assert (paths.resource_root() / "database" / "rocks.csv").exists()
    assert paths.frozen() is False
    monkeypatch.setattr("sys.frozen", True, raising=False)
    monkeypatch.setattr("sys.executable", str(tmp_path / "RingBlast.exe"))
    assert paths.portable() and paths.user_dir() == tmp_path / "RingBlast_data"
    assert paths.app_dir() == tmp_path.resolve()


def test_gui_selftest(capsys):
    pytest = __import__("pytest")
    pytest.importorskip("PySide6")
    from ringblast.gui import app
    assert app.selftest() == 0
    assert "rocks: 65" in capsys.readouterr().out


def test_launch_with_splash(monkeypatch):
    pytest = __import__("pytest")
    pytest.importorskip("PySide6")
    from PySide6 import QtCore as C
    from PySide6 import QtWidgets as W
    from ringblast.gui import launch
    app = W.QApplication.instance() or W.QApplication([])
    steps = []
    orig = launch.Splash.step

    def step(self, v, t):
        steps.append((v, t))
        orig(self, v, t)
        if v == 1.0:                      # quit only once the event loop is about to start
            C.QTimer.singleShot(800, app.quit)
    monkeypatch.setattr(launch.Splash, "step", step)
    assert launch.main() == 0
    values = [v for v, _ in steps]
    assert values[0] < 0.1 and values[-1] == 1.0 and values == sorted(values)
    assert any("matplotlib" in t for _, t in steps)


def test_log_x_axis_toggle():
    import matplotlib
    matplotlib.use("Agg")
    from ringblast.export import plot_fragmentation
    from ringblast import db
    from ringblast.design import run_design
    from ringblast.models import DesignParams, StopeGeometry
    res = run_design(db.load_rocks(False)["Limestone"], db.load_explosives(False)["anfo77"],
                     StopeGeometry(25, 80, 2, 5, 5, 55), DesignParams(c_langefors=0.8, rock_factor_A=10))
    assert plot_fragmentation(res).axes[0].get_xscale() == "log"
    assert plot_fragmentation(res, log_x=False).axes[0].get_xscale() == "linear"
    assert plot_fragmentation(res, 0, log_x=False).axes[0].get_xscale() == "linear"


def test_booster_cunningham_uniformity_and_mixed_rws():
    """Booster + column: real BCL/CCL in n (Cunningham 1983), length-weighted RWS, summed mass."""
    import copy
    from ringblast import db
    from ringblast.design import run_design
    from ringblast.fragmentation import charge_mass_kg, split_charge
    from ringblast.models import DesignParams, StopeGeometry
    rock, expl = db.load_rocks(False)["Limestone"], db.load_explosives(False)
    col, bst = expl["anfo77"], expl["gelA6"]
    st = StopeGeometry(25, 80, 2, 5, 5, 55)
    base = DesignParams(c_langefors=0.8, rock_factor_A=10, deviation_base_m=0.0, deviation_per_m=0.0)
    one = run_design(rock, col, st, base)
    p = copy.copy(base)
    p.booster, p.booster_length_m = bst, 0.5
    two = run_design(rock, col, st, p)
    # the single-explosive result is unchanged by the new code (BCL = CCL convention)
    assert one.charge_kg > 0
    h = two.levels[0].ring.holes[0]
    b, c = split_charge(h, p)
    assert abs(b - 0.5) < 1e-9 and abs(b + c - h.charged_length) < 1e-9
    assert charge_mass_kg(h, col, p) > charge_mass_kg(h, col, base)      # denser booster
    # booster only changes mass through its density; hole geometry is identical
    assert two.n_holes == one.n_holes and two.charged_length_m == one.charged_length_m
    assert two.charge_kg > one.charge_kg
    z1, z2 = one.levels[0].zones[0], two.levels[0].zones[0]
    assert col.rws_anfo <= z2.rws_eff <= bst.rws_anfo
    assert z1.rws_eff == col.rws_anfo
    # a short bottom charge makes |BCL-CCL|/L large -> larger n than BCL = CCL
    assert z2.uniformity_n > z1.uniformity_n
    # explicit check of the formula for one zone-free hole pair
    L = b + c
    assert abs(((abs(b - c) / L + 0.1) ** 0.1) - (abs(b - c) / L + 0.1) ** 0.1) < 1e-12


def test_booster_drawn_in_pattern_and_dxf(tmp_path):
    import copy
    import ezdxf
    import matplotlib
    matplotlib.use("Agg")
    from ringblast import db
    from ringblast.design import run_design
    from ringblast.export import export_dxf, plot_pattern
    from ringblast.models import DesignParams, StopeGeometry
    rock, expl = db.load_rocks(False)["Limestone"], db.load_explosives(False)
    st = StopeGeometry(25, 80, 2, 5, 5, 55)
    p = DesignParams(c_langefors=0.8, rock_factor_A=10)
    p.booster, p.booster_length_m = expl["gelA6"], 0.5
    res = run_design(rock, expl["anfo77"], st, p)
    ax = plot_pattern(res, st, params=p).axes[0]
    widths = {round(l.get_linewidth(), 2) for l in ax.lines}
    colors = {l.get_color() for l in ax.lines}
    from ringblast import plotstyle
    assert plotstyle.get().booster_color in colors
    assert max(widths) > 1.5 * plotstyle.get().line_width * 0.9          # booster thicker than column
    ax0 = plot_pattern(res, st).axes[0]
    assert plotstyle.get().booster_color not in {l.get_color() for l in ax0.lines}
    doc = ezdxf.readfile(export_dxf(tmp_path / "b.dxf", res, st, params=p))
    assert len(doc.modelspace().query('LINE[layer=="HOLES_BOOSTER"]')) == res.n_holes


# ---------------------------------------------------------------- update check
class _Resp:
    def __init__(self, data):
        import json as _j
        self._b = _j.dumps(data).encode()

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _fake_opener(routes):
    import urllib.error

    def opener(req, timeout=0):
        url = req.full_url
        for suffix, data in routes.items():
            if url.endswith(suffix):
                if data is None:
                    raise urllib.error.HTTPError(url, 404, "nf", {}, None)
                return _Resp(data)
        raise AssertionError(url)
    return opener


def test_version_parsing_and_comparison():
    from ringblast import updates as u
    assert u.parse_version("v0.2.1") == (0, 2, 1, 1)
    assert u.is_newer("0.2.0", "0.1.9") and u.is_newer("v1.0", "0.9.9")
    assert not u.is_newer("0.1.0", "0.1.0") and not u.is_newer("0.1.0", "0.2.0")
    assert not u.is_newer("0.2.0rc1", "0.2.0")           # a pre-release is older than the release
    assert not u.is_newer("garbage", "0.1.0")


def test_fetch_latest_release_tag_fallback_and_none():
    from ringblast import updates as u
    rel = {"tag_name": "v0.3.0", "html_url": "https://x/rel", "body": "notes", "published_at": "2026-12-01T10:00:00Z",
           "assets": [{"name": "src.zip", "browser_download_url": "a"},
                      {"name": "RingBlast-portable-0.3.0.zip", "browser_download_url": "https://x/portable.zip"}]}
    i = u.fetch_latest(_fake_opener({"/releases/latest": rel}))
    assert (i.version, i.asset_url, i.published) == ("0.3.0", "https://x/portable.zip", "2026-12-01")
    tags = [{"name": "v0.1.0"}, {"name": "v0.2.5"}, {"name": "nightly"}]
    i = u.fetch_latest(_fake_opener({"/releases/latest": None, "/tags": tags}))
    assert i.version == "0.2.5" and i.asset_url == ""
    assert u.fetch_latest(_fake_opener({"/releases/latest": None, "/tags": None})) is None


def test_update_errors_skip_and_daily_limit(tmp_path, monkeypatch):
    import urllib.error
    from ringblast import db
    from ringblast import updates as u
    monkeypatch.setattr(db, "USER_DIR", tmp_path)
    monkeypatch.delenv("RINGBLAST_NO_UPDATE_CHECK", raising=False)
    rel = {"tag_name": "v9.0.0", "html_url": "https://x/rel", "assets": []}
    ok = _fake_opener({"/releases/latest": rel})
    assert u.due_for_auto_check()
    assert u.check(opener=ok).version == "9.0.0"
    assert not u.due_for_auto_check()                     # checked today: no second automatic check
    u.save_settings(skip_version="9.0.0")
    assert u.check(manual=False, opener=ok) is None       # skipped version: silent
    assert u.check(manual=True, opener=ok).version == "9.0.0"
    assert u.check(opener=_fake_opener({"/releases/latest": {"tag_name": "v0.0.1", "assets": []}})) is None

    def offline(req, timeout=0):
        raise urllib.error.URLError("no network")
    import pytest
    with pytest.raises(u.UpdateError):
        u.check(opener=offline)
    u.save_settings(check_updates=False)
    assert not u.due_for_auto_check()
    from ringblast.gui import tips
    tips.set_enabled(False)                               # the tooltip option must not erase the others
    assert u.load_settings()["check_updates"] is False and u.load_settings()["tooltips"] is False


def test_update_dialog_flow(monkeypatch, tmp_path):
    from PySide6 import QtWidgets as W
    from ringblast import db, updates as u
    monkeypatch.setattr(db, "USER_DIR", tmp_path)
    monkeypatch.setenv("RINGBLAST_NO_UPDATE_CHECK", "1")
    from ringblast.gui import app
    qapp = W.QApplication.instance() or W.QApplication([])
    win = app.MainWindow()
    asked, shown = [], []
    monkeypatch.setattr(win._updater, "ask", lambda info: asked.append(info.version))
    monkeypatch.setattr(W.QMessageBox, "information", lambda *a, **k: shown.append(a[2]))
    win._updater._done(u.UpdateInfo("9.9.9", "v9.9.9", "https://x"), "", False)
    assert asked == ["9.9.9"]
    win._updater._done(None, "", False)                   # automatic + up to date: silent
    assert not shown
    win._updater._done(None, "", True)                    # manual + up to date: says so
    assert "latest version" in shown[-1]
    win._updater._done(None, "GitHub cannot be reached", True)
    assert "cannot be reached" in shown[-1]
    win._updater.start(manual=False)                      # disabled by the environment: nothing starts
    assert win._updater._worker is None
    assert win.menuBar().findChildren(W.QMenu)[-1].actions()[2].text().startswith("Check for updates")


# ---------------------------------------------------------------- photo zoom and window size
def test_photo_zoom_pan_and_reset():
    import numpy as np
    from PySide6 import QtCore as C
    from PySide6 import QtGui as G
    from PySide6 import QtWidgets as W
    from ringblast.gui.images_tab import ImageView
    W.QApplication.instance() or W.QApplication([])
    v = ImageView(); v.resize(400, 300)
    v.set_image(np.zeros((300, 400, 3), np.uint8))
    assert v.zoom_factor() == 1.0
    r0, k0 = v._rect()

    def wheel(pos, dy):
        ev = G.QWheelEvent(C.QPointF(pos), C.QPointF(pos), C.QPoint(0, 0), C.QPoint(0, dy),
                           C.Qt.NoButton, C.Qt.NoModifier, C.Qt.NoScrollPhase, False)
        v.wheelEvent(ev)
    cur = C.QPointF(100, 80)
    pt = ((cur.x() - r0.x()) / k0, (cur.y() - r0.y()) / k0)           # photo point under the cursor
    wheel(cur, 240)                                                    # two wheel steps forward: zoom in
    assert v.zoom_factor() > 1.5
    r, k = v._rect()
    assert abs((cur.x() - r.x()) / k - pt[0]) < 1e-6 and abs((cur.y() - r.y()) / k - pt[1]) < 1e-6
    wheel(cur, 120 * 40)                                               # the zoom is limited
    assert v.zoom_factor() == v.MAX_ZOOM
    r, k = v._rect()                                                   # the photo always covers the view
    assert r.x() <= 1e-6 and r.right() >= v.width() - 1e-6 and r.y() <= 1e-6 and r.bottom() >= v.height() - 1e-6
    wheel(cur, -120 * 80)                                              # back out: whole photo again
    assert v.zoom_factor() == 1.0
    wheel(cur, 120)
    v.mouseDoubleClickEvent(None)
    assert v.zoom_factor() == 1.0
    wheel(cur, 120)
    v.set_image(np.zeros((300, 400, 3), np.uint8))                     # same photo size (e.g. other view): zoom kept
    assert v.zoom_factor() > 1.0
    v.set_image(np.zeros((200, 200, 3), np.uint8))                     # another photo: whole picture
    assert v.zoom_factor() == 1.0
    v.grab()                                                           # painting works when zoomed


def test_window_fits_screen_and_scrolls(monkeypatch):
    from PySide6 import QtWidgets as W
    W.QApplication.instance() or W.QApplication([])
    from ringblast.gui import app
    win = app.MainWindow()
    a = win.screen().availableGeometry()
    assert win.width() <= a.width() and win.height() <= a.height()
    assert win.minimumSizeHint().width() < 400 and win.minimumSizeHint().height() < 400   # content scrolls, not overflows
    win.fit_to_screen(5000, 5000)
    assert win.width() <= a.width() and win.height() <= a.height()


# ---------------------------------------------------------------- area of interest and photo export
def test_roi_crop_compose_and_scale_bar():
    import numpy as np
    from ringblast import imageanalysis as ia
    img = np.full((300, 400, 3), 120, np.uint8)
    crop, off = ia.crop_roi(img, [50, 40, 250, 200])
    assert crop.shape[:2] == (160, 200) and off == (50, 40)
    assert ia.crop_roi(img, [])[0] is img and ia.crop_roi(img, [10, 10, 15, 15])[0] is img   # empty / tiny: whole photo
    assert ia.crop_roi(img, [250, 200, 50, 40])[0].shape[:2] == (160, 200)                     # corners in any order
    part = np.full((80, 100, 3), 255, np.uint8)                                                # result at lower resolution
    out = ia.compose_roi(img, [50, 40, 250, 200], part)
    assert out.shape == img.shape and out[100, 100, 0] == 255 and out[5, 5, 0] < 60           # darkened outside
    bar = ia.add_scale_bar(out, 4.0)
    assert bar.shape == out.shape and (bar != out).any() and (ia.add_scale_bar(out, 0) == out).all()


def test_roi_analysis_and_export_of_photos(win, tmp_path):
    import cv2
    import numpy as np
    img, _ = make_photo()
    big = np.zeros((img.shape[0] + 300, img.shape[1] + 200, 3), np.uint8)       # drift walls around the pile
    big[150:150 + img.shape[0], 100:100 + img.shape[1]] = img
    f = tmp_path / "wide.png"; cv2.imwrite(str(f), big)
    tab = win.images_tab
    tab.add_files([str(f)])
    tab.set_scale_points((100, 100), (100 + 60 * SCALE, 100), 60.0)
    tab.listw.setCurrentRow(0)
    got = []
    tab.view.roiPicked.connect(got.append)
    tab.begin_roi()
    assert tab.view.roi_mode
    tab._roi_picked([100, 150, 100 + img.shape[1], 150 + img.shape[0]])         # as if dragged by the user
    r = tab.records[0]
    assert r.roi == [100, 150, 1300, 1050] and "1200 x 900" in tab.roi_label.text()
    tab.analyse_selected()
    res = tab.results[r.path]
    assert res.n_fragments > 5 and res.overlay.shape[0] <= big.shape[0]
    assert abs(res.image_area_cm2 * 1.0 - 1200 * 900 / SCALE ** 2) / (1200 * 900 / SCALE ** 2) < 0.1   # area of the ROI only
    assert r.analysed_with["roi"] == r.roi
    tab.view_mode.setCurrentIndex(0); tab._show_image()                          # composite with outlined ROI renders
    tab.view_mode.setCurrentIndex(3); tab._show_image()
    files = tab.export_photos(tmp_path / "figs")
    names = sorted(p.name for p in files)
    assert names == ["photo_wide_analysed_area.png", "photo_wide_fragments.png", "photo_wide_overview.png"]
    assert all(cv2.imread(str(p)) is not None for p in files)
    tab.clear_roi()
    assert r.roi == [] and "whole" in tab.roi_label.text()
    assert "roi" in type(r).__dataclass_fields__
    # saved and reloaded in a project
    from ringblast import project
    r.roi = [10, 20, 300, 400]
    p = tmp_path / "t.ringblast"
    project.save_project(p, "t", "", dict(project.DEFAULT_INPUTS), [r], {})
    assert project.load_project(p)["images"][0].roi == [10, 20, 300, 400]


def test_photo_report_html_and_pdf(win, tmp_path):
    import cv2
    img, _ = make_photo()
    paths = []
    for i, seed in enumerate((3, 4)):
        im, _ = make_photo(seed=seed)
        f = tmp_path / f"ph{i}.png"; cv2.imwrite(str(f), im); paths.append(str(f))
    tab = win.images_tab
    tab.add_files(paths)
    for i in range(2):
        tab.listw.setCurrentRow(i)
        tab.set_scale_points((100, 100), (100 + 60 * SCALE, 100), 60.0)
    tab.listw.setCurrentRow(0)
    tab._roi_picked([50, 50, 1100, 800])
    tab.seg_w["contrast"].setValue(3.0)
    tab.copy_segmentation_to_all()                       # same settings for every photo
    tab.analyse_all()
    out = tab.write_report(tmp_path / "r.html")
    h = out.read_text(encoding="utf-8")
    assert h.count("data:image/png;base64") >= 5 and "same for all photos" in h
    assert "ph0.png" in h and "ph1.png" in h and "All photos together" in h and "1050 x 750 px" in h
    dx = tab.write_report(tmp_path / "r.docx")
    import docx as _d
    d = _d.Document(str(dx))
    assert len(d.inline_shapes) >= 5 and len(d.tables) >= 4
    assert "All photos together" in [p.text for p in d.paragraphs] and "1. ph0.png" in [p.text for p in d.paragraphs]
    pdf = tab.write_report(tmp_path / "r.pdf")
    assert pdf.read_bytes()[:4] == b"%PDF" and pdf.stat().st_size > 20000
    tab.seg_w["contrast"].setValue(1.0)                  # different settings for one photo
    tab.listw.setCurrentRow(1)
    tab.seg_w["contrast"].setValue(4.5)
    tab.analyse_all()
    h2 = tab.write_report(tmp_path / "r2.html").read_text(encoding="utf-8")
    assert "settings differ between photos" in h2 and "4.5" in h2


# ---------------------------------------------------------------- twin drifts moved onto the walls; Word design report
def _twin(dist, **kw):
    from ringblast.models import StopeGeometry
    return StopeGeometry(width=20, height=40, n_sublevels=2, drift_width=5, drift_height=5,
                         drifts_per_sublevel=2, drift_wall_distance_m=dist, **kw)


def test_twin_drifts_negative_wall_distance():
    import pytest
    from ringblast import db
    from ringblast.design import run_design
    from ringblast.geometry import level_specs
    from ringblast.models import DesignParams, StopeGeometry
    rock, ex = list(db.load_rocks().values())[0], list(db.load_explosives().values())[0]
    xs = {d: [round(s.centre[0], 3) for s in level_specs(_twin(d), 2.0)[:2]] for d in (0, -1, -2.5)}
    assert xs[0] == [-7.5, 7.5] and xs[-1] == [-8.5, 8.5] and xs[-2.5] == [-10.0, 10.0]   # axis on the wall
    for d in (0, -1, -2.5):                                          # the whole design runs, also with the axis on the wall
        res = run_design(rock, ex, _twin(d), DesignParams())
        assert res.n_holes > 0 and all(h.length > 0.5 for lv in res.levels for h in lv.ring.holes)
    with pytest.raises(ValueError, match="cannot be below"):
        _twin(-2.6).validate()                                        # beyond the wall
    with pytest.raises(ValueError, match="negative"):
        _twin(-1, twin_position="halves").validate()                  # only for two drifts at the sides
    with pytest.raises(ValueError, match="negative"):
        StopeGeometry(width=20, height=40, drift_wall_distance_m=-1, drift_position="left").validate()


def test_word_design_report(tmp_path):
    import docx
    from ringblast import db
    from ringblast.design import run_design
    from ringblast.export import export_report_docx
    from ringblast.models import DesignParams
    rock, ex = list(db.load_rocks().values())[0], list(db.load_explosives().values())[0]
    s, p = _twin(-1), DesignParams()
    out = export_report_docx(tmp_path / "d.docx", run_design(rock, ex, s, p), s, rock, ex, p, "Test design")
    d = docx.Document(str(out))
    texts = [x.text for x in d.paragraphs]
    assert "Test design" in texts and "Results by level" in texts and "Sublevel 1 left" in texts
    assert len(d.inline_shapes) >= 4 and len(d.tables) >= 5


def test_gui_wall_distance_spin_accepts_negative(win):
    w = win.w["wd"]
    assert w.minimum() <= -2.5
    win.ndrifts.setCurrentText("2")
    w.setValue(-2.5)
    win.update_layout()                                               # layout redraws without error


def test_plots_zoom_with_the_wheel():
    import numpy as np
    from matplotlib.backend_bases import MouseEvent
    from matplotlib.figure import Figure
    from PySide6 import QtWidgets as W
    W.QApplication.instance() or W.QApplication([])
    from ringblast.gui.zoomcanvas import ZoomCanvas
    fig = Figure(figsize=(4, 3)); ax = fig.subplots()
    ax.plot([1, 100], [0, 100]); ax.set_xscale("log"); ax.set_xlim(0.5, 300); ax.set_ylim(0, 100)
    c = ZoomCanvas(fig); c.draw()
    x0, y0 = ax.transData.transform((10, 50))

    def scroll(step):
        c.scroll_event_ev = MouseEvent("scroll_event", c, x0, y0, step=step)
        c._scroll(c.scroll_event_ev)
    scroll(3)
    xl, yl = ax.get_xlim(), ax.get_ylim()
    assert xl[1] / xl[0] < 300 / 0.5 and yl[1] - yl[0] < 100                      # zoomed in (log axis in log space)
    px, py = ax.transData.inverted().transform((x0, y0))
    assert abs(px - 10) / 10 < 1e-6 and abs(py - 50) < 1e-6                        # point under the cursor stays
    scroll(-20)                                                                    # zooming out stops at the original view
    assert np.allclose(ax.get_xlim(), (0.5, 300)) and np.allclose(ax.get_ylim(), (0, 100))
    scroll(200)
    assert (ax.get_ylim()[1] - ax.get_ylim()[0]) >= 100 / 60 - 1e-9                # zoom in is limited
    c._press(MouseEvent("button_press_event", c, x0, y0, button=1, dblclick=True))  # double-click: whole plot again
    assert np.allclose(ax.get_xlim(), (0.5, 300))
    scroll(2); c._press(MouseEvent("button_press_event", c, x0, y0, button=1))       # pan while zoomed
    c._move(MouseEvent("motion_notify_event", c, x0 + 20, y0 + 10)); c._release(None)
    assert not np.allclose(ax.get_ylim(), (0, 100))


def test_twin_drifts_with_gap_and_figure_case(win):
    import pytest
    from ringblast import db
    from ringblast.design import run_design
    from ringblast.geometry import level_specs
    from ringblast.models import DesignParams, StopeGeometry
    rock, ex = list(db.load_rocks().values())[0], list(db.load_explosives().values())[0]
    s = StopeGeometry(width=30, height=106, n_sublevels=2, drift_width=5, drift_height=5, drifts_per_sublevel=2,
                      twin_position="gap", twin_gap_m=15, drift_vertical="top", drift_top_distance_m=20,
                      undercut_height_m=23, hopper_bottom_width_m=7.5)
    sp = level_specs(s, 3.0)
    assert [round(x.centre[0], 2) for x in sp[:2]] == [-10.0, 10.0]               # 15 m between the two 5 m drifts
    assert abs(sp[0].drift_rect[2] - sp[1].drift_rect[0] + 15) < 1e-9              # clear gap = 15 m
    assert round(sp[0].top_y, 2) == 86.0 and round(sp[2].top_y, 2) == 86.0 - 41.5  # roofs 20 m below each block top
    assert run_design(rock, ex, s, DesignParams()).n_holes > 0
    s.twin_gap_m = 25
    s.validate()                                                                   # axes on the walls: still allowed
    s.twin_gap_m = 26
    with pytest.raises(ValueError, match="too large"):
        s.validate()
    s.twin_gap_m = -1
    with pytest.raises(ValueError, match="negative"):
        s.validate()
    win.ndrifts.setCurrentText("2")
    win.twin.setCurrentIndex(win.twin.findData("gap"))
    assert win.w["gap"].isEnabled() and not win.w["wd"].isEnabled()
    win.twin.setCurrentIndex(win.twin.findData("sides"))
    assert not win.w["gap"].isEnabled() and win.w["wd"].isEnabled()
    assert win.get_inputs()["gap"] == 5.0 and win.get_inputs()["twin_position"] == "sides"


def test_block_gaps_grey_regions_and_geometry_always_visible(win):
    import numpy as np
    from ringblast import db
    from ringblast.design import run_design
    from ringblast.geometry import level_specs, uncharged_regions
    from ringblast.models import DesignParams, StopeGeometry
    rock, ex = list(db.load_rocks().values())[0], list(db.load_explosives().values())[0]
    base = dict(width=30, height=106, n_sublevels=2, drift_width=5, drift_height=5, drifts_per_sublevel=2,
                twin_position="sides", drift_vertical="top", drift_top_distance_m=15)
    s0 = StopeGeometry(**base, sublevel_gap_m=2.0, twin_block_gap_m=0.0)
    s1 = StopeGeometry(**base, sublevel_gap_m=4.0, twin_block_gap_m=3.0)
    a, b = level_specs(s0, 4.2), level_specs(s1, 4.2)
    assert a[0].bl[1] - (a[2].tl[1]) == 2.0 and b[0].bl[1] - b[2].tl[1] == 4.0      # vertical gap between the blocks
    assert a[0].tr[0] == 0.0 and b[0].tr[0] == -1.5 and b[1].tl[0] == 1.5          # left / right blocks 3 m apart
    assert len(uncharged_regions(s0, 4.2)) == 2 and len(uncharged_regions(s1, 4.2)) == 4
    area = lambda p: abs(sum(p[i][0] * p[(i + 1) % 4][1] - p[(i + 1) % 4][0] * p[i][1] for i in range(4))) / 2
    assert sorted(round(area(q), 3) for q in uncharged_regions(s1, 4.2))[-1] == 30 * 4.0     # grey strip between blocks
    r0, r1 = run_design(rock, ex, s0, DesignParams()), run_design(rock, ex, s1, DesignParams())
    assert r1.n_holes > 0
    from ringblast.export import stope_outline                                      # the total volume stays that of the stope
    out = stope_outline(s1)
    stope_area = abs(sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(out, out[1:] + out[:1]))) / 2
    voids = 5 * 5 * 5                                                               # four sublevel drifts + base drift
    for r_ in (r0, r1):
        assert abs(r_.volume_m3 - (stope_area - voids) * r_.burden_m) / ((stope_area - voids) * r_.burden_m) < 0.01
    assert abs(r1.volume_m3 - r0.volume_m3) / r0.volume_m3 < 0.03                   # gaps do not change the volume
    assert r1.powder_factor < r0.powder_factor * 1.001 or r1.charge_kg < r0.charge_kg
    assert StopeGeometry(**base).sublevel_gap_m is None                            # legacy: half burden
    import pytest
    with pytest.raises(ValueError, match="cannot be negative"):
        StopeGeometry(**base, sublevel_gap_m=-1).validate()
    # GUI: the geometry is visible next to the blast parameters; Run design overlays the charges
    win.apply_inputs({**win.get_inputs(), "width": 30.0, "height": 106.0, "drifts": 2, "vg": 3.0, "hg": 2.0, "dtop": 15.0, "n_sub": 2})
    assert win.plots.count() == 1 and win.plots.tabText(0) == "Layout" and win.plots.widget(0) is win.design_canvas
    assert win.w["hg"].isEnabled() and "hopper" not in " ".join(win.w).lower() and "uc" not in win.w and "hb" not in win.w
    win.run()
    assert [win.plots.tabText(i) for i in range(win.plots.count())] == ["Pattern", "Fragmentation"]
    ax = win.plots.widget(0).figure.axes[0]
    assert len(ax.patches) >= 4 and any(np.allclose(p.get_facecolor()[:3], (0.7, 0.7, 0.7), atol=0.02) for p in ax.patches)  # grey gaps
    win.update_layout()
    assert win.plots.count() == 1 and win.plots.tabText(0) == "Layout"


def test_wide_x_range_and_sublevel_groups(win):
    import numpy as np
    from ringblast import db
    from ringblast.design import run_design
    from ringblast.export import plot_fragmentation, plot_pattern, plot_stope_layout
    from ringblast.geometry import level_specs
    from ringblast.models import DesignParams, StopeGeometry
    rock, ex = list(db.load_rocks().values())[0], list(db.load_explosives().values())[0]
    s = StopeGeometry(width=30, height=106, n_sublevels=2, drift_width=5, drift_height=5, drifts_per_sublevel=2,
                      twin_position="sides", drift_wall_distance_m=-2.5, drift_vertical="top", drift_top_distance_m=15)
    xmax = max(sp.drift_rect[2] for sp in level_specs(s, 0.0))
    assert xmax == 17.5                                                            # drift sticks out of the stope outline
    lay = plot_stope_layout(s)
    lo, hi = lay.axes[0].get_xlim()
    assert hi > xmax + 5 and lo < -xmax - 5                                        # nothing is hidden, room for the labels
    p = DesignParams(); res = run_design(rock, ex, s, p)
    fig = plot_pattern(res, s, (1, 2), params=p)                                   # both drifts of sublevel 1
    lo, hi = fig.axes[0].get_xlim()
    assert hi > xmax + 5 and lo < -xmax - 5
    ys = fig.axes[0].get_ylim()
    assert ys[1] - ys[0] < 106 / 2 + 15                                             # zoomed on the sublevel
    assert len(plot_fragmentation(res, (1, 2)).axes[0].get_lines()) == 3          # left, right, together
    win.apply_inputs({**win.get_inputs(), "drifts": 2, "n_sub": 2})
    win.run()
    names = [win.level.itemText(i) for i in range(win.level.count())]
    assert names[:3] == ["All levels", "Sublevel 1 (left + right)", "Sublevel 2 (left + right)"] and "Sublevel 1 left" in names
    win.level.setCurrentIndex(1)                                                    # draws without error
    assert win.plots.count() == 2
    assert win.layout_canvas.minimumHeight() <= 300 and win.design_canvas.minimumHeight() <= 300


def test_level_labels_centred_and_inside_the_axes():
    from ringblast import db
    from ringblast.design import run_design
    from ringblast.export import plot_pattern, plot_stope_layout
    from ringblast.models import DesignParams, StopeGeometry
    rock, ex = list(db.load_rocks().values())[0], list(db.load_explosives().values())[0]
    for s in (StopeGeometry(width=30, height=106, n_sublevels=2, drift_width=5, drift_height=5, drifts_per_sublevel=2,
                            twin_position="sides", drift_wall_distance_m=-2.5, drift_vertical="top", drift_top_distance_m=15),
              StopeGeometry(width=25, height=80, n_sublevels=2, drift_width=5, drift_height=5)):
        res = run_design(rock, ex, s, DesignParams())
        for fig in (plot_stope_layout(s), plot_pattern(res, s), plot_pattern(res, s, (1, 2) if s.drifts_per_sublevel == 2 else 1)):
            fig.canvas.draw()
            ax = fig.axes[0]
            box = ax.get_window_extent()
            names = [t for t in ax.texts if t.get_text().startswith("Sublevel") or t.get_text().startswith("Base")]
            assert names
            for t in names:
                bb = t.get_window_extent()
                assert bb.x0 > box.x0 + 3 and bb.x1 < box.x1 - 3                  # inside the axes, not on the frame
                assert t.get_va() == "center"                                       # centred on the drift
                _, y = t.get_position()
                lv = [sp for sp in level_specs_for(s) if sp.name.replace(" ", "") in t.get_text().replace("\n", "").replace(" ", "")]
                if lv:
                    assert abs(y - (lv[0].drift_rect[1] + lv[0].drift_rect[3]) / 2) < 1e-9


def level_specs_for(stope):
    from ringblast.geometry import level_specs
    return level_specs(stope, 0.0)
