"""Builds the portable RingBlast (no Python needed on the target computer).

    python launcher/build_portable.py

Result: dist/RingBlast/ (RingBlast.exe on Windows) and dist/RingBlast-portable-<version>-<os>.zip.
Copy the folder (or unzip the zip) anywhere, e.g. on a USB stick: the settings, the user database rows and
the photos of the opened projects are stored in RingBlast_data next to the program.
PyInstaller does not cross-compile: run this on Windows to get a Windows program (see
.github/workflows/build-windows.yml to do it automatically on GitHub).
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from ringblast import __version__  # noqa: E402

SEP = ";" if sys.platform == "win32" else ":"
NAME = "RingBlast"
TAG = {"win32": "windows", "darwin": "macos"}.get(sys.platform, "linux")
EXCLUDES = ["tkinter", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtQuick", "PySide6.QtQml",
            "PySide6.Qt3DCore", "PySide6.QtMultimedia", "PySide6.QtPdf", "PySide6.QtSql", "PySide6.QtNetwork",
            "PySide6.QtDesigner", "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtBluetooth",
            "pytest", "IPython", "scipy", "pandas"]


def main() -> int:
    for d in ("build", "dist"):
        shutil.rmtree(ROOT / d, ignore_errors=True)
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed", "--name", NAME,
           "--paths", "src", "--collect-submodules", "ringblast",
           "--collect-data", "docx"]
    icon = ROOT / "launcher" / "ringblast.ico"
    if sys.platform == "win32" and icon.exists():
        cmd += ["--icon", str(icon)]
    for src in ("database", "examples", "docs", "figures", "launcher"):
        cmd += ["--add-data", f"{ROOT / src}{SEP}{src}"]
    for m in EXCLUDES:
        cmd += ["--exclude-module", m]
    cmd.append("launcher/ringblast_entry.py")
    print(" ".join(cmd))
    if subprocess.call(cmd, cwd=ROOT) != 0:
        return 1
    out = ROOT / "dist" / NAME
    # folders the program offers by default, plus a short note for the user
    for d in ("projects", "output"):
        (out / d).mkdir(exist_ok=True)
    (out / "README.txt").write_text(
        "RingBlast - portable version\r\n\r\n"
        "Start RingBlast.exe (Windows). No installation and no Python are needed.\r\n"
        "Settings, your own rocks/explosives and the photos of opened projects are stored in the folder\r\n"
        "RingBlast_data next to the program, so the whole folder can be moved or copied (USB stick).\r\n"
        "Projects are saved by default in 'projects', exported results in 'output'.\r\n"
        "Help > User manual (F1) opens the manual. Licence: MIT.\r\n", encoding="utf-8")
    zpath = ROOT / "dist" / f"{NAME}-portable-{__version__}-{TAG}.zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(out.rglob("*")):
            if f.is_file():
                z.write(f, Path(NAME) / f.relative_to(out))
    print("built:", out, "\nzip:", zpath, f"({zpath.stat().st_size / 1e6:.0f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
