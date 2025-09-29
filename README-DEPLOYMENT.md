# 🚀 LeKiwi Deployment System - ACTUAL Implementation

## What Actually Exists Right Now

This is the REAL deployment system that's implemented and working in the codebase. No theoretical features - just what's actually built.

---

## 🎯 What This System Actually Does

- **Auto-discovers robots** on your network (192.168.88.x subnet)
- **Detects robot types** (xlerobot vs lekiwi5)
- **Fixes teleop.ini configuration** automatically
- **Provides web dashboard** at http://localhost:8000
- **Manages robot deployments** via Python scripts

---

## 📦 What's Actually in the Codebase

```
lekiwi-heartbeat/
├── start-deployment-system.sh       # MAIN STARTUP SCRIPT - USE THIS!
│
├── deployment-server/               # Server components
│   ├── server.py                   # FastAPI web server & API
│   ├── smart_discover.py           # Network robot discovery
│   ├── add_discovered_robots.py    # Converts discoveries to fleet config
│   ├── detect_robot_type.py        # Hardware type detection
│   ├── comparison_engine.py        # Robot config comparison
│   ├── robot_versioning.py         # Version management
│   ├── server_discovery.py         # Additional discovery tools
│   └── static/
│       ├── index.html              # Web dashboard UI
│       └── comparison.html         # Comparison UI
│
├── deployment-master/               # Deployment scripts
│   ├── lekiwi-master-deploy.py    # Python deployment tool
│   └── lekiwi-robot-deploy.sh     # Bash deployment script
│
├── deployment-agent/                # Robot agent (basic)
│   ├── agent.py                    # Simple robot agent
│   └── install.sh                  # Agent installer
│
├── deployment-cli/                  # CLI tools
│   ├── lekiwi-deploy               # Deployment CLI
│   └── lekiwi-complete             # Completion script
│
└── deployment-ssh/                  # SSH tools
    └── ssh-proxy-server.py         # SSH proxy server
```

---

## ⚡ How to ACTUALLY Start the System

### The One Command That Works:

```bash
# Clone the repo
git clone https://github.com/your-org/lekiwi-heartbeat.git
cd lekiwi-heartbeat

# Make script executable
chmod +x start-deployment-system.sh

# Start everything (production mode)
./start-deployment-system.sh

# Or start with verbose output (development mode)
./start-deployment-system.sh --dev
```

**That's it!** The script handles everything:
- Installs Python dependencies
- Discovers robots on network
- Starts the web server
- Opens dashboard at http://localhost:8000

---

## 🎮 What You Can Actually Do Right Now

### Check Robot Status
```bash
# Using the deployment master script
python3 deployment-master/lekiwi-master-deploy.py 192.168.88.64 --action check
```

### Fix Robot Configuration
```bash
# Fix teleop.ini configuration
python3 deployment-master/lekiwi-master-deploy.py 192.168.88.64 --action teleop-only
```

### Deploy to Robot
```bash
# Full deployment from reference robot
python3 deployment-master/lekiwi-master-deploy.py 192.168.88.64 --action full

# Deploy from specific source robot
python3 deployment-master/lekiwi-master-deploy.py 192.168.88.64 --source 192.168.88.21
```

### View Discovered Robots
```bash
# Check discovered fleet
cat /tmp/lekiwi_fleet.json | python3 -m json.tool

# View robot types
cat /tmp/robot_types.json | python3 -m json.tool
```

---

## 🔧 Actual Configuration Files Used

### Fleet Configuration (Auto-Generated)
```json
// /tmp/lekiwi_fleet.json - Created by smart_discover.py
{
  "robots": [
    {
      "ip": "192.168.88.57",
      "hostname": "xlerobot1",
      "type": "xlerobot"
    },
    {
      "ip": "192.168.88.64",
      "hostname": "lekiwi5",
      "type": "lekiwi5"
    }
  ],
  "total": 2
}
```

### Robot Types (Auto-Detected)
```json
// /tmp/robot_types.json - Created by detect_robot_type.py
{
  "192.168.88.57": {
    "type": "xlerobot",
    "cameras": 3,
    "arms": "bimanual"
  }
}
```

### Comparison Configuration
```json
// deployment-server/comparison_config.json
{
  "paths_to_compare": [
    "/opt/frodobots/bin",
    "/opt/frodobots/FrodoBots-Lib",
    "/opt/frodobots/teleop.ini"
  ]
}
```

---

## 🏗️ How It Actually Works

```
┌─────────────────────────────────────────────────────┐
│           start-deployment-system.sh                 │
│  • Installs dependencies                             │
│  • Runs robot discovery                              │
│  • Starts web server                                 │
└────────────────────┬────────────────────────────────┘
                     ▼
┌─────────────────────────────────────────────────────┐
│         deployment-server/server.py                  │
│  • FastAPI web server on port 8000                   │
│  • Serves web dashboard                              │
│  • Provides REST APIs                                │
└────────────────────┬────────────────────────────────┘
                     ▼
┌─────────────────────────────────────────────────────┐
│           Robot Discovery Process                    │
│  • smart_discover.py scans network                   │
│  • detect_robot_type.py identifies hardware          │
│  • Creates /tmp/lekiwi_fleet.json                   │
└────────────────────┬────────────────────────────────┘
                     ▼
┌─────────────────────────────────────────────────────┐
│     deployment-master/lekiwi-master-deploy.py       │
│  • Connects to robots via SSH                        │
│  • Fixes teleop.ini configuration                    │
│  • Deploys code from reference robot                 │
└─────────────────────────────────────────────────────┘
```

---

## 🛠️ Actual Features That Work

### Robot Discovery
- Scans 192.168.88.x subnet
- Identifies robot hostnames
- Detects robot hardware types
- Creates fleet configuration

### Configuration Management
- Reads teleop.ini files
- Fixes incorrect device IDs
- Generates proper tokens
- Updates robot configurations

### Deployment Capabilities
- SSH-based deployment
- Reference robot cloning
- Service management
- Status checking

---

## 📊 Monitoring & Logs

### Server Logs
```bash
# When running in dev mode, logs show in terminal
./start-deployment-system.sh --dev

# Production logs are minimal
./start-deployment-system.sh  # Only errors shown

# Check Python server logs
ps aux | grep uvicorn
```

### Discovery Results
```bash
# View discovery log
cat /tmp/smart_discovered.txt

# Check fleet configuration
cat /tmp/lekiwi_fleet.json

# View robot types
cat /tmp/robot_types.json
```

---

## 🚨 Troubleshooting

### Server Won't Start

The script handles this automatically:
```bash
# Script auto-kills processes on port 8000
# But if you need manual control:
lsof -ti:8000 | xargs kill -9
fuser -k 8000/tcp
```

### Robots Not Discovered

```bash
# Clean discovery files
./start-deployment-system.sh --clean-discovery

# Or manually
rm /tmp/lekiwi_fleet.json /tmp/smart_discovered.txt
./start-deployment-system.sh
```

### SSH Connection Issues

```bash
# Test SSH to robot
ssh lekiwi@192.168.88.64

# Check if sshpass is installed
which sshpass || brew install hudochenkov/sshpass/sshpass
```

---

## 🎯 What Actually Works

### Working Features
- ✅ **Auto-discovery** of robots on network
- ✅ **Web dashboard** at http://localhost:8000
- ✅ **Robot type detection** (xlerobot vs lekiwi5)
- ✅ **Teleop.ini fixing** for incorrect configurations
- ✅ **SSH-based deployment** from reference robot
- ✅ **Status checking** for individual robots

### What's Partially Implemented
- ⚠️ Basic agent exists but not fully integrated
- ⚠️ CLI tools exist but need configuration
- ⚠️ Web UI exists but some features incomplete

---

## 📈 Actual System Status

### What's Implemented ✅
- [x] Startup script that handles everything
- [x] Robot discovery system
- [x] Robot type detection
- [x] Web server with dashboard
- [x] Deployment master scripts
- [x] Configuration fixing tools

### What Needs Work
- [ ] Full agent integration on robots
- [ ] GitHub webhook integration
- [ ] Database storage (currently uses files)
- [ ] Real-time WebSocket updates

---

## 🤝 How to Use What's Built

1. **Start the system**: `./start-deployment-system.sh`
2. **Access dashboard**: http://localhost:8000
3. **Check robots**: Look at `/tmp/lekiwi_fleet.json`
4. **Fix robot config**: Use `lekiwi-master-deploy.py`
5. **Deploy code**: Use deployment master scripts

---

## 🎊 Summary

This is the ACTUAL deployment system as it exists in the codebase. It provides:
- Automatic robot discovery
- Configuration management
- Web-based monitoring
- SSH-based deployment tools

Run `./start-deployment-system.sh` and it works out of the box!

---

*This documentation reflects the ACTUAL implementation, not theoretical features*