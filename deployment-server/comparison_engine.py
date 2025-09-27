#!/usr/bin/env python3
"""
Robot Deployment Comparison Engine
Compares file deployments across robots to track versions and differences
"""

import os
import json
import hashlib
import difflib
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from datetime import datetime

class RobotFileComparison:
    """Engine for comparing robot deployments"""
    
    # Files to compare across robots
    COMPARISON_FILES = [
        "/opt/frodobots/teleop.sh",
        "/opt/frodobots/lekiwi.sh",
        "/etc/systemd/system/teleop.service",
        "/etc/systemd/system/lekiwi.service",
        "/home/lekiwi/lerobot/lerobot/common/robots/lekiwi/lekiwi_host.py",
        "/home/lekiwi/.bashrc",
    ]
    
    # Files to fetch but exclude from compliance checks (robot-specific)
    ROBOT_SPECIFIC_FILES = [
        "/opt/frodobots/teleop.ini",  # Has unique device IDs per robot
    ]
    
    # Binary files to check (compare checksums only)
    BINARY_FILES = [
        "/opt/frodobots/teleop_agent",
        "/opt/frodobots/lib/libteleop_media_gst.so",
        "/opt/frodobots/lib/libteleop_ctrl_zmq_ik.so",
    ]
    
    def __init__(self, cache_dir: str = "/tmp/robot_comparisons"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(exist_ok=True)
        self.baseline_version = "0.01"
        self.baseline_robots = ["192.168.88.21", "192.168.88.58", "192.168.88.62"]
        
    def fetch_robot_files(self, robot_ip: str, username: str = "lekiwi", password: str = "lekiwi") -> Dict:
        """Fetch all comparison files from a robot"""
        robot_data = {
            "ip": robot_ip,
            "timestamp": datetime.now().isoformat(),
            "files": {},
            "checksums": {},
            "errors": []
        }
        
        # Create cache directory for this robot
        robot_cache = self.cache_dir / robot_ip.replace(".", "_")
        robot_cache.mkdir(exist_ok=True)
        
        # Fetch all files (comparison + robot-specific)
        all_files = self.COMPARISON_FILES + self.ROBOT_SPECIFIC_FILES
        for filepath in all_files:
            local_path = robot_cache / Path(filepath).name
            # Increased timeout for slow Raspberry Pis
            cmd = f"sshpass -p {password} scp -o StrictHostKeyChecking=no -o ConnectTimeout=15 {username}@{robot_ip}:{filepath} {local_path} 2>/dev/null"
            result = subprocess.run(cmd, shell=True, capture_output=True, timeout=30)
            
            if result.returncode == 0:
                try:
                    with open(local_path, 'r') as f:
                        content = f.read()
                        robot_data["files"][filepath] = content
                        # Calculate checksum
                        robot_data["checksums"][filepath] = hashlib.sha256(content.encode()).hexdigest()
                except:
                    robot_data["errors"].append(f"Could not read {filepath}")
            else:
                # Check if file exists with adequate timeout
                check_cmd = f"sshpass -p {password} ssh -o StrictHostKeyChecking=no -o ConnectTimeout=15 {username}@{robot_ip} '[ -f {filepath} ] && echo exists'"
                check_result = subprocess.run(check_cmd, shell=True, capture_output=True, text=True, timeout=20)
                if "exists" not in check_result.stdout:
                    robot_data["files"][filepath] = None  # File doesn't exist
                else:
                    robot_data["errors"].append(f"Could not fetch {filepath}")
        
        # Fetch binary file checksums
        for filepath in self.BINARY_FILES:
            # Adequate timeout for checksum calculation on slow Pis
            cmd = f"sshpass -p {password} ssh -o StrictHostKeyChecking=no -o ConnectTimeout=15 {username}@{robot_ip} 'sha256sum {filepath} 2>/dev/null | cut -d\" \" -f1'"
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=25)
            
            if result.returncode == 0 and result.stdout.strip():
                robot_data["checksums"][filepath] = result.stdout.strip()
            else:
                # Check if file exists with adequate timeout
                check_cmd = f"sshpass -p {password} ssh -o StrictHostKeyChecking=no -o ConnectTimeout=15 {username}@{robot_ip} '[ -f {filepath} ] && echo exists'"
                check_result = subprocess.run(check_cmd, shell=True, capture_output=True, text=True, timeout=20)
                if "exists" not in check_result.stdout:
                    robot_data["checksums"][filepath] = None  # File doesn't exist
                    
        # Save to cache
        cache_file = self.cache_dir / f"{robot_ip.replace('.', '_')}.json"
        with open(cache_file, 'w') as f:
            json.dump(robot_data, f, indent=2)
            
        return robot_data
    
    def create_baseline(self) -> Dict:
        """Create baseline version 0.01 from working robots"""
        baseline = {
            "version": self.baseline_version,
            "created": datetime.now().isoformat(),
            "robots": self.baseline_robots,
            "files": {},
            "checksums": {}
        }
        
        # Fetch files from all baseline robots
        robot_data = {}
        for robot_ip in self.baseline_robots:
            print(f"Fetching baseline from {robot_ip}...")
            robot_data[robot_ip] = self.fetch_robot_files(robot_ip)
        
        # For each file, use the most common version as baseline
        all_files = set()
        for data in robot_data.values():
            all_files.update(data["files"].keys())
            all_files.update(data["checksums"].keys())
        
        for filepath in all_files:
            # Collect all versions of this file
            versions = {}
            checksums = {}
            
            for robot_ip, data in robot_data.items():
                if filepath in data["files"]:
                    content = data["files"][filepath]
                    if content is not None:
                        checksum = hashlib.sha256(content.encode()).hexdigest()
                        if checksum not in versions:
                            versions[checksum] = {"content": content, "robots": []}
                        versions[checksum]["robots"].append(robot_ip)
                elif filepath in data["checksums"]:
                    checksum = data["checksums"][filepath]
                    if checksum is not None:
                        if checksum not in checksums:
                            checksums[checksum] = []
                        checksums[checksum].append(robot_ip)
            
            # Use the most common version as baseline
            if versions:
                # Find version present on most robots
                best_version = max(versions.items(), key=lambda x: len(x[1]["robots"]))
                baseline["files"][filepath] = best_version[1]["content"]
                baseline["checksums"][filepath] = best_version[0]
            elif checksums:
                # For binary files
                best_checksum = max(checksums.items(), key=lambda x: len(x[1]))
                baseline["checksums"][filepath] = best_checksum[0]
        
        # Save baseline
        baseline_file = self.cache_dir / "baseline_v0.01.json"
        with open(baseline_file, 'w') as f:
            json.dump(baseline, f, indent=2)
            
        return baseline
    
    def compare_robots(self, robot1_ip: str, robot2_ip: str) -> Dict:
        """Compare two robots' deployments"""
        # Fetch data from both robots
        robot1_data = self.fetch_robot_files(robot1_ip)
        robot2_data = self.fetch_robot_files(robot2_ip)
        
        comparison = {
            "robot1": robot1_ip,
            "robot2": robot2_ip,
            "timestamp": datetime.now().isoformat(),
            "differences": [],
            "identical_files": [],
            "missing_files": {
                "robot1_missing": [],
                "robot2_missing": []
            }
        }
        
        # Compare all files
        all_files = set()
        all_files.update(robot1_data["files"].keys())
        all_files.update(robot2_data["files"].keys())
        all_files.update(robot1_data["checksums"].keys())
        all_files.update(robot2_data["checksums"].keys())
        
        for filepath in all_files:
            # Text files - compare content
            if filepath in robot1_data["files"] or filepath in robot2_data["files"]:
                file1 = robot1_data["files"].get(filepath)
                file2 = robot2_data["files"].get(filepath)
                
                if file1 is None and file2 is None:
                    continue
                elif file1 is None:
                    comparison["missing_files"]["robot1_missing"].append(filepath)
                elif file2 is None:
                    comparison["missing_files"]["robot2_missing"].append(filepath)
                elif file1 == file2:
                    comparison["identical_files"].append(filepath)
                else:
                    # Generate diff
                    diff = list(difflib.unified_diff(
                        file1.splitlines(keepends=True),
                        file2.splitlines(keepends=True),
                        fromfile=f"{robot1_ip}:{filepath}",
                        tofile=f"{robot2_ip}:{filepath}",
                        n=3
                    ))
                    
                    comparison["differences"].append({
                        "file": filepath,
                        "type": "content",
                        "diff": ''.join(diff)
                    })
            
            # Binary files - compare checksums
            elif filepath in robot1_data["checksums"] or filepath in robot2_data["checksums"]:
                checksum1 = robot1_data["checksums"].get(filepath)
                checksum2 = robot2_data["checksums"].get(filepath)
                
                if checksum1 is None and checksum2 is None:
                    continue
                elif checksum1 is None:
                    comparison["missing_files"]["robot1_missing"].append(filepath)
                elif checksum2 is None:
                    comparison["missing_files"]["robot2_missing"].append(filepath)
                elif checksum1 == checksum2:
                    comparison["identical_files"].append(filepath)
                else:
                    comparison["differences"].append({
                        "file": filepath,
                        "type": "binary",
                        "checksum1": checksum1,
                        "checksum2": checksum2
                    })
        
        return comparison
    
    def compare_to_baseline(self, robot_ip: str) -> Dict:
        """Compare a robot to the baseline version"""
        # Load baseline
        baseline_file = self.cache_dir / "baseline_v0.01.json"
        if not baseline_file.exists():
            self.create_baseline()
        
        with open(baseline_file, 'r') as f:
            baseline = json.load(f)
        
        # Fetch robot data
        robot_data = self.fetch_robot_files(robot_ip)
        
        comparison = {
            "robot": robot_ip,
            "baseline_version": baseline["version"],
            "timestamp": datetime.now().isoformat(),
            "status": "compliant",  # Will be set to non-compliant if differences found
            "differences": [],
            "missing_files": [],
            "extra_files": []
        }
        
        # Check all baseline files (excluding robot-specific ones)
        for filepath, baseline_content in baseline["files"].items():
            # Skip robot-specific files in compliance check
            if filepath in self.ROBOT_SPECIFIC_FILES:
                continue
                
            robot_content = robot_data["files"].get(filepath)
            
            if robot_content is None:
                comparison["missing_files"].append(filepath)
                comparison["status"] = "non-compliant"
            elif robot_content != baseline_content:
                diff = list(difflib.unified_diff(
                    baseline_content.splitlines(keepends=True),
                    robot_content.splitlines(keepends=True),
                    fromfile=f"baseline:{filepath}",
                    tofile=f"{robot_ip}:{filepath}",
                    n=3
                ))
                comparison["differences"].append({
                    "file": filepath,
                    "diff": ''.join(diff)
                })
                comparison["status"] = "non-compliant"
        
        # Check binary files (excluding robot-specific ones)
        for filepath, baseline_checksum in baseline["checksums"].items():
            # Skip robot-specific files in compliance check
            if filepath in self.ROBOT_SPECIFIC_FILES:
                continue
                
            if filepath not in baseline["files"]:  # Skip if already checked as text file
                robot_checksum = robot_data["checksums"].get(filepath)
                
                if robot_checksum is None:
                    comparison["missing_files"].append(filepath)
                    comparison["status"] = "non-compliant"
                elif robot_checksum != baseline_checksum:
                    comparison["differences"].append({
                        "file": filepath,
                        "type": "binary",
                        "baseline_checksum": baseline_checksum,
                        "robot_checksum": robot_checksum
                    })
                    comparison["status"] = "non-compliant"
        
        return comparison

# Standalone functions for API use
def create_baseline_deployment():
    """Create baseline version 0.01"""
    engine = RobotFileComparison()
    return engine.create_baseline()

def compare_robot_deployments(robot1_ip: str, robot2_ip: str):
    """Compare two robots"""
    engine = RobotFileComparison()
    return engine.compare_robots(robot1_ip, robot2_ip)

def compare_robot_to_baseline(robot_ip: str):
    """Compare robot to baseline"""
    engine = RobotFileComparison()
    return engine.compare_to_baseline(robot_ip)