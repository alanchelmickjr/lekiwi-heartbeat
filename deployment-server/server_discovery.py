#!/usr/bin/env python3
"""
Parallel Staged Discovery Module for LeKiwi Deploy Server
Implements true parallel discovery with staged validation
"""

import asyncio
import json
import time
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, asdict
from enum import Enum
from concurrent.futures import ThreadPoolExecutor
import paramiko
import socket
import subprocess
from datetime import datetime
from pathlib import Path

# Discovery stages
class DiscoveryStage(Enum):
    AWAKE = "awake"  # Stage 1: Network/ping check
    TYPE = "type"  # Stage 2: Detect robot type (Lekiwi/XLE/blank Pi)
    SOFTWARE = "software"  # Stage 3: Check installed components
    VIDEO = "video"  # Stage 4: Camera/stream status
    TELEOP_HOST = "teleop_host"  # Stage 5: Service ready
    TELEOP_OPERATION = "teleop_operation"  # Stage 6: Actually being controlled

@dataclass
class RobotDiscoveryStatus:
    """Status of a robot through discovery stages"""
    ip: str
    hostname: Optional[str] = None
    robot_type: Optional[str] = None  # lekiwi, xlerobot, blank_pi, unknown
    is_valid_robot: bool = False
    stages: Dict[str, Dict[str, Any]] = None
    last_updated: float = 0
    
    def __post_init__(self):
        if self.stages is None:
            self.stages = {
                DiscoveryStage.AWAKE.value: {"status": "pending", "message": "Not checked"},
                DiscoveryStage.TYPE.value: {"status": "pending", "message": "Not checked"},
                DiscoveryStage.SOFTWARE.value: {"status": "pending", "message": "Not checked"},
                DiscoveryStage.VIDEO.value: {"status": "pending", "message": "Not checked"},
                DiscoveryStage.TELEOP_HOST.value: {"status": "pending", "message": "Not checked"},
                DiscoveryStage.TELEOP_OPERATION.value: {"status": "pending", "message": "Not checked"},
            }
        self.last_updated = time.time()

class ParallelDiscovery:
    """Handles parallel staged discovery of robots"""
    
    def __init__(self, max_workers: int = 30):
        self.max_workers = max_workers
        self.robots: Dict[str, RobotDiscoveryStatus] = {}
        self.discovery_running = False
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        
    async def discover_network(self, network: str = "192.168.88", start: int = 1, end: int = 254) -> Dict[str, Any]:
        """
        Perform full parallel discovery of network
        Returns discovery results with staged status for each robot
        """
        self.discovery_running = True
        self.robots.clear()
        
        # Generate IP list
        ips = [f"{network}.{i}" for i in range(start, end + 1)]
        
        # Stage 1: Parallel network scan (AWAKE check)
        print(f"🔍 Stage 1: Scanning {len(ips)} IPs for network connectivity...")
        awake_robots = await self._stage1_awake_check(ips)
        
        if not awake_robots:
            self.discovery_running = False
            return self._get_discovery_results()
        
        # Stage 2: Parallel type detection
        print(f"🤖 Stage 2: Detecting robot types for {len(awake_robots)} hosts...")
        typed_robots = await self._stage2_type_detection(awake_robots)
        
        # Filter out blank Pis and non-robots
        valid_robots = [ip for ip in typed_robots if self.robots[ip].is_valid_robot]
        
        if not valid_robots:
            self.discovery_running = False
            return self._get_discovery_results()
        
        # Stage 3: Parallel software check
        print(f"💾 Stage 3: Checking software on {len(valid_robots)} robots...")
        await self._stage3_software_check(valid_robots)
        
        # Stage 4: Parallel video check
        print(f"📷 Stage 4: Checking cameras on {len(valid_robots)} robots...")
        await self._stage4_video_check(valid_robots)
        
        # Stage 5: Parallel teleop host check
        print(f"🎮 Stage 5: Checking teleop services on {len(valid_robots)} robots...")
        await self._stage5_teleop_host_check(valid_robots)
        
        # Stage 6: Parallel teleop operation check
        print(f"🕹️ Stage 6: Checking active teleoperation on {len(valid_robots)} robots...")
        await self._stage6_teleop_operation_check(valid_robots)
        
        self.discovery_running = False
        return self._get_discovery_results()
    
    async def _stage1_awake_check(self, ips: List[str]) -> List[str]:
        """Stage 1: Check which IPs respond to network requests"""
        loop = asyncio.get_event_loop()
        
        async def check_awake(ip: str) -> Optional[str]:
            try:
                # Quick TCP check on port 22 (SSH)
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(2)  # 2 second timeout
                result = await loop.run_in_executor(
                    self.executor,
                    sock.connect_ex,
                    (ip, 22)
                )
                sock.close()
                
                if result == 0:
                    # Host is awake and has SSH
                    if ip not in self.robots:
                        self.robots[ip] = RobotDiscoveryStatus(ip=ip)
                    
                    self.robots[ip].stages[DiscoveryStage.AWAKE.value] = {
                        "status": "success",
                        "message": "SSH port open",
                        "timestamp": time.time()
                    }
                    return ip
                else:
                    # Try ping as fallback
                    ping_result = await loop.run_in_executor(
                        self.executor,
                        subprocess.run,
                        ["ping", "-c", "1", "-W", "1", ip],
                        {"capture_output": True}
                    )
                    
                    if ping_result.returncode == 0:
                        if ip not in self.robots:
                            self.robots[ip] = RobotDiscoveryStatus(ip=ip)
                        
                        self.robots[ip].stages[DiscoveryStage.AWAKE.value] = {
                            "status": "partial",
                            "message": "Responds to ping but no SSH",
                            "timestamp": time.time()
                        }
                        return None  # Don't include non-SSH hosts
            except Exception as e:
                pass
            
            return None
        
        # Run all checks in parallel
        tasks = [check_awake(ip) for ip in ips]
        results = await asyncio.gather(*tasks)
        
        # Filter out None results
        return [ip for ip in results if ip is not None]
    
    async def _stage2_type_detection(self, ips: List[str]) -> List[str]:
        """Stage 2: Detect what type of device each IP is"""
        loop = asyncio.get_event_loop()
        
        async def detect_type(ip: str) -> str:
            try:
                # Try SSH connection to check system
                client = paramiko.SSHClient()
                client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                
                def ssh_check():
                    try:
                        client.connect(ip, username='lekiwi', password='lekiwi', timeout=5)
                        
                        # Get hostname
                        stdin, stdout, stderr = client.exec_command('hostname')
                        hostname = stdout.read().decode().strip()
                        self.robots[ip].hostname = hostname
                        
                        # Check if it's a Raspberry Pi
                        stdin, stdout, stderr = client.exec_command('cat /proc/device-tree/model 2>/dev/null')
                        model = stdout.read().decode().strip()
                        is_pi = 'Raspberry Pi' in model
                        
                        # Check for robot software
                        checks = {
                            'lekiwi': 'ls /opt/frodobots/teleop 2>/dev/null | grep -q teleop',
                            'xlerobot': 'ls /opt/frodobots/lib/libteleop_*xlerobot*.so 2>/dev/null | wc -l',
                            'lerobot': 'test -d /home/lekiwi/lerobot',
                            'conda': 'test -d /home/lekiwi/miniconda3',
                            'systemd': 'systemctl list-units --no-pager | grep -E "(teleop|lekiwi)"'
                        }
                        
                        results = {}
                        for key, cmd in checks.items():
                            stdin, stdout, stderr = client.exec_command(cmd)
                            exit_status = stdout.channel.recv_exit_status()
                            output = stdout.read().decode().strip()
                            
                            if key == 'xlerobot':
                                results[key] = output.isdigit() and int(output) > 0
                            else:
                                results[key] = exit_status == 0
                        
                        client.close()
                        
                        # Determine robot type
                        if results.get('xlerobot'):
                            robot_type = 'xlerobot'
                            is_valid = True
                        elif results.get('lekiwi') or results.get('lerobot'):
                            robot_type = 'lekiwi'
                            is_valid = True
                        elif is_pi and not any([results.get('lekiwi'), results.get('lerobot'), results.get('conda')]):
                            robot_type = 'blank_pi'
                            is_valid = False  # Blank Pi is not a valid robot
                        else:
                            robot_type = 'unknown'
                            is_valid = False
                        
                        self.robots[ip].robot_type = robot_type
                        self.robots[ip].is_valid_robot = is_valid
                        
                        self.robots[ip].stages[DiscoveryStage.TYPE.value] = {
                            "status": "success" if is_valid else "warning",
                            "message": f"Detected as {robot_type}",
                            "details": {
                                "hostname": hostname,
                                "is_pi": is_pi,
                                "has_lekiwi": results.get('lekiwi', False),
                                "has_xlerobot": results.get('xlerobot', False),
                                "has_lerobot": results.get('lerobot', False),
                                "has_conda": results.get('conda', False)
                            },
                            "timestamp": time.time()
                        }
                        
                        return robot_type
                        
                    except Exception as e:
                        self.robots[ip].stages[DiscoveryStage.TYPE.value] = {
                            "status": "error",
                            "message": f"SSH failed: {str(e)}",
                            "timestamp": time.time()
                        }
                        return 'unknown'
                
                result = await loop.run_in_executor(self.executor, ssh_check)
                return ip
                
            except Exception as e:
                self.robots[ip].stages[DiscoveryStage.TYPE.value] = {
                    "status": "error",
                    "message": str(e),
                    "timestamp": time.time()
                }
                return ip
        
        # Run all type detections in parallel
        tasks = [detect_type(ip) for ip in ips]
        await asyncio.gather(*tasks)
        
        return ips
    
    async def _stage3_software_check(self, ips: List[str]) -> None:
        """Stage 3: Check installed software components"""
        loop = asyncio.get_event_loop()
        
        async def check_software(ip: str) -> None:
            try:
                client = paramiko.SSHClient()
                client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                
                def ssh_check():
                    try:
                        client.connect(ip, username='lekiwi', password='lekiwi', timeout=5)
                        
                        # Detailed software checks
                        software_checks = {
                            'miniconda': 'test -d /home/lekiwi/miniconda3 && echo "installed"',
                            'lerobot_env': 'test -d /home/lekiwi/miniconda3/envs/lerobot && echo "installed"',
                            'lekiwi_package': 'test -d /home/lekiwi/lerobot/lekiwi && echo "installed"',
                            'teleop_binary': 'test -f /opt/frodobots/teleop && echo "installed"',
                            'systemd_teleop': 'systemctl is-enabled teleop 2>/dev/null',
                            'systemd_lekiwi': 'systemctl is-enabled lekiwi 2>/dev/null'
                        }
                        
                        results = {}
                        for key, cmd in software_checks.items():
                            stdin, stdout, stderr = client.exec_command(cmd)
                            output = stdout.read().decode().strip()
                            results[key] = 'installed' in output or 'enabled' in output
                        
                        client.close()
                        
                        # Determine software status
                        all_installed = all([
                            results.get('teleop_binary'),
                            results.get('systemd_teleop') or results.get('systemd_lekiwi')
                        ])
                        
                        self.robots[ip].stages[DiscoveryStage.SOFTWARE.value] = {
                            "status": "success" if all_installed else "warning",
                            "message": "All components installed" if all_installed else "Missing components",
                            "components": results,
                            "timestamp": time.time()
                        }
                        
                    except Exception as e:
                        self.robots[ip].stages[DiscoveryStage.SOFTWARE.value] = {
                            "status": "error",
                            "message": str(e),
                            "timestamp": time.time()
                        }
                
                await loop.run_in_executor(self.executor, ssh_check)
                
            except Exception as e:
                self.robots[ip].stages[DiscoveryStage.SOFTWARE.value] = {
                    "status": "error",
                    "message": str(e),
                    "timestamp": time.time()
                }
        
        # Run all software checks in parallel
        tasks = [check_software(ip) for ip in ips]
        await asyncio.gather(*tasks)
    
    async def _stage4_video_check(self, ips: List[str]) -> None:
        """Stage 4: Check camera/video status"""
        loop = asyncio.get_event_loop()
        
        async def check_video(ip: str) -> None:
            try:
                client = paramiko.SSHClient()
                client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                
                def ssh_check():
                    try:
                        client.connect(ip, username='lekiwi', password='lekiwi', timeout=5)
                        
                        # Check for video devices
                        stdin, stdout, stderr = client.exec_command('ls /dev/video* 2>/dev/null | wc -l')
                        num_cameras = int(stdout.read().decode().strip() or 0)
                        
                        # Check if streaming is possible
                        stdin, stdout, stderr = client.exec_command('which ffmpeg 2>/dev/null')
                        has_ffmpeg = stdout.read().decode().strip() != ''
                        
                        # Check for active streams
                        stdin, stdout, stderr = client.exec_command('ps aux | grep -E "(ffmpeg|gstreamer)" | grep -v grep | wc -l')
                        active_streams = int(stdout.read().decode().strip() or 0)
                        
                        client.close()
                        
                        self.robots[ip].stages[DiscoveryStage.VIDEO.value] = {
                            "status": "success" if num_cameras > 0 else "warning",
                            "message": f"{num_cameras} camera(s) detected",
                            "details": {
                                "camera_count": num_cameras,
                                "has_ffmpeg": has_ffmpeg,
                                "active_streams": active_streams
                            },
                            "timestamp": time.time()
                        }
                        
                    except Exception as e:
                        self.robots[ip].stages[DiscoveryStage.VIDEO.value] = {
                            "status": "error",
                            "message": str(e),
                            "timestamp": time.time()
                        }
                
                await loop.run_in_executor(self.executor, ssh_check)
                
            except Exception as e:
                self.robots[ip].stages[DiscoveryStage.VIDEO.value] = {
                    "status": "error",
                    "message": str(e),
                    "timestamp": time.time()
                }
        
        # Run all video checks in parallel
        tasks = [check_video(ip) for ip in ips]
        await asyncio.gather(*tasks)
    
    async def _stage5_teleop_host_check(self, ips: List[str]) -> None:
        """Stage 5: Check if teleop service is ready (HOST status)"""
        loop = asyncio.get_event_loop()
        
        async def check_teleop_host(ip: str) -> None:
            try:
                client = paramiko.SSHClient()
                client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                
                def ssh_check():
                    try:
                        client.connect(ip, username='lekiwi', password='lekiwi', timeout=5)
                        
                        # Check service status
                        stdin, stdout, stderr = client.exec_command('systemctl is-active teleop 2>/dev/null')
                        teleop_active = stdout.read().decode().strip() == 'active'
                        
                        stdin, stdout, stderr = client.exec_command('systemctl is-active lekiwi 2>/dev/null')
                        lekiwi_active = stdout.read().decode().strip() == 'active'
                        
                        # Check if port 5558 is listening (teleop port)
                        stdin, stdout, stderr = client.exec_command('ss -tuln | grep -q :5558 && echo "listening"')
                        port_listening = stdout.read().decode().strip() == 'listening'
                        
                        client.close()
                        
                        is_ready = (teleop_active or lekiwi_active) and port_listening
                        
                        self.robots[ip].stages[DiscoveryStage.TELEOP_HOST.value] = {
                            "status": "success" if is_ready else "warning",
                            "message": "Teleop service ready" if is_ready else "Service not ready",
                            "details": {
                                "teleop_service": teleop_active,
                                "lekiwi_service": lekiwi_active,
                                "port_5558": port_listening
                            },
                            "timestamp": time.time()
                        }
                        
                    except Exception as e:
                        self.robots[ip].stages[DiscoveryStage.TELEOP_HOST.value] = {
                            "status": "error",
                            "message": str(e),
                            "timestamp": time.time()
                        }
                
                await loop.run_in_executor(self.executor, ssh_check)
                
            except Exception as e:
                self.robots[ip].stages[DiscoveryStage.TELEOP_HOST.value] = {
                    "status": "error",
                    "message": str(e),
                    "timestamp": time.time()
                }
        
        # Run all teleop host checks in parallel
        tasks = [check_teleop_host(ip) for ip in ips]
        await asyncio.gather(*tasks)
    
    async def _stage6_teleop_operation_check(self, ips: List[str]) -> None:
        """Stage 6: Check if robot is actually being teleoperated (OPERATION status)"""
        loop = asyncio.get_event_loop()
        
        async def check_teleop_operation(ip: str) -> None:
            try:
                client = paramiko.SSHClient()
                client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                
                def ssh_check():
                    try:
                        client.connect(ip, username='lekiwi', password='lekiwi', timeout=5)
                        
                        # Check for active teleoperation connections
                        # Look for established connections on teleop ports
                        stdin, stdout, stderr = client.exec_command('ss -tn | grep -E ":5558|:5559" | grep ESTAB | wc -l')
                        active_connections = int(stdout.read().decode().strip() or 0)
                        
                        # Check CPU usage of teleop process (if being operated, CPU will be higher)
                        stdin, stdout, stderr = client.exec_command("ps aux | grep '[t]eleop' | awk '{print $3}' | head -1")
                        cpu_usage = stdout.read().decode().strip()
                        cpu_percent = float(cpu_usage) if cpu_usage else 0.0
                        
                        # Check for recent activity in logs
                        stdin, stdout, stderr = client.exec_command('journalctl -u teleop --since "1 minute ago" --no-pager 2>/dev/null | wc -l')
                        recent_logs = int(stdout.read().decode().strip() or 0)
                        
                        client.close()
                        
                        # Determine if actively being operated
                        is_operated = active_connections > 0 and (cpu_percent > 5.0 or recent_logs > 10)
                        
                        self.robots[ip].stages[DiscoveryStage.TELEOP_OPERATION.value] = {
                            "status": "active" if is_operated else "idle",
                            "message": "Being teleoperated" if is_operated else "Idle (not operated)",
                            "details": {
                                "active_connections": active_connections,
                                "cpu_usage": cpu_percent,
                                "recent_activity": recent_logs > 10
                            },
                            "timestamp": time.time()
                        }
                        
                    except Exception as e:
                        self.robots[ip].stages[DiscoveryStage.TELEOP_OPERATION.value] = {
                            "status": "error",
                            "message": str(e),
                            "timestamp": time.time()
                        }
                
                await loop.run_in_executor(self.executor, ssh_check)
                
            except Exception as e:
                self.robots[ip].stages[DiscoveryStage.TELEOP_OPERATION.value] = {
                    "status": "error",
                    "message": str(e),
                    "timestamp": time.time()
                }
        
        # Run all teleop operation checks in parallel
        tasks = [check_teleop_operation(ip) for ip in ips]
        await asyncio.gather(*tasks)
    
    def _get_discovery_results(self) -> Dict[str, Any]:
        """Get current discovery results"""
        return {
            "timestamp": time.time(),
            "total_scanned": len(self.robots),
            "valid_robots": sum(1 for r in self.robots.values() if r.is_valid_robot),
            "blank_pis": sum(1 for r in self.robots.values() if r.robot_type == 'blank_pi'),
            "robots": {
                ip: {
                    "ip": robot.ip,
                    "hostname": robot.hostname,
                    "type": robot.robot_type,
                    "is_valid": robot.is_valid_robot,
                    "stages": robot.stages,
                    "last_updated": robot.last_updated
                }
                for ip, robot in self.robots.items()
            }
        }
    
    async def update_single_robot(self, ip: str) -> Dict[str, Any]:
        """Update status for a single robot through all stages"""
        if ip not in self.robots:
            self.robots[ip] = RobotDiscoveryStatus(ip=ip)
        
        # Run through all stages for this single robot
        await self._stage1_awake_check([ip])
        
        if self.robots[ip].stages[DiscoveryStage.AWAKE.value]["status"] == "success":
            await self._stage2_type_detection([ip])
            
            if self.robots[ip].is_valid_robot:
                await self._stage3_software_check([ip])
                await self._stage4_video_check([ip])
                await self._stage5_teleop_host_check([ip])
                await self._stage6_teleop_operation_check([ip])
        
        return {
            "ip": self.robots[ip].ip,
            "hostname": self.robots[ip].hostname,
            "type": self.robots[ip].robot_type,
            "is_valid": self.robots[ip].is_valid_robot,
            "stages": self.robots[ip].stages,
            "last_updated": self.robots[ip].last_updated
        }

# Global discovery instance
discovery_engine = ParallelDiscovery()