#!/usr/bin/env python3
"""
LeKiwi Deploy Server - Vercel-style deployment system for robot fleets
Eliminates manual SSH deployments with Git-based automatic updates
"""

import os
import sys
import json
import uuid
import shutil
import hashlib
import asyncio
import subprocess
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, BackgroundTasks, Request, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import uvicorn

# Configuration
CONFIG = {
    "server_port": int(os.getenv("DEPLOY_PORT", "8000")),
    "deployments_dir": Path(os.getenv("DEPLOYMENTS_DIR", "/opt/lekiwi-deploy/deployments")),
    "packages_dir": Path(os.getenv("PACKAGES_DIR", "/opt/lekiwi-deploy/packages")),
    "repos_dir": Path(os.getenv("REPOS_DIR", "/opt/lekiwi-deploy/repos")),
    "max_deployments": int(os.getenv("MAX_DEPLOYMENTS", "100")),
    "github_repo": os.getenv("GITHUB_REPO", "https://github.com/your-org/robot-code.git"),
    "github_token": os.getenv("GITHUB_TOKEN", ""),  # Optional, for private repos
}

# Create directories
for dir_path in [CONFIG["deployments_dir"], CONFIG["packages_dir"], CONFIG["repos_dir"]]:
    dir_path.mkdir(parents=True, exist_ok=True)

# In-memory storage (will be replaced with PostgreSQL)
deployments_db: Dict[str, Dict] = {}
robot_status_db: Dict[str, Dict] = {}
deployment_history: List[Dict] = []

# Load existing deployments on startup
DEPLOYMENTS_FILE = CONFIG["deployments_dir"] / "deployments.json"
if DEPLOYMENTS_FILE.exists():
    with open(DEPLOYMENTS_FILE, "r") as f:
        deployments_db = json.load(f)

# Pydantic models
class Deployment(BaseModel):
    version: str = Field(..., description="Deployment version (e.g., v2.1.0)")
    branch: str = Field(default="main", description="Git branch to deploy")
    commit: Optional[str] = Field(None, description="Specific commit SHA")
    author: str = Field(default="unknown", description="Deployment author")
    message: str = Field(default="", description="Deployment message")
    target_group: str = Field(default="all", description="Target robot group")
    auto_rollback: bool = Field(default=True, description="Auto-rollback on failure")

class RobotStatus(BaseModel):
    robot_id: str
    deployment_id: Optional[str] = None
    version: Optional[str] = None
    status: str  # "idle", "downloading", "deploying", "success", "failed"
    message: Optional[str] = None
    health: Optional[Dict[str, Any]] = None

class RollbackRequest(BaseModel):
    deployment_id: Optional[str] = None
    version: Optional[str] = None
    time_ago: Optional[str] = None  # e.g., "2-hours-ago"
    target_group: str = Field(default="all")

# Lifespan context manager for startup/shutdown
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    print(f"🚀 LeKiwi Deploy Server starting on port {CONFIG['server_port']}")
    print(f"📁 Deployments directory: {CONFIG['deployments_dir']}")
    print(f"📦 Packages directory: {CONFIG['packages_dir']}")
    
    # Start background tasks
    asyncio.create_task(cleanup_old_deployments())
    asyncio.create_task(monitor_robot_health())
    
    yield
    
    # Shutdown
    print("👋 LeKiwi Deploy Server shutting down")
    save_deployments()

# Create FastAPI app
app = FastAPI(
    title="LeKiwi Deploy Server",
    description="Vercel-style deployment system for robot fleets",
    version="1.0.0",
    lifespan=lifespan
)

# Add CORS middleware for web dashboard
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure this properly in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Helper functions
def generate_deployment_id() -> str:
    """Generate unique deployment ID"""
    return f"dep_{uuid.uuid4().hex[:12]}"

def calculate_checksum(file_path: Path) -> str:
    """Calculate SHA256 checksum of file"""
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()

def save_deployments():
    """Persist deployments to disk"""
    with open(DEPLOYMENTS_FILE, "w") as f:
        json.dump(deployments_db, f, indent=2, default=str)

async def cleanup_old_deployments():
    """Background task to clean up old deployments"""
    while True:
        try:
            await asyncio.sleep(3600)  # Run every hour
            
            # Sort deployments by timestamp
            sorted_deps = sorted(
                deployments_db.values(),
                key=lambda x: x.get("timestamp", ""),
                reverse=True
            )
            
            # Keep only the latest MAX_DEPLOYMENTS
            if len(sorted_deps) > CONFIG["max_deployments"]:
                to_remove = sorted_deps[CONFIG["max_deployments"]:]
                for dep in to_remove:
                    dep_id = dep["id"]
                    # Remove package file
                    package_path = Path(dep.get("package_path", ""))
                    if package_path.exists():
                        package_path.unlink()
                    # Remove from database
                    deployments_db.pop(dep_id, None)
                
                save_deployments()
                print(f"🧹 Cleaned up {len(to_remove)} old deployments")
                
        except Exception as e:
            print(f"Error in cleanup task: {e}")

async def monitor_robot_health():
    """Background task to monitor robot health"""
    while True:
        try:
            await asyncio.sleep(30)  # Check every 30 seconds
            
            now = datetime.now()
            for robot_id, status in robot_status_db.items():
                last_seen = datetime.fromisoformat(status.get("last_seen", now.isoformat()))
                if (now - last_seen) > timedelta(minutes=5):
                    status["health"] = "offline"
                    print(f"⚠️ Robot {robot_id} appears to be offline")
                    
        except Exception as e:
            print(f"Error in health monitor: {e}")

async def build_deployment_package(deployment: Deployment) -> Dict:
    """Build deployment package from Git repository"""
    deployment_id = generate_deployment_id()
    repo_path = CONFIG["repos_dir"] / deployment_id
    package_path = CONFIG["packages_dir"] / f"{deployment_id}.tar.gz"
    
    try:
        # Clone repository
        print(f"📥 Cloning repository for {deployment_id}")
        
        clone_cmd = ["git", "clone", "--depth", "1"]
        if deployment.branch:
            clone_cmd.extend(["--branch", deployment.branch])
        
        # Add auth token if available (for private repos)
        repo_url = CONFIG["github_repo"]
        if CONFIG["github_token"]:
            repo_url = repo_url.replace("https://", f"https://{CONFIG['github_token']}@")
        
        clone_cmd.extend([repo_url, str(repo_path)])
        
        result = subprocess.run(clone_cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise Exception(f"Git clone failed: {result.stderr}")
        
        # Checkout specific commit if provided
        if deployment.commit:
            subprocess.run(
                ["git", "checkout", deployment.commit],
                cwd=repo_path,
                check=True
            )
        
        # Get actual commit SHA
        commit_sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_path,
            text=True
        ).strip()
        
        # Create VERSION file
        version_file = repo_path / "VERSION"
        version_file.write_text(deployment.version)
        
        # Create deployment metadata
        metadata = {
            "id": deployment_id,
            "version": deployment.version,
            "branch": deployment.branch,
            "commit": commit_sha,
            "author": deployment.author,
            "message": deployment.message,
            "timestamp": datetime.now().isoformat(),
            "target_group": deployment.target_group,
            "auto_rollback": deployment.auto_rollback
        }
        
        metadata_file = repo_path / "DEPLOYMENT.json"
        with open(metadata_file, "w") as f:
            json.dump(metadata, f, indent=2)
        
        # Create tarball package
        print(f"📦 Creating deployment package for {deployment_id}")
        subprocess.run(
            ["tar", "-czf", str(package_path), "-C", str(repo_path), "."],
            check=True
        )
        
        # Calculate checksum
        checksum = calculate_checksum(package_path)
        
        # Clean up repo directory
        shutil.rmtree(repo_path)
        
        # Store deployment info
        deployment_info = {
            **metadata,
            "package_path": str(package_path),
            "checksum": checksum,
            "package_size": package_path.stat().st_size,
            "status": "ready"
        }
        
        deployments_db[deployment_id] = deployment_info
        deployment_history.append(deployment_info)
        save_deployments()
        
        print(f"✅ Deployment {deployment_id} ready (version: {deployment.version})")
        return deployment_info
        
    except Exception as e:
        # Clean up on failure
        if repo_path.exists():
            shutil.rmtree(repo_path)
        if package_path.exists():
            package_path.unlink()
        
        raise HTTPException(status_code=500, detail=f"Failed to build deployment: {str(e)}")

# API Endpoints

@app.get("/")
async def root():
    """Root endpoint with server info"""
    return {
        "name": "LeKiwi Deploy Server",
        "version": "1.0.0",
        "status": "operational",
        "deployments": len(deployments_db),
        "robots": len(robot_status_db),
        "latest_deployment": max(deployments_db.values(), key=lambda x: x["timestamp"])["id"] if deployments_db else None
    }

@app.post("/api/deploy")
async def create_deployment(deployment: Deployment, background_tasks: BackgroundTasks):
    """Create a new deployment"""
    try:
        # Build deployment package in background
        deployment_info = await build_deployment_package(deployment)
        
        # Notify robots in background
        background_tasks.add_task(notify_robots, deployment_info)
        
        return {
            "status": "success",
            "deployment_id": deployment_info["id"],
            "version": deployment_info["version"],
            "message": f"Deployment {deployment_info['id']} created successfully"
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/check-update")
async def check_for_update(
    robot_id: str = Query(..., description="Robot ID"),
    current_version: str = Query(..., description="Current robot version"),
    group: str = Query(default="all", description="Robot group")
):
    """Check if robot needs an update"""
    
    # Update robot last seen
    if robot_id not in robot_status_db:
        robot_status_db[robot_id] = {}
    robot_status_db[robot_id]["last_seen"] = datetime.now().isoformat()
    robot_status_db[robot_id]["current_version"] = current_version
    robot_status_db[robot_id]["group"] = group
    
    # Find latest deployment for this group
    applicable_deployments = [
        d for d in deployments_db.values()
        if d["status"] == "ready" and (d["target_group"] == "all" or d["target_group"] == group)
    ]
    
    if not applicable_deployments:
        return {"update_available": False}
    
    latest = max(applicable_deployments, key=lambda x: x["timestamp"])
    
    if latest["version"] != current_version:
        return {
            "update_available": True,
            "deployment_id": latest["id"],
            "version": latest["version"],
            "download_url": f"/api/download/{latest['id']}",
            "checksum": latest["checksum"],
            "package_size": latest.get("package_size", 0),
            "auto_rollback": latest.get("auto_rollback", True)
        }
    
    return {"update_available": False}

@app.get("/api/download/{deployment_id}")
async def download_package(deployment_id: str):
    """Download deployment package"""
    if deployment_id not in deployments_db:
        raise HTTPException(status_code=404, detail="Deployment not found")
    
    package_path = Path(deployments_db[deployment_id]["package_path"])
    if not package_path.exists():
        raise HTTPException(status_code=404, detail="Package file not found")
    
    return FileResponse(
        path=package_path,
        filename=f"{deployment_id}.tar.gz",
        media_type="application/gzip"
    )

@app.get("/api/deployments")
async def list_deployments(
    limit: int = Query(default=100, description="Maximum number of deployments to return"),
    group: Optional[str] = Query(default=None, description="Filter by target group")
):
    """List all deployments"""
    deployments = list(deployments_db.values())
    
    # Filter by group if specified
    if group:
        deployments = [d for d in deployments if d.get("target_group") == group]
    
    # Sort by timestamp (newest first)
    deployments.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
    
    return deployments[:limit]

@app.post("/api/rollback")
async def rollback_deployment(request: RollbackRequest):
    """Rollback to a previous deployment"""
    
    target_deployment = None
    
    # Find target deployment based on request
    if request.deployment_id:
        target_deployment = deployments_db.get(request.deployment_id)
    
    elif request.version:
        # Find by version
        for dep in deployments_db.values():
            if dep["version"] == request.version:
                target_deployment = dep
                break
    
    elif request.time_ago:
        # Parse time ago (e.g., "2-hours-ago")
        try:
            parts = request.time_ago.replace("-ago", "").split("-")
            amount = int(parts[0])
            unit = parts[1]
            
            delta = timedelta()
            if "hour" in unit:
                delta = timedelta(hours=amount)
            elif "day" in unit:
                delta = timedelta(days=amount)
            elif "minute" in unit:
                delta = timedelta(minutes=amount)
            
            target_time = datetime.now() - delta
            
            # Find deployment closest to target time
            for dep in sorted(deployments_db.values(), key=lambda x: x["timestamp"], reverse=True):
                dep_time = datetime.fromisoformat(dep["timestamp"])
                if dep_time <= target_time:
                    target_deployment = dep
                    break
                    
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid time format: {request.time_ago}")
    
    if not target_deployment:
        raise HTTPException(status_code=404, detail="Target deployment not found")
    
    # Create a new deployment entry for the rollback
    rollback_id = generate_deployment_id()
    rollback_deployment = {
        **target_deployment,
        "id": rollback_id,
        "timestamp": datetime.now().isoformat(),
        "is_rollback": True,
        "rollback_from": deployments_db[max(deployments_db.keys(), key=lambda k: deployments_db[k]["timestamp"])]["id"],
        "message": f"Rollback to {target_deployment['version']} ({target_deployment['id']})"
    }
    
    deployments_db[rollback_id] = rollback_deployment
    save_deployments()
    
    return {
        "status": "success",
        "deployment_id": rollback_id,
        "rolled_back_to": target_deployment["id"],
        "version": target_deployment["version"],
        "message": f"Rolled back to deployment {target_deployment['id']}"
    }

@app.post("/api/robot/status")
async def update_robot_status(status: RobotStatus):
    """Update robot deployment status"""
    robot_status_db[status.robot_id] = {
        "robot_id": status.robot_id,
        "deployment_id": status.deployment_id,
        "version": status.version,
        "status": status.status,
        "message": status.message,
        "health": status.health,
        "last_seen": datetime.now().isoformat()
    }
    
    # Log important status changes
    if status.status in ["failed", "success"]:
        print(f"🤖 Robot {status.robot_id}: {status.status} - {status.message or 'No message'}")
    
    return {"status": "updated"}

@app.get("/api/robots")
async def list_robots():
    """List all robots and their status"""
    return list(robot_status_db.values())

@app.get("/api/robots/{robot_id}")
async def get_robot_status(robot_id: str):
    """Get specific robot status"""
    if robot_id not in robot_status_db:
        raise HTTPException(status_code=404, detail="Robot not found")
    
    return robot_status_db[robot_id]

@app.post("/webhook/github")
async def github_webhook(request: Request, background_tasks: BackgroundTasks):
    """Handle GitHub webhook events"""
    try:
        payload = await request.json()
        
        # Check if it's a push event
        if request.headers.get("X-GitHub-Event") != "push":
            return {"status": "ignored", "reason": "Not a push event"}
        
        # Extract information from payload
        ref = payload.get("ref", "")
        branch = ref.replace("refs/heads/", "") if ref.startswith("refs/heads/") else None
        
        if not branch:
            return {"status": "ignored", "reason": "No branch information"}
        
        # Auto-deploy based on branch
        target_group = "all"
        if branch == "main" or branch == "master":
            target_group = "production"
        elif branch == "staging":
            target_group = "staging"
        elif branch == "development":
            target_group = "development"
        else:
            return {"status": "ignored", "reason": f"Branch {branch} not configured for auto-deploy"}
        
        # Create deployment
        deployment = Deployment(
            version=f"auto-{payload['after'][:8]}",
            branch=branch,
            commit=payload["after"],
            author=payload.get("pusher", {}).get("name", "GitHub"),
            message=payload.get("head_commit", {}).get("message", "Auto-deployment from GitHub"),
            target_group=target_group
        )
        
        deployment_info = await build_deployment_package(deployment)
        background_tasks.add_task(notify_robots, deployment_info)
        
        return {
            "status": "success",
            "deployment_id": deployment_info["id"],
            "message": f"Auto-deployment triggered for branch {branch}"
        }
        
    except Exception as e:
        print(f"Error processing GitHub webhook: {e}")
        return {"status": "error", "message": str(e)}

async def notify_robots(deployment_info: Dict):
    """Notify robots about new deployment (placeholder for push notifications)"""
    print(f"📢 Notifying robots about deployment {deployment_info['id']}")
    # In a real implementation, this would send push notifications to robots
    # For now, robots poll for updates

# Health check endpoint
@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "deployments": len(deployments_db),
        "robots": len(robot_status_db)
    }

# Main entry point
if __name__ == "__main__":
    uvicorn.run(
        "server:app",
        host="0.0.0.0",
        port=CONFIG["server_port"],
        reload=True,
        log_level="info"
    )