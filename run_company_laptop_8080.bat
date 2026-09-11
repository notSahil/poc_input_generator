@echo off
REM ============================================================
REM   Sitetracker Data Hub - Company Laptop Launcher (Port 8080)
REM ============================================================
echo ============================================================
echo   Starting Sitetracker Data Hub on Port 8080...
echo   Open your browser to: http://localhost:8080
echo ============================================================
cd /d "%~dp0"
set PYTHONPATH=%CD%
python -m streamlit run app.py --server.port 8080
pause
