#!/usr/bin/env python3
"""
Comprehensive test of the bot with multiple URLs from different batches
"""

import asyncio
import sys
sys.path.append('.')

from ticketwatch_v2 import fetch_url_with_playwright, extract_status
import asyncio

async def test_multiple_urls():
    """Test multiple URLs to ensure extraction works properly"""
    
    # Get URLs from batch files
    test_urls = []
    
    for batch_num in range(1, 4):  # Test first 3 batches
        try:
            with open(f'url_batches/batch{batch_num}.txt', 'r') as f:
                lines = [line.strip() for line in f if line.strip()]
                urls = [line for line in lines if line.startswith('http')]
                # Take first 2 URLs from each batch
                test_urls.extend(urls[:2])
        except:
            print(f"⚠️ Could not read batch{batch_num}.txt")
    
    print(f"🔍 Testing {len(test_urls)} URLs from multiple batches...")
    print("=" * 80)
    
    semaphore = asyncio.Semaphore(1)  # Test one at a time for thoroughness
    results = []
    
    for i, url in enumerate(test_urls, 1):
        print(f"\n📊 TEST {i}/{len(test_urls)}: {url}")
        print("-" * 60)
        
        try:
            # Fetch with Playwright
            url_result, event_data = await fetch_url_with_playwright(url, semaphore)
            
            if event_data:
                print(f"✅ Title: {event_data.get('title', 'NOT FOUND')}")
                print(f"✅ Price: {event_data.get('price', 'NOT FOUND')}")
                print(f"✅ Price Range: {event_data.get('price_range', 'NOT FOUND')}")
                print(f"✅ Sold Out: {event_data.get('soldout', 'NOT FOUND')}")
                print(f"✅ Event Date: {event_data.get('event_dt', 'NOT FOUND')}")
                print(f"✅ Cancelled: {event_data.get('cancelled', 'NOT FOUND')}")
                print(f"✅ Terminated: {event_data.get('terminated', 'NOT FOUND')}")
                print(f"✅ Presale: {event_data.get('presale', 'NOT FOUND')}")
                
                # Check for issues
                issues = []
                if event_data.get('title', '').startswith('Unknown Event'):
                    issues.append("❌ Unknown Event title")
                if event_data.get('event_dt') is None:
                    issues.append("❌ No event date")
                if event_data.get('price') is None and not event_data.get('soldout'):
                    issues.append("❌ No price found (and not sold out)")
                
                if issues:
                    print(f"⚠️ ISSUES: {', '.join(issues)}")
                else:
                    print("✅ All data extracted successfully!")
                
                results.append({
                    'url': url,
                    'success': True,
                    'data': event_data,
                    'issues': issues
                })
            else:
                print("❌ No event data returned")
                results.append({
                    'url': url,
                    'success': False,
                    'data': None,
                    'issues': ['No data returned']
                })
                
        except Exception as e:
            print(f"❌ Error: {e}")
            results.append({
                'url': url,
                'success': False,
                'data': None,
                'issues': [f'Error: {e}']
            })
    
    # Summary
    print("\n" + "=" * 80)
    print("📊 COMPREHENSIVE TEST SUMMARY")
    print("=" * 80)
    
    successful = [r for r in results if r['success']]
    failed = [r for r in results if not r['success']]
    
    print(f"✅ Successful: {len(successful)}/{len(results)}")
    print(f"❌ Failed: {len(failed)}/{len(results)}")
    
    if successful:
        print(f"\n📈 SUCCESS RATE: {len(successful)/len(results)*100:.1f}%")
        
        # Check for common issues
        unknown_events = [r for r in successful if r['data'] and r['data'].get('title', '').startswith('Unknown Event')]
        no_dates = [r for r in successful if r['data'] and r['data'].get('event_dt') is None]
        no_prices = [r for r in successful if r['data'] and r['data'].get('price') is None and not r['data'].get('soldout')]
        
        if unknown_events:
            print(f"⚠️ {len(unknown_events)} events have 'Unknown Event' titles")
        if no_dates:
            print(f"⚠️ {len(no_dates)} events missing dates")
        if no_prices:
            print(f"⚠️ {len(no_prices)} events missing prices (and not sold out)")
    
    if failed:
        print(f"\n❌ FAILED URLs:")
        for r in failed:
            print(f"   - {r['url']}: {', '.join(r['issues'])}")
    
    # Overall assessment
    if len(successful) == len(results) and not any(r['issues'] for r in successful):
        print("\n🎉 ALL TESTS PASSED! Bot is ready for production.")
        return True
    elif len(successful) >= len(results) * 0.8:  # 80% success rate
        print("\n✅ GOOD SUCCESS RATE! Minor issues to address.")
        return True
    else:
        print("\n❌ POOR SUCCESS RATE! Major issues need fixing.")
        return False

if __name__ == "__main__":
    success = asyncio.run(test_multiple_urls())
    sys.exit(0 if success else 1)
