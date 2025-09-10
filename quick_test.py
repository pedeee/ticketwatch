#!/usr/bin/env python3
"""
Quick test of the fixed Playwright implementation
"""

import asyncio
import sys
sys.path.append('.')

from ticketwatch_v2 import fetch_url_with_playwright

async def test_single_url():
    """Test a single URL to verify the fix"""
    url = "https://www.ticketweb.ca/event/comeback-kid-prowl-punitive-damage-overflow-brewing-co-tickets/14422243"
    
    print(f"🔍 Testing: {url}")
    
    semaphore = asyncio.Semaphore(1)
    
    try:
        url_result, event_data = await fetch_url_with_playwright(url, semaphore)
        
        if event_data:
            print(f"✅ Title: {event_data.get('title', 'NOT FOUND')}")
            print(f"✅ Price: {event_data.get('price', 'NOT FOUND')}")
            print(f"✅ Date: {event_data.get('event_dt', 'NOT FOUND')}")
            print(f"✅ Sold Out: {event_data.get('soldout', 'NOT FOUND')}")
            
            # Check if we got real data
            if (event_data.get('title') and not event_data.get('title').startswith('Unknown Event') and
                event_data.get('event_dt') and event_data.get('price')):
                print("🎉 SUCCESS: All data extracted properly!")
                return True
            else:
                print("❌ ISSUE: Missing key data")
                return False
        else:
            print("❌ No event data returned")
            return False
            
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

if __name__ == "__main__":
    success = asyncio.run(test_single_url())
    sys.exit(0 if success else 1)
