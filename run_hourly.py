#!/usr/bin/env python3
"""
Hourly scheduler for ticketwatch - run this to monitor events every hour.

Usage:
    python run_hourly.py               # Run once
    python run_hourly.py --continuous  # Run continuously every hour
"""

import sys
import time
import subprocess
from datetime import datetime

def run_ticketwatch():
    """Run the ticketwatch script and handle errors"""
    try:
        print(f"\n{'='*60}")
        print(f"🕐 Starting ticketwatch run at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*60}")
        
        # Run the improved ticketwatch script
        result = subprocess.run([sys.executable, "ticketwatch_v2.py"], 
                              capture_output=False, text=True)
        
        if result.returncode == 0:
            print(f"✅ Ticketwatch completed successfully")
        else:
            print(f"❌ Ticketwatch failed with exit code {result.returncode}")
            
    except (subprocess.SubprocessError, FileNotFoundError, OSError) as e:
        print(f"💥 Error running ticketwatch: {e}")

def main():
    if "--continuous" in sys.argv:
        print("🎟️ Starting continuous hourly monitoring...")
        print("Press Ctrl+C to stop")
        
        try:
            while True:
                run_ticketwatch()
                print(f"\n💤 Sleeping for 1 hour...")
                time.sleep(3600)  # 1 hour = 3600 seconds
        except KeyboardInterrupt:
            print("\n⏹️ Stopping hourly monitoring")
    else:
        print("🎟️ Running ticketwatch once...")
        run_ticketwatch()

if __name__ == "__main__":
    main()