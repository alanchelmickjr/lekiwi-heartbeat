#!/usr/bin/env python3
"""
Robot Versioning System - Vercel for Robots
Creates snapshots from working robots and deploys deltas to others
"""

import os
import sys
import json
import hashlib
import tarfile
import tempfile
import subprocess
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple

class RobotVersioning:
    """Handles robot versioning and delta deployments"""
    
    def __init__(self, versions_dir: str = "/tmp/robot_versions"):
        self.versions_dir = Path(versions_dir)
        self.versions_dir.mkdir(parents=True, exist_ok=True)
        self.metadata_file = self.versions_dir / "versions.json"
        self.metadata = self.load_metadata()
        
    def load_metadata(self) -> Dict:
        """Load version metadata"""
        if self.metadata_file.exists():
            with open(self.metadata_file, 'r') as f:
                return json.load(f)
        return {"versions": [], "current": None, "master_robot": "192.168.88.21"}
    
    def save_metadata(self):
        """Save version metadata"""
        with open(self.metadata_file, 'w') as f:
            json.dump(self.metadata, f, indent=2)
    
    def create_snapshot(self, robot_ip: str, version_name: str = None, 
                       description: str = "") -> Dict:
        """Create a snapshot from a working robot"""
        print(f"📸 Creating snapshot from {robot_ip}...")
        
        # Generate version name if not provided
        if not version_name:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            version_name = f"v_{timestamp}"
        
        version_dir = self.versions_dir / version_name
        version_dir.mkdir(exist_ok=True)
        
        # Files to snapshot
        snapshot_files = {
            # Core robot files
            "/opt/frodobots/teleop_agent": "binary",
            "/opt/frodobots/teleop.sh": "text",
            "/opt/frodobots/lib/libteleop_media_gst.so": "binary",
            "/opt/frodobots/lib/libteleop_ctrl_zmq_ik.so": "binary",
            
            # Services
            "/etc/systemd/system/teleop.service": "text",
            "/etc/systemd/system/lekiwi.service": "text",
            
            # LeRobot/LeKiwi files
            "/home/lekiwi/lerobot/lerobot/common/robots/lekiwi/lekiwi_host.py": "text",
            "/home/lekiwi/lerobot/lerobot/common/robots/lekiwi/__init__.py": "text",
            "/home/lekiwi/lerobot/lerobot/common/robots/lekiwi/lekiwi.py": "text",
            
            # Config files (excluding robot-specific teleop.ini)
            "/home/lekiwi/.bashrc": "text",
        }
        
        version_info = {
            "name": version_name,
            "source_robot": robot_ip,
            "created": datetime.now().isoformat(),
            "description": description,
            "files": {},
            "checksums": {},
            "permissions": {},
            "total_size": 0
        }
        
        # Create temporary directory for files
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            
            for filepath, filetype in snapshot_files.items():
                print(f"  Fetching {filepath}...")
                
                # Create local directory structure
                local_file = tmppath / filepath.lstrip('/')
                local_file.parent.mkdir(parents=True, exist_ok=True)
                
                # Fetch file with proper permissions preservation
                if filetype == "binary":
                    # For binary files, preserve exact copy with adequate timeout
                    cmd = [
                        "sshpass", "-p", "lekiwi", "scp", "-p",
                        "-o", "StrictHostKeyChecking=no",
                        "-o", "ConnectTimeout=15",
                        f"lekiwi@{robot_ip}:{filepath}",
                        str(local_file)
                    ]
                else:
                    # For text files, we can read content with adequate timeout
                    cmd = [
                        "sshpass", "-p", "lekiwi", "scp",
                        "-o", "StrictHostKeyChecking=no",
                        "-o", "ConnectTimeout=15",
                        f"lekiwi@{robot_ip}:{filepath}",
                        str(local_file)
                    ]
                
                result = subprocess.run(cmd, capture_output=True, timeout=30)
                
                if result.returncode == 0 and local_file.exists():
                    # Get file permissions with adequate timeout
                    perm_cmd = [
                        "sshpass", "-p", "lekiwi", "ssh",
                        "-o", "StrictHostKeyChecking=no",
                        "-o", "ConnectTimeout=15",
                        f"lekiwi@{robot_ip}",
                        f"stat -c '%a' {filepath}"
                    ]
                    perm_result = subprocess.run(perm_cmd, capture_output=True, text=True, timeout=20)
                    permissions = perm_result.stdout.strip() if perm_result.returncode == 0 else "644"
                    
                    # Calculate checksum
                    with open(local_file, 'rb') as f:
                        checksum = hashlib.sha256(f.read()).hexdigest()
                    
                    # Store metadata
                    version_info["checksums"][filepath] = checksum
                    version_info["permissions"][filepath] = permissions
                    version_info["total_size"] += local_file.stat().st_size
                    
                    # Copy to version directory
                    dest_file = version_dir / filepath.lstrip('/')
                    dest_file.parent.mkdir(parents=True, exist_ok=True)
                    
                    if filetype == "text":
                        # Store text content for easy diff
                        with open(local_file, 'r', errors='ignore') as f:
                            content = f.read()
                        with open(dest_file, 'w') as f:
                            f.write(content)
                        version_info["files"][filepath] = str(dest_file)
                    else:
                        # Copy binary file
                        import shutil
                        shutil.copy2(local_file, dest_file)
                        version_info["files"][filepath] = str(dest_file)
                else:
                    print(f"    ⚠️ Could not fetch {filepath}")
        
        # Save version metadata
        version_meta_file = version_dir / "version.json"
        with open(version_meta_file, 'w') as f:
            json.dump(version_info, f, indent=2)
        
        # Update global metadata
        self.metadata["versions"].append({
            "name": version_name,
            "created": version_info["created"],
            "source_robot": robot_ip,
            "description": description,
            "file_count": len(version_info["files"]),
            "total_size": version_info["total_size"]
        })
        self.metadata["current"] = version_name
        self.save_metadata()
        
        print(f"✅ Snapshot {version_name} created successfully!")
        print(f"   Files: {len(version_info['files'])}")
        print(f"   Size: {version_info['total_size'] / 1024 / 1024:.2f} MB")
        
        return version_info
    
    def calculate_delta(self, target_robot: str, version_name: str = None) -> Dict:
        """Calculate what files need to be updated on target robot"""
        if not version_name:
            version_name = self.metadata.get("current")
        
        if not version_name:
            raise ValueError("No version specified and no current version set")
        
        version_dir = self.versions_dir / version_name
        version_meta_file = version_dir / "version.json"
        
        if not version_meta_file.exists():
            raise ValueError(f"Version {version_name} not found")
        
        with open(version_meta_file, 'r') as f:
            version_info = json.load(f)
        
        print(f"🔍 Calculating delta for {target_robot} from version {version_name}...")
        
        delta = {
            "version": version_name,
            "target_robot": target_robot,
            "files_to_update": [],
            "files_missing": [],
            "files_different": [],
            "total_size": 0
        }
        
        # Check each file in the version
        for filepath, local_path in version_info["files"].items():
            # Get checksum from target robot with adequate timeout
            cmd = [
                "sshpass", "-p", "lekiwi", "ssh",
                "-o", "StrictHostKeyChecking=no",
                "-o", "ConnectTimeout=15",
                f"lekiwi@{target_robot}",
                f"[ -f {filepath} ] && sha256sum {filepath} | cut -d' ' -f1 || echo 'MISSING'"
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=25)
            
            if result.returncode == 0:
                target_checksum = result.stdout.strip()
                
                if target_checksum == "MISSING":
                    delta["files_missing"].append(filepath)
                    delta["files_to_update"].append(filepath)
                    if Path(local_path).exists():
                        delta["total_size"] += Path(local_path).stat().st_size
                elif target_checksum != version_info["checksums"][filepath]:
                    delta["files_different"].append(filepath)
                    delta["files_to_update"].append(filepath)
                    if Path(local_path).exists():
                        delta["total_size"] += Path(local_path).stat().st_size
        
        print(f"📊 Delta analysis complete:")
        print(f"   Files to update: {len(delta['files_to_update'])}")
        print(f"   Missing files: {len(delta['files_missing'])}")
        print(f"   Different files: {len(delta['files_different'])}")
        print(f"   Total size: {delta['total_size'] / 1024:.2f} KB")
        
        return delta
    
    def deploy_version(self, target_robot: str, version_name: str = None,
                      delta_only: bool = True) -> bool:
        """Deploy a version to target robot"""
        if not version_name:
            version_name = self.metadata.get("current")
        
        if not version_name:
            raise ValueError("No version specified and no current version set")
        
        version_dir = self.versions_dir / version_name
        version_meta_file = version_dir / "version.json"
        
        if not version_meta_file.exists():
            raise ValueError(f"Version {version_name} not found")
        
        with open(version_meta_file, 'r') as f:
            version_info = json.load(f)
        
        print(f"🚀 Deploying version {version_name} to {target_robot}...")
        
        # Calculate delta if requested
        if delta_only:
            delta = self.calculate_delta(target_robot, version_name)
            files_to_deploy = delta["files_to_update"]
        else:
            files_to_deploy = list(version_info["files"].keys())
        
        if not files_to_deploy:
            print("✅ Robot is already up to date!")
            return True
        
        success_count = 0
        failed_files = []
        
        # Deploy each file
        for filepath in files_to_deploy:
            local_path = Path(version_info["files"][filepath])
            
            if not local_path.exists():
                print(f"  ❌ Local file not found: {filepath}")
                failed_files.append(filepath)
                continue
            
            print(f"  Deploying {filepath}...")
            
            # First copy to /tmp on target with adequate timeout
            remote_tmp = f"/tmp/{local_path.name}"
            cmd = [
                "sshpass", "-p", "lekiwi", "scp",
                "-o", "StrictHostKeyChecking=no",
                "-o", "ConnectTimeout=15",
                str(local_path),
                f"lekiwi@{target_robot}:{remote_tmp}"
            ]
            
            result = subprocess.run(cmd, capture_output=True, timeout=30)
            
            if result.returncode == 0:
                # Create directory if needed and move file with sudo
                permissions = version_info["permissions"].get(filepath, "644")
                
                move_cmds = [
                    f"sudo mkdir -p $(dirname {filepath})",
                    f"sudo mv {remote_tmp} {filepath}",
                    f"sudo chmod {permissions} {filepath}",
                    f"sudo chown lekiwi:lekiwi {filepath}"
                ]
                
                for move_cmd in move_cmds:
                    ssh_cmd = [
                        "sshpass", "-p", "lekiwi", "ssh",
                        "-o", "StrictHostKeyChecking=no",
                        "-o", "ConnectTimeout=15",
                        f"lekiwi@{target_robot}",
                        move_cmd
                    ]
                    subprocess.run(ssh_cmd, capture_output=True, timeout=20)
                
                success_count += 1
                print(f"    ✅ Deployed successfully")
            else:
                print(f"    ❌ Failed to deploy")
                failed_files.append(filepath)
        
        # Handle robot-specific configuration (teleop.ini)
        print("  Configuring robot-specific files...")
        self.configure_robot_specific(target_robot)
        
        # Restart services if needed
        if any("systemd" in f for f in files_to_deploy):
            print("  Reloading systemd and restarting services...")
            restart_cmds = [
                "sudo systemctl daemon-reload",
                "sudo systemctl restart teleop",
                "sudo systemctl restart lekiwi"
            ]
            
            for cmd in restart_cmds:
                ssh_cmd = [
                    "sshpass", "-p", "lekiwi", "ssh",
                    "-o", "StrictHostKeyChecking=no",
                    "-o", "ConnectTimeout=15",
                    f"lekiwi@{target_robot}",
                    cmd
                ]
                subprocess.run(ssh_cmd, capture_output=True, timeout=20)
        
        print(f"\n📊 Deployment Summary:")
        print(f"   ✅ Successfully deployed: {success_count}/{len(files_to_deploy)}")
        
        if failed_files:
            print(f"   ❌ Failed files: {', '.join(failed_files)}")
            return False
        
        print(f"✅ Deployment complete!")
        return True
    
    def configure_robot_specific(self, robot_ip: str):
        """Configure robot-specific files like teleop.ini"""
        # Get MAC address for device ID with adequate timeout
        cmd = [
            "sshpass", "-p", "lekiwi", "ssh",
            "-o", "StrictHostKeyChecking=no",
            "-o", "ConnectTimeout=15",
            f"lekiwi@{robot_ip}",
            "ip link show eth0 | grep ether | awk '{print $2}'"
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        
        if result.returncode == 0:
            mac = result.stdout.strip()
            if mac:
                # Generate device ID
                mac_clean = mac.replace(':', '')
                device_id = f"lekiwi_{mac_clean[4:]}"
                
                # Generate token
                import base64
                token_string = f"lekiwi:lekiwi666:{device_id}:1000001"
                token = base64.b64encode(token_string.encode()).decode()
                
                # Create teleop.ini
                teleop_config = f"""[teleop]
token = {token}
video = 2
audio = 0
project = lekiwi
record = false

[signal]
cert = /opt/frodobots/cert/cert.pem
key = /opt/frodobots/cert/priv.pem
ca = /opt/frodobots/cert/AmazonRootCA1.pem
device = {device_id}

[plugin]
media = /opt/frodobots/lib/libteleop_media_gst.so
ctrl = /opt/frodobots/lib/libteleop_ctrl_zmq_ik.so
camera1 = v4l2src device=/dev/video2 !videoflip video-direction=180
camera2 = v4l2src device=/dev/video0 !videoflip video-direction=180
"""
                
                # Write and deploy teleop.ini
                with tempfile.NamedTemporaryFile(mode='w', suffix='.ini', delete=False) as f:
                    f.write(teleop_config)
                    temp_file = f.name
                
                # Copy to robot with adequate timeout
                copy_cmd = [
                    "sshpass", "-p", "lekiwi", "scp",
                    "-o", "StrictHostKeyChecking=no",
                    "-o", "ConnectTimeout=15",
                    temp_file,
                    f"lekiwi@{robot_ip}:/tmp/teleop.ini"
                ]
                subprocess.run(copy_cmd, capture_output=True, timeout=30)
                
                # Move to correct location with adequate timeout
                move_cmd = [
                    "sshpass", "-p", "lekiwi", "ssh",
                    "-o", "StrictHostKeyChecking=no",
                    "-o", "ConnectTimeout=15",
                    f"lekiwi@{robot_ip}",
                    "sudo mv /tmp/teleop.ini /opt/frodobots/teleop.ini && sudo chown lekiwi:lekiwi /opt/frodobots/teleop.ini"
                ]
                subprocess.run(move_cmd, capture_output=True, timeout=20)
                
                # Clean up temp file
                os.unlink(temp_file)
                
                print(f"    ✅ Configured teleop.ini with device ID: {device_id}")
    
    def list_versions(self) -> List[Dict]:
        """List all available versions"""
        return self.metadata.get("versions", [])
    
    def set_master_robot(self, robot_ip: str):
        """Set the master robot for snapshots"""
        self.metadata["master_robot"] = robot_ip
        self.save_metadata()
        print(f"✅ Master robot set to {robot_ip}")

def main():
    """CLI interface for robot versioning"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Robot Versioning System - Vercel for Robots')
    subparsers = parser.add_subparsers(dest='command', help='Commands')
    
    # Snapshot command
    snapshot_parser = subparsers.add_parser('snapshot', help='Create a snapshot from a robot')
    snapshot_parser.add_argument('robot_ip', help='Source robot IP')
    snapshot_parser.add_argument('--name', help='Version name (auto-generated if not provided)')
    snapshot_parser.add_argument('--description', default='', help='Version description')
    
    # Deploy command
    deploy_parser = subparsers.add_parser('deploy', help='Deploy a version to a robot')
    deploy_parser.add_argument('robot_ip', help='Target robot IP')
    deploy_parser.add_argument('--version', help='Version to deploy (uses current if not specified)')
    deploy_parser.add_argument('--full', action='store_true', help='Deploy all files, not just delta')
    
    # Delta command
    delta_parser = subparsers.add_parser('delta', help='Show what would be deployed')
    delta_parser.add_argument('robot_ip', help='Target robot IP')
    delta_parser.add_argument('--version', help='Version to compare')
    
    # List command
    list_parser = subparsers.add_parser('list', help='List all versions')
    
    # Set master command
    master_parser = subparsers.add_parser('set-master', help='Set master robot')
    master_parser.add_argument('robot_ip', help='Master robot IP')
    
    args = parser.parse_args()
    
    versioning = RobotVersioning()
    
    if args.command == 'snapshot':
        versioning.create_snapshot(args.robot_ip, args.name, args.description)
    elif args.command == 'deploy':
        versioning.deploy_version(args.robot_ip, args.version, not args.full)
    elif args.command == 'delta':
        delta = versioning.calculate_delta(args.robot_ip, args.version)
        print(json.dumps(delta, indent=2))
    elif args.command == 'list':
        versions = versioning.list_versions()
        for v in versions:
            print(f"{v['name']} - {v['created']} from {v['source_robot']} ({v['file_count']} files)")
    elif args.command == 'set-master':
        versioning.set_master_robot(args.robot_ip)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()