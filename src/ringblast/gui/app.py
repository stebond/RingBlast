"""PySide6 front end.  All numerics live in the core package; this module only collects inputs,
calls run_design() and shows / exports the results.   Run:  ringblast-gui"""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6 import QtCore as C
from PySide6 import QtWidgets as W
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as Canvas
from matplotlib.figure import Figure

from . import tips
from .. import db, paths, plotstyle, project
from ..burden import METHODS
from ..design import run_design
from ..export import (export_dxf, export_hole_csv, export_json, export_report_html,
                      plot_fragmentation, plot_pattern, plot_stope_layout)
from ..models import DesignParams, MissingInput, StopeGeometry
from ..project import DEFAULT_INPUTS as D
from .data_tab import DataTab
from .images_tab import ImagesTab
from .settings_tab import SettingsTab

ROOT = paths.resource_root()                         # bundled resources (launcher icons, ...)
WORK = paths.app_dir()                               # folder shown to the user (projects/, output/)


def _spin(value, lo, hi, step=0.1, dec=2):
    s = W.QDoubleSpinBox()
    s.setDecimals(dec)
    s.setRange(lo, hi)
    s.setSingleStep(step)
    s.setValue(value)
    return s


class MainWindow(W.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("RingBlast - ring/fan blast design")
        self.setWindowIcon(app_icon())
        plotstyle.load()
        self.result = None
        self._ctx = None
        self.project_id = project.new_project_id()
        self.save_warnings: list[str] = []
        self.rocks, self.expl = db.load_rocks(), db.load_explosives()

        # ---------------------------------------------------------- design tab
        self.rock = W.QComboBox()
        self.expc = W.QComboBox()
        self.booster = W.QComboBox()      # bottom charge; first entry = none
        self.method = W.QComboBox()
        for m in METHODS.values():
            self.method.addItem(f"{m.key}  ({m.reference})", m.key)
        self.pos = W.QComboBox(); self.pos.addItems(["center", "left", "right"])
        self.vpos = W.QComboBox(); self.vpos.addItems(["top", "center"])
        self.ndrifts = W.QComboBox(); self.ndrifts.addItems(["1", "2"])
        self.twin = W.QComboBox(); self.twin.addItem("at the walls (sides)", "sides")
        self.twin.addItem("centre of each half", "halves")
        self.show_zones = W.QCheckBox("Show fragmentation zones (green circles)"); self.show_zones.setChecked(True)
        self.show_zones.toggled.connect(lambda *_: self._show_plots())
        self.log_x = W.QCheckBox("Logarithmic size axis (fragmentation plot)"); self.log_x.setChecked(True)
        self.log_x.toggled.connect(lambda *_: self._show_plots())
        self.base = W.QCheckBox("Include base drift (bottom of the hopper)")
        self.level = W.QComboBox(); self.level.addItem("All levels", None)
        self.level.currentIndexChanged.connect(self._show_plots)
        self.w = {
            "width": _spin(D["width"], 3, 200, 0.5), "height": _spin(D["height"], 5, 500, 1),
            "n_sub": _spin(D["n_sub"], 1, 20, 1, 0), "dw": _spin(D["dw"], 1, 20, 0.5),
            "dh": _spin(D["dh"], 1, 20, 0.5), "angle": _spin(D["angle"], 30, 80, 1, 0),
            "d": _spin(D["d"], 30, 300, 1, 0), "sb": _spin(D["sb"], 0.8, 2.0, 0.05),
            "f": _spin(D["f"], 0.3, 1.0, 0.05), "c": _spin(D["c"], 0.2, 1.5, 0.05),
            "A": _spin(D["A"], 0.5, 20, 0.5), "zone": _spin(D["zone"], 1, 20, 0.5),
            "manual": _spin(D["manual"], 0, 20, 0.1), "wd": _spin(D["wd"], 0, 20, 0.5),
            "dtop": _spin(D["dtop"], 0, 200, 0.5), "arch": _spin(D["arch"], 0, 100, 0.5),
            "bcl": _spin(D["bcl"], 0.1, 5, 0.1),
        }
        geometry = W.QFormLayout()
        for label, w in [("Stope width L (m)", self.w["width"]), ("Stope height H (m)", self.w["height"]),
                         ("Sublevels (above the base)", self.w["n_sub"]), ("Include base", self.base),
                         ("Drifts per sublevel", self.ndrifts),
                         ("One drift: horizontal position", self.pos),
                         ("Two drifts: positions (symmetric)", self.twin),
                         ("Side drift: distance from wall (m)", self.w["wd"]),
                         ("Sublevel drift position (vertical)", self.vpos),
                         ("Drift roof: distance from block top (m)", self.w["dtop"]),
                         ("Roof arch rise (m, 0 = flat)", self.w["arch"]), ("Drift width (m)", self.w["dw"]),
                         ("Drift height (m)", self.w["dh"]), ("Hopper wall angle (deg)", self.w["angle"])]:
            geometry.addRow(label, w)
        box1 = W.QGroupBox("Stope geometry"); box1.setLayout(geometry)
        self.layout_status = W.QLabel(); self.layout_status.setWordWrap(True)
        self.layout_fig = Figure(figsize=(4.6, 6.4))
        self.layout_canvas = Canvas(self.layout_fig)
        lleft = W.QWidget(); lv = W.QVBoxLayout(lleft)
        lv.addWidget(box1); lv.addWidget(self.layout_status); lv.addStretch(1)
        layout_tab = W.QSplitter(); layout_tab.addWidget(lleft); layout_tab.addWidget(self.layout_canvas)
        layout_tab.setStretchFactor(1, 3)

        design = W.QFormLayout()
        for label, w in [("Rock", self.rock), ("Explosive (column)", self.expc), ("Booster (bottom charge)", self.booster),
                         ("Booster length BCL (m)", self.w["bcl"]), ("Burden method", self.method),
                         ("Hole diameter (mm)", self.w["d"]), ("S/B", self.w["sb"]),
                         ("Fixation f", self.w["f"]), ("Langefors c (kg/m3)", self.w["c"]),
                         ("Rock factor A", self.w["A"]), ("Zone thickness R (m)", self.w["zone"]),
                         ("Manual burden (m, 0 = off)", self.w["manual"])]:
            design.addRow(label, w)
        self.run_btn = W.QPushButton("Run design"); self.run_btn.clicked.connect(self.run)
        self.btn_export = W.QPushButton("Export DXF / CSV / JSON / HTML..."); self.btn_export.clicked.connect(self.export)
        self.btn_export.setEnabled(False)
        design.addRow("Show level", self.level)
        design.addRow(self.show_zones)
        design.addRow(self.log_x)
        design.addRow(self.run_btn); design.addRow(self.btn_export)
        box2 = W.QGroupBox("Blast parameters"); box2.setLayout(design)
        self.geom_label = W.QLabel(); self.geom_label.setWordWrap(True)
        dleft = W.QWidget(); dv = W.QVBoxLayout(dleft)
        dv.addWidget(self.geom_label); dv.addWidget(box2); dv.addStretch(1)

        self.plots = W.QTabWidget()                       # Pattern / Fragmentation after "Run design"
        self.summary = W.QPlainTextEdit(readOnly=True)
        right = W.QSplitter(C.Qt.Vertical); right.addWidget(self.plots); right.addWidget(self.summary)
        right.setStretchFactor(0, 3)
        design_tab = W.QSplitter(); design_tab.addWidget(dleft); design_tab.addWidget(right)
        design_tab.setStretchFactor(1, 3)

        # ---------------------------------------------------------- other tabs
        self.rock_tab = DataTab("rocks", "Rock properties used by the burden methods and Kuz-Ram.")
        self.expl_tab = DataTab("explosives", "Explosive properties (density, energy, VOD, relative weight strength).")
        self.images_tab = ImagesTab(lambda: self.result)
        self.settings_tab = SettingsTab()
        self.rock_tab.changed.connect(self.reload_databases)
        self.expl_tab.changed.connect(self.reload_databases)
        self.settings_tab.styleChanged.connect(self.redraw_plots)

        self.tabs = W.QTabWidget()
        for wdg, title in [(layout_tab, "Stope layout"), (design_tab, "Blast design"), (self.rock_tab, "Rock properties"),
                           (self.expl_tab, "Explosives"), (self.images_tab, "Muck-pile photos"),
                           (self.settings_tab, "Settings")]:
            self.tabs.addTab(wdg, title)

        # ---------------------------------------------------------- project bar
        self.proj_name = W.QLineEdit(); self.proj_name.setPlaceholderText("Project name")
        self.proj_notes = W.QPlainTextEdit(); self.proj_notes.setMaximumHeight(52)
        self.proj_notes.setPlaceholderText("Project notes (site, blast number, remarks...)")
        bar = W.QHBoxLayout()
        bar.addWidget(self.proj_name, 1); bar.addWidget(self.proj_notes, 2)
        for text, fn, tip in [("Open project...", self.open_project, "Load a saved project"),
                              ("Save project...", self.save_project,
                               "Save everything in one file: inputs, rock/explosive rows used, the photos and their measurements"),
                              ("Reset", self.reset_all,
                               "Back to default inputs; clears name, notes and photos (the database tables "
                               "and the plot settings have their own reset buttons)")]:
            b = W.QPushButton(text); b.setToolTip(tip); b.clicked.connect(lambda _=False, f=fn: f())
            bar.addWidget(b)
        central = W.QWidget(); cv = W.QVBoxLayout(central)
        cv.addLayout(bar); cv.addWidget(self.tabs, 1)
        self.setCentralWidget(central)
        self.resize(1300, 860)

        # ---------------------------------------------------------- tooltips
        w = self.w
        tips.set_all([
            (self.rock, "Rock of the stope. Its density, strength and fragmentation energy feed the burden and Kuz-Ram calculations. Edit the list in the Rock properties tab."),
            (self.booster, "Optional bottom charge (booster) placed at the toe of every charged hole. With a booster the uniformity index uses the real BCL and CCL (Cunningham 1983), the RWS is the mean of booster and column weighted on the length each occupies, and the charge mass is the sum of the two. (none) = a single explosive."),
            (w["bcl"], "Booster length BCL (m) at the toe of each hole; the rest of the charged length is the column (CCL). Ignored when no booster is chosen."),
            (self.expc, "Explosive used in the holes: density, energy and relative weight strength. Edit the list in the Explosives tab."),
            (self.method, "Method used to compute the burden B. Some methods need rock or explosive properties that must be filled in the tables."),
            (self.vpos, "Vertical position of the sublevel drifts: 'top' = roof at the top of the block (minus the distance below); 'center' = drift centred in the sublevel. The fan then also covers the rock above the drift."),
            (w["dtop"], "Distance between the top of the sublevel block and the drift roof (m). 0 = drift at the top. Only used when the position is 'top'."),
            (w["arch"], "Arched roof of the stope: distance (m) between the top edge of the rectangle and the crown of the circular arc. 0 = flat roof (rectangle). Applies to the top sublevel; maximum half the stope width."),
            (self.ndrifts, "One drift per sublevel, or two symmetric drifts about the stope axis; each of the two fires one half of the block (the base drift stays single, at the bottom centre)."),
            (self.twin, "Two drifts: flush with the walls (or at the wall distance below), or at the centre of each half of the stope."),
            (self.log_x, "Logarithmic scale for the size axis of the fragmentation plot (default). Untick to use a linear scale. Does not change any result."),
            (self.show_zones, "Draw or hide the circles that bound the fragmentation calculation zones in the pattern plot. Does not change any result."),
            (self.pos, "Where the sublevel drifts are: centre of the stope, or against the left / right wall. The base drift is always at the bottom centre."),
            (self.base, "Adds the base drift at the bottom of the hopper, which fires the trapezoidal block above it."),
            (self.level, "Show the pattern and fragmentation of one level, or of all levels together."),
            (w["width"], "Width L of the stope section (m)."), (w["height"], "Total height H of the stope (m)."),
            (w["n_sub"], "Number of sublevel drifts above the base. Each fires a rectangular block with its own ring."),
            (w["dw"], "Width of the drift section (m)."), (w["dh"], "Height of the drift section (m)."),
            (w["angle"], "Inclination of the sloping sides of the base trapezoid (hopper walls), in degrees."),
            (w["wd"], "Side drifts only: gap between the drift and the stope wall (m). 0 = flush with the wall."),
            (w["d"], "Diameter of the drill holes (mm)."),
            (w["sb"], "Spacing-to-burden ratio S/B. The actual spacing is adjusted so that the ring closes exactly on the corners."),
            (w["f"], "Fixation factor f of the Langefors-Kihlstrom formula (about 0.65 for inclined / fan holes)."),
            (w["c"], "Rock constant c (m) of the Langefors-Kihlstrom formula, typically 0.3 to 1.0."),
            (w["A"], "Kuz-Ram rock factor A (about 8-12 for medium rock). It scales the predicted fragment size."),
            (w["zone"], "Radial thickness R (m) of the annular zones around the fan centre, used to predict fragmentation with distance from the drift."),
            (w["manual"], "If larger than 0, this burden (m) is used instead of the selected method."),
            (self.run_btn, "Computes the holes, charging and fragmentation for all levels with the current inputs."),
            (self.btn_export, "Writes the DXF drawing, the hole table (CSV), the JSON data and the HTML report. Available after Run design."),
            (self.proj_name, "Name of the project; it is used in file names and reports."),
            (self.proj_notes, "Free notes: site, blast number, remarks."),
        ])
        tips.by_text(self, {"Open project...": "Open a saved project (*.ringblast), with its photos and settings.",
                            "Reset": "Back to default inputs; clears name, notes and photos. The data tables and plot settings have their own reset buttons."})

        # ---------------------------------------------------------- Help menu
        help_menu = self.menuBar().addMenu("&Help")
        act_manual = help_menu.addAction("User manual"); act_manual.setShortcut("F1")
        act_manual.triggered.connect(self.show_manual)
        help_menu.addSeparator()
        act_about = help_menu.addAction("About RingBlast..."); act_about.triggered.connect(self.show_about)
        self._manual = None

        # ---------------------------------------------------------- wiring
        for w in list(self.w.values())[:5] + [self.w["angle"], self.w["wd"], self.w["dtop"], self.w["arch"]]:
            w.valueChanged.connect(self.update_layout)
        self.pos.currentIndexChanged.connect(self.update_layout)
        self.vpos.currentIndexChanged.connect(self.update_layout)
        self.ndrifts.currentIndexChanged.connect(self.update_layout)
        self.twin.currentIndexChanged.connect(self.update_layout)
        self.ndrifts.currentIndexChanged.connect(self._drift_controls)
        self.vpos.currentIndexChanged.connect(lambda *_: self.w["dtop"].setEnabled(self.vpos.currentText() == "top"))
        self.base.toggled.connect(self.update_layout)
        self.apply_inputs(D, redraw=False)
        self.reload_databases(keep=False)
        self.update_layout()

    # ================================================================== help
    def show_manual(self):
        from .help import ManualDialog
        if self._manual is None:
            self._manual = ManualDialog(self, self.windowIcon())
        self._manual.show(); self._manual.raise_(); self._manual.activateWindow()

    def show_about(self):
        from .help import AboutDialog
        AboutDialog(self, self.windowIcon()).exec()

    # ================================================================== state (project / reset)
    def get_inputs(self) -> dict:
        w = self.w
        return {"rock": self.rock.currentText(), "explosive": self.expc.currentText(),
                "booster": self.booster.currentText() if self.booster.currentIndex() > 0 else "",
                "burden_method": self.method.currentData(), "drift_position": self.pos.currentText(),
                "drift_vertical": self.vpos.currentText(), "drifts": int(self.ndrifts.currentText()),
                "twin_position": self.twin.currentData(), "show_zones": self.show_zones.isChecked(), "log_x": self.log_x.isChecked(),
                "base_drift": self.base.isChecked(), **{k: w[k].value() for k in D if k in w}}

    def apply_inputs(self, d: dict, redraw: bool = True):
        widgets = [self.rock, self.expc, self.booster, self.method, self.pos, self.vpos, self.ndrifts, self.twin, self.show_zones, self.log_x,
                   self.base, *self.w.values()]
        for x in widgets:
            x.blockSignals(True)
        try:
            for k, wd in self.w.items():
                wd.setValue(float(d.get(k, D[k])))
            b = d.get("booster", "")
            self.booster.setCurrentIndex(max(self.booster.findText(b), 0) if b else 0)
            self.pos.setCurrentText(d["drift_position"])
            self.vpos.setCurrentText(d["drift_vertical"])
            self.ndrifts.setCurrentText(str(int(d["drifts"])))
            self.twin.setCurrentIndex(max(self.twin.findData(d["twin_position"]), 0))
            self.show_zones.setChecked(bool(d["show_zones"]))
            self.log_x.setChecked(bool(d.get("log_x", True)))
            self.base.setChecked(bool(d["base_drift"]))
            i = self.method.findData(d["burden_method"])
            self.method.setCurrentIndex(max(i, 0))
            for combo, key in ((self.rock, "rock"), (self.expc, "explosive")):
                if combo.findText(d[key]) >= 0:
                    combo.setCurrentText(d[key])
        finally:
            for x in widgets:
                x.blockSignals(False)
        self._drift_controls()
        if redraw:
            self.update_layout()

    def reload_databases(self, keep: bool = True):
        """Refill the rock / explosive lists after the tables changed."""
        cur = (self.rock.currentText(), self.expc.currentText()) if keep else (D["rock"], D["explosive"])
        self.rocks, self.expl = db.load_rocks(), db.load_explosives()
        for combo, names, c in ((self.rock, sorted(self.rocks), cur[0]), (self.expc, list(self.expl), cur[1])):
            combo.blockSignals(True)
            combo.clear()
            combo.addItems(names)
            if c in names:
                combo.setCurrentText(c)
            combo.blockSignals(False)
        curb = self.booster.currentText() if self.booster.currentIndex() > 0 else ""
        self.booster.blockSignals(True)
        self.booster.clear()
        self.booster.addItems(["(none)", *self.expl])
        self.booster.setCurrentIndex(max(self.booster.findText(curb), 0) if curb else 0)
        self.booster.blockSignals(False)
        if db.ROW_ERRORS:
            self.summary.setPlainText("Database warnings:\n" + "\n".join(db.ROW_ERRORS))

    def _used_rows(self) -> dict:
        """Rows stored in a project: everything the user added/modified plus the items in use."""
        out = {}
        used = {"rocks": {self.rock.currentText()},
                "explosives": {self.expc.currentText(), self.booster.currentText()}}
        for kind in ("rocks", "explosives"):
            rows = db.effective_rows(kind)
            out[kind] = [r for r in rows if db.row_status(kind, r) != "builtin" or r["name"] in used[kind]]
        return out

    def save_project_to(self, path) -> Path:
        """Write the single project file (inputs, database rows, photos, measurements)."""
        out, self.save_warnings = project.save_project(
            path, self.proj_name.text().strip(), self.proj_notes.toPlainText(), self.get_inputs(),
            self.images_tab.records, self._used_rows(), self.images_tab.fragment_sizes(), self.project_id)
        return out

    def load_project_from(self, path) -> list[str]:
        data = project.load_project(path)
        msgs = []
        for kind, tab in (("rocks", self.rock_tab), ("explosives", self.expl_tab)):
            msgs += db.import_rows(kind, data["database"].get(kind, []))
            tab.reload()
        self.reload_databases(keep=False)
        self.project_id = data["project_id"]
        self.proj_name.setText(data["name"])
        self.proj_notes.setPlainText(data["notes"])
        self.apply_inputs(data["inputs"], redraw=False)
        self.images_tab.set_records(data["images"], data["fragment_sizes"])
        self.update_layout()
        return msgs

    def _project_dir(self) -> Path:
        d = WORK / "projects"
        d.mkdir(exist_ok=True)
        return d

    def save_project(self):
        name = self.proj_name.text().strip() or "project"
        path, _ = W.QFileDialog.getSaveFileName(self, "Save project", str(self._project_dir() / (name + project.EXTENSION)),
                                                f"RingBlast project (*{project.EXTENSION})")
        if path:
            if not path.endswith(project.EXTENSION):
                path += project.EXTENSION
            try:
                self.save_project_to(path)
            except OSError as e:
                W.QMessageBox.warning(self, "Save project", str(e))
                return
            self.statusBar().showMessage(f"Project saved: {path}", 8000)
            if self.save_warnings:
                W.QMessageBox.warning(self, "Save project", "\n".join(self.save_warnings))

    def open_project(self):
        path, _ = W.QFileDialog.getOpenFileName(self, "Open project", str(self._project_dir()),
                                                f"RingBlast project (*{project.EXTENSION} *.json)")
        if path:
            try:
                msgs = self.load_project_from(path)
            except (OSError, ValueError, KeyError) as e:
                W.QMessageBox.warning(self, "Open project", str(e))
                return
            if msgs:
                W.QMessageBox.information(self, "Database", "\n".join(msgs))

    def reset_all(self, confirm: bool = True):
        if confirm and W.QMessageBox.question(
                self, "Reset", "Reset all inputs to the default values and clear the project name, notes "
                "and photos?") != W.QMessageBox.Yes:
            return
        self.project_id = project.new_project_id()
        self.proj_name.clear()
        self.proj_notes.clear()
        self.apply_inputs(D, redraw=False)
        self.images_tab.clear()
        self.update_layout()

    # ================================================================== calculation
    def _inputs(self):
        w = self.w
        n = int(w["n_sub"].value())
        stope = StopeGeometry(w["width"].value(), w["height"].value(), n,
                              w["dw"].value(), w["dh"].value(), w["angle"].value(),
                              drift_position=self.pos.currentText(),
                              drift_wall_distance_m=w["wd"].value(),
                              drifts_per_sublevel=int(self.ndrifts.currentText()),
                              twin_position=self.twin.currentData(),
                              drift_vertical=self.vpos.currentText(), drift_top_distance_m=w["dtop"].value(),
                              roof_arch_rise_m=w["arch"].value(),
                              base_drift=self.base.isChecked())
        manual = w["manual"].value()
        p = DesignParams(hole_diameter_mm=w["d"].value(), burden_method="manual" if manual > 0 else self.method.currentData(),
                         burden_manual_m=manual or None, sb_ratio=w["sb"].value(), fixation=w["f"].value(),
                         c_langefors=w["c"].value(), rock_factor_A=w["A"].value(),
                         zone_length_m=w["zone"].value(), booster_length_m=w["bcl"].value())
        if self.booster.currentIndex() > 0:
            p.booster = self.expl[self.booster.currentText()]
        try:
            rock, ex = self.rocks[self.rock.currentText()], self.expl[self.expc.currentText()]
        except KeyError:
            raise ValueError("choose a valid rock and explosive (see the Rock properties / Explosives tabs)")
        return rock, ex, stope, p

    def _drift_controls(self, *_):
        two = self.ndrifts.currentText() == "2"
        self.pos.setEnabled(not two)
        self.twin.setEnabled(two)

    def _draw_layout(self):
        _, _, stope, _ = self._inputs()
        stope.validate()
        from ..geometry import level_specs
        level_specs(stope, 0.0)
        plot_stope_layout(stope, self.layout_fig)
        self.layout_canvas.draw_idle()

    def update_layout(self):
        """Redraw the stope from the geometry inputs only (no blast calculation)."""
        self.result = None
        self.btn_export.setEnabled(False)
        self.plots.clear()
        try:
            self._draw_layout()
            self.run_btn.setEnabled(True)
            _, _, stope, _ = self._inputs()
            self.layout_status.setText("Layout OK. Go to the Blast design tab to choose the explosive and run the calculation.")
            self.geom_label.setText(f"Stope {stope.width:g} x {stope.height:g} m, {stope.n_sublevels} sublevels"
                                    + (" + base drift" if stope.base_drift else "")
                                    + f", drifts {stope.drift_width:g} x {stope.drift_height:g} m "
                                      f"({self.pos.currentText()}).")
            self.summary.setPlainText("Choose rock, explosive and parameters, then press \"Run design\".")
        except ValueError as e:
            self.layout_fig.clear()
            self.layout_canvas.draw_idle()
            self.run_btn.setEnabled(False)
            self.layout_status.setText(f"Layout not valid: {e}")
            self.geom_label.setText("The stope layout is not valid: fix it in the Stope layout tab.")
            self.summary.setPlainText(f"Layout not valid: {e}")
        self.images_tab.refresh()

    def redraw_plots(self):
        """The plot style changed: redraw everything that is on screen."""
        try:
            self._draw_layout()
        except ValueError:
            pass
        if self.result is not None:
            cur = self.plots.currentIndex()
            self._show_plots()
            self.plots.setCurrentIndex(max(0, min(cur, self.plots.count() - 1)))
        self.images_tab.refresh()

    def run(self):
        try:
            rock, ex, stope, p = self._inputs()
            self.result = run_design(rock, ex, stope, p)
            self._ctx = (rock, ex, stope, p)
        except (MissingInput, ValueError, RuntimeError) as e:
            W.QMessageBox.warning(self, "Input problem", str(e))
            return
        r = self.result
        self.level.blockSignals(True)
        self.level.clear()
        self.level.addItem("All levels", None)
        for lv in r.levels:
            self.level.addItem(lv.spec.name, lv.spec.index)
        self.level.blockSignals(False)
        lines = [f"B = {r.burden_m:.2f} m   S = {r.spacing_m:.2f} m", ""]
        for lv in r.levels:
            lines.append(f"{lv.spec.name:11s} ({lv.spec.position:6s}) holes {lv.n_holes:3d}  "
                         f"drilled {lv.drilled_length_m:7.1f} m  charge {lv.charge_kg:6.0f} kg  "
                         f"PF {lv.powder_factor:.2f}  mean size {lv.weighted_mean_size_cm:.1f} cm")
        lines += ["", f"TOTAL: holes = {r.n_holes}", f"drilled = {r.drilled_length_m:.1f} m",
                  f"charge = {r.charge_kg:.0f} kg", f"powder factor = {r.powder_factor:.2f} kg/m3",
                  f"weighted mean size = {r.weighted_mean_size_cm:.1f} cm", ""]
        lines += [f"warning: {x}" for x in r.warnings]
        self.summary.setPlainText("\n".join(lines))
        self._show_plots()
        self.btn_export.setEnabled(True)
        self.images_tab.refresh()

    def _show_plots(self):
        if self.result is None:
            return
        lvl = self.level.currentData()
        stope = self._ctx[2]
        cur = self.plots.currentIndex()
        self.plots.clear()
        self.plots.addTab(Canvas(plot_pattern(self.result, stope, lvl, self.show_zones.isChecked(), self._ctx[3])), "Pattern")
        self.plots.addTab(Canvas(plot_fragmentation(self.result, lvl, self.log_x.isChecked())), "Fragmentation")
        self.plots.setCurrentIndex(max(cur, 0))

    def export(self):
        default = WORK / "output"
        default.mkdir(exist_ok=True)
        folder = W.QFileDialog.getExistingDirectory(self, "Output folder", str(default))
        if not folder:
            return
        rock, ex, stope, p = self._ctx
        out = Path(folder) / (self.proj_name.text().strip().replace(" ", "_") or "ringblast")
        export_dxf(out.with_suffix(".dxf"), self.result, stope, params=p)
        export_hole_csv(out.with_suffix(".holes.csv"), self.result, stope, p)
        export_json(out.with_suffix(".json"), self.result, stope, rock, ex, p)
        export_report_html(out.with_suffix(".html"), self.result, stope, rock, ex, p,
                           self.proj_name.text().strip() or "RingBlast report")
        W.QMessageBox.information(self, "Export", f"Files saved in {folder}\n"
                                  "(DXF for AutoCAD, hole CSV, JSON, HTML report)")
        if sys.platform == "win32":
            import os
            os.startfile(folder)


def app_icon():
    """RingBlast icon (window title bar, taskbar, Alt-Tab): PNG for any size plus the multi-size .ico."""
    from PySide6 import QtGui as G
    icon = G.QIcon()
    for name in ("ringblast.png", "ringblast.ico"):
        f = ROOT / "launcher" / name
        if f.exists():
            icon.addFile(str(f))
    return icon


def selftest() -> int:
    """Checks that the bundled resources are found (used to verify a portable build): ringblast-gui --selftest"""
    ok = True
    for label, path in (("database", db.database_dir() / "rocks.csv"), ("manual", paths.resource_root() / "docs" / "manual.html"),
                        ("icon", paths.resource_root() / "launcher" / "ringblast.png")):
        found = path.exists()
        ok &= found
        print(f"{label}: {'OK' if found else 'MISSING'}  {path}")
    n = len(db.load_rocks())
    print(f"rocks: {n}, explosives: {len(db.load_explosives())}")
    ok &= n > 0
    try:
        db.USER_DIR.mkdir(parents=True, exist_ok=True)
        probe = db.USER_DIR / ".write_test"
        probe.write_text("x"); probe.unlink()
        print(f"user data folder writable: {db.USER_DIR}")
    except OSError as exc:
        ok = False
        print(f"user data folder NOT writable: {db.USER_DIR} ({exc})")
    print("portable mode:", paths.portable())
    return 0 if ok else 1


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    if sys.platform == "win32":             # own taskbar identity, so the taskbar shows the RingBlast icon
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("UniBo.RingBlast")
        except Exception:
            pass
    app = W.QApplication.instance() or W.QApplication(sys.argv)
    app.setWindowIcon(app_icon())
    tips.install(app)
    win = MainWindow(); win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
