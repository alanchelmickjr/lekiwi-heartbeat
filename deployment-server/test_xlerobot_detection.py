#!/usr/bin/env python3
"""
Test script to verify XLEROBOT detection works properly
Specifically tests robot at 192.168.88.29 (lekiwi5 with /opt/frodobots)
"""

import sys
import json
from detect_robot_type import detect_robot_type, get_robot_capabilities

# ANSI colors for output
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
CYAN = '\033[96m'
RESET = '\033[0m'

def test_robot_detection(robot_ip):
    """Test robot type detection for a specific IP"""
    print(f"\n{CYAN}Testing robot detection for {robot_ip}{RESET}")
    print("=" * 60)
    
    # Test basic type detection
    print(f"\n{YELLOW}1. Testing detect_robot_type()...{RESET}")
    robot_type = detect_robot_type(robot_ip)
    print(f"   Robot Type: {robot_type}")
    
    if robot_type == 'xlerobot':
        print(f"   {GREEN}✓ XLEROBOT detected!{RESET}")
    elif robot_type == 'lekiwi':
        print(f"   {YELLOW}⚠ Regular LEKIWI detected (not XLEROBOT){RESET}")
    else:
        print(f"   {RED}✗ Type: {robot_type}{RESET}")
    
    # Test capabilities detection
    print(f"\n{YELLOW}2. Testing get_robot_capabilities()...{RESET}")
    capabilities = get_robot_capabilities(robot_ip)
    
    print(f"   IP: {capabilities['ip']}")
    print(f"   Type: {capabilities['type']}")
    print(f"   Arms: {capabilities['arms']}")
    print(f"   Cameras: {capabilities['cameras']}")
    print(f"   Control Type: {capabilities['control_type']}")
    
    # Verify XLEROBOT configuration
    if robot_type == 'xlerobot':
        if capabilities['arms'] == 2 and capabilities['cameras'] == 3:
            print(f"\n   {GREEN}✓ Correct XLEROBOT configuration:{RESET}")
            print(f"     - 2 arms (bimanual)")
            print(f"     - 3 cameras (RealSense + 2 claw cameras)")
        else:
            print(f"\n   {RED}✗ Incorrect configuration for XLEROBOT{RESET}")
            print(f"     Expected: 2 arms, 3 cameras")
            print(f"     Got: {capabilities['arms']} arms, {capabilities['cameras']} cameras")
    
    # Display features
    print(f"\n{YELLOW}3. Robot Features:{RESET}")
    for feature in capabilities['features']:
        print(f"   • {feature}")
    
    return robot_type, capabilities

def main():
    """Main test function"""
    print(f"{CYAN}═══════════════════════════════════════════════════════════════{RESET}")
    print(f"{CYAN}       XLEROBOT Detection Test - /opt/frodobots Check{RESET}")
    print(f"{CYAN}═══════════════════════════════════════════════════════════════{RESET}")
    
    # Test the specific robot mentioned in the task
    target_robot = "192.168.88.29"
    print(f"\n{BLUE}Testing robot at {target_robot} (lekiwi5 with /opt/frodobots)...{RESET}")
    
    try:
        robot_type, capabilities = test_robot_detection(target_robot)
        
        # Summary
        print(f"\n{CYAN}═══════════════════════════════════════════════════════════════{RESET}")
        print(f"{CYAN}                         TEST RESULTS{RESET}")
        print(f"{CYAN}═══════════════════════════════════════════════════════════════{RESET}")
        
        if robot_type == 'xlerobot' and capabilities['arms'] == 2 and capabilities['cameras'] == 3:
            print(f"\n{GREEN}✅ SUCCESS! Robot at {target_robot} correctly identified as:{RESET}")
            print(f"   - Type: XLEROBOT")
            print(f"   - Arms: 2 (bimanual)")
            print(f"   - Cameras: 3 (RealSense + 2 claw cameras)")
            print(f"\n{GREEN}The /opt/frodobots directory detection is working!{RESET}")
        else:
            print(f"\n{RED}❌ FAILED! Robot at {target_robot} not correctly identified{RESET}")
            print(f"   - Expected: xlerobot with 2 arms and 3 cameras")
            print(f"   - Got: {robot_type} with {capabilities['arms']} arms and {capabilities['cameras']} cameras")
        
        # Save results to file for verification
        results = {
            "robot_ip": target_robot,
            "detected_type": robot_type,
            "capabilities": capabilities,
            "test_passed": robot_type == 'xlerobot' and capabilities['arms'] == 2 and capabilities['cameras'] == 3
        }
        
        with open("/tmp/xlerobot_detection_test.json", "w") as f:
            json.dump(results, f, indent=2)
        
        print(f"\n{BLUE}Test results saved to /tmp/xlerobot_detection_test.json{RESET}")
        
    except Exception as e:
        print(f"\n{RED}Error during test: {e}{RESET}")
        return 1
    
    # Test additional robots if provided
    if len(sys.argv) > 1:
        print(f"\n{CYAN}Testing additional robots...{RESET}")
        for ip in sys.argv[1:]:
            test_robot_detection(ip)
    
    return 0

if __name__ == "__main__":
    sys.exit(main())