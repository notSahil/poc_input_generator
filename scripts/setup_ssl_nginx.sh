#!/usr/bin/env bash
# ==============================================================================
# setup_ssl_nginx.sh: Automate Nginx + Let's Encrypt SSL on Oracle Cloud Ubuntu
# Domain: 161-118-182-20.sslip.io
# ==============================================================================
set -euo pipefail

DOMAIN="161-118-182-20.sslip.io"
EMAIL="admin@thbs.com"

echo "=== 1. Checking and Opening Firewall Ports in iptables ==="
if ! sudo iptables -C INPUT -p tcp --dport 80 -j ACCEPT 2>/dev/null; then
    echo "Adding port 80 (HTTP) to iptables..."
    sudo iptables -I INPUT 5 -p tcp --dport 80 -j ACCEPT
fi

if ! sudo iptables -C INPUT -p tcp --dport 443 -j ACCEPT 2>/dev/null; then
    echo "Adding port 443 (HTTPS) to iptables..."
    sudo iptables -I INPUT 6 -p tcp --dport 443 -j ACCEPT
fi

# Save iptables rules if netfilter-persistent is available
if command -v netfilter-persistent &>/dev/null; then
    sudo netfilter-persistent save || true
fi

echo "=== 2. Installing Nginx & Certbot ==="
sudo apt-get update -y
sudo apt-get install -y nginx certbot python3-certbot-nginx

echo "=== 3. Obtaining Let's Encrypt SSL Certificate ==="
# Stop nginx temporarily if needed for standalone challenge or use webroot
if [ ! -d "/etc/letsencrypt/live/${DOMAIN}" ]; then
    echo "Requesting new certificate for ${DOMAIN}..."
    sudo systemctl stop nginx || true
    sudo certbot certonly --standalone \
        --non-interactive \
        --agree-tos \
        --register-unsafely-without-email \
        -d "${DOMAIN}"
else
    echo "Certificate for ${DOMAIN} already exists. Skipping issuance."
fi

echo "=== 4. Deploying Nginx Configuration ==="
REPO_DIR="/home/ubuntu/poc_input_generator"
sudo cp "${REPO_DIR}/scripts/nginx_sitetracker.conf" /etc/nginx/sites-available/sitetracker
sudo ln -sf /etc/nginx/sites-available/sitetracker /etc/nginx/sites-enabled/
# Remove default site if present
sudo rm -f /etc/nginx/sites-enabled/default

# Test Nginx syntax
sudo nginx -t

echo "=== 5. Hardening Streamlit Service (Binding to 127.0.0.1) ==="
SERVICE_FILE="/etc/systemd/system/streamlit.service"
if grep -q "0.0.0.0" "${SERVICE_FILE}"; then
    echo "Updating streamlit.service to bind to 127.0.0.1..."
    sudo sed -i 's/--server.address 0.0.0.0/--server.address 127.0.0.1/g' "${SERVICE_FILE}"
    sudo systemctl daemon-reload
fi

echo "=== 6. Restarting Services ==="
sudo systemctl restart streamlit
sudo systemctl restart nginx
sudo systemctl enable nginx

echo "=== 7. Verification ==="
echo "Streamlit status:"
sudo systemctl is-active streamlit
echo "Nginx status:"
sudo systemctl is-active nginx

echo "=== HTTPS Deployment Complete! ==="
echo "Access your app at: https://${DOMAIN}"
