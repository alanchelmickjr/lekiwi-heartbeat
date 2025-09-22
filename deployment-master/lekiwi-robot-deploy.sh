#!/bin/bash

# LeKiwi Robot Complete Deployment System
# Installs: lerobot → lekiwi → teleop (with auto-configuration)

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
ROBOT_IP="$1"
ROBOT_USER="${2:-lekiwi}"
ROBOT_PASS="${3:-lekiwi}"
ACTION="${4:-full}"  # full, teleop-only, check

if [ -z "$ROBOT_IP" ]; then
    echo -e "${RED}Usage: $0 <robot-ip> [username] [password] [action]${NC}"
    echo "Actions: full (complete install), teleop-only, check"
    exit 1
fi

echo -e "${BLUE}═══════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}     LeKiwi Robot Deployment System${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}Target Robot:${NC} $ROBOT_IP"
echo -e "${GREEN}Action:${NC} $ACTION"
echo ""

# Function to execute commands on robot
robot_exec() {
    sshpass -p "$ROBOT_PASS" ssh -o StrictHostKeyChecking=no "$ROBOT_USER@$ROBOT_IP" "$@"
}

# Function to copy files to robot
robot_copy() {
    sshpass -p "$ROBOT_PASS" scp -o StrictHostKeyChecking=no "$1" "$ROBOT_USER@$ROBOT_IP:$2"
}

# Get robot MAC address and generate device ID
get_device_id() {
    local mac=$(robot_exec "ip link show eth0 | awk '/ether/ {print \$2}' | tr -d ':'")
    local device_id="lekiwi_${mac:4}"  # Last 4 octets
    echo "$device_id"
}

# Generate base64 token for teleop
generate_token() {
    local device_id="$1"
    local token_string="lekiwi:lekiwi666:${device_id}:1000001"
    echo -n "$token_string" | base64
}

# Check robot status
check_robot() {
    echo -e "${YELLOW}Checking robot status...${NC}"
    
    # Get device ID
    DEVICE_ID=$(get_device_id)
    echo -e "${GREEN}✓${NC} Device ID: $DEVICE_ID"
    
    # Check OS
    OS_INFO=$(robot_exec "lsb_release -d 2>/dev/null || cat /etc/os-release | grep PRETTY_NAME")
    echo -e "${GREEN}✓${NC} OS: $OS_INFO"
    
    # Check services
    echo -e "\n${YELLOW}Service Status:${NC}"
    for service in teleop lekiwi lerobot; do
        if robot_exec "systemctl is-active $service &>/dev/null"; then
            echo -e "  ${GREEN}✓${NC} $service: active"
        else
            echo -e "  ${RED}✗${NC} $service: not found/inactive"
        fi
    done
    
    # Check installations
    echo -e "\n${YELLOW}Installed Components:${NC}"
    if robot_exec "[ -d /opt/frodobots ]"; then
        echo -e "  ${GREEN}✓${NC} Teleop installed at /opt/frodobots"
        robot_exec "cat /opt/frodobots/teleop.ini 2>/dev/null | grep 'device =' | head -1" || true
    else
        echo -e "  ${RED}✗${NC} Teleop not installed"
    fi
    
    if robot_exec "[ -d /home/$ROBOT_USER/lerobot ]"; then
        echo -e "  ${GREEN}✓${NC} LeRobot installed"
    else
        echo -e "  ${RED}✗${NC} LeRobot not installed"
    fi
    
    if robot_exec "[ -d /home/$ROBOT_USER/lekiwi ]"; then
        echo -e "  ${GREEN}✓${NC} LeKiwi installed"
    else
        echo -e "  ${RED}✗${NC} LeKiwi not installed"
    fi
}

# Install LeRobot (base system)
install_lerobot() {
    echo -e "\n${YELLOW}Installing LeRobot...${NC}"
    
    robot_exec "sudo apt-get update && sudo apt-get install -y python3-pip python3-venv git"
    
    # Clone and setup lerobot
    robot_exec "cd ~ && [ ! -d lerobot ] && git clone https://github.com/huggingface/lerobot.git || echo 'LeRobot already cloned'"
    
    robot_exec "cd ~/lerobot && python3 -m venv venv && source venv/bin/activate && pip install -e ."
    
    echo -e "${GREEN}✓${NC} LeRobot installed"
}

# Install LeKiwi (holonomic base support)
install_lekiwi() {
    echo -e "\n${YELLOW}Installing LeKiwi holonomic base support...${NC}"
    
    # Clone LeKiwi repo (assuming it exists)
    robot_exec "cd ~ && [ ! -d lekiwi ] && git clone https://github.com/lekiwi/lekiwi-base.git lekiwi || echo 'LeKiwi already cloned'"
    
    # Install LeKiwi dependencies
    robot_exec "cd ~/lekiwi && [ -f requirements.txt ] && pip install -r requirements.txt || echo 'No requirements.txt'"
    
    # Create systemd service for LeKiwi
    cat > /tmp/lekiwi.service << 'EOF'
[Unit]
Description=LeKiwi Holonomic Base Service
After=network.target

[Service]
Type=simple
User=lekiwi
WorkingDirectory=/home/lekiwi/lekiwi
ExecStart=/usr/bin/python3 /home/lekiwi/lekiwi/main.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF
    
    robot_copy /tmp/lekiwi.service /tmp/
    robot_exec "sudo mv /tmp/lekiwi.service /etc/systemd/system/ && sudo systemctl daemon-reload"
    
    echo -e "${GREEN}✓${NC} LeKiwi installed"
}

# Install Teleop from BitRobot
install_teleop() {
    echo -e "\n${YELLOW}Installing BitRobot Teleop...${NC}"
    
    # Get device ID
    DEVICE_ID=$(get_device_id)
    TOKEN=$(generate_token "$DEVICE_ID")
    
    echo -e "${GREEN}✓${NC} Device ID: $DEVICE_ID"
    echo -e "${GREEN}✓${NC} Token generated"
    
    # Create directories
    robot_exec "sudo mkdir -p /opt/frodobots/{cert,lib}"
    robot_exec "sudo chown -R $ROBOT_USER:$ROBOT_USER /opt/frodobots"
    
    # Download teleop agent (assuming we have it)
    echo -e "${YELLOW}Downloading teleop components...${NC}"
    
    # Create teleop.ini with proper configuration
    cat > /tmp/teleop.ini << EOF
[teleop]
token = $TOKEN
video = 2
audio = 0
project = lekiwi
record = false

[signal]
cert = /opt/frodobots/cert/cert.pem
key = /opt/frodobots/cert/priv.pem
ca = /opt/frodobots/cert/AmazonRootCA1.pem
device = $DEVICE_ID

[plugin]
media = /opt/frodobots/lib/libteleop_media_gst.so
ctrl = /opt/frodobots/lib/libteleop_ctrl_zmq_ik.so
camera1 = v4l2src device=/dev/video2 !videoflip video-direction=180
camera2 = v4l2src device=/dev/video0 !videoflip video-direction=180
EOF
    
    robot_copy /tmp/teleop.ini /tmp/
    robot_exec "sudo mv /tmp/teleop.ini /opt/frodobots/"
    
    # Create teleop.sh startup script
    cat > /tmp/teleop.sh << 'EOF'
#!/bin/bash
while ! ping -c 1 8.8.8.8 &> /dev/null; do
    echo "8.8.8.8 is not reachable, retrying..."
    sleep 1
done
echo "8.8.8.8 is reachable, starting the application..."
/opt/frodobots/teleop_agent /opt/frodobots/teleop.ini
EOF
    
    robot_copy /tmp/teleop.sh /tmp/
    robot_exec "sudo mv /tmp/teleop.sh /opt/frodobots/ && sudo chmod +x /opt/frodobots/teleop.sh"
    
    # Create systemd service
    cat > /tmp/teleop.service << 'EOF'
[Unit]
Description=BitRobot Teleop Service
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=lekiwi
WorkingDirectory=/opt/frodobots
ExecStart=/opt/frodobots/teleop.sh
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF
    
    robot_copy /tmp/teleop.service /tmp/
    robot_exec "sudo mv /tmp/teleop.service /etc/systemd/system/ && sudo systemctl daemon-reload"
    
    # Download actual teleop_agent binary (placeholder - need actual source)
    echo -e "${YELLOW}Note: You need to provide the actual teleop_agent binary${NC}"
    echo -e "${YELLOW}Expected at: /opt/frodobots/teleop_agent${NC}"
    
    # Copy from working robot if available
    if [ "$ROBOT_IP" != "192.168.88.21" ]; then
        echo -e "${YELLOW}Attempting to copy teleop_agent from working robot...${NC}"
        sshpass -p "$ROBOT_PASS" scp -o StrictHostKeyChecking=no \
            "$ROBOT_USER@192.168.88.21:/opt/frodobots/teleop_agent" \
            /tmp/teleop_agent 2>/dev/null && \
        robot_copy /tmp/teleop_agent /tmp/ && \
        robot_exec "sudo mv /tmp/teleop_agent /opt/frodobots/ && sudo chmod +x /opt/frodobots/teleop_agent" && \
        echo -e "${GREEN}✓${NC} Teleop agent copied from working robot" || \
        echo -e "${RED}✗${NC} Could not copy teleop_agent"
        
        # Also copy libraries
        sshpass -p "$ROBOT_PASS" scp -r -o StrictHostKeyChecking=no \
            "$ROBOT_USER@192.168.88.21:/opt/frodobots/lib/*" \
            /tmp/ 2>/dev/null && \
        robot_copy /tmp/libteleop*.so /tmp/ && \
        robot_exec "sudo mv /tmp/libteleop*.so /opt/frodobots/lib/" && \
        echo -e "${GREEN}✓${NC} Teleop libraries copied" || \
        echo -e "${RED}✗${NC} Could not copy libraries"
        
        # Copy certificates
        sshpass -p "$ROBOT_PASS" scp -r -o StrictHostKeyChecking=no \
            "$ROBOT_USER@192.168.88.21:/opt/frodobots/cert/*" \
            /tmp/ 2>/dev/null && \
        robot_copy /tmp/*.pem /tmp/ && \
        robot_exec "sudo mv /tmp/*.pem /opt/frodobots/cert/" && \
        echo -e "${GREEN}✓${NC} Certificates copied" || \
        echo -e "${RED}✗${NC} Could not copy certificates"
    fi
    
    echo -e "${GREEN}✓${NC} Teleop configuration complete"
}

# Start services
start_services() {
    echo -e "\n${YELLOW}Starting services...${NC}"
    
    for service in lekiwi teleop; do
        if robot_exec "sudo systemctl enable $service && sudo systemctl restart $service"; then
            echo -e "${GREEN}✓${NC} $service service started"
        else
            echo -e "${RED}✗${NC} Failed to start $service"
        fi
    done
}

# Main deployment flow
case "$ACTION" in
    check)
        check_robot
        ;;
    teleop-only)
        check_robot
        install_teleop
        start_services
        echo -e "\n${GREEN}✓ Teleop deployment complete!${NC}"
        ;;
    full)
        check_robot
        echo -e "\n${BLUE}Starting full deployment...${NC}"
        install_lerobot
        install_lekiwi
        install_teleop
        start_services
        echo -e "\n${GREEN}✓ Full deployment complete!${NC}"
        check_robot
        ;;
    *)
        echo -e "${RED}Unknown action: $ACTION${NC}"
        exit 1
        ;;
esac

echo -e "\n${BLUE}═══════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}Deployment finished for robot at $ROBOT_IP${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════${NC}"