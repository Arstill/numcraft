@echo off
rem Перетащите на этот файл PDF каталога ZCC - рядом появится .txt с текстом каталога.
rem Этот .txt (он намного меньше PDF) можно отправить, чтобы подключить фрезы и свёрла из каталога.
chcp 65001 >nul
set PYTHONUTF8=1
set "PY="
python --version >nul 2>&1 && set "PY=python"
if not defined PY py --version >nul 2>&1 && set "PY=py"
if not defined PY (
  echo Python не найден. Установите с https://www.python.org/downloads/ ^(галочка "Add python.exe to PATH"^).
  pause
  exit /b 1
)
%PY% -c "import pypdf" >nul 2>&1 || %PY% -m pip install --user pypdf
if "%~1"=="" (
  echo Перетащите на этот файл PDF каталога ZCC.
  pause
  exit /b
)
cd /d "%~dp0src"
%PY% -m numcraft catalog text "%~1" -o "%~dpn1.txt"
echo.
pause
