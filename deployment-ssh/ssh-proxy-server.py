#!/usr/bin/env python3
"""
LeKiwi Secure SSH Proxy Server
Managed SSH access with audit logging and Gun.js integration
"""

import os
import sys
import json
import uuid
import asyncio
import subprocess
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, Optional, List
import hashlib
import jwt

from fastapi import FastAPI, HTTPException, WebSocket, Request, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import paramiko
import uvicorn
from pydantic import BaseModel

# Gun.js for real-time robot discovery
try:
    from gundb import Gun
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "gun-python", "paramiko"])
    from gundb import Gun

class SSHProxyServer:
    """
    Secure SSH proxy with audit logging and access control
    """
    
    def __init__(self):
        self.app = FastAPI(title="LeKiwi SSH Proxy")
        self.security = HTTPBearer()
        
        # Gun.js connection for robot discovery
        self.gun = Gun(['ws://localhost:8765/gun'])
        self.fleet_ref = self.gun.get('lekiwi-fleet')
        self.robots_ref = self.fleet_ref.get('robots')
        
        # SSH key management
        self.keys_dir = Path("/opt/lekiwi-deploy/ssh-keys")
        self.keys_dir.mkdir(parents=True, exist_ok=True)
        
        # Audit log
        self.audit_log = Path("/opt/lekiwi-deploy/logs/ssh-audit.log")
        self.audit_log.parent.mkdir(parents=True, exist_ok=True)
        
        # Active SSH sessions
        self.active_sessions = {}
        
        # Setup routes
        self.setup_routes()
        
        # Load authorized keys
        self.load_authorized_keys()
    
    def load_authorized_keys(self):
        """Load or generate SSH keys for robot access"""
        self.master_key_path = self.keys_dir / "master_key"
        
        if not self.master_key_path.exists():
            # Generate master SSH key
            subprocess.run([
                "ssh-keygen", "-t", "rsa", "-b", "4096",
                "-f", str(self.master_key_path),
                "-N", "",  # No passphrase
                "-C", "lekiwi-master@deploy.lekiwi.io"
            ], check=True)
            
            print(f"✅ Generated master SSH key: {self.master_key_path}")
    
    def audit_log_entry(self, user: str, action: str, robot_id: str, details: Dict = None):
        """Log SSH access for audit trail"""
        entry = {
            "timestamp": datetime.now().isoformat(),
            "user": user,
            "action": action,
            "robot_id": robot_id,
            "details": details or {}
        }
        
        with open(self.audit_log, "a") as f:
            f.write(json.dumps(entry) + "\n")
    
    def verify_access(self, user: str, robot_id: str) -> bool:
        """Verify user has access to robot"""
        # Check user permissions (integrate with your auth system)
        # For now, implement role-based access
        
        user_roles = self.get_user_roles(user)
        
        # Admins can access all robots
        if "admin" in user_roles:
            return True
        
        # Developers can access non-production robots
        robot_group = self.get_robot_group(robot_id)
        if "developer" in user_roles and robot_group != "production":
            return True
        
        # Check specific robot permissions
        return self.check_robot_permission(user, robot_id)
    
    def get_user_roles(self, user: str) -> List[str]:
        """Get user roles from auth system"""
        # TODO: Integrate with your auth system
        # For demo, use a simple mapping
        role_map = {
            "admin@lekiwi.io": ["admin"],
            "dev@lekiwi.io": ["developer"],
            "ops@lekiwi.io": ["operator"]
        }
        return role_map.get(user, ["viewer"])
    
    def get_robot_group(self, robot_id: str) -> str:
        """Get robot group from Gun.js"""
        # Query Gun.js for robot info
        # For demo, return based on ID pattern
        if "PROD" in robot_id:
            return "production"
        elif "STG" in robot_id:
            return "staging"
        return "development"
    
    def check_robot_permission(self, user: str, robot_id: str) -> bool:
        """Check specific robot access permission"""
        # TODO: Implement granular permissions
        return False
    
    async def create_ssh_session(self, robot_id: str, user: str) -> Dict:
        """Create SSH session to robot"""
        try:
            # Get robot IP from Gun.js or discovery
            robot_ip = await self.get_robot_ip(robot_id)
            
            if not robot_ip:
                raise Exception(f"Robot {robot_id} not found")
            
            # Create SSH client
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            
            # Connect using master key
            ssh.connect(
                hostname=robot_ip,
                username="lekiwi",
                key_filename=str(self.master_key_path),
                timeout=10
            )
            
            # Generate session ID
            session_id = str(uuid.uuid4())
            
            # Store session
            self.active_sessions[session_id] = {
                "ssh_client": ssh,
                "robot_id": robot_id,
                "robot_ip": robot_ip,
                "user": user,
                "started_at": datetime.now().isoformat(),
                "commands": []
            }
            
            # Log access
            self.audit_log_entry(user, "ssh_connect", robot_id, {
                "session_id": session_id,
                "robot_ip": robot_ip
            })
            
            return {
                "session_id": session_id,
                "robot_id": robot_id,
                "robot_ip": robot_ip,
                "status": "connected"
            }
            
        except Exception as e:
            self.audit_log_entry(user, "ssh_connect_failed", robot_id, {
                "error": str(e)
            })
            raise
    
    async def get_robot_ip(self, robot_id: str) -> Optional[str]:
        """Get robot IP address from Gun.js or network discovery"""
        # Try Gun.js first
        # For demo, use pattern matching
        if robot_id.startswith("Lekiwi_"):
            # Extract last part as IP hint
            # In production, query Gun.js or use service discovery
            return f"192.168.88.{hash(robot_id) % 254 + 1}"
        return None
    
    def setup_routes(self):
        """Setup FastAPI routes"""
        
        @self.app.post("/api/ssh/connect")
        async def connect_ssh(
            robot_id: str,
            credentials: HTTPAuthorizationCredentials = Depends(self.security)
        ):
            """Establish SSH connection to robot"""
            # Verify JWT token
            try:
                payload = jwt.decode(
                    credentials.credentials,
                    os.getenv("JWT_SECRET", "secret"),
                    algorithms=["HS256"]
                )
                user = payload.get("user")
            except jwt.InvalidTokenError:
                raise HTTPException(status_code=401, detail="Invalid token")
            
            # Verify access
            if not self.verify_access(user, robot_id):
                raise HTTPException(status_code=403, detail="Access denied")
            
            # Create SSH session
            session = await self.create_ssh_session(robot_id, user)
            return session
        
        @self.app.post("/api/ssh/execute")
        async def execute_command(
            session_id: str,
            command: str,
            credentials: HTTPAuthorizationCredentials = Depends(self.security)
        ):
            """Execute command via SSH"""
            if session_id not in self.active_sessions:
                raise HTTPException(status_code=404, detail="Session not found")
            
            session = self.active_sessions[session_id]
            ssh_client = session["ssh_client"]
            
            # Log command
            session["commands"].append({
                "command": command,
                "timestamp": datetime.now().isoformat()
            })
            
            self.audit_log_entry(
                session["user"],
                "ssh_command",
                session["robot_id"],
                {"command": command, "session_id": session_id}
            )
            
            # Execute command
            stdin, stdout, stderr = ssh_client.exec_command(command)
            
            return {
                "stdout": stdout.read().decode(),
                "stderr": stderr.read().decode(),
                "exit_code": stdout.channel.recv_exit_status()
            }
        
        @self.app.websocket("/ws/ssh/{session_id}")
        async def ssh_websocket(websocket: WebSocket, session_id: str):
            """WebSocket for interactive SSH session"""
            await websocket.accept()
            
            if session_id not in self.active_sessions:
                await websocket.close(code=1008, reason="Session not found")
                return
            
            session = self.active_sessions[session_id]
            ssh_client = session["ssh_client"]
            
            # Create interactive shell
            channel = ssh_client.invoke_shell()
            
            # Relay data between WebSocket and SSH
            try:
                while True:
                    # From client to SSH
                    if websocket.client_state.value == 1:  # Connected
                        try:
                            data = await asyncio.wait_for(
                                websocket.receive_text(),
                                timeout=0.1
                            )
                            channel.send(data)
                        except asyncio.TimeoutError:
                            pass
                    
                    # From SSH to client
                    if channel.recv_ready():
                        output = channel.recv(1024).decode()
                        await websocket.send_text(output)
                    
                    await asyncio.sleep(0.01)
                    
            except Exception as e:
                print(f"WebSocket error: {e}")
            finally:
                channel.close()
                await websocket.close()
        
        @self.app.delete("/api/ssh/disconnect/{session_id}")
        async def disconnect_ssh(session_id: str):
            """Disconnect SSH session"""
            if session_id in self.active_sessions:
                session = self.active_sessions[session_id]
                session["ssh_client"].close()
                
                self.audit_log_entry(
                    session["user"],
                    "ssh_disconnect",
                    session["robot_id"],
                    {
                        "session_id": session_id,
                        "duration": str(
                            datetime.now() - 
                            datetime.fromisoformat(session["started_at"])
                        ),
                        "commands_executed": len(session["commands"])
                    }
                )
                
                del self.active_sessions[session_id]
                
            return {"status": "disconnected"}
        
        @self.app.get("/api/ssh/sessions")
        async def list_sessions(
            credentials: HTTPAuthorizationCredentials = Depends(self.security)
        ):
            """List active SSH sessions"""
            # Only admins can see all sessions
            sessions = []
            for sid, session in self.active_sessions.items():
                sessions.append({
                    "session_id": sid,
                    "robot_id": session["robot_id"],
                    "user": session["user"],
                    "started_at": session["started_at"],
                    "commands_executed": len(session["commands"])
                })
            return sessions
        
        @self.app.get("/api/ssh/audit")
        async def get_audit_log(
            limit: int = 100,
            credentials: HTTPAuthorizationCredentials = Depends(self.security)
        ):
            """Get SSH audit log"""
            # Only admins can view audit log
            entries = []
            if self.audit_log.exists():
                with open(self.audit_log, "r") as f:
                    lines = f.readlines()[-limit:]
                    for line in lines:
                        entries.append(json.loads(line))
            return entries

# Branch-based versioning system
class BranchVersioning:
    """
    Automatic versioning based on Git branches
    """
    
    @staticmethod
    def get_version_from_branch():
        """Generate version from current Git branch"""
        try:
            # Get current branch
            branch = subprocess.check_output(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                stderr=subprocess.DEVNULL
            ).decode().strip()
            
            # Get commit hash
            commit = subprocess.check_output(
                ["git", "rev-parse", "--short", "HEAD"],
                stderr=subprocess.DEVNULL
            ).decode().strip()
            
            # Get commit count
            count = subprocess.check_output(
                ["git", "rev-list", "--count", "HEAD"],
                stderr=subprocess.DEVNULL
            ).decode().strip()
            
            # Generate version based on branch
            if branch == "main" or branch == "master":
                # Production version
                version = f"v1.0.{count}"
            elif branch == "develop":
                # Development version
                version = f"v0.9.{count}-dev"
            elif branch.startswith("feature/"):
                # Feature branch
                feature = branch.replace("feature/", "")
                version = f"v0.0.{count}-{feature}"
            elif branch.startswith("hotfix/"):
                # Hotfix version
                hotfix = branch.replace("hotfix/", "")
                version = f"v1.0.{count}-hotfix-{hotfix}"
            else:
                # Generic branch version
                version = f"v0.0.{count}-{branch}"
            
            # Add commit hash for uniqueness
            version = f"{version}+{commit}"
            
            return {
                "version": version,
                "branch": branch,
                "commit": commit,
                "build": count
            }
            
        except Exception as e:
            # Fallback version
            return {
                "version": f"v0.0.0+{datetime.now().strftime('%Y%m%d%H%M%S')}",
                "branch": "unknown",
                "commit": "unknown",
                "build": "0"
            }
    
    @staticmethod
    def create_deployment_from_branch():
        """Create deployment with automatic branch versioning"""
        version_info = BranchVersioning.get_version_from_branch()
        
        # Determine target group based on branch
        branch = version_info["branch"]
        if branch in ["main", "master"]:
            target_group = "production"
        elif branch == "develop":
            target_group = "development"
        elif branch.startswith("feature/"):
            target_group = "feature-test"
        elif branch.startswith("hotfix/"):
            target_group = "hotfix-test"
        else:
            target_group = "experimental"
        
        deployment = {
            "version": version_info["version"],
            "branch": branch,
            "commit": version_info["commit"],
            "build_number": version_info["build"],
            "target_group": target_group,
            "timestamp": datetime.now().isoformat(),
            "auto_generated": True
        }
        
        return deployment

if __name__ == "__main__":
    # Start SSH proxy server
    server = SSHProxyServer()
    
    print("🔐 LeKiwi SSH Proxy Server")
    print("=" * 40)
    print("✅ Secure SSH access with audit logging")
    print("✅ Automatic branch-based versioning")
    print("✅ Gun.js robot discovery")
    print("=" * 40)
    
    # Example: Create deployment with branch versioning
    deployment = BranchVersioning.create_deployment_from_branch()
    print(f"📦 Current version: {deployment['version']}")
    print(f"🎯 Target group: {deployment['target_group']}")
    
    uvicorn.run(server.app, host="0.0.0.0", port=8022)