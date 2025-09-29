# Lekiwi/XLE Robot Factory Install System

## Overview

This factory install system provides zero-touch network boot installation for Lekiwi and XLE model robots running on Raspberry Pi 4 and 5. The system automatically detects hardware, installs a lightweight monitoring agent, and configures the robot for production use.

### Key Features

- **Zero-touch deployment** via PXE boot or USB image
- **Automatic hardware detection** (Lekiwi 9 servos vs XLE dual arms + RealSense)
- **Lightweight monitoring agent** (<50MB RAM usage)
- **Real-time polling** without impacting teleoperation
- **mTLS security** for secure communication
- **Rollback capability** with multiple recovery levels
- **Cloud-init support** for automated configuration

## System Requirements

### Hardware
- Raspberry Pi 4 or 5 (minimum 2GB RAM)
- Minimum 8GB SD card or network boot capability
- Ethernet connection for PXE boot (optional)

### Network
- DHCP server for automatic IP assignment
- DNS server (optional, mDNS/Avahi supported)
- Internet connection for package downloads

## Quick Start

### 1. Setting Up the PXE Boot Server

```bash
# Run on the deployment server
cd factory-install/boot-server
sudo ./pxe-config.sh

# The script will:
# - Install and configure dnsmasq for DHCP/TFTP
# - Set up NFS for network booting
# - Download and prepare Raspberry Pi OS images
# - Configure PXE boot menus
```

### 2. Preparing USB Installation Media

```bash
# Create bootable USB with cloud-init
cd factory-install
sudo dd if=raspios-lite.img of=/dev/sdX bs=4M status=progress
sudo mkdir -p /mnt/boot
sudo mount /dev/sdX1 /mnt/boot
sudo cp cloud-init/user-data.yaml /mnt/boot/
sudo touch /mnt/boot/ssh
sudo umount /mnt/boot
```

### 3. Building the Monitoring Agent

```bash
cd factory-install/agent
cargo build --release --target aarch64-unknown-linux-gnu
# Binary will be at: target/release/lekiwi-agent
```

## Installation Process

### Network Boot (PXE)

1. **Configure Raspberry Pi for network boot:**
   ```bash
   # On Raspberry Pi 4
   sudo raspi-config
   # Advanced Options > Boot Order > Network Boot
   
   # On Raspberry Pi 5
   # Edit /boot/firmware/config.txt
   # Add: boot_order=0xf21
   ```

2. **Connect to network and power on**
   - Robot will automatically receive DHCP lease
   - PXE boot menu will appear (or auto-boot if configured)
   - System will boot from NFS root

3. **First boot configuration:**
   - Hardware detection runs automatically
   - Robot type determined (Lekiwi/XLE)
   - Unique robot ID generated
   - Monitoring agent installed and started

### USB/SD Card Installation

1. **Insert prepared media and boot**
2. **Cloud-init runs automatically:**
   - Configures network
   - Installs required packages
   - Runs hardware detection
   - Installs monitoring agent
3. **System reboots with new configuration**

## Hardware Detection

The system automatically detects robot type based on hardware:

### Lekiwi Detection
- PCA9685 servo controller at I2C address 0x40
- 9 servo configuration
- GPIO access for additional sensors

### XLE Detection
- Intel RealSense camera (USB)
- Dynamixel servo controllers
- STM32 or FTDI USB controllers
- Dual arm configuration

## Monitoring Agent

### Features
- Written in Rust for minimal resource usage
- REST API on port 8080
- Heartbeat to control server every 5 seconds
- Tracks static system info (cached until reboot)
- Dynamic updates for video/teleop status
- Automatic reboot detection

### API Endpoints
```bash
# Health check
curl http://localhost:8080/health

# Get robot status
curl http://localhost:8080/status

# Manual heartbeat trigger
curl -X POST http://localhost:8080/heartbeat
```

### Resource Limits
- Maximum 50MB RAM usage
- 10% CPU quota
- Automatic restart on failure

## Security Configuration

### mTLS Setup

1. **On control server:**
```bash
cd factory-install/security
sudo ./setup-mtls.sh server
```

2. **On robot:**
```bash
cd factory-install/security
sudo ./setup-mtls.sh robot [ROBOT_ID] [ROBOT_TYPE]
```

### Certificate Management
- Certificates stored in `/etc/lekiwi/certs/`
- Private keys in `/etc/lekiwi/keys/`
- Automatic rotation 30 days before expiry
- Daily rotation check via systemd timer

## Rollback and Recovery

### Rollback Levels

#### 1. Soft Reset
Clears configuration and state while preserving system:
```bash
sudo /usr/local/bin/factory-reset.sh soft
```
- Stops services
- Clears agent state
- Regenerates SSH keys
- Resets network configuration
- Re-runs hardware detection

#### 2. Hard Reset
Reinstalls packages and resets system configuration:
```bash
sudo /usr/local/bin/factory-reset.sh hard
```
- Performs soft reset first
- Removes custom packages
- Resets hostname and boot configuration
- Removes custom services
- Reinstalls from recovery partition

#### 3. Factory Reset
Complete system restore from factory image:
```bash
sudo /usr/local/bin/factory-reset.sh factory
```
- Downloads factory image if not present
- Completely overwrites system disk
- Returns to original Raspberry Pi OS state

### Backup and Restore

#### Create Backup
```bash
sudo /usr/local/bin/factory-reset.sh backup
```
Backs up:
- `/etc/lekiwi/` configuration
- Robot identification files
- Network configuration
- Service definitions
- Agent state

#### Restore from Backup
```bash
sudo /usr/local/bin/factory-reset.sh restore [backup-file.tar.gz]
```

### Emergency Recovery Mode
```bash
sudo /usr/local/bin/factory-reset.sh recovery
```
- Enables SSH access
- Creates recovery user (password: recovery)
- Starts minimal network services
- Provides command-line recovery options

## Validation and Testing

### Run Full Validation Suite
```bash
sudo /usr/local/bin/validate-install.sh
```

### Test Categories
1. **Prerequisites** - Raspberry Pi detection, kernel version
2. **System Resources** - Memory, disk space, CPU
3. **Hardware Detection** - Robot type, peripherals
4. **Network** - Connectivity, DNS, mDNS
5. **Agent** - Installation, service status, API
6. **Security** - SSH config, certificates, firewall
7. **Performance** - Boot time, CPU, I/O benchmarks
8. **Services** - Required services running
9. **Robot Hardware** - Type-specific hardware tests
10. **Rollback Capability** - Recovery mechanisms

### Test Report
- Saved to `/var/log/lekiwi-tests/`
- Success rate calculation
- Pass/Fail/Skip summary
- Detailed logs for debugging

## Troubleshooting

### Agent Not Starting
```bash
# Check service status
systemctl status lekiwi-agent

# View logs
journalctl -u lekiwi-agent -f

# Test agent manually
/usr/local/bin/lekiwi-agent --debug
```

### Hardware Not Detected
```bash
# Re-run detection
sudo /usr/local/bin/detect-hardware.sh

# Check I2C devices (Lekiwi)
i2cdetect -y 1

# Check USB devices (XLE)
lsusb -v
```

### Network Boot Fails
```bash
# On PXE server, check services
systemctl status dnsmasq
systemctl status nfs-kernel-server

# Check TFTP files
ls -la /srv/tftp/

# Monitor DHCP requests
tail -f /var/log/syslog | grep dnsmasq
```

### Certificate Issues
```bash
# Verify certificates
openssl verify -CAfile /etc/lekiwi/certs/ca-cert.pem \
    /etc/lekiwi/certs/client-cert.pem

# Check expiry
openssl x509 -in /etc/lekiwi/certs/client-cert.pem \
    -noout -enddate

# Force rotation
sudo /usr/local/bin/rotate-robot-cert.sh
```

## File Structure

```
factory-install/
├── agent/                  # Rust monitoring agent
│   ├── Cargo.toml
│   └── src/main.rs
├── boot-server/           # PXE boot configuration
│   └── pxe-config.sh
├── cloud-init/            # Cloud-init configuration
│   └── user-data.yaml
├── scripts/               # Installation scripts
│   ├── detect-hardware.sh
│   ├── systemd-services.sh
│   └── factory-reset.sh
├── security/              # Security configuration
│   └── setup-mtls.sh
├── validation/            # Testing procedures
│   └── validate-install.sh
└── docs/                  # Documentation
    └── README.md
```

## Configuration Files

### Robot Configuration (`/etc/robot.conf`)
```bash
ROBOT_TYPE=lekiwi
ROBOT_ID=uuid-here
HOSTNAME=lekiwi-abc123
MAC_ADDRESS=dc:a6:32:xx:xx:xx
CONFIGURED_AT=2024-01-01T00:00:00Z
```

### Hardware Configuration (`/etc/lekiwi/hardware.conf`)
```bash
ROBOT_TYPE=lekiwi
RASPBERRY_PI_VERSION=5
MEMORY_SIZE=8GB
I2C_DEVICES=PCA9685@0x40
SERVO_COUNT=9
CAMERA_TYPE=none
```

### Agent Configuration (`/etc/lekiwi/agent.env`)
```bash
CONTROL_SERVER=https://control.lekiwi.io:8443
ENABLE_MTLS=true
ROBOT_ID=uuid-here
```

## Performance Specifications

### Resource Usage
- Agent: <50MB RAM, <10% CPU
- Boot time: <30 seconds (network boot)
- Heartbeat interval: 5 seconds
- State file size: <1KB
- Network bandwidth: <1KB/s average

### Scalability
- Supports 100+ robots per PXE server
- Parallel installation capability
- Automatic load distribution
- Minimal control server overhead

## Security Considerations

### Network Security
- mTLS for all robot-server communication
- Certificate-based authentication
- Automatic certificate rotation
- Firewall rules (UFW)

### System Security
- No default passwords
- SSH key-only authentication
- Minimal attack surface
- Regular security updates
- Secure boot support (Pi 5)

## Development and Contribution

### Building from Source
```bash
# Clone repository
git clone https://github.com/lekiwi/factory-install.git
cd factory-install

# Build agent
cd agent
cargo build --release

# Run tests
cargo test
```

### Testing Changes
1. Use validation suite for regression testing
2. Test on both Pi 4 and Pi 5
3. Verify both Lekiwi and XLE configurations
4. Check resource usage remains within limits

## Support and Maintenance

### Log Files
- Agent logs: `journalctl -u lekiwi-agent`
- Hardware detection: `/var/log/lekiwi-hardware-detect.log`
- Factory reset: `/var/log/factory-reset.log`
- Validation tests: `/var/log/lekiwi-tests/`

### Monitoring
- Prometheus metrics: `http://robot:8080/metrics`
- Health endpoint: `http://robot:8080/health`
- Status endpoint: `http://robot:8080/status`

### Updates
- Automatic agent updates via systemd timer
- Manual update: `sudo /usr/local/bin/lekiwi-update.sh`
- Rollback on update failure

## License

MIT License - See LICENSE file for details

## Contact

- Documentation: https://docs.lekiwi.io
- Support: support@lekiwi.io
- Issues: https://github.com/lekiwi/factory-install/issues