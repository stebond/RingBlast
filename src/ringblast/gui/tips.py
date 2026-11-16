"""Tooltips (help hints): one switch for the whole program, remembered on this computer.

Every parameter and button has a tooltip.  Experienced users can turn them off in the Settings
tab; the switch works with an application-wide event filter, so it covers every widget at once.
"""
from __future__ import annotations

import json

from PySide6 import QtCore as C
from PySide6 import QtWidgets as W

from .. import db

_state = {"enabled": True, "loaded": False}


def _file():
    return db.USER_DIR / "ui_settings.json"


def enabled() -> bool:
    if not _state["loaded"]:
        _state["loaded"] = True
        try:
            _state["enabled"] = bool(json.loads(_file().read_text(encoding="utf-8")).get("tooltips", True))
        except Exception:
            _state["enabled"] = True
    return _state["enabled"]


def set_enabled(on: bool) -> None:
    _state.update(enabled=bool(on), loaded=True)
    try:
        from .. import updates                      # merge into the shared settings file
        updates.save_settings(tooltips=bool(on))
    except OSError:
        pass


class TooltipFilter(C.QObject):
    def eventFilter(self, obj, ev):
        if ev.type() == C.QEvent.ToolTip and not enabled():
            return True                       # swallow the tooltip event: nothing is shown
        return False


_filter = None


def install(app: W.QApplication) -> None:
    global _filter
    if _filter is None:
        _filter = TooltipFilter(app)
        app.installEventFilter(_filter)


def by_text(root: W.QWidget, mapping: dict[str, str]) -> None:
    """Set tooltips on the push buttons of `root` identified by their text."""
    for b in root.findChildren(W.QPushButton):
        if b.text() in mapping:
            b.setToolTip(mapping[b.text()])


def set_all(pairs) -> None:
    for w, t in pairs:
        w.setToolTip(t)
