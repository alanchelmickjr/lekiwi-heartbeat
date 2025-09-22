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

def get_ssh_banner(ip, port=22, timeout=2):
    """Get SSH banner from server"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect((ip, port))
        
        # Read banner (usually first 255 bytes)
        banner = sock.recv(255).decode('utf-8', errors='ignore').strip()
        sock.close()
        return banner
    except:
        return None

def try_ssh_login(ip, username='lekiwi', password='1234', timeout=3):
    """Try to SSH login with known credentials"""
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
    
    # First check if SSH port is open
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1)
        if sock.connect_ex((ip, 22)) == 0:
            result['ssh_open'] = True
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
        
        # Check if hostname contains 'lekiwi'
        if 'lekiwi' in result['hostname'].lower():
            result['is_robot'] = True
    
    return result

def discover_smart(network="192.168.88", start=1, end=254):
    """Smart discovery of LeKiwi robots"""
    print(f"{CYAN}═══════════════════════════════════════════════════════════════{RESET}")
    print(f"{CYAN}       🔍 LeKiwi Smart Robot Discovery Scanner 🔍{RESET}")
    print(f"{CYAN}═══════════════════════════════════════════════════════════════{RESET}\n")
    
    print(f"Scanning: {network}.{start}-{end}")
    print(f"Methods: SSH banner detection + credential testing\n")
    
    robots = []
    ssh_hosts = []
    potential_pis = []
    
    ips = [f"{network}.{i}" for i in range(start, end + 1)]
    total = len(ips)
    
    print(f"{YELLOW}Scanning {total} IPs...{RESET}\n")
    
    with ThreadPoolExecutor(max_workers=20) as executor:
        futures = {executor.submit(scan_host, ip): ip for ip in ips}
        
        completed = 0
        for future in as_completed(futures):
            completed += 1
            result = future.result()
            
            # Update progress
            progress = f"[{completed}/{total}] Scanning..."
            sys.stdout.write(f"\r{progress}")
            sys.stdout.flush()
            
            # Process results
            if result['ssh_open']:
                # Clear line for important output
                sys.stdout.write(f"\r{' ' * 50}\r")
                
                if result['is_robot']:
                    robots.append(result)
                    print(f"{GREEN}🤖 ROBOT: {result['ip']} - {result['hostname']}")
                    if result['model']:
                        print(f"   Model: {result['model']}{RESET}")
                elif result['is_pi']:
                    potential_pis.append(result)
                    print(f"{CYAN}🥧 Raspberry Pi: {result['ip']} - {result['hostname'] or 'unknown'}{RESET}")
                else:
                    ssh_hosts.append(result)
                    if result['hostname']:
                        print(f"{YELLOW}📡 SSH Host: {result['ip']} - {result['hostname']}{RESET}")
                
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
        print(f"\n{CYAN}   You can add them manually or rename their hostnames to include 'lekiwi'{RESET}")
    
    return robots + potential_pis  # Return both confirmed and potential robots

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