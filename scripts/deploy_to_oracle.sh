#!/bin/bash
set -e

echo "========================================================="
echo "🚀 STARTING DEPLOYMENT TO ORACLE CLOUD INSTANCE"
echo "========================================================="

export PATH="$HOME/.local/bin:$PATH"

# 1. Setup 2GB Swap if not already present
if [ ! -f /swapfile ]; then
    echo "📦 Creating 2GB swap space..."
    sudo fallocate -l 2G /swapfile || sudo dd if=/dev/zero of=/swapfile bs=1M count=2048
    sudo chmod 600 /swapfile
    sudo mkswap /swapfile
    sudo swapon /swapfile
    echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
    echo "✅ Swap created successfully."
else
    echo "ℹ️ Swapfile already active."
fi

# 2. Configure OS Firewall (iptables)
echo "🛡️ Configuring firewall rules for ports 8080 and 8501..."
sudo iptables -I INPUT 5 -p tcp --dport 8080 -j ACCEPT 2>/dev/null || sudo iptables -A INPUT -p tcp --dport 8080 -j ACCEPT
sudo iptables -I INPUT 5 -p tcp --dport 8501 -j ACCEPT 2>/dev/null || sudo iptables -A INPUT -p tcp --dport 8501 -j ACCEPT
sudo netfilter-persistent save 2>/dev/null || true

# 3. Clone / Update Repository
echo "📂 Setting up poc_input_generator repository..."
cd /home/ubuntu
if [ -d "poc_input_generator" ]; then
    cd poc_input_generator
    git pull origin main
else
    git clone https://github.com/notSahil/poc_input_generator.git
    cd poc_input_generator
fi

# 4. Create Virtual Environment and Install Dependencies with UV
echo "🐍 Setting up Python 3.12 virtual environment..."
uv venv .venv --python 3.12
source .venv/bin/activate
uv pip install -r requirements.txt

# 5. Run Quick Test to Verify Code Functionality
echo "🧪 Running verification tests on Oracle VM..."
python quick_test.py

# 6. Install and Configure code-server (Browser VS Code)
echo "💻 Installing code-server (VS Code in Browser)..."
if ! command -v code-server &> /dev/null; then
    curl -fsSL https://code-server.dev/install.sh | sh
fi

mkdir -p /home/ubuntu/.config/code-server
cat <<EOF > /home/ubuntu/.config/code-server/config.yaml
bind-addr: 0.0.0.0:8080
auth: password
password: Sitetracker2026!
cert: false
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now code-server@ubuntu
sudo systemctl restart code-server@ubuntu

# 7. Setup Streamlit 24/7 Systemd Service
echo "⚡ Setting up Streamlit systemd service..."
sudo tee /etc/systemd/system/streamlit.service <<EOF
[Unit]
Description=Streamlit Sitetracker Data Hub
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/poc_input_generator
Environment="PATH=/home/ubuntu/poc_input_generator/.venv/bin:/home/ubuntu/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
ExecStart=/home/ubuntu/poc_input_generator/.venv/bin/streamlit run app.py --server.port 8501 --server.address 0.0.0.0 --server.headless true
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now streamlit
sudo systemctl restart streamlit

echo "========================================================="
echo "🎉 ORACLE CLOUD DEPLOYMENT COMPLETED SUCCESSFULLY!"
echo "========================================================="
