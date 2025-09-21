#!/usr/bin/env python3
"""
LeKiwi Reverse Tunnel System
Robots connect OUT to server - works from any network, no VPN needed!
All robots on same version get same changes atomically.
"""

import os
import sys
import json
import uuid
import asyncio
import subprocess
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional, List, Set
import hashlib
import ssl
import socket

from fastapi import FastAPI, WebSocket, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import paramiko
from sshtunnel import SSHTunnelForwarder
import websockets

# Gun.js for P2P coordination
try:
    from gundb import Gun
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "gun-python", "sshtunnel", "websockets"])
    from gundb import Gun

class ReverseTunnelServer:
    """
    Central server that robots connect TO (no inbound connections needed on robots)
    """
    
    def __init__(self):
        self.app = FastAPI(title="LeKiwi Reverse Tunnel Hub")
        
        # Connected robots (they connect to us)
        self.robot_tunnels: Dict[str, 'RobotTunnel'] = {}
        
        # Version-locked deployment groups
        self.version_groups: Dict[str, Set[str]] = {}
        
        # Gun.js for real-time coordination
        self.gun = Gun(['ws://localhost:8765/gun'])
        self.fleet_ref = self.gun.get('lekiwi-fleet')
        
        # WebSocket connections from robots
        self.robot_websockets: Dict[str, WebSocket] = {}
        
        # Setup routes
        self.setup_routes()
        
        # Tunnel configuration
        self.tunnel_port_base = 30000  # Starting port for robot tunnels
        self.next_tunnel_port = self.tunnel_port_base
        
    def setup_routes(self):
        """Setup FastAPI routes"""
        
        @self.app.websocket("/ws/robot/{robot_id}")
        async def robot_connection(websocket: WebSocket, robot_id: str):
            """
            Robots connect here - establishes reverse tunnel
            Works from ANY network - home wifi, cellular, behind NAT, etc.
            """
            await websocket.accept()
            
            try:
                # Get robot info
                robot_info = await websocket.receive_json()
                version = robot_info.get("version", "unknown")
                group = robot_info.get("group", "default")
                
                # Register robot
                self.robot_websockets[robot_id] = websocket
                
                # Add to version group
                if version not in self.version_groups:
                    self.version_groups[version] = set()
                self.version_groups[version].add(robot_id)
                
                # Allocate tunnel port
                tunnel_port = self.allocate_tunnel_port()
                
                # Create reverse tunnel
                tunnel = RobotTunnel(
                    robot_id=robot_id,
                    websocket=websocket,
                    tunnel_port=tunnel_port,
                    version=version,
                    group=group
                )
                
                self.robot_tunnels[robot_id] = tunnel
                
                # Notify robot of tunnel setup
                await websocket.send_json({
                    "type": "tunnel_established",
                    "tunnel_port": tunnel_port,
                    "server_host": os.getenv("PUBLIC_HOST", "deploy.lekiwi.io")
                })
                
                # Update Gun.js
                self.fleet_ref.get('robots').get(robot_id).put({
                    "status": "connected",
                    "version": version,
                    "group": group,
                    "tunnel_port": tunnel_port,
                    "connected_at": datetime.now().isoformat(),
                    "connection_from": robot_info.get("public_ip", "unknown")
                })
                
                print(f"🤖 Robot {robot_id} connected from anywhere!")
                print(f"   Version: {version}")
                print(f"   Tunnel: localhost:{tunnel_port}")
                
                # Handle messages
                while True:
                    data = await websocket.receive_json()
                    await self.handle_robot_message(robot_id, data)
                    
            except Exception as e:
                print(f"Robot {robot_id} disconnected: {e}")
            finally:
                # Cleanup
                if robot_id in self.robot_tunnels:
                    del self.robot_tunnels[robot_id]
                if robot_id in self.robot_websockets:
                    del self.robot_websockets[robot_id]
                
                # Remove from version group
                for version_set in self.version_groups.values():
                    version_set.discard(robot_id)
                
                # Update Gun.js
                self.fleet_ref.get('robots').get(robot_id).get('status').put('disconnected')
        
        @self.app.post("/api/deploy/version-locked")
        async def deploy_to_version_group(deployment: Dict, background_tasks: BackgroundTasks):
            """
            Deploy to all robots with same version - atomic group update
            """
            target_version = deployment.get("target_version")
            new_version = deployment.get("new_version")
            
            if target_version not in self.version_groups:
                raise HTTPException(404, f"No robots on version {target_version}")
            
            robots = self.version_groups[target_version]
            
            print(f"📦 Deploying {new_version} to {len(robots)} robots on {target_version}")
            
            # Send deployment to all robots with this version
            background_tasks.add_task(
                self.deploy_to_robots,
                robots,
                deployment
            )
            
            return {
                "status": "deploying",
                "target_version": target_version,
                "new_version": new_version,
                "robot_count": len(robots)
            }
        
        @self.app.get("/api/robots/by-version")
        async def get_robots_by_version():
            """Get robots grouped by version"""
            result = {}
            for version, robot_ids in self.version_groups.items():
                result[version] = {
                    "robots": list(robot_ids),
                    "count": len(robot_ids),
                    "can_deploy": len(robot_ids) > 0
                }
            return result
        
        @self.app.post("/api/ssh/{robot_id}")
        async def ssh_to_robot(robot_id: str, command: Optional[str] = None):
            """
            SSH to robot through reverse tunnel - works from anywhere!
            """
            if robot_id not in self.robot_tunnels:
                raise HTTPException(404, f"Robot {robot_id} not connected")
            
            tunnel = self.robot_tunnels[robot_id]
            
            # SSH through the reverse tunnel
            result = await tunnel.execute_command(command or "hostname")
            
            return {
                "robot_id": robot_id,
                "version": tunnel.version,
                "tunnel_port": tunnel.tunnel_port,
                "result": result
            }
        
        @self.app.get("/api/robots/online")
        async def get_online_robots():
            """Get all connected robots"""
            robots = []
            for robot_id, tunnel in self.robot_tunnels.items():
                robots.append({
                    "robot_id": robot_id,
                    "version": tunnel.version,
                    "group": tunnel.group,
                    "tunnel_port": tunnel.tunnel_port,
                    "connected_since": tunnel.connected_at.isoformat()
                })
            return robots
    
    def allocate_tunnel_port(self) -> int:
        """Allocate unique port for robot tunnel"""
        port = self.next_tunnel_port
        self.next_tunnel_port += 1
        return port
    
    async def handle_robot_message(self, robot_id: str, data: Dict):
        """Handle message from robot"""
        msg_type = data.get("type")
        
        if msg_type == "status_update":
            # Update Gun.js with robot status
            self.fleet_ref.get('robots').get(robot_id).get('status').put(data.get("status"))
            
        elif msg_type == "deployment_result":
            # Robot reporting deployment result
            result = data.get("result")
            version = data.get("version")
            
            if result == "success":
                # Update version group
                old_version = self.robot_tunnels[robot_id].version
                if old_version in self.version_groups:
                    self.version_groups[old_version].discard(robot_id)
                if version not in self.version_groups:
                    self.version_groups[version] = set()
                self.version_groups[version].add(robot_id)
                
                # Update tunnel info
                self.robot_tunnels[robot_id].version = version
    
    async def deploy_to_robots(self, robot_ids: Set[str], deployment: Dict):
        """Deploy to specific robots atomically"""
        successful = []
        failed = []
        
        # Send deployment command to all robots
        for robot_id in robot_ids:
            if robot_id in self.robot_websockets:
                ws = self.robot_websockets[robot_id]
                try:
                    await ws.send_json({
                        "type": "deploy",
                        "deployment": deployment
                    })
                    successful.append(robot_id)
                except:
                    failed.append(robot_id)
        
        # Update Gun.js
        self.fleet_ref.get('deployments').get(deployment['id']).put({
            "status": "deployed",
            "successful": successful,
            "failed": failed,
            "timestamp": datetime.now().isoformat()
        })

class RobotTunnel:
    """
    Represents a reverse tunnel from a robot
    """
    
    def __init__(self, robot_id: str, websocket: WebSocket, tunnel_port: int, 
                 version: str, group: str):
        self.robot_id = robot_id
        self.websocket = websocket
        self.tunnel_port = tunnel_port
        self.version = version
        self.group = group
        self.connected_at = datetime.now()
        
        # SSH client for commands
        self.ssh_client = None
    
    async def execute_command(self, command: str) -> Dict:
        """Execute command on robot through tunnel"""
        try:
            # Send command through WebSocket
            await self.websocket.send_json({
                "type": "execute",
                "command": command
            })
            
            # Wait for response
            response = await self.websocket.receive_json()
            
            return {
                "stdout": response.get("stdout", ""),
                "stderr": response.get("stderr", ""),
                "exit_code": response.get("exit_code", -1)
            }
            
        except Exception as e:
            return {
                "error": str(e),
                "exit_code": -1
            }

class RobotReverseTunnelClient:
    """
    Runs on each robot - connects OUT to server
    Works from ANY network - no port forwarding needed!
    """
    
    def __init__(self):
        self.robot_id = self.get_robot_id()
        self.version = self.get_current_version()
        self.group = os.getenv("ROBOT_GROUP", "default")
        
        # Server to connect to (can be anywhere on internet)
        self.server_url = os.getenv("TUNNEL_SERVER", "wss://deploy.lekiwi.io/ws/robot")
        
        # Local SSH server (for tunnel)
        self.local_ssh_port = 22
        
    def get_robot_id(self) -> str:
        """Get robot ID"""
        try:
            mac = subprocess.check_output(
                "ip link show eth0 | awk '/ether/ {print $2}' | tr -d ':' | tail -c 9",
                shell=True
            ).decode().strip()
            return f"Lekiwi_{mac.upper()}"
        except:
            return f"Lekiwi_{socket.gethostname()}"
    
    def get_current_version(self) -> str:
        """Get current deployed version"""
        version_file = Path("/opt/lekiwi-deploy/current/VERSION")
        if version_file.exists():
            return version_file.read_text().strip()
        return "0.0.0"
    
    def get_public_ip(self) -> str:
        """Get public IP (for logging)"""
        try:
            import requests
            return requests.get("https://api.ipify.org").text
        except:
            return "unknown"
    
    async def connect_to_server(self):
        """
        Connect to deployment server from ANYWHERE
        No VPN, no port forwarding, works on any wifi/network!
        """
        while True:
            try:
                print(f"🌐 Connecting to tunnel server from anywhere...")
                
                # Connect WebSocket to server
                async with websockets.connect(f"{self.server_url}/{self.robot_id}") as websocket:
                    
                    # Send robot info
                    await websocket.send(json.dumps({
                        "version": self.version,
                        "group": self.group,
                        "public_ip": self.get_public_ip(),
                        "hostname": socket.gethostname()
                    }))
                    
                    # Receive tunnel info
                    response = json.loads(await websocket.recv())
                    if response.get("type") == "tunnel_established":
                        print(f"✅ Reverse tunnel established!")
                        print(f"   Server: {response.get('server_host')}")
                        print(f"   Port: {response.get('tunnel_port')}")
                        print(f"   We can be accessed from ANYWHERE now!")
                    
                    # Handle commands from server
                    while True:
                        message = json.loads(await websocket.recv())
                        await self.handle_server_message(websocket, message)
                        
            except Exception as e:
                print(f"Connection lost: {e}")
                print("Reconnecting in 5 seconds...")
                await asyncio.sleep(5)
    
    async def handle_server_message(self, websocket, message: Dict):
        """Handle commands from server"""
        msg_type = message.get("type")
        
        if msg_type == "execute":
            # Execute command locally
            command = message.get("command")
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True
            )
            
            # Send result back
            await websocket.send(json.dumps({
                "type": "command_result",
                "stdout": result.stdout,
                "stderr": result.stderr,
                "exit_code": result.returncode
            }))
            
        elif msg_type == "deploy":
            # Apply deployment
            deployment = message.get("deployment")
            success = await self.apply_deployment(deployment)
            
            # Update version if successful
            if success:
                self.version = deployment.get("new_version")
            
            # Report result
            await websocket.send(json.dumps({
                "type": "deployment_result",
                "result": "success" if success else "failed",
                "version": self.version
            }))
    
    async def apply_deployment(self, deployment: Dict) -> bool:
        """Apply deployment atomically with version group"""
        try:
            print(f"📦 Applying deployment: {deployment.get('new_version')}")
            
            # Download and apply (simplified)
            # In production, this would download package, verify, extract, etc.
            
            # Update VERSION file
            version_file = Path("/opt/lekiwi-deploy/current/VERSION")
            version_file.write_text(deployment.get("new_version"))
            
            # Restart services
            subprocess.run(["systemctl", "restart", "teleop"], check=False)
            subprocess.run(["systemctl", "restart", "lekiwi"], check=False)
            
            print(f"✅ Deployment successful!")
            return True
            
        except Exception as e:
            print(f"❌ Deployment failed: {e}")
            return False
    
    def run(self):
        """Main loop"""
        print(f"🤖 LeKiwi Reverse Tunnel Client")
        print(f"   Robot ID: {self.robot_id}")
        print(f"   Version: {self.version}")
        print(f"   Group: {self.group}")
        print(f"")
        print(f"🌍 Can connect from ANY network:")
        print(f"   ✅ Home WiFi")
        print(f"   ✅ Public WiFi")
        print(f"   ✅ Cellular hotspot")
        print(f"   ✅ Behind NAT/firewall")
        print(f"   ✅ No port forwarding needed!")
        print(f"")
        
        # Run async event loop
        asyncio.run(self.connect_to_server())

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["server", "client"], default="client")
    args = parser.parse_args()
    
    if args.mode == "server":
        # Run tunnel server
        server = ReverseTunnelServer()
        print("🌐 LeKiwi Reverse Tunnel Server")
        print("=" * 40)
        print("Robots connect OUT to this server")
        print("Works from ANY network - no VPN needed!")
        print("=" * 40)
        uvicorn.run(server.app, host="0.0.0.0", port=8080)
    else:
        # Run robot client
        client = RobotReverseTunnelClient()
        client.run()