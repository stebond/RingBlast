@echo off
setlocal
rem ==== RingBlast launcher: double-click to start. On the first run it sets up its own environment. ====
cd /d "%~dp0"
set "VENV=%~dp0.venv"
set "PYW=%VENV%\Scripts\pythonw.exe"

if exist "%PYW%" goto run

echo ============================================================
echo  RingBlast - first run: setting up (2-5 minutes)
echo  An internet connection is required. Do not close this window.
echo ============================================================

rem Look for Python 3.10 or newer
set "PY="
py -3 -c "import sys; sys.exit(0 if sys.version_info[:2]>=(3,10) else 1)" >nul 2>&1 && set "PY=py -3"
if not defined PY (
  python -c "import sys; sys.exit(0 if sys.version_info[:2]>=(3,10) else 1)" >nul 2>&1 && set "PY=python"
)
if not defined PY (
  echo Python 3.10 or newer was not found. Trying to install it with winget...
  winget install -e --id Python.Python.3.12 --silent --accept-package-agreements --accept-source-agreements
  echo.
  echo If the installation succeeded, close this window and double-click RingBlast.bat again.
  echo Otherwise install Python from https://www.python.org/downloads/ ^(tick "Add python.exe to PATH"^).
  pause
  exit /b 1
)

rem Create the private environment and install RingBlast with its GUI
%PY% -m venv "%VENV%" || goto fail
"%VENV%\Scripts\python.exe" -m pip install --upgrade pip || goto fail
"%VENV%\Scripts\python.exe" -m pip install -e ".[gui]" || goto fail
echo.
echo Setup completed.

:run
rem Install any component added by a program update (checked at every start, takes a second)
"%VENV%\Scripts\python.exe" -c "import PySide6, cv2, PIL, ezdxf, matplotlib, numpy" >nul 2>&1
if errorlevel 1 (
  echo Installing missing components ^(internet connection required^)...
  "%VENV%\Scripts\python.exe" -m pip install -e ".[gui]" || goto fail_update
)
if /i "%~1"=="nostart" exit /b 0
start "" "%PYW%" -m ringblast.gui.launch
exit /b 0

:fail_update
echo.
echo ERROR while installing the missing components. Check the internet connection and try again.
pause
exit /b 1

:fail
echo.
echo ERROR during setup. Check the internet connection and try again.
rmdir /s /q "%VENV%" >nul 2>&1
pause
exit /b 1
