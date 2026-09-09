@echo off
REM ============================================================
REM   Sitetracker Data Hub - Windows Launcher
REM ============================================================
echo ============================================================
echo   Starting Sitetracker Data Hub...
echo ============================================================
cd /d "%~dp0"
set PYTHONPATH=%CD%
python -m streamlit run app.py
pause
