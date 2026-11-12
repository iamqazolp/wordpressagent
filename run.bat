@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONUTF8=1
set GRADIO_ANALYTICS_ENABLED=False
set HF_HUB_DISABLE_TELEMETRY=1
if not exist ".venv\Scripts\python.exe" call install.bat
if not exist ".venv\Scripts\python.exe" exit /b 1
rem Cap nhat ban moi: requirements.txt doi thi cai lai thu vien (giong cua so khoi dong), neu khong se loi ImportError
".venv\Scripts\python.exe" tools\install_deps.py --if-needed
if errorlevel 1 ( echo [X] Cai thu vien that bai. Kiem tra ket noi mang roi chay lai. & pause & exit /b 1 )
".venv\Scripts\python.exe" app.py
echo.
echo Ung dung da dung. Neu co loi, chup man hinh nay gui cho nguoi ho tro.
pause
