@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1

set "PY="
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)" >nul 2>nul
  if not errorlevel 1 set "PY=py -3"
)
if not defined PY (
  where python >nul 2>nul
  if %errorlevel%==0 (
    python -c "import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)" >nul 2>nul
    if not errorlevel 1 set "PY=python"
  )
)
if not defined PY (
  echo [X] Chua co Python 3.11 tro len. Tai tai https://www.python.org/downloads/
  echo     Khi cai nho tick o "Add python.exe to PATH", sau do chay lai install.bat
  pause
  exit /b 1
)
echo [OK] Da tim thay Python.

rem Tao .env NGAY (truoc khi cai thu vien) de du buoc cai co loi, file van co san.
%PY% tools\init_env.py >nul
set "ENVRC=%errorlevel%"

if not exist ".venv\Scripts\python.exe" (
  %PY% -m venv .venv
  if errorlevel 1 ( echo [X] Khong tao duoc moi truong ao. & pause & exit /b 1 )
)

".venv\Scripts\python.exe" -m pip install --upgrade pip -q
echo Dang cai thu vien (vai phut o lan dau)...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 ( echo [X] Cai thu vien that bai. Kiem tra ket noi mang roi chay lai. & pause & exit /b 1 )
".venv\Scripts\python.exe" -c "from launcher.core import requirements_stamp, _stamp_path; from pathlib import Path; p = Path('.'); _stamp_path(p).write_text(requirements_stamp(p), encoding='utf-8')"

echo.
echo [OK] Cai dat xong.
if "%ENVRC%"=="10" (
  echo Mo file .env va dien GEMINI_API_KEY ^(bat buoc^), roi bam dup run.bat
  start notepad .env
) else (
  echo Bam dup run.bat de mo ung dung.
)
pause
