#!/usr/bin/env python3
"""
Detect robot type (LeKiwi vs XLERobot) by checking system characteristics
"""

import subprocess
import json
import os
import re
import glob

# Configurable timeouts for robot type detection
SSH_CONNECT_TIMEOUT = int(os.getenv('ROBOT_SSH_CONNECT_TIMEOUT', '15'))  # Increased from 5 to 15 seconds
SSH_COMMAND_TIMEOUT = int(os.getenv('ROBOT_SSH_COMMAND_TIMEOUT', '20'))  # Increased from 5 to 20 seconds

def detect_ama_boards():
    """
    Detect ALL AMA board variants (AMA00-AMA99 and other patterns)
    Checks for:
    1. Waveshare UART servo boards via USB
    2. /dev/ttyAMA* serial ports (Raspberry Pi UART)
    3. /dev/ttyACM* ports (USB CDC ACM devices)
    
    Returns: List of detected board identifiers with their device paths
    """
    detected_boards = []
    
    try:
        # Check for USB devices from Waveshare
        # Using lsusb to find Waveshare devices
        try:
            lsusb_result = subprocess.run(['lsusb'], capture_output=True, text=True, timeout=5)
            if lsusb_result.returncode == 0:
                # Look for Waveshare or common UART chip vendors
                for line in lsusb_result.stdout.splitlines():
                    if any(vendor in line.lower() for vendor in ['waveshare', 'ftdi', 'ch340', 'cp210', 'pl2303']):
                        # Extract USB ID and vendor info
                        match = re.search(r'Bus \d+ Device \d+: ID ([0-9a-f:]+)\s+(.+)', line)
                        if match:
                            usb_id = match.group(1)
                            description = match.group(2)
                            detected_boards.append({
                                'type': 'USB',
                                'id': usb_id,
                                'description': description,
                                'device': 'USB device'
                            })
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
        
        # Check /dev/ttyAMA* devices (Raspberry Pi UART)
        ttyama_devices = glob.glob('/dev/ttyAMA*')
        for device in ttyama_devices:
            # Extract the AMA variant number/pattern
            match = re.match(r'/dev/ttyAMA(\w+)', device)
            if match:
                variant = match.group(1)
                board_id = f"AMA{variant}"
                
                # Check if device is accessible
                if os.path.exists(device):
                    detected_boards.append({
                        'type': 'Serial',
                        'id': board_id,
                        'device': device,
                        'description': f'AMA board variant {variant}'
                    })
        
        # Check /dev/ttyACM* devices (USB CDC ACM)
        ttyacm_devices = glob.glob('/dev/ttyACM*')
        for device in ttyacm_devices:
            # Extract the ACM number
            match = re.match(r'/dev/ttyACM(\d+)', device)
            if match:
                acm_num = match.group(1)
                
                # Try to get more info about the device
                device_info = "Unknown ACM device"
                try:
                    # Check if it's a potential AMA board by looking at device attributes
                    udevadm_cmd = f"udevadm info -q all -n {device} 2>/dev/null"
                    udev_result = subprocess.run(udevadm_cmd, shell=True, capture_output=True, text=True, timeout=2)
                    if udev_result.returncode == 0:
                        # Look for Waveshare or servo-related identifiers
                        if any(keyword in udev_result.stdout.lower() for keyword in ['waveshare', 'servo', 'uart', 'ama']):
                            device_info = "Potential AMA board (ACM)"
                            # Try to extract model info
                            model_match = re.search(r'ID_MODEL=([^\n]+)', udev_result.stdout)
                            if model_match:
                                device_info = f"AMA board: {model_match.group(1)}"
                except:
                    pass
                
                detected_boards.append({
                    'type': 'ACM',
                    'id': f'ACM{acm_num}',
                    'device': device,
                    'description': device_info
                })
        
        # Check for any other AMA-pattern devices
        # Look for devices that might be named differently
        all_tty_devices = glob.glob('/dev/tty*')
        ama_pattern = re.compile(r'/dev/tty.*AMA.*', re.IGNORECASE)
        
        for device in all_tty_devices:
            if ama_pattern.match(device) and device not in [b['device'] for b in detected_boards if 'device' in b]:
                # Extract the AMA identifier
                ama_match = re.search(r'AMA(\w+)', device, re.IGNORECASE)
                if ama_match:
                    variant = ama_match.group(1)
                    detected_boards.append({
                        'type': 'Other',
                        'id': f'AMA{variant}',
                        'device': device,
                        'description': f'Alternative AMA board variant {variant}'
                    })
        
        # Also check for boards that might be connected via I2C or SPI
        # These might show up in /sys/class/
        try:
            # Check I2C devices
            i2c_devices = glob.glob('/sys/class/i2c-dev/i2c-*')
            for i2c_dev in i2c_devices:
                # Look for AMA-related entries
                device_name_path = os.path.join(i2c_dev, 'device', 'name')
                if os.path.exists(device_name_path):
                    with open(device_name_path, 'r') as f:
                        name = f.read().strip()
                        if 'ama' in name.lower():
                            i2c_num = os.path.basename(i2c_dev).replace('i2c-', '')
                            detected_boards.append({
                                'type': 'I2C',
                                'id': f'AMA-I2C{i2c_num}',
                                'device': i2c_dev,
                                'description': f'I2C AMA board: {name}'
                            })
        except:
            pass
        
    except Exception as e:
        print(f"Error detecting AMA boards: {e}")
    
    # Remove duplicates based on device path
    unique_boards = {}
    for board in detected_boards:
        key = board.get('device', board.get('id'))
        if key not in unique_boards:
            unique_boards[key] = board
    
    return list(unique_boards.values())

def detect_robot_type(robot_ip):
    """
    Detect if a robot is regular LeKiwi or XLERobot
    XLERobot identified by multiple methods:
    1. Presence of XLEROBOT-specific libraries in /opt/frodobots/lib/
    2. Known XLE IP addresses (hardcoded list)
    3. AMA board detection (hardware-based)
    4. Camera count (3+ cameras = XLE)
    5. Hostname pattern containing 'xlerobot' (last resort)
    Returns: 'xlerobot', 'lekiwi', 'lekiwi-lite', or 'unknown'
    """
    # Known XLE robot IPs (ONLY confirmed XLE robots)
    KNOWN_XLE_IPS = [
        '192.168.88.27',  # Confirmed XLE (software-sick)
        '192.168.88.29',  # Confirmed XLE
        # DO NOT add regular LeKiwi robots here!
    ]
    
    # Check if this is a known XLE IP first
    if robot_ip in KNOWN_XLE_IPS:
        print(f"Detected XLEROBOT at {robot_ip} (known XLE IP)")
        return 'xlerobot'
    
    try:
        # METHOD 1: Check for XLEROBOT-specific libraries (most reliable for properly configured XLE)
        # XLEROBOTs have libteleop_*_xlerobot.so files
        # Using adequate timeout for slow Raspberry Pis
        cmd = f"sshpass -p lekiwi ssh -o StrictHostKeyChecking=no -o ConnectTimeout={SSH_CONNECT_TIMEOUT} lekiwi@{robot_ip} 'ls /opt/frodobots/lib/libteleop_*xlerobot*.so 2>/dev/null | wc -l'"
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=SSH_COMMAND_TIMEOUT)
        
        if result.returncode == 0 and result.stdout:
            xlerobot_lib_count = result.stdout.strip()
            if xlerobot_lib_count.isdigit() and int(xlerobot_lib_count) > 0:
                # XLEROBOT-specific libraries found - this is an XLEROBOT
                print(f"Detected XLEROBOT at {robot_ip} (has XLEROBOT-specific libraries)")
                return 'xlerobot'
        
        # METHOD 2: Check for AMA boards (hardware detection for XLE)
        # XLE robots typically have 4 AMA boards for dual-arm control
        # Regular LeKiwi only has 1-2 AMA boards
        ama_boards = detect_ama_boards_remote(robot_ip)
        if ama_boards and len(ama_boards) >= 4:  # XLE robots have 4 AMA boards
            print(f"Detected XLEROBOT at {robot_ip} (has {len(ama_boards)} AMA boards)")
            return 'xlerobot'
        
        # METHOD 3: Check camera count (XLE has exactly 3 cameras, LeKiwi has 2)
        # Skip this check - it's unreliable due to video device numbering
        # cmd = f"sshpass -p lekiwi ssh -o StrictHostKeyChecking=no -o ConnectTimeout={SSH_CONNECT_TIMEOUT} lekiwi@{robot_ip} 'ls /dev/video* 2>/dev/null | wc -l'"
        # This method is disabled - too unreliable
        
        # METHOD 4: Check for dual-arm configuration files
        cmd = f"sshpass -p lekiwi ssh -o StrictHostKeyChecking=no -o ConnectTimeout={SSH_CONNECT_TIMEOUT} lekiwi@{robot_ip} 'ls /opt/frodobots/config/*bimanual* /opt/frodobots/config/*dual* 2>/dev/null | wc -l'"
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=SSH_COMMAND_TIMEOUT)
        
        if result.returncode == 0 and result.stdout:
            config_count = result.stdout.strip()
            if config_count.isdigit() and int(config_count) > 0:
                print(f"Detected XLEROBOT at {robot_ip} (has dual-arm configuration)")
                return 'xlerobot'
        
        # METHOD 5: Hostname pattern (disabled - causes false positives)
        # Hostnames can be incorrect/renamed, so this is unreliable
        # Only use the methods above for accurate detection
        
        # If none of the XLE detection methods worked, check for regular LeKiwi
        # Check binary size AND control library together for other robot types
        cmd = f"sshpass -p lekiwi ssh -o StrictHostKeyChecking=no -o ConnectTimeout={SSH_CONNECT_TIMEOUT} lekiwi@{robot_ip} 'stat -c %s /opt/frodobots/teleop_agent 2>/dev/null; grep ctrl /opt/frodobots/teleop.ini 2>/dev/null'"
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=SSH_COMMAND_TIMEOUT)
        
        if result.returncode == 0 and result.stdout:
            lines = result.stdout.strip().split('\n')
            binary_size = 0
            ctrl_lib = ""
            
            if lines[0].isdigit():
                binary_size = int(lines[0])
            if len(lines) > 1:
                ctrl_lib = lines[1]
            
            # Classify based on combination
            if binary_size > 5000000:  # > 5MB = Full LeKiwi
                return 'lekiwi'
            elif binary_size < 2000000 and binary_size > 0:  # < 2MB
                # Small binary - check for IK library
                if '_ik' not in ctrl_lib:
                    return 'lekiwi-lite'  # No IK = lite version
                else:
                    return 'lekiwi-lite'  # Has IK but small binary
                
    except Exception as e:
        print(f"Error detecting robot type for {robot_ip}: {e}")
    
    # Default to lekiwi if we can't determine (better than unknown for UI)
    return 'lekiwi'

def get_robot_capabilities(robot_ip):
    """
    Get detailed robot capabilities based on type
    XLERobot is the advanced bimanual (dual-arm) version with 3 cameras
    Detected by multiple methods including hardware detection
    """
    robot_type = detect_robot_type(robot_ip)
    
    # XLERobot detected by multiple methods
    is_xle = robot_type == 'xlerobot'
    
    # Get AMA board information
    ama_boards = []
    try:
        ama_boards = detect_ama_boards_remote(robot_ip)
    except:
        pass
    
    # Get camera devices with enumeration
    camera_devices = {}
    try:
        cmd = f"sshpass -p lekiwi ssh -o StrictHostKeyChecking=no -o ConnectTimeout={SSH_CONNECT_TIMEOUT} lekiwi@{robot_ip} 'v4l2-ctl --list-devices 2>/dev/null || ls -la /dev/video* 2>/dev/null'"
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=SSH_COMMAND_TIMEOUT)
        if result.returncode == 0 and result.stdout:
            # Parse camera devices
            lines = result.stdout.strip().split('\n')
            video_idx = 0
            for line in lines:
                if '/dev/video' in line:
                    device_match = re.search(r'(/dev/video\d+)', line)
                    if device_match:
                        device = device_match.group(1)
                        # Try to determine camera type from context
                        if 'realsense' in line.lower() or video_idx == 0:
                            camera_devices['RealSense'] = device
                        elif 'claw' in line.lower() or 'arm' in line.lower():
                            if 'Claw 1' not in camera_devices:
                                camera_devices['Claw 1'] = device
                            else:
                                camera_devices['Claw 2'] = device
                        elif 'front' in line.lower():
                            camera_devices['Front'] = device
                        elif 'wrist' in line.lower():
                            camera_devices['Wrist'] = device
                        else:
                            # Generic assignment based on order
                            if is_xle:
                                names = ['RealSense', 'Claw 1', 'Claw 2']
                            else:
                                names = ['Front', 'Wrist']
                            if video_idx < len(names):
                                camera_devices[names[video_idx]] = device
                        video_idx += 1
    except:
        pass
    
    capabilities = {
        'ip': robot_ip,
        'type': robot_type,  # Use actual detected type
        'arms': 2 if is_xle else 1,
        'cameras': 3 if is_xle else 2,
        'control_type': 'bimanual' if is_xle else 'single-arm',
        'features': [],
        'ama_boards': len(ama_boards),  # Number of AMA boards detected
        'ama_board_info': [f"{board.get('id', 'Unknown')} ({board.get('type', '')})" for board in ama_boards][:3],  # First 3 boards
        'camera_devices': camera_devices  # Camera device paths
    }
    
    if is_xle:
        capabilities['features'] = [
            'Bimanual control (dual-arm)',
            '3 cameras for enhanced vision (RealSense + 2 claw cameras)',
            'Double teleop controls',
            'Advanced manipulation capabilities',
            'XLE Enhanced Robot',
            f'{len(ama_boards)} AMA boards detected' if ama_boards else 'AMA boards not detected'
        ]
    else:
        capabilities['features'] = [
            'Single-arm control',
            '2 cameras (front + wrist)',
            'Standard teleop controls',
            'LeKiwi Robot'
        ]
    
    return capabilities

def detect_ama_boards_remote(robot_ip):
    """
    Detect AMA boards on a remote robot via SSH
    """
    try:
        # Command to check for AMA devices on remote system
        cmd = f"""sshpass -p lekiwi ssh -o StrictHostKeyChecking=no -o ConnectTimeout={SSH_CONNECT_TIMEOUT} lekiwi@{robot_ip} '
            echo "=== ttyAMA devices ==="
            ls -la /dev/ttyAMA* 2>/dev/null || echo "No ttyAMA devices"
            echo "=== ttyACM devices ==="
            ls -la /dev/ttyACM* 2>/dev/null || echo "No ttyACM devices"
            echo "=== USB devices ==="
            lsusb 2>/dev/null | grep -i "waveshare\\|uart\\|servo" || echo "No relevant USB devices"
            echo "=== All AMA-pattern devices ==="
            ls -la /dev/tty* 2>/dev/null | grep -i ama || echo "No AMA-pattern devices"
        '"""
        
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=SSH_COMMAND_TIMEOUT)
        
        if result.returncode == 0:
            boards = []
            lines = result.stdout.splitlines()
            
            for line in lines:
                # Parse ttyAMA devices
                if '/dev/ttyAMA' in line:
                    match = re.search(r'/dev/ttyAMA(\w+)', line)
                    if match:
                        variant = match.group(1)
                        boards.append({
                            'type': 'Serial',
                            'id': f'AMA{variant}',
                            'device': f'/dev/ttyAMA{variant}'
                        })
                
                # Parse ttyACM devices
                elif '/dev/ttyACM' in line:
                    match = re.search(r'/dev/ttyACM(\d+)', line)
                    if match:
                        acm_num = match.group(1)
                        boards.append({
                            'type': 'ACM',
                            'id': f'ACM{acm_num}',
                            'device': f'/dev/ttyACM{acm_num}'
                        })
                
                # Parse USB devices
                elif 'waveshare' in line.lower() or 'uart' in line.lower():
                    # Extract USB info
                    usb_match = re.search(r'ID ([0-9a-f:]+)\s+(.+)', line)
                    if usb_match:
                        boards.append({
                            'type': 'USB',
                            'id': usb_match.group(1),
                            'description': usb_match.group(2)
                        })
            
            return boards
        
    except Exception as e:
        print(f"Error detecting AMA boards on {robot_ip}: {e}")
    
    return []

if __name__ == "__main__":
    # Test local AMA board detection
    print("Local AMA Board Detection:")
    print("=" * 50)
    local_boards = detect_ama_boards()
    if local_boards:
        print(f"Found {len(local_boards)} AMA board(s):")
        for board in local_boards:
            print(f"  - Type: {board['type']}, ID: {board['id']}")
            if 'device' in board:
                print(f"    Device: {board['device']}")
            if 'description' in board:
                print(f"    Description: {board['description']}")
    else:
        print("No AMA boards detected locally")
    
    # Test with known robots
    test_ips = ['192.168.88.57', '192.168.88.58', '192.168.88.62', '192.168.88.64']
    
    print("\nRobot Type Detection Results:")
    print(f"SSH Timeouts: Connect={SSH_CONNECT_TIMEOUT}s, Command={SSH_COMMAND_TIMEOUT}s")
    print("=" * 50)
    
    for ip in test_ips:
        robot_type = detect_robot_type(ip)
        capabilities = get_robot_capabilities(ip)
        
        print(f"\n{ip}:")
        print(f"  Type: {robot_type}")
        print(f"  Features:")
        for feature in capabilities['features']:
            print(f"    - {feature}")
        
        # Test remote AMA board detection
        remote_boards = detect_ama_boards_remote(ip)
        if remote_boards:
            print(f"  AMA Boards: {len(remote_boards)}")
            for board in remote_boards:
                print(f"    - {board['id']} ({board['type']})")
        else:
            print(f"  AMA Boards: None detected")
    
    # Output JSON for integration
    results = {ip: get_robot_capabilities(ip) for ip in test_ips}
    
    with open('/tmp/robot_types.json', 'w') as f:
        json.dump(results, f, indent=2)
    
    print(f"\nResults saved to /tmp/robot_types.json")