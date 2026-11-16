"""Help menu windows: user manual and About dialog."""
from __future__ import annotations

import platform
import sys
from pathlib import Path

from PySide6 import QtCore as C
from PySide6 import QtGui as G
from PySide6 import QtWidgets as W

from .. import about, paths

ROOT = paths.resource_root()
MANUAL = ROOT / "docs" / "manual.html"


def _icon_path() -> Path | None:
    p = ROOT / "launcher" / "ringblast.png"
    return p if p.exists() else None


class ManualDialog(W.QDialog):
    """Shows docs/manual.html (links and screenshots work); not modal, so it can stay open while working."""

    def __init__(self, parent=None, icon: G.QIcon | None = None):
        super().__init__(parent)
        self.setWindowTitle(f"{about.NAME} - user manual")
        if icon is not None:
            self.setWindowIcon(icon)
        self.resize(980, 760)
        self.browser = W.QTextBrowser()
        self.browser.setOpenExternalLinks(True)
        if MANUAL.exists():
            self.browser.setSource(C.QUrl.fromLocalFile(str(MANUAL)))
        else:
            self.browser.setHtml(f"<h2>Manual not found</h2><p>Expected file: {MANUAL}</p>")
        self.find = W.QLineEdit(); self.find.setPlaceholderText("Find in the manual (Enter = next)")
        self.find.returnPressed.connect(self._find_next)
        back = W.QPushButton("Back"); back.clicked.connect(self.browser.backward)
        top = W.QPushButton("Contents"); top.clicked.connect(lambda: self.browser.scrollToAnchor("start") or
                                                             self.browser.verticalScrollBar().setValue(0))
        ext = W.QPushButton("Open in web browser"); ext.clicked.connect(self._open_external)
        ext.setEnabled(MANUAL.exists())
        close = W.QPushButton("Close"); close.clicked.connect(self.close)
        bar = W.QHBoxLayout()
        for w in (back, top, self.find): bar.addWidget(w, 1 if w is self.find else 0)
        bar.addWidget(ext); bar.addWidget(close)
        lay = W.QVBoxLayout(self); lay.addLayout(bar); lay.addWidget(self.browser, 1)

    def _find_next(self):
        text = self.find.text()
        if text and not self.browser.find(text):
            self.browser.moveCursor(G.QTextCursor.Start)        # wrap around
            self.browser.find(text)

    def _open_external(self):
        G.QDesktopServices.openUrl(C.QUrl.fromLocalFile(str(MANUAL)))


def system_info() -> str:
    """Versions of the program and of its main libraries (for bug reports)."""
    import matplotlib
    import numpy
    import PySide6
    lines = [f"{about.NAME} {about.VERSION}", f"Python {sys.version.split()[0]} ({platform.platform()})",
             f"PySide6 {PySide6.__version__}, numpy {numpy.__version__}, matplotlib {matplotlib.__version__}"]
    try:
        import cv2
        lines.append(f"OpenCV {cv2.__version__}")
    except Exception:
        pass
    try:
        import ezdxf
        lines.append(f"ezdxf {ezdxf.__version__}")
    except Exception:
        pass
    return "\n".join(lines)


class AboutDialog(W.QDialog):
    def __init__(self, parent=None, icon: G.QIcon | None = None):
        super().__init__(parent)
        self.setWindowTitle(f"About {about.NAME}")
        if icon is not None:
            self.setWindowIcon(icon)
        self.setMinimumWidth(560)
        logo = W.QLabel(); logo.setAlignment(C.Qt.AlignTop)
        ip = _icon_path()
        if ip:
            logo.setPixmap(G.QPixmap(str(ip)).scaled(160, 160, C.Qt.KeepAspectRatio, C.Qt.SmoothTransformation))
        authors = "<br>".join(about.AUTHORS)
        text = W.QLabel(
            f"<h2 style='margin:0'>{about.NAME}</h2>"
            f"<p><b>Version {about.VERSION}</b> &nbsp;&middot;&nbsp; {about.YEAR}</p>"
            f"<p>{about.DESCRIPTION}</p>"
            f"<p><b>Authors</b><br>{authors}</p>"
            f"<p>{about.AFFILIATION}</p>"
            f"<p><b>Contact:</b> <a href='mailto:{about.CONTACT}'>{about.CONTACT}</a><br>"
            f"<b>License:</b> {about.LICENSE}</p>"
            f"<p><b>How to cite</b><br>{about.CITATION}</p>")
        text.setWordWrap(True); text.setTextFormat(C.Qt.RichText); text.setOpenExternalLinks(True)
        text.setTextInteractionFlags(C.Qt.TextBrowserInteraction)
        row = W.QHBoxLayout(); row.addWidget(logo); row.addWidget(text, 1)
        self.info = system_info()
        copy = W.QPushButton("Copy program information")
        copy.setToolTip("Copies the versions of the program and its libraries (useful in a bug report)")
        copy.clicked.connect(lambda: W.QApplication.clipboard().setText(f"{self.info}\n\n{about.CITATION}"))
        ok = W.QPushButton("Close"); ok.setDefault(True); ok.clicked.connect(self.accept)
        btns = W.QHBoxLayout(); btns.addWidget(copy); btns.addStretch(1); btns.addWidget(ok)
        lay = W.QVBoxLayout(self); lay.addLayout(row); lay.addLayout(btns)
        self.setMinimumHeight(430)
        self.setSizeGripEnabled(True)
        self.adjustSize()
