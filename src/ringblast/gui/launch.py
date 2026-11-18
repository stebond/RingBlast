"""Start-up with a splash screen: the window appears at once and a progress bar follows the loading of
the libraries and of the program (the first start of a freshly installed program can take 20-30 s).

Only PySide6 is imported before the splash screen is shown; everything else is imported step by step.
"""
from __future__ import annotations

import sys
import time

from PySide6 import QtCore as C
from PySide6 import QtGui as G
from PySide6 import QtWidgets as W

from .. import __version__, paths

NAVY, AMBER = G.QColor("#16304f"), G.QColor("#f0a020")
SIZE = (560, 320)


def _logo() -> G.QPixmap:
    for name in ("ringblast.png", "ringblast.ico"):
        f = paths.resource_root() / "launcher" / name
        if f.exists():
            return G.QPixmap(str(f))
    return G.QPixmap()


class Splash(W.QSplashScreen):
    """Splash screen drawn by code: logo, name, version, status line and a progress bar."""

    def __init__(self) -> None:
        pm = G.QPixmap(*SIZE)
        pm.fill(NAVY)
        super().__init__(pm, C.Qt.WindowType.WindowStaysOnTopHint | C.Qt.WindowType.SplashScreen)
        self._logo = _logo()
        self.value, self.text = 0.0, "Starting..."
        self._redraw()

    def _redraw(self) -> None:
        w, h = SIZE
        pm = G.QPixmap(w, h)
        pm.fill(NAVY)
        p = G.QPainter(pm)
        p.setRenderHint(G.QPainter.RenderHint.Antialiasing)
        p.setRenderHint(G.QPainter.RenderHint.SmoothPixmapTransform)
        if not self._logo.isNull():
            p.drawPixmap(C.QRect(36, 40, 120, 120), self._logo)
        p.setPen(G.QColor("white"))
        f = G.QFont("Segoe UI", 30, G.QFont.Weight.Bold)
        p.setFont(f)
        p.drawText(C.QRect(180, 48, 360, 56), C.Qt.AlignmentFlag.AlignVCenter, "RingBlast")
        p.setPen(G.QColor("#b8c7da"))
        p.setFont(G.QFont("Segoe UI", 10))
        p.drawText(C.QRect(182, 104, 360, 22), C.Qt.AlignmentFlag.AlignVCenter,
                   "Ring blast design and fragmentation analysis")
        p.drawText(C.QRect(182, 128, 360, 22), C.Qt.AlignmentFlag.AlignVCenter, f"Version {__version__}")
        p.setPen(AMBER)
        p.drawLine(36, 190, w - 36, 190)
        p.setPen(G.QColor("white"))
        p.setFont(G.QFont("Segoe UI", 9))
        p.drawText(C.QRect(36, 212, w - 72, 22), C.Qt.AlignmentFlag.AlignVCenter, self.text)
        bar = C.QRectF(36, 244, w - 72, 12)
        p.setPen(C.Qt.PenStyle.NoPen)
        p.setBrush(G.QColor("#2b4a70"))
        p.drawRoundedRect(bar, 6, 6)
        fill = C.QRectF(bar.x(), bar.y(), max(12.0, bar.width() * self.value), bar.height())
        p.setBrush(AMBER)
        p.drawRoundedRect(fill, 6, 6)
        p.setPen(G.QColor("#8aa0bb"))
        p.setFont(G.QFont("Segoe UI", 8))
        p.drawText(C.QRect(36, 280, w - 72, 20), C.Qt.AlignmentFlag.AlignVCenter,
                   "University of Bologna - DICAM   |   MIT License")
        p.end()
        self.setPixmap(pm)

    def step(self, value: float, text: str) -> None:
        self.value, self.text = value, text
        self._redraw()
        W.QApplication.processEvents()


def _steps():
    """(progress after the step, message, function): real imports, in the order the program needs them."""
    def numpy_():
        import numpy  # noqa: F401

    def mpl():
        import matplotlib
        import matplotlib.backends.backend_qtagg  # noqa: F401

    def dxf():
        import ezdxf  # noqa: F401

    def image():
        import cv2  # noqa: F401
        import PIL  # noqa: F401

    def engine():
        from .. import burden, charging, design, export, fragmentation, geometry, imageanalysis, project  # noqa: F401

    def data():
        from .. import db
        db.load_rocks()
        db.load_explosives()

    def gui():
        from . import app  # noqa: F401

    return [(0.10, "Loading numerical library (numpy)...", numpy_),
            (0.30, "Loading plotting library (matplotlib)...", mpl),
            (0.40, "Loading DXF export (ezdxf)...", dxf),
            (0.60, "Loading image analysis (OpenCV)...", image),
            (0.72, "Loading calculation engine...", engine),
            (0.80, "Reading rock and explosive databases...", data),
            (0.92, "Loading user interface...", gui)]


def main() -> int:
    if "--selftest" in sys.argv:
        from .app import selftest
        return selftest()
    if sys.platform == "win32":             # own taskbar identity, so the taskbar shows the RingBlast icon
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("UniBo.RingBlast")
        except Exception:
            pass
    t0 = time.time()
    qapp = W.QApplication.instance() or W.QApplication(sys.argv)
    splash = Splash()
    splash.show()
    splash.step(0.03, "Starting...")
    for value, text, fn in _steps():
        splash.step(value - 0.05, text)
        fn()
        splash.step(value, text)
    splash.step(0.95, "Creating the main window...")
    from . import app
    qapp.setWindowIcon(app.app_icon())
    app.tips.install(qapp)
    win = app.MainWindow()
    splash.step(1.0, "Ready")
    win.showMaximized()                      # fills the screen: nothing can run beyond its edges
    # keep the splash visible for a moment even on a fast start, so it does not just flash
    while time.time() - t0 < 1.2:
        W.QApplication.processEvents()
        time.sleep(0.02)
    splash.finish(win)
    return qapp.exec()


if __name__ == "__main__":
    sys.exit(main())
