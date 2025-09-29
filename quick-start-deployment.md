# LeKiwi Deploy - Quick Start Guide 🚀
## Get Your Vercel-Style Deployment Running NOW!

### What You'll Have in 5 Minutes
- ✅ Auto-discovery of all robots on network
- ✅ Web dashboard at http://localhost:8000
- ✅ Automatic robot configuration fixing
- ✅ Real-time deployment status
- ✅ No manual setup required!

## Step 1: Start the Deployment System (30 seconds!)

### The ACTUAL Way - Using the Startup Script

```bash
# Clone the repository
git clone https://github.com/your-org/lekiwi-heartbeat.git
cd lekiwi-heartbeat

# Make the script executable
chmod +x start-deployment-system.sh

# Start the system (it handles EVERYTHING automatically!)
./start-deployment-system.sh

# Or start in development mode for verbose output
./start-deployment-system.sh --dev
```

**That's it!** The script automatically:
- ✅ Installs Python dependencies (fastapi, uvicorn, aiohttp, pydantic)
- ✅ Installs sshpass for robot communication
- ✅ Creates deployment directories in `~/.lekiwi-deploy/`
- ✅ Discovers all robots on your network (192.168.88.x)
- ✅ Cleans up any hung processes from previous runs
- ✅ Starts the deployment server on port 8000
- ✅ Opens the web dashboard

### What the Script Actually Does

1. **Dependency Installation** (automatic):
   ```bash
   # Python packages (installed quietly)
   pip3 install fastapi uvicorn aiohttp pydantic
   
   # SSH tool for robot access
   brew install hudochenkov/sshpass/sshpass  # macOS
   apt-get install sshpass                   # Linux
   ```

2. **Robot Discovery** (automatic):
   ```bash
   # Runs automatically if no fleet config exists
   cd deployment-server
   python3 smart_discover.py
   python3 add_discovered_robots.py
   ```

3. **Server Startup** (automatic):
   ```bash
   # Starts with appropriate settings
   python3 -m uvicorn server:app --host 0.0.0.0 --port 8000
   ```

## Step 2: Access the Web Dashboard

Open your browser to: **http://localhost:8000**

You'll see:
- Real-time robot status grid
- Deployment controls
- Robot configuration management
- Live logs

## Step 3: Check Discovered Robots

```bash
# View the auto-discovered fleet
cat /tmp/lekiwi_fleet.json | python3 -m json.tool

# Check robot types detected
cat /tmp/robot_types.json | python3 -m json.tool

# See discovery results
cat /tmp/smart_discovered.txt
```

## Step 4: Deploy to Robots (Using Existing Scripts)

The system includes deployment scripts that work with discovered robots:

### Fix Robot Configuration (teleop.ini)

```bash
# Fix teleop configuration for a specific robot
python3 deployment-master/lekiwi-master-deploy.py 192.168.88.64 --action teleop-only

# Check robot status
python3 deployment-master/lekiwi-master-deploy.py 192.168.88.64 --action check

# Full deployment from reference robot
python3 deployment-master/lekiwi-master-deploy.py 192.168.88.64 --action full
```

### Deploy Using the Web Interface

1. Open http://localhost:8000
2. Click on a robot in the grid
3. Select deployment action
4. Monitor progress in real-time

## How the System ACTUALLY Works

### Directory Structure Created

The startup script creates these directories automatically:

```bash
~/.lekiwi-deploy/
├── deployments/    # Deployment packages
├── packages/       # Built packages
├── repos/          # Git repositories
└── logs/          # Server logs

/tmp/
├── lekiwi_fleet.json         # Auto-discovered robots
├── robot_types.json          # Hardware type detection
├── discovery_results.json    # Raw discovery data
├── smart_discovered.txt      # Discovery log
└── robot_comparisons/        # Configuration comparisons
```

### Environment Variables Set

The script sets these automatically:

```bash
export DEPLOY_PORT=8000
export DEPLOYMENTS_DIR="$HOME/.lekiwi-deploy/deployments"
export PACKAGES_DIR="$HOME/.lekiwi-deploy/packages"
export REPOS_DIR="$HOME/.lekiwi-deploy/repos"
export GITHUB_REPO="https://github.com/huggingface/lerobot.git"
```

### Process Management

The script handles all process management:

```bash
# Automatic cleanup of hung processes
pkill -9 -f "uvicorn server:app"
pkill -9 -f "python.*server.py"
pkill -9 -f "python.*smart_discover.py"

# Port management
lsof -ti:8000 | xargs kill -9
fuser -k 8000/tcp

# SSH cleanup
pkill -f "ssh.*192.168.88.*"
```

## What You ACTUALLY Have Right Now

✅ **Auto-Discovery**: All robots found automatically
✅ **Web Dashboard**: Already running at http://localhost:8000
✅ **Robot Detection**: Identifies robot types (xlerobot vs lekiwi5)
✅ **Configuration Fixing**: Automatic teleop.ini correction
✅ **Deployment Scripts**: Ready-to-use Python deployment tools
✅ **Clean Process Management**: No more hung processes

## Development vs Production Mode

### Production Mode (Default)
```bash
./start-deployment-system.sh
```
- Minimal output
- Automatic cleanup
- Silent dependency installation
- Error logging only

### Development Mode
```bash
./start-deployment-system.sh --dev
```
- Verbose output
- Interactive prompts
- Detailed logging
- Reload on file changes

## Troubleshooting

### Server Won't Start?

The script handles this automatically, but if needed:

```bash
# Script already kills processes, but manually:
lsof -ti:8000 | xargs kill -9

# Check what's running
ps aux | grep -E "uvicorn|server.py"

# View startup in dev mode for debugging
./start-deployment-system.sh --dev
```

### Robots Not Discovered?

```bash
# Clean discovery files and re-run
./start-deployment-system.sh --clean-discovery

# Or manually remove and restart
rm /tmp/lekiwi_fleet.json
./start-deployment-system.sh
```

### Check Discovery Results

```bash
# View discovered robots
cat /tmp/smart_discovered.txt

# Check fleet configuration
cat /tmp/lekiwi_fleet.json | python3 -m json.tool

# See robot types
cat /tmp/robot_types.json | python3 -m json.tool
```

---

**You're done! The system is ALREADY RUNNING! 🚀**

Just run:
```bash
./start-deployment-system.sh
```

And access: **http://localhost:8000**

Total setup time: **30 seconds**
Manual configuration: **ZERO**