#!/usr/bin/env python3
"""
Script to rename XLE robot hostname to xlerobot1
"""

import paramiko
import sys

def rename_xlerobot(ip='192.168.88.57', new_hostname='xlerobot1'):
    """Rename the XLE robot hostname"""
    
    print(f"🤖 Renaming XLE robot at {ip} to {new_hostname}...")
    
    try:
        # Connect via SSH
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(ip, username='lekiwi', password='lekiwi', timeout=5)
        
        # Get current hostname
        stdin, stdout, stderr = client.exec_command('hostname')
        current_hostname = stdout.read().decode().strip()
        print(f"  Current hostname: {current_hostname}")
        
        # Update hostname file
        print(f"  Setting new hostname: {new_hostname}")
        stdin, stdout, stderr = client.exec_command(f'echo "{new_hostname}" | sudo tee /etc/hostname')
        result = stdout.read().decode().strip()
        
        # Update hosts file
        print(f"  Updating /etc/hosts...")
        stdin, stdout, stderr = client.exec_command(f'sudo sed -i "s/{current_hostname}/{new_hostname}/g" /etc/hosts')
        
        # Apply hostname immediately
        stdin, stdout, stderr = client.exec_command(f'sudo hostname {new_hostname}')
        
        # Verify the change
        stdin, stdout, stderr = client.exec_command('hostname')
        new_current = stdout.read().decode().strip()
        
        if new_current == new_hostname:
            print(f"✅ Successfully renamed to {new_hostname}")
            print(f"⚠️  Note: Full change requires reboot")
            print(f"   Run: ssh lekiwi@{ip} 'sudo reboot'")
        else:
            print(f"❌ Hostname change may not have applied correctly")
            print(f"   Current: {new_current}")
        
        client.close()
        return True
        
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        return False

if __name__ == "__main__":
    # Check for custom IP or hostname
    ip = sys.argv[1] if len(sys.argv) > 1 else '192.168.88.57'
    hostname = sys.argv[2] if len(sys.argv) > 2 else 'xlerobot1'
    
    print("=" * 60)
    print("XLE Robot Hostname Renamer")
    print("=" * 60)
    
    success = rename_xlerobot(ip, hostname)
    
    if success:
        print("\n✅ Done! The robot should now identify as 'xlerobot1'")
        print("   Discovery will detect it as an XLE robot type")
    else:
        print("\n❌ Failed to rename hostname")
        print("   Check SSH credentials and try again")