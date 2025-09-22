#!/usr/bin/env python3
"""
Simple robot discovery script that actually works
Shows progress and finds LeKiwi robots on the network
"""

import socket
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

# ANSI colors for output
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
RESET = '\033[0m'

def check_ssh_port(ip, timeout=1):
    """Check if SSH port 22 is open"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((ip, 22))
        sock.close()
        return result == 0
    except:
        return False

def get_hostname(ip):
    """Get hostname via SSH"""
    try:
        cmd = f"sshpass -p '1234' ssh -o StrictHostKeyChecking=no -o ConnectTimeout=2 lekiwi@{ip} hostname 2>/dev/null"
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=3)
        if result.returncode == 0:
            return result.stdout.strip()
    except:
        pass
    return None

def scan_ip(ip):
    """Scan a single IP"""
    sys.stdout.write(f"\r{YELLOW}Scanning: {ip}...{RESET}")
    sys.stdout.flush()
    
    if check_ssh_port(ip):
        hostname = get_hostname(ip)
        if hostname and 'lekiwi' in hostname.lower():
            return {'ip': ip, 'hostname': hostname, 'status': 'robot'}
        else:
            return {'ip': ip, 'hostname': hostname, 'status': 'ssh_open'}
    return {'ip': ip, 'hostname': None, 'status': 'no_ssh'}

def discover_robots(network="192.168.88", start=1, end=254):
    """Discover robots on the network"""
    print(f"{BLUE}═══════════════════════════════════════════════════════{RESET}")
    print(f"{BLUE}       🔍 LeKiwi Robot Discovery Scanner 🔍{RESET}")
    print(f"{BLUE}═══════════════════════════════════════════════════════{RESET}\n")
    
    print(f"Scanning network: {network}.{start}-{end}")
    print(f"Looking for robots with SSH (port 22) and hostname 'lekiwi'\n")
    
    robots = []
    ssh_hosts = []
    
    # Create IP list
    ips = [f"{network}.{i}" for i in range(start, end + 1)]
    total = len(ips)
    
    # Scan with thread pool
    with ThreadPoolExecutor(max_workers=20) as executor:
        futures = {executor.submit(scan_ip, ip): ip for ip in ips}
        
        completed = 0
        for future in as_completed(futures):
            completed += 1
            result = future.result()
            
            # Clear the line and show progress
            sys.stdout.write(f"\r{' ' * 60}\r")  # Clear line
            
            if result['status'] == 'robot':
                robots.append(result)
                print(f"{GREEN}✅ ROBOT FOUND: {result['ip']} ({result['hostname']}){RESET}")
            elif result['status'] == 'ssh_open':
                ssh_hosts.append(result)
                print(f"{YELLOW}📡 SSH Open: {result['ip']} (hostname: {result['hostname'] or 'unknown'}){RESET}")
            
            # Show progress
            percent = (completed / total) * 100
            sys.stdout.write(f"Progress: [{completed}/{total}] {percent:.1f}%")
            sys.stdout.flush()
    
    # Clear progress line
    sys.stdout.write(f"\r{' ' * 60}\r")
    
    # Summary
    print(f"\n{BLUE}═══════════════════════════════════════════════════════{RESET}")
    print(f"{BLUE}                    SCAN COMPLETE{RESET}")
    print(f"{BLUE}═══════════════════════════════════════════════════════{RESET}\n")
    
    if robots:
        print(f"{GREEN}🤖 LEKIWI ROBOTS FOUND ({len(robots)}):{RESET}")
        for r in robots:
            print(f"   • {r['ip']} - {r['hostname']}")
    else:
        print(f"{RED}❌ No LeKiwi robots found{RESET}")
    
    if ssh_hosts:
        print(f"\n{YELLOW}📡 OTHER SSH HOSTS ({len(ssh_hosts)}):{RESET}")
        for h in ssh_hosts:
            print(f"   • {h['ip']} - {h['hostname'] or 'unknown'}")
    
    print(f"\n{BLUE}Total IPs scanned: {total}{RESET}")
    print(f"{GREEN}LeKiwi robots: {len(robots)}{RESET}")
    print(f"{YELLOW}Other SSH hosts: {len(ssh_hosts)}{RESET}")
    print(f"{RED}No SSH: {total - len(robots) - len(ssh_hosts)}{RESET}\n")
    
    return robots

if __name__ == "__main__":
    # Run discovery
    robots = discover_robots()
    
    # Save results
    if robots:
        print(f"{BLUE}Saving robot list...{RESET}")
        with open("/tmp/discovered_robots.txt", "w") as f:
            for r in robots:
                f.write(f"{r['ip']} {r['hostname']}\n")
        print(f"{GREEN}✅ Robot list saved to /tmp/discovered_robots.txt{RESET}")