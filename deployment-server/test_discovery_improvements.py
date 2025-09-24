#!/usr/bin/env python3
"""
Test script to verify discovery improvements
"""

import subprocess
import json
import time
import sys

# ANSI colors
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
CYAN = '\033[96m'
RESET = '\033[0m'

def test_discovery():
    """Test the improved discovery with different scenarios"""
    
    print(f"{BLUE}═══════════════════════════════════════════════════════{RESET}")
    print(f"{BLUE}       Testing Discovery Improvements{RESET}")
    print(f"{BLUE}═══════════════════════════════════════════════════════{RESET}\n")
    
    # Test 1: Check timeout improvements
    print(f"{CYAN}Test 1: Checking improved timeouts...{RESET}")
    start_time = time.time()
    
    # Run discovery on a small range to test speed
    result = subprocess.run(
        ["python3", "smart_discover.py", "20", "30"],
        capture_output=True,
        text=True,
        timeout=60
    )
    
    elapsed = time.time() - start_time
    print(f"  Discovery took {elapsed:.2f} seconds")
    
    if elapsed < 30:
        print(f"  {GREEN}✓ Good speed with improved timeouts{RESET}")
    else:
        print(f"  {YELLOW}⚠ Discovery still slow ({elapsed:.2f}s){RESET}")
    
    # Test 2: Check JSON output
    print(f"\n{CYAN}Test 2: Checking structured JSON output...{RESET}")
    discovery_data = None
    try:
        with open("/tmp/discovery_results.json", "r") as f:
            discovery_data = json.load(f)
            
        print(f"  Found data structure:")
        print(f"    - Confirmed robots: {len(discovery_data.get('robots', []))}")
        print(f"    - Potential robots: {len(discovery_data.get('potential_robots', []))}")
        print(f"    - Other SSH hosts: {len(discovery_data.get('other_ssh', []))}")
        print(f"  {GREEN}✓ JSON output working correctly{RESET}")
        
        # Show detected devices
        if discovery_data.get('robots'):
            print(f"\n  {GREEN}Confirmed robots:{RESET}")
            for robot in discovery_data['robots']:
                print(f"    • {robot['ip']} - {robot.get('hostname', 'unknown')}")
        
        if discovery_data.get('potential_robots'):
            print(f"\n  {CYAN}Potential robots (Raspberry Pis):{RESET}")
            for robot in discovery_data['potential_robots']:
                print(f"    • {robot['ip']} - {robot.get('hostname', 'unknown')}")
                
    except FileNotFoundError:
        print(f"  {RED}✗ JSON file not created{RESET}")
    except json.JSONDecodeError:
        print(f"  {RED}✗ Invalid JSON format{RESET}")
    
    # Test 3: Check progress reporting
    print(f"\n{CYAN}Test 3: Checking progress reporting...{RESET}")
    if "Progress:" in result.stdout or "%" in result.stdout:
        print(f"  {GREEN}✓ Progress reporting enabled{RESET}")
        
        # Count progress updates
        progress_lines = [l for l in result.stdout.split('\n') if 'Progress:' in l or '%' in l]
        print(f"  Found {len(progress_lines)} progress updates")
    else:
        print(f"  {YELLOW}⚠ No progress reporting found{RESET}")
    
    # Test 4: Check Raspberry Pi detection
    print(f"\n{CYAN}Test 4: Checking Raspberry Pi detection...{RESET}")
    pi_detected = "Raspberry Pi DETECTED" in result.stdout
    if pi_detected:
        print(f"  {GREEN}✓ Raspberry Pi detection working{RESET}")
        pi_count = result.stdout.count("Raspberry Pi")
        print(f"  Found {pi_count} mentions of Raspberry Pi")
    else:
        print(f"  {YELLOW}⚠ No Raspberry Pis detected in test range{RESET}")
    
    # Show full discovery summary
    print(f"\n{BLUE}═══════════════════════════════════════════════════════{RESET}")
    print(f"{BLUE}                    Test Summary{RESET}")
    print(f"{BLUE}═══════════════════════════════════════════════════════{RESET}")
    
    tests_passed = 0
    tests_total = 4
    
    if elapsed < 30:
        tests_passed += 1
    if "/tmp/discovery_results.json" in result.stdout or discovery_data:
        tests_passed += 1
    if "Progress:" in result.stdout or "%" in result.stdout:
        tests_passed += 1
    if pi_detected or discovery_data.get('potential_robots'):
        tests_passed += 1
    
    print(f"\n{GREEN if tests_passed == tests_total else YELLOW}Tests passed: {tests_passed}/{tests_total}{RESET}")
    
    if tests_passed == tests_total:
        print(f"{GREEN}✅ All improvements working correctly!{RESET}")
    else:
        print(f"{YELLOW}⚠ Some improvements need attention{RESET}")
    
    return tests_passed == tests_total

def test_parallel_checking():
    """Test that parallel checking works"""
    print(f"\n{CYAN}Testing parallel robot checking...{RESET}")
    
    # This would need to be tested through the web interface
    print(f"  {YELLOW}Note: Parallel checking must be tested via web interface{RESET}")
    print(f"  Open http://localhost:8080 and click 'Discover Robots'")
    print(f"  You should see:")
    print(f"    1. Progress updates during scanning")
    print(f"    2. All Raspberry Pis detected (not just 'lekiwi' hostnames)")
    print(f"    3. Parallel status checking with progress")
    print(f"    4. Faster overall discovery time")

if __name__ == "__main__":
    # Run tests
    success = test_discovery()
    test_parallel_checking()
    
    print(f"\n{BLUE}═══════════════════════════════════════════════════════{RESET}")
    print(f"{BLUE}           Next Steps to Verify Fixes{RESET}")
    print(f"{BLUE}═══════════════════════════════════════════════════════{RESET}")
    
    print(f"\n1. Run full network scan:")
    print(f"   {YELLOW}python3 smart_discover.py{RESET}")
    
    print(f"\n2. Test web interface:")
    print(f"   {YELLOW}Open http://localhost:8080{RESET}")
    print(f"   {YELLOW}Click 'Discover Robots'{RESET}")
    
    print(f"\n3. Check specific issues:")
    print(f"   • All Raspberry Pis should be detected")
    print(f"   • Progress updates should show during scan")
    print(f"   • Checking should be faster (parallel)")
    print(f"   • No duplicate logic warnings")
    
    sys.exit(0 if success else 1)