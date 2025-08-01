#!/usr/bin/env python3
"""
Failed URLs Manager - View and manage the priority queue system
"""

import json
import os
from datetime import datetime

FAILED_URLS_FILE = "failed_urls.json"

def view_failed_urls():
    """Show current failed URLs"""
    if not os.path.exists(FAILED_URLS_FILE):
        print("✅ No failed URLs file found - all URLs are succeeding!")
        return
    
    try:
        with open(FAILED_URLS_FILE) as f:
            data = json.load(f)
        
        failed_urls = data.get("failed_urls", [])
        timestamp = data.get("timestamp", "Unknown")
        count = data.get("count", len(failed_urls))
        
        print(f"🔴 Failed URLs Report")
        print(f"=" * 50)
        print(f"📊 Count: {count} URLs")
        print(f"🕐 Last updated: {timestamp}")
        print(f"🎯 These URLs will get priority in next run")
        print()
        
        if failed_urls:
            print("📋 Failed URLs (showing first 10):")
            for i, url in enumerate(failed_urls[:10], 1):
                # Extract event name from URL if possible
                event_name = url.split('/')[-1].replace('-tickets', '').replace('-', ' ').title()
                print(f" {i:2}. {event_name[:50]}")
                print(f"     {url}")
            
            if len(failed_urls) > 10:
                print(f"     ... and {len(failed_urls) - 10} more URLs")
        else:
            print("✅ No failed URLs in queue")
            
    except Exception as e:
        print(f"❌ Error reading failed URLs file: {e}")

def reset_failed_urls():
    """Clear the failed URLs queue"""
    if os.path.exists(FAILED_URLS_FILE):
        try:
            os.remove(FAILED_URLS_FILE)
            print("✅ Failed URLs queue cleared")
            print("📝 Next run will use random selection from all URLs")
        except Exception as e:
            print(f"❌ Error clearing failed URLs: {e}")
    else:
        print("✅ No failed URLs file to clear")

def main():
    print("🎟️ Ticketwatch Failed URLs Manager")
    print("=" * 40)
    
    while True:
        print("\nOptions:")
        print("1. View current failed URLs")
        print("2. Reset/clear failed URLs queue") 
        print("3. Exit")
        
        choice = input("\nEnter choice (1-3): ").strip()
        
        if choice == "1":
            view_failed_urls()
        elif choice == "2":
            confirm = input("⚠️ Clear all failed URLs? (y/N): ").strip().lower()
            if confirm in ['y', 'yes']:
                reset_failed_urls()
            else:
                print("❌ Reset cancelled")
        elif choice == "3":
            print("👋 Goodbye!")
            break
        else:
            print("❌ Invalid choice")

if __name__ == "__main__":
    main()