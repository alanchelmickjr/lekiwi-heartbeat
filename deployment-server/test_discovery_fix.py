#!/usr/bin/env python3
"""
Test script to verify discovery is working properly without resetting
"""

import requests
import time
import json
from datetime import datetime

API_URL = "http://localhost:8000"

def test_discovery():
    """Test that discovery preserves state and can run multiple times"""
    
    print("🧪 Testing Discovery Fix")
    print("=" * 60)
    
    # Test 1: Get initial fleet
    print("\n1️⃣ Getting initial fleet...")
    response = requests.get(f"{API_URL}/api/fleet")
    initial_fleet = response.json()
    initial_count = len(initial_fleet.get('robots', []))
    print(f"   Initial robots: {initial_count}")
    
    # Test 2: Run discovery
    print("\n2️⃣ Running discovery...")
    response = requests.post(f"{API_URL}/api/discover")
    if response.ok:
        result = response.json()
        print(f"   Status: {result.get('status')}")
        print(f"   Message: {result.get('message')}")
        discovered_count = result.get('fleet', {}).get('total', 0)
        print(f"   Discovered robots: {discovered_count}")
    
    # Wait a bit
    time.sleep(2)
    
    # Test 3: Get fleet again - should have robots
    print("\n3️⃣ Getting fleet after discovery...")
    response = requests.get(f"{API_URL}/api/fleet")
    fleet_after = response.json()
    after_count = len(fleet_after.get('robots', []))
    print(f"   Robots after discovery: {after_count}")
    
    # Test 4: Run discovery AGAIN - should not reset
    print("\n4️⃣ Running discovery again (should preserve state)...")
    response = requests.post(f"{API_URL}/api/discover")
    if response.ok:
        result = response.json()
        print(f"   Status: {result.get('status')}")
        second_discovered = result.get('fleet', {}).get('total', 0)
        print(f"   Robots found: {second_discovered}")
    
    # Test 5: Verify robots still exist
    print("\n5️⃣ Verifying robots not reset...")
    response = requests.get(f"{API_URL}/api/fleet")
    final_fleet = response.json()
    final_count = len(final_fleet.get('robots', []))
    print(f"   Final robot count: {final_count}")
    
    # Show robot details
    if final_fleet.get('robots'):
        print("\n📊 Robot Details:")
        for robot in final_fleet['robots'][:5]:  # Show first 5
            print(f"   • {robot['ip']} - {robot.get('hostname', 'unknown')}")
            if robot.get('stages'):
                stages_complete = sum(1 for s in robot['stages'].values() 
                                     if s.get('status') in ['success', 'active'])
                print(f"     Stages: {stages_complete}/{len(robot['stages'])} complete")
    
    # Results
    print("\n✅ Test Results:")
    print(f"   • Discovery can run multiple times: {'✓' if final_count > 0 else '✗'}")
    print(f"   • State preserved between runs: {'✓' if final_count >= after_count else '✗'}")
    print(f"   • Robots not cleared: {'✓' if final_count > 0 else '✗'}")
    
    return final_count > 0

if __name__ == "__main__":
    try:
        success = test_discovery()
        if success:
            print("\n🎉 Discovery is working properly!")
        else:
            print("\n❌ Discovery still has issues")
            
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        print("\nMake sure the deployment server is running on port 8000")