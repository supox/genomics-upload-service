#!/usr/bin/env python3
"""
End-to-End Test Runner

This script helps run the e2e tests by:
1. Checking if Docker services are running
2. Running the test suite
3. Providing clear output and instructions

Usage:
    python run_e2e_tests.py
"""

import os
import sys
import subprocess
import time
import asyncio
import requests
from pathlib import Path

def check_docker_services():
    """Check if Docker services are running"""
    print("🔍 Checking Docker services...")
    
    try:
        # Check if docker-compose is running
        result = subprocess.run(
            ["docker-compose", "ps"], 
            capture_output=True, 
            text=True,
            cwd=Path(__file__).parent
        )
        
        if result.returncode != 0:
            print("❌ Docker Compose not running. Please start services first:")
            print("   docker-compose up -d")
            return False
        
        # Check if upload service is responding
        for attempt in range(30):
            try:
                response = requests.get("http://localhost:8000/health", timeout=5)
                if response.status_code == 200:
                    print("✅ Upload service is ready")
                    break
            except requests.RequestException:
                if attempt < 29:
                    print(f"⏳ Waiting for upload service... (attempt {attempt + 1}/30)")
                    time.sleep(2)
                else:
                    print("❌ Upload service not responding")
                    return False
        
        # Check if LocalStack is responding
        try:
            response = requests.get("http://localhost:4566/_localstack/health", timeout=5)
            if response.status_code == 200:
                print("✅ LocalStack S3 is ready")
            else:
                print("❌ LocalStack S3 not responding")
                return False
        except requests.RequestException:
            print("❌ LocalStack S3 not responding")
            return False
        
        return True
        
    except FileNotFoundError:
        print("❌ Docker Compose not found. Please install Docker and Docker Compose.")
        return False

def run_tests():
    """Run the e2e tests"""
    print("\n🧪 Running End-to-End Tests...")
    
    # Run pytest with e2e tests
    cmd = [
        sys.executable, "-m", "pytest",
        "tests/e2e/",
        "-v",
        "--tb=short",
        "--color=yes",
        "-s"  # Don't capture output so we can see real-time progress
    ]
    
    print(f"Running command: {' '.join(cmd)}")
    print("=" * 80)
    
    result = subprocess.run(cmd, cwd=Path(__file__).parent)
    
    if result.returncode == 0:
        print("\n✅ All tests passed!")
        return True
    else:
        print("\n❌ Some tests failed!")
        return False

def main():
    """Main test runner"""
    print("🚀 File Upload Service - End-to-End Test Runner")
    print("=" * 50)
    
    # Check if services are running
    if not check_docker_services():
        print("\n💡 To start the services, run:")
        print("   docker-compose up -d")
        print("   # Wait for services to be ready, then run this script again")
        sys.exit(1)
    
    # Run the tests
    success = run_tests()
    
    if success:
        print("\n🎉 All end-to-end tests completed successfully!")
        sys.exit(0)
    else:
        print("\n🔧 Some tests failed. Check the output above for details.")
        sys.exit(1)

if __name__ == "__main__":
    main() 
