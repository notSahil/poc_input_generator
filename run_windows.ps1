# ============================================================
#   Sitetracker Data Hub - Windows PowerShell Launcher
# ============================================================
Write-Host "Starting Sitetracker Data Hub..." -ForegroundColor Cyan

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir
$env:PYTHONPATH = $ScriptDir

python -m streamlit run app.py
