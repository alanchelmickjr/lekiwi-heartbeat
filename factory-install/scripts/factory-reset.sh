#!/bin/bash
# Factory Reset and Rollback Script for Lekiwi/XLE Robots
# Provides multiple recovery options and rollback capabilities

set -e

# Configuration
BACKUP_DIR="/etc/lekiwi/backup"
RECOVERY_DIR="/recovery"
FACTORY_IMAGE="/recovery/factory-image.img"
CONFIG_BACKUP="/recovery/config-backup.tar.gz"
LOG_FILE="/var/log/factory-reset.log"
RESET_LEVEL="${1:-soft}"  # soft, hard, or factory

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
MAGENTA='\033[0;35m'
NC='\033[0m'

# Logging
exec > >(tee -a ${LOG_FILE})
exec 2>&1

log_info() {
    echo -e "${GREEN}[INFO]${NC} $(date '+%Y-%m-%d %H:%M:%S') - $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $(date '+%Y-%m-%d %H:%M:%S') - $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $(date '+%Y-%m-%d %H:%M:%S') - $1"
}

log_progress() {
    echo -e "${BLUE}[PROGRESS]${NC} $(date '+%Y-%m-%d %H:%M:%S') - $1"
}

# Safety checks
safety_checks() {
    log_info "Performing safety checks..."
    
    # Check if running as root
    if [[ $EUID -ne 0 ]]; then
        log_error "This script must be run as root"
        exit 1
    fi
    
    # Check for recovery partition
    if [ ! -d ${RECOVERY_DIR} ]; then
        log_warn "Recovery partition not found, creating..."
        mkdir -p ${RECOVERY_DIR}
    fi
    
    # Confirm reset
    if [ -t 0 ]; then
        echo -e "${YELLOW}WARNING: This will reset the robot to factory settings!${NC}"
        echo "Reset level: ${RESET_LEVEL}"
        echo "Type 'RESET' to confirm: "
        read confirmation
        
        if [ "${confirmation}" != "RESET" ]; then
            log_info "Reset cancelled by user"
            exit 0
        fi
    fi
}

# Backup current configuration
backup_current_config() {
    log_info "Backing up current configuration..."
    
    local backup_name="backup-$(date +%Y%m%d-%H%M%S)"
    local backup_path="${BACKUP_DIR}/${backup_name}"
    
    mkdir -p ${backup_path}
    
    # Backup critical files
    local files_to_backup=(
        "/etc/lekiwi"
        "/etc/robot.conf"
        "/etc/hostname"
        "/etc/hosts"
        "/etc/network"
        "/etc/netplan"
        "/etc/systemd/system/lekiwi-*.service"
        "/var/lib/lekiwi-agent"
    )
    
    for file in "${files_to_backup[@]}"; do
        if [ -e "${file}" ]; then
            cp -a "${file}" "${backup_path}/" 2>/dev/null || true
            log_info "Backed up: ${file}"
        fi
    done
    
    # Create compressed backup
    tar -czf "${BACKUP_DIR}/${backup_name}.tar.gz" -C "${backup_path}" .
    rm -rf "${backup_path}"
    
    log_info "Configuration backed up to: ${BACKUP_DIR}/${backup_name}.tar.gz"
}

# Soft reset - Reset services and configurations
soft_reset() {
    log_progress "Performing soft reset..."
    
    # Stop services
    log_info "Stopping services..."
    systemctl stop lekiwi-agent.service || true
    systemctl stop lekiwi-watchdog.service || true
    systemctl stop lekiwi-telemetry.timer || true
    
    # Clear agent state
    log_info "Clearing agent state..."
    rm -rf /var/lib/lekiwi-agent/*
    rm -f /etc/robot.conf
    rm -f /etc/lekiwi/hardware.conf
    
    # Reset network configuration
    log_info "Resetting network configuration..."
    if [ -f /etc/netplan/01-netcfg.yaml ]; then
        cat > /etc/netplan/01-netcfg.yaml <<EOF
network:
  version: 2
  ethernets:
    eth0:
      dhcp4: true
      optional: true
  wifis:
    wlan0:
      dhcp4: true
      optional: true
EOF
        netplan apply
    fi
    
    # Regenerate SSH keys
    log_info "Regenerating SSH keys..."
    rm -f /etc/ssh/ssh_host_*
    ssh-keygen -A
    systemctl restart ssh
    
    # Clear logs
    log_info "Clearing logs..."
    journalctl --rotate
    journalctl --vacuum-time=1s
    
    # Re-run hardware detection
    log_info "Re-running hardware detection..."
    if [ -f /usr/local/bin/detect-hardware.sh ]; then
        /usr/local/bin/detect-hardware.sh
    fi
    
    # Restart services
    log_info "Restarting services..."
    systemctl daemon-reload
    systemctl start lekiwi-agent.service
    
    log_info "Soft reset completed"
}

# Hard reset - Reinstall packages and reset system
hard_reset() {
    log_progress "Performing hard reset..."
    
    # First do soft reset
    soft_reset
    
    # Remove installed packages
    log_info "Removing custom packages..."
    apt-get remove --purge -y lekiwi-agent 2>/dev/null || true
    
    # Clear APT cache
    log_info "Clearing package cache..."
    apt-get clean
    apt-get autoclean
    apt-get autoremove -y
    
    # Reset system configuration
    log_info "Resetting system configuration..."
    
    # Reset hostname
    hostnamectl set-hostname raspberrypi
    echo "raspberrypi" > /etc/hostname
    
    # Reset hosts file
    cat > /etc/hosts <<EOF
127.0.0.1       localhost
127.0.1.1       raspberrypi

# IPv6
::1             localhost ip6-localhost ip6-loopback
ff02::1         ip6-allnets
ff02::2         ip6-allrouters
EOF
    
    # Reset boot configuration
    if [ -f /boot/config.txt.template ]; then
        cp /boot/config.txt.template /boot/config.txt
    fi
    
    # Remove custom services
    log_info "Removing custom services..."
    rm -f /etc/systemd/system/lekiwi-*.service
    rm -f /etc/systemd/system/robot-*.service
    systemctl daemon-reload
    
    # Clear user data
    log_info "Clearing user data..."
    userdel -r lekiwi-agent 2>/dev/null || true
    userdel -r robot 2>/dev/null || true
    
    # Reinstall from recovery
    if [ -f ${RECOVERY_DIR}/install-robot.sh ]; then
        log_info "Reinstalling from recovery..."
        ${RECOVERY_DIR}/install-robot.sh
    fi
    
    log_info "Hard reset completed"
}

# Factory reset - Complete system restore
factory_reset() {
    log_progress "Performing factory reset..."
    
    # Check for factory image
    if [ ! -f ${FACTORY_IMAGE} ]; then
        log_error "Factory image not found at ${FACTORY_IMAGE}"
        log_info "Attempting to download factory image..."
        
        # Download factory image
        wget -O ${FACTORY_IMAGE} \
            "https://releases.lekiwi.io/factory/raspios-lite-latest.img" || {
            log_error "Failed to download factory image"
            exit 1
        }
    fi
    
    # Find root device
    ROOT_DEV=$(mount | grep "on / " | awk '{print $1}')
    ROOT_DISK=$(echo ${ROOT_DEV} | sed 's/[0-9]*$//')
    
    log_warn "This will completely overwrite ${ROOT_DISK}"
    log_info "Writing factory image..."
    
    # Create restore script that runs from RAM
    cat > /tmp/restore.sh <<'RESTORE'
#!/bin/bash
# This script runs from RAM to restore the system

# Copy essential tools to RAM
mkdir -p /tmp/restore-tools
cp /bin/dd /tmp/restore-tools/
cp /bin/sync /tmp/restore-tools/
cp /sbin/reboot /tmp/restore-tools/

# Unmount filesystems
sync
umount -a 2>/dev/null || true

# Write factory image
/tmp/restore-tools/dd if=${1} of=${2} bs=4M status=progress

# Sync and reboot
/tmp/restore-tools/sync
sleep 5
/tmp/restore-tools/reboot -f
RESTORE
    
    chmod +x /tmp/restore.sh
    
    # Execute restore from RAM
    exec /tmp/restore.sh ${FACTORY_IMAGE} ${ROOT_DISK}
}

# Restore from backup
restore_from_backup() {
    local backup_file="${1}"
    
    if [ -z "${backup_file}" ]; then
        # List available backups
        log_info "Available backups:"
        ls -la ${BACKUP_DIR}/*.tar.gz 2>/dev/null || {
            log_error "No backups found"
            exit 1
        }
        
        echo "Enter backup filename: "
        read backup_file
    fi
    
    if [ ! -f "${backup_file}" ]; then
        backup_file="${BACKUP_DIR}/${backup_file}"
    fi
    
    if [ ! -f "${backup_file}" ]; then
        log_error "Backup file not found: ${backup_file}"
        exit 1
    fi
    
    log_info "Restoring from backup: ${backup_file}"
    
    # Stop services
    systemctl stop lekiwi-agent.service || true
    
    # Extract backup
    tar -xzf "${backup_file}" -C / --overwrite
    
    # Reload configurations
    systemctl daemon-reload
    
    # Restart services
    systemctl start lekiwi-agent.service
    
    log_info "Restore completed"
}

# Create recovery partition
create_recovery_partition() {
    log_info "Creating recovery partition..."
    
    # Check available space
    local available_space=$(df / | tail -1 | awk '{print int($4/1024/1024)}')
    
    if [ ${available_space} -lt 2 ]; then
        log_error "Insufficient space for recovery partition (need 2GB)"
        exit 1
    fi
    
    # Create recovery directory
    mkdir -p ${RECOVERY_DIR}
    
    # Copy essential files
    cp -a /usr/local/bin/detect-hardware.sh ${RECOVERY_DIR}/ || true
    cp -a /usr/local/bin/lekiwi-agent ${RECOVERY_DIR}/ || true
    cp -a /etc/lekiwi ${RECOVERY_DIR}/etc-lekiwi-backup || true
    
    # Create recovery installer
    cat > ${RECOVERY_DIR}/install-robot.sh <<'INSTALLER'
#!/bin/bash
# Recovery installation script

echo "Starting recovery installation..."

# Reinstall agent
if [ -f /recovery/lekiwi-agent ]; then
    cp /recovery/lekiwi-agent /usr/local/bin/
    chmod +x /usr/local/bin/lekiwi-agent
fi

# Restore configurations
if [ -d /recovery/etc-lekiwi-backup ]; then
    cp -a /recovery/etc-lekiwi-backup /etc/lekiwi
fi

# Re-run hardware detection
if [ -f /recovery/detect-hardware.sh ]; then
    /recovery/detect-hardware.sh
fi

echo "Recovery installation completed"
INSTALLER
    
    chmod +x ${RECOVERY_DIR}/install-robot.sh
    
    log_info "Recovery partition created"
}

# Emergency recovery mode
emergency_recovery() {
    log_warn "Entering emergency recovery mode..."
    
    # Enable SSH for recovery
    systemctl start ssh || true
    
    # Start minimal network
    ip link set eth0 up
    dhclient eth0 || true
    
    # Create recovery user
    useradd -m -s /bin/bash recovery 2>/dev/null || true
    echo "recovery:recovery" | chpasswd
    
    # Display recovery information
    echo ""
    echo "========================================"
    echo -e "${MAGENTA}EMERGENCY RECOVERY MODE${NC}"
    echo "========================================"
    echo "Network interfaces:"
    ip addr show | grep inet
    echo ""
    echo "SSH access: ssh recovery@$(hostname -I | awk '{print $1}')"
    echo "Password: recovery"
    echo ""
    echo "Available recovery options:"
    echo "  1. Soft reset: $0 soft"
    echo "  2. Hard reset: $0 hard"
    echo "  3. Factory reset: $0 factory"
    echo "  4. Restore backup: $0 restore"
    echo "========================================"
    
    # Keep system running for recovery
    while true; do
        sleep 60
    done
}

# Display help
show_help() {
    echo "Lekiwi/XLE Robot Factory Reset Tool"
    echo ""
    echo "Usage: $0 [OPTION]"
    echo ""
    echo "Options:"
    echo "  soft      - Soft reset (clear state, regenerate keys)"
    echo "  hard      - Hard reset (reinstall packages, reset system)"
    echo "  factory   - Factory reset (complete system restore)"
    echo "  restore   - Restore from backup"
    echo "  backup    - Create configuration backup"
    echo "  recovery  - Enter emergency recovery mode"
    echo "  help      - Show this help message"
    echo ""
    echo "Examples:"
    echo "  $0 soft              # Perform soft reset"
    echo "  $0 restore backup.tar.gz  # Restore specific backup"
    echo ""
}

# Main execution
main() {
    log_info "Factory Reset Tool v1.0.0"
    log_info "Reset level: ${RESET_LEVEL}"
    
    case "${RESET_LEVEL}" in
        soft)
            safety_checks
            backup_current_config
            soft_reset
            ;;
        hard)
            safety_checks
            backup_current_config
            hard_reset
            ;;
        factory)
            safety_checks
            backup_current_config
            factory_reset
            ;;
        restore)
            restore_from_backup "${2}"
            ;;
        backup)
            backup_current_config
            ;;
        recovery)
            emergency_recovery
            ;;
        help|--help|-h)
            show_help
            exit 0
            ;;
        *)
            log_error "Invalid reset level: ${RESET_LEVEL}"
            show_help
            exit 1
            ;;
    esac
    
    log_info "Reset process completed successfully"
    echo ""
    echo -e "${GREEN}Robot has been reset.${NC}"
    echo "Please reboot to complete the process: sudo reboot"
}

# Run main function
if [ "${BASH_SOURCE[0]}" == "${0}" ]; then
    main "$@"
fi