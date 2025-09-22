#!/usr/bin/env python3
"""
Test script for the comparison engine
Creates baseline and tests comparisons
"""

import sys
import os
sys.path.append(os.path.dirname(__file__))

from comparison_engine import RobotFileComparison

def main():
    print("🔍 Testing Robot Deployment Comparison Engine")
    print("=" * 60)
    
    engine = RobotFileComparison()
    
    # Test 1: Create baseline from working robots
    print("\n📊 Creating baseline version 0.01 from working robots...")
    print("   Source robots: 192.168.88.21, 192.168.88.58, 192.168.88.62")
    
    try:
        baseline = engine.create_baseline()
        print(f"✅ Baseline created successfully!")
        print(f"   - Version: {baseline['version']}")
        print(f"   - Files tracked: {len(baseline['files'])}")
        print(f"   - Binary checksums: {len(baseline['checksums'])}")
        print(f"   - Created: {baseline['created']}")
    except Exception as e:
        print(f"❌ Failed to create baseline: {e}")
        return 1
    
    # Test 2: Compare working robot with broken robot
    print("\n🔍 Comparing working robot (.21) with broken robot (.57)...")
    
    try:
        comparison = engine.compare_robots("192.168.88.21", "192.168.88.57")
        print(f"✅ Comparison completed!")
        print(f"   - Differences found: {len(comparison['differences'])}")
        print(f"   - Identical files: {len(comparison['identical_files'])}")
        print(f"   - Missing in .21: {len(comparison['missing_files']['robot1_missing'])}")
        print(f"   - Missing in .57: {len(comparison['missing_files']['robot2_missing'])}")
        
        if comparison['differences']:
            print("\n   Key differences:")
            for diff in comparison['differences'][:3]:  # Show first 3 differences
                print(f"     - {diff['file']} ({diff['type']})")
    except Exception as e:
        print(f"❌ Failed to compare robots: {e}")
    
    # Test 3: Check compliance of each robot
    print("\n✅ Checking baseline compliance for all robots...")
    
    robots = [
        ("192.168.88.21", "Working - Baseline"),
        ("192.168.88.57", "Broken - No Conda"),
        ("192.168.88.58", "Working - Baseline"),
        ("192.168.88.62", "Working - Baseline"),
        ("192.168.88.64", "Broken - No Conda")
    ]
    
    for robot_ip, description in robots:
        try:
            result = engine.compare_to_baseline(robot_ip)
            status_icon = "✅" if result['status'] == 'compliant' else "❌"
            print(f"   {status_icon} {robot_ip} ({description}): {result['status'].upper()}")
            if result['status'] == 'non-compliant':
                print(f"      - Differences: {len(result['differences'])}")
                print(f"      - Missing files: {len(result['missing_files'])}")
        except Exception as e:
            print(f"   ⚠️  {robot_ip}: Error - {e}")
    
    print("\n" + "=" * 60)
    print("✅ Comparison engine test complete!")
    print("\nYou can now:")
    print("1. Open http://localhost:8000/static/comparison.html to use the GUI")
    print("2. Use the API endpoints directly:")
    print("   - POST /api/comparison/baseline/create")
    print("   - GET  /api/comparison/baseline")
    print("   - POST /api/comparison/compare")
    print("   - POST /api/comparison/check-compliance")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())