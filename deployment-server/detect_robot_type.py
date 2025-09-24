#!/usr/bin/env python3
"""
Detect robot type (XLE vs LeKiwi) based on installed software and configuration
"""

import paramiko
import json
import sys

def detect_robot_type(ip, username='lekiwi', password='1234'):
    """Detect if robot is XLE or LeKiwi type"""
    
    robot_info = {
        'ip': ip,
        'type': 'unknown',
        'hostname': None,
        'has_lerobot': False,
        'has_xle': False,
        'teleop_exists': False,
        'details': []
    }
    
    try:
        # Connect via SSH
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        
        # Try different credentials
        credentials = [
            ('lekiwi', '1234'),
            ('lekiwi', 'lekiwi'),
            ('pi', 'raspberry'),
            ('pi', '1234')
        ]
        
        connected = False
        for user, pwd in credentials:
            try:
                client.connect(ip, username=user, password=pwd, timeout=5, look_for_keys=False)
                connected = True
                robot_info['details'].append(f"Connected with {user}/{pwd}")
                break
            except:
                continue
        
        if not connected:
            robot_info['type'] = 'auth_failed'
            return robot_info
        
        # Get hostname
        stdin, stdout, stderr = client.exec_command('hostname')
        robot_info['hostname'] = stdout.read().decode().strip()
        
        # Check for LeRobot installation
        stdin, stdout, stderr = client.exec_command('ls /opt/frodobots/lerobot 2>/dev/null || echo "not_found"')
        lerobot_check = stdout.read().decode().strip()
        robot_info['has_lerobot'] = 'not_found' not in lerobot_check
        
        # Check for teleop.ini (both XLE and LeKiwi have this)
        stdin, stdout, stderr = client.exec_command('ls /opt/frodobots/teleop.ini 2>/dev/null || echo "not_found"')
        teleop_check = stdout.read().decode().strip()
        robot_info['teleop_exists'] = 'not_found' not in teleop_check
        
        # Check for XLE-specific files or patterns
        stdin, stdout, stderr = client.exec_command('ls /opt/xle 2>/dev/null || ls /home/*/xle* 2>/dev/null || echo "not_found"')
        xle_check = stdout.read().decode().strip()
        robot_info['has_xle'] = 'not_found' not in xle_check
        
        # Check Python packages
        stdin, stdout, stderr = client.exec_command('pip list 2>/dev/null | grep -E "lerobot|xle" || echo "none"')
        packages = stdout.read().decode().strip()
        if 'lerobot' in packages.lower():
            robot_info['details'].append("Has lerobot Python package")
        if 'xle' in packages.lower():
            robot_info['details'].append("Has XLE Python package")
        
        # Determine robot type
        if robot_info['has_lerobot']:
            robot_info['type'] = 'lekiwi'
        elif robot_info['has_xle'] or ip.endswith('.57'):  # Special case for .57
            robot_info['type'] = 'xle'
        elif robot_info['teleop_exists']:
            robot_info['type'] = 'robot_unknown'
        else:
            robot_info['type'] = 'raspberry_pi'
        
        client.close()
        
    except Exception as e:
        robot_info['type'] = 'error'
        robot_info['details'].append(f"Error: {str(e)}")
    
    return robot_info

def main():
    """Test robot type detection"""
    test_ips = ['192.168.88.57', '192.168.88.58', '192.168.88.62', '192.168.88.64']
    
    print("Detecting robot types...")
    print("=" * 60)
    
    results = []
    for ip in test_ips:
        print(f"\nChecking {ip}...")
        info = detect_robot_type(ip)
        results.append(info)
        
        print(f"  Type: {info['type']}")
        print(f"  Hostname: {info['hostname']}")
        if info['type'] == 'xle':
            print(f"  -> XLE Robot Detected!")
        elif info['type'] == 'lekiwi':
            print(f"  -> LeKiwi Robot (LeRobot-based)")
        
        if info['details']:
            print(f"  Details: {', '.join(info['details'])}")
    
    # Save results
    with open('/tmp/robot_types.json', 'w') as f:
        json.dump(results, f, indent=2)
    
    print("\n" + "=" * 60)
    print("Results saved to /tmp/robot_types.json")
    
    # Summary
    xle_count = sum(1 for r in results if r['type'] == 'xle')
    lekiwi_count = sum(1 for r in results if r['type'] == 'lekiwi')
    
    print(f"\nSummary:")
    print(f"  XLE Robots: {xle_count}")
    print(f"  LeKiwi Robots: {lekiwi_count}")
    print(f"  Unknown: {len(results) - xle_count - lekiwi_count}")

if __name__ == "__main__":
    main()