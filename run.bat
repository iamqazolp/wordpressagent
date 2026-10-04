@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONUTF8=1
if not exist ".venv\Scripts\python.exe" call install.bat
if not exist ".venv\Scripts\python.exe" exit /b 1
".venv\Scripts\python.exe" app.py
echo.
echo Ung dung da dung. Neu co loi, chup man hinh nay gui cho nguoi ho tro.
pause
