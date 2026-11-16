import os
import pytest
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")


def test_gui_smoke():
    from PySide6 import QtWidgets as W
    from ringblast.gui.app import MainWindow
    app = W.QApplication.instance() or W.QApplication([])
    w = MainWindow()
    w.w["c"].setValue(0.8)
    w.rock.setCurrentText("Limestone")
    w.run()
    assert w.result is not None and len(w.result.levels) == 3 and w.result.levels[0].n_holes == 20
    assert f"TOTAL: holes = {w.result.n_holes}" in w.summary.toPlainText()


def test_gui_side_drift_and_level_selector():
    from PySide6 import QtWidgets as W
    from ringblast.gui.app import MainWindow
    app = W.QApplication.instance() or W.QApplication([])
    w = MainWindow()
    w.pos.setCurrentText("left")
    w.run()
    assert [l.spec.position for l in w.result.levels] == ["left", "left", "center"]
    w.level.setCurrentIndex(3)                       # Base
    assert w.plots.count() == 2


def test_gui_layout_drawn_before_run():
    from PySide6 import QtWidgets as W
    from ringblast.gui.app import MainWindow
    app = W.QApplication.instance() or W.QApplication([])
    w = MainWindow()
    assert w.result is None and w.plots.count() == 0 and w.tabs.tabText(0) == "Stope layout" and w.tabs.tabText(1) == "Blast design"
    assert w.run_btn.isEnabled() and "Layout OK" in w.layout_status.text()
    w.w["n_sub"].setValue(4)                                   # changing geometry redraws, no calculation
    assert w.result is None and w.plots.count() == 0
    w.w["width"].setValue(4)                                   # drift wider than the stope
    assert not w.run_btn.isEnabled() and "not valid" in w.layout_status.text()
    w.w["width"].setValue(25)
    w.run()
    assert w.plots.count() == 2 and w.plots.tabText(0) == "Pattern"
    w.w["height"].setValue(100)                                # geometry change invalidates results
    assert w.result is None and not w.btn_export.isEnabled() and w.plots.count() == 0
