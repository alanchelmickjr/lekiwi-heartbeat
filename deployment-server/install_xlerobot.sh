#!/bin/bash
#
# XLEROBOT Installation Script
# Copies XLEROBOT-specific libraries from a source robot to a target robot
#

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Default values
SOURCE_IP="192.168.88.29"
TARGET_IP="192.168.88.27"
LEKIWI_USER="lekiwi"
LEKIWI_PASS="lekiwi"

# Parse arguments
if [ $# -ge 1 ]; then
    TARGET_IP=$1
fi
if [ $# -ge 2 ]; then
    SOURCE_IP=$2
fi

echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}              XLEROBOT Installation Script${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
echo ""
echo -e "${YELLOW}Source Robot:${NC} $SOURCE_IP (has XLEROBOT libraries)"
echo -e "${YELLOW}Target Robot:${NC} $TARGET_IP (will receive XLEROBOT libraries)"
echo ""

# Function to check SSH connectivity
check_ssh() {
    local ip=$1
    echo -n "Checking SSH connection to $ip... "
    if sshpass -p $LEKIWI_PASS ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 $LEKIWI_USER@$ip "echo ok" &>/dev/null; then
        echo -e "${GREEN}✓ Connected${NC}"
        return 0
    else
        echo -e "${RED}✗ Failed${NC}"
        return 1
    fi
}

# Check both robots are accessible
echo -e "${YELLOW}Step 1: Checking connectivity...${NC}"
if ! check_ssh $SOURCE_IP; then
    echo -e "${RED}Cannot connect to source robot at $SOURCE_IP${NC}"
    exit 1
fi
if ! check_ssh $TARGET_IP; then
    echo -e "${RED}Cannot connect to target robot at $TARGET_IP${NC}"
    exit 1
fi

# List XLEROBOT files on source
echo ""
echo -e "${YELLOW}Step 2: Finding XLEROBOT libraries on source ($SOURCE_IP)...${NC}"
XLEROBOT_FILES=$(sshpass -p $LEKIWI_PASS ssh -o StrictHostKeyChecking=no $LEKIWI_USER@$SOURCE_IP "ls /opt/frodobots/lib/*xlerobot*.so 2>/dev/null")

if [ -z "$XLEROBOT_FILES" ]; then
    echo -e "${RED}No XLEROBOT libraries found on source robot!${NC}"
    exit 1
fi

echo -e "${GREEN}Found XLEROBOT libraries:${NC}"
echo "$XLEROBOT_FILES" | while read file; do
    echo "  • $(basename $file)"
done

# Check if target already has XLEROBOT files
echo ""
echo -e "${YELLOW}Step 3: Checking target robot ($TARGET_IP)...${NC}"
EXISTING_FILES=$(sshpass -p $LEKIWI_PASS ssh -o StrictHostKeyChecking=no $LEKIWI_USER@$TARGET_IP "ls /opt/frodobots/lib/*xlerobot*.so 2>/dev/null | wc -l")

if [ "$EXISTING_FILES" -gt 0 ]; then
    echo -e "${YELLOW}Warning: Target already has $EXISTING_FILES XLEROBOT file(s)${NC}"
    read -p "Do you want to overwrite them? (y/n): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Installation cancelled."
        exit 0
    fi
else
    echo "Target has no XLEROBOT libraries (clean install)"
fi

# Copy XLEROBOT libraries
echo ""
echo -e "${YELLOW}Step 4: Copying XLEROBOT libraries to target...${NC}"

# Create temp directory on target
sshpass -p $LEKIWI_PASS ssh -o StrictHostKeyChecking=no $LEKIWI_USER@$TARGET_IP "mkdir -p /tmp/xlerobot_install"

# Copy each file
SUCCESS_COUNT=0
FAIL_COUNT=0

for file in $XLEROBOT_FILES; do
    filename=$(basename $file)
    echo -n "  Copying $filename... "
    
    # Copy from source to local temp
    if sshpass -p $LEKIWI_PASS scp -o StrictHostKeyChecking=no $LEKIWI_USER@$SOURCE_IP:$file /tmp/$filename 2>/dev/null; then
        # Copy from local temp to target
        if sshpass -p $LEKIWI_PASS scp -o StrictHostKeyChecking=no /tmp/$filename $LEKIWI_USER@$TARGET_IP:/tmp/xlerobot_install/ 2>/dev/null; then
            # Move to final location with proper permissions
            if sshpass -p $LEKIWI_PASS ssh -o StrictHostKeyChecking=no $LEKIWI_USER@$TARGET_IP "sudo mv /tmp/xlerobot_install/$filename /opt/frodobots/lib/ && sudo chmod 755 /opt/frodobots/lib/$filename && sudo chown lekiwi:lekiwi /opt/frodobots/lib/$filename" 2>/dev/null; then
                echo -e "${GREEN}✓${NC}"
                ((SUCCESS_COUNT++))
            else
                echo -e "${RED}✗ (failed to install)${NC}"
                ((FAIL_COUNT++))
            fi
        else
            echo -e "${RED}✗ (failed to copy to target)${NC}"
            ((FAIL_COUNT++))
        fi
        rm -f /tmp/$filename
    else
        echo -e "${RED}✗ (failed to copy from source)${NC}"
        ((FAIL_COUNT++))
    fi
done

# Clean up temp directory on target
sshpass -p $LEKIWI_PASS ssh -o StrictHostKeyChecking=no $LEKIWI_USER@$TARGET_IP "rm -rf /tmp/xlerobot_install"

# Verify installation
echo ""
echo -e "${YELLOW}Step 5: Verifying installation...${NC}"
INSTALLED_FILES=$(sshpass -p $LEKIWI_PASS ssh -o StrictHostKeyChecking=no $LEKIWI_USER@$TARGET_IP "ls /opt/frodobots/lib/*xlerobot*.so 2>/dev/null")

if [ -n "$INSTALLED_FILES" ]; then
    echo -e "${GREEN}Installed XLEROBOT libraries on target:${NC}"
    echo "$INSTALLED_FILES" | while read file; do
        size=$(sshpass -p $LEKIWI_PASS ssh -o StrictHostKeyChecking=no $LEKIWI_USER@$TARGET_IP "stat -c %s $file 2>/dev/null")
        echo "  • $(basename $file) ($(echo $size | numfmt --to=iec-i --suffix=B))"
    done
else
    echo -e "${RED}No XLEROBOT libraries found on target!${NC}"
fi

# Test detection
echo ""
echo -e "${YELLOW}Step 6: Testing XLEROBOT detection...${NC}"
cd $(dirname $0) 2>/dev/null
if [ -f "detect_robot_type.py" ]; then
    echo "Running detection test..."
    python3 -c "
from detect_robot_type import detect_robot_type, get_robot_capabilities
ip = '$TARGET_IP'
robot_type = detect_robot_type(ip)
caps = get_robot_capabilities(ip)
print(f'  Robot Type: {robot_type}')
print(f'  Arms: {caps[\"arms\"]}')
print(f'  Cameras: {caps[\"cameras\"]}')
if robot_type == 'xlerobot':
    print('  ✓ XLEROBOT detection successful!')
else:
    print('  ✗ XLEROBOT not detected - check installation')
" 2>/dev/null || echo "  Detection script not available"
else
    echo "  Detection script not found, skipping test"
fi

# Summary
echo ""
echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}                    Installation Summary${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
echo ""
if [ $SUCCESS_COUNT -gt 0 ]; then
    echo -e "${GREEN}✓ Successfully installed $SUCCESS_COUNT XLEROBOT libraries${NC}"
fi
if [ $FAIL_COUNT -gt 0 ]; then
    echo -e "${RED}✗ Failed to install $FAIL_COUNT files${NC}"
fi

echo ""
echo -e "${YELLOW}Target robot $TARGET_IP is now configured as an XLEROBOT!${NC}"
echo ""
echo "To verify the installation, you can:"
echo "  1. SSH to the robot: ssh $LEKIWI_USER@$TARGET_IP"
echo "  2. Check libraries: ls -la /opt/frodobots/lib/*xlerobot*.so"
echo "  3. Run detection: python3 detect_robot_type.py (from deployment-server)"
echo ""