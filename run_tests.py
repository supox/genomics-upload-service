#!/usr/bin/env python3
"""
Test Runner for File Upload Service

This script provides different ways to run the test suite with various options:
- Smoke tests (quick verification)
- Full test suite
- Specific test categories
- Tests with different levels of verbosity

Usage:
    python run_tests.py [options]
    
Options:
    --smoke         Run smoke tests only (quick verification)
    --api           Run API tests only
    --e2e           Run end-to-end tests only
    --validation    Run validation tests only
    --health        Run health check tests only
    --manual        Run tests converted from manual testing
    --slow          Run slow tests only
    --fast          Run fast tests only (exclude slow tests)
    --coverage      Run tests with coverage report
    --no-capture    Don't capture output (show print statements)
    --verbose       Verbose output
    --help          Show this help message
"""

import os
import sys
import subprocess
import argparse
from pathlib import Path


def run_command(cmd: list, description: str):
    """Run a command and handle errors."""
    print(f"\n🚀 {description}")
    print(f"Running: {' '.join(cmd)}")
    print("=" * 80)
    
    result = subprocess.run(cmd, cwd=Path(__file__).parent)
    
    if result.returncode == 0:
        print(f"\n✅ {description} completed successfully!")
    else:
        print(f"\n❌ {description} failed!")
        
    return result.returncode == 0


def main():
    parser = argparse.ArgumentParser(
        description="Test runner for File Upload Service",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python run_tests.py --smoke              # Quick smoke tests
    python run_tests.py --api --verbose      # API tests with verbose output
    python run_tests.py --e2e --no-capture  # E2E tests with output
    python run_tests.py --coverage           # Full test suite with coverage
    python run_tests.py --fast               # All tests except slow ones
        """
    )
    
    # Test selection options
    parser.add_argument("--smoke", action="store_true", help="Run smoke tests only")
    parser.add_argument("--api", action="store_true", help="Run API tests only")
    parser.add_argument("--e2e", action="store_true", help="Run end-to-end tests only")
    parser.add_argument("--validation", action="store_true", help="Run validation tests only")
    parser.add_argument("--health", action="store_true", help="Run health check tests only")
    parser.add_argument("--manual", action="store_true", help="Run tests converted from manual testing")
    parser.add_argument("--slow", action="store_true", help="Run slow tests only")
    parser.add_argument("--fast", action="store_true", help="Run fast tests only (exclude slow tests)")
    parser.add_argument("--integration", action="store_true", help="Run integration tests only")
    
    # Test execution options
    parser.add_argument("--coverage", action="store_true", help="Run tests with coverage report")
    parser.add_argument("--no-capture", action="store_true", help="Don't capture output (show print statements)")
    parser.add_argument("--verbose", action="store_true", help="Verbose output")
    parser.add_argument("--parallel", action="store_true", help="Run tests in parallel")
    parser.add_argument("--failfast", action="store_true", help="Stop on first failure")
    parser.add_argument("--fast-mode", action="store_true", help="Run tests with speed optimizations")
    
    args = parser.parse_args()
    
    # Build pytest command
    cmd = [sys.executable, "-m", "pytest"]
    
    # Fast mode optimizations
    if args.fast_mode:
        cmd.extend([
            "--no-cov",  # Disable coverage
            "-x",  # Stop on first failure
            "--tb=no",  # No traceback
            "--disable-warnings",  # Disable warnings
            "-q",  # Quiet output
        ])
        print("🚀 Fast mode enabled - optimized for speed")
    
    # Add test selection markers
    markers = []
    if args.smoke:
        markers.append("smoke")
    if args.api:
        markers.append("api")
    if args.e2e:
        markers.append("e2e")
    if args.validation:
        markers.append("validation")
    if args.health:
        markers.append("health")
    if args.manual:
        markers.append("manual")
    if args.slow:
        markers.append("slow")
    if args.integration:
        markers.append("integration")
    
    if args.fast:
        markers.append("not slow")
    
    if markers:
        cmd.extend(["-m", " or ".join(markers)])
    
    # Add execution options
    if args.coverage:
        cmd.extend(["--cov=src", "--cov-report=term-missing", "--cov-report=html:data/htmlcov"])
    
    if args.no_capture:
        cmd.append("-s")
    
    if args.verbose:
        cmd.append("-v")
    
    if args.parallel:
        cmd.extend(["-n", "auto"])
    
    if args.failfast:
        cmd.append("--maxfail=1")
    
    # Add default options
    cmd.extend([
        "--tb=short",
        "--color=yes",
        "--durations=10"
    ])
    
    # Determine description
    if markers:
        description = f"Running {' and '.join(markers)} tests"
    else:
        description = "Running all tests"
    
    # Run the command
    success = run_command(cmd, description)
    
    # Additional information
    if success:
        print("\n🎉 Test run completed successfully!")
        
        if args.coverage:
            print("\n📊 Coverage report:")
            print("  - Terminal report shown above")
            print("  - HTML report: data/htmlcov/index.html")
        
        print("\n💡 Other useful commands:")
        print("  python run_tests.py --smoke         # Quick smoke tests")
        print("  python run_tests.py --api           # API tests only")
        print("  python run_tests.py --e2e           # End-to-end tests only")
        print("  python run_tests.py --fast          # All tests except slow ones")
        print("  python run_tests.py --coverage      # Full test suite with coverage")
        
    else:
        print("\n🔧 Test run failed. Common solutions:")
        print("  1. Make sure services are running: docker-compose up -d")
        print("  2. Check service health: curl http://localhost:8000/health")
        print("  3. Check LocalStack: curl http://localhost:4566/_localstack/health")
        print("  4. Install dependencies: pip install -r requirements.txt")
        
        sys.exit(1)


if __name__ == "__main__":
    main() 
