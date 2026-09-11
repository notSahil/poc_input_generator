#!/usr/bin/env bash
# ============================================================
#   Sitetracker Data Hub - Company Laptop Launcher (Port 8080)
# ============================================================
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
export PYTHONPATH="$SCRIPT_DIR"

echo "============================================================"
echo "  Starting Sitetracker Data Hub on Port 8080..."
echo "  Open your browser to: http://localhost:8080"
echo "============================================================"

if [ -d ".venv" ]; then
    .venv/bin/streamlit run app.py --server.port 8080
elif command -v streamlit &> /dev/null; then
    streamlit run app.py --server.port 8080
else
    python3 -m streamlit run app.py --server.port 8080
fi
