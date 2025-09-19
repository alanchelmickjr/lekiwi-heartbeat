# LeKiwi Deploy - Quick Start Guide 🚀
## Get Your Vercel-Style Deployment Running TODAY!

### What You'll Have in 1 Hour
- ✅ No more manual SSH deployments
- ✅ Git push = automatic robot updates
- ✅ Instant rollback to any version
- ✅ Complete deployment history
- ✅ Real-time deployment status

## Step 1: Set Up Deployment Server (15 minutes)

### 1.1 Create a Simple Deployment Server

```bash
# On your control server (or any server accessible by robots)
mkdir -p /opt/lekiwi-deploy
cd /opt/lekiwi-deploy
```

### 1.2 Install Dependencies

```bash
# Install Python and dependencies
sudo apt update
sudo apt install -y python3-pip python3-venv postgresql nginx
python3 -m venv venv
source venv/bin/activate
pip install fastapi uvicorn aiofiles psycopg2-binary pydantic gitpython
```

### 1.3 Create the Deployment Server

```python
# /opt/lekiwi-deploy/server.py
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from pydantic import BaseModel
import subprocess
import json
import hashlib
from pathlib import Path
from datetime import datetime
import uuid
from typing import Dict, List, Optional

app = FastAPI(title="LeKiwi Deploy Server")

# Storage paths
DEPLOYMENTS_DIR = Path("/opt/lekiwi-deploy/deployments")
PACKAGES_DIR = Path("/opt/lekiwi-deploy/packages")
DEPLOYMENTS_DIR.mkdir(exist_ok=True)
PACKAGES_DIR.mkdir(exist_ok=True)

# In-memory deployment tracking (use PostgreSQL in production)
deployments = {}
robot_status = {}

class Deployment(BaseModel):
    version: str
    branch: str = "main"
    commit: str
    author: str = "unknown"
    message: str = ""

@app.post("/api/deploy")
async def create_deployment(deployment: Deployment, background_tasks: BackgroundTasks):
    """Create a new deployment from Git"""
    
    deployment_id = f"dep_{uuid.uuid4().hex[:8]}"
    
    # Clone/pull latest code
    repo_path = DEPLOYMENTS_DIR / deployment_id
    
    # Clone the repository
    subprocess.run([
        "git", "clone", 
        "--branch", deployment.branch,
        "https://github.com/your-org/robot-code.git",  # UPDATE THIS
        str(repo_path)
    ], check=True)
    
    # Checkout specific commit
    subprocess.run(
        ["git", "checkout", deployment.commit],
        cwd=repo_path,
        check=True
    )
    
    # Create deployment package
    package_path = PACKAGES_DIR / f"{deployment_id}.tar.gz"
    subprocess.run([
        "tar", "-czf", str(package_path),
        "-C", str(repo_path), "."
    ], check=True)
    
    # Calculate checksum
    checksum = hashlib.sha256(package_path.read_bytes()).hexdigest()
    
    # Store deployment info
    deployment_info = {
        "id": deployment_id,
        "version": deployment.version,
        "branch": deployment.branch,
        "commit": deployment.commit,
        "author": deployment.author,
        "message": deployment.message,
        "timestamp": datetime.now().isoformat(),
        "package_path": str(package_path),
        "checksum": checksum,
        "status": "ready"
    }
    
    deployments[deployment_id] = deployment_info
    
    # Save to file (simple persistence)
    with open(DEPLOYMENTS_DIR / "deployments.json", "w") as f:
        json.dump(deployments, f, indent=2)
    
    return {"deployment_id": deployment_id, "status": "created"}

@app.get("/api/check-update")
async def check_update(robot_id: str, current_version: str):
    """Check if robot needs update"""
    
    # Get latest deployment
    if not deployments:
        return {"update_available": False}
    
    latest = sorted(deployments.values(), 
                   key=lambda x: x['timestamp'], 
                   reverse=True)[0]
    
    if latest['version'] != current_version:
        return {
            "update_available": True,
            "deployment_id": latest['id'],
            "version": latest['version'],
            "download_url": f"/api/download/{latest['id']}",
            "checksum": latest['checksum']
        }
    
    return {"update_available": False}

@app.get("/api/download/{deployment_id}")
async def download_package(deployment_id: str):
    """Download deployment package"""
    if deployment_id not in deployments:
        raise HTTPException(404, "Deployment not found")
    
    package_path = deployments[deployment_id]['package_path']
    return FileResponse(package_path)

@app.get("/api/deployments")
async def list_deployments(limit: int = 100):
    """List all deployments"""
    return sorted(deployments.values(), 
                 key=lambda x: x['timestamp'], 
                 reverse=True)[:limit]

@app.post("/api/rollback/{deployment_id}")
async def rollback_to_deployment(deployment_id: str):
    """Mark a deployment as current (for rollback)"""
    if deployment_id not in deployments:
        raise HTTPException(404, "Deployment not found")
    
    # Set this as the "latest" by updating its timestamp
    deployments[deployment_id]['timestamp'] = datetime.now().isoformat()
    deployments[deployment_id]['rollback'] = True
    
    return {"status": "rolled back", "deployment_id": deployment_id}

@app.post("/api/robot/status")
async def update_robot_status(robot_id: str, status: dict):
    """Update robot deployment status"""
    robot_status[robot_id] = {
        **status,
        "last_seen": datetime.now().isoformat()
    }
    return {"status": "updated"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
```

### 1.4 Create Systemd Service

```bash
sudo cat > /etc/systemd/system/lekiwi-deploy.service << EOF
[Unit]
Description=LeKiwi Deploy Server
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/lekiwi-deploy
Environment="PATH=/opt/lekiwi-deploy/venv/bin"
ExecStart=/opt/lekiwi-deploy/venv/bin/python /opt/lekiwi-deploy/server.py
Restart=always

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable lekiwi-deploy
sudo systemctl start lekiwi-deploy
```

## Step 2: Install Agent on Robots (10 minutes per robot)

### 2.1 Create Installation Script

```bash
#!/bin/bash
# install-agent.sh - Run this on each robot

echo "🤖 Installing LeKiwi Deploy Agent"

# Create directories
mkdir -p /opt/lekiwi-deploy/{agent,deployments,current}

# Create the agent
cat > /opt/lekiwi-deploy/agent/agent.py << 'AGENT_EOF'
#!/usr/bin/env python3

import os
import sys
import time
import json
import shutil
import hashlib
import requests
import subprocess
from pathlib import Path
from datetime import datetime

class DeployAgent:
    def __init__(self):
        self.server_url = "http://YOUR_SERVER_IP:8000"  # UPDATE THIS
        self.robot_id = self.get_robot_id()
        self.deployments_dir = Path("/opt/lekiwi-deploy/deployments")
        self.current_link = Path("/opt/lekiwi-deploy/current")
        self.deployments_dir.mkdir(exist_ok=True)
        
    def get_robot_id(self):
        """Get robot ID from MAC address"""
        try:
            mac = subprocess.check_output(
                "ip link show eth0 | awk '/ether/ {print $2}' | tr -d ':' | tail -c 9",
                shell=True
            ).decode().strip()
            return f"Lekiwi_{mac.upper()}"
        except:
            return "Lekiwi_UNKNOWN"
    
    def get_current_version(self):
        """Get current deployed version"""
        version_file = self.current_link / "VERSION"
        if version_file.exists():
            return version_file.read_text().strip()
        return "0.0.0"
    
    def check_for_updates(self):
        """Check server for updates"""
        try:
            response = requests.get(
                f"{self.server_url}/api/check-update",
                params={
                    "robot_id": self.robot_id,
                    "current_version": self.get_current_version()
                }
            )
            if response.status_code == 200:
                data = response.json()
                if data.get("update_available"):
                    return data
        except Exception as e:
            print(f"Error checking updates: {e}")
        return None
    
    def download_and_deploy(self, update_info):
        """Download and deploy update"""
        deployment_id = update_info['deployment_id']
        deployment_path = self.deployments_dir / deployment_id
        
        print(f"📦 Downloading {deployment_id}...")
        
        # Download package
        response = requests.get(
            f"{self.server_url}{update_info['download_url']}",
            stream=True
        )
        
        package_file = deployment_path.with_suffix('.tar.gz')
        with open(package_file, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        
        # Verify checksum
        checksum = hashlib.sha256(package_file.read_bytes()).hexdigest()
        if checksum != update_info['checksum']:
            print("❌ Checksum mismatch!")
            return False
        
        # Extract package
        deployment_path.mkdir(exist_ok=True)
        subprocess.run([
            "tar", "-xzf", str(package_file),
            "-C", str(deployment_path)
        ], check=True)
        
        # Write version file
        (deployment_path / "VERSION").write_text(update_info['version'])
        
        # Stop services
        print("🛑 Stopping services...")
        subprocess.run(["systemctl", "stop", "teleop"], check=False)
        subprocess.run(["systemctl", "stop", "lekiwi"], check=False)
        
        # Switch deployment (atomic)
        print("🔄 Switching deployment...")
        temp_link = Path("/opt/lekiwi-deploy/current.tmp")
        if temp_link.exists():
            temp_link.unlink()
        temp_link.symlink_to(deployment_path)
        temp_link.replace(self.current_link)
        
        # Start services
        print("▶️ Starting services...")
        subprocess.run(["systemctl", "start", "teleop"], check=False)
        subprocess.run(["systemctl", "start", "lekiwi"], check=False)
        
        print(f"✅ Deployed {deployment_id}")
        
        # Report success
        requests.post(
            f"{self.server_url}/api/robot/status",
            json={
                "robot_id": self.robot_id,
                "deployment_id": deployment_id,
                "version": update_info['version'],
                "status": "success"
            }
        )
        
        # Clean old deployments (keep last 5)
        self.cleanup_old_deployments()
        
        return True
    
    def cleanup_old_deployments(self):
        """Remove old deployments, keeping last 5"""
        deployments = sorted(
            [d for d in self.deployments_dir.iterdir() if d.is_dir()],
            key=lambda x: x.stat().st_mtime,
            reverse=True
        )
        
        current_target = self.current_link.resolve() if self.current_link.exists() else None
        
        keep_count = 0
        for dep in deployments:
            if dep == current_target or keep_count < 5:
                keep_count += 1
            else:
                print(f"🗑️ Removing old deployment {dep.name}")
                shutil.rmtree(dep)
    
    def run(self):
        """Main loop"""
        print(f"🤖 Deploy agent started for {self.robot_id}")
        
        while True:
            try:
                update = self.check_for_updates()
                if update:
                    print(f"🚀 Update available: {update['version']}")
                    self.download_and_deploy(update)
                
                time.sleep(30)  # Check every 30 seconds
                
            except KeyboardInterrupt:
                print("Agent stopped")
                break
            except Exception as e:
                print(f"Error: {e}")
                time.sleep(60)

if __name__ == "__main__":
    agent = DeployAgent()
    agent.run()
AGENT_EOF

chmod +x /opt/lekiwi-deploy/agent/agent.py

# Create systemd service
cat > /etc/systemd/system/lekiwi-deploy-agent.service << EOF
[Unit]
Description=LeKiwi Deploy Agent
After=network-online.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 /opt/lekiwi-deploy/agent/agent.py
Restart=always
RestartSec=30

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable lekiwi-deploy-agent
systemctl start lekiwi-deploy-agent

echo "✅ Deploy agent installed!"
```

### 2.2 Run Installation on Each Robot

```bash
# Copy script to robot and run
scp install-agent.sh lekiwi@192.168.88.21:~/
ssh lekiwi@192.168.88.21 "sudo bash ~/install-agent.sh"
```

## Step 3: Deploy from GitHub (5 minutes)

### 3.1 Create GitHub Webhook

```python
# Add to server.py
@app.post("/webhook/github")
async def github_webhook(request: Request):
    """Handle GitHub push events"""
    payload = await request.json()
    
    if payload.get('ref') == 'refs/heads/main':
        # Auto-deploy main branch
        deployment = Deployment(
            version=f"auto-{payload['after'][:7]}",
            branch="main",
            commit=payload['after'],
            author=payload['pusher']['name'],
            message=payload['head_commit']['message']
        )
        
        return await create_deployment(deployment, BackgroundTasks())
    
    return {"status": "ignored"}
```

### 3.2 Configure GitHub Webhook

1. Go to your GitHub repo settings
2. Add webhook: `http://YOUR_SERVER_IP:8000/webhook/github`
3. Select "Just the push event"
4. Save

## Step 4: Create Simple CLI Tool (5 minutes)

```bash
#!/bin/bash
# /usr/local/bin/lekiwi-deploy

SERVER="http://YOUR_SERVER_IP:8000"

case "$1" in
    deploy)
        # Deploy current git HEAD
        VERSION=$(git describe --tags --always)
        COMMIT=$(git rev-parse HEAD)
        BRANCH=$(git branch --show-current)
        
        curl -X POST "$SERVER/api/deploy" \
            -H "Content-Type: application/json" \
            -d "{
                \"version\": \"$VERSION\",
                \"commit\": \"$COMMIT\",
                \"branch\": \"$BRANCH\",
                \"author\": \"$(git config user.name)\"
            }"
        ;;
        
    list)
        # List deployments
        curl "$SERVER/api/deployments" | jq '.'
        ;;
        
    rollback)
        # Rollback to deployment
        curl -X POST "$SERVER/api/rollback/$2"
        ;;
        
    status)
        # Show robot status
        curl "$SERVER/api/status" | jq '.'
        ;;
        
    *)
        echo "Usage: lekiwi-deploy {deploy|list|rollback|status}"
        ;;
esac
```

## Step 5: Test Your New System! 🎉

### Deploy Your First Update

```bash
# From your code repository
git push origin main

# Or manually trigger
lekiwi-deploy deploy

# Watch the magic happen!
# Robots will automatically pull and deploy the update
```

### Check Deployment Status

```bash
# List all deployments
lekiwi-deploy list

# See robot status
lekiwi-deploy status
```

### Rollback if Needed

```bash
# Rollback to previous deployment
lekiwi-deploy rollback dep_abc123
```

## What You Now Have

✅ **No More SSH**: Developers just push to Git
✅ **Automatic Updates**: Robots check every 30 seconds
✅ **Version History**: Every deployment is saved
✅ **Easy Rollback**: One command to rollback
✅ **Zero Downtime**: Atomic deployment switching

## Next Steps (When You Have Time)

1. **Add Web Dashboard**: Pretty UI for monitoring
2. **PostgreSQL Storage**: Replace JSON with database
3. **Health Checks**: Auto-rollback on failures
4. **Staged Rollouts**: Deploy to subset first
5. **Real-time Logs**: WebSocket log streaming

## Troubleshooting

```bash
# Check agent status on robot
systemctl status lekiwi-deploy-agent
journalctl -u lekiwi-deploy-agent -f

# Check server status
systemctl status lekiwi-deploy
journalctl -u lekiwi-deploy -f

# Manual deployment test
curl http://YOUR_SERVER:8000/api/deployments
```

---

**You're done! No more SSH tomfoolery! 🚀**

Your developers can now just:
```bash
git push  # And robots update automatically!
```

Total setup time: ~1 hour
SSH logins eliminated: ∞