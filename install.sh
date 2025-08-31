#!/bin/bash

# Lekiwi Fleet Control System Installer
# Automates the tomfoolery out of robot management!

set -e

echo "🤖 Lekiwi Fleet Control System Installer"
echo "=========================================="

# Check if running as root
if [[ $EUID -ne 0 ]]; then
   echo "This script must be run as root (use sudo)" 
   exit 1
fi

# Detect if this is the control station or a robot
INSTALL_TYPE=""
while [[ "$INSTALL_TYPE" != "control" && "$INSTALL_TYPE" != "robot" ]]; do
    echo ""
    echo "What are you installing?"
    echo "1) Control Station (central monitoring)"
    echo "2) Robot Node (individual robot)"
    read -p "Enter 1 or 2: " choice
    
    case $choice in
        1) INSTALL_TYPE="control";;
        2) INSTALL_TYPE="robot";;
        *) echo "Please enter 1 or 2";;
    esac
done

echo ""
echo "Installing Lekiwi Fleet Control as: $INSTALL_TYPE"
echo ""

# Create directories
mkdir -p /opt/lekiwi/{scripts,config,logs}
cd /opt/lekiwi

# Install Python dependencies
echo "📦 Installing Python dependencies..."
apt update
apt install -y python3-pip python3-venv openssh-client nmap

# Create virtual environment
python3 -m venv /opt/lekiwi/venv
source /opt/lekiwi/venv/bin/activate

# Install required packages
pip install fastapi uvicorn psutil asyncio-mqtt websockets

# Download the main fleet control script
echo "📥 Installing fleet control system..."

cat > /opt/lekiwi/fleet_control.py << 'EOF'
# [The main Python script from the previous artifact goes here]
# This would be the complete fleet control system
EOF

# Make it executable
chmod +x /opt/lekiwi/fleet_control.py

if [[ "$INSTALL_TYPE" == "control" ]]; then
    echo "🖥️  Setting up Control Station..."
    
    # Create control station service with console output
    cat > /etc/systemd/system/lekiwi-fleet-control.service << 'EOF'
[Unit]
Description=Lekiwi Fleet Control Server
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/lekiwi
Environment=PATH=/opt/lekiwi/venv/bin
ExecStart=/opt/lekiwi/venv/bin/python /opt/lekiwi/fleet_control.py
Restart=always
RestartSec=10
# Show output on console during boot
StandardOutput=journal+console
StandardError=journal+console

[Install]
WantedBy=multi-user.target
EOF

    # Enable and start service
    systemctl daemon-reload
    systemctl enable lekiwi-fleet-control
    
    # Also create a startup script that shows progress
    cat > /opt/lekiwi/startup_with_output.sh << 'STARTUP_EOF'
#!/bin/bash
echo "🤖 Starting Lekiwi Fleet Control System..."
echo "=========================================="
echo ""

# Show what's happening
echo "📡 Checking network connectivity..."
if ping -c 1 8.8.8.8 >/dev/null 2>&1; then
    echo "✅ Network is up"
else
    echo "⚠️  Network connectivity issues"
fi

echo ""
echo "🔍 Starting robot discovery on 192.168.88.x network..."
echo "   This will scan for all Lekiwi robots automatically"
echo ""

echo "🌐 Starting web interface on port 8080..."
echo "   Access at: http://$(hostname -I | awk '{print $1}'):8080"
echo ""

# Start the actual service
systemctl start lekiwi-fleet-control

# Wait a moment for it to start
sleep 3

if systemctl is-active lekiwi-fleet-control >/dev/null; then
    echo "✅ Fleet Control System is running!"
    echo ""
    echo "🎉 Ready! Open http://$(hostname -I | awk '{print $1}'):8080"
else
    echo "❌ Failed to start fleet control system"
    echo "Check logs: journalctl -u lekiwi-fleet-control"
fi
STARTUP_EOF

    chmod +x /opt/lekiwi/startup_with_output.sh
    
    echo ""
    echo "✅ Control Station installed!"
    echo ""
    echo "The service will start automatically on boot."
    echo "To start immediately: sudo systemctl start lekiwi-fleet-control"
    echo "Web interface will be available at: http://$(hostname -I | awk '{print $1}'):8080"
    echo ""
    echo "Boot output will show on console with:"
    echo "  📡 Network check"
    echo "  🔍 Robot discovery progress"
    echo "  🌐 Web server startup"
    echo ""
    
elif [[ "$INSTALL_TYPE" == "robot" ]]; then
    echo "🤖 Setting up Robot Node..."
    
    # Setup SSH keys for control station access (you'll need to distribute the public key)
    mkdir -p /home/lekiwi/.ssh
    chown lekiwi:lekiwi /home/lekiwi/.ssh
    chmod 700 /home/lekiwi/.ssh
    
    # Create the improved environment setup service
    cat > /etc/systemd/system/lekiwi-env.service << 'EOF'
[Unit]
Description=Lekiwi Robot Environment Setup
Before=teleop.service lekiwi.service
After=network.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/opt/lekiwi/setup_env.sh
RemainAfterExit=yes
User=root
Environment="PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

[Install]
WantedBy=multi-user.target
EOF

    # Create the environment setup script
    cat > /opt/lekiwi/setup_env.sh << 'ENV_SCRIPT'
#!/bin/bash
set -e

# Lekiwi Robot Environment Setup
echo "Setting up Lekiwi robot environment..."

# Get device name using the MAC address method
DEVICE_NAME=$(echo Lekiwi_$(ip link show eth0 | awk '/ether/ {print $2}' | tr -d ':' | tail -c 9 | tr 'a-f' 'A-F'))
IP_ADDRESS=$(hostname -I | awk '{print $1}')

echo "Device: $DEVICE_NAME"
echo "IP: $IP_ADDRESS"

# Create robot environment file
cat > /opt/lekiwi/robot.env << EOF
DEVICE_NAME=$DEVICE_NAME
IP_ADDRESS=$IP_ADDRESS
LD_LIBRARY_PATH=/opt/frodobots/lib
LEKIWI_FLEET_MODE=true
ROBOT_ID=$DEVICE_NAME
EOF

# Update system environment with the LD_LIBRARY_PATH
echo "LD_LIBRARY_PATH=/opt/frodobots/lib" >> /etc/environment
echo "DEVICE_NAME=$DEVICE_NAME" >> /etc/environment
echo "IP_ADDRESS=$IP_ADDRESS" >> /etc/environment

# Update teleop.ini with correct device name
if [ -f /opt/frodobots/teleop.ini ]; then
    # Backup original
    cp /opt/frodobots/teleop.ini /opt/frodobots/teleop.ini.backup
    
    # Update device name in [signal] section
    sed -i "s/^device = .*/device = $DEVICE_NAME/" /opt/frodobots/teleop.ini
    
    echo "✅ Updated teleop.ini with device name: $DEVICE_NAME"
else
    echo "⚠️  /opt/frodobots/teleop.ini not found - will be created on first run"
fi

# Create improved teleop.sh that sources environment properly
cat > /opt/frodobots/teleop.sh << 'TELEOP_EOF'
#!/bin/bash

# Source the robot environment
if [ -f /opt/lekiwi/robot.env ]; then
    source /opt/lekiwi/robot.env
fi

# Ensure LD_LIBRARY_PATH is set (this was the annoying export command!)
export LD_LIBRARY_PATH="/opt/frodobots/lib:$LD_LIBRARY_PATH"

# Change to frodobots directory
cd /opt/frodobots

# Log startup
echo "$(date): Starting teleop_agent with device $DEVICE_NAME" >> /opt/lekiwi/logs/teleop.log

# Run teleop agent
exec ./teleop_agent ./teleop.ini 2>&1 | tee -a /opt/lekiwi/logs/teleop.log
TELEOP_EOF

    chmod +x /opt/frodobots/teleop.sh

    # Create improved lekiwi.sh for LeRobot
    if [ -f /opt/frodobots/lekiwi.sh ]; then
        cp /opt/frodobots/lekiwi.sh /opt/frodobots/lekiwi.sh.backup
    fi

    cat > /opt/frodobots/lekiwi.sh << 'LEKIWI_EOF'
#!/bin/bash

# Source robot environment
if [ -f /opt/lekiwi/robot.env ]; then
    source /opt/lekiwi/robot.env
fi

# Activate conda environment
source /home/lekiwi/miniconda3/bin/activate
conda activate lerobot

# Change to lerobot directory
cd /home/lekiwi/lerobot

# Use the device name for robot ID
ROBOT_ID=${DEVICE_NAME:-"my_awesome_kiwi"}

echo "$(date): Starting lerobot with robot ID $ROBOT_ID" >> /opt/lekiwi/logs/lerobot.log

# Run lerobot
exec python -m lerobot.common.robots.lekiwi.lekiwi_host --robot.id=$ROBOT_ID 2>&1 | tee -a /opt/lekiwi/logs/lerobot.log
LEKIWI_EOF

    chmod +x /opt/frodobots/lekiwi.sh

    echo "Robot environment setup complete for $DEVICE_NAME"
ENV_SCRIPT

    chmod +x /opt/lekiwi/setup_env.sh

    # Update existing systemd services to depend on our environment setup
    if [ -f /etc/systemd/system/teleop.service ]; then
        # Add dependency on lekiwi-env service
        if ! grep -q "After=.*lekiwi-env" /etc/systemd/system/teleop.service; then
            sed -i '/After=network.target/s/$/\nAfter=lekiwi-env.service/' /etc/systemd/system/teleop.service
            sed -i '/After=network.target/s/$/\nWants=lekiwi-env.service/' /etc/systemd/system/teleop.service
        fi
    fi

    if [ -f /etc/systemd/system/lekiwi.service ]; then
        # Add dependency on lekiwi-env service
        if ! grep -q "After=.*lekiwi-env" /etc/systemd/system/lekiwi.service; then
            sed -i '/After=network.target/s/$/\nAfter=lekiwi-env.service/' /etc/systemd/system/lekiwi.service
            sed -i '/After=network.target/s/$/\nWants=lekiwi-env.service/' /etc/systemd/system/lekiwi.service
        fi
    fi

    # Enable services
    systemctl daemon-reload
    systemctl enable lekiwi-env.service

    echo ""
    echo "✅ Robot node configured!"
    echo ""
    echo "The robot will now:"
    echo "  - Auto-set device name from MAC address"
    echo "  - Export LD_LIBRARY_PATH automatically (no more manual export!)"
    echo "  - Update teleop.ini with correct device name"
    echo "  - Be discoverable by the fleet control system"
    echo ""
    echo "Reboot the robot to activate all changes."
fi

# Create fleet management script for easy operations
cat > /opt/lekiwi/fleet-manager << 'MANAGER_EOF'
#!/bin/bash

# Lekiwi Fleet Manager - Easy commands for robot management

case $1 in
    "discover")
        echo "🔍 Scanning network for Lekiwi robots..."
        nmap -sn 192.168.88.0/24 | grep -B2 "Nmap scan report" | grep -E "scan report|MAC Address"
        ;;
    "status")
        if [ -z "$2" ]; then
            echo "Usage: fleet-manager status <robot-ip>"
            exit 1
        fi
        echo "📊 Status for robot at $2:"
        ssh -o ConnectTimeout=5 lekiwi@$2 'echo "Device: $(echo Lekiwi_$(ip link show eth0 | awk "/ether/ {print \$2}" | tr -d ":" | tail -c 9 | tr "a-f" "A-F"))"; echo "Teleop: $(systemctl is-active teleop)"; echo "LeRobot: $(systemctl is-active lekiwi)"; echo "Uptime: $(uptime -p)"'
        ;;
    "restart-teleop")
        if [ -z "$2" ]; then
            echo "Usage: fleet-manager restart-teleop <robot-ip>"
            exit 1
        fi
        echo "🔄 Restarting teleop on $2..."
        ssh lekiwi@$2 'sudo systemctl restart teleop'
        ;;
    "restart-lerobot")
        if [ -z "$2" ]; then
            echo "Usage: fleet-manager restart-lerobot <robot-ip>"
            exit 1
        fi
        echo "🔄 Restarting lerobot on $2..."
        ssh lekiwi@$2 'sudo systemctl restart lekiwi'
        ;;
    "logs")
        if [ -z "$2" ]; then
            echo "Usage: fleet-manager logs <robot-ip> [teleop|lerobot]"
            exit 1
        fi
        service=${3:-"teleop"}
        echo "📋 Recent logs from $2 ($service):"
        ssh lekiwi@$2 "tail -20 /opt/lekiwi/logs/$service.log"
        ;;
    "update-config")
        if [ -z "$2" ] || [ -z "$3" ] || [ -z "$4" ]; then
            echo "Usage: fleet-manager update-config <robot-ip> <section> <key=value>"
            echo "Example: fleet-manager update-config 192.168.88.21 teleop token=newtoken123"
            exit 1
        fi
        echo "⚙️ Updating config on $2..."
        ssh lekiwi@$2 "sudo python3 -c \"
import configparser
config = configparser.ConfigParser()
config.read('/opt/frodobots/teleop.ini')
if not config.has_section('$3'): config.add_section('$3')
key, value = '$4'.split('=', 1)
config.set('$3', key, value)
with open('/opt/frodobots/teleop.ini', 'w') as f: config.write(f)
print('Updated $3.$4')
\""
        ;;
    *)
        echo "🤖 Lekiwi Fleet Manager"
        echo "====================="
        echo ""
        echo "Commands:"
        echo "  discover                    - Scan network for robots"
        echo "  status <ip>                 - Show robot status"
        echo "  restart-teleop <ip>         - Restart teleop service"
        echo "  restart-lerobot <ip>        - Restart lerobot service"
        echo "  logs <ip> [service]         - Show recent logs"
        echo "  update-config <ip> <section> <key=value> - Update robot config"
        echo ""
        echo "Examples:"
        echo "  fleet-manager discover"
        echo "  fleet-manager status 192.168.88.21"
        echo "  fleet-manager restart-teleop 192.168.88.21"
        echo "  fleet-manager update-config 192.168.88.21 teleop token=newtoken"
        ;;
esac
MANAGER_EOF

chmod +x /opt/lekiwi/fleet-manager

# Add to PATH
if ! grep -q "/opt/lekiwi" /etc/environment; then
    echo 'PATH="/opt/lekiwi:$PATH"' >> /etc/environment
fi

echo ""
echo "🎉 Lekiwi Fleet Control System installed successfully!"
echo ""
echo "Fleet Manager Commands:"
echo "  fleet-manager discover      - Find all robots"
echo "  fleet-manager status <ip>   - Check robot status"  
echo ""

if [[ "$INSTALL_TYPE" == "control" ]]; then
    echo "To start the web interface:"
    echo "  sudo systemctl start lekiwi-fleet-control"
    echo ""
    echo "Then open: http://$(hostname -I | awk '{print $1}'):8080"
else
    echo "Robot is ready! Reboot to activate environment setup."
    echo ""
    echo "After reboot, the robot will:"
    echo "  ✅ Auto-configure device name from MAC"
    echo "  ✅ Set LD_LIBRARY_PATH automatically"
    echo "  ✅ Be discoverable by fleet control"
fi

echo ""
echo "No more tomfoolery! 🎊"