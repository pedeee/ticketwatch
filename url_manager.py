#!/usr/bin/env python3
"""
URL Manager for Ticketwatch - Easy URL list management

Usage:
    python url_manager.py add <url>                 # Add a new URL
    python url_manager.py add <url1> <url2> ...     # Add multiple URLs
    python url_manager.py remove <url>              # Remove a URL
    python url_manager.py list                      # Show all URLs with dates
    python url_manager.py sort                      # Sort URLs by date
    python url_manager.py validate                  # Check all URLs and dates
    python url_manager.py clean                     # Remove past events
    python url_manager.py stats                     # Show statistics
"""

import sys
import json
import requests
import asyncio
import aiohttp
from datetime import datetime
from typing import Dict, List, Any, Optional
from bs4 import BeautifulSoup
from dateutil import parser as dtparse, tz

# Import from main script
from ticketwatch_v2 import (
    extract_status, load_lines, load_state, save_state, 
    save_sorted_urls, HEADERS, URL_FILE, STATE_FILE
)

def print_usage():
    print(__doc__)

async def fetch_event_info(url: str) -> Optional[Dict[str, Any]]:
    """Fetch event information for a single URL"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=HEADERS, timeout=30) as response:
                response.raise_for_status()
                html = await response.text()
                return extract_status(html)
    except Exception as e:
        print(f"⚠️  Failed to fetch {url}: {e}")
        return None

def add_urls(new_urls: List[str]):
    """Add new URLs to the list"""
    try:
        existing_urls = load_lines(URL_FILE)
    except SystemExit:
        existing_urls = []
        print("📝 Creating new urls.txt file")
    
    added_count = 0
    for url in new_urls:
        url = url.strip()
        if not url:
            continue
            
        if url in existing_urls:
            print(f"⚠️  URL already exists: {url}")
            continue
            
        existing_urls.append(url)
        added_count += 1
        print(f"✅ Added: {url}")
    
    if added_count > 0:
        # Save temporarily without sorting (will sort after fetching data)
        with open(URL_FILE, "w") as f:
            f.write("\n".join(existing_urls) + "\n")
        print(f"\n🎉 Added {added_count} new URLs")
        print("🔄 Run 'python url_manager.py sort' to organize by date")
    else:
        print("❌ No new URLs were added")

def remove_url(url_to_remove: str):
    """Remove a URL from the list"""
    try:
        urls = load_lines(URL_FILE)
    except SystemExit:
        print("❌ No urls.txt file found")
        return
    
    if url_to_remove not in urls:
        print(f"❌ URL not found: {url_to_remove}")
        return
    
    urls.remove(url_to_remove)
    with open(URL_FILE, "w") as f:
        f.write("\n".join(urls) + "\n")
    print(f"🗑️ Removed: {url_to_remove}")

def list_urls():
    """List all URLs with their event information"""
    try:
        urls = load_lines(URL_FILE)
        state = load_state(STATE_FILE)
    except SystemExit:
        print("❌ No urls.txt file found")
        return
    
    if not urls:
        print("📝 No URLs in the list")
        return
    
    print(f"📋 Current URL list ({len(urls)} events):\n")
    
    # Group by month
    events_by_month = {}
    events_without_date = []
    
    for i, url in enumerate(urls, 1):
        event_info = state.get(url, {})
        title = event_info.get("title", "Unknown Event")
        
        if event_info.get("event_dt"):
            try:
                event_dt = dtparse.parse(event_info["event_dt"])
                month_year = event_dt.strftime("%B %Y")
                date_str = event_dt.strftime("%b %d")
                
                if month_year not in events_by_month:
                    events_by_month[month_year] = []
                events_by_month[month_year].append((i, title, date_str, url))
            except:
                events_without_date.append((i, title, "Date error", url))
        else:
            events_without_date.append((i, title, "No date", url))
    
    # Print events by month
    for month in sorted(events_by_month.keys()):
        print(f"━━━ {month} ━━━")
        for i, title, date_str, url in sorted(events_by_month[month], key=lambda x: x[2]):
            print(f"{i:3}. {title} - {date_str}")
            print(f"     {url}")
        print()
    
    # Print events without dates
    if events_without_date:
        print("━━━ Events without dates ━━━")
        for i, title, date_str, url in events_without_date:
            print(f"{i:3}. {title} - {date_str}")
            print(f"     {url}")

async def sort_urls():
    """Sort URLs by event date"""
    try:
        urls = load_lines(URL_FILE)
    except SystemExit:
        print("❌ No urls.txt file found")
        return
    
    print(f"🔄 Fetching event data for {len(urls)} URLs...")
    
    # Fetch fresh data for all URLs
    event_data = {}
    for i, url in enumerate(urls):
        print(f"📡 Fetching {i+1}/{len(urls)}: {url[:50]}...")
        info = await fetch_event_info(url)
        if info:
            event_data[url] = info
    
    # Save the sorted URLs
    save_sorted_urls(URL_FILE, urls, event_data)
    save_state(STATE_FILE, event_data)
    print("✅ URLs sorted and saved!")

async def validate_urls():
    """Validate all URLs and show any issues"""
    try:
        urls = load_lines(URL_FILE)
    except SystemExit:
        print("❌ No urls.txt file found")
        return
    
    print(f"🔍 Validating {len(urls)} URLs...\n")
    
    failed_urls = []
    past_events = []
    no_date_urls = []
    
    for i, url in enumerate(urls):
        print(f"Checking {i+1}/{len(urls)}: {url[:50]}...")
        info = await fetch_event_info(url)
        
        if not info:
            failed_urls.append(url)
            continue
        
        # Check if past event
        if info.get("event_dt"):
            try:
                event_dt = dtparse.parse(info["event_dt"])
                if event_dt < datetime.now(tz.tzutc()):
                    past_events.append((url, info["title"], event_dt.strftime("%b %d, %Y")))
            except:
                no_date_urls.append((url, info["title"]))
        else:
            no_date_urls.append((url, info["title"]))
    
    # Report results
    print(f"\n📊 Validation Results:")
    print(f"✅ Working URLs: {len(urls) - len(failed_urls)}")
    print(f"❌ Failed URLs: {len(failed_urls)}")
    print(f"🗓️ Past events: {len(past_events)}")
    print(f"❓ Missing dates: {len(no_date_urls)}")
    
    if failed_urls:
        print(f"\n❌ Failed URLs:")
        for url in failed_urls:
            print(f"  • {url}")
    
    if past_events:
        print(f"\n🗓️ Past events (should be removed):")
        for url, title, date_str in past_events:
            print(f"  • {title} - {date_str}")
    
    if no_date_urls:
        print(f"\n❓ URLs without event dates:")
        for url, title in no_date_urls:
            print(f"  • {title}")

def clean_past_events():
    """Remove past events from the URL list"""
    try:
        urls = load_lines(URL_FILE)
        state = load_state(STATE_FILE)
    except SystemExit:
        print("❌ No urls.txt file found")
        return
    
    past_events = []
    active_urls = []
    
    for url in urls:
        event_info = state.get(url, {})
        if event_info.get("event_dt"):
            try:
                event_dt = dtparse.parse(event_info["event_dt"])
                if event_dt < datetime.now(tz.tzutc()):
                    past_events.append((url, event_info.get("title", "Unknown"), event_dt.strftime("%b %d, %Y")))
                else:
                    active_urls.append(url)
            except:
                active_urls.append(url)  # Keep if date parsing fails
        else:
            active_urls.append(url)  # Keep if no date
    
    if past_events:
        print(f"🗑️ Removing {len(past_events)} past events:")
        for url, title, date_str in past_events:
            print(f"  • {title} - {date_str}")
        
        save_sorted_urls(URL_FILE, active_urls, state)
        print(f"✅ Cleaned! {len(active_urls)} URLs remaining")
    else:
        print("✅ No past events found to remove")

def show_stats():
    """Show statistics about the URL list"""
    try:
        urls = load_lines(URL_FILE)
        state = load_state(STATE_FILE)
    except SystemExit:
        print("❌ No urls.txt file found")
        return
    
    print(f"📊 Ticketwatch Statistics\n")
    print(f"Total URLs: {len(urls)}")
    
    # Count by status
    with_dates = 0
    without_dates = 0
    past_events = 0
    upcoming_events = 0
    sold_out = 0
    
    # Count by month
    monthly_counts = {}
    
    for url in urls:
        event_info = state.get(url, {})
        
        if event_info.get("soldout"):
            sold_out += 1
        
        if event_info.get("event_dt"):
            with_dates += 1
            try:
                event_dt = dtparse.parse(event_info["event_dt"])
                month_year = event_dt.strftime("%B %Y")
                monthly_counts[month_year] = monthly_counts.get(month_year, 0) + 1
                
                if event_dt < datetime.now(tz.tzutc()):
                    past_events += 1
                else:
                    upcoming_events += 1
            except:
                without_dates += 1
        else:
            without_dates += 1
    
    print(f"Events with dates: {with_dates}")
    print(f"Events without dates: {without_dates}")
    print(f"Upcoming events: {upcoming_events}")
    print(f"Past events: {past_events}")
    print(f"Sold out events: {sold_out}")
    
    if monthly_counts:
        print(f"\n📅 Events by month:")
        for month in sorted(monthly_counts.keys()):
            print(f"  {month}: {monthly_counts[month]} events")

async def main():
    if len(sys.argv) < 2:
        print_usage()
        return
    
    command = sys.argv[1].lower()
    
    if command == "add":
        if len(sys.argv) < 3:
            print("❌ Please provide URL(s) to add")
            print("Usage: python url_manager.py add <url1> [url2] ...")
            return
        add_urls(sys.argv[2:])
    
    elif command == "remove":
        if len(sys.argv) < 3:
            print("❌ Please provide URL to remove")
            print("Usage: python url_manager.py remove <url>")
            return
        remove_url(sys.argv[2])
    
    elif command == "list":
        list_urls()
    
    elif command == "sort":
        await sort_urls()
    
    elif command == "validate":
        await validate_urls()
    
    elif command == "clean":
        clean_past_events()
    
    elif command == "stats":
        show_stats()
    
    else:
        print(f"❌ Unknown command: {command}")
        print_usage()

if __name__ == "__main__":
    asyncio.run(main())