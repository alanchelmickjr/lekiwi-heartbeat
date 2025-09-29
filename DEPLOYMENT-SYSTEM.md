# LeKiwi Deployment System - Complete Documentation

## 🚀 Quick Start

```bash
# Clone the repository
git clone https://github.com/your-org/lekiwi-heartbeat.git
cd lekiwi-heartbeat

# Make the startup script executable
chmod +x start-deployment-system.sh

# Start the deployment system
./start-deployment-system.sh

# Or start in development mode with verbose output
./start-deployment-system.sh --dev
```

**That's it!** The system is now running at http://localhost:8000

## 📋 What This System ACTUALLY Does

### ✅ Working Features
- **Auto-discovers robots** on your network (192.168.88.x subnet)
- **Detects robot types** (xlerobot vs lekiwi5 hardware)
- **Fixes teleop.ini** configuration issues automatically
- **Provides web dashboard** for monitoring and control
- **SSH-based deployment** from reference robots
- **Status checking** for individual robots

### ⚠️ Partially Implemented
- Basic agent exists (`deployment-agent/agent.py`) but not integrated
- CLI tools exist (`deployment-cli/`) but need configuration
- Web dashboard exists but missing some features

### ❌ Not Implemented (But Documented Elsewhere)
- Git webhook auto-deployment
- Instant rollback to previous versions
- Deployment history with versioning
- Real-time WebSocket logs
- PostgreSQL storage
- Health checks and auto-rollback

## 🏗️ System Architecture

```
┌─────────────────────────────────────────────────────┐
│           start-deployment-system.sh                 │
│                      ↓                               │
│         [Installs Dependencies]                      │
│                      ↓                               │
│         [Discovers Robots on Network]                │
│                      ↓                               │
│         [Starts Web Server on :8000]                 │
└─────────────────────────────────────────────────────┘
                      ↓
┌─────────────────────────────────────────────────────┐
│           deployment-server/server.py                │
│         • Serves Web Dashboard                       │
│         • Provides REST APIs                         │
│         • Manages Robot Fleet                        │
└─────────────────────────────────────────────────────┘
                      ↓
┌─────────────────────────────────────────────────────┐
│     deployment-master/lekiwi-master-deploy.py       │
│         • SSH Connection to Robots                   │
│         • Configuration Fixing                       │
│         • Code Deployment                            │
└─────────────────────────────────────────────────────┘
```

## 📁 Project Structure

```
lekiwi-heartbeat/
├── start-deployment-system.sh          # Main startup script - USE THIS!
│
├── deployment-server/                  # Web server components
│   ├── server.py                      # FastAPI server
│   ├── smart_discover.py              # Network robot discovery
│   ├── detect_robot_type.py           # Hardware detection
│   ├── comparison_engine.py           # Configuration comparison
│   ├── robot_versioning.py            # Version management
│   └── static/
│       ├── index.html                 # Web dashboard
│       └── comparison.html            # Comparison UI
│
├── deployment-master/                  # Deployment tools
│   ├── lekiwi-master-deploy.py       # Main deployment script
│   └── lekiwi-robot-deploy.sh        # Bash alternative
│
├── deployment-agent/                   # Robot agent (partial)
│   ├── agent.py                       # Basic implementation
│   └── install.sh                     # Installation script
│
└── deployment-cli/                     # CLI tools (partial)
    ├── lekiwi-deploy                  # Deployment CLI
    └── lekiwi-complete                # Bash completion
```

## 🔧 Configuration

### Environment Variables (Set by startup script)
```bash
DEPLOY_PORT=8000
DEPLOYMENTS_DIR="$HOME/.lekiwi-deploy/deployments"
PACKAGES_DIR="$HOME/.lekiwi-deploy/packages"
REPOS_DIR="$HOME/.lekiwi-deploy/repos"
GITHUB_REPO="https://github.com/huggingface/lerobot.git"
```

### Auto-Generated Files
```
/tmp/lekiwi_fleet.json         # Discovered robots
/tmp/robot_types.json          # Hardware types
/tmp/discovery_results.json    # Raw discovery data
/tmp/smart_discovered.txt      # Discovery log
```

## 💻 Command Reference

### Starting the System
```bash
# Production mode (minimal output)
./start-deployment-system.sh

# Development mode (verbose)
./start-deployment-system.sh --dev

# Clean discovery cache and restart
./start-deployment-system.sh --clean-discovery

# Show help
./start-deployment-system.sh --help
```

### Robot Management
```bash
# Check robot status
python3 deployment-master/lekiwi-master-deploy.py 192.168.88.64 --action check

# Fix teleop.ini configuration
python3 deployment-master/lekiwi-master-deploy.py 192.168.88.64 --action teleop-only

# Full deployment from reference robot
python3 deployment-master/lekiwi-master-deploy.py 192.168.88.64 --action full

# Deploy from specific source
python3 deployment-master/lekiwi-master-deploy.py 192.168.88.64 --source 192.168.88.21
```

### Checking System State
```bash
# View discovered robots
cat /tmp/lekiwi_fleet.json | python3 -m json.tool

# Check robot types
cat /tmp/robot_types.json | python3 -m json.tool

# View discovery log
cat /tmp/smart_discovered.txt
```

## 🌐 Web Dashboard

Access at http://localhost:8000 after starting the system.

### Available Endpoints
- `/` - Main dashboard
- `/health` - Health check endpoint
- `/api/info` - Server information
- `/api/robots` - List discovered robots
- `/api/deployments` - Deployment operations

## 🛠️ Troubleshooting

### Server Won't Start
```bash
# The startup script auto-handles port conflicts, but if needed:
lsof -ti:8000 | xargs kill -9
```

### Robots Not Discovered
```bash
# Clean and re-discover
./start-deployment-system.sh --clean-discovery
```

### SSH Connection Issues
```bash
# Ensure sshpass is installed (auto-installed by script)
which sshpass || brew install hudochenkov/sshpass/sshpass
```

### View Logs in Dev Mode
```bash
# Start with verbose logging
./start-deployment-system.sh --dev
```

## 📝 Development vs Production Mode

### Production Mode (Default)
- Minimal console output
- Automatic dependency installation
- Silent error handling
- Log level: ERROR only

### Development Mode (--dev flag)
- Verbose console output
- Interactive prompts
- Detailed error messages
- Log level: INFO
- Auto-reload on file changes

## 🔄 Process Management

The startup script automatically:
- Kills hung processes from previous runs
- Cleans up stale SSH connections
- Frees port 8000 if occupied
- Removes temporary files (optionally)

## 🚦 System Status

### Green (Working)
- Robot discovery
- Web dashboard
- Configuration fixing
- SSH deployment

### Yellow (Partial)
- Robot agent (exists but not integrated)
- CLI tools (exist but need setup)

### Red (Not Implemented)
- Git webhooks
- Version rollback
- Deployment history
- Real-time logs
- Health checks

## 📚 Related Documentation

### Active Documentation
- `README-DEPLOYMENT-SYSTEM.md` - Detailed system overview
- `README-DEPLOYMENT.md` - Implementation summary
- `quick-start-deployment.md` - Quick start guide
- `DEPLOYMENT-DOCS-CONSOLIDATION.md` - Documentation audit

### Archived (Theoretical Features)
- `docs/archive/theoretical-features/deployment-architecture.md`
- `docs/archive/theoretical-features/deployment-implementation.md`
- `docs/archive/theoretical-features/vercel-for-robots.md`

## 🎯 Future Roadmap

If you want to implement the theoretical features:

1. **Phase 1**: Integrate the existing agent
2. **Phase 2**: Add Git webhook support
3. **Phase 3**: Implement version management
4. **Phase 4**: Add rollback capability
5. **Phase 5**: Real-time WebSocket logs

## 📞 Support

For issues with the ACTUAL system:
1. Check this documentation first
2. Run in dev mode for detailed errors
3. Check the `/tmp/*.json` files for discovery issues
4. Verify SSH access to robots

---

**Remember**: This documentation describes what ACTUALLY exists and works. For theoretical features that were never built, see the archived documentation.