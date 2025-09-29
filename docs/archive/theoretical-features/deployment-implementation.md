# LeKiwi Deployment System - Implementation Guide
## From SSH Chaos to Automated Bliss 🚀

### Quick Win Implementation (Get This Running TODAY!)

## Step 1: Simple Deployment Agent for Robots

This lightweight Python agent runs on each robot and automatically pulls code updates from a Git repository.

### File Structure
```
/opt/lekiwi/
├── deployment/
│   ├── agent.py           # Main deployment agent
│   ├── config.yaml         # Agent configuration
│   ├── current/           # Current running code
│   ├── staging/           # Staging area for new code
│   ├── backup/            # Previous version backup
│   └── logs/              # Deployment logs
```

### Core Deployment Agent Code

```python
#!/usr/bin/env python3
# /opt/lekiwi/deployment/agent.py

import os
import sys
import yaml
import time
import shutil
import hashlib
import logging
import subprocess
from datetime import datetime
from pathlib import Path
import requests
import json

class LeKiwiDeploymentAgent:
    """
    Automated deployment agent - No more manual SSH updates!
    Polls for updates, validates, deploys, and can rollback.
    """
    
    def __init__(self, config_path="/opt/lekiwi/deployment/config.yaml"):
        self.config = self.load_config(config_path)
        self.setup_logging()
        self.robot_id = self.get_robot_id()
        self.current_version = self.get_current_version()
        
    def load_config(self, path):
        """Load agent configuration"""
        with open(path, 'r') as f:
            return yaml.safe_load(f)
    
    def setup_logging(self):
        """Configure logging"""
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler('/opt/lekiwi/deployment/logs/agent.log'),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger('DeploymentAgent')
    
    def get_robot_id(self):
        """Get unique robot identifier"""
        # Use MAC address-based ID (same as existing system)
        try:
            mac = subprocess.check_output(
                "ip link show eth0 | awk '/ether/ {print $2}' | tr -d ':' | tail -c 9",
                shell=True
            ).decode().strip()
            return f"Lekiwi_{mac.upper()}"
        except:
            return os.environ.get('ROBOT_ID', 'unknown')
    
    def check_for_updates(self):
        """Check deployment server for new versions"""
        try:
            response = requests.get(
                f"{self.config['server']['url']}/api/check-update",
                params={
                    'robot_id': self.robot_id,
                    'current_version': self.current_version,
                    'group': self.config.get('group', 'default')
                },
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                if data.get('update_available'):
                    return data
            return None
            
        except Exception as e:
            self.logger.error(f"Failed to check for updates: {e}")
            return None
    
    def download_update(self, update_info):
        """Download deployment package"""
        try:
            self.logger.info(f"Downloading version {update_info['version']}")
            
            # Download to staging area
            staging_path = Path('/opt/lekiwi/deployment/staging')
            staging_path.mkdir(exist_ok=True)
            
            # Download package
            response = requests.get(
                update_info['download_url'],
                stream=True,
                timeout=60
            )
            
            package_path = staging_path / f"package-{update_info['version']}.tar.gz"
            
            with open(package_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            
            # Verify checksum
            if self.verify_checksum(package_path, update_info['checksum']):
                return package_path
            else:
                self.logger.error("Checksum verification failed!")
                return None
                
        except Exception as e:
            self.logger.error(f"Download failed: {e}")
            return None
    
    def verify_checksum(self, file_path, expected_checksum):
        """Verify file integrity"""
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        
        actual = sha256_hash.hexdigest()
        return actual == expected_checksum
    
    def backup_current(self):
        """Backup current deployment"""
        try:
            current = Path('/opt/lekiwi/deployment/current')
            backup = Path('/opt/lekiwi/deployment/backup')
            
            # Remove old backup
            if backup.exists():
                shutil.rmtree(backup)
            
            # Copy current to backup
            if current.exists():
                shutil.copytree(current, backup)
                self.logger.info("Current deployment backed up")
                return True
                
        except Exception as e:
            self.logger.error(f"Backup failed: {e}")
            return False
    
    def apply_update(self, package_path, update_info):
        """Apply the update"""
        try:
            self.logger.info(f"Applying update {update_info['version']}")
            
            # Extract package to staging
            staging = Path('/opt/lekiwi/deployment/staging/extracted')
            staging.mkdir(exist_ok=True)
            
            subprocess.run(
                f"tar -xzf {package_path} -C {staging}",
                shell=True,
                check=True
            )
            
            # Stop services
            self.stop_services(update_info.get('services_to_restart', []))
            
            # Move staging to current
            current = Path('/opt/lekiwi/deployment/current')
            if current.exists():
                shutil.rmtree(current)
            shutil.move(staging, current)
            
            # Update version file
            with open(current / 'VERSION', 'w') as f:
                f.write(update_info['version'])
            
            # Apply any configuration changes
            self.apply_config_changes(update_info.get('config_changes', {}))
            
            # Start services
            self.start_services(update_info.get('services_to_restart', []))
            
            # Run health checks
            if self.run_health_checks(update_info.get('health_checks', [])):
                self.logger.info("Update applied successfully!")
                return True
            else:
                self.logger.error("Health checks failed, rolling back...")
                self.rollback()
                return False
                
        except Exception as e:
            self.logger.error(f"Update failed: {e}")
            self.rollback()
            return False
    
    def rollback(self):
        """Rollback to previous version"""
        try:
            self.logger.warning("Initiating rollback...")
            
            backup = Path('/opt/lekiwi/deployment/backup')
            current = Path('/opt/lekiwi/deployment/current')
            
            if not backup.exists():
                self.logger.error("No backup available for rollback!")
                return False
            
            # Stop services
            self.stop_all_services()
            
            # Restore backup
            if current.exists():
                shutil.rmtree(current)
            shutil.copytree(backup, current)
            
            # Start services
            self.start_all_services()
            
            self.logger.info("Rollback completed")
            return True
            
        except Exception as e:
            self.logger.error(f"Rollback failed: {e}")
            return False
    
    def stop_services(self, services):
        """Stop specified services"""
        for service in services:
            try:
                subprocess.run(
                    f"systemctl stop {service}",
                    shell=True,
                    check=True
                )
                self.logger.info(f"Stopped {service}")
            except:
                self.logger.warning(f"Failed to stop {service}")
    
    def start_services(self, services):
        """Start specified services"""
        for service in services:
            try:
                subprocess.run(
                    f"systemctl start {service}",
                    shell=True,
                    check=True
                )
                self.logger.info(f"Started {service}")
            except:
                self.logger.warning(f"Failed to start {service}")
    
    def run_health_checks(self, checks):
        """Run post-deployment health checks"""
        if not checks:
            return True
        
        time.sleep(5)  # Give services time to start
        
        for check in checks:
            try:
                if check['type'] == 'http':
                    response = requests.get(
                        f"http://localhost:{check['port']}{check['endpoint']}",
                        timeout=5
                    )
                    if response.status_code != check['expected_status']:
                        return False
                        
                elif check['type'] == 'service':
                    result = subprocess.run(
                        f"systemctl is-active {check['name']}",
                        shell=True,
                        capture_output=True
                    )
                    if result.returncode != 0:
                        return False
                        
            except Exception as e:
                self.logger.error(f"Health check failed: {e}")
                return False
        
        return True
    
    def report_status(self, status, version=None, message=None):
        """Report deployment status to server"""
        try:
            data = {
                'robot_id': self.robot_id,
                'status': status,
                'version': version or self.current_version,
                'timestamp': datetime.now().isoformat(),
                'message': message
            }
            
            requests.post(
                f"{self.config['server']['url']}/api/report-status",
                json=data,
                timeout=10
            )
        except:
            pass  # Don't fail deployment if reporting fails
    
    def run(self):
        """Main agent loop"""
        self.logger.info(f"Deployment agent started for {self.robot_id}")
        
        while True:
            try:
                # Check for updates
                update = self.check_for_updates()
                
                if update:
                    self.logger.info(f"Update available: {update['version']}")
                    
                    # Report deployment starting
                    self.report_status('deploying', update['version'])
                    
                    # Backup current
                    if not self.backup_current():
                        self.report_status('failed', message='Backup failed')
                        continue
                    
                    # Download update
                    package = self.download_update(update)
                    if not package:
                        self.report_status('failed', message='Download failed')
                        continue
                    
                    # Apply update
                    if self.apply_update(package, update):
                        self.current_version = update['version']
                        self.report_status('success', update['version'])
                    else:
                        self.report_status('failed', message='Deployment failed')
                
                # Wait before next check
                time.sleep(self.config.get('check_interval', 60))
                
            except KeyboardInterrupt:
                self.logger.info("Agent stopped by user")
                break
            except Exception as e:
                self.logger.error(f"Agent error: {e}")
                time.sleep(60)

if __name__ == "__main__":
    agent = LeKiwiDeploymentAgent()
    agent.run()
```

### Configuration File
```yaml
# /opt/lekiwi/deployment/config.yaml

# Deployment server configuration
server:
  url: "https://fleet.lekiwi.io"  # Or your deployment server
  
# Robot configuration  
robot:
  group: "warehouse"  # Robot group for staged deployments
  environment: "production"  # production, staging, development
  
# Update settings
check_interval: 60  # Check for updates every 60 seconds
auto_deploy: true  # Automatically deploy updates
deployment_window:  # Optional deployment window
  start: "02:00"
  end: "04:00"
  
# Services to manage
services:
  - teleop
  - lekiwi
  - lekiwi-navigation
  
# Health checks after deployment
health_checks:
  - type: http
    port: 8080
    endpoint: /health
    expected_status: 200
  - type: service
    name: teleop
  - type: service
    name: lekiwi
```

### Systemd Service
```ini
# /etc/systemd/system/lekiwi-deployment.service

[Unit]
Description=LeKiwi Deployment Agent
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/lekiwi/deployment
ExecStart=/usr/bin/python3 /opt/lekiwi/deployment/agent.py
Restart=always
RestartSec=30
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

## Step 2: Simple Deployment Server

A lightweight FastAPI server that manages deployments.

```python
# deployment-server.py
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import yaml
import hashlib
from pathlib import Path
from typing import Dict, List, Optional
import subprocess

app = FastAPI(title="LeKiwi Deployment Server")

# In-memory storage (use database in production)
deployments = {}
robot_status = {}

class UpdateCheck(BaseModel):
    robot_id: str
    current_version: str
    group: str = "default"

@app.get("/api/check-update")
async def check_update(robot_id: str, current_version: str, group: str = "default"):
    """Check if robot needs an update"""
    
    # Get latest version for this group
    latest = get_latest_version(group)
    
    if latest and latest['version'] != current_version:
        return {
            "update_available": True,
            "version": latest['version'],
            "download_url": f"/api/download/{latest['version']}",
            "checksum": latest['checksum'],
            "services_to_restart": latest.get('services', []),
            "health_checks": latest.get('health_checks', [])
        }
    
    return {"update_available": False}

@app.post("/api/deploy")
async def create_deployment(version: str, groups: List[str] = ["default"]):
    """Create a new deployment"""
    
    # Build deployment package
    package_path = build_deployment_package(version)
    
    # Calculate checksum
    checksum = calculate_checksum(package_path)
    
    # Register deployment
    deployment = {
        "version": version,
        "groups": groups,
        "checksum": checksum,
        "package_path": str(package_path),
        "timestamp": datetime.now().isoformat(),
        "status": "active"
    }
    
    deployments[version] = deployment
    
    return {"status": "success", "deployment": deployment}

@app.get("/api/status")
async def get_fleet_status():
    """Get status of all robots"""
    return {
        "robots": robot_status,
        "deployments": deployments
    }
```

## Step 3: GitHub Webhook Integration

```python
# webhook_handler.py
@app.post("/webhook/github")
async def github_webhook(request: Request):
    """Handle GitHub push events"""
    
    payload = await request.json()
    
    # Check if it's a push to main branch
    if payload.get('ref') == 'refs/heads/main':
        # Trigger deployment build
        commit = payload['after']
        
        # Build and deploy
        version = f"auto-{commit[:7]}"
        await create_deployment(version, ["staging"])
        
        return {"status": "deployment triggered"}
    
    return {"status": "ignored"}
```

## Installation Script

```bash
#!/bin/bash
# install-deployment-agent.sh

echo "🚀 Installing LeKiwi Deployment Agent"

# Create directories
mkdir -p /opt/lekiwi/deployment/{current,staging,backup,logs}

# Download agent
curl -o /opt/lekiwi/deployment/agent.py \
  https://raw.githubusercontent.com/your-org/lekiwi-fleet/main/deployment/agent.py

# Create config
cat > /opt/lekiwi/deployment/config.yaml << EOF
server:
  url: "https://fleet.lekiwi.io"
robot:
  group: "production"
check_interval: 60
auto_deploy: true
EOF

# Install systemd service
cat > /etc/systemd/system/lekiwi-deployment.service << EOF
[Unit]
Description=LeKiwi Deployment Agent
After=network-online.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 /opt/lekiwi/deployment/agent.py
Restart=always

[Install]
WantedBy=multi-user.target
EOF

# Start service
systemctl daemon-reload
systemctl enable lekiwi-deployment
systemctl start lekiwi-deployment

echo "✅ Deployment agent installed and running!"
echo "No more manual SSH updates needed!"
```

## Immediate Benefits

1. **Push to Deploy**: Developers push to Git, robots auto-update
2. **Consistent Updates**: All robots get the same code
3. **Rollback Safety**: Automatic rollback on failures
4. **Audit Trail**: Complete log of all deployments
5. **No SSH Required**: Developers don't need robot access

## Next Steps

1. Install agent on one test robot
2. Set up simple deployment server
3. Test with a small code change
4. Roll out to entire fleet
5. Add dashboard for visibility

---

**Your SSH nightmare is over! 🎉**