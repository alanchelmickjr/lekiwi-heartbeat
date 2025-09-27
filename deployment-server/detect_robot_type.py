#!/usr/bin/env python3
"""
Detect robot type (LeKiwi vs XLERobot) by checking system characteristics
"""

import subprocess
import json

def detect_robot_type(robot_ip):
    """
    Detect if a robot is regular LeKiwi or XLERobot
    XLERobot identified by:
    1. Presence of XLEROBOT-specific libraries in /opt/frodobots/lib/
    2. Hostname pattern containing 'xlerobot' (fallback)
    Returns: 'xlerobot', 'lekiwi', 'lekiwi-lite', or 'unknown'
    """
    try:
        # FIRST: Check for XLEROBOT-specific libraries (most reliable for XLE)
        # XLEROBOTs have libteleop_*_xlerobot.so files
        cmd = f"sshpass -p lekiwi ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 lekiwi@{robot_ip} 'ls /opt/frodobots/lib/libteleop_*xlerobot*.so 2>/dev/null | wc -l'"
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=5)
        
        if result.returncode == 0 and result.stdout:
            xlerobot_lib_count = result.stdout.strip()
            if xlerobot_lib_count.isdigit() and int(xlerobot_lib_count) > 0:
                # XLEROBOT-specific libraries found - this is an XLEROBOT
                print(f"Detected XLEROBOT at {robot_ip} (has XLEROBOT-specific libraries)")
                return 'xlerobot'
        
        # No longer using hostname as fallback - it causes false positives
        # Only XLEROBOT-specific libraries are reliable indicators
        
        # Check binary size AND control library together for other robot types
        cmd = f"sshpass -p lekiwi ssh -o StrictHostKeyChecking=no lekiwi@{robot_ip} 'stat -c %s /opt/frodobots/teleop_agent 2>/dev/null; grep ctrl /opt/frodobots/teleop.ini 2>/dev/null'"
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=5)
        
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
    
    return 'unknown'

def get_robot_capabilities(robot_ip):
    """
    Get detailed robot capabilities based on type
    XLERobot is the advanced bimanual (dual-arm) version with 3 cameras
    Detected by /opt/frodobots directory OR hostname pattern
    """
    robot_type = detect_robot_type(robot_ip)
    
    # XLERobot detected by directory check or hostname pattern
    is_xle = robot_type == 'xlerobot'
    
    capabilities = {
        'ip': robot_ip,
        'type': robot_type,  # Use actual detected type
        'arms': 2 if is_xle else 1,
        'cameras': 3 if is_xle else 2,
        'control_type': 'bimanual' if is_xle else 'single-arm',
        'features': []
    }
    
    if is_xle:
        capabilities['features'] = [
            'Bimanual control (dual-arm)',
            '3 cameras for enhanced vision (RealSense + 2 claw cameras)',
            'Double teleop controls',
            'Advanced manipulation capabilities',
            'XLE Enhanced Robot'
        ]
    else:
        capabilities['features'] = [
            'Single-arm control',
            '2 cameras (front + wrist)',
            'Standard teleop controls',
            'LeKiwi Robot'
        ]
    
    return capabilities

if __name__ == "__main__":
    # Test with known robots
    test_ips = ['192.168.88.57', '192.168.88.58', '192.168.88.62', '192.168.88.64']
    
    print("Robot Type Detection Results:")
    print("=" * 50)
    
    for ip in test_ips:
        robot_type = detect_robot_type(ip)
        capabilities = get_robot_capabilities(ip)
        
        print(f"\n{ip}:")
        print(f"  Type: {robot_type}")
        print(f"  Has IK: {capabilities['has_ik']}")
        print(f"  Binary: {capabilities['binary_type']}")
        print(f"  Features:")
        for feature in capabilities['features']:
            print(f"    - {feature}")
    
    # Output JSON for integration
    results = {ip: get_robot_capabilities(ip) for ip in test_ips}
    
    with open('/tmp/robot_types.json', 'w') as f:
        json.dump(results, f, indent=2)
    
    print(f"\nResults saved to /tmp/robot_types.json")