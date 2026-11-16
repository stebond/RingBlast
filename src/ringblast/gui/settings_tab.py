"""Settings tab: appearance of every plot (colours, background, fonts, sizes)."""
from __future__ import annotations

from dataclasses import asdict

from PySide6 import QtCore as C
from PySide6 import QtGui as G
from PySide6 import QtWidgets as W

from .. import plotstyle
from . import tips
from ..plotstyle import PlotStyle

GROUPS = [
    ("Background and text", [("figure_bg", "Figure background"), ("axes_bg", "Plot area background"),
                             ("text_color", "Text colour"), ("axes_color", "Axes / tick colour"),
                             ("grid", "Show grid"), ("grid_color", "Grid colour")]),
    ("Fonts and lines", [("font_family", "Font"), ("font_size", "Base font size"),
                         ("title_size", "Title size"), ("label_size", "Axis label size"),
                         ("tick_size", "Tick label size"), ("legend_size", "Legend / annotation size"),
                         ("line_width", "Line width factor")]),
    ("Stope drawing", [("stope_outline", "Stope outline"), ("stope_fill", "Stope fill"),
                       ("drift_color", "Drift outline"), ("drift_fill", "Drift fill"),
                       ("block_sublevel_1", "Sublevel block (odd)"), ("block_sublevel_2", "Sublevel block (even)"),
                       ("block_base", "Base block")]),
    ("Blast pattern", [("charged_color", "Charged part of the holes"), ("stemming_color", "Stemming / uncharged"),
                       ("booster_color", "Booster (bottom charge)"),
                       ("zone_color", "Fragmentation zone boundaries")]),
    ("Curves", [("palette", "Colour palette"), ("predicted_color", "Predicted (Kuz-Ram) curve"),
                ("measured_color", "Measured (photo) curve")]),
]


class ColorButton(W.QPushButton):
    colorChanged = C.Signal()

    def __init__(self, color: str):
        super().__init__()
        self.setFixedWidth(90)
        self.set_color(color)
        self.clicked.connect(self._pick)

    def color(self) -> str:
        return self._color

    def set_color(self, c: str):
        self._color = c
        fg = "#000000" if G.QColor(c).lightness() > 128 else "#ffffff"
        self.setStyleSheet(f"background-color:{c}; color:{fg}")
        self.setText(c)

    def _pick(self):
        c = W.QColorDialog.getColor(G.QColor(self._color), self, "Choose colour")
        if c.isValid():
            self.set_color(c.name())
            self.colorChanged.emit()


def _spin(v, lo=0.5, hi=40.0, step=0.5):
    s = W.QDoubleSpinBox()
    s.setRange(lo, hi)
    s.setSingleStep(step)
    s.setDecimals(2)
    s.setValue(v)
    return s


class SettingsTab(W.QWidget):
    styleChanged = C.Signal()

    def __init__(self):
        super().__init__()
        self.widgets: dict[str, W.QWidget] = {}
        cur = plotstyle.get()
        outer = W.QVBoxLayout(self)
        top = W.QHBoxLayout()
        self.preset = W.QComboBox(); self.preset.addItems(list(plotstyle.PRESETS))
        load = W.QPushButton("Load preset"); load.clicked.connect(self.load_preset)
        reset = W.QPushButton("Reset to defaults"); reset.clicked.connect(self.reset)
        top.addWidget(W.QLabel("Preset:")); top.addWidget(self.preset); top.addWidget(load)
        top.addStretch(1); top.addWidget(reset)
        outer.addLayout(top)
        self.tips_box = W.QCheckBox("Show help tooltips (hints that appear when the mouse rests on a parameter or button)")
        self.tips_box.setChecked(tips.enabled())
        self.tips_box.setToolTip("Untick it when you know the program: the hints will no longer appear. Remembered on this computer.")
        self.tips_box.toggled.connect(tips.set_enabled)
        outer.addWidget(self.tips_box)
        from .. import updates
        self.upd_box = W.QCheckBox("Check for a new version of RingBlast at start-up (at most once a day, needs internet)")
        self.upd_box.setChecked(updates.auto_check_enabled())
        self.upd_box.setToolTip("When ticked the program asks GitHub, in the background, whether a newer release exists and "
                                "offers to download it. Nothing is sent but the request itself. You can always use Help > Check for updates.")
        self.upd_box.toggled.connect(lambda on: updates.save_settings(check_updates=bool(on)))
        outer.addWidget(self.upd_box)
        outer.addWidget(W.QLabel("Changes apply immediately to all plots and are remembered on this computer."))
        grid = W.QGridLayout()
        for g, (title, items) in enumerate(GROUPS):
            box = W.QGroupBox(title)
            form = W.QFormLayout(box)
            for key, label in items:
                w = self._make(key, getattr(cur, key))
                self.widgets[key] = w
                form.addRow(label, w)
            grid.addWidget(box, g // 2, g % 2)
        outer.addLayout(grid)
        outer.addStretch(1)
        T = {"figure_bg": "Colour around the plot area.", "axes_bg": "Colour inside the axes.",
             "text_color": "Colour of titles, labels and annotations.", "axes_color": "Colour of axis lines and tick marks.",
             "grid": "Draw a grid on the plots.", "grid_color": "Colour of the grid lines.",
             "font_family": "Font used in all plots.", "font_size": "Base font size (points).",
             "title_size": "Size of plot titles.", "label_size": "Size of axis labels.", "tick_size": "Size of tick labels.",
             "legend_size": "Size of legends and annotations.", "line_width": "Multiplier of all line widths.",
             "stope_outline": "Colour of the stope contour.", "stope_fill": "Fill of the stope.",
             "drift_color": "Colour of the drift outline.", "drift_fill": "Fill of the drifts.",
             "block_sublevel_1": "Fill of the odd sublevel blocks.", "block_sublevel_2": "Fill of the even sublevel blocks.",
             "block_base": "Fill of the base (hopper) block.",
             "charged_color": "Colour of the charged part of each hole.", "stemming_color": "Colour of the stemming / uncharged part.", "booster_color": "Colour of the booster (bottom charge), drawn thicker than the column.",
             "zone_color": "Colour of the fragmentation zone boundaries.", "palette": "Colours used for the curves of the different levels.",
             "predicted_color": "Colour of the Kuz-Ram prediction in the photo plots.",
             "measured_color": "Colour of the distribution measured on the photos."}
        for k, t in T.items():
            if k in self.widgets:
                self.widgets[k].setToolTip(t)
        tips.by_text(self, {"Load preset": "Applies the preset selected on the left (Default, Dark, Publication).",
                            "Reset to defaults": "Restores the original plot appearance."})
        self.preset.setToolTip("Ready-made plot styles; Publication uses white background and larger fonts.")

    def _make(self, key, value):
        if key == "font_family":
            w = W.QComboBox(); w.addItems(plotstyle.available_fonts())
            if w.findText(value) < 0:
                w.addItem(value)
            w.setCurrentText(value)
            w.currentTextChanged.connect(self._changed)
        elif key == "palette":
            w = W.QComboBox(); w.addItems(plotstyle.PALETTES); w.setCurrentText(value)
            w.currentTextChanged.connect(self._changed)
        elif isinstance(value, bool):
            w = W.QCheckBox(); w.setChecked(value); w.toggled.connect(self._changed)
        elif isinstance(value, float):
            w = _spin(value, 0.2 if key == "line_width" else 4.0, 4.0 if key == "line_width" else 40.0,
                      0.1 if key == "line_width" else 0.5)
            w.valueChanged.connect(self._changed)
        else:
            w = ColorButton(value); w.colorChanged.connect(self._changed)
        return w

    def style(self) -> PlotStyle:
        d = {}
        for k, w in self.widgets.items():
            d[k] = (w.color() if isinstance(w, ColorButton) else w.currentText() if isinstance(w, W.QComboBox)
                    else w.isChecked() if isinstance(w, W.QCheckBox) else w.value())
        return PlotStyle(**d)

    def set_style(self, st: PlotStyle):
        for k, v in asdict(st).items():
            w = self.widgets[k]
            w.blockSignals(True)
            if isinstance(w, ColorButton):
                w.set_color(v)
            elif isinstance(w, W.QComboBox):
                if w.findText(v) < 0:
                    w.addItem(v)
                w.setCurrentText(v)
            elif isinstance(w, W.QCheckBox):
                w.setChecked(v)
            else:
                w.setValue(v)
            w.blockSignals(False)
        self._changed()

    def _changed(self, *_):
        st = self.style()
        plotstyle.set_style(st)
        try:
            plotstyle.save(st)
        except OSError:
            pass
        self.styleChanged.emit()

    def load_preset(self):
        self.set_style(plotstyle.PRESETS[self.preset.currentText()])

    def reset(self):
        self.set_style(plotstyle.defaults())
