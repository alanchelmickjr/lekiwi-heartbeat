#!/usr/bin/env python3
"""
LeKiwi Master Deployment System
Automates deployment to robot fleet with proper configuration
"""

import os
import sys
import json
import base64
import subprocess
import argparse
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime

class Colors:
    RED = '\033[0;31m'
    GREEN = '\033[0;32m'
    YELLOW = '\033[1;33m'
    BLUE = '\033[0;34m'
    MAGENTA = '\033[0;35m'
    CYAN = '\033[0;36m'
    NC = '\033[0m'  # No Color

class LeKiwiDeployment:
    def __init__(self, robot_ip: str, username: str = "lekiwi", password: str = "lekiwi"):
        self.robot_ip = robot_ip
        self.username = username
        self.password = password
        self.device_id = None
        self.mac_address = None
        
    def log(self, message: str, color: str = Colors.NC):
        """Print colored log message"""
        print(f"{color}{message}{Colors.NC}")
        
    def execute_ssh(self, command: str, suppress_error: bool = False, stream_output: bool = False) -> tuple:
        """Execute command on robot via SSH"""
        # Escape single quotes in command
        escaped_command = command.replace("'", "'\"'\"'")
        ssh_cmd = f"sshpass -p {self.password} ssh -o StrictHostKeyChecking=no {self.username}@{self.robot_ip} '{escaped_command}'"
        
        if stream_output:
            # Stream output in real-time for long-running commands
            self.log(f"  Executing: {command}", Colors.CYAN)
            process = subprocess.Popen(ssh_cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            
            stdout_lines = []
            stderr_lines = []
            
            # Use unbuffered output for real-time streaming
            import select
            import time
            
            # Set non-blocking mode for better real-time output
            start_time = time.time()
            last_output_time = time.time()
            timeout_seconds = 600  # 10 minute hard timeout
            idle_timeout = 120  # 2 minute idle timeout
            
            self.log(f"    ⏳ Command started, monitoring output...", Colors.CYAN)
            
            while True:
                # Check if process is still running
                poll_status = process.poll()
                if poll_status is not None:
                    # Process finished
                    break
                    
                # Check for timeout
                current_time = time.time()
                if current_time - start_time > timeout_seconds:
                    self.log(f"    ⏰ Command timed out after {timeout_seconds} seconds!", Colors.RED)
                    process.kill()
                    break
                    
                if current_time - last_output_time > idle_timeout:
                    self.log(f"    ⚠️ No output for {idle_timeout} seconds, command may be stuck", Colors.YELLOW)
                    
                # Try to read available output
                ready, _, _ = select.select([process.stdout], [], [], 0.1)
                if ready:
                    line = process.stdout.readline()
                    if line:
                        last_output_time = current_time
                        line = line.rstrip()
                        stdout_lines.append(line)
                        
                        # Print progress indicators and important lines
                        # Always show download progress (wget/curl output)
                        if any(x in line for x in ['%', '....', 'KB/s', 'MB/s', 'ETA', '==>', 'downloaded']):
                            self.log(f"    {line}", Colors.CYAN)
                        # Show Miniconda installation progress
                        elif any(x in line.lower() for x in ['prefix', 'extracting', 'unpacking',
                                                              'installing', 'initializing', 'preparing',
                                                              'transaction', 'linking', 'unlinking']):
                            self.log(f"    📦 {line}", Colors.YELLOW)
                        # Show errors or warnings
                        elif any(x in line.lower() for x in ['error', 'warning', 'fail', 'unable']):
                            self.log(f"    ⚠️ {line}", Colors.RED)
                        # Show every 50th line to indicate progress
                        elif len(stdout_lines) % 50 == 0:
                            display_line = line[:80] + "..." if len(line) > 80 else line
                            self.log(f"    ... {display_line}", Colors.CYAN)
            
            # Get any remaining output
            remaining_out, remaining_err = process.communicate()
            if remaining_out:
                stdout_lines.extend(remaining_out.strip().split('\n'))
            if remaining_err:
                stderr_lines = remaining_err.strip().split('\n')
            
            returncode = process.returncode
            stdout = '\n'.join(stdout_lines)
            stderr = '\n'.join(stderr_lines)
            
            if returncode != 0 and not suppress_error:
                self.log(f"Error executing: {command}", Colors.RED)
                if stderr:
                    self.log(f"Error: {stderr}", Colors.RED)
                    
            return returncode, stdout, stderr
        else:
            # Original non-streaming version
            result = subprocess.run(ssh_cmd, shell=True, capture_output=True, text=True)
            
            if result.returncode != 0 and not suppress_error:
                self.log(f"Error executing: {command}", Colors.RED)
                self.log(f"Error: {result.stderr}", Colors.RED)
                
            return result.returncode, result.stdout.strip(), result.stderr.strip()
        
    def copy_to_robot(self, local_path: str, remote_path: str) -> bool:
        """Copy file to robot via SCP"""
        scp_cmd = f"sshpass -p {self.password} scp -o StrictHostKeyChecking=no {local_path} {self.username}@{self.robot_ip}:{remote_path}"
        result = subprocess.run(scp_cmd, shell=True, capture_output=True)
        return result.returncode == 0
        
    def get_device_info(self) -> Dict:
        """Get robot device information"""
        self.log("\n📊 Getting device information...", Colors.CYAN)
        
        # Get MAC address - use different approach to avoid quote issues
        ret, mac, _ = self.execute_ssh("ip link show eth0 | grep ether | cut -d' ' -f6")
        if ret == 0 and mac:
            self.mac_address = mac
            # Generate device ID - LOWERCASE lekiwi_ + last 4 octets of MAC
            mac_clean = mac.replace(':', '')
            self.device_id = f"lekiwi_{mac_clean[4:]}"  # Ensure lowercase
            
            self.log(f"  ✓ MAC Address: {self.mac_address}", Colors.GREEN)
            self.log(f"  ✓ Device ID: {self.device_id}", Colors.GREEN)
            
            # Generate token
            token_string = f"lekiwi:lekiwi666:{self.device_id}:1000001"
            token = base64.b64encode(token_string.encode()).decode()
            
            return {
                'mac': self.mac_address,
                'device_id': self.device_id,
                'token': token,
                'hostname': self.execute_ssh("hostname")[1]
            }
        else:
            self.log("  ✗ Failed to get MAC address", Colors.RED)
            return None
            
    def check_status(self) -> Dict:
        """Check current robot status"""
        self.log("\n🔍 Checking robot status...", Colors.CYAN)
        
        status = {
            'services': {},
            'installations': {},
            'conda_env': False
        }
        
        # Check services
        for service in ['teleop', 'lekiwi']:
            ret, _, _ = self.execute_ssh(f"systemctl is-active {service}", suppress_error=True)
            status['services'][service] = (ret == 0)
            if status['services'][service]:
                self.log(f"  ✓ {service} service: active", Colors.GREEN)
            else:
                self.log(f"  ✗ {service} service: inactive", Colors.YELLOW)
                
        # Check installations
        ret, _, _ = self.execute_ssh("[ -d /opt/frodobots ]", suppress_error=True)
        status['installations']['teleop'] = (ret == 0)
        
        ret, _, _ = self.execute_ssh("[ -d /home/lekiwi/lerobot ]", suppress_error=True)
        status['installations']['lerobot'] = (ret == 0)
        
        ret, _, _ = self.execute_ssh("[ -d /home/lekiwi/lerobot/lerobot/common/robots/lekiwi ]", suppress_error=True)
        status['installations']['lekiwi'] = (ret == 0)
        
        # Check for either lerobot or lerobotenv conda environments
        ret1, _, _ = self.execute_ssh("[ -d /home/lekiwi/miniconda3/envs/lerobot ]", suppress_error=True)
        ret2, _, _ = self.execute_ssh("[ -d /home/lekiwi/miniconda3/envs/lerobotenv ]", suppress_error=True)
        status['conda_env'] = (ret1 == 0 or ret2 == 0)
        
        for component, installed in status['installations'].items():
            if installed:
                self.log(f"  ✓ {component}: installed", Colors.GREEN)
            else:
                self.log(f"  ✗ {component}: not installed", Colors.YELLOW)
                
        if status['conda_env']:
            self.log(f"  ✓ Conda environment: lerobot exists", Colors.GREEN)
        else:
            self.log(f"  ✗ Conda environment: not found", Colors.YELLOW)
            
        return status
        
    def install_lerobot(self) -> bool:
        """Install LeRobot base system"""
        self.log("\n🤖 Installing LeRobot...", Colors.CYAN)
        
        # Check if already installed
        ret, _, _ = self.execute_ssh("[ -d /home/lekiwi/lerobot ]", suppress_error=True)
        if ret == 0:
            self.log("  ℹ LeRobot already installed", Colors.YELLOW)
            return True
            
        # Install dependencies
        self.log("  Installing dependencies...", Colors.YELLOW)
        self.execute_ssh("sudo apt-get update && sudo apt-get install -y python3-pip python3-venv git")
        
        # Clone LeRobot
        self.log("  Cloning LeRobot repository...", Colors.YELLOW)
        ret, _, _ = self.execute_ssh("cd /home/lekiwi && git clone https://github.com/huggingface/lerobot.git")
        
        if ret != 0:
            self.log("  ✗ Failed to clone LeRobot", Colors.RED)
            return False
            
        # Setup conda environment if needed
        ret, _, _ = self.execute_ssh("[ -d /home/lekiwi/miniconda3 ]", suppress_error=True)
        if ret != 0:
            self.log("  Miniconda not found, installing...", Colors.YELLOW)
            if not self.install_miniconda_only():
                self.log("  ✗ Failed to install Miniconda", Colors.RED)
                return False
            
        # Create conda environment and install LeRobot (use lerobot as env name)
        self.log("  Creating conda environment...", Colors.YELLOW)
        self.execute_ssh("source /home/lekiwi/miniconda3/bin/activate && conda create -n lerobot python=3.10 -y")
        self.execute_ssh("source /home/lekiwi/miniconda3/bin/activate lerobot && cd /home/lekiwi/lerobot && pip install -e .")
        
        self.log("  ✓ LeRobot installed", Colors.GREEN)
        return True
    
    def install_miniconda_only(self) -> bool:
        """Install only Miniconda without LeRobot"""
        self.log("\n🐍 Installing Miniconda...", Colors.CYAN)
        
        # Check if already installed
        ret, _, _ = self.execute_ssh("[ -d /home/lekiwi/miniconda3 ]", suppress_error=True)
        if ret == 0:
            self.log("  ℹ Miniconda already installed", Colors.YELLOW)
            # Verify it's working
            ret, version_out, _ = self.execute_ssh("source /home/lekiwi/miniconda3/bin/activate && conda --version", suppress_error=True)
            if ret == 0:
                self.log(f"  ✓ Conda version: {version_out}", Colors.GREEN)
                return True
            else:
                self.log("  ⚠️ Miniconda directory exists but conda not working, reinstalling...", Colors.YELLOW)
                # Remove broken installation
                self.execute_ssh("rm -rf /home/lekiwi/miniconda3")
        
        # Check system architecture to ensure we're on ARM64
        ret, arch, _ = self.execute_ssh("uname -m")
        if ret == 0:
            self.log(f"  System architecture: {arch}", Colors.CYAN)
            if "aarch64" not in arch and "arm64" not in arch:
                self.log(f"  ⚠️ Warning: System is {arch}, not ARM64/aarch64", Colors.YELLOW)
        
        # Install dependencies
        self.log("  Installing system dependencies...", Colors.YELLOW)
        ret, _, err = self.execute_ssh("sudo apt-get update && sudo apt-get install -y wget curl ca-certificates")
        if ret != 0:
            self.log(f"  ✗ Failed to install dependencies: {err}", Colors.RED)
            return False
        
        # Clean up any old installer
        self.execute_ssh("rm -f /tmp/miniconda.sh", suppress_error=True)
        
        # Download Miniconda for ARM64/aarch64 (Raspberry Pi)
        miniconda_url = "https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-aarch64.sh"
        self.log(f"  📥 Downloading Miniconda from: {miniconda_url}", Colors.YELLOW)
        self.log("  This may take 2-3 minutes depending on network speed...", Colors.YELLOW)
        
        # First test connectivity
        self.log("  Testing download connectivity...", Colors.CYAN)
        test_cmd = f"curl -I -L --connect-timeout 10 {miniconda_url} | head -n 1"
        ret, test_out, test_err = self.execute_ssh(test_cmd, suppress_error=True)
        if ret != 0:
            self.log("  ⚠️ Cannot reach Miniconda server, checking network...", Colors.YELLOW)
            # Test basic network
            ping_ret, _, _ = self.execute_ssh("ping -c 1 8.8.8.8", suppress_error=True)
            if ping_ret != 0:
                self.log("  ✗ No internet connection on robot!", Colors.RED)
                return False
        
        # Use wget with progress indicator - more reliable than curl on Raspberry Pi
        download_cmd = f"wget --no-check-certificate --progress=dot:mega {miniconda_url} -O /tmp/miniconda.sh 2>&1"
        self.log("  Starting download with wget...", Colors.CYAN)
        ret, out, err = self.execute_ssh(download_cmd, stream_output=True)
        
        if ret != 0:
            self.log(f"  ✗ Failed to download Miniconda", Colors.RED)
            if err:
                self.log(f"  Error: {err[:500]}", Colors.RED)
            # Try alternative download method with curl
            self.log("  Trying alternative download method with curl...", Colors.YELLOW)
            alt_cmd = f"curl -L -o /tmp/miniconda.sh {miniconda_url} 2>&1"
            ret, out, err = self.execute_ssh(alt_cmd, stream_output=True)
            if ret != 0:
                self.log(f"  ✗ Alternative download also failed", Colors.RED)
                if err:
                    self.log(f"  Error: {err[:500]}", Colors.RED)
                return False
        
        # Verify download
        ret, size_out, _ = self.execute_ssh("ls -lh /tmp/miniconda.sh | awk '{print $5}'")
        if ret == 0:
            self.log(f"  Downloaded file size: {size_out}", Colors.CYAN)
        
        # Check if file exists and is not empty
        ret, _, _ = self.execute_ssh("[ -s /tmp/miniconda.sh ]")
        if ret != 0:
            self.log("  ✗ Downloaded file is empty or missing", Colors.RED)
            return False
        
        # Make installer executable
        self.execute_ssh("chmod +x /tmp/miniconda.sh")
        
        # Install Miniconda with verbose output
        self.log("  🚀 Starting Miniconda installation...", Colors.YELLOW)
        self.log("  This will take 2-3 minutes. Installation progress:", Colors.CYAN)
        
        # First make sure the script is executable and valid
        self.log("  Checking installer integrity...", Colors.CYAN)
        check_ret, check_out, _ = self.execute_ssh("file /tmp/miniconda.sh && head -n 1 /tmp/miniconda.sh")
        if check_ret == 0:
            self.log(f"  Installer check: {check_out[:100]}", Colors.CYAN)
        
        # Run the installer with explicit bash and unbuffered output
        # Add -x flag for verbose output to see what's happening
        install_cmd = "bash -x /tmp/miniconda.sh -b -p /home/lekiwi/miniconda3 2>&1"
        self.log("  Executing installer (this WILL take time, please be patient)...", Colors.YELLOW)
        ret, install_out, install_err = self.execute_ssh(install_cmd, stream_output=True)
        
        if ret != 0:
            self.log(f"  ✗ Failed to install Miniconda", Colors.RED)
            self.log(f"  Error output: {install_err}", Colors.RED)
            if install_out:
                self.log(f"  Install output: {install_out[-500:]}", Colors.YELLOW)  # Last 500 chars
            # Clean up failed installation
            self.execute_ssh("rm -rf /home/lekiwi/miniconda3", suppress_error=True)
            return False
        
        # Add conda to PATH in .bashrc
        self.log("  Configuring PATH...", Colors.YELLOW)
        self.execute_ssh("echo 'export PATH=/home/lekiwi/miniconda3/bin:$PATH' >> ~/.bashrc")
        
        # Initialize conda for bash
        self.log("  Initializing conda for bash shell...", Colors.YELLOW)
        ret, init_out, init_err = self.execute_ssh("/home/lekiwi/miniconda3/bin/conda init bash", stream_output=True)
        if ret == 0 and init_out:
            self.log(f"  Conda init output: {init_out[:200]}", Colors.CYAN)
        
        # Verify installation
        ret, version_out, _ = self.execute_ssh("source /home/lekiwi/miniconda3/bin/activate && conda --version")
        if ret == 0:
            self.log(f"  ✓ Miniconda installed successfully: {version_out}", Colors.GREEN)
        else:
            self.log("  ⚠️ Miniconda installed but verification failed", Colors.YELLOW)
        
        # Clean up installer
        self.execute_ssh("rm -f /tmp/miniconda.sh", suppress_error=True)
        
        # Configure conda to not auto-activate base environment (optional)
        self.execute_ssh("/home/lekiwi/miniconda3/bin/conda config --set auto_activate_base false", suppress_error=True)
        
        return True
    
    def setup_python_environment(self) -> bool:
        """Setup conda environment with LeRobot and LeKiwi packages"""
        self.log("\n🔧 Setting up Python environment...", Colors.CYAN)
        
        # Ensure Miniconda is installed
        ret, _, _ = self.execute_ssh("[ -d /home/lekiwi/miniconda3 ]", suppress_error=True)
        if ret != 0:
            self.log("  Installing Miniconda first...", Colors.YELLOW)
            if not self.install_miniconda_only():
                return False
        
        # Check if lerobot conda environment exists
        ret1, _, _ = self.execute_ssh("[ -d /home/lekiwi/miniconda3/envs/lerobot ]", suppress_error=True)
        if ret1 == 0:
            self.log("  ℹ lerobot environment already exists", Colors.YELLOW)
        else:
            # Create conda environment
            self.log("  Creating lerobot conda environment...", Colors.YELLOW)
            ret, _, _ = self.execute_ssh("source /home/lekiwi/miniconda3/bin/activate && conda create -n lerobot python=3.10 -y")
            if ret != 0:
                self.log("  ✗ Failed to create conda environment", Colors.RED)
                return False
        
        # Install LeRobot if not already installed
        ret, _, _ = self.execute_ssh("[ -d /home/lekiwi/lerobot ]", suppress_error=True)
        if ret != 0:
            self.log("  Cloning LeRobot repository...", Colors.YELLOW)
            ret, _, _ = self.execute_ssh("cd /home/lekiwi && git clone https://github.com/huggingface/lerobot.git")
            if ret != 0:
                self.log("  ✗ Failed to clone LeRobot", Colors.RED)
                return False
        
        # Install LeRobot in conda environment
        self.log("  Installing LeRobot in conda environment...", Colors.YELLOW)
        ret, _, _ = self.execute_ssh("source /home/lekiwi/miniconda3/bin/activate lerobot && cd /home/lekiwi/lerobot && pip install -e .")
        if ret != 0:
            self.log("  ✗ Failed to install LeRobot", Colors.RED)
            return False
        
        # Install LeKiwi package if missing
        ret, _, _ = self.execute_ssh("[ -d /home/lekiwi/lerobot/lerobot/common/robots/lekiwi ]", suppress_error=True)
        if ret != 0:
            self.log("  Installing LeKiwi robot package...", Colors.YELLOW)
            # Copy LeKiwi package from master robot (.21)
            self.copy_lekiwi_package()
        else:
            self.log("  ✓ LeKiwi package already installed", Colors.GREEN)
        
        self.log("  ✓ Python environment setup completed", Colors.GREEN)
        return True
    
    def copy_lekiwi_package(self) -> bool:
        """Copy LeKiwi robot package from master robot"""
        self.log("  Copying LeKiwi package from master robot...", Colors.YELLOW)
        
        # Create the directory structure
        self.execute_ssh("mkdir -p /home/lekiwi/lerobot/lerobot/common/robots/lekiwi")
        
        # Copy LeKiwi package files from master robot (.21)
        master_ip = "192.168.88.21"
        lekiwi_files = [
            "/home/lekiwi/lerobot/lerobot/common/robots/lekiwi/lekiwi_host.py",
            "/home/lekiwi/lerobot/lerobot/common/robots/lekiwi/__init__.py",
            "/home/lekiwi/lerobot/lerobot/common/robots/lekiwi/lekiwi.py"
        ]
        
        for file_path in lekiwi_files:
            filename = os.path.basename(file_path)
            cmd = f"sshpass -p {self.password} scp -o StrictHostKeyChecking=no {self.username}@{master_ip}:{file_path} /tmp/{filename}"
            result = subprocess.run(cmd, shell=True, capture_output=True)
            
            if result.returncode == 0:
                # Copy to target robot
                if self.copy_to_robot(f"/tmp/{filename}", f"/tmp/{filename}"):
                    self.execute_ssh(f"mv /tmp/{filename} /home/lekiwi/lerobot/lerobot/common/robots/lekiwi/")
                    self.log(f"    ✓ Copied {filename}", Colors.GREEN)
                else:
                    self.log(f"    ✗ Failed to copy {filename}", Colors.RED)
            else:
                self.log(f"    ⚠️ Could not get {filename} from master robot", Colors.YELLOW)
        
        # Set permissions
        self.execute_ssh("chown -R lekiwi:lekiwi /home/lekiwi/lerobot/lerobot/common/robots/lekiwi")
        
        return True
        
    def configure_teleop(self) -> bool:
        """Configure teleop.ini with correct device ID"""
        self.log("\n⚙️  Configuring Teleop...", Colors.CYAN)
        
        device_info = self.get_device_info()
        if not device_info:
            return False
            
        # Create teleop.ini content
        teleop_config = f"""[teleop]
token = {device_info['token']}
video = 2
audio = 0
project = lekiwi
record = false

[signal]
cert = /opt/frodobots/cert/cert.pem
key = /opt/frodobots/cert/priv.pem
ca = /opt/frodobots/cert/AmazonRootCA1.pem
device = {device_info['device_id']}

[plugin]
media = /opt/frodobots/lib/libteleop_media_gst.so
ctrl = /opt/frodobots/lib/libteleop_ctrl_zmq_ik.so
camera1 = v4l2src device=/dev/video2 !videoflip video-direction=180
camera2 = v4l2src device=/dev/video0 !videoflip video-direction=180
"""
        
        # Write config to temp file
        temp_config = "/tmp/teleop.ini"
        with open(temp_config, 'w') as f:
            f.write(teleop_config)
            
        # Copy to robot
        if self.copy_to_robot(temp_config, "/tmp/teleop.ini"):
            self.execute_ssh("sudo mv /tmp/teleop.ini /opt/frodobots/teleop.ini")
            self.execute_ssh("sudo chown lekiwi:lekiwi /opt/frodobots/teleop.ini")
            self.log(f"  ✓ Configured teleop.ini with device ID: {device_info['device_id']}", Colors.GREEN)
            
            # Restart teleop service
            self.execute_ssh("sudo systemctl restart teleop")
            self.log("  ✓ Restarted teleop service", Colors.GREEN)
            return True
        else:
            self.log("  ✗ Failed to configure teleop.ini", Colors.RED)
            return False
            
    def copy_teleop_from_working_robot(self, source_ip: str = "192.168.88.21") -> bool:
        """Copy teleop binaries from working robot"""
        self.log(f"\n📦 Copying teleop from working robot ({source_ip})...", Colors.CYAN)
        
        # Create directories
        self.execute_ssh("sudo mkdir -p /opt/frodobots/{cert,lib}")
        self.execute_ssh("sudo chown -R lekiwi:lekiwi /opt/frodobots")
        
        # Copy files from working robot to local temp
        files_to_copy = [
            ("/opt/frodobots/teleop_agent", "/tmp/teleop_agent"),
            ("/opt/frodobots/teleop.sh", "/tmp/teleop.sh"),
            ("/opt/frodobots/lib/libteleop_media_gst.so", "/tmp/libteleop_media_gst.so"),
            ("/opt/frodobots/lib/libteleop_ctrl_zmq_ik.so", "/tmp/libteleop_ctrl_zmq_ik.so"),
            ("/opt/frodobots/cert/cert.pem", "/tmp/cert.pem"),
            ("/opt/frodobots/cert/priv.pem", "/tmp/priv.pem"),
            ("/opt/frodobots/cert/AmazonRootCA1.pem", "/tmp/AmazonRootCA1.pem"),
        ]
        
        for src, dest in files_to_copy:
            cmd = f"sshpass -p {self.password} scp -o StrictHostKeyChecking=no {self.username}@{source_ip}:{src} {dest}"
            result = subprocess.run(cmd, shell=True, capture_output=True)
            if result.returncode == 0:
                # Copy to target robot
                filename = os.path.basename(dest)
                if self.copy_to_robot(dest, f"/tmp/{filename}"):
                    if "cert" in src:
                        self.execute_ssh(f"sudo mv /tmp/{filename} /opt/frodobots/cert/")
                    elif "lib" in src:
                        self.execute_ssh(f"sudo mv /tmp/{filename} /opt/frodobots/lib/")
                    else:
                        self.execute_ssh(f"sudo mv /tmp/{filename} /opt/frodobots/")
                        if filename in ["teleop_agent", "teleop.sh"]:
                            self.execute_ssh(f"sudo chmod +x /opt/frodobots/{filename}")
                    self.log(f"  ✓ Copied {filename}", Colors.GREEN)
                else:
                    self.log(f"  ✗ Failed to copy {filename} to robot", Colors.RED)
            else:
                self.log(f"  ✗ Failed to get {filename} from source", Colors.RED)
                
        return True
        
    def create_systemd_services(self) -> bool:
        """Create systemd service files"""
        self.log("\n📝 Creating systemd services...", Colors.CYAN)
        
        # Check if teleop service exists
        ret, _, _ = self.execute_ssh("[ -f /etc/systemd/system/teleop.service ]", suppress_error=True)
        if ret != 0:
            # Create teleop service
            teleop_service = """[Unit]
Description=BitRobot Teleop Service
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=lekiwi
WorkingDirectory=/opt/frodobots
ExecStart=/opt/frodobots/teleop.sh
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
"""
            with open("/tmp/teleop.service", 'w') as f:
                f.write(teleop_service)
            self.copy_to_robot("/tmp/teleop.service", "/tmp/teleop.service")
            self.execute_ssh("sudo mv /tmp/teleop.service /etc/systemd/system/")
            self.execute_ssh("sudo systemctl daemon-reload")
            self.execute_ssh("sudo systemctl enable teleop")
            self.log("  ✓ Created teleop service", Colors.GREEN)
        else:
            self.log("  ℹ Teleop service already exists", Colors.YELLOW)
            
        # Check if lekiwi service exists
        ret, _, _ = self.execute_ssh("[ -f /etc/systemd/system/lekiwi.service ]", suppress_error=True)
        if ret != 0:
            # Create lekiwi service
            lekiwi_service = """[Unit]
Description=LeKiwi Holonomic Base Service
After=network.target

[Service]
Type=simple
User=lekiwi
WorkingDirectory=/home/lekiwi/lerobot
Environment="PATH=/home/lekiwi/miniconda3/envs/lerobot/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
ExecStart=/home/lekiwi/miniconda3/envs/lerobot/bin/python /home/lekiwi/lerobot/lerobot/common/robots/lekiwi/lekiwi_host.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
"""
            with open("/tmp/lekiwi.service", 'w') as f:
                f.write(lekiwi_service)
            self.copy_to_robot("/tmp/lekiwi.service", "/tmp/lekiwi.service")
            self.execute_ssh("sudo mv /tmp/lekiwi.service /etc/systemd/system/")
            self.execute_ssh("sudo systemctl daemon-reload")
            self.execute_ssh("sudo systemctl enable lekiwi")
            self.log("  ✓ Created lekiwi service", Colors.GREEN)
        else:
            self.log("  ℹ LeKiwi service already exists", Colors.YELLOW)
            
        return True
        
    def deploy_full(self, source_robot: str = "192.168.88.21") -> bool:
        """Full deployment process"""
        self.log(f"\n{'='*60}", Colors.BLUE)
        self.log(f"    LeKiwi Robot Deployment - {self.robot_ip}", Colors.BLUE)
        self.log(f"{'='*60}\n", Colors.BLUE)
        
        # Get device info
        device_info = self.get_device_info()
        if not device_info:
            self.log("Failed to get device information", Colors.RED)
            return False
            
        # Check current status
        status = self.check_status()
        
        # Install LeRobot if needed
        if not status['installations']['lerobot']:
            if not self.install_lerobot():
                return False
                
        # Copy teleop if needed
        if not status['installations']['teleop']:
            if not self.copy_teleop_from_working_robot(source_robot):
                self.log("Warning: Some teleop files may be missing", Colors.YELLOW)
                
        # Configure teleop
        if not self.configure_teleop():
            self.log("Failed to configure teleop", Colors.RED)
            
        # Create systemd services
        if not self.create_systemd_services():
            self.log("Failed to create systemd services", Colors.RED)
            
        # Start services
        self.log("\n🚀 Starting services...", Colors.CYAN)
        for service in ['teleop', 'lekiwi']:
            ret, _, _ = self.execute_ssh(f"sudo systemctl restart {service}")
            if ret == 0:
                self.log(f"  ✓ {service} service started", Colors.GREEN)
            else:
                self.log(f"  ✗ Failed to start {service}", Colors.RED)
                
        # Final status check
        self.log("\n📊 Final Status Check:", Colors.CYAN)
        final_status = self.check_status()
        
        self.log(f"\n{'='*60}", Colors.GREEN)
        self.log(f"    Deployment Complete for {self.robot_ip}!", Colors.GREEN)
        self.log(f"    Device ID: {device_info['device_id']}", Colors.GREEN)
        self.log(f"{'='*60}\n", Colors.GREEN)
        
        return True
        
def main():
    parser = argparse.ArgumentParser(description='LeKiwi Robot Deployment System')
    parser.add_argument('robot_ip', help='Target robot IP address')
    parser.add_argument('--username', default='lekiwi', help='SSH username')
    parser.add_argument('--password', default='lekiwi', help='SSH password')
    parser.add_argument('--source', default='192.168.88.21', help='Source robot for copying teleop')
    parser.add_argument('--action', default='full', choices=['full', 'check', 'teleop-only', 'install-conda', 'setup-env'],
                       help='Deployment action')
    
    args = parser.parse_args()
    
    deployer = LeKiwiDeployment(args.robot_ip, args.username, args.password)
    
    if args.action == 'check':
        deployer.get_device_info()
        deployer.check_status()
    elif args.action == 'teleop-only':
        deployer.configure_teleop()
    elif args.action == 'install-conda':
        # Install Miniconda only
        deployer.log(f"\n🐍 Installing Miniconda on {args.robot_ip}...", Colors.CYAN)
        success = deployer.install_miniconda_only()
        if success:
            deployer.log("✅ Miniconda installation completed", Colors.GREEN)
        else:
            deployer.log("❌ Miniconda installation failed", Colors.RED)
    elif args.action == 'setup-env':
        # Setup Python environment (conda env + LeRobot + LeKiwi)
        deployer.log(f"\n🔧 Setting up Python environment on {args.robot_ip}...", Colors.CYAN)
        success = deployer.setup_python_environment()
        if success:
            deployer.log("✅ Python environment setup completed", Colors.GREEN)
        else:
            deployer.log("❌ Python environment setup failed", Colors.RED)
    else:
        deployer.deploy_full(args.source)
        
if __name__ == "__main__":
    main()