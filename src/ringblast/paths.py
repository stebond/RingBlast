"""Locations of bundled resources and of the user data, for source, installed and portable runs.

* resource_root(): folder that holds database/, docs/, launcher/, examples/ (the project folder when
  run from source, the PyInstaller bundle when frozen).
* app_dir(): folder of the program the user sees (project folder, or the folder of RingBlast.exe).
* user_dir(): where settings, user database rows and extracted project photos are stored.
  - $RINGBLAST_HOME if set;
  - portable mode: <app_dir>/RingBlast_data when the program is frozen (RingBlast.exe, ./RingBlast) or
    when a file named "portable.txt" exists in the project folder (if that folder is read-only,
    ~/.ringblast is used instead);
  - frozen macOS app: ~/Library/Application Support/RingBlast (the .app bundle is read-only);
  - otherwise ~/.ringblast.
* work_dir(): default parent of the "projects" and "output" folders: the program folder when it is
  writable (portable Windows/Linux), otherwise ~/Documents/RingBlast (macOS app, read-only installs).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def resource_root() -> Path:
    if frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parents[2]


def app_dir() -> Path:
    if frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def portable() -> bool:
    return frozen() or (app_dir() / "portable.txt").exists()


def user_dir() -> Path:
    env = os.environ.get("RINGBLAST_HOME")
    if env:
        return Path(env)
    if frozen() and sys.platform == "darwin":
        # the .app bundle is read-only once installed/quarantined: use the standard macOS folder
        return Path.home() / "Library" / "Application Support" / "RingBlast"
    if portable():
        d = app_dir() / "RingBlast_data"
        # a read-only location (e.g. /opt, a CD) cannot hold the data: use the home folder instead
        if os.access(d if d.exists() else app_dir(), os.W_OK):
            return d
    return Path.home() / ".ringblast"


def work_dir() -> Path:
    """Folder that holds the default 'projects' and 'output' folders shown to the user."""
    env = os.environ.get("RINGBLAST_WORK")
    if env:
        return Path(env)
    base = app_dir()
    if not (frozen() and sys.platform == "darwin") and os.access(base, os.W_OK):
        return base
    return Path.home() / "Documents" / "RingBlast"
