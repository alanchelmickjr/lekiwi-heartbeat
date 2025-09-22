#!/usr/bin/env python3
"""
Automatically add discovered robots to the fleet
"""

import json
import os

# ANSI colors
GREEN = '\033[92m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
RESET = '\033[0m'

def add_robots_to_fleet():
    """Add discovered robots to the fleet configuration"""
    
    # Read discovered robots
    discovered_file = "/tmp/smart_discovered.txt"
    if not os.path.exists(discovered_file):
        print(f"{YELLOW}No discovered robots file found. Run smart_discover.py first!{RESET}")
        return
    
    robots = []
    with open(discovered_file, 'r') as f:
        for line in f:
            parts = line.strip().split()
            if parts:
                ip = parts[0]
                robots.append({
                    'ip': ip,
                    'hostname': f'lekiwi_{ip.split(".")[-1]}',  # Use last octet as ID
                    'status': 'discovered',
                    'type': 'Raspberry Pi'
                })
    
    if not robots:
        print(f"{YELLOW}No robots found in discovery file{RESET}")
        return
    
    # Save to fleet configuration
    fleet_config = {
        'robots': robots,
        'total': len(robots),
        'discovered_at': os.path.getmtime(discovered_file)
    }
    
    config_file = "/tmp/lekiwi_fleet.json"
    with open(config_file, 'w') as f:
        json.dump(fleet_config, f, indent=2)
    
    print(f"{BLUE}═══════════════════════════════════════════════════════{RESET}")
    print(f"{BLUE}       🤖 LeKiwi Fleet Configuration Updated 🤖{RESET}")
    print(f"{BLUE}═══════════════════════════════════════════════════════{RESET}\n")
    
    print(f"{GREEN}✅ Added {len(robots)} robots to fleet:{RESET}")
    for r in robots:
        print(f"   • {r['ip']} ({r['hostname']})")
    
    print(f"\n{BLUE}Fleet configuration saved to: {config_file}{RESET}")
    
    # Also create a simple hosts file for easy access
    hosts_file = "/tmp/lekiwi_hosts.txt"
    with open(hosts_file, 'w') as f:
        f.write("# LeKiwi Robot Fleet\n")
        for r in robots:
            f.write(f"{r['ip']} {r['hostname']}\n")
    
    print(f"{BLUE}Hosts file created: {hosts_file}{RESET}")
    
    # Create deployment script
    deploy_script = "/tmp/deploy_to_all.sh"
    with open(deploy_script, 'w') as f:
        f.write("#!/bin/bash\n")
        f.write("# Deploy to all LeKiwi robots\n\n")
        f.write("ROBOTS=(\n")
        for r in robots:
            f.write(f"  {r['ip']}\n")
        f.write(")\n\n")
        f.write('for robot in "${ROBOTS[@]}"; do\n')
        f.write('  echo "Deploying to $robot..."\n')
        f.write('  # Add your deployment command here\n')
        f.write('  # Example: sshpass -p "1234" ssh lekiwi@$robot "command"\n')
        f.write('done\n')
    
    os.chmod(deploy_script, 0o755)
    print(f"{BLUE}Deployment script created: {deploy_script}{RESET}")
    
    print(f"\n{GREEN}✅ Fleet is ready for management!{RESET}")
    print(f"\nNext steps:")
    print(f"  1. Check robot status: {YELLOW}python3 check_fleet_status.py{RESET}")
    print(f"  2. Deploy baseline: {YELLOW}python3 deploy_baseline.py{RESET}")
    print(f"  3. Fix broken robots: {YELLOW}python3 fix_broken_robots.py{RESET}")
    
    return robots

if __name__ == "__main__":
    add_robots_to_fleet()