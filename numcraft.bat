rem NumCraft: drag STEP and/or PDF drawing onto this file,
rem or double-click it and drag the files into the window.
@echo off
setlocal
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

rem --- find Python: "python" or the "py" launcher
set "PY="
python --version >nul 2>&1 && set "PY=python"
if not defined PY py --version >nul 2>&1 && set "PY=py"
if not defined PY (
  echo Python not found. Install it from https://www.python.org/downloads/
  echo and tick "Add python.exe to PATH" in the first installer window.
  pause
  exit /b 1
)

rem --- first run: install libraries
%PY% -c "import pydantic, yaml, pypdf, cryptography" >nul 2>&1
if errorlevel 1 (
  echo First run: installing pydantic, pyyaml, pypdf, cryptography ...
  %PY% -m pip install --user pydantic pyyaml pypdf cryptography
  if errorlevel 1 (
    echo Could not install libraries. Check the internet connection and try again.
    pause
    exit /b 1
  )
)

cd /d "%~dp0src"
%PY% -m numcraft drop %*
echo.
pause
