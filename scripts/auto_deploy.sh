#!/bin/bash

# ==============================================================================
# POC Input Generator - Auto Deployment Script
# This script is designed to be run via a cron job on the Oracle Ubuntu Server.
# It checks for updates on the remote repository and pulls them automatically.
# ==============================================================================

# Get the absolute path of the project directory (one level up from this script)
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Define where to save the logs
LOG_FILE="$PROJECT_DIR/runs/auto_deploy.log"

# Navigate to the project directory
cd "$PROJECT_DIR" || { echo "Failed to cd to $PROJECT_DIR"; exit 1; }

# Fetch the latest changes from the remote without outputting to terminal
git fetch > /dev/null 2>&1

# Compare the local branch with the remote tracking branch
LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse @{u})

if [ "$LOCAL" != "$REMOTE" ]; then
    echo "------------------------------------------------" >> "$LOG_FILE"
    echo "$(date): New commits detected. Updating..." >> "$LOG_FILE"
    
    # Pull the changes
    git pull >> "$LOG_FILE" 2>&1
    
    echo "$(date): Code updated successfully." >> "$LOG_FILE"
    
    # Note: Streamlit usually auto-reloads upon detecting file changes.
    # If you ever need to forcefully restart the Streamlit systemd service,
    # you can uncomment the line below (requires sudo permissions for the cron user):
    # sudo systemctl restart streamlit.service
fi
