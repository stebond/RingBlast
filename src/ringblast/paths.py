"""Locations of bundled resources and of the user data, for source, installed and portable runs.

* resource_root(): folder that holds database/, docs/, launcher/, examples/ (the project folder when
  run from source, the PyInstaller bundle when frozen).
* app_dir(): folder of the program the user sees (project folder, or the folder of RingBlast.exe).
* user_dir(): where settings, user database rows and extracted project photos are stored.
  - $RINGBLAST_HOME if set;
  - portable mode: <app_dir>/RingBlast_data when the program is frozen (RingBlast.exe) or when a file
    named "portable.txt" exists in the project folder;
  - otherwise ~/.ringblast.
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
    if portable():
        return app_dir() / "RingBlast_data"
    return Path.home() / ".ringblast"
