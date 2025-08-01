#!/usr/bin/env python3
"""
Hourly scheduler for ticketwatch - optimized for GitHub Actions and local use.

Usage:
    python run_hourly.py               # Run once
    python run_hourly.py --continuous  # Run continuously every hour
    python run_hourly.py --github      # GitHub Actions mode (with environment variables)
"""

import sys
import os
import time
import subprocess
from datetime import datetime

def check_environment():
    """Check if running in GitHub Actions and validate environment"""
    is_github = os.getenv("GITHUB_ACTIONS") == "true" or "--github" in sys.argv
    
    if is_github:
        print("🚀 Running in GitHub Actions mode")
        
        # Check required environment variables
        required_vars = ["TG_TOKEN", "TG_CHAT"]
        missing_vars = [var for var in required_vars if not os.getenv(var)]
        
        if missing_vars:
            print(f"⚠️  Missing environment variables: {', '.join(missing_vars)}")
            print("📧 Notifications may not work properly")
        else:
            print("✅ All environment variables configured")
    else:
        print("🏠 Running in local mode")
    
    return is_github

def check_system_health():
    """Check system health before running"""
    issues = []
    
    # Check required files
    required_files = ["urls.txt", "state.json", "ticketwatch_v2.py"]
    for file in required_files:
        if not os.path.exists(file):
            issues.append(f"Missing {file}")
    
    # Check URLs file is not empty
    if os.path.exists("urls.txt"):
        try:
            with open("urls.txt", "r") as f:
                lines = [line.strip() for line in f if line.strip() and not line.startswith("#")]
                if not lines:
                    issues.append("urls.txt is empty")
                else:
                    print(f"📊 Found {len(lines)} URLs to monitor")
        except Exception as e:
            issues.append(f"Cannot read urls.txt: {e}")
    
    if issues:
        print("❌ System health check failed:")
        for issue in issues:
            print(f"  • {issue}")
        return False
    
    print("✅ System health check passed")
    return True

def run_ticketwatch():
    """Run the ticketwatch script and handle errors"""
    try:
        print(f"\n{'='*60}")
        print(f"🕐 Starting ticketwatch run at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*60}")
        
        # Check system health first
        if not check_system_health():
            print("❌ Skipping run due to system health issues")
            return False
        
        # Set PRIMARY environment variable for the main process
        env = os.environ.copy()
        env["PRIMARY"] = "true"
        
        # Run the improved ticketwatch script
        result = subprocess.run([sys.executable, "ticketwatch_v2.py"], 
                              capture_output=False, text=True, env=env)
        
        if result.returncode == 0:
            print(f"✅ Ticketwatch completed successfully")
            return True
        else:
            print(f"❌ Ticketwatch failed with exit code {result.returncode}")
            return False
            
    except (subprocess.SubprocessError, FileNotFoundError, OSError) as e:
        print(f"💥 Error running ticketwatch: {e}")
        return False

def main():
    print("🎟️ Ticketwatch Hourly Runner")
    print("============================")
    
    # Check environment
    is_github = check_environment()
    
    if "--continuous" in sys.argv and not is_github:
        print("\n🔄 Starting continuous hourly monitoring...")
        print("Press Ctrl+C to stop")
        
        try:
            while True:
                success = run_ticketwatch()
                if not success and is_github:
                    print("❌ GitHub Actions mode: Exiting due to error")
                    sys.exit(1)
                print(f"\n💤 Sleeping for 1 hour...")
                time.sleep(3600)  # 1 hour = 3600 seconds
        except KeyboardInterrupt:
            print("\n⏹️ Stopping hourly monitoring")
    else:
        print("\n🚀 Running ticketwatch once...")
        success = run_ticketwatch()
        
        if is_github:
            # In GitHub Actions, we want to fail the job if ticketwatch fails
            if not success:
                print("❌ GitHub Actions: Job failed")
                sys.exit(1)
            else:
                print("✅ GitHub Actions: Job completed successfully")

if __name__ == "__main__":
    main()