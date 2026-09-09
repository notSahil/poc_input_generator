@echo off
REM ============================================================
REM   Sitetracker Data Hub - Windows Installer
REM ============================================================
echo ============================================================
echo   Installing Sitetracker Data Hub Dependencies
echo ============================================================
cd /d "%~dp0"
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
echo.
echo ============================================================
echo   Installation Complete!
echo   Run 'run_windows.bat' to start the application.
echo ============================================================
pause
