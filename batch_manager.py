#!/usr/bin/env python3
"""
Batch Manager for Ticketwatch - Manage your batch system efficiently

Usage:
    python batch_manager.py add <url> [--batch=N]       # Add to specific batch or auto-assign
    python batch_manager.py add <url1> <url2> ...       # Add multiple URLs
    python batch_manager.py list                        # Show all batches
    python batch_manager.py stats                       # Show batch statistics  
    python batch_manager.py sort [--batch=N]            # Sort specific batch or all batches
    python batch_manager.py balance                     # Rebalance URLs across batches
    python batch_manager.py run [--batch=N]             # Run specific batch or all batches
    python batch_manager.py validate                    # Validate all batches
    python batch_manager.py preview [--batch=N]         # Preview past events that could be removed
    python batch_manager.py clean [--batch=N]           # Remove past events (no confirmation)
    python batch_manager.py clean --review [--batch=N]  # Remove past events with confirmation
"""

import sys
import os
import glob
import asyncio
import subprocess
from typing import List, Dict, Any, Optional
from url_manager import fetch_event_info
from ticketwatch_v2 import load_lines, save_sorted_urls, load_state

BATCH_DIR = "url_batches"
BATCH_SIZE = 75  # URLs per batch

def get_batch_files() -> List[str]:
    """Get all batch files in order"""
    return sorted(glob.glob(f"{BATCH_DIR}/batch*.txt"))

def get_batch_stats():
    """Get statistics for all batches"""
    batch_files = get_batch_files()
    stats = {}
    total_urls = 0
    
    for batch_file in batch_files:
        batch_name = os.path.basename(batch_file).replace('.txt', '')
        try:
            urls = load_lines(batch_file)
            state_file = f"{batch_file}.state.json"
            state = load_state(state_file) if os.path.exists(state_file) else {}
            
            # Count events with dates
            with_dates = sum(1 for url in urls if state.get(url, {}).get("event_dt"))
            
            stats[batch_name] = {
                "file": batch_file,
                "url_count": len(urls),
                "with_dates": with_dates,
                "without_dates": len(urls) - with_dates
            }
            total_urls += len(urls)
        except:
            stats[batch_name] = {"file": batch_file, "url_count": 0, "with_dates": 0, "without_dates": 0}
    
    return stats, total_urls

def find_smallest_batch() -> str:
    """Find the batch with the fewest URLs"""
    stats, _ = get_batch_stats()
    if not stats:
        return f"{BATCH_DIR}/batch1.txt"
    
    smallest = min(stats.items(), key=lambda x: x[1]["url_count"])
    return smallest[1]["file"]

def add_urls_to_batch(urls: List[str], batch_num: Optional[int] = None):
    """Add URLs to a specific batch or auto-assign"""
    if batch_num:
        batch_file = f"{BATCH_DIR}/batch{batch_num}.txt"
    else:
        batch_file = find_smallest_batch()
    
    # Create batch directory if it doesn't exist
    os.makedirs(BATCH_DIR, exist_ok=True)
    
    # Load existing URLs
    try:
        existing_urls = load_lines(batch_file)
    except:
        existing_urls = []
    
    added_count = 0
    for url in urls:
        url = url.strip()
        if not url:
            continue
            
        # Check if URL exists in any batch
        if url_exists_in_batches(url):
            print(f"⚠️  URL already exists: {url}")
            continue
            
        existing_urls.append(url)
        added_count += 1
        print(f"✅ Added to {os.path.basename(batch_file)}: {url}")
    
    if added_count > 0:
        with open(batch_file, "w") as f:
            f.write("\n".join(existing_urls) + "\n")
        print(f"\n🎉 Added {added_count} URLs to {os.path.basename(batch_file)}")

def url_exists_in_batches(url: str) -> bool:
    """Check if URL exists in any batch"""
    for batch_file in get_batch_files():
        try:
            urls = load_lines(batch_file)
            if url in urls:
                return True
        except:
            continue
    return False

def list_batches():
    """List all batches with their statistics"""
    stats, total = get_batch_stats()
    
    print(f"📊 Batch Statistics ({total} total URLs)\n")
    
    for batch_name, info in stats.items():
        print(f"📁 {batch_name}:")
        print(f"   URLs: {info['url_count']}")
        print(f"   With dates: {info['with_dates']}")
        print(f"   Missing dates: {info['without_dates']}")
        print()

async def sort_batch(batch_num: Optional[int] = None):
    """Sort specific batch or all batches by date"""
    if batch_num:
        batch_files = [f"{BATCH_DIR}/batch{batch_num}.txt"]
    else:
        batch_files = get_batch_files()
    
    for batch_file in batch_files:
        batch_name = os.path.basename(batch_file).replace('.txt', '')
        print(f"🔄 Sorting {batch_name}...")
        
        try:
            urls = load_lines(batch_file)
            print(f"📡 Fetching event data for {len(urls)} URLs...")
            
            # Fetch fresh data
            event_data = {}
            for i, url in enumerate(urls):
                print(f"  Fetching {i+1}/{len(urls)}: {url[:50]}...")
                info = await fetch_event_info(url)
                if info:
                    event_data[url] = info
            
            # Save sorted
            save_sorted_urls(batch_file, urls, event_data)
            
            # Save state
            state_file = f"{batch_file}.state.json"
            from ticketwatch_v2 import save_state
            save_state(state_file, event_data)
            
            print(f"✅ {batch_name} sorted and saved!")
        except Exception as e:
            print(f"❌ Error sorting {batch_name}: {e}")

def balance_batches():
    """Rebalance URLs evenly across batches"""
    print("🔄 Rebalancing URLs across batches...")
    
    # Collect all URLs
    all_urls = []
    for batch_file in get_batch_files():
        try:
            urls = load_lines(batch_file)
            all_urls.extend(urls)
        except:
            continue
    
    if not all_urls:
        print("❌ No URLs found to balance")
        return
    
    # Calculate batches needed
    num_batches = max(5, (len(all_urls) + BATCH_SIZE - 1) // BATCH_SIZE)
    urls_per_batch = len(all_urls) // num_batches
    
    print(f"📊 Distributing {len(all_urls)} URLs across {num_batches} batches (~{urls_per_batch} each)")
    
    # Create new batch files
    for i in range(num_batches):
        start_idx = i * urls_per_batch
        end_idx = start_idx + urls_per_batch if i < num_batches - 1 else len(all_urls)
        batch_urls = all_urls[start_idx:end_idx]
        
        batch_file = f"{BATCH_DIR}/batch{i+1}.txt"
        with open(batch_file, "w") as f:
            f.write("\n".join(batch_urls) + "\n")
        
        print(f"✅ Created {os.path.basename(batch_file)} with {len(batch_urls)} URLs")

def run_batches(batch_num: Optional[int] = None):
    """Run ticketwatch on specific batch or all batches"""
    if batch_num:
        batch_files = [f"{BATCH_DIR}/batch{batch_num}.txt"]
    else:
        batch_files = get_batch_files()
    
    print(f"🚀 Running ticketwatch on {len(batch_files)} batches...\n")
    
    for batch_file in batch_files:
        batch_name = os.path.basename(batch_file).replace('.txt', '')
        print(f"▶️  Running {batch_name}...")
        
        try:
            result = subprocess.run([
                sys.executable, "ticketwatch_v2.py", batch_file
            ], capture_output=True, text=True)
            
            if result.returncode == 0:
                print(f"✅ {batch_name} completed successfully")
            else:
                print(f"❌ {batch_name} failed: {result.stderr}")
        except Exception as e:
            print(f"💥 Error running {batch_name}: {e}")
        print()

def validate_batches():
    """Validate all batch files"""
    print("🔍 Validating all batches...\n")
    
    batch_files = get_batch_files()
    total_issues = 0
    
    for batch_file in batch_files:
        batch_name = os.path.basename(batch_file).replace('.txt', '')
        print(f"Checking {batch_name}...")
        
        try:
            urls = load_lines(batch_file)
            state_file = f"{batch_file}.state.json"
            state = load_state(state_file) if os.path.exists(state_file) else {}
            
            issues = []
            if not urls:
                issues.append("No URLs found")
            if not os.path.exists(state_file):
                issues.append("Missing state file")
            
            missing_dates = sum(1 for url in urls if not state.get(url, {}).get("event_dt"))
            if missing_dates:
                issues.append(f"{missing_dates} URLs missing dates")
            
            if issues:
                print(f"  ⚠️  Issues: {', '.join(issues)}")
                total_issues += len(issues)
            else:
                print(f"  ✅ OK ({len(urls)} URLs)")
                
        except Exception as e:
            print(f"  ❌ Error: {e}")
            total_issues += 1
        print()
    
    if total_issues == 0:
        print("🎉 All batches are valid!")
    else:
        print(f"⚠️  Found {total_issues} issues across batches")

def clean_batch_past_events(batch_num: Optional[int] = None, review_mode: bool = False):
    """Remove past events from specific batch(es) with optional review"""
    if batch_num:
        batch_files = [f"{BATCH_DIR}/batch{batch_num}.txt"]
    else:
        batch_files = get_batch_files()
    
    total_removed = 0
    total_past_found = 0
    
    for batch_file in batch_files:
        batch_name = os.path.basename(batch_file).replace('.txt', '')
        print(f"\n🔍 Checking {batch_name}...")
        
        try:
            urls = load_lines(batch_file)
            state_file = f"{batch_file}.state.json"
            state = load_state(state_file) if os.path.exists(state_file) else {}
        except:
            print(f"❌ Could not load {batch_name}")
            continue
        
        past_events = []
        active_urls = []
        
        for url in urls:
            event_info = state.get(url, {})
            if event_info.get("event_dt"):
                try:
                    from dateutil import parser as dtparse, tz
                    from datetime import datetime
                    event_dt = dtparse.parse(event_info["event_dt"])
                    if event_dt < datetime.now(tz.tzutc()):
                        past_events.append((url, event_info.get("title", "Unknown"), event_dt.strftime("%b %d, %Y")))
                    else:
                        active_urls.append(url)
                except:
                    active_urls.append(url)
            else:
                active_urls.append(url)
        
        if not past_events:
            print(f"  ✅ No past events in {batch_name}")
            continue
        
        total_past_found += len(past_events)
        print(f"  📅 Found {len(past_events)} past events:")
        for i, (url, title, date_str) in enumerate(past_events[:5], 1):  # Show first 5
            print(f"    {i:2}. {title} - {date_str}")
        if len(past_events) > 5:
            print(f"    ... and {len(past_events) - 5} more")
        
        if review_mode:
            response = input(f"\n  Remove {len(past_events)} events from {batch_name}? (y/N): ").strip().lower()
            if response not in ['y', 'yes']:
                print(f"  ❌ Skipped {batch_name}")
                continue
        
        # Save cleaned batch
        save_sorted_urls(batch_file, active_urls, state)
        print(f"  🗑️ Removed {len(past_events)} events from {batch_name}")
        total_removed += len(past_events)
    
    print(f"\n📊 Summary:")
    print(f"  Past events found: {total_past_found}")
    print(f"  Events removed: {total_removed}")
    if review_mode and total_removed < total_past_found:
        print(f"  Events kept: {total_past_found - total_removed}")

def preview_cleanup(batch_num: Optional[int] = None):
    """Preview what would be removed without actually removing anything"""
    if batch_num:
        batch_files = [f"{BATCH_DIR}/batch{batch_num}.txt"]
    else:
        batch_files = get_batch_files()
    
    total_past = 0
    
    print("🔍 Preview of past events that could be removed:\n")
    
    for batch_file in batch_files:
        batch_name = os.path.basename(batch_file).replace('.txt', '')
        
        try:
            urls = load_lines(batch_file)
            state_file = f"{batch_file}.state.json"
            state = load_state(state_file) if os.path.exists(state_file) else {}
        except:
            continue
        
        past_events = []
        for url in urls:
            event_info = state.get(url, {})
            if event_info.get("event_dt"):
                try:
                    from dateutil import parser as dtparse, tz
                    from datetime import datetime
                    event_dt = dtparse.parse(event_info["event_dt"])
                    if event_dt < datetime.now(tz.tzutc()):
                        past_events.append((event_info.get("title", "Unknown"), event_dt.strftime("%b %d, %Y")))
                except:
                    pass
        
        if past_events:
            print(f"📁 {batch_name} ({len(past_events)} past events):")
            for title, date_str in sorted(past_events, key=lambda x: x[1])[:3]:
                print(f"  • {title} - {date_str}")
            if len(past_events) > 3:
                print(f"  ... and {len(past_events) - 3} more")
            print()
            total_past += len(past_events)
    
    if total_past == 0:
        print("✅ No past events found!")
    else:
        print(f"📊 Total: {total_past} past events could be removed")
        print(f"\n💡 To remove with confirmation: python3 batch_manager.py clean --review")
        print(f"💡 To remove automatically: python3 batch_manager.py clean")

def print_usage():
    print(__doc__)

def parse_batch_arg(args: List[str]) -> Optional[int]:
    """Parse --batch=N argument"""
    for arg in args:
        if arg.startswith("--batch="):
            try:
                return int(arg.split("=")[1])
            except ValueError:
                print("❌ Invalid batch number")
                return None
    return None

async def main():
    if len(sys.argv) < 2:
        print_usage()
        return
    
    command = sys.argv[1].lower()
    
    if command == "add":
        if len(sys.argv) < 3:
            print("❌ Please provide URL(s) to add")
            return
        
        batch_num = parse_batch_arg(sys.argv[2:])
        urls = [arg for arg in sys.argv[2:] if not arg.startswith("--")]
        add_urls_to_batch(urls, batch_num)
    
    elif command == "list":
        list_batches()
    
    elif command == "stats":
        list_batches()
    
    elif command == "sort":
        batch_num = parse_batch_arg(sys.argv[2:])
        await sort_batch(batch_num)
    
    elif command == "balance":
        balance_batches()
    
    elif command == "run":
        batch_num = parse_batch_arg(sys.argv[2:])
        run_batches(batch_num)
    
    elif command == "validate":
        validate_batches()
    
    elif command == "clean":
        review_mode = "--review" in sys.argv[2:]
        batch_num = parse_batch_arg(sys.argv[2:])
        clean_batch_past_events(batch_num, review_mode)
    
    elif command == "preview":
        batch_num = parse_batch_arg(sys.argv[2:])
        preview_cleanup(batch_num)
    
    else:
        print(f"❌ Unknown command: {command}")
        print_usage()

if __name__ == "__main__":
    asyncio.run(main())