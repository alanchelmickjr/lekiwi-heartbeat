#!/bin/bash
# LeKiwi Deploy Server Installation Script
# Run this on your control/deployment server

set -e

echo "🚀 LeKiwi Deploy Server Installation"
echo "===================================="
echo ""

# Check if running as root
if [[ $EUID -ne 0 ]]; then
   echo "This script must be run as root (use sudo)"
   exit 1
fi

# Configuration
INSTALL_DIR="/opt/lekiwi-deploy"
SERVER_PORT="${DEPLOY_PORT:-8000}"
GITHUB_REPO="${GITHUB_REPO:-https://github.com/your-org/robot-code.git}"

echo "📦 Installing system dependencies..."
apt-get update
apt-get install -y python3 python3-pip python3-venv git nginx

echo "📁 Creating directory structure..."
mkdir -p $INSTALL_DIR/{deployments,packages,repos,logs}
mkdir -p /etc/lekiwi-deploy

echo "🐍 Setting up Python environment..."
cd $INSTALL_DIR
python3 -m venv venv
source venv/bin/activate

echo "📚 Installing Python dependencies..."
pip install --upgrade pip
pip install fastapi uvicorn requests aiofiles pydantic

echo "📝 Creating configuration file..."
cat > /etc/lekiwi-deploy/config.json << EOF
{
    "server_port": $SERVER_PORT,
    "deployments_dir": "$INSTALL_DIR/deployments",
    "packages_dir": "$INSTALL_DIR/packages",
    "repos_dir": "$INSTALL_DIR/repos",
    "max_deployments": 100,
    "github_repo": "$GITHUB_REPO"
}
EOF

echo "📄 Copying server script..."
if [ -f "server.py" ]; then
    cp server.py $INSTALL_DIR/
else
    echo "⚠️  server.py not found in current directory"
    echo "   Please copy it manually to $INSTALL_DIR/"
fi

echo "🔧 Creating systemd service..."
cat > /etc/systemd/system/lekiwi-deploy.service << EOF
[Unit]
Description=LeKiwi Deploy Server
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=$INSTALL_DIR
Environment="PATH=$INSTALL_DIR/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
Environment="DEPLOY_PORT=$SERVER_PORT"
Environment="DEPLOYMENTS_DIR=$INSTALL_DIR/deployments"
Environment="PACKAGES_DIR=$INSTALL_DIR/packages"
Environment="REPOS_DIR=$INSTALL_DIR/repos"
Environment="GITHUB_REPO=$GITHUB_REPO"
ExecStart=$INSTALL_DIR/venv/bin/python $INSTALL_DIR/server.py
Restart=always
RestartSec=10
StandardOutput=append:$INSTALL_DIR/logs/server.log
StandardError=append:$INSTALL_DIR/logs/server.log

[Install]
WantedBy=multi-user.target
EOF

echo "🌐 Configuring Nginx reverse proxy..."
cat > /etc/nginx/sites-available/lekiwi-deploy << EOF
server {
    listen 80;
    server_name _;
    
    location / {
        proxy_pass http://localhost:$SERVER_PORT;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host \$host;
        proxy_cache_bypass \$http_upgrade;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF

ln -sf /etc/nginx/sites-available/lekiwi-deploy /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default

echo "🔄 Reloading services..."
systemctl daemon-reload
systemctl enable lekiwi-deploy
systemctl restart nginx

echo ""
echo "✅ Installation complete!"
echo ""
echo "Next steps:"
echo "1. Update GITHUB_REPO in /etc/lekiwi-deploy/config.json"
echo "2. Start the server: sudo systemctl start lekiwi-deploy"
echo "3. Check status: sudo systemctl status lekiwi-deploy"
echo "4. View logs: tail -f $INSTALL_DIR/logs/server.log"
echo ""
echo "Server will be available at:"
echo "  http://$(hostname -I | awk '{print $1}'):$SERVER_PORT"
echo "  http://$(hostname -I | awk '{print $1}') (via Nginx)"
echo ""
echo "To configure GitHub webhook:"
echo "  Webhook URL: http://$(hostname -I | awk '{print $1}')/webhook/github"
echo "  Content type: application/json"
echo "  Events: Just the push event"