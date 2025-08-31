# 🤖 Lekiwi Fleet Control System

An automated installer and management system for Lekiwi robots that eliminates the tomfoolery out of robot fleet management!

## What This Does

This installer automates the setup and configuration of:
- **Control Station**: Central monitoring and fleet management dashboard
- **Robot Nodes**: Individual robot configuration and environment setup

## Features

### Control Station
- 🌐 Web interface for fleet monitoring (port 8080)
- 🔍 Automatic robot discovery on 192.168.88.x network
- 📊 Real-time status monitoring
- 🎛️ Centralized fleet control

### Robot Node Setup
- 🔧 Automatic device naming using MAC address
- ⚙️ Environment variable management (no more manual `export LD_LIBRARY_PATH`!)
- 📝 Auto-configuration of `teleop.ini` with correct device names
- 🚀 Systemd service management for teleop and lerobot
- 📋 Comprehensive logging

## Quick Start

### Install Control Station
```bash
sudo ./install.sh
# Select option 1 for Control Station
```

### Install on Robot
```bash
sudo ./install.sh  
# Select option 2 for Robot Node
```

## Fleet Management Commands

After installation, use the `fleet-manager` command:

```bash
# Discover all robots on network
fleet-manager discover

# Check robot status
fleet-manager status 192.168.88.21

# Restart services
fleet-manager restart-teleop 192.168.88.21
fleet-manager restart-lerobot 192.168.88.21

# View logs
fleet-manager logs 192.168.88.21 teleop
fleet-manager logs 192.168.88.21 lerobot

# Update robot configuration
fleet-manager update-config 192.168.88.21 teleop token=newtoken123
```

## What Gets Automated

### For Robots
- ✅ Device naming from MAC address (`Lekiwi_XXXXX`)
- ✅ Library path setup (`LD_LIBRARY_PATH=/opt/frodobots/lib`)
- ✅ Service dependencies and startup order
- ✅ Configuration file updates
- ✅ Log management

### For Control Station
- ✅ Network scanning and robot discovery
- ✅ Web interface with real-time monitoring
- ✅ Boot-time status display
- ✅ Service management

## Network Requirements

- Robots should be on the `192.168.88.x` subnet
- SSH access configured between control station and robots
- Port 8080 available for web interface

## Installation Details

- **Installation Path**: `/opt/lekiwi/`
- **Services**: `lekiwi-fleet-control.service`, `lekiwi-env.service`
- **Logs**: `/opt/lekiwi/logs/`
- **Config**: `/opt/lekiwi/config/`

## Web Interface

After installing the control station, access the web interface at:
```
http://<control-station-ip>:8080
```

## Troubleshooting

### Check Service Status
```bash
systemctl status lekiwi-fleet-control  # Control station
systemctl status lekiwi-env            # Robot environment
systemctl status teleop                # Robot teleop
systemctl status lekiwi               # Robot lerobot
```

### View Logs
```bash
journalctl -u lekiwi-fleet-control -f  # Control station logs
tail -f /opt/lekiwi/logs/teleop.log     # Robot teleop logs
tail -f /opt/lekiwi/logs/lerobot.log    # Robot lerobot logs
```

### Manual Robot Discovery
```bash
nmap -sn 192.168.88.0/24
```

## Requirements

- Linux system (Ubuntu/Debian preferred)
- Python 3.7+
- SSH client
- Network access to robots
- Root access for installation

---

**No more tomfoolery!** 🎊

The Lekiwi Fleet Control System automates all the annoying setup tasks so you can focus on making your robots do awesome things.