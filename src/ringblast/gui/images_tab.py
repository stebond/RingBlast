"""Muck-pile photo analysis tab: load photos, calibrate the scale, measure the fragment sizes."""
from __future__ import annotations

import csv
import json
from datetime import date
from pathlib import Path

import numpy as np
from PySide6 import QtCore as C
from PySide6 import QtGui as G
from PySide6 import QtWidgets as W
from .zoomcanvas import ZoomCanvas as Canvas

from .. import imageanalysis as ia
from ..export import plot_image_distributions, stope_passing_curve
from ..project import ImageRecord
from . import tips


def bgr_to_pixmap(img: np.ndarray) -> G.QPixmap:
    rgb = np.ascontiguousarray(img[:, :, ::-1])
    h, w = rgb.shape[:2]
    return G.QPixmap.fromImage(G.QImage(rgb.data, w, h, 3 * w, G.QImage.Format_RGB888).copy())


class ImageView(W.QLabel):
    """Shows a photo scaled to fit; collects the two clicks of the scale reference.

    Mouse wheel = zoom around the cursor (to inspect the fragments), left-button drag (or middle button)
    = pan, double-click = back to the whole photo.  While the scale is being picked, a left click picks
    a point instead of panning, so the two points can be placed precisely on a zoomed photo."""
    pointsPicked = C.Signal(list)
    roiPicked = C.Signal(list)              # [x0, y0, x1, y1] in photo pixels
    MAX_ZOOM = 40.0

    def __init__(self):
        super().__init__()
        self.setMinimumSize(380, 280)
        self.setSizePolicy(W.QSizePolicy.Expanding, W.QSizePolicy.Expanding)
        self.setAlignment(C.Qt.AlignCenter)
        self.setText("No photo")
        self.setToolTip("Mouse wheel: zoom in/out around the cursor. Drag with the left (or middle) button: move the photo. "
                        "Double-click: show the whole photo.")
        self._pix = None
        self.pick_mode = False
        self.points: list = []
        self._zoom = 1.0                    # 1 = whole photo fitted in the view
        self._origin = None                 # top-left of the photo in view coordinates when zoomed
        self._drag = None                   # (mouse position, origin) while panning
        self.roi: list = []                 # area of interest to outline, [x0, y0, x1, y1]
        self.roi_mode = False               # True while the user drags the rectangle of the area of interest
        self._roi_a = None                  # drag start / current point, photo pixels
        self._roi_b = None

    # ------------------------------------------------------------ geometry
    def set_image(self, img: np.ndarray | None):
        old = (self._pix.width(), self._pix.height()) if self._pix is not None else None
        self._pix = bgr_to_pixmap(img) if img is not None else None
        if self._pix is None or old != (self._pix.width(), self._pix.height()):
            self.reset_zoom()               # another photo: start from the whole picture
        self.update()

    def reset_zoom(self):
        self._zoom, self._origin = 1.0, None
        self.update()

    def zoom_factor(self) -> float:
        return self._zoom

    def _fit_k(self) -> float:
        return min(self.width() / self._pix.width(), self.height() / self._pix.height())

    def _clamp_origin(self, o: C.QPointF, k: float) -> C.QPointF:
        """Keep the photo covering the view (or centred when it is smaller than the view)."""
        x, y = o.x(), o.y()
        rw, rh = self._pix.width() * k, self._pix.height() * k
        x = (self.width() - rw) / 2 if rw <= self.width() else min(0.0, max(self.width() - rw, x))
        y = (self.height() - rh) / 2 if rh <= self.height() else min(0.0, max(self.height() - rh, y))
        return C.QPointF(x, y)

    def _rect(self):
        k = self._fit_k() * self._zoom
        if self._origin is None or self._zoom <= 1.0:
            o = C.QPointF((self.width() - self._pix.width() * k) / 2, (self.height() - self._pix.height() * k) / 2)
        else:
            o = self._clamp_origin(self._origin, k)
        return C.QRectF(o.x(), o.y(), self._pix.width() * k, self._pix.height() * k), k

    def paintEvent(self, ev):
        if self._pix is None:
            return super().paintEvent(ev)
        p = G.QPainter(self)
        r, k = self._rect()
        p.setRenderHint(G.QPainter.SmoothPixmapTransform, k < 3)     # pixels stay sharp at high zoom
        vis = r.intersected(C.QRectF(self.rect()))                    # draw only the visible part
        src = C.QRectF((vis.x() - r.x()) / k, (vis.y() - r.y()) / k, vis.width() / k, vis.height() / k)
        p.drawPixmap(vis, self._pix, src)
        p.setPen(G.QPen(G.QColor("#ffd400"), 2))
        pts = [C.QPointF(r.x() + x * k, r.y() + y * k) for x, y in self.points]
        for q in pts:
            p.drawLine(q + C.QPointF(-6, 0), q + C.QPointF(6, 0))
            p.drawLine(q + C.QPointF(0, -6), q + C.QPointF(0, 6))
        if len(pts) == 2:
            p.drawLine(pts[0], pts[1])
        rect = None
        if self._roi_a is not None and self._roi_b is not None:
            rect = [*self._roi_a, *self._roi_b]
        elif len(self.roi) == 4:
            rect = self.roi
        if rect:
            x0, x1 = sorted((rect[0], rect[2])); y0, y1 = sorted((rect[1], rect[3]))
            pen = G.QPen(G.QColor("#00e5ff"), 2, C.Qt.DashLine)
            p.setPen(pen); p.setBrush(C.Qt.NoBrush)
            p.drawRect(C.QRectF(r.x() + x0 * k, r.y() + y0 * k, (x1 - x0) * k, (y1 - y0) * k))
        if self._zoom > 1.001:
            p.setPen(G.QColor("white")); p.setBrush(G.QColor(0, 0, 0, 150))
            txt = f"x{self._zoom:.1f}  (double-click: whole photo)"
            box = C.QRectF(6, 6, p.fontMetrics().horizontalAdvance(txt) + 14, p.fontMetrics().height() + 6)
            p.drawRoundedRect(box, 4, 4)
            p.drawText(box, C.Qt.AlignCenter, txt)

    # ------------------------------------------------------------ mouse
    def wheelEvent(self, ev):
        if self._pix is None:
            return super().wheelEvent(ev)
        steps = ev.angleDelta().y() / 120.0
        if steps == 0:
            return
        r, k = self._rect()
        cur = ev.position()
        point = C.QPointF((cur.x() - r.x()) / k, (cur.y() - r.y()) / k)          # photo point under the cursor
        self._zoom = min(self.MAX_ZOOM, max(1.0, self._zoom * (1.25 ** steps)))
        k2 = self._fit_k() * self._zoom
        self._origin = C.QPointF(cur.x() - point.x() * k2, cur.y() - point.y() * k2)   # ... stays under it
        if self._zoom <= 1.0:
            self._origin = None
        self.update()
        ev.accept()

    def mouseDoubleClickEvent(self, ev):
        if self._pix is not None:
            self.reset_zoom()

    def mousePressEvent(self, ev):
        if self._pix is None:
            return
        if self.roi_mode and ev.button() == C.Qt.LeftButton:
            self._roi_a = self._roi_b = self._to_photo(ev.position())
            self.update()
            return
        pan = ev.button() == C.Qt.MiddleButton or (ev.button() == C.Qt.LeftButton and not (self.pick_mode or self.roi_mode))
        if pan and self._zoom > 1.0:
            r, _ = self._rect()
            self._drag = (ev.position(), C.QPointF(r.x(), r.y()))
            self.setCursor(C.Qt.ClosedHandCursor)
            return
        if not (self.pick_mode and ev.button() == C.Qt.LeftButton):
            return
        r, k = self._rect()
        x, y = (ev.position().x() - r.x()) / k, (ev.position().y() - r.y()) / k
        if 0 <= x <= self._pix.width() and 0 <= y <= self._pix.height():
            self.points.append((x, y))
            self.update()
            if len(self.points) == 2:
                self.pick_mode = False
                self.pointsPicked.emit(list(self.points))

    def _to_photo(self, pos):
        """View position -> photo pixel, clamped to the photo."""
        r, k = self._rect()
        x = min(max((pos.x() - r.x()) / k, 0.0), float(self._pix.width()))
        y = min(max((pos.y() - r.y()) / k, 0.0), float(self._pix.height()))
        return (x, y)

    def mouseMoveEvent(self, ev):
        if self._roi_a is not None:
            self._roi_b = self._to_photo(ev.position())
            self.update()
            return
        if self._drag is not None:
            start, o0 = self._drag
            d = ev.position() - start
            self._origin = C.QPointF(o0.x() + d.x(), o0.y() + d.y())
            self.update()

    def mouseReleaseEvent(self, ev):
        if self._roi_a is not None:
            a, b = self._roi_a, self._to_photo(ev.position())
            self._roi_a = self._roi_b = None
            self.roi_mode = False
            self.unsetCursor()
            if abs(a[0] - b[0]) >= 20 and abs(a[1] - b[1]) >= 20:     # ignore a simple click
                self.roiPicked.emit([min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1])])
            self.update()
            return
        if self._drag is not None:
            self._drag = None
            self.unsetCursor()


class ImagesTab(W.QWidget):
    changed = C.Signal()

    def __init__(self, design_provider=lambda: None):
        super().__init__()
        self.design_provider = design_provider
        self.project_name = lambda: ""                 # set by the main window
        self.ask_project_name = None                   # set by the main window: asks for a name if missing
        self.records: list[ImageRecord] = []
        self.results: dict[str, ia.FragmentResult] = {}
        self._loading = False
        self._cache: tuple[str, np.ndarray] | None = None

        self.listw = W.QListWidget()
        self.listw.currentRowChanged.connect(self._select)
        btns = W.QGridLayout()
        for i, (t, f) in enumerate([("Add photos...", self.add_dialog), ("Remove", self.remove_selected),
                                    ("Analyse selected", self.analyse_selected), ("Analyse all", self.analyse_all),
                                    ("Export results...", self.export_dialog),
                                    ("Save all photos...", self.save_photos_dialog),
                                    ("Report (HTML / PDF)...", self.report_dialog)]):
            b = W.QPushButton(t); b.clicked.connect(lambda _=False, fn=f: fn())
            btns.addWidget(b, i // 2, i % 2)

        self.date = W.QDateEdit(calendarPopup=True); self.date.setDisplayFormat("yyyy-MM-dd")
        self.date.setDate(C.QDate.currentDate())
        self.location = W.QPlainTextEdit(); self.location.setMaximumHeight(60)
        self.location.setPlaceholderText("Where the photo was taken (level, ring, position in the pile)")
        self.notes = W.QPlainTextEdit(); self.notes.setMaximumHeight(60)
        self.notes.setPlaceholderText("Notes on the visit / the muck pile")
        self.scale = W.QDoubleSpinBox(); self.scale.setRange(0, 1e4); self.scale.setDecimals(3)
        self.scale.setSpecialValueText("not set"); self.scale.setSuffix(" px/cm")
        self.scale_btn = W.QPushButton("Set scale: click two points of a known length")
        self.scale_btn.clicked.connect(self.begin_scale)
        self.roi_btn = W.QPushButton("Select area of interest: drag a rectangle")
        self.roi_btn.clicked.connect(self.begin_roi)
        self.roi_clear = W.QPushButton("Whole photo")
        self.roi_clear.clicked.connect(self.clear_roi)
        self.roi_label = W.QLabel("Area of interest: whole photo")
        self.roi_label.setWordWrap(True)
        self.min_size = W.QDoubleSpinBox(); self.min_size.setRange(0.5, 200); self.min_size.setValue(3.0)
        self.min_size.setSuffix(" cm")
        self.sens = W.QDoubleSpinBox(); self.sens.setRange(0, 1); self.sens.setSingleStep(0.1); self.sens.setValue(0.5)
        form = W.QFormLayout()
        for label, w in [("Date", self.date), ("Location", self.location), ("Notes", self.notes),
                         ("Image scale", self.scale), ("", self.scale_btn),
                         ("Analysed area", self.roi_label)]:
            form.addRow(label, w)
        roi_row = W.QHBoxLayout(); roi_row.addWidget(self.roi_btn, 1); roi_row.addWidget(self.roi_clear)
        form.addRow("", roi_row)
        seg_form = self._build_segmentation_controls()
        for w in (self.location, self.notes):
            w.textChanged.connect(self._save_form)
        self.date.dateChanged.connect(self._save_form)
        self.scale.valueChanged.connect(self._save_form)

        photo_page = W.QWidget(); photo_page.setLayout(form)
        seg_page = W.QScrollArea(); seg_page.setWidgetResizable(True)
        inner = W.QWidget(); inner.setLayout(seg_form); seg_page.setWidget(inner)
        self.left_tabs = W.QTabWidget()
        self.left_tabs.addTab(photo_page, "Photo")
        self.left_tabs.addTab(seg_page, "Segmentation")
        left = W.QWidget(); lv = W.QVBoxLayout(left)
        lv.addWidget(W.QLabel("Muck-pile photos")); lv.addWidget(self.listw, 1)
        lv.addLayout(btns); lv.addWidget(self.left_tabs, 2)

        self.view = ImageView(); self.view.pointsPicked.connect(self._points_picked)
        self.view.roiPicked.connect(self._roi_picked)
        self.view_mode = W.QComboBox()
        self.view_mode.addItems(["Fragments", "Original photo", "Pre-processed (grey)", "Boundaries (red = rejected)"])
        self.view_mode.currentIndexChanged.connect(self._show_image)
        self.live = W.QCheckBox("Live update while changing parameters"); self.live.setChecked(False)
        self.live_timer = C.QTimer(self); self.live_timer.setSingleShot(True); self.live_timer.setInterval(500)
        self.live_timer.timeout.connect(self._live_refresh)
        self.status = W.QLabel("")
        self.plot_holder = W.QVBoxLayout()
        self.summary = W.QPlainTextEdit(readOnly=True)
        right = W.QWidget(); rv = W.QVBoxLayout(right)
        bar = W.QHBoxLayout(); bar.addWidget(W.QLabel("View:")); bar.addWidget(self.view_mode)
        bar.addWidget(self.live); bar.addStretch(1); bar.addWidget(self.status)
        self.log_x = W.QCheckBox("Logarithmic size axis"); self.log_x.setChecked(True)
        self.log_x.toggled.connect(lambda *_: self.refresh())
        rv.addWidget(self.view, 3); rv.addLayout(bar)
        pw = W.QWidget(); pl = W.QVBoxLayout(pw); pl.setContentsMargins(0, 0, 0, 0)
        pl.addWidget(self.log_x); pl.addLayout(self.plot_holder, 1)
        sp = W.QSplitter(C.Qt.Horizontal); sp.addWidget(pw); sp.addWidget(self.summary)
        rv.addWidget(sp, 3)
        main = W.QSplitter(); main.addWidget(left); main.addWidget(right); main.setStretchFactor(1, 3)
        W.QVBoxLayout(self).addWidget(main)
        self._form_enabled(False)
        tips.by_text(self, {
            "Add photos...": "Loads one or more photos of the muck pile (jpg, png, tif, bmp).",
            "Remove": "Removes the selected photo from the project (the original file is not touched).",
            "Analyse selected": "Measures the fragments of the selected photo with the current segmentation settings. Needs the image scale.",
            "Analyse all": "Analyses every photo that has a scale, each with its own settings.",
            "Export results...": "Saves the summary CSV, the outlined images and the pooled size distribution.",
            "Save all photos...": "Saves, for every analysed photo, the picture with the outlined fragments and a scale bar (PNG), "
                                  "ready for papers and reports, together with the analysed part of the original photo.",
            "Report (HTML / PDF)...": "Report of all analysed photos: photo and area of interest, outlined fragments, "
                                  "settings, statistics and size distributions, and the distribution of the whole set. "
                                  "Choose .html, .pdf or .docx (Word) as the file type.",
            "Select area of interest: drag a rectangle": "Drag a rectangle on the photo around the part that has to be analysed "
                                  "(the muck pile, not the drift walls or the floor). Only that area is analysed; the rest is darkened.",
            "Whole photo": "Removes the area of interest: the whole photo will be analysed."})
        tips.set_all([
            (self.log_x, "Logarithmic scale for the size axis (default). Untick for a linear scale. Display only; results are unchanged."),
            (self.listw, "Photos of the project. Select one to see it and to edit its date, notes, scale and settings."),
            (self.date, "Date of the photo or of the site visit."),
            (self.location, "Where the photo was taken: level, ring, position in the pile."),
            (self.notes, "Remarks on the muck pile or on the photo conditions."),
            (self.scale, "Image scale in pixels per cm. Normally set with the button below; you can also type it."),
            (self.scale_btn, "Click the two ends of an object of known length in the photo, then enter its length in cm."),
            (self.view_mode, "What to show: detected fragments, the original photo, the pre-processed grey image, or the boundaries (red) found by the threshold."),
            (self.live, "Re-runs the analysis automatically half a second after you stop changing a segmentation value."),
            (self.view, "Photo. During scale setting, click the two ends of the reference length."),
            (self.summary, "Size statistics (equivalent diameters, volume-weighted) of each photo and of all photos together.")])
        self.refresh()

    # ------------------------------------------------------------------ segmentation controls
    def _build_segmentation_controls(self) -> W.QFormLayout:
        def dspin(lo, hi, step, dec=1, suffix=""):
            w = W.QDoubleSpinBox(); w.setRange(lo, hi); w.setSingleStep(step); w.setDecimals(dec); w.setSuffix(suffix)
            return w
        def ispin(lo, hi):
            w = W.QSpinBox(); w.setRange(lo, hi)
            return w
        self.min_size = dspin(0.5, 200, 0.5, 1, " cm")
        self.min_size.setToolTip("Regions smaller than this are ignored (counted as unresolved area)")
        self.sens = dspin(0, 1, 0.1, 2)
        self.sens.setToolTip("Higher = more boundary pixels and more splitting of touching blocks (more, smaller fragments)")
        self.seg_w = {
            "contrast": dspin(0, 10, 0.5, 1),
            "gamma": dspin(0.3, 3, 0.1, 2),
            "smoothing": dspin(0, 4, 0.25, 2),
            "threshold_mode": W.QComboBox(),
            "threshold_shift": dspin(-40, 40, 1, 1),
            "fixed_level": ispin(0, 255),
            "window": dspin(1, 12, 0.5, 1),
            "invert": W.QCheckBox("Fragments are darker than the gaps"),
            "erode_iter": ispin(0, 6), "open_iter": ispin(0, 6), "close_iter": ispin(0, 6),
            "max_fragment_fraction": dspin(0.05, 0.95, 0.05, 2),
        }
        self.seg_w["threshold_mode"].addItems(["adaptive", "otsu", "fixed"])
        tips = {
            "contrast": "Local contrast enhancement (CLAHE clip limit); 0 = off. Raise it for flat, hazy photos",
            "gamma": "<1 brightens shadows, >1 darkens highlights. Use it to recover detail in dark or glaring areas",
            "smoothing": "Noise smoothing relative to the smallest fragment; 0 = off. Raise it if rock texture is cut into pieces",
            "threshold_mode": "adaptive: local threshold (uneven light, default). otsu: one automatic global level. "
                              "fixed: you choose the grey level",
            "threshold_shift": "adaptive: + gives fewer boundary pixels (fragments merge), - gives more (fragments split). "
                               "otsu: shifts the automatic level",
            "fixed_level": "Grey level (0-255) separating fragments from gaps (mode 'fixed')",
            "window": "Size of the local window of the adaptive threshold, in smallest-fragment diameters",
            "invert": "Tick when gaps are brighter than the fragments (e.g. wet dark rock on light fines)",
            "erode_iter": "Shrinks the fragments to separate touching blocks",
            "open_iter": "Removes small bright specks",
            "close_iter": "Fills small dark holes inside fragments",
            "max_fragment_fraction": "Regions covering more than this fraction of the image are rejected (sky, background)",
        }
        for k, t in tips.items():
            self.seg_w[k].setToolTip(t)
        labels = [("Smallest fragment", self.min_size), ("Sensitivity (0-1)", self.sens),
                  ("Contrast (CLAHE)", self.seg_w["contrast"]), ("Gamma", self.seg_w["gamma"]),
                  ("Smoothing", self.seg_w["smoothing"]), ("Threshold mode", self.seg_w["threshold_mode"]),
                  ("Threshold shift", self.seg_w["threshold_shift"]), ("Fixed grey level", self.seg_w["fixed_level"]),
                  ("Adaptive window", self.seg_w["window"]), ("", self.seg_w["invert"]),
                  ("Erode (separate)", self.seg_w["erode_iter"]), ("Open (despeckle)", self.seg_w["open_iter"]),
                  ("Close (fill holes)", self.seg_w["close_iter"]),
                  ("Max fragment / image", self.seg_w["max_fragment_fraction"])]
        form = W.QFormLayout()
        for label, w in labels:
            form.addRow(label, w)
        reset = W.QPushButton("Reset segmentation"); reset.clicked.connect(self.reset_segmentation)
        allb = W.QPushButton("Copy to all photos"); allb.clicked.connect(self.copy_segmentation_to_all)
        row = W.QHBoxLayout(); row.addWidget(reset); row.addWidget(allb)
        reset.setToolTip("Restores the default segmentation settings of the current photo.")
        allb.setToolTip("Applies the current segmentation settings to every photo (analyse again afterwards).")
        form.addRow(row)
        for w in [self.min_size, self.sens, *self.seg_w.values()]:
            sig = (w.currentTextChanged if isinstance(w, W.QComboBox) else
                   w.toggled if isinstance(w, W.QCheckBox) else w.valueChanged)
            sig.connect(self._seg_changed)
        return form

    @staticmethod
    def current_parameters(r: ImageRecord) -> dict:
        """Every setting that influences the result of one photo."""
        return {**ia.SEG_DEFAULTS, **r.seg, "min_size_cm": r.min_size_cm, "sensitivity": r.sensitivity,
                "scale_px_per_cm": r.scale_px_per_cm, "roi": [round(v) for v in r.roi]}

    def seg_values(self) -> dict:
        out = {}
        for k, w in self.seg_w.items():
            out[k] = (w.currentText() if isinstance(w, W.QComboBox) else w.isChecked() if isinstance(w, W.QCheckBox)
                      else w.value())
        return out

    def _set_seg_widgets(self, seg: dict, min_size: float, sens: float):
        vals = {**ia.SEG_DEFAULTS, **seg}
        self.min_size.setValue(min_size); self.sens.setValue(sens)
        for k, w in self.seg_w.items():
            if isinstance(w, W.QComboBox):
                w.setCurrentText(str(vals[k]))
            elif isinstance(w, W.QCheckBox):
                w.setChecked(bool(vals[k]))
            else:
                w.setValue(vals[k])
        fixed = vals["threshold_mode"] == "fixed"
        self.seg_w["fixed_level"].setEnabled(fixed)
        self.seg_w["window"].setEnabled(vals["threshold_mode"] == "adaptive")

    def _seg_changed(self, *_):
        if self._loading:
            return
        mode = self.seg_w["threshold_mode"].currentText()
        self.seg_w["fixed_level"].setEnabled(mode == "fixed")
        self.seg_w["window"].setEnabled(mode == "adaptive")
        self._save_form()
        self.refresh_summary()
        if self.live.isChecked():
            self.live_timer.start()                       # debounce: wait until the user stops changing values
        elif self.view_mode.currentIndex() in (2, 3):
            self.live_timer.start()                       # stage previews are cheap: always refresh them

    def _live_refresh(self):
        r = self.current()
        if r is None or not r.scale_px_per_cm:
            return
        if self.live.isChecked():
            self.analyse([r], quiet=True)
        else:
            self._show_image()

    def reset_segmentation(self):
        self._loading = True
        self._set_seg_widgets({}, 3.0, 0.5)
        self._loading = False
        self._save_form()
        self._live_refresh()

    def copy_segmentation_to_all(self):
        r = self.current()
        if r is None:
            return
        for o in self.records:
            o.seg, o.min_size_cm, o.sensitivity = dict(r.seg), r.min_size_cm, r.sensitivity
        self.status.setText("Segmentation settings copied to all photos (analyse again to apply)")
        self.changed.emit()

    # ------------------------------------------------------------------ records
    def current(self) -> ImageRecord | None:
        i = self.listw.currentRow()
        return self.records[i] if 0 <= i < len(self.records) else None

    def add_files(self, paths) -> None:
        for p in paths:
            p = str(Path(p).resolve())
            if any(r.path == p for r in self.records):
                continue
            d = ia.exif_date(p) or date.today().isoformat()
            self.records.append(ImageRecord(p, date=d, seg=dict(ia.SEG_DEFAULTS)))
            self.listw.addItem(Path(p).name)
        if self.records:
            self.listw.setCurrentRow(len(self.records) - 1)
        self.changed.emit()
        self.refresh()

    def add_dialog(self):
        paths, _ = W.QFileDialog.getOpenFileNames(self, "Add photos", "", "Images (*.jpg *.jpeg *.png *.tif *.tiff *.bmp)")
        self.add_files(paths)

    def remove_selected(self):
        i = self.listw.currentRow()
        if i < 0:
            return
        self.results.pop(self.records[i].path, None)
        del self.records[i]
        self.listw.takeItem(i)
        self.changed.emit()
        self._select(self.listw.currentRow())
        self.refresh()

    def fragment_sizes(self) -> list:
        """Measured fragment sizes per record (None if not analysed), for the project file."""
        return [self.results[r.path].sizes_cm.tolist() if r.path in self.results else None for r in self.records]

    def set_records(self, records: list[ImageRecord], sizes: list | None = None):
        self.records, self.results, self._cache = list(records), {}, None
        for r, sz in zip(self.records, sizes or []):
            if sz:                                          # restore the measurements stored in the project
                self.results[r.path] = ia.from_sizes(sz, r.scale_px_per_cm or 0.0,
                                                     r.summary.get("unresolved_area_fraction", float("nan")))
        self.listw.clear()
        for r in self.records:
            self.listw.addItem(r.name + ("" if Path(r.path).exists() else "  (file not found)"))
        if self.records:
            self.listw.setCurrentRow(0)
        self._select(self.listw.currentRow())
        self.refresh()

    def clear(self):
        self.set_records([])

    # ------------------------------------------------------------------ form <-> record
    def _form_enabled(self, on: bool):
        for w in (self.date, self.location, self.notes, self.scale, self.scale_btn, self.roi_btn, self.roi_clear, self.min_size, self.sens,
                  *self.seg_w.values()):
            w.setEnabled(on)

    def _select(self, row):
        r = self.current()
        self._form_enabled(r is not None)
        self._loading = True
        if r is not None:
            self.date.setDate(C.QDate.fromString(r.date, "yyyy-MM-dd") if r.date else C.QDate.currentDate())
            self.location.setPlainText(r.location)
            self.notes.setPlainText(r.notes)
            self.scale.setValue(r.scale_px_per_cm or 0.0)
            self._set_seg_widgets(r.seg, r.min_size_cm, r.sensitivity)
            self.view.points = [tuple(p) for p in r.scale_points]
            self._roi_text(r)
        else:
            self.view.points = []
            self.view.roi = []
            self.roi_label.setText("whole photo")
        self._loading = False
        self._show_image()
        self.refresh_summary()

    def _save_form(self, *_):
        r = self.current()
        if r is None or self._loading:
            return
        r.date = self.date.date().toString("yyyy-MM-dd")
        r.location, r.notes = self.location.toPlainText(), self.notes.toPlainText()
        r.min_size_cm, r.sensitivity = self.min_size.value(), self.sens.value()
        r.seg = self.seg_values()
        manual = self.scale.value()
        if manual > 0 and manual != (r.scale_px_per_cm or 0):       # scale typed by hand
            r.scale_px_per_cm, r.scale_points, r.scale_length_cm = manual, [], None
            self.view.points = []
            self.view.update()
            self._roi_text(r)
        self.changed.emit()

    def _image(self, rec: ImageRecord) -> np.ndarray | None:
        if self._cache and self._cache[0] == rec.path:
            return self._cache[1]
        try:
            img = ia.load_image(rec.path)
        except Exception:
            return None
        self._cache = (rec.path, img)
        return img

    def _show_image(self, *_):
        r = self.current()
        if r is None:
            self.view.set_image(None)
            return
        res = self.results.get(r.path)
        raw = self._image(r)
        mode = self.view_mode.currentIndex()
        img = raw
        self.view.roi = list(r.roi)
        if mode == 0 and res is not None and res.overlay is not None and raw is not None:
            img = ia.compose_roi(raw, r.analysed_with.get("roi") or [], res.overlay)    # whole photo, ROI outlined
        elif mode in (2, 3) and raw is not None:
            if r.scale_px_per_cm:
                part, _ = ia.crop_roi(raw, r.roi)
                img = ia.compose_roi(raw, r.roi, ia.stage_image(part, r.scale_px_per_cm, r.min_size_cm, r.sensitivity,
                                                                r.seg, "pre" if mode == 2 else "mask"))
            else:
                self.status.setText("Set the image scale to preview the processing stages")
        self.view.set_image(img)

    # ------------------------------------------------------------------ area of interest
    def begin_roi(self):
        r = self.current()
        if r is None or self._image(r) is None:
            W.QMessageBox.warning(self, "Area of interest", "Select a readable photo first.")
            return
        self.view_mode.setCurrentIndex(1)
        self.view.roi_mode = True
        self.view.setCursor(C.Qt.CrossCursor)
        self.status.setText("Drag a rectangle on the photo (mouse wheel to zoom, middle button to move)")

    def _roi_picked(self, roi: list):
        r = self.current()
        if r is None:
            return
        r.roi = [round(v) for v in roi]
        self._roi_text(r)
        self.changed.emit()
        self._show_image()
        self.status.setText("Area of interest set: press Analyse selected to analyse it")

    def clear_roi(self):
        r = self.current()
        if r is not None and r.roi:
            r.roi = []
            self._roi_text(r)
            self.changed.emit()
            self._show_image()

    def _roi_text(self, r: ImageRecord) -> None:
        if len(r.roi) != 4:
            self.roi_label.setText("whole photo")
            return
        w, h = abs(r.roi[2] - r.roi[0]), abs(r.roi[3] - r.roi[1])
        txt = f"{w} x {h} px"
        if r.scale_px_per_cm:
            txt += f"  ({w / r.scale_px_per_cm / 100:.2f} x {h / r.scale_px_per_cm / 100:.2f} m)"
        self.roi_label.setText(txt)

    # ------------------------------------------------------------------ scale
    def begin_scale(self):
        if self.current() is None or self._image(self.current()) is None:
            W.QMessageBox.warning(self, "Scale", "Select a readable photo first.")
            return
        self.view_mode.setCurrentIndex(1)
        self.view.points = []
        self.view.pick_mode = True
        W.QMessageBox.information(self, "Scale", "Click the two ends of an object of known length "
                                  "(ruler, helmet, drill rod...) in the photo.")

    def _points_picked(self, pts):
        length, ok = W.QInputDialog.getDouble(self, "Scale", "Real distance between the two points (cm):",
                                              50.0, 0.1, 1e5, 1)
        if ok:
            self.set_scale_points(pts[0], pts[1], length)

    def set_scale_points(self, p1, p2, length_cm: float):
        r = self.current()
        if r is None or length_cm <= 0:
            return
        d = float(np.hypot(p2[0] - p1[0], p2[1] - p1[1]))
        if d < 2:
            W.QMessageBox.warning(self, "Scale", "The two points are too close.")
            return
        r.scale_points, r.scale_length_cm, r.scale_px_per_cm = [tuple(p1), tuple(p2)], length_cm, d / length_cm
        self.view.points = list(r.scale_points)
        self._loading = True
        self.scale.setValue(r.scale_px_per_cm)
        self._loading = False
        self.view.update()
        self.changed.emit()

    # ------------------------------------------------------------------ analysis
    def analyse_selected(self):
        r = self.current()
        if r is not None:
            self.analyse([r])

    def analyse_all(self):
        self.analyse(self.records)

    def analyse(self, records, quiet: bool = False) -> list[str]:
        problems = []
        W.QApplication.setOverrideCursor(C.Qt.WaitCursor)
        try:
            for r in records:
                if not r.scale_px_per_cm:
                    problems.append(f"{r.name}: set the image scale first")
                    continue
                img = self._image(r)
                if img is None:
                    problems.append(f"{r.name}: file not found or unreadable")
                    continue
                part, _ = ia.crop_roi(img, r.roi)                    # only the area of interest
                res = ia.analyse_image(part, r.scale_px_per_cm, r.min_size_cm, r.sensitivity, params=r.seg)
                self.results[r.path] = res
                r.summary = res.summary()
                r.analysed_with = self.current_parameters(r)
                self.status.setText(f"{r.name}: {res.n_fragments} fragments, D50 = {res.percentiles_cm.get(50, float('nan')):.1f} cm, "
                                    f"unresolved area {100 * res.unresolved_area_fraction:.0f} %")
        finally:
            W.QApplication.restoreOverrideCursor()
        if problems and not quiet:
            W.QMessageBox.warning(self, "Analysis", "\n".join(problems))
        self.changed.emit()
        self._show_image()
        self.refresh()
        return problems

    # ------------------------------------------------------------------ results
    def pooled(self) -> dict | None:
        res = [self.results[r.path] for r in self.records if r.path in self.results]
        return ia.combine(res) if res else None

    def refresh(self):
        entries = [{"name": r.name, "sizes_cm": self.results[r.path].sizes_cm}
                   for r in self.records if r.path in self.results]
        pooled = self.pooled()
        predicted = None
        design = self.design_provider()
        if design is not None:
            x = np.geomspace(0.5, 150, 300)
            curve = stope_passing_curve(design, x)
            if curve is not None:
                predicted = (x, curve)
        fig = plot_image_distributions(entries, pooled["sizes_cm"] if pooled else None, predicted, self.log_x.isChecked())
        while self.plot_holder.count():
            w = self.plot_holder.takeAt(0).widget()
            if w:
                w.setParent(None)
                w.deleteLater()
        self.plot_holder.addWidget(Canvas(fig))
        self.refresh_summary()

    def refresh_summary(self):
        lines = []
        fmt = lambda d: (f"n={d.get('n_fragments', 0)}  D10={d.get('d10_cm', float('nan')):.1f}  "
                         f"D50={d.get('d50_cm', float('nan')):.1f}  D80={d.get('d80_cm', float('nan')):.1f}  "
                         f"Dmax={d.get('dmax_cm', float('nan')):.1f} cm  RR n={d.get('rr_n', float('nan')):.2f}")
        for r in self.records:
            tag = "" if r.path in self.results else " (not analysed)"
            if r.path in self.results and r.analysed_with and {"roi": [], **r.analysed_with} != self.current_parameters(r):
                tag = " (parameters changed since the analysis: analyse again)"
            lines.append(f"{r.name} [{r.date}]{tag}")
            if r.summary:
                lines.append("   " + fmt(r.summary))
        p = self.pooled()
        if p:
            lines += ["", "ALL PHOTOS: " + fmt({"n_fragments": p["n_fragments"], "dmax_cm": p["dmax_cm"],
                                                 "rr_n": p["rr_n"], **{f"d{k}_cm": v for k, v in p["percentiles_cm"].items()}})]
        d = self.design_provider()
        if d is not None:
            lines.append(f"Design (Kuz-Ram) weighted mean size X50 = {d.weighted_mean_size_cm:.1f} cm")
        lines += ["", "Sizes are equivalent diameters of the visible fragments, volume-weighted. Check against sieving."]
        self.summary.setPlainText("\n".join(lines))

    def export_dialog(self):
        folder = W.QFileDialog.getExistingDirectory(self, "Output folder", str(Path.cwd()))
        if folder:
            self.export(folder)

    def save_photos_dialog(self):
        if not any(self.results.get(r.path) is not None and self.results[r.path].overlay is not None for r in self.records):
            W.QMessageBox.information(self, "Save all photos", "Analyse the photos first (they need a scale).")
            return
        folder = W.QFileDialog.getExistingDirectory(self, "Folder for the photos", str(Path.cwd()))
        if not folder:
            return
        files = self.export_photos(folder)
        W.QMessageBox.information(self, "Save all photos", f"{len(files)} images saved in\n{folder}")

    def report_dialog(self):
        if not any(r.path in self.results for r in self.records):
            W.QMessageBox.information(self, "Report", "Analyse the photos first (they need a scale).")
            return
        project = self.ask_project_name("write the report") if self.ask_project_name else self.project_name()
        if not project:
            return                                        # no project name: nothing is written
        f, flt = W.QFileDialog.getSaveFileName(self, "Photo analysis report", str(Path.cwd() / "photo_report.html"),
                                               "HTML report (*.html);;PDF report (*.pdf);;Word report (*.docx)")
        if f:
            if "docx" in flt.lower() and not f.lower().endswith(".docx"):
                f += ".docx"
            elif "pdf" in flt.lower() and not f.lower().endswith(".pdf"):
                f += ".pdf"
            try:
                self.write_report(f, project)
            except ImportError as e:
                W.QMessageBox.warning(self, "Report", f"The Word report needs the python-docx package ({e}).\n\n"
                                      "Install it with:  pip install python-docx\n"
                                      "(or choose the HTML or PDF format, which need nothing more).")
                return
            except Exception as e:                       # never lose the session because of a report
                W.QMessageBox.warning(self, "Report", f"The report could not be written:\n{e}")
                return
            W.QMessageBox.information(self, "Report", f"Report saved:\n{f}")

    def write_report(self, path, project=None) -> Path:
        """HTML (self-contained), PDF or Word, by the extension of path; the project name, program version
        and date are printed under the title."""
        project = self.project_name() if project is None else project
        from .. import photoreport as pr
        path = Path(path)
        predicted = None
        design = self.design_provider()
        if design is not None:
            x = np.geomspace(0.5, 150, 300)
            curve = stope_passing_curve(design, x)
            if curve is not None:
                predicted = (x, curve)
        if path.suffix.lower() == ".docx":
            return pr.write_docx(path, self.records, self.results, self._image, predicted, self.log_x.isChecked(),
                                project=project)
        body, imgs = pr.build(self.records, self.results, self._image, predicted, self.log_x.isChecked(),
                              img_w=640 if path.suffix.lower() == ".pdf" else 760, project=project)
        if path.suffix.lower() != ".pdf":
            return pr.write_html(path if path.suffix else path.with_suffix(".html"), body, imgs)
        doc = G.QTextDocument()
        doc.setDefaultStyleSheet("body{font-family:Arial;font-size:9pt} h1{color:#16304f} h2{color:#16304f} "
                                 "th{background-color:#eef2f7} table{border-collapse:collapse}")
        for name, data in imgs.items():
            im = G.QImage(); im.loadFromData(data)
            doc.addResource(G.QTextDocument.ImageResource, C.QUrl(name), im)
        doc.setHtml(body)
        wr = G.QPdfWriter(str(path))
        wr.setPageSize(G.QPageSize(G.QPageSize.A4))
        wr.setPageMargins(C.QMarginsF(15, 15, 15, 15), G.QPageLayout.Millimeter)
        wr.setResolution(96)
        doc.setPageSize(C.QSizeF(wr.width(), wr.height()))
        doc.print_(wr)
        return path

    def export_photos(self, folder) -> list[Path]:
        """For each analysed photo: *_fragments.png (outlined fragments + scale bar, the analysed area),
        *_analysed_area.png (the same area without outlines) and, when an area of interest was used,
        *_overview.png (whole photo with the area outlined).  Returns the files written."""
        import cv2
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        out = []
        for r in self.records:
            res = self.results.get(r.path)
            if res is None or res.overlay is None:
                continue
            stem = Path(r.path).stem
            q = folder / f"photo_{stem}_fragments.png"
            cv2.imwrite(str(q), ia.add_scale_bar(res.overlay, res.overlay_px_per_cm))
            out.append(q)
            raw = self._image(r)
            roi = r.analysed_with.get("roi") or []
            if raw is not None:
                part, _ = ia.crop_roi(raw, roi)
                q = folder / f"photo_{stem}_analysed_area.png"
                oh, ow = res.overlay.shape[:2]
                cv2.imwrite(str(q), ia.add_scale_bar(cv2.resize(part, (ow, oh), interpolation=cv2.INTER_AREA),
                                                      res.overlay_px_per_cm))
                out.append(q)
                if len(roi) == 4:
                    ov = raw.copy()
                    x0, y0, x1, y1 = [int(v) for v in roi]
                    cv2.rectangle(ov, (x0, y0), (x1, y1), (255, 229, 0), max(3, raw.shape[1] // 250))
                    q = folder / f"photo_{stem}_overview.png"
                    cv2.imwrite(str(q), ia.add_scale_bar(ov, r.scale_px_per_cm or 0))
                    out.append(q)
        return out

    def export(self, folder) -> list[Path]:
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        out = []
        p = folder / "photo_analysis_summary.csv"
        keys = ["n_fragments", "d10_cm", "d20_cm", "d50_cm", "d80_cm", "d90_cm", "dmax_cm", "rr_n", "rr_xc_cm",
                "unresolved_area_fraction"]
        with open(p, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["file", "date", "location", "notes", "scale_px_per_cm", "min_size_cm", "sensitivity", "segmentation", "parameters_used_for_results", *keys])
            for r in self.records:
                w.writerow([r.path, r.date, r.location, r.notes, r.scale_px_per_cm, r.min_size_cm, r.sensitivity, json.dumps(r.seg), json.dumps(r.analysed_with),
                            *[r.summary.get(k, "") for k in keys]])
        out.append(p)
        out += self.export_photos(folder)
        pooled = self.pooled()
        if pooled:
            d, pa = ia.volume_weighted_curve(pooled["sizes_cm"])
            q = folder / "photo_combined_distribution.csv"
            with open(q, "w", newline="", encoding="utf-8") as fh:
                w = csv.writer(fh)
                w.writerow(["size_cm", "passing_fraction_volume_weighted"])
                w.writerows(zip(d, pa))
            out.append(q)
        return out
