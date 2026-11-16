@echo off
rem Builds the PORTABLE Windows program: dist\RingBlast\RingBlast.exe + dist\RingBlast-portable-<version>-windows.zip
rem Needs Python 3.10+ on this computer (build only; the result does not). Run it by double-click.
cd /d "%~dp0.."
if not exist ".venv\Scripts\python.exe" call RingBlast.bat nostart
".venv\Scripts\python.exe" -m pip install --upgrade pyinstaller || exit /b 1
".venv\Scripts\python.exe" launcher\build_portable.py
pause
