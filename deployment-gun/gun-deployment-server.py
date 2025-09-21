#!/usr/bin/env python3
"""
LeKiwi Gun.js P2P Deployment System
Decentralized deployment coordination using Gun.js
"""

import os
import json
import uuid
import hashlib
import asyncio
import subprocess
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional, List
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.backends import default_backend
from cryptography.x509 import load_pem_x509_certificate
import ssl

from fastapi import FastAPI, HTTPException, WebSocket, Depends, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import jwt
import aiohttp
from pydantic import BaseModel

# Gun.js Python client
try:
    from gundb import Gun
except ImportError:
    print("Installing Gun.js Python client...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "gun-python"])
    from gundb import Gun

class GunDeploymentServer:
    """
    P2P Deployment server using Gun.js for decentralized coordination
    """
    
    def __init__(self):
        # Initialize Gun.js connection
        self.gun = Gun([
            'http://localhost:8765/gun',  # Local Gun relay
            'https://gun-relay.lekiwi.io/gun',  # Cloud Gun relay
            'https://gunjs.herokuapp.com/gun'  # Public Gun relay (backup)
        ])
        
        # Certificate management
        self.certs_dir = Path("/opt/lekiwi-deploy/certs")
        self.certs_dir.mkdir(parents=True, exist_ok=True)
        
        # Initialize or load server keypair
        self.private_key, self.public_key = self.load_or_create_keypair()
        
        # Gun.js references
        self.fleet_ref = self.gun.get('lekiwi-fleet')
        self.deployments_ref = self.fleet_ref.get('deployments')
        self.robots_ref = self.fleet_ref.get('robots')
        self.certs_ref = self.fleet_ref.get('certificates')
        
        # FastAPI app
        self.app = FastAPI(title="LeKiwi Gun.js Deployment Server")
        self.setup_routes()
        
        # Security
        self.security = HTTPBearer()
        
    def load_or_create_keypair(self):
        """Load existing keypair or create new one"""
        private_key_path = self.certs_dir / "server_private.pem"
        public_key_path = self.certs_dir / "server_public.pem"
        
        if private_key_path.exists() and public_key_path.exists():
            # Load existing keys
            with open(private_key_path, "rb") as f:
                private_key = serialization.load_pem_private_key(
                    f.read(), password=None, backend=default_backend()
                )
            with open(public_key_path, "rb") as f:
                public_key = serialization.load_pem_public_key(
                    f.read(), backend=default_backend()
                )
        else:
            # Generate new keypair
            private_key = rsa.generate_private_key(
                public_exponent=65537,
                key_size=2048,
                backend=default_backend()
            )
            public_key = private_key.public_key()
            
            # Save keys
            with open(private_key_path, "wb") as f:
                f.write(private_key.private_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PrivateFormat.PKCS8,
                    encryption_algorithm=serialization.NoEncryption()
                ))
            
            with open(public_key_path, "wb") as f:
                f.write(public_key.public_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PublicFormat.SubjectPublicKeyInfo
                ))
        
        return private_key, public_key
    
    def sign_deployment(self, deployment_data: Dict) -> str:
        """Sign deployment package with server private key"""
        message = json.dumps(deployment_data, sort_keys=True).encode()
        signature = self.private_key.sign(
            message,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.MAX_LENGTH
            ),
            hashes.SHA256()
        )
        return signature.hex()
    
    async def create_deployment(self, deployment_info: Dict):
        """Create and publish deployment via Gun.js"""
        deployment_id = f"dep_{uuid.uuid4().hex[:12]}"
        
        # Sign the deployment
        signature = self.sign_deployment(deployment_info)
        
        # Create deployment record
        deployment_record = {
            'id': deployment_id,
            'version': deployment_info['version'],
            'timestamp': datetime.now().isoformat(),
            'signature': signature,
            'package_url': deployment_info['package_url'],
            'checksum': deployment_info['checksum'],
            'author': deployment_info.get('author', 'unknown'),
            'message': deployment_info.get('message', ''),
            'target_group': deployment_info.get('target_group', 'all')
        }
        
        # Publish to Gun.js network
        self.deployments_ref.get(deployment_id).put(deployment_record)
        
        # Also publish as "latest" for the target group
        self.fleet_ref.get('latest').get(deployment_info['target_group']).put(deployment_record)
        
        return deployment_id
    
    async def register_robot(self, robot_id: str, public_key: str, metadata: Dict):
        """Register a new robot with its public key"""
        robot_record = {
            'id': robot_id,
            'public_key': public_key,
            'registered_at': datetime.now().isoformat(),
            'metadata': metadata,
            'status': 'active'
        }
        
        # Store in Gun.js
        self.robots_ref.get(robot_id).put(robot_record)
        
        # Generate robot certificate
        cert = self.generate_robot_certificate(robot_id, public_key)
        self.certs_ref.get(robot_id).put(cert)
        
        return cert
    
    def generate_robot_certificate(self, robot_id: str, public_key: str) -> Dict:
        """Generate a certificate for robot authentication"""
        cert_data = {
            'robot_id': robot_id,
            'public_key': public_key,
            'issued_at': datetime.now().isoformat(),
            'expires_at': (datetime.now() + timedelta(days=365)).isoformat(),
            'issuer': 'lekiwi-deployment-server'
        }
        
        # Sign the certificate
        signature = self.sign_deployment(cert_data)
        cert_data['signature'] = signature
        
        return cert_data
    
    async def revoke_robot(self, robot_id: str):
        """Revoke a robot's access"""
        # Mark robot as revoked in Gun.js
        self.robots_ref.get(robot_id).get('status').put('revoked')
        self.robots_ref.get(robot_id).get('revoked_at').put(datetime.now().isoformat())
        
        # Add to revocation list
        self.fleet_ref.get('revoked').get(robot_id).put(True)
    
    def setup_routes(self):
        """Setup FastAPI routes"""
        
        @self.app.post("/api/deploy")
        async def deploy(deployment: Dict, credentials: HTTPAuthorizationCredentials = Security(self.security)):
            """Create new deployment"""
            # Verify JWT token
            try:
                payload = jwt.decode(credentials.credentials, self.public_key, algorithms=["RS256"])
            except jwt.InvalidTokenError:
                raise HTTPException(status_code=401, detail="Invalid token")
            
            deployment_id = await self.create_deployment(deployment)
            return {"deployment_id": deployment_id, "status": "published"}
        
        @self.app.post("/api/robot/register")
        async def register_robot(robot_id: str, public_key: str, metadata: Dict = {}):
            """Register new robot"""
            cert = await self.register_robot(robot_id, public_key, metadata)
            return {"status": "registered", "certificate": cert}
        
        @self.app.delete("/api/robot/{robot_id}")
        async def remove_robot(robot_id: str, credentials: HTTPAuthorizationCredentials = Security(self.security)):
            """Remove/revoke robot"""
            await self.revoke_robot(robot_id)
            return {"status": "revoked"}
        
        @self.app.websocket("/ws/gun")
        async def gun_websocket(websocket: WebSocket):
            """WebSocket relay for Gun.js P2P network"""
            await websocket.accept()
            
            # Bridge WebSocket to Gun.js network
            try:
                while True:
                    data = await websocket.receive_text()
                    # Forward to Gun network
                    # This would integrate with Gun.js WebSocket handling
                    await websocket.send_text(data)
            except:
                await websocket.close()

# Gun.js configuration for P2P network
GUN_CONFIG = {
    "peers": [
        "http://localhost:8765/gun",
        "wss://gun-relay.lekiwi.io/gun",
        "https://gunjs.herokuapp.com/gun"
    ],
    "localStorage": False,
    "radisk": True,
    "multicast": {
        "address": "233.255.255.255",
        "port": 8765
    }
}

# Create Gun.js relay server
def create_gun_relay():
    """Create local Gun.js relay server"""
    gun_relay_code = """
const Gun = require('gun');
const http = require('http');
const express = require('express');

const app = express();
const server = http.createServer(app);

// Gun.js configuration
const gun = Gun({
    web: server,
    peers: %s,
    localStorage: false,
    radisk: true
});

// Serve Gun.js
app.use(Gun.serve);

// Start server
const PORT = process.env.GUN_PORT || 8765;
server.listen(PORT, () => {
    console.log('Gun.js relay server running on port ' + PORT);
});
""" % json.dumps(GUN_CONFIG["peers"])
    
    relay_file = Path("/opt/lekiwi-deploy/gun-relay.js")
    relay_file.write_text(gun_relay_code)
    
    # Install Gun.js if needed
    subprocess.run(["npm", "install", "gun", "express"], cwd="/opt/lekiwi-deploy")
    
    return relay_file

if __name__ == "__main__":
    # Create Gun relay
    relay_file = create_gun_relay()
    
    # Start Gun relay in background
    subprocess.Popen(["node", str(relay_file)])
    
    # Start deployment server
    server = GunDeploymentServer()
    uvicorn.run(server.app, host="0.0.0.0", port=8000)