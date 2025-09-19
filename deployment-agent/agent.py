#!/usr/bin/env python3
"""
LeKiwi Deploy Agent - Runs on each robot for automatic deployments
No more manual SSH updates! Just git push and robots update automatically.
"""

import os
import sys
import json
import time
import shutil
import hashlib
import logging
import tarfile
import subprocess
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional, List
import signal

try:
    import requests
except ImportError:
    print("Installing requests library...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "requests"])
    import requests

class LeKiwiDeployAgent:
    """
    Deployment agent that runs on each robot.
    - Polls for updates from deployment server
    - Downloads and applies updates atomically
    - Maintains deployment history for instant rollback
    - Reports status back to server
    """
    
    def __init__(self, config_file: Optional[str] = None):
        """Initialize the deployment agent"""
        self.config = self.load_config(config_file)
        self.setup_logging()
        self.setup_directories()
        
        # Robot identification
        self.robot_id = self.get_robot_id()
        self.robot_group = self.config.get("group", "all")
        
        # Deployment paths
        self.base_dir = Path(self.config.get("base_dir", "/opt/lekiwi-deploy"))
        self.deployments_dir = self.base_dir / "deployments"
        self.current_link = self.base_dir / "current"
        self.downloads_dir = self.base_dir / "downloads"
        
        # Server configuration
        self.server_url = self.config.get("server_url", "http://localhost:8000")
        self.check_interval = self.config.get("check_interval", 30)
        self.max_deployments = self.config.get("max_deployments", 10)
        
        # Services to manage
        self.services = self.config.get("services", ["teleop", "lekiwi"])
        
        # State
        self.running = True
        self.current_version = self.get_current_version()
        
        # Setup signal handlers
        signal.signal(signal.SIGTERM, self.handle_shutdown)
        signal.signal(signal.SIGINT, self.handle_shutdown)
        
        self.logger.info(f"🤖 LeKiwi Deploy Agent initialized")
        self.logger.info(f"   Robot ID: {self.robot_id}")
        self.logger.info(f"   Group: {self.robot_group}")
        self.logger.info(f"   Current Version: {self.current_version}")
        self.logger.info(f"   Server: {self.server_url}")
    
    def load_config(self, config_file: Optional[str] = None) -> Dict:
        """Load configuration from file or environment"""
        config = {
            "server_url": os.getenv("DEPLOY_SERVER_URL", "http://localhost:8000"),
            "group": os.getenv("ROBOT_GROUP", "all"),
            "check_interval": int(os.getenv("CHECK_INTERVAL", "30")),
            "max_deployments": int(os.getenv("MAX_DEPLOYMENTS", "10")),
            "base_dir": os.getenv("DEPLOY_BASE_DIR", "/opt/lekiwi-deploy"),
            "services": os.getenv("SERVICES", "teleop,lekiwi").split(","),
            "auto_deploy": os.getenv("AUTO_DEPLOY", "true").lower() == "true",
            "health_check_timeout": int(os.getenv("HEALTH_CHECK_TIMEOUT", "30"))
        }
        
        # Load from config file if provided
        if config_file and Path(config_file).exists():
            with open(config_file, "r") as f:
                file_config = json.load(f)
                config.update(file_config)
        
        return config
    
    def setup_logging(self):
        """Configure logging"""
        log_dir = Path(self.config["base_dir"]) / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(log_dir / "agent.log"),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger("DeployAgent")
    
    def setup_directories(self):
        """Create necessary directories"""
        base_dir = Path(self.config["base_dir"])
        for subdir in ["deployments", "downloads", "logs", "backups"]:
            (base_dir / subdir).mkdir(parents=True, exist_ok=True)
    
    def get_robot_id(self) -> str:
        """Get unique robot identifier"""
        # Try to get from environment first
        if robot_id := os.getenv("ROBOT_ID"):
            return robot_id
        
        # Try to get from MAC address (same as existing system)
        try:
            result = subprocess.run(
                "ip link show eth0 | awk '/ether/ {print $2}' | tr -d ':' | tail -c 9",
                shell=True,
                capture_output=True,
                text=True
            )
            if result.returncode == 0 and result.stdout.strip():
                mac = result.stdout.strip()
                return f"Lekiwi_{mac.upper()}"
        except Exception as e:
            self.logger.warning(f"Could not get MAC address: {e}")
        
        # Fallback to hostname
        import socket
        return f"Lekiwi_{socket.gethostname()}"
    
    def get_current_version(self) -> str:
        """Get currently deployed version"""
        if self.current_link.exists() and self.current_link.is_symlink():
            version_file = self.current_link / "VERSION"
            if version_file.exists():
                return version_file.read_text().strip()
        return "0.0.0"
    
    def get_deployment_metadata(self, deployment_path: Path) -> Optional[Dict]:
        """Get metadata for a deployment"""
        metadata_file = deployment_path / "DEPLOYMENT.json"
        if metadata_file.exists():
            with open(metadata_file, "r") as f:
                return json.load(f)
        return None
    
    def check_for_updates(self) -> Optional[Dict]:
        """Check deployment server for updates"""
        try:
            response = requests.get(
                f"{self.server_url}/api/check-update",
                params={
                    "robot_id": self.robot_id,
                    "current_version": self.current_version,
                    "group": self.robot_group
                },
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                if data.get("update_available"):
                    self.logger.info(f"🆕 Update available: {data.get('version')}")
                    return data
            
            return None
            
        except requests.RequestException as e:
            self.logger.error(f"Failed to check for updates: {e}")
            return None
        except Exception as e:
            self.logger.error(f"Unexpected error checking updates: {e}")
            return None
    
    def download_package(self, update_info: Dict) -> Optional[Path]:
        """Download deployment package"""
        try:
            deployment_id = update_info["deployment_id"]
            package_file = self.downloads_dir / f"{deployment_id}.tar.gz"
            
            # Skip if already downloaded
            if package_file.exists():
                if self.verify_checksum(package_file, update_info["checksum"]):
                    self.logger.info(f"📦 Package already downloaded: {deployment_id}")
                    return package_file
                else:
                    package_file.unlink()
            
            self.logger.info(f"📥 Downloading package {deployment_id}...")
            
            # Report status
            self.report_status("downloading", deployment_id, update_info.get("version"))
            
            # Download with progress
            response = requests.get(
                f"{self.server_url}{update_info['download_url']}",
                stream=True,
                timeout=60
            )
            response.raise_for_status()
            
            total_size = int(response.headers.get('content-length', 0))
            downloaded = 0
            
            with open(package_file, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total_size > 0:
                            progress = (downloaded / total_size) * 100
                            if progress % 10 < 0.1:  # Log every 10%
                                self.logger.info(f"   Progress: {progress:.0f}%")
            
            # Verify checksum
            if not self.verify_checksum(package_file, update_info["checksum"]):
                self.logger.error("❌ Checksum verification failed!")
                package_file.unlink()
                return None
            
            self.logger.info(f"✅ Package downloaded successfully")
            return package_file
            
        except Exception as e:
            self.logger.error(f"Download failed: {e}")
            self.report_status("failed", deployment_id, message=f"Download failed: {e}")
            return None
    
    def verify_checksum(self, file_path: Path, expected_checksum: str) -> bool:
        """Verify file checksum"""
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        
        actual = sha256_hash.hexdigest()
        return actual == expected_checksum
    
    def extract_package(self, package_file: Path, deployment_id: str) -> Optional[Path]:
        """Extract deployment package"""
        try:
            deployment_path = self.deployments_dir / deployment_id
            
            if deployment_path.exists():
                self.logger.info(f"Deployment {deployment_id} already extracted")
                return deployment_path
            
            self.logger.info(f"📂 Extracting package to {deployment_path}")
            deployment_path.mkdir(parents=True, exist_ok=True)
            
            with tarfile.open(package_file, 'r:gz') as tar:
                tar.extractall(deployment_path)
            
            return deployment_path
            
        except Exception as e:
            self.logger.error(f"Extraction failed: {e}")
            if deployment_path.exists():
                shutil.rmtree(deployment_path)
            return None
    
    def stop_services(self):
        """Stop managed services"""
        for service in self.services:
            try:
                self.logger.info(f"🛑 Stopping service: {service}")
                subprocess.run(
                    ["systemctl", "stop", service],
                    check=False,
                    timeout=30
                )
            except Exception as e:
                self.logger.warning(f"Failed to stop {service}: {e}")
    
    def start_services(self):
        """Start managed services"""
        for service in self.services:
            try:
                self.logger.info(f"▶️  Starting service: {service}")
                subprocess.run(
                    ["systemctl", "start", service],
                    check=False,
                    timeout=30
                )
            except Exception as e:
                self.logger.warning(f"Failed to start {service}: {e}")
    
    def switch_deployment(self, deployment_path: Path) -> bool:
        """Atomically switch to new deployment"""
        try:
            self.logger.info(f"🔄 Switching to deployment: {deployment_path.name}")
            
            # Create temporary symlink
            temp_link = self.base_dir / "current.tmp"
            if temp_link.exists():
                temp_link.unlink()
            
            temp_link.symlink_to(deployment_path)
            
            # Atomic rename
            temp_link.replace(self.current_link)
            
            self.logger.info("✅ Deployment switched successfully")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to switch deployment: {e}")
            return False
    
    def run_health_checks(self) -> bool:
        """Run post-deployment health checks"""
        self.logger.info("🏥 Running health checks...")
        
        # Wait for services to stabilize
        time.sleep(5)
        
        # Check if services are running
        all_healthy = True
        for service in self.services:
            try:
                result = subprocess.run(
                    ["systemctl", "is-active", service],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                if result.returncode != 0:
                    self.logger.error(f"❌ Service {service} is not active")
                    all_healthy = False
                else:
                    self.logger.info(f"✅ Service {service} is active")
            except Exception as e:
                self.logger.error(f"Failed to check {service}: {e}")
                all_healthy = False
        
        # Check for custom health endpoint
        try:
            response = requests.get(
                "http://localhost:8080/health",
                timeout=5
            )
            if response.status_code == 200:
                self.logger.info("✅ Health endpoint responding")
            else:
                self.logger.warning(f"Health endpoint returned {response.status_code}")
        except:
            pass  # Health endpoint is optional
        
        return all_healthy
    
    def rollback(self) -> bool:
        """Rollback to previous deployment"""
        try:
            self.logger.warning("🔙 Initiating rollback...")
            
            # Find previous deployment
            deployments = sorted(
                [d for d in self.deployments_dir.iterdir() if d.is_dir()],
                key=lambda x: x.stat().st_mtime,
                reverse=True
            )
            
            current_target = self.current_link.resolve() if self.current_link.exists() else None
            previous = None
            
            for dep in deployments:
                if dep != current_target and previous is None:
                    previous = dep
                    break
            
            if not previous:
                self.logger.error("No previous deployment available for rollback")
                return False
            
            self.logger.info(f"Rolling back to: {previous.name}")
            
            # Stop services
            self.stop_services()
            
            # Switch deployment
            if not self.switch_deployment(previous):
                return False
            
            # Start services
            self.start_services()
            
            # Update version
            self.current_version = self.get_current_version()
            
            self.logger.info("✅ Rollback completed successfully")
            return True
            
        except Exception as e:
            self.logger.error(f"Rollback failed: {e}")
            return False
    
    def deploy(self, update_info: Dict) -> bool:
        """Deploy an update"""
        deployment_id = update_info["deployment_id"]
        version = update_info.get("version", "unknown")
        
        try:
            self.logger.info(f"🚀 Starting deployment: {deployment_id} (v{version})")
            self.report_status("deploying", deployment_id, version)
            
            # Download package
            package_file = self.download_package(update_info)
            if not package_file:
                return False
            
            # Extract package
            deployment_path = self.extract_package(package_file, deployment_id)
            if not deployment_path:
                return False
            
            # Stop services
            self.stop_services()
            
            # Switch deployment
            if not self.switch_deployment(deployment_path):
                self.start_services()  # Restart with old deployment
                return False
            
            # Start services with new deployment
            self.start_services()
            
            # Run health checks
            if not self.run_health_checks():
                if update_info.get("auto_rollback", True):
                    self.logger.warning("Health checks failed, rolling back...")
                    self.rollback()
                    self.report_status("failed", deployment_id, version, "Health checks failed, rolled back")
                    return False
            
            # Update current version
            self.current_version = version
            
            # Clean up old deployments
            self.cleanup_old_deployments()
            
            self.logger.info(f"✅ Deployment successful: {deployment_id} (v{version})")
            self.report_status("success", deployment_id, version)
            return True
            
        except Exception as e:
            self.logger.error(f"Deployment failed: {e}")
            self.report_status("failed", deployment_id, version, str(e))
            
            # Attempt rollback
            if update_info.get("auto_rollback", True):
                self.rollback()
            
            return False
    
    def cleanup_old_deployments(self):
        """Remove old deployments, keeping the most recent ones"""
        try:
            deployments = sorted(
                [d for d in self.deployments_dir.iterdir() if d.is_dir()],
                key=lambda x: x.stat().st_mtime,
                reverse=True
            )
            
            current_target = self.current_link.resolve() if self.current_link.exists() else None
            
            kept = 0
            for dep in deployments:
                if dep == current_target:
                    continue  # Never delete current
                
                if kept < self.max_deployments:
                    kept += 1
                else:
                    self.logger.info(f"🗑️  Removing old deployment: {dep.name}")
                    shutil.rmtree(dep)
            
        except Exception as e:
            self.logger.warning(f"Cleanup failed: {e}")
    
    def report_status(self, status: str, deployment_id: Optional[str] = None, 
                     version: Optional[str] = None, message: Optional[str] = None):
        """Report status to deployment server"""
        try:
            data = {
                "robot_id": self.robot_id,
                "deployment_id": deployment_id,
                "version": version or self.current_version,
                "status": status,
                "message": message,
                "health": {
                    "services": {service: self.check_service_status(service) for service in self.services},
                    "timestamp": datetime.now().isoformat()
                }
            }
            
            requests.post(
                f"{self.server_url}/api/robot/status",
                json=data,
                timeout=5
            )
        except Exception as e:
            self.logger.warning(f"Failed to report status: {e}")
    
    def check_service_status(self, service: str) -> str:
        """Check if a service is running"""
        try:
            result = subprocess.run(
                ["systemctl", "is-active", service],
                capture_output=True,
                text=True,
                timeout=2
            )
            return "active" if result.returncode == 0 else "inactive"
        except:
            return "unknown"
    
    def handle_shutdown(self, signum, frame):
        """Handle shutdown signals"""
        self.logger.info("Shutdown signal received, stopping agent...")
        self.running = False
    
    def run(self):
        """Main agent loop"""
        self.logger.info("=" * 60)
        self.logger.info("🚀 LeKiwi Deploy Agent Started")
        self.logger.info("=" * 60)
        
        # Report initial status
        self.report_status("idle")
        
        while self.running:
            try:
                # Check for updates
                update = self.check_for_updates()
                
                if update and self.config.get("auto_deploy", True):
                    # Deploy the update
                    self.deploy(update)
                elif update:
                    self.logger.info(f"Update available but auto-deploy is disabled: {update.get('version')}")
                
                # Wait before next check
                time.sleep(self.check_interval)
                
            except KeyboardInterrupt:
                self.logger.info("Interrupted by user")
                break
            except Exception as e:
                self.logger.error(f"Unexpected error in main loop: {e}")
                time.sleep(60)  # Wait longer on error
        
        self.logger.info("Agent stopped")

def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description="LeKiwi Deploy Agent")
    parser.add_argument("--config", help="Path to config file")
    parser.add_argument("--server", help="Deployment server URL")
    parser.add_argument("--group", help="Robot group")
    parser.add_argument("--check-interval", type=int, help="Check interval in seconds")
    
    args = parser.parse_args()
    
    # Override config with command line arguments
    if args.server:
        os.environ["DEPLOY_SERVER_URL"] = args.server
    if args.group:
        os.environ["ROBOT_GROUP"] = args.group
    if args.check_interval:
        os.environ["CHECK_INTERVAL"] = str(args.check_interval)
    
    # Create and run agent
    agent = LeKiwiDeployAgent(args.config)
    agent.run()

if __name__ == "__main__":
    main()