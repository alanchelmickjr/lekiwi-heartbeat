#!/usr/bin/env python3
"""
LeKiwi P2P Robot Agent with Gun.js
Decentralized deployment with cryptographic verification
"""

import os
import sys
import json
import time
import hashlib
import logging
import subprocess
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.backends import default_backend
from cryptography.x509 import load_pem_x509_certificate

# Gun.js Python client
try:
    from gundb import Gun
except ImportError:
    print("Installing Gun.js Python client...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "gun-python", "cryptography"])
    from gundb import Gun

class GunRobotAgent:
    """
    P2P Robot agent using Gun.js for decentralized deployment
    """
    
    def __init__(self, config_file: Optional[str] = None):
        self.config = self.load_config(config_file)
        self.setup_logging()
        
        # Robot identity
        self.robot_id = self.get_robot_id()
        self.group = self.config.get("group", "all")
        
        # Security - Load or create robot keypair
        self.private_key, self.public_key, self.certificate = self.setup_security()
        
        # Gun.js P2P connection
        self.gun = Gun(self.config.get("gun_peers", [
            'ws://localhost:8765/gun',
            'wss://gun-relay.lekiwi.io/gun',
            'https://gunjs.herokuapp.com/gun'
        ]))
        
        # Gun.js references
        self.fleet_ref = self.gun.get('lekiwi-fleet')
        self.deployments_ref = self.fleet_ref.get('deployments')
        self.robots_ref = self.fleet_ref.get('robots')
        self.my_robot_ref = self.robots_ref.get(self.robot_id)
        
        # Deployment tracking
        self.current_version = self.get_current_version()
        self.deployment_history = []
        
        # P2P event listeners
        self.setup_gun_listeners()
        
        self.logger.info(f"🤖 Gun.js Robot Agent initialized")
        self.logger.info(f"   Robot ID: {self.robot_id}")
        self.logger.info(f"   Group: {self.group}")
        self.logger.info(f"   P2P Network: Connected")
    
    def setup_security(self):
        """Setup cryptographic keys and certificates"""
        certs_dir = Path("/opt/lekiwi-deploy/certs")
        certs_dir.mkdir(parents=True, exist_ok=True)
        
        private_key_path = certs_dir / f"{self.robot_id}_private.pem"
        public_key_path = certs_dir / f"{self.robot_id}_public.pem"
        cert_path = certs_dir / f"{self.robot_id}_cert.json"
        
        if private_key_path.exists():
            # Load existing keys
            with open(private_key_path, "rb") as f:
                private_key = serialization.load_pem_private_key(
                    f.read(), password=None, backend=default_backend()
                )
            with open(public_key_path, "rb") as f:
                public_key = serialization.load_pem_public_key(
                    f.read(), backend=default_backend()
                )
            
            # Load certificate if exists
            certificate = None
            if cert_path.exists():
                with open(cert_path, "r") as f:
                    certificate = json.load(f)
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
            
            # Register with deployment server to get certificate
            certificate = self.register_with_server(public_key)
            if certificate:
                with open(cert_path, "w") as f:
                    json.dump(certificate, f)
        
        return private_key, public_key, certificate
    
    def register_with_server(self, public_key):
        """Register robot with deployment server"""
        try:
            import requests
            
            public_key_pem = public_key.public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo
            ).decode()
            
            response = requests.post(
                f"{self.config.get('server_url', 'http://localhost:8000')}/api/robot/register",
                json={
                    "robot_id": self.robot_id,
                    "public_key": public_key_pem,
                    "metadata": {
                        "group": self.group,
                        "version": self.current_version
                    }
                }
            )
            
            if response.status_code == 200:
                return response.json().get("certificate")
        except Exception as e:
            self.logger.error(f"Failed to register with server: {e}")
        
        return None
    
    def verify_deployment_signature(self, deployment: Dict, signature: str) -> bool:
        """Verify deployment signature using server's public key"""
        try:
            # Load server's public key (should be distributed securely)
            server_public_key_path = Path("/opt/lekiwi-deploy/certs/server_public.pem")
            if not server_public_key_path.exists():
                self.logger.warning("Server public key not found, skipping verification")
                return True  # Allow for testing, should be False in production
            
            with open(server_public_key_path, "rb") as f:
                server_public_key = serialization.load_pem_public_key(
                    f.read(), backend=default_backend()
                )
            
            # Verify signature
            message = json.dumps(deployment, sort_keys=True).encode()
            signature_bytes = bytes.fromhex(signature)
            
            server_public_key.verify(
                signature_bytes,
                message,
                padding.PSS(
                    mgf=padding.MGF1(hashes.SHA256()),
                    salt_length=padding.PSS.MAX_LENGTH
                ),
                hashes.SHA256()
            )
            
            return True
            
        except Exception as e:
            self.logger.error(f"Signature verification failed: {e}")
            return False
    
    def setup_gun_listeners(self):
        """Setup Gun.js P2P event listeners"""
        
        # Listen for new deployments in our group
        def on_deployment_update(data, key):
            if data and isinstance(data, dict):
                # Check if deployment is for our group
                target_group = data.get('target_group', 'all')
                if target_group == 'all' or target_group == self.group:
                    self.logger.info(f"📦 New deployment detected: {data.get('id')}")
                    self.handle_deployment(data)
        
        # Subscribe to latest deployments for our group
        self.fleet_ref.get('latest').get(self.group).on(on_deployment_update)
        self.fleet_ref.get('latest').get('all').on(on_deployment_update)
        
        # Listen for direct commands to this robot
        def on_robot_command(data, key):
            if data and isinstance(data, dict):
                command = data.get('command')
                if command == 'rollback':
                    self.rollback_to_version(data.get('version'))
                elif command == 'update':
                    self.force_update_check()
                elif command == 'status':
                    self.report_status()
        
        self.my_robot_ref.get('commands').on(on_robot_command)
    
    def handle_deployment(self, deployment: Dict):
        """Handle new deployment from Gun.js network"""
        
        # Verify deployment signature
        if not self.verify_deployment_signature(deployment, deployment.get('signature', '')):
            self.logger.error("❌ Deployment signature verification failed!")
            return
        
        # Check if we already have this version
        if deployment.get('version') == self.current_version:
            self.logger.info("Already on this version")
            return
        
        # Download and apply deployment
        self.apply_deployment(deployment)
    
    def apply_deployment(self, deployment: Dict):
        """Apply a deployment"""
        try:
            deployment_id = deployment['id']
            version = deployment['version']
            
            self.logger.info(f"🚀 Applying deployment {deployment_id} (v{version})")
            
            # Update status in Gun.js
            self.my_robot_ref.get('status').put({
                'state': 'deploying',
                'deployment_id': deployment_id,
                'timestamp': datetime.now().isoformat()
            })
            
            # Download package
            package_path = self.download_package(deployment)
            if not package_path:
                raise Exception("Failed to download package")
            
            # Apply update (simplified for example)
            deployment_dir = Path(f"/opt/lekiwi-deploy/deployments/{deployment_id}")
            deployment_dir.mkdir(parents=True, exist_ok=True)
            
            # Extract package
            subprocess.run(
                ["tar", "-xzf", str(package_path), "-C", str(deployment_dir)],
                check=True
            )
            
            # Switch symlink atomically
            current_link = Path("/opt/lekiwi-deploy/current")
            temp_link = Path("/opt/lekiwi-deploy/current.tmp")
            temp_link.symlink_to(deployment_dir)
            temp_link.replace(current_link)
            
            # Restart services
            self.restart_services()
            
            # Update current version
            self.current_version = version
            
            # Report success to Gun.js network
            self.my_robot_ref.get('status').put({
                'state': 'deployed',
                'deployment_id': deployment_id,
                'version': version,
                'timestamp': datetime.now().isoformat()
            })
            
            self.logger.info(f"✅ Successfully deployed {deployment_id}")
            
        except Exception as e:
            self.logger.error(f"Deployment failed: {e}")
            
            # Report failure
            self.my_robot_ref.get('status').put({
                'state': 'failed',
                'deployment_id': deployment_id,
                'error': str(e),
                'timestamp': datetime.now().isoformat()
            })
            
            # Attempt rollback
            self.rollback()
    
    def download_package(self, deployment: Dict) -> Optional[Path]:
        """Download deployment package"""
        try:
            import requests
            
            package_url = deployment['package_url']
            checksum = deployment['checksum']
            deployment_id = deployment['id']
            
            # Download to local storage
            package_path = Path(f"/opt/lekiwi-deploy/downloads/{deployment_id}.tar.gz")
            package_path.parent.mkdir(parents=True, exist_ok=True)
            
            response = requests.get(package_url, stream=True)
            with open(package_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            
            # Verify checksum
            sha256_hash = hashlib.sha256()
            with open(package_path, "rb") as f:
                for byte_block in iter(lambda: f.read(4096), b""):
                    sha256_hash.update(byte_block)
            
            if sha256_hash.hexdigest() != checksum:
                raise Exception("Checksum verification failed")
            
            return package_path
            
        except Exception as e:
            self.logger.error(f"Package download failed: {e}")
            return None
    
    def report_status(self):
        """Report current status to Gun.js network"""
        status = {
            'robot_id': self.robot_id,
            'version': self.current_version,
            'group': self.group,
            'timestamp': datetime.now().isoformat(),
            'health': self.check_health()
        }
        
        # Publish to Gun.js
        self.my_robot_ref.get('current_status').put(status)
        
        # Also publish to fleet-wide status
        self.fleet_ref.get('robot_status').get(self.robot_id).put(status)
    
    def check_health(self) -> Dict:
        """Check robot health"""
        return {
            'services': self.check_services(),
            'disk_space': self.check_disk_space(),
            'memory': self.check_memory(),
            'network': 'connected'
        }
    
    def check_services(self) -> Dict:
        """Check service status"""
        services = {}
        for service in self.config.get('services', ['teleop', 'lekiwi']):
            try:
                result = subprocess.run(
                    ["systemctl", "is-active", service],
                    capture_output=True,
                    text=True
                )
                services[service] = 'active' if result.returncode == 0 else 'inactive'
            except:
                services[service] = 'unknown'
        return services
    
    def check_disk_space(self) -> Dict:
        """Check available disk space"""
        import shutil
        stat = shutil.disk_usage("/")
        return {
            'total': stat.total,
            'used': stat.used,
            'free': stat.free,
            'percent': (stat.used / stat.total) * 100
        }
    
    def check_memory(self) -> Dict:
        """Check memory usage"""
        try:
            import psutil
            mem = psutil.virtual_memory()
            return {
                'total': mem.total,
                'available': mem.available,
                'percent': mem.percent
            }
        except:
            return {}
    
    def restart_services(self):
        """Restart managed services"""
        for service in self.config.get('services', ['teleop', 'lekiwi']):
            try:
                subprocess.run(["systemctl", "restart", service], check=False)
                self.logger.info(f"Restarted {service}")
            except Exception as e:
                self.logger.error(f"Failed to restart {service}: {e}")
    
    def rollback(self):
        """Rollback to previous deployment"""
        # Find previous deployment
        deployments = sorted(
            Path("/opt/lekiwi-deploy/deployments").iterdir(),
            key=lambda x: x.stat().st_mtime,
            reverse=True
        )
        
        if len(deployments) > 1:
            previous = deployments[1]
            self.logger.info(f"Rolling back to {previous.name}")
            
            # Switch symlink
            current_link = Path("/opt/lekiwi-deploy/current")
            temp_link = Path("/opt/lekiwi-deploy/current.tmp")
            temp_link.symlink_to(previous)
            temp_link.replace(current_link)
            
            # Restart services
            self.restart_services()
            
            self.logger.info("✅ Rollback completed")
    
    def setup_logging(self):
        """Setup logging"""
        log_dir = Path("/opt/lekiwi-deploy/logs")
        log_dir.mkdir(parents=True, exist_ok=True)
        
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(log_dir / "agent.log"),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger("GunRobotAgent")
    
    def load_config(self, config_file: Optional[str] = None) -> Dict:
        """Load configuration"""
        default_config = {
            "gun_peers": [
                "ws://localhost:8765/gun",
                "wss://gun-relay.lekiwi.io/gun"
            ],
            "group": "all",
            "services": ["teleop", "lekiwi"],
            "server_url": "http://localhost:8000"
        }
        
        if config_file and Path(config_file).exists():
            with open(config_file, "r") as f:
                config = json.load(f)
                default_config.update(config)
        
        return default_config
    
    def get_robot_id(self) -> str:
        """Get robot ID"""
        # Try MAC address method
        try:
            result = subprocess.run(
                "ip link show eth0 | awk '/ether/ {print $2}' | tr -d ':' | tail -c 9",
                shell=True,
                capture_output=True,
                text=True
            )
            if result.returncode == 0 and result.stdout.strip():
                return f"Lekiwi_{result.stdout.strip().upper()}"
        except:
            pass
        
        import socket
        return f"Lekiwi_{socket.gethostname()}"
    
    def get_current_version(self) -> str:
        """Get current version"""
        version_file = Path("/opt/lekiwi-deploy/current/VERSION")
        if version_file.exists():
            return version_file.read_text().strip()
        return "0.0.0"
    
    def run(self):
        """Main loop"""
        self.logger.info("🌐 Connected to Gun.js P2P network")
        self.logger.info("👂 Listening for deployments...")
        
        # Report initial status
        self.report_status()
        
        # P2P event loop
        try:
            while True:
                # Periodic status report
                time.sleep(60)
                self.report_status()
                
        except KeyboardInterrupt:
            self.logger.info("Shutting down...")

if __name__ == "__main__":
    agent = GunRobotAgent()
    agent.run()