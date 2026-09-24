# Infrastructure, Deployment & Environment Reference

> **DEVOPS & ENVIRONMENT KNOWLEDGE BASE**  
> Complete operational reference for Oracle Cloud server, GitHub repository, local execution, systemd services, ports, and deployment automation.

---

## Quick Redirection
- **System Architecture** → [`.memory/SYSTEM_ARCHITECTURE.md`](SYSTEM_ARCHITECTURE.md)
- **Data Pipeline Flow** → [`.memory/PIPELINE_FLOW.md`](PIPELINE_FLOW.md)
- **Salesforce Integrations** → [`.memory/SALESFORCE_INTEGRATION.md`](SALESFORCE_INTEGRATION.md)
- **Module Index** → [`.memory/MODULE_INDEX.md`](MODULE_INDEX.md)

---

## 1. Production Oracle Cloud Ubuntu Server

The application is hosted on an Oracle Cloud Infrastructure (OCI) Ubuntu VM.

| Property | Details |
|---|---|
| **Public IP Address** | `161.118.182.20` *(Production server)* |
| **Operating System** | Ubuntu 20.04 LTS (Oracle Cloud Kernel) |
| **Hardware Resources**| 1 GB RAM + 2 GB Swap (`/swapfile`), 45 GB Disk (~20% utilized) |
| **SSH User** | `ubuntu` |
| **SSH Key Location** | `/Users/sahilkumar/Downloads/ssh-key-2026-08-09.key` |
| **SSH Command** | `ssh -i /Users/sahilkumar/Downloads/ssh-key-2026-08-09.key ubuntu@161.118.182.20` |
| **Project Directory** | `/home/ubuntu/poc_input_generator` |

---

## 2. Server Ports & Running Services

| Service | Port | Protocol | Management | Credentials / Access |
|---|---|---|---|---|
| **Streamlit App** | `8501` | HTTP / WebSocket | `sudo systemctl [status\|restart\|stop] streamlit.service` | Open in browser: `http://161.118.182.20:8501` |
| **code-server (IDE)** | `8080` | HTTP / WebSocket | `sudo systemctl [status\|restart\|stop] code-server@ubuntu.service` | Open in browser: `http://161.118.182.20:8080`<br>Password: **`Sitetracker2026!`** |
| **SSH Daemon** | `22` | SSH | `systemctl status ssh` | SSH Key authentication only |

### Firewall Rules (`iptables`)
Ports `8080` and `8501` are explicitly open in Oracle Cloud OS firewall via `iptables`:
```bash
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 8501 -j ACCEPT
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 8080 -j ACCEPT
sudo netfilter-persistent save
```

---

## 3. GitHub Repository & Deployment Workflow

| Property | Details |
|---|---|
| **Remote Origin** | `https://github.com/notSahil/poc_input_generator.git` |
| **Primary Branch** | `main` |
| **Deployment Mode** | Git Push ➔ Pull on Server (or automated cron pull) |

### Standard Deployment Sequence
Whenever you want to deploy code changes to the live Oracle Cloud server:

```bash
# 1. On Local Machine: Test and push changes
uv run pytest tests/
git add .
git commit -m "feat/fix: description of changes"
git push origin main

# 2. SSH into Oracle Server
ssh -i /Users/sahilkumar/Downloads/ssh-key-2026-08-09.key ubuntu@161.118.182.20

# 3. Pull latest changes and update dependencies
cd /home/ubuntu/poc_input_generator
git pull origin main
uv pip install -r requirements.txt

# 4. Verify system tests on server
uv run python quick_test.py

# 5. Restart Streamlit service
sudo systemctl restart streamlit.service

# 6. Check service status
sudo systemctl status streamlit.service
```

### Auto-Deploy Cron Job
The server has an automated sync script located at `scripts/auto_deploy.sh`:
- Runs via cron periodically.
- Executes `git fetch && git pull`.
- Streamlit's built-in file watcher detects file changes and reloads automatically without server downtime for minor UI/script edits.

---

## 4. Local Machine & Company Laptop Setup

### Running with `uv` (Required Package Manager)
**DO NOT USE `pip` DIRECTLY.** Always use Astral's `uv`:

```bash
# Install dependencies
uv pip install -r requirements.txt

# Run the Streamlit application (default port 8501 or 8080)
uv run streamlit run app.py --server.port 8080

# Run full test suite
uv run pytest tests/

# Run fast smoke test
uv run python quick_test.py
```

### Clean Code Zip Packaging (`poc_code_clean.zip`)
To download the codebase onto a restricted company laptop without gigabytes of virtual environments, cache files, or past run data:

```bash
# Run packaging utility
uv run python scripts/package_clean_code.py
```
- Creates a lightweight **~4.6 MB** zip file containing pure source code, configurations, and test suites.
- Excludes: `.venv`, `.git`, `runs/`, `data/manual_runs/`, `__pycache__`, `.numbers`, `.pdf`, `.zip`, and `.env` credentials.
- Can be downloaded directly from the server via code-server at `http://161.118.182.20:8080` (right-click `poc_code_clean.zip` ➔ Download).
