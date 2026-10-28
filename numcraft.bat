@echo off
rem Два способа:
rem  1) перетащить STEP и/или PDF на значок numcraft.bat;
rem  2) открыть numcraft.bat двойным щелчком, перетащить файлы в окно и нажать Enter.
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

cd /d "%~dp0src"

if not "%~1"=="" (
  %PY% -m numcraft plan %* --gcode --open
  echo.
  pause
  exit /b
)

:ask
echo.
echo ============================================================
echo  Перетащите в это окно STEP-модель и/или PDF чертежа детали
echo  (можно по очереди), затем нажмите Enter.
echo  Пустой Enter - выход.
echo ============================================================
set "FILES="
set /p FILES=Файлы: 
if not defined FILES exit /b
%PY% -m numcraft plan %FILES% --gcode --open
goto ask
