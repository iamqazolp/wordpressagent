@echo off
rem Du phong neu bam dup WordPressAgent.pyw khong mo: file nay mo no roi tu dong dong (khong de lai cua so den).
cd /d "%~dp0"
where pyw >nul 2>nul
if %errorlevel%==0 (
  start "" pyw -3 WordPressAgent.pyw
  exit /b 0
)
where pythonw >nul 2>nul
if %errorlevel%==0 (
  start "" pythonw WordPressAgent.pyw
  exit /b 0
)
echo [X] Chua tim thay Python 3.11 tro len. Tai tai https://www.python.org/downloads/
echo     Khi cai nho tick o "Add python.exe to PATH", sau do bam dup lai file nay.
pause
exit /b 1
