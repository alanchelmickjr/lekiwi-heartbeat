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
import base64
import io
import time
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, BackgroundTasks, Request, Query
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import uvicorn

# For camera streaming - optional imports
try:
    import zmq
    ZMQ_AVAILABLE = True
except ImportError:
    ZMQ_AVAILABLE = False
    print("⚠️ ZMQ not available - camera streaming will use SSH fallback")

# Import comparison engine
from comparison_engine import (
    RobotFileComparison,
    create_baseline_deployment,
    compare_robot_deployments,
    compare_robot_to_baseline
)

# Import the new versioning system
try:
    from robot_versioning import RobotVersioning
    versioning = RobotVersioning()
    print("✅ Robot versioning system loaded")
except ImportError as e:
    print(f"⚠️ Robot versioning module not available: {e}")
    versioning = None

# Configuration
CONFIG = {
    "server_port": int(os.getenv("DEPLOY_PORT", "8000")),
    "deployments_dir": Path(os.getenv("DEPLOYMENTS_DIR", Path.home() / ".lekiwi-deploy/deployments")),
    "packages_dir": Path(os.getenv("PACKAGES_DIR", Path.home() / ".lekiwi-deploy/packages")),
    "repos_dir": Path(os.getenv("REPOS_DIR", Path.home() / ".lekiwi-deploy/repos")),
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

# Mount static files
static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

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

@app.get("/", response_class=HTMLResponse)
async def root():
    """Serve the web dashboard"""
    index_file = Path(__file__).parent / "static" / "index.html"
    if index_file.exists():
        return index_file.read_text()
    else:
        # Fallback to API info if no HTML file
        return JSONResponse({
            "name": "LeKiwi Deploy Server",
            "version": "1.0.0",
            "status": "operational",
            "deployments": len(deployments_db),
            "robots": len(robot_status_db),
            "latest_deployment": max(deployments_db.values(), key=lambda x: x["timestamp"])["id"] if deployments_db else None
        })

@app.get("/api/fleet")
async def get_fleet():
    """Get the discovered fleet configuration"""
    fleet_file = Path("/tmp/lekiwi_fleet.json")
    if fleet_file.exists():
        with open(fleet_file, 'r') as f:
            return json.load(f)
    else:
        # Trigger discovery if fleet file doesn't exist
        print("🔍 Fleet configuration not found. Running robot discovery...")
        
        try:
            # Run smart discovery to find all robots
            # Increased timeout to allow for proper Raspberry Pi scanning
            discovery_result = subprocess.run(
                ["python3", "smart_discover.py"],
                capture_output=True,
                text=True,
                timeout=120,  # Increased from 60 to 120 seconds for thorough discovery
                cwd=Path(__file__).parent  # Run in deployment-server directory
            )
            
            if discovery_result.returncode != 0:
                print(f"⚠️ Discovery failed: {discovery_result.stderr}")
            
            # Check if discovery results exist
            discovered_file = Path("/tmp/smart_discovered.txt")
            if discovered_file.exists():
                # Convert discovery results to fleet configuration
                conversion_result = subprocess.run(
                    ["python3", "add_discovered_robots.py"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    cwd=Path(__file__).parent
                )
                
                if conversion_result.returncode != 0:
                    print(f"⚠️ Fleet conversion failed: {conversion_result.stderr}")
                
                # Try to read the fleet file again
                if fleet_file.exists():
                    with open(fleet_file, 'r') as f:
                        fleet_data = json.load(f)
                        print(f"✅ Discovered {fleet_data.get('total', 0)} robots")
                        return fleet_data
            
            # If discovery failed or no robots found, return empty fleet
            print("⚠️ No robots discovered")
            return {
                "robots": [],
                "total": 0,
                "discovered_at": datetime.now().timestamp(),
                "error": "Discovery failed or no robots found"
            }
            
        except subprocess.TimeoutExpired:
            print("⚠️ Discovery timed out")
            return {
                "robots": [],
                "total": 0,
                "discovered_at": datetime.now().timestamp(),
                "error": "Discovery timed out"
            }
        except Exception as e:
            print(f"❌ Discovery error: {e}")
            return {
                "robots": [],
                "total": 0,
                "discovered_at": datetime.now().timestamp(),
                "error": str(e)
            }

@app.get("/api/info")
async def api_info():
    """API info endpoint"""
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

# Execute command endpoint for robot management
@app.post("/api/execute")
async def execute_command(request: Request):
    """Execute deployment commands for robot management"""
    try:
        data = await request.json()
        command = data.get("command")
        args = data.get("args", [])
        
        # Security check - only allow specific commands
        allowed_commands = ["python3", "python", "bash", "ssh-keygen", "sshpass"]
        if command not in allowed_commands and not command.endswith('.py'):
            raise HTTPException(status_code=403, detail=f"Command not allowed: {command}")
        
        # Fix paths for deployment scripts
        if command in ["python3", "python"] and args and "deployment-master" in args[0]:
            # Adjust path to be relative to current working directory
            script_path = args[0]
            if not os.path.isabs(script_path):
                # Go up one directory from deployment-server to find deployment-master
                args[0] = os.path.join(os.path.dirname(os.path.dirname(__file__)), script_path)
        
        # Determine appropriate timeout based on the action
        timeout = 5  # Default timeout for simple commands
        use_streaming = False  # Flag to determine if we should stream output
        
        # Check if this is a Miniconda installation or other long-running operation
        if args and len(args) > 2:
            if '--action' in args and 'install-conda' in args:
                timeout = 300  # 5 minutes for Miniconda installation (increased for safety)
                use_streaming = True
                print(f"🐍 Miniconda installation detected, using {timeout}s timeout with output streaming")
            elif '--action' in args and 'setup-env' in args:
                timeout = 300  # 5 minutes for full environment setup
                use_streaming = True
                print(f"🔧 Environment setup detected, using {timeout}s timeout")
            elif '--action' in args and 'full' in args:
                timeout = 240  # 4 minutes for full deployment
                print(f"🚀 Full deployment detected, using {timeout}s timeout")
        
        # Execute command
        full_command = [command] + args
        print(f"📦 Executing: {' '.join(full_command)} (timeout: {timeout}s)")  # Debug logging
        
        # For long-running commands with streaming, use Popen to capture output progressively
        if use_streaming:
            print(f"🔄 Using streaming output for command...")
            
            # Use Popen for better control over the process
            process = subprocess.Popen(
                full_command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=os.path.dirname(os.path.dirname(__file__))
            )
            
            # Collect output with timeout
            try:
                stdout, stderr = process.communicate(timeout=timeout)
                return_code = process.returncode
                
                # Log important parts of the output for debugging
                if "Installing Miniconda" in stdout:
                    print("✅ Miniconda installation output detected")
                    # Extract and log key installation steps
                    for line in stdout.split('\n'):
                        if any(keyword in line for keyword in ['PREFIX', 'extracting', 'installing',
                                                                'unpacking', 'Preparing', 'Extracting',
                                                                'Conda version', '✓', '✗', '⚠️']):
                            print(f"  📍 {line.strip()}")
                
                return {
                    "success": return_code == 0,
                    "output": stdout,
                    "error": stderr,
                    "return_code": return_code
                }
            except subprocess.TimeoutExpired:
                process.kill()
                stdout, stderr = process.communicate()  # Get any remaining output
                error_msg = f"Command timed out after {timeout} seconds. Partial output captured."
                print(f"⏰ {error_msg}")
                return {
                    "success": False,
                    "output": stdout if stdout else "No output captured before timeout",
                    "error": f"{error_msg}\n{stderr}" if stderr else error_msg,
                    "return_code": -1
                }
        else:
            # Original non-streaming version for quick commands
            result = subprocess.run(
                full_command,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=os.path.dirname(os.path.dirname(__file__))
            )
            
            return {
                "success": result.returncode == 0,
                "output": result.stdout,
                "error": result.stderr,
                "return_code": result.returncode
            }
        
    except subprocess.TimeoutExpired as e:
        error_msg = f"Command timed out after {timeout} seconds"
        print(f"⏰ {error_msg}: {' '.join(full_command)}")
        # Try to get partial output if available
        partial_output = e.stdout.decode() if e.stdout else "No output captured"
        partial_error = e.stderr.decode() if e.stderr else ""
        return {
            "success": False,
            "output": partial_output,
            "error": f"{error_msg}\n{partial_error}",
            "return_code": -1
        }
    except Exception as e:
        print(f"❌ Error in execute_command: {e}")  # Debug logging
        raise HTTPException(status_code=500, detail=str(e))

# Comparison API Endpoints
@app.post("/api/comparison/baseline/create")
async def create_baseline():
    """Create baseline version 0.01 from working robots (.21, .58, .62)"""
    try:
        print("📊 Creating baseline version 0.01 from working robots...")
        baseline = create_baseline_deployment()
        return {
            "status": "success",
            "message": "Baseline version 0.01 created successfully",
            "baseline": {
                "version": baseline["version"],
                "created": baseline["created"],
                "robots": baseline["robots"],
                "files_count": len(baseline["files"]),
                "checksums_count": len(baseline["checksums"])
            }
        }
    except Exception as e:
        print(f"Error creating baseline: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/comparison/baseline")
async def get_baseline():
    """Get baseline version information"""
    try:
        baseline_file = Path("/tmp/robot_comparisons/baseline_v0.01.json")
        if not baseline_file.exists():
            raise HTTPException(status_code=404, detail="Baseline not found. Create it first.")
        
        with open(baseline_file, 'r') as f:
            baseline = json.load(f)
        
        return {
            "version": baseline["version"],
            "created": baseline["created"],
            "robots": baseline["robots"],
            "files": list(baseline["files"].keys()),
            "checksums": list(baseline["checksums"].keys())
        }
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Baseline not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/comparison/compare")
async def compare_robots(request: Request):
    """Compare two robots' deployments"""
    try:
        data = await request.json()
        robot1_ip = data.get("robot1")
        robot2_ip = data.get("robot2")
        
        if not robot1_ip or not robot2_ip:
            raise HTTPException(status_code=400, detail="Both robot1 and robot2 IPs are required")
        
        print(f"🔍 Comparing {robot1_ip} vs {robot2_ip}...")
        comparison = compare_robot_deployments(robot1_ip, robot2_ip)
        
        return {
            "status": "success",
            "comparison": {
                "robot1": comparison["robot1"],
                "robot2": comparison["robot2"],
                "timestamp": comparison["timestamp"],
                "differences_count": len(comparison["differences"]),
                "identical_files_count": len(comparison["identical_files"]),
                "robot1_missing_count": len(comparison["missing_files"]["robot1_missing"]),
                "robot2_missing_count": len(comparison["missing_files"]["robot2_missing"]),
                "differences": comparison["differences"],
                "missing_files": comparison["missing_files"],
                "identical_files": comparison["identical_files"]
            }
        }
    except Exception as e:
        print(f"Error comparing robots: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/comparison/check-compliance")
async def check_compliance(request: Request):
    """Check if a robot is compliant with baseline version 0.01"""
    try:
        data = await request.json()
        robot_ip = data.get("robot_ip")
        
        if not robot_ip:
            raise HTTPException(status_code=400, detail="robot_ip is required")
        
        print(f"✅ Checking compliance for {robot_ip}...")
        comparison = compare_robot_to_baseline(robot_ip)
        
        return {
            "status": "success",
            "robot": comparison["robot"],
            "baseline_version": comparison["baseline_version"],
            "compliance_status": comparison["status"],
            "is_compliant": comparison["status"] == "compliant",
            "differences_count": len(comparison["differences"]),
            "missing_files_count": len(comparison["missing_files"]),
            "differences": comparison["differences"],
            "missing_files": comparison["missing_files"]
        }
    except Exception as e:
        print(f"Error checking compliance: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/comparison/files/{robot_ip}")
async def get_robot_files(robot_ip: str):
    """Get cached files from a robot"""
    try:
        cache_file = Path(f"/tmp/robot_comparisons/{robot_ip.replace('.', '_')}.json")
        if not cache_file.exists():
            # Fetch fresh data
            engine = RobotFileComparison()
            robot_data = engine.fetch_robot_files(robot_ip)
        else:
            with open(cache_file, 'r') as f:
                robot_data = json.load(f)
        
        return {
            "robot": robot_ip,
            "timestamp": robot_data["timestamp"],
            "files": list(robot_data["files"].keys()),
            "checksums": robot_data["checksums"],
            "errors": robot_data.get("errors", [])
        }
    except Exception as e:
        print(f"Error getting robot files: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/comparison/refresh/{robot_ip}")
async def refresh_robot_cache(robot_ip: str):
    """Refresh cached files for a robot"""
    try:
        print(f"🔄 Refreshing cache for {robot_ip}...")
        engine = RobotFileComparison()
        robot_data = engine.fetch_robot_files(robot_ip)
        
        return {
            "status": "success",
            "message": f"Cache refreshed for {robot_ip}",
            "files_fetched": len(robot_data["files"]),
            "checksums_fetched": len(robot_data["checksums"]),
            "errors": robot_data.get("errors", [])
        }
    except Exception as e:
        print(f"Error refreshing cache: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/deploy-from-master")
async def deploy_from_master(request: Request):
    """Deploy from master robot (.21) to target robot using rsync and auto-configure teleop.ini"""
    try:
        data = await request.json()
        target_ip = data.get("target_ip")
        master_ip = data.get("master_ip", "192.168.88.58")  # Changed to .58 since .21 is dead
        
        if not target_ip:
            raise HTTPException(status_code=400, detail="target_ip is required")
        
        print(f"🚀 Deploying from {master_ip} to {target_ip}...")
        
        # Execute the deployment script with source parameter
        result = subprocess.run(
            ["python3",
             os.path.join(os.path.dirname(os.path.dirname(__file__)), "deployment-master/lekiwi-master-deploy.py"),
             target_ip,
             "--source", master_ip,
             "--action", "full"],
            capture_output=True,
            text=True,
            timeout=120,  # 2 minute timeout for full deployment
            cwd=os.path.dirname(os.path.dirname(__file__))
        )
        
        return {
            "success": result.returncode == 0,
            "output": result.stdout,
            "error": result.stderr,
            "message": f"Deployment from {master_ip} to {target_ip} " +
                      ("completed successfully" if result.returncode == 0 else "failed"),
            "return_code": result.returncode
        }
        
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=408, detail="Deployment timed out")
    except Exception as e:
        print(f"Error in deploy_from_master: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# SSH API Endpoints for simplified SSH access
@app.post("/api/ssh-simple")
async def create_ssh_session(request: Request):
    """Create simplified SSH session (returns session info for frontend)"""
    try:
        data = await request.json()
        robot_ip = data.get("robot_ip")
        robot_id = data.get("robot_id", robot_ip)
        
        if not robot_ip:
            raise HTTPException(status_code=400, detail="robot_ip is required")
        
        # Test SSH connectivity with adequate timeout for slow Pis
        test_cmd = ["sshpass", "-p", "lekiwi", "ssh", "-o", "StrictHostKeyChecking=no",
                   "-o", "ConnectTimeout=15", f"lekiwi@{robot_ip}", "echo 'SSH connection test'"]
        
        result = subprocess.run(test_cmd, capture_output=True, text=True, timeout=20)
        
        if result.returncode != 0:
            raise HTTPException(status_code=503, detail=f"Cannot connect to robot at {robot_ip}: {result.stderr}")
        
        # Generate simple session ID
        session_id = f"ssh_{uuid.uuid4().hex[:8]}_{robot_ip.replace('.', '_')}"
        
        return {
            "session_id": session_id,
            "robot_ip": robot_ip,
            "robot_id": robot_id,
            "status": "connected"
        }
        
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=408, detail=f"SSH connection to {robot_ip} timed out (15s limit)")
    except Exception as e:
        print(f"SSH connection error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/ssh-execute")
async def execute_ssh_command(request: Request):
    """Execute command via SSH on robot"""
    try:
        data = await request.json()
        robot_ip = data.get("robot_ip")
        command = data.get("command")
        
        if not robot_ip or not command:
            raise HTTPException(status_code=400, detail="robot_ip and command are required")
        
        # Security: Basic command filtering
        dangerous_commands = ["rm -rf", "format", "mkfs", "dd if=", ":(){ :|:& };:", "shutdown", "reboot"]
        if any(dangerous in command.lower() for dangerous in dangerous_commands):
            raise HTTPException(status_code=403, detail="Potentially dangerous command blocked")
        
        # Execute command via SSH with adequate timeout
        ssh_cmd = ["sshpass", "-p", "lekiwi", "ssh", "-o", "StrictHostKeyChecking=no",
                  "-o", "ConnectTimeout=15", f"lekiwi@{robot_ip}", command]
        
        result = subprocess.run(ssh_cmd, capture_output=True, text=True, timeout=45)
        
        return {
            "success": result.returncode == 0,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "exit_code": result.returncode,
            "command": command,
            "robot_ip": robot_ip
        }
        
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=408, detail="SSH command timed out")
    except Exception as e:
        print(f"SSH execution error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# WebSocket for real-time updates
from fastapi import WebSocket, WebSocketDisconnect
from typing import Set

class ConnectionManager:
    def __init__(self):
        self.active_connections: Set[WebSocket] = set()
    
    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.add(websocket)
    
    def disconnect(self, websocket: WebSocket):
        self.active_connections.discard(websocket)
    
    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except:
                pass

manager = ConnectionManager()

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket for real-time updates"""
    await manager.connect(websocket)
    try:
        while True:
            # Keep connection alive and handle messages
            data = await websocket.receive_text()
            # Echo back or handle commands
            await websocket.send_text(f"Echo: {data}")
    except WebSocketDisconnect:
        manager.disconnect(websocket)

# Versioning System API Endpoints
@app.post("/api/versioning/snapshot")
async def create_version_snapshot(request: Request):
    """Create a snapshot from a master robot"""
    if not versioning:
        raise HTTPException(status_code=500, detail="Versioning system not available")
    
    data = await request.json()
    master_ip = data.get('master_ip', '192.168.88.58')  # Default to .58 since .21 is dead
    version = data.get('version', 'latest')
    description = data.get('description', 'Snapshot created from web UI')
    
    try:
        snapshot_path = versioning.create_snapshot(master_ip, version, description)
        return JSONResponse(content={
            "success": True,
            "snapshot_path": str(snapshot_path),
            "version": version,
            "message": f"Snapshot created from {master_ip}"
        })
    except Exception as e:
        print(f"Snapshot creation error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/versioning/list")
async def list_version_snapshots():
    """List all available version snapshots"""
    if not versioning:
        raise HTTPException(status_code=500, detail="Versioning system not available")
    
    try:
        versions = versioning.list_versions()
        return JSONResponse(content={
            "success": True,
            "versions": versions
        })
    except Exception as e:
        print(f"Error listing versions: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/versioning/deploy")
async def deploy_version_to_robot(request: Request):
    """Deploy a specific version to a robot using delta sync"""
    if not versioning:
        raise HTTPException(status_code=500, detail="Versioning system not available")
    
    data = await request.json()
    target_ip = data.get('target_ip')
    version = data.get('version', 'latest')
    delta_only = data.get('delta_only', True)
    
    if not target_ip:
        raise HTTPException(status_code=400, detail="Target IP required")
    
    try:
        result = versioning.deploy_version(target_ip, version, delta_only=delta_only)
        return JSONResponse(content={
            "success": True,
            "deployed_files": result,
            "version": version,
            "target": target_ip,
            "message": f"Version {version} deployed to {target_ip}"
        })
    except Exception as e:
        print(f"Deployment error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/versioning/calculate-delta")
async def calculate_version_delta(request: Request):
    """Calculate delta between robot and version"""
    if not versioning:
        raise HTTPException(status_code=500, detail="Versioning system not available")
    
    data = await request.json()
    target_ip = data.get('target_ip')
    version = data.get('version', 'latest')
    
    if not target_ip:
        raise HTTPException(status_code=400, detail="Target IP required")
    
    try:
        delta = versioning.calculate_delta(target_ip, version)
        return JSONResponse(content={
            "success": True,
            "delta": delta,
            "version": version,
            "target": target_ip,
            "files_to_add": len(delta.get('files_to_add', [])),
            "files_to_update": len(delta.get('files_to_update', [])),
            "files_to_remove": len(delta.get('files_to_remove', []))
        })
    except Exception as e:
        print(f"Delta calculation error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# API endpoint to manually trigger discovery
@app.post("/api/discover")
async def trigger_discovery():
    """Manually trigger robot discovery"""
    try:
        print("🔍 Manually triggering robot discovery...")
        
        # Clean up old discovery files
        for file in ["/tmp/discovery_results.json", "/tmp/smart_discovered.txt",
                     "/tmp/lekiwi_fleet.json", "/tmp/robot_types.json"]:
            file_path = Path(file)
            if file_path.exists():
                file_path.unlink()
        
        # Run smart discovery with adequate timeout for thorough scanning
        discovery_result = subprocess.run(
            ["python3", "smart_discover.py"],
            capture_output=True,
            text=True,
            timeout=120,  # Increased timeout for complete discovery
            cwd=Path(__file__).parent
        )
        
        if discovery_result.returncode != 0:
            print(f"⚠️ Discovery failed: {discovery_result.stderr}")
            raise HTTPException(status_code=500, detail="Discovery failed")
        
        # Convert discovery results to fleet configuration
        discovered_file = Path("/tmp/smart_discovered.txt")
        if discovered_file.exists():
            conversion_result = subprocess.run(
                ["python3", "add_discovered_robots.py"],
                capture_output=True,
                text=True,
                timeout=10,
                cwd=Path(__file__).parent
            )
            
            if conversion_result.returncode != 0:
                print(f"⚠️ Fleet conversion failed: {conversion_result.stderr}")
        
        # Read the fleet file
        fleet_file = Path("/tmp/lekiwi_fleet.json")
        if fleet_file.exists():
            with open(fleet_file, 'r') as f:
                fleet_data = json.load(f)
                return {
                    "status": "success",
                    "message": f"Discovered {fleet_data.get('total', 0)} robots",
                    "fleet": fleet_data
                }
        else:
            return {
                "status": "warning",
                "message": "Discovery completed but no robots found",
                "fleet": {
                    "robots": [],
                    "total": 0,
                    "discovered_at": datetime.now().timestamp()
                }
            }
            
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=408, detail="Discovery timed out")
    except Exception as e:
        print(f"❌ Discovery error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Camera Streaming Endpoints
@app.get("/api/robot/{robot_ip}/stream.mjpg")
async def get_camera_stream(robot_ip: str, camera: str = Query(default="0")):
    """Get MJPEG stream from robot camera"""
    from fastapi.responses import StreamingResponse
    
    # Simple MJPEG streaming command
    cmd = f"sshpass -p lekiwi ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 lekiwi@{robot_ip} 'ffmpeg -f v4l2 -i /dev/video{camera} -f mjpeg -q:v 5 -r 10 -' 2>/dev/null"
    
    def generate():
        process = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        try:
            while True:
                data = process.stdout.read(65536)  # Read in chunks
                if not data:
                    break
                yield data
        finally:
            process.terminate()
    
    return StreamingResponse(generate(), media_type="multipart/x-mixed-replace;boundary=frame")

# Simplified camera thumbnail endpoint
@app.get("/api/robot/{robot_ip}/camera-thumbnail")
async def get_camera_thumbnail(robot_ip: str):
    """Get camera thumbnails from a robot - SIMPLIFIED"""
    try:
        thumbnails = {}
        
        # Detect robot type
        from detect_robot_type import detect_robot_type
        robot_type = detect_robot_type(robot_ip)
        print(f"📷 Getting thumbnails for {robot_ip} (type: {robot_type})")
        
        # Simple approach: just grab a frame from each camera
        
        if robot_type == 'xlerobot':
            # XLE Robot: Try to grab frames from 3 cameras
            cameras = [
                ('RealSense', '/dev/video0'),
                ('Claw 1', '/dev/video2'),
                ('Claw 2', '/dev/video4')
            ]
        else:
            # LeKiwi Robot: 2 cameras
            cameras = [
                ('Front', '/dev/video0'),
                ('Wrist', '/dev/video2')
            ]
        
        # Try to capture a frame from each camera
        for cam_name, video_dev in cameras:
            cmd = f"sshpass -p lekiwi ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 lekiwi@{robot_ip} 'ffmpeg -f v4l2 -i {video_dev} -frames:v 1 -f image2pipe -vcodec mjpeg -vf scale=320:240 - 2>/dev/null' | base64"
            
            try:
                result = subprocess.run(["bash", "-c", cmd], capture_output=True, timeout=10)
                if result.returncode == 0 and result.stdout:
                    base64_data = result.stdout.decode().replace('\n', '').strip()
                    if base64_data:
                        thumbnails[cam_name.lower().replace(' ', '_')] = f"data:image/jpeg;base64,{base64_data}"
                        print(f"  ✓ Captured {cam_name} from {video_dev}")
                    else:
                        print(f"  ✗ No data from {cam_name} at {video_dev}")
                else:
                    print(f"  ✗ Failed to capture {cam_name} from {video_dev}")
            except Exception as e:
                print(f"  ✗ Error capturing {cam_name}: {e}")
        
        # Return simplified results
        return JSONResponse(content={
            "success": len(thumbnails) > 0,
            "robot_type": robot_type,
            "thumbnails": thumbnails,
            "camera_count": len(thumbnails),
            "timestamp": time.time()
        })
            
    except Exception as e:
        print(f"Camera thumbnail error for {robot_ip}: {e}")
        return JSONResponse(content={
            "success": False,
            "error": str(e),
            "thumbnails": {},
            "timestamp": time.time()
        })

@app.get("/api/robot/{robot_ip}/type")
async def get_robot_type(robot_ip: str):
    """Get robot type (lekiwi vs xlerobot)"""
    try:
        from detect_robot_type import detect_robot_type, get_robot_capabilities
        
        robot_type = detect_robot_type(robot_ip)
        capabilities = get_robot_capabilities(robot_ip)
        
        return JSONResponse(content={
            "success": True,
            "type": robot_type,
            "capabilities": capabilities,
            "robot_ip": robot_ip
        })
        
    except Exception as e:
        print(f"Robot type detection error for {robot_ip}: {e}")
        return JSONResponse(content={
            "success": False,
            "type": "unknown",
            "error": str(e),
            "robot_ip": robot_ip
        })

@app.get("/api/robot/{robot_ip}/teleoperation-status")
async def get_teleoperation_status(robot_ip: str):
    """Check if robot is being teleoperated"""
    try:
        # Method 1: Check for teleoperate.py process
        process_check_cmd = f"sshpass -p lekiwi ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10 lekiwi@{robot_ip} 'pgrep -f teleoperate.py || echo none'"
        
        process_result = subprocess.run(
            ["bash", "-c", process_check_cmd],
            capture_output=True,
            text=True,
            timeout=15
        )
        
        has_process = process_result.returncode == 0 and process_result.stdout.strip() != "none"
        
        # Method 2: Check if port 5558 is in use (teleoperation port)
        port_check_cmd = f"sshpass -p lekiwi ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10 lekiwi@{robot_ip} 'netstat -tuln | grep :5558 || echo none'"
        
        port_result = subprocess.run(
            ["bash", "-c", port_check_cmd],
            capture_output=True,
            text=True,
            timeout=15
        )
        
        port_in_use = port_result.returncode == 0 and port_result.stdout.strip() != "none"
        
        # Method 3: Check systemctl status of teleop service
        service_check_cmd = f"sshpass -p lekiwi ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10 lekiwi@{robot_ip} 'systemctl is-active teleop'"
        
        service_result = subprocess.run(
            ["bash", "-c", service_check_cmd],
            capture_output=True,
            text=True,
            timeout=15
        )
        
        service_active = service_result.stdout.strip() == "active"
        
        # Determine if teleoperated
        is_teleoperated = has_process or port_in_use
        
        return JSONResponse(content={
            "success": True,
            "teleoperated": is_teleoperated,
            "details": {
                "process_running": has_process,
                "port_5558_in_use": port_in_use,
                "teleop_service_active": service_active,
                "checked_at": datetime.now().isoformat()
            },
            "robot_ip": robot_ip
        })
        
    except subprocess.TimeoutExpired:
        return JSONResponse(content={
            "success": False,
            "teleoperated": False,
            "error": "Connection timeout",
            "robot_ip": robot_ip
        })
    except Exception as e:
        print(f"Teleoperation status error for {robot_ip}: {e}")
        return JSONResponse(content={
            "success": False,
            "teleoperated": False,
            "error": str(e),
            "robot_ip": robot_ip
        })

@app.post("/api/robot/{robot_ip}/stop-teleop")
async def stop_teleoperation(robot_ip: str):
    """Stop teleoperation services on a robot"""
    try:
        print(f"🛑 Stopping teleoperation on {robot_ip}...")
        
        # First, check if services exist before trying to stop them
        # Check if teleop service exists
        teleop_exists_cmd = f"sshpass -p lekiwi ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10 lekiwi@{robot_ip} 'systemctl list-unit-files | grep -q \"^teleop.service\" && echo \"exists\" || echo \"not_installed\"'"
        
        teleop_exists_result = subprocess.run(
            ["bash", "-c", teleop_exists_cmd],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        teleop_exists = teleop_exists_result.stdout.strip() == "exists"
        
        # Check if lekiwi service exists
        lekiwi_exists_cmd = f"sshpass -p lekiwi ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10 lekiwi@{robot_ip} 'systemctl list-unit-files | grep -q \"^lekiwi.service\" && echo \"exists\" || echo \"not_installed\"'"
        
        lekiwi_exists_result = subprocess.run(
            ["bash", "-c", lekiwi_exists_cmd],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        lekiwi_exists = lekiwi_exists_result.stdout.strip() == "exists"
        
        # If neither service exists, return error
        if not teleop_exists and not lekiwi_exists:
            return JSONResponse(content={
                "success": False,
                "services_stopped": {
                    "teleop": False,
                    "lekiwi": False
                },
                "details": {
                    "teleop_status": "not installed",
                    "lekiwi_status": "not installed",
                    "teleop_exists": False,
                    "lekiwi_exists": False
                },
                "message": "Services are not installed on this robot",
                "robot_ip": robot_ip
            }, status_code=400)
        
        # Track service statuses
        teleop_final_status = "not installed"
        lekiwi_final_status = "not installed"
        teleop_stopped = False
        lekiwi_stopped = False
        
        # Stop teleop service if it exists
        if teleop_exists:
            # Check current status
            teleop_check_cmd = f"sshpass -p lekiwi ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10 lekiwi@{robot_ip} 'systemctl is-active teleop'"
            teleop_status = subprocess.run(
                ["bash", "-c", teleop_check_cmd],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            teleop_current_status = teleop_status.stdout.strip()
            
            if teleop_current_status == "active":
                # Service is running, stop it
                teleop_stop_cmd = f"sshpass -p lekiwi ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10 lekiwi@{robot_ip} 'sudo systemctl stop teleop'"
                teleop_result = subprocess.run(
                    ["bash", "-c", teleop_stop_cmd],
                    capture_output=True,
                    text=True,
                    timeout=15
                )
                
                # Check if stop was successful
                teleop_check_after = subprocess.run(
                    ["bash", "-c", teleop_check_cmd],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                
                if teleop_check_after.stdout.strip() != "active":
                    teleop_stopped = True
                    teleop_final_status = "stopped"
                else:
                    teleop_final_status = "failed to stop"
            else:
                # Service exists but is already stopped
                teleop_stopped = True
                teleop_final_status = "already stopped"
        
        # Stop lekiwi service if it exists
        if lekiwi_exists:
            # Check current status
            lekiwi_check_cmd = f"sshpass -p lekiwi ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10 lekiwi@{robot_ip} 'systemctl is-active lekiwi'"
            lekiwi_status = subprocess.run(
                ["bash", "-c", lekiwi_check_cmd],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            lekiwi_current_status = lekiwi_status.stdout.strip()
            
            if lekiwi_current_status == "active":
                # Service is running, stop it
                lekiwi_stop_cmd = f"sshpass -p lekiwi ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10 lekiwi@{robot_ip} 'sudo systemctl stop lekiwi'"
                lekiwi_result = subprocess.run(
                    ["bash", "-c", lekiwi_stop_cmd],
                    capture_output=True,
                    text=True,
                    timeout=15
                )
                
                # Check if stop was successful
                lekiwi_check_after = subprocess.run(
                    ["bash", "-c", lekiwi_check_cmd],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                
                if lekiwi_check_after.stdout.strip() != "active":
                    lekiwi_stopped = True
                    lekiwi_final_status = "stopped"
                else:
                    lekiwi_final_status = "failed to stop"
            else:
                # Service exists but is already stopped
                lekiwi_stopped = True
                lekiwi_final_status = "already stopped"
        
        # Determine overall success
        # Success means: all existing services are stopped (either were already stopped or we stopped them)
        success = True
        if teleop_exists and not teleop_stopped:
            success = False
        if lekiwi_exists and not lekiwi_stopped:
            success = False
        
        # Create appropriate message
        if success:
            if not teleop_exists and not lekiwi_exists:
                message = "No services installed to stop"
            elif teleop_final_status == "already stopped" and lekiwi_final_status == "already stopped":
                message = "Services were already stopped"
            elif teleop_final_status == "stopped" or lekiwi_final_status == "stopped":
                message = "Services stopped successfully"
            else:
                message = "Services are not running"
        else:
            message = "Failed to stop some services"
        
        return JSONResponse(content={
            "success": success,
            "services_stopped": {
                "teleop": teleop_stopped,
                "lekiwi": lekiwi_stopped
            },
            "details": {
                "teleop_status": teleop_final_status,
                "lekiwi_status": lekiwi_final_status,
                "teleop_exists": teleop_exists,
                "lekiwi_exists": lekiwi_exists
            },
            "message": message,
            "robot_ip": robot_ip
        })
        
    except subprocess.TimeoutExpired:
        return JSONResponse(content={
            "success": False,
            "error": "Connection timeout",
            "message": "Failed to connect to robot",
            "robot_ip": robot_ip
        }, status_code=408)
    except Exception as e:
        print(f"Stop teleoperation error for {robot_ip}: {e}")
        return JSONResponse(content={
            "success": False,
            "error": str(e),
            "message": f"Error stopping teleoperation: {str(e)}",
            "robot_ip": robot_ip
        }, status_code=500)

# Main entry point
if __name__ == "__main__":
    uvicorn.run(
        "server:app",
        host="0.0.0.0",
        port=CONFIG["server_port"],
        reload=True,
        log_level="info"
    )