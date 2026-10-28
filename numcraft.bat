@echo off
rem Перетащите на этот файл STEP и/или PDF чертежа детали - техкарта откроется в браузере.
chcp 65001 >nul
set PYTHONUTF8=1

rem Ищем Python: сначала python, затем лаунчер py
set "PY="
python --version >nul 2>&1 && set "PY=python"
if not defined PY py --version >nul 2>&1 && set "PY=py"
if not defined PY (
  echo Python не найден.
  echo Установите его с https://www.python.org/downloads/
  echo В первом окне установщика отметьте "Add python.exe to PATH".
  pause
  exit /b 1
)

rem При первом запуске ставим библиотеки
%PY% -c "import pydantic, yaml, pypdf" >nul 2>&1
if errorlevel 1 (
  echo Первый запуск: устанавливаю библиотеки pydantic, pyyaml, pypdf...
  %PY% -m pip install --user pydantic pyyaml pypdf
  if errorlevel 1 (
    echo Не удалось установить библиотеки. Проверьте интернет и повторите.
    pause
    exit /b 1
  )
)

if "%~1"=="" (
  echo Всё готово. Перетащите на numcraft.bat файлы детали: STEP-модель и PDF чертежа.
  pause
  exit /b
)
cd /d "%~dp0src"
%PY% -m numcraft plan %* --gcode --open
if errorlevel 1 pause
