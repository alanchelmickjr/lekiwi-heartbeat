#!/bin/bash
# Script to rename XLE robot hostname via SSH

IP="${1:-192.168.88.57}"
NEW_NAME="${2:-xlerobot1}"

echo "============================================================"
echo "XLE Robot Hostname Renamer (SSH Version)"
echo "============================================================"
echo "🤖 Renaming robot at $IP to $NEW_NAME..."

# SSH command to rename hostname
sshpass -p 'lekiwi' ssh -o StrictHostKeyChecking=no lekiwi@$IP << EOF
    echo "Current hostname: \$(hostname)"
    echo "Setting new hostname to: $NEW_NAME"
    
    # Use hostnamectl if available (systemd)
    if command -v hostnamectl &> /dev/null; then
        echo "Using hostnamectl..."
        sudo hostnamectl set-hostname $NEW_NAME
    else
        # Fallback to traditional method
        echo "Using traditional method..."
        echo "$NEW_NAME" | sudo tee /etc/hostname
        sudo sed -i "s/\$(hostname)/$NEW_NAME/g" /etc/hosts
        sudo hostname $NEW_NAME
    fi
    
    # Verify the change
    echo "New hostname: \$(hostname)"
    
    # Check if service needs restart
    echo "Restarting networking..."
    sudo systemctl restart networking 2>/dev/null || true
    
    echo "✅ Hostname changed. A reboot is recommended for full effect."
EOF

echo ""
echo "✅ Done! The robot should now identify as '$NEW_NAME'"
echo "   To fully apply changes, reboot the robot:"
echo "   ssh lekiwi@$IP 'sudo reboot'"