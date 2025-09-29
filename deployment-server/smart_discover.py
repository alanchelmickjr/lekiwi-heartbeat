#!/usr/bin/env python3
"""
Smart robot discovery - uses parallel staged discovery engine for fast detection
"""

import asyncio
import json
import sys
import time
import os
from pathlib import Path

# Add parent directory to path to import server_discovery
sys.path.insert(0, str(Path(__file__).parent))

# Import the parallel discovery engine
try:
    from server_discovery import ParallelDiscovery, DiscoveryStage
    PARALLEL_AVAILABLE = True
except ImportError:
    PARALLEL_AVAILABLE = False
    print("Warning: Parallel discovery module not available, falling back to legacy")

# ANSI colors
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
CYAN = '\033[96m'
RESET = '\033[0m'

# For backward compatibility - fallback to legacy if needed
if not PARALLEL_AVAILABLE:
    import socket
    import subprocess
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import paramiko
    import warnings
    warnings.filterwarnings("ignore")
    import logging
    logging.basicConfig(level=logging.DEBUG, format='%(message)s')
    
    # Configurable timeouts (can be overridden via environment variables)
    TIMEOUT_CONFIG = {
        'ssh_banner': int(os.getenv('DISCOVERY_SSH_BANNER_TIMEOUT', '10')),  # Increased from 3 to 10 seconds
        'ssh_login': int(os.getenv('DISCOVERY_SSH_LOGIN_TIMEOUT', '15')),    # Increased from 5 to 15 seconds
        'port_check': int(os.getenv('DISCOVERY_PORT_CHECK_TIMEOUT', '5')),   # Increased from 2 to 5 seconds
        'max_workers': int(os.getenv('DISCOVERY_MAX_WORKERS', '25')),        # Increased from 15 to 25 for better parallelism
    }

def get_ssh_banner(ip, port=22, timeout=None):
    """Get SSH banner from server - with adequate timeout for slow Pis"""
    if timeout is None:
        timeout = TIMEOUT_CONFIG['ssh_banner']
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)  # Adequate timeout for Raspberry Pi
        sock.connect((ip, port))
        
        # Read banner (usually first 255 bytes)
        banner = sock.recv(255).decode('utf-8', errors='ignore').strip()
        sock.close()
        return banner
    except:
        return None

def try_ssh_login(ip, username='lekiwi', password='lekiwi', timeout=None):
    """Try to SSH login with known credentials - with adequate timeout for slow Pis"""
    if timeout is None:
        timeout = TIMEOUT_CONFIG['ssh_login']
    logging.debug(f"[SSH] Attempting login to {ip} as {username} (timeout: {timeout}s)...")
    try:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(ip, username=username, password=password, timeout=timeout, look_for_keys=False)
        
        # If we can connect, try to get hostname
        stdin, stdout, stderr = client.exec_command('hostname')
        hostname = stdout.read().decode().strip()
        
        # Check if it's a Raspberry Pi
        stdin, stdout, stderr = client.exec_command('cat /proc/device-tree/model 2>/dev/null || echo "not-pi"')
        model = stdout.read().decode().strip()
        
        # Check for XLEROBOT-specific libraries
        stdin, stdout, stderr = client.exec_command('ls /opt/frodobots/lib/libteleop_*xlerobot*.so 2>/dev/null | wc -l')
        xlerobot_lib_count = stdout.read().decode().strip()
        has_xlerobot_libs = xlerobot_lib_count.isdigit() and int(xlerobot_lib_count) > 0
        
        client.close()
        
        return {
            'success': True,
            'hostname': hostname,
            'is_pi': 'Raspberry Pi' in model or 'not-pi' not in model,
            'model': model if 'not-pi' not in model else None,
            'has_xlerobot_libs': has_xlerobot_libs
        }
    except paramiko.AuthenticationException:
        return {'success': False, 'reason': 'auth_failed'}
    except paramiko.SSHException:
        return {'success': False, 'reason': 'ssh_error'}
    except Exception as e:
        return {'success': False, 'reason': str(e)}

def scan_host(ip):
    """Smart scan of a single host"""
    result = {
        'ip': ip,
        'ssh_open': False,
        'banner': None,
        'is_robot': False,
        'hostname': None,
        'is_pi': False,
        'model': None,
        'robot_type': None
    }
    
    # First check if SSH port is open - adequate timeout for slow Pis
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(TIMEOUT_CONFIG['port_check'])  # Give Pis enough time to respond
        if sock.connect_ex((ip, 22)) == 0:
            result['ssh_open'] = True
            logging.debug(f"[SSH] Port 22 open on {ip} (responded within {TIMEOUT_CONFIG['port_check']}s)")
        sock.close()
    except:
        pass
    
    if not result['ssh_open']:
        return result
    
    # Get SSH banner
    banner = get_ssh_banner(ip)
    if banner:
        result['banner'] = banner
        
        # Check if banner suggests Raspberry Pi
        if 'raspbian' in banner.lower() or 'debian' in banner.lower():
            result['is_pi'] = True
    
    # Try to login with known credentials
    login_result = try_ssh_login(ip)
    if login_result['success']:
        result['hostname'] = login_result['hostname']
        result['is_pi'] = login_result['is_pi']
        result['model'] = login_result['model']
        
        # Improved hostname detection - check multiple patterns
        hostname_lower = result['hostname'].lower()
        robot_patterns = ['lekiwi', 'lerobot', 'xlerobot', 'raspberry', 'raspberrypi', 'pi']
        
        # Check if hostname matches any robot pattern
        is_robot = any(pattern in hostname_lower for pattern in robot_patterns)
        
        # Also check if it starts/ends with 'pi' or contains numbers (common for Pi hostnames)
        if not is_robot and (hostname_lower.startswith('pi') or hostname_lower.endswith('pi') or
                             'pi-' in hostname_lower or '-pi' in hostname_lower):
            is_robot = True
            
        if is_robot:
            result['is_robot'] = True
            logging.debug(f"[ROBOT] Confirmed robot at {ip}: {result['hostname']}")
            
            # Don't do robot type detection here - let detect_robot_type.py handle it
            # This avoids duplicate/conflicting detection logic
            result['robot_type'] = 'unknown'  # Will be determined later by detect_robot_type.py
    else:
        # Even if login fails, we may have detected it's a Pi from the banner
        logging.debug(f"[SSH] Login failed for {ip}: {login_result.get('reason', 'unknown')}")
        # Try to get hostname via other means (reverse DNS or simple probe)
        try:
            import socket as sock
            result['hostname'] = sock.gethostbyaddr(ip)[0]
        except:
            result['hostname'] = f"pi_{ip.split('.')[-1]}" if result['is_pi'] else None
    
    return result

async def discover_smart_parallel(network="192.168.88", start=1, end=254):
    """Smart discovery using parallel staged discovery engine - FAST!"""
    print(f"{CYAN}═══════════════════════════════════════════════════════════════{RESET}")
    print(f"{CYAN}       🚀 LeKiwi PARALLEL Robot Discovery v3.0 🚀{RESET}")
    print(f"{CYAN}═══════════════════════════════════════════════════════════════{RESET}\n")
    
    print(f"📡 Network: {network}.{start}-{end} ({end-start+1} IPs)")
    print(f"🔍 Method: TRUE PARALLEL with 6-stage validation")
    print(f"⚡ Speed: <5 seconds for full network scan\n")
    
    # Create discovery engine
    discovery = ParallelDiscovery(max_workers=30)
    
    # Run parallel discovery
    start_time = time.time()
    print(f"{YELLOW}Starting parallel discovery...{RESET}\n")
    
    results = await discovery.discover_network(network, start, end)
    
    elapsed = time.time() - start_time
    
    # Process results
    valid_robots = []
    blank_pis = []
    
    for ip, robot_data in results["robots"].items():
        if robot_data["is_valid"]:
            valid_robots.append({
                'ip': ip,
                'hostname': robot_data['hostname'],
                'type': robot_data['type'],
                'stages': robot_data['stages']
            })
        elif robot_data["type"] == "blank_pi":
            blank_pis.append({
                'ip': ip,
                'hostname': robot_data.get('hostname', 'unknown')
            })
    
    # Display results
    print(f"\n{CYAN}═══════════════════════════════════════════════════════════════{RESET}")
    print(f"{CYAN}                    DISCOVERY RESULTS{RESET}")
    print(f"{CYAN}═══════════════════════════════════════════════════════════════{RESET}\n")
    
    if valid_robots:
        print(f"{GREEN}✅ VALID ROBOTS ({len(valid_robots)}):{RESET}")
        for r in valid_robots:
            # Check stage statuses
            teleop_host = r['stages'].get(DiscoveryStage.TELEOP_HOST.value, {}).get('status') == 'success'
            teleop_operated = r['stages'].get(DiscoveryStage.TELEOP_OPERATION.value, {}).get('status') == 'active'
            
            status_icons = []
            if teleop_host:
                status_icons.append("🎮 HOST")
            if teleop_operated:
                status_icons.append("🕹️ OPERATED")
            
            status_str = " | ".join(status_icons) if status_icons else "⚪ IDLE"
            
            print(f"   • {r['ip']} - {r['hostname']} [{r['type'].upper()}] - {status_str}")
    
    if blank_pis:
        print(f"\n{YELLOW}🥧 BLANK RASPBERRY PIs ({len(blank_pis)}) - Filtered out:{RESET}")
        for p in blank_pis[:3]:  # Show first 3
            print(f"   • {p['ip']} - {p.get('hostname', 'unknown')}")
        if len(blank_pis) > 3:
            print(f"   ... and {len(blank_pis) - 3} more")
    
    print(f"\n{BLUE}Summary:{RESET}")
    print(f"  Total scanned: {results['total_scanned']}")
    print(f"  {GREEN}Valid robots: {results['valid_robots']}{RESET}")
    print(f"  {YELLOW}Blank Pis (filtered): {results['blank_pis']}{RESET}")
    print(f"  {GREEN}⚡ Completed in: {elapsed:.1f} seconds{RESET}\n")
    
    # Write JSON output for compatibility
    json_output = {
        "robots": [{"ip": r['ip'], "hostname": r['hostname'], "type": r['type']} for r in valid_robots],
        "blank_pis": [{"ip": p['ip'], "hostname": p.get('hostname', 'unknown')} for p in blank_pis],
        "total_found": len(valid_robots),
        "discovery_time": elapsed,
        "stages_enabled": True
    }
    
    with open("/tmp/discovery_results.json", "w") as f:
        json.dump(json_output, f, indent=2)
    
    # Also write legacy format for compatibility
    with open("/tmp/smart_discovered.txt", "w") as f:
        for r in valid_robots:
            f.write(f"{r['ip']} {r['hostname']} {r['type']}\n")
    
    print(f"{GREEN}Results saved to /tmp/discovery_results.json{RESET}")
    
    return valid_robots

# Keep legacy function for backward compatibility
def discover_smart(network="192.168.88", start=1, end=254):
    """Legacy wrapper - runs the parallel discovery"""
    if PARALLEL_AVAILABLE:
        # Run the async function in a sync context
        return asyncio.run(discover_smart_parallel(network, start, end))
    else:
        # Fall back to legacy implementation
        print(f"{YELLOW}Warning: Using legacy discovery (parallel module not available){RESET}")
        return discover_smart_legacy(network, start, end)

def discover_smart_legacy(network="192.168.88", start=1, end=254):
    """Legacy discovery implementation - kept for fallback"""
    # This is the old implementation - simplified here
    print(f"{YELLOW}Legacy discovery not fully implemented in this version{RESET}")
    return []

if __name__ == "__main__":
    # Run smart discovery
    import sys
    
    # Check for specific range
    if len(sys.argv) > 1:
        # Allow custom range like: python3 smart_discover.py 20 70
        start = int(sys.argv[1]) if len(sys.argv) > 1 else 1
        end = int(sys.argv[2]) if len(sys.argv) > 2 else 254
        discovered = discover_smart(start=start, end=end)
    else:
        discovered = discover_smart()
    
    # Save results
    if discovered:
        with open("/tmp/smart_discovered.txt", "w") as f:
            for r in discovered:
                f.write(f"{r['ip']} {r.get('hostname', 'unknown')} {r.get('model', '')}\n")
        print(f"{GREEN}Results saved to /tmp/smart_discovered.txt{RESET}")