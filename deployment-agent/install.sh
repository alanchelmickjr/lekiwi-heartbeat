#!/bin/bash
# LeKiwi Deploy Agent Installation Script
# Run this on each robot to enable automatic deployments

set -e

echo "🤖 LeKiwi Deploy Agent Installation"
echo "===================================="
echo ""

# Check if running as root
if [[ $EUID -ne 0 ]]; then
   echo "This script must be run as root (use sudo)"
   exit 1
fi

# Configuration - UPDATE THESE!
DEPLOY_SERVER_URL="${DEPLOY_SERVER_URL:-http://192.168.88.1:8000}"
ROBOT_GROUP="${ROBOT_GROUP:-production}"
CHECK_INTERVAL="${CHECK_INTERVAL:-30}"

echo "Configuration:"
echo "  Server URL: $DEPLOY_SERVER_URL"
echo "  Robot Group: $ROBOT_GROUP"
echo "  Check Interval: ${CHECK_INTERVAL}s"
echo ""

read -p "Continue with these settings? (y/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Installation cancelled"
    exit 1
fi

# Installation directory
INSTALL_DIR="/opt/lekiwi-deploy"

echo "📦 Installing system dependencies..."
apt-get update
apt-get install -y python3 python3-pip

echo "📁 Creating directory structure..."
mkdir -p $INSTALL_DIR/{deployments,downloads,logs,backups,current}
mkdir -p /etc/lekiwi-deploy

echo "📚 Installing Python dependencies..."
pip3 install requests

echo "📄 Copying agent script..."
if [ -f "agent.py" ]; then
    cp agent.py $INSTALL_DIR/
    chmod +x $INSTALL_DIR/agent.py
else
    echo "⚠️  agent.py not found in current directory"
    echo "   Downloading from repository..."
    # You can add a wget/curl command here to download from your repo
fi

echo "📝 Creating configuration file..."
cat > /etc/lekiwi-deploy/agent.json << EOF
{
    "server_url": "$DEPLOY_SERVER_URL",
    "group": "$ROBOT_GROUP",
    "check_interval": $CHECK_INTERVAL,
    "max_deployments": 10,
    "base_dir": "$INSTALL_DIR",
    "services": ["teleop", "lekiwi"],
    "auto_deploy": true,
    "health_check_timeout": 30
}
EOF

echo "🔧 Creating systemd service..."
cat > /etc/systemd/system/lekiwi-deploy-agent.service << EOF
[Unit]
Description=LeKiwi Deploy Agent
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=$INSTALL_DIR
Environment="PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
Environment="DEPLOY_SERVER_URL=$DEPLOY_SERVER_URL"
Environment="ROBOT_GROUP=$ROBOT_GROUP"
Environment="CHECK_INTERVAL=$CHECK_INTERVAL"
ExecStart=/usr/bin/python3 $INSTALL_DIR/agent.py --config /etc/lekiwi-deploy/agent.json
Restart=always
RestartSec=30
StandardOutput=append:$INSTALL_DIR/logs/agent.log
StandardError=append:$INSTALL_DIR/logs/agent.log

[Install]
WantedBy=multi-user.target
EOF

echo "🔄 Reloading services..."
systemctl daemon-reload
systemctl enable lekiwi-deploy-agent

# Get robot ID for display
ROBOT_ID=$(echo Lekiwi_$(ip link show eth0 2>/dev/null | awk '/ether/ {print $2}' | tr -d ':' | tail -c 9 | tr 'a-f' 'A-F'))
if [ -z "$ROBOT_ID" ]; then
    ROBOT_ID="Lekiwi_$(hostname)"
fi

echo ""
echo "✅ Installation complete!"
echo ""
echo "Robot ID: $ROBOT_ID"
echo "Group: $ROBOT_GROUP"
echo "Server: $DEPLOY_SERVER_URL"
echo ""
echo "Next steps:"
echo "1. Start the agent: sudo systemctl start lekiwi-deploy-agent"
echo "2. Check status: sudo systemctl status lekiwi-deploy-agent"
echo "3. View logs: tail -f $INSTALL_DIR/logs/agent.log"
echo ""
echo "The agent will:"
echo "  ✅ Check for updates every ${CHECK_INTERVAL} seconds"
echo "  ✅ Automatically deploy new versions"
echo "  ✅ Keep last 10 deployments for rollback"
echo "  ✅ Report status to deployment server"
echo ""
echo "🎉 No more manual SSH deployments!"