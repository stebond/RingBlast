"""Update check in the GUI: a background thread asks GitHub, the main thread asks the user."""
from __future__ import annotations

from PySide6 import QtCore as C
from PySide6 import QtGui as G
from PySide6 import QtWidgets as W

from .. import paths, updates
from ..about import VERSION


class _Worker(C.QThread):
    """Runs updates.check() off the GUI thread (the network can be slow or absent)."""
    result = C.Signal(object, str)          # (UpdateInfo | None, error text)

    def __init__(self, manual: bool, parent=None) -> None:
        super().__init__(parent)
        self.manual = manual

    def run(self) -> None:
        try:
            self.result.emit(updates.check(manual=self.manual), "")
        except updates.UpdateError as e:
            self.result.emit(None, str(e))
        except Exception as e:                # never let a check crash the program
            self.result.emit(None, f"Unexpected error: {e}")


class UpdateChecker(C.QObject):
    def __init__(self, window: W.QWidget) -> None:
        super().__init__(window)
        self.win = window
        self._worker = None

    def start(self, manual: bool = False) -> None:
        """manual=True: always tell the user the outcome; False: stay silent unless there is news."""
        if self._worker is not None and self._worker.isRunning():
            return
        if not manual and not updates.due_for_auto_check():
            return
        self._worker = _Worker(manual, self)
        self._worker.result.connect(lambda info, err: self._done(info, err, manual))
        self._worker.start()

    def _done(self, info, err: str, manual: bool) -> None:
        if err:
            if manual:
                W.QMessageBox.information(self.win, "Check for updates",
                                          f"The check could not be done.\n\n{err}\n\nYou can look at {updates.PAGE} yourself.")
        elif info is None:
            if manual:
                W.QMessageBox.information(self.win, "Check for updates",
                                          f"RingBlast {VERSION} is the latest version.")
        else:
            self.ask(info)

    def ask(self, info: updates.UpdateInfo) -> str:
        """Tell the user a new version exists and ask whether to download it. Returns the choice."""
        box = W.QMessageBox(self.win)
        box.setIcon(W.QMessageBox.Icon.Information)
        box.setWindowTitle("Update available")
        box.setText(f"<b>RingBlast {info.version}</b> is available (you have {VERSION}). "
                    "Do you want to download the new version?")
        if paths.frozen():
            how = "The portable program will be downloaded as a zip file: unzip it in a new folder and run it. " \
                  "Your projects and settings are not touched."
        else:
            how = "The release page will open. If you installed from source, update with git pull " \
                  "or download the new files."
        notes = "\n".join(info.notes.splitlines()[:12])
        box.setInformativeText(how)
        if notes:
            box.setDetailedText(f"{info.tag}  {info.published}\n\n{notes}")
        yes = box.addButton("Download", W.QMessageBox.ButtonRole.AcceptRole)
        later = box.addButton("Remind me later", W.QMessageBox.ButtonRole.RejectRole)
        skip = box.addButton("Skip this version", W.QMessageBox.ButtonRole.DestructiveRole)
        box.setDefaultButton(yes)
        box.exec()
        clicked = box.clickedButton()
        if clicked is yes:
            G.QDesktopServices.openUrl(C.QUrl(info.asset_url or info.page_url))
            return "download"
        if clicked is skip:
            updates.save_settings(skip_version=info.version)
            return "skip"
        return "later"
