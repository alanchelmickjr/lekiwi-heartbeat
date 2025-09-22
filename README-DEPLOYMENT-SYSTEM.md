# 🚀 LeKiwi Deployment System

## Vercel-Style Push-to-Deploy for Robot Fleets

A complete deployment system that brings modern CI/CD practices to robotics. Just like Vercel revolutionized web deployment, this system makes robot fleet management as simple as `git push`.

## ✨ Features

### Web Dashboard (http://localhost:8000)
- **Real-time Robot Monitoring** - See all robots status at a glance
- **One-Click Deployments** - Deploy new versions with a single button
- **Instant Rollbacks** - Roll back to any previous version instantly
- **Live Logs** - Watch deployment progress in real-time
- **Dark Theme UI** - Beautiful Vercel-inspired interface

### Deployment Capabilities
- **Git-Based Deployments** - Deploy directly from GitHub branches
- **Automatic Robot Configuration** - Fixes teleop.ini device IDs automatically
- **Multiple Deployment Strategies** - All robots, groups, or individual
- **Version Management** - Track and manage all deployment versions
- **Health Monitoring** - Automatic health checks and status updates

## 🚀 Quick Start

### 1. Start the Deployment System

```bash
# Make scripts executable
chmod +x start-deployment-system.sh

# Start the server with web GUI
./start-deployment-system.sh
```

Open http://localhost:8000 in your browser

### 2. Check Robot Status

From the web interface or command line:

```bash
# Check individual robot
python3 deployment-master/lekiwi-master-deploy.py 192.168.88.21 --action check

# Check all known robots
python3 deployment-master/lekiwi-master-deploy.py 192.168.88.57 --action check
python3 deployment-master/lekiwi-master-deploy.py 192.168.88.64 --action check
```

### 3. Fix Robot Configuration

The system automatically fixes the teleop.ini device ID issue:

```bash
# Fix teleop configuration only
python3 deployment-master/lekiwi-master-deploy.py 192.168.88.64 --action teleop-only
```

### 4. Deploy to Robots

From the web interface or command line:

```bash
# Full deployment to a robot
python3 deployment-master/lekiwi-master-deploy.py 192.168.88.64 --action full

# Deploy to all robots via API
curl -X POST http://localhost:8000/api/deploy \
  -H "Content-Type: application/json" \
  -d '{"version": "v2.1.0", "branch": "main", "target_group": "all"}'
```

## 📁 Project Structure

```
lekiwi-heartbeat/
├── deployment-server/          # Main deployment server
│   ├── server.py              # FastAPI backend with all APIs
│   └── static/
│       └── index.html         # Web dashboard (Vercel-style)
│
├── deployment-master/          # Robot deployment scripts
│   ├── lekiwi-master-deploy.py  # Python deployment tool
│   └── lekiwi-robot-deploy.sh   # Bash alternative
│
├── deployment-agent/           # Robot-side agent
│   └── agent.py               # Runs on each robot
│
├── deployment-gun/             # P2P deployment (alternative)
│   ├── gun-deployment-server.py
│   └── gun-robot-agent.py
│
└── start-deployment-system.sh  # Startup script
```

## 🤖 Known Robots

| IP Address | Robot ID | Status | Notes |
|------------|----------|--------|-------|
| 192.168.88.21 | lekiwi_67222140 | ✅ Working | Reference robot |
| 192.168.88.57 | lekiwi_67223052 | ✅ Fixed | Teleop corrected |
| 192.168.88.64 | Unknown | ⚠️ Needs Check | May need teleop fix |

## 🔧 Robot Configuration

### Teleop.ini Format

The system automatically generates the correct configuration:

```ini
[teleop]
token = <base64 encoded: lekiwi:lekiwi666:DEVICE_ID:1000001>
device = lekiwi_XXXXXXXX  # MUST be lowercase lekiwi_

[signal]
device = lekiwi_XXXXXXXX  # Last 8 hex chars of MAC address
```

### Common Issues & Fixes

1. **Wrong Device ID Format** (e.g., `Lekiwi_` instead of `lekiwi_`)
   - The system automatically fixes this
   - Run with `--action teleop-only` to fix just the config

2. **Service Not Starting**
   - Check teleop.ini has correct lowercase device ID
   - Verify all required files in `/opt/frodobots/`

3. **Robot Not Responding**
   - Verify SSH access: `ssh lekiwi@192.168.88.XX`
   - Check network connectivity
   - Verify services: `systemctl status teleop lekiwi`

## 🌐 API Endpoints

### Core Endpoints

- `GET /` - Web dashboard
- `GET /health` - Health check
- `GET /api/info` - Server information
- `POST /api/deploy` - Create new deployment
- `GET /api/deployments` - List all deployments
- `POST /api/rollback` - Rollback to previous version
- `GET /api/robots` - List all robots
- `POST /api/robot/status` - Update robot status
- `GET /api/check-update?robot_id=X` - Check if robot needs update
- `GET /api/download/{deployment_id}` - Download deployment package

### WebSocket

- `WS /ws` - Real-time updates for dashboard

## 🎯 Deployment Workflow

1. **Developer pushes code** → GitHub
2. **Webhook triggers** → Deployment server
3. **Server builds package** → Creates versioned deployment
4. **Robots check for updates** → Pull new version
5. **Automatic rollback** → If health checks fail
6. **Dashboard updates** → Real-time status

## 🔐 Security

- SSH key-based authentication for robots
- Deployment package checksums
- Version tracking and rollback capability
- Restricted command execution
- CORS configured for web access

## 📊 Monitoring

The web dashboard provides:
- Real-time robot status
- Deployment history
- Live logs streaming
- Health metrics
- Quick rollback buttons

## 🚦 Commands Reference

### Server Management
```bash
# Start deployment system
./start-deployment-system.sh

# Manual server start
cd deployment-server
python3 -m uvicorn server:app --reload

# Check server health
curl http://localhost:8000/health
```

### Robot Management
```bash
# Check robot status
python3 deployment-master/lekiwi-master-deploy.py <IP> --action check

# Fix teleop only
python3 deployment-master/lekiwi-master-deploy.py <IP> --action teleop-only

# Full deployment
python3 deployment-master/lekiwi-master-deploy.py <IP> --action full

# Deploy from specific source robot
python3 deployment-master/lekiwi-master-deploy.py <IP> --source 192.168.88.21
```

### Deployment Operations
```bash
# Create deployment via API
curl -X POST http://localhost:8000/api/deploy \
  -H "Content-Type: application/json" \
  -d '{"version": "v2.1.0", "branch": "main"}'

# Rollback to previous
curl -X POST http://localhost:8000/api/rollback \
  -H "Content-Type: application/json" \
  -d '{"deployment_id": "previous"}'

# List deployments
curl http://localhost:8000/api/deployments
```

## 🎨 Web Interface Features

### Main Dashboard
- **Robot Grid** - Visual status of all robots
- **Quick Deploy** - Form for instant deployments
- **Deployment History** - Recent deployments with rollback
- **Live Logs** - Real-time deployment progress

### Robot Management
- **Status Check** - Check individual robot health
- **Deploy to Robot** - Target specific robot
- **Fix Configuration** - Auto-fix teleop.ini issues

### Quick Actions (Floating Buttons)
- **↩️ Rollback** - Instant rollback to previous
- **🔄 Refresh** - Update all statuses

## 📈 Future Enhancements

- [ ] PostgreSQL for deployment history
- [ ] Automated testing before deployment
- [ ] Gradual rollout strategies
- [ ] Performance metrics collection
- [ ] Multi-region deployment support
- [ ] Docker containerization
- [ ] Kubernetes integration
- [ ] CI/CD pipeline integration

## 🆘 Troubleshooting

### Server Won't Start
```bash
# Check if port 8000 is in use
lsof -i:8000

# Kill existing process
kill $(lsof -t -i:8000)

# Check Python dependencies
pip3 list | grep fastapi
```

### Robot Connection Issues
```bash
# Test SSH connection
ssh lekiwi@192.168.88.XX

# Check robot services
ssh lekiwi@192.168.88.XX "systemctl status teleop lekiwi"

# View robot logs
ssh lekiwi@192.168.88.XX "journalctl -u teleop -n 50"
```

### Deployment Failures
```bash
# Check server logs
tail -f deployment-server/logs/server.log

# Verify package creation
ls -la /opt/lekiwi-deploy/packages/

# Manual rollback
python3 deployment-master/lekiwi-master-deploy.py <IP> --action rollback
```

## 📝 License

MIT License - Feel free to use and modify for your robot fleet!

## 🙏 Credits

Built with ❤️ for the LeKiwi robot fleet. Inspired by Vercel's amazing deployment experience.

---

**Remember: With great deployment power comes great robot responsibility! 🤖**