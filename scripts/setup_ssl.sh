#!/bin/bash
set -e

# ==============================================================================
# Sitetracker Data Hub - HTTPS & Nginx Setup Script (Oracle Cloud Ubuntu)
# ==============================================================================
# Usage:
#   sudo bash scripts/setup_ssl.sh <your-subdomain>.duckdns.org <your-email@example.com>
# ==============================================================================

DOMAIN="$1"
EMAIL="$2"

if [ -z "$DOMAIN" ]; then
    echo "❌ Error: Domain name is required."
    echo "Usage: sudo bash scripts/setup_ssl.sh <your-subdomain>.duckdns.org <your-email@example.com>"
    exit 1
fi

if [ -z "$EMAIL" ]; then
    echo "❌ Error: Email address is required for SSL certificate renewal alerts."
    echo "Usage: sudo bash scripts/setup_ssl.sh <your-subdomain>.duckdns.org <your-email@example.com>"
    exit 1
fi

echo "========================================================="
echo "🔒 CONFIGURING HTTPS FOR: $DOMAIN"
echo "📧 NOTIFICATION EMAIL:   $EMAIL"
echo "========================================================="

# 1. Update iptables firewall for ports 80 and 443
echo "🛡️ Opening ports 80 and 443 in VM firewall (iptables)..."
sudo iptables -I INPUT 5 -p tcp --dport 80 -j ACCEPT 2>/dev/null || sudo iptables -A INPUT -p tcp --dport 80 -j ACCEPT
sudo iptables -I INPUT 5 -p tcp --dport 443 -j ACCEPT 2>/dev/null || sudo iptables -A INPUT -p tcp --dport 443 -j ACCEPT
sudo netfilter-persistent save 2>/dev/null || true
echo "✅ Firewall rules updated."

# 2. Install Nginx and Certbot
echo "📦 Installing Nginx and Certbot..."
sudo apt-get update -y
sudo apt-get install -y nginx certbot python3-certbot-nginx

# 3. Create Nginx Configuration for Streamlit with WebSocket support
echo "⚙️ Configuring Nginx reverse proxy for Streamlit (Port 8501)..."
sudo tee /etc/nginx/sites-available/streamlit > /dev/null <<EOF
server {
    listen 80;
    server_name $DOMAIN;

    client_max_body_size 100M;

    location / {
        proxy_pass http://127.0.0.1:8501;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;

        # Streamlit WebSocket protocol upgrade
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 86400;
    }
}
EOF

# Enable the site and remove default configuration
sudo rm -f /etc/nginx/sites-enabled/default
sudo ln -sf /etc/nginx/sites-available/streamlit /etc/nginx/sites-enabled/streamlit

echo "🔍 Testing Nginx configuration..."
sudo nginx -t

echo "🔄 Restarting Nginx service..."
sudo systemctl restart nginx
sudo systemctl enable nginx

# 4. Obtain and install SSL certificate using Certbot
echo "📜 Requesting SSL Certificate from Let's Encrypt..."
sudo certbot --nginx \
    -d "$DOMAIN" \
    --non-interactive \
    --agree-tos \
    --email "$EMAIL" \
    --redirect

echo "🔄 Reloading Nginx with HTTPS..."
sudo systemctl reload nginx

echo "========================================================="
echo "🎉 SUCCESS! Your application is now live and secure at:"
echo "👉 https://$DOMAIN"
echo "========================================================="
