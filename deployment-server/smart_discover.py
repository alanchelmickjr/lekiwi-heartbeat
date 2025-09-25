#!/usr/bin/env python3
"""
Smart robot discovery - identifies robots by SSH banner and login attempt
"""

import socket
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
import paramiko
import warnings
warnings.filterwarnings("ignore")

# ANSI colors
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
CYAN = '\033[96m'
RESET = '\033[0m'

# Add diagnostic logging
import json
import logging
logging.basicConfig(level=logging.DEBUG, format='%(message)s')

def get_ssh_banner(ip, port=22, timeout=3):
    """Get SSH banner from server - reliable timeout"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)  # Balanced for reliability
        sock.connect((ip, port))
        
        # Read banner (usually first 255 bytes)
        banner = sock.recv(255).decode('utf-8', errors='ignore').strip()
        sock.close()
        return banner
    except:
        return None

def try_ssh_login(ip, username='lekiwi', password='lekiwi', timeout=5):
    """Try to SSH login with known credentials - reliable timeout"""
    logging.debug(f"[SSH] Attempting login to {ip} as {username}...")
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
        
        client.close()
        
        return {
            'success': True,
            'hostname': hostname,
            'is_pi': 'Raspberry Pi' in model or 'not-pi' not in model,
            'model': model if 'not-pi' not in model else None
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
        'model': None
    }
    
    # First check if SSH port is open - balanced timeout
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2)  # Balanced between speed and reliability
        if sock.connect_ex((ip, 22)) == 0:
            result['ssh_open'] = True
            logging.debug(f"[SSH] Port 22 open on {ip}")
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
            
            # Detect if it's an XLE robot by hostname pattern only
            if 'xlerobot' in hostname_lower:
                result['robot_type'] = 'xlerobot'
            else:
                result['robot_type'] = 'lekiwi'
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

def discover_smart(network="192.168.88", start=1, end=254):
    """Smart discovery of LeKiwi robots with improved detection"""
    print(f"{CYAN}═══════════════════════════════════════════════════════════════{RESET}")
    print(f"{CYAN}       🤖 LeKiwi Smart Robot Discovery v2.1 🤖{RESET}")
    print(f"{CYAN}═══════════════════════════════════════════════════════════════{RESET}\n")
    
    print(f"📡 Network: {network}.{start}-{end} ({end-start+1} IPs)")
    print(f"🔍 Methods: Fast parallel scan + SSH detection + Pi identification")
    print(f"⚡ Speed: Optimized for fast discovery\n")
    
    robots = []
    ssh_hosts = []
    potential_pis = []
    
    ips = [f"{network}.{i}" for i in range(start, end + 1)]
    total = len(ips)
    
    print(f"{YELLOW}Scanning {total} IPs with improved detection...{RESET}\n")
    
    # Balanced workers for reliable parallel scanning
    start_time = time.time()
    with ThreadPoolExecutor(max_workers=15) as executor:  # Balanced for speed and reliability
        futures = {executor.submit(scan_host, ip): ip for ip in ips}
        
        completed = 0
        last_percent = 0
        last_update = time.time()
        
        for future in as_completed(futures):
            completed += 1
            result = future.result()
            
            # Better progress reporting with ETA
            percent = int((completed / total) * 100)
            current_time = time.time()
            elapsed = current_time - start_time
            
            # Update every 5% or every 2 seconds
            if percent != last_percent and (percent % 5 == 0 or current_time - last_update > 2):
                rate = completed / elapsed if elapsed > 0 else 0
                eta = (total - completed) / rate if rate > 0 else 0
                
                # Show detailed progress
                print(f"\n{YELLOW}Progress: {percent}% ({completed}/{total} IPs)")
                print(f"  Speed: {rate:.1f} IPs/sec | ETA: {eta:.0f}s | Elapsed: {elapsed:.0f}s{RESET}")
                last_percent = percent
                last_update = current_time
            
            # Simple progress indicator
            progress = f"[{completed}/{total}] Scanning {result['ip']}..."
            sys.stdout.write(f"\r{progress}")
            sys.stdout.flush()
            
            # Process results
            if result['ssh_open']:
                # Clear line for important output
                sys.stdout.write(f"\r{' ' * 80}\r")
                
                if result['is_robot']:
                    robots.append(result)
                    robot_type = result.get('robot_type', 'unknown')
                    if robot_type == 'xlerobot':
                        print(f"{CYAN}🤖 XLE ROBOT FOUND: {result['ip']} - {result['hostname']}")
                    else:
                        print(f"{GREEN}🤖 LEKIWI ROBOT FOUND: {result['ip']} - {result['hostname']}")
                    if result['model']:
                        print(f"   Model: {result['model']}")
                    print(f"   Type: {robot_type.upper()}{RESET}")
                elif result['is_pi']:
                    # Treat ALL Raspberry Pis as potential robots - even if auth failed!
                    potential_pis.append(result)
                    print(f"{CYAN}🥧 Raspberry Pi DETECTED: {result['ip']} - {result.get('hostname', 'auth_failed')}")
                    if result.get('banner'):
                        print(f"   Banner: {result['banner'][:60]}")
                    print(f"   {YELLOW}(Likely a robot - needs credential check){RESET}")
                elif result.get('banner'):
                    # Check if banner suggests it might be a Pi we missed
                    if 'debian' in result['banner'].lower() or 'raspbian' in result['banner'].lower():
                        result['is_pi'] = True  # Mark as Pi based on banner
                        potential_pis.append(result)
                        print(f"{CYAN}🥧 Possible Raspberry Pi: {result['ip']} (Debian-based)")
                        print(f"   {YELLOW}Banner: {result['banner'][:60]}{RESET}")
                    else:
                        ssh_hosts.append(result)
                        logging.debug(f"[SSH] Non-Pi host: {result['ip']} - {result.get('hostname', 'unknown')}")
                else:
                    ssh_hosts.append(result)
                
                # Show progress again
                sys.stdout.write(f"{progress}")
                sys.stdout.flush()
    
    # Clear progress
    sys.stdout.write(f"\r{' ' * 50}\r")
    
    # Summary
    print(f"\n{CYAN}═══════════════════════════════════════════════════════════════{RESET}")
    print(f"{CYAN}                    DISCOVERY RESULTS{RESET}")
    print(f"{CYAN}═══════════════════════════════════════════════════════════════{RESET}\n")
    
    if robots:
        print(f"{GREEN}✅ LEKIWI ROBOTS ({len(robots)}):{RESET}")
        for r in robots:
            print(f"   • {r['ip']} - {r['hostname']}")
            if r['model']:
                print(f"     └─ {r['model']}")
    
    if potential_pis:
        print(f"\n{CYAN}🥧 POTENTIAL RASPBERRY PIs ({len(potential_pis)}):{RESET}")
        print(f"   {YELLOW}(These might be robots with different hostnames){RESET}")
        for p in potential_pis:
            print(f"   • {p['ip']} - {p['hostname'] or 'unknown'}")
            if p['banner']:
                print(f"     └─ Banner: {p['banner'][:50]}...")
    
    if ssh_hosts:
        print(f"\n{YELLOW}📡 OTHER SSH HOSTS ({len(ssh_hosts)}):{RESET}")
        for h in ssh_hosts[:5]:  # Show first 5
            print(f"   • {h['ip']} - {h['hostname'] or 'unknown'}")
        if len(ssh_hosts) > 5:
            print(f"   ... and {len(ssh_hosts) - 5} more")
    
    print(f"\n{BLUE}Summary:{RESET}")
    print(f"  Total scanned: {total}")
    print(f"  {GREEN}LeKiwi robots: {len(robots)}{RESET}")
    print(f"  {CYAN}Raspberry Pis: {len(potential_pis)}{RESET}")
    print(f"  {YELLOW}Other SSH: {len(ssh_hosts)}{RESET}")
    print(f"  {RED}No SSH: {total - len(robots) - len(potential_pis) - len(ssh_hosts)}{RESET}\n")
    
    # Suggest adding potential Pis as robots
    if potential_pis and not robots:
        print(f"{CYAN}💡 TIP: Found {len(potential_pis)} Raspberry Pi(s) that might be robots.{RESET}")
        print(f"{CYAN}   They have SSH but different hostnames. These are likely your robots:{RESET}")
        for p in potential_pis:
            print(f"   • {p['ip']}")
        print(f"\n{CYAN}   These will be treated as robots and auto-configured!{RESET}")
    
    # Write structured JSON output for better parsing
    all_discovered = robots + potential_pis
    json_output = {
        "robots": [{"ip": r['ip'], "hostname": r.get('hostname', 'unknown'), "type": r.get('robot_type', 'lekiwi'), "model": r.get('model', '')} for r in robots],
        "potential_robots": [{"ip": p['ip'], "hostname": p.get('hostname', 'unknown'), "type": "raspberry_pi"} for p in potential_pis],
        "other_ssh": [{"ip": h['ip'], "hostname": h.get('hostname', 'unknown'), "type": "ssh_host"} for h in ssh_hosts[:5]],
        "total_found": len(all_discovered)
    }
    
    # Write JSON output to file for web interface to parse
    with open("/tmp/discovery_results.json", "w") as f:
        json.dump(json_output, f, indent=2)
    
    print(f"\n{GREEN}Discovery results saved to /tmp/discovery_results.json{RESET}")
    
    return all_discovered  # Return both confirmed and potential robots

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