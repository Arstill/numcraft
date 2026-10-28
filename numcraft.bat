@echo off
rem Перетащите на этот файл STEP и/или PDF чертежа детали — техкарта откроется в браузере.
chcp 65001 >nul
set PYTHONUTF8=1
if "%~1"=="" (
  echo Перетащите на numcraft.bat файлы детали: STEP-модель и PDF чертежа.
  pause
  exit /b
)
cd /d "%~dp0src"
python -m numcraft plan %* --gcode --open
if errorlevel 1 pause
