# ============================================================
#   Sitetracker Data Hub - Windows PowerShell Launcher (Port 8080)
# ============================================================
Write-Host "Starting Sitetracker Data Hub on http://localhost:8080 ..." -ForegroundColor Cyan

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir
$env:PYTHONPATH = $ScriptDir

python -m streamlit run app.py --server.port 8080
