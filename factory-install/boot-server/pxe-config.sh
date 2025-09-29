#!/bin/bash
# PXE Boot Server Configuration for Lekiwi/XLE Robot Factory Install
# Supports both Raspberry Pi 4 and Pi 5 network booting

set -e

TFTP_ROOT="/srv/tftp"
NFS_ROOT="/srv/nfs/lekiwi"
DHCP_RANGE_START="192.168.100.100"
DHCP_RANGE_END="192.168.100.200"
SERVER_IP="192.168.100.1"
DOMAIN="robots.local"

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if running as root
if [[ $EUID -ne 0 ]]; then
   log_error "This script must be run as root"
   exit 1
fi

# Install required packages
install_packages() {
    log_info "Installing required packages..."
    apt-get update
    apt-get install -y \
        dnsmasq \
        nfs-kernel-server \
        nginx \
        isc-dhcp-server \
        tftpd-hpa \
        syslinux \
        pxelinux \
        rsync \
        qemu-user-static \
        systemd-container \
        debootstrap \
        git \
        build-essential
}

# Configure dnsmasq for PXE boot
configure_dnsmasq() {
    log_info "Configuring dnsmasq for PXE boot..."
    
    # Backup original config
    cp /etc/dnsmasq.conf /etc/dnsmasq.conf.bak || true
    
    cat > /etc/dnsmasq.conf <<EOF
# PXE Boot Configuration for Lekiwi/XLE Robots
interface=eth0
bind-interfaces

# DNS settings
domain=${DOMAIN}
local=/${DOMAIN}/
expand-hosts

# DHCP settings
dhcp-range=${DHCP_RANGE_START},${DHCP_RANGE_END},12h
dhcp-option=option:router,${SERVER_IP}
dhcp-option=option:dns-server,${SERVER_IP}

# PXE boot settings
dhcp-boot=pxelinux.0
enable-tftp
tftp-root=${TFTP_ROOT}

# Raspberry Pi 4 specific
dhcp-match=set:rpi4,option:client-arch,0
dhcp-boot=tag:rpi4,bootcode.bin

# Raspberry Pi 5 specific  
dhcp-match=set:rpi5,option:client-arch,11
dhcp-boot=tag:rpi5,boot.img

# UEFI boot for newer Pis
dhcp-match=set:efi-x86_64,option:client-arch,7
dhcp-match=set:efi-arm64,option:client-arch,11
dhcp-boot=tag:efi-arm64,grubnetaa64.efi

# Log DHCP requests
log-dhcp
log-queries

# Static IP assignments based on MAC
# Example: dhcp-host=dc:a6:32:xx:xx:xx,lekiwi-001,192.168.100.101
EOF
    
    # Create MAC address mapping file
    touch /etc/dnsmasq.d/static-ips.conf
    
    systemctl restart dnsmasq
    systemctl enable dnsmasq
}

# Setup TFTP directory structure
setup_tftp() {
    log_info "Setting up TFTP directory structure..."
    
    mkdir -p ${TFTP_ROOT}/{pi4,pi5,pxelinux.cfg,efi}
    
    # Create PXE boot menu
    cat > ${TFTP_ROOT}/pxelinux.cfg/default <<EOF
DEFAULT menu.c32
PROMPT 0
TIMEOUT 50
MENU TITLE Lekiwi/XLE Robot Factory Install

LABEL lekiwi
    MENU LABEL Install Lekiwi Robot OS
    KERNEL vmlinuz-lekiwi
    APPEND initrd=initrd-lekiwi.img root=/dev/nfs nfsroot=${SERVER_IP}:${NFS_ROOT}/lekiwi ip=dhcp rw robot_type=lekiwi

LABEL xle
    MENU LABEL Install XLE Robot OS  
    KERNEL vmlinuz-xle
    APPEND initrd=initrd-xle.img root=/dev/nfs nfsroot=${SERVER_IP}:${NFS_ROOT}/xle ip=dhcp rw robot_type=xle

LABEL auto
    MENU LABEL Auto-detect and Install
    KERNEL vmlinuz-auto
    APPEND initrd=initrd-auto.img root=/dev/nfs nfsroot=${SERVER_IP}:${NFS_ROOT}/auto ip=dhcp rw auto_detect=true
EOF
    
    # Set permissions
    chmod -R 755 ${TFTP_ROOT}
    chown -R tftp:tftp ${TFTP_ROOT}
}

# Configure NFS exports
configure_nfs() {
    log_info "Configuring NFS exports..."
    
    mkdir -p ${NFS_ROOT}/{lekiwi,xle,auto}
    
    # Add NFS exports
    cat >> /etc/exports <<EOF
${NFS_ROOT}/lekiwi *(rw,sync,no_subtree_check,no_root_squash)
${NFS_ROOT}/xle *(rw,sync,no_subtree_check,no_root_squash)
${NFS_ROOT}/auto *(rw,sync,no_subtree_check,no_root_squash)
EOF
    
    exportfs -ra
    systemctl restart nfs-kernel-server
    systemctl enable nfs-kernel-server
}

# Download and prepare Raspberry Pi OS images
prepare_os_images() {
    log_info "Preparing OS images..."
    
    local WORK_DIR="/tmp/pxe-work"
    mkdir -p ${WORK_DIR}
    
    # Download latest Raspberry Pi OS Lite
    if [ ! -f "${WORK_DIR}/raspios-lite.img" ]; then
        log_info "Downloading Raspberry Pi OS Lite..."
        wget -O ${WORK_DIR}/raspios-lite.zip \
            "https://downloads.raspberrypi.org/raspios_lite_arm64/images/raspios_lite_arm64-2024-03-15/2024-03-15-raspios-bookworm-arm64-lite.img.xz"
        xz -d ${WORK_DIR}/raspios-lite.zip
        mv ${WORK_DIR}/*.img ${WORK_DIR}/raspios-lite.img
    fi
    
    # Mount and customize for each robot type
    for ROBOT_TYPE in lekiwi xle auto; do
        log_info "Preparing ${ROBOT_TYPE} image..."
        
        local TARGET_DIR="${NFS_ROOT}/${ROBOT_TYPE}"
        
        # Mount the image
        local LOOP_DEV=$(losetup --show -fP ${WORK_DIR}/raspios-lite.img)
        mkdir -p /mnt/rpi-tmp
        mount ${LOOP_DEV}p2 /mnt/rpi-tmp
        mount ${LOOP_DEV}p1 /mnt/rpi-tmp/boot
        
        # Copy to NFS root
        rsync -ax /mnt/rpi-tmp/ ${TARGET_DIR}/
        
        # Customize for PXE boot
        customize_image ${TARGET_DIR} ${ROBOT_TYPE}
        
        # Copy kernel and initrd to TFTP
        cp ${TARGET_DIR}/boot/kernel8.img ${TFTP_ROOT}/vmlinuz-${ROBOT_TYPE}
        cp ${TARGET_DIR}/boot/initramfs8 ${TFTP_ROOT}/initrd-${ROBOT_TYPE}.img || \
           create_initramfs ${TARGET_DIR} ${TFTP_ROOT}/initrd-${ROBOT_TYPE}.img
        
        # Cleanup
        umount /mnt/rpi-tmp/boot
        umount /mnt/rpi-tmp
        losetup -d ${LOOP_DEV}
    done
}

# Customize OS image for robot type
customize_image() {
    local TARGET_DIR=$1
    local ROBOT_TYPE=$2
    
    log_info "Customizing image for ${ROBOT_TYPE}..."
    
    # Enable SSH
    touch ${TARGET_DIR}/boot/ssh
    
    # Configure network boot
    cat > ${TARGET_DIR}/boot/cmdline.txt <<EOF
console=serial0,115200 console=tty1 root=/dev/nfs nfsroot=${SERVER_IP}:${NFS_ROOT}/${ROBOT_TYPE} ip=dhcp rootwait rw robot_type=${ROBOT_TYPE}
EOF
    
    # Disable swap
    systemctl --root=${TARGET_DIR} mask dphys-swapfile.service
    
    # Configure fstab for NFS root
    cat > ${TARGET_DIR}/etc/fstab <<EOF
proc            /proc           proc    defaults          0       0
${SERVER_IP}:${NFS_ROOT}/${ROBOT_TYPE} / nfs defaults,noatime 0 0
tmpfs           /tmp            tmpfs   defaults,noatime,mode=1777 0 0
tmpfs           /var/log        tmpfs   defaults,noatime,mode=0755 0 0
EOF
    
    # Add custom firstboot script
    cat > ${TARGET_DIR}/etc/systemd/system/firstboot.service <<EOF
[Unit]
Description=First Boot Configuration
After=network-online.target
Wants=network-online.target
ConditionPathExists=!/etc/robot-configured

[Service]
Type=oneshot
ExecStart=/usr/local/bin/firstboot.sh
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF
    
    # Create firstboot script
    cat > ${TARGET_DIR}/usr/local/bin/firstboot.sh <<'FIRSTBOOT'
#!/bin/bash
set -e

# Detect hardware and set robot type
ROBOT_TYPE="${robot_type:-auto}"

if [ "$ROBOT_TYPE" = "auto" ]; then
    # Auto-detect logic
    if lsusb | grep -q "RealSense"; then
        ROBOT_TYPE="xle"
    elif i2cdetect -y 1 0x40 0x40 | grep -q "40"; then
        ROBOT_TYPE="lekiwi"
    else
        ROBOT_TYPE="unknown"
    fi
fi

# Generate unique robot ID
ROBOT_ID=$(cat /proc/sys/kernel/random/uuid)
MAC_ADDR=$(ip link show eth0 | awk '/ether/ {print $2}' | tr -d ':')
HOSTNAME="${ROBOT_TYPE}-${MAC_ADDR: -6}"

# Set hostname
hostnamectl set-hostname ${HOSTNAME}
echo ${HOSTNAME} > /etc/hostname

# Save robot configuration
cat > /etc/robot.conf <<CONFIG
ROBOT_TYPE=${ROBOT_TYPE}
ROBOT_ID=${ROBOT_ID}
HOSTNAME=${HOSTNAME}
CONFIGURED_AT=$(date -Iseconds)
CONFIG

# Install agent
curl -sSL http://${SERVER_IP}/install-agent.sh | bash -s -- --type ${ROBOT_TYPE} --id ${ROBOT_ID}

# Mark as configured
touch /etc/robot-configured

# Reboot to apply all changes
systemctl reboot
FIRSTBOOT
    
    chmod +x ${TARGET_DIR}/usr/local/bin/firstboot.sh
    systemctl --root=${TARGET_DIR} enable firstboot.service
}

# Create initramfs if needed
create_initramfs() {
    local ROOT_DIR=$1
    local OUTPUT=$2
    
    log_info "Creating initramfs..."
    
    # Create minimal initramfs with NFS support
    local INITRD_DIR="/tmp/initrd-$$"
    mkdir -p ${INITRD_DIR}/{bin,sbin,etc,proc,sys,dev,lib,lib64,mnt,tmp,var}
    
    # Copy essential binaries
    for cmd in sh busybox mount umount; do
        cp -a ${ROOT_DIR}/bin/${cmd} ${INITRD_DIR}/bin/ 2>/dev/null || true
    done
    
    # Copy libraries
    cp -a ${ROOT_DIR}/lib/modules ${INITRD_DIR}/lib/ 2>/dev/null || true
    
    # Create init script
    cat > ${INITRD_DIR}/init <<'INIT'
#!/bin/sh
/bin/busybox --install -s
mount -t proc none /proc
mount -t sysfs none /sys
mount -t devtmpfs none /dev

# Wait for network
sleep 5

# Mount NFS root
mount -t nfs -o nolock ${nfsroot} /mnt

# Switch root
exec switch_root /mnt /sbin/init
INIT
    
    chmod +x ${INITRD_DIR}/init
    
    # Create initramfs
    (cd ${INITRD_DIR} && find . | cpio -o -H newc | gzip > ${OUTPUT})
    rm -rf ${INITRD_DIR}
}

# Setup HTTP server for agent installation
setup_http_server() {
    log_info "Setting up HTTP server..."
    
    mkdir -p /var/www/pxe
    
    # Copy agent installer
    cp ../scripts/install-agent.sh /var/www/pxe/
    
    # Configure nginx
    cat > /etc/nginx/sites-available/pxe <<EOF
server {
    listen 80;
    server_name ${SERVER_IP};
    root /var/www/pxe;
    
    location / {
        autoindex on;
    }
    
    location /install-agent.sh {
        add_header Content-Type text/plain;
    }
}
EOF
    
    ln -sf /etc/nginx/sites-available/pxe /etc/nginx/sites-enabled/
    rm -f /etc/nginx/sites-enabled/default
    
    systemctl restart nginx
    systemctl enable nginx
}

# Main installation flow
main() {
    log_info "Starting PXE boot server setup..."
    
    install_packages
    configure_dnsmasq
    setup_tftp
    configure_nfs
    prepare_os_images
    setup_http_server
    
    log_info "PXE boot server setup complete!"
    log_info "Server IP: ${SERVER_IP}"
    log_info "DHCP Range: ${DHCP_RANGE_START} - ${DHCP_RANGE_END}"
    log_info "TFTP Root: ${TFTP_ROOT}"
    log_info "NFS Root: ${NFS_ROOT}"
    
    # Test services
    log_info "Testing services..."
    systemctl status dnsmasq --no-pager | head -5
    systemctl status nfs-kernel-server --no-pager | head -5
    systemctl status nginx --no-pager | head -5
    
    log_info "Setup complete! Robots can now network boot from this server."
}

# Run main function
main "$@"