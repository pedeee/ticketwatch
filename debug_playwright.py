#!/usr/bin/env python3
"""
Debug script to see what HTML Playwright is actually getting from Ticketweb
"""

import asyncio
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup

async def debug_ticketweb_page(url):
    """Debug what HTML we're getting from a Ticketweb page"""
    print(f"🔍 Debugging: {url}")
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                '--no-sandbox',
                '--disable-dev-shm-usage',
                '--disable-blink-features=AutomationControlled',
                '--disable-features=VizDisplayCompositor'
            ]
        )
        
        context = await browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            locale='en-US',
            timezone_id='America/New_York'
        )
        
        page = await context.new_page()
        
        try:
            # Navigate to URL
            await page.goto(url, timeout=30000, wait_until='networkidle')
            
            # Wait a bit for any dynamic content
            await page.wait_for_timeout(3000)
            
            # Get page content
            html = await page.content()
            
            print(f"📄 HTML length: {len(html)} characters")
            
            # Parse with BeautifulSoup
            soup = BeautifulSoup(html, 'html.parser')
            
            # Look for common event data patterns
            print("\n🔍 Looking for event data...")
            
            # Check for JSON-LD structured data
            json_ld = soup.find_all('script', type='application/ld+json')
            print(f"📊 Found {len(json_ld)} JSON-LD scripts")
            
            for i, script in enumerate(json_ld):
                try:
                    import json
                    data = json.loads(script.string)
                    print(f"  JSON-LD {i+1}: {data}")
                except:
                    print(f"  JSON-LD {i+1}: Could not parse")
            
            # Look for price information
            price_elements = soup.find_all(text=re.compile(r'\$\d+'))
            print(f"💰 Found {len(price_elements)} price elements")
            
            # Look for date information
            date_elements = soup.find_all(text=re.compile(r'\d{1,2}/\d{1,2}/\d{4}'))
            print(f"📅 Found {len(date_elements)} date elements")
            
            # Look for sold out indicators
            sold_out_elements = soup.find_all(text=re.compile(r'sold.?out', re.I))
            print(f"🚫 Found {len(sold_out_elements)} sold out elements")
            
            # Save HTML to file for inspection
            with open('debug_output.html', 'w', encoding='utf-8') as f:
                f.write(html)
            print("💾 Saved HTML to debug_output.html")
            
            # Show first 1000 characters of HTML
            print(f"\n📝 First 1000 characters of HTML:")
            print(html[:1000])
            
        except Exception as e:
            print(f"❌ Error: {e}")
        finally:
            await browser.close()

async def main():
    # Test with a few URLs from batch1
    test_urls = [
        "https://www.ticketweb.com/event/example-event-1",
        "https://www.ticketweb.com/event/example-event-2"
    ]
    
    # Read actual URLs from batch1.txt
    try:
        with open('url_batches/batch1.txt', 'r') as f:
            lines = [line.strip() for line in f if line.strip()]
            # Filter out comments and get actual URLs
            urls = [line for line in lines if line.startswith('http')]
            test_urls = urls[:2]  # Test first 2 URLs
            print(f"📋 Found {len(urls)} URLs in batch1.txt")
    except:
        print("⚠️ Could not read batch1.txt, using example URLs")
    
    for url in test_urls:
        await debug_ticketweb_page(url)
        print("\n" + "="*80 + "\n")

if __name__ == "__main__":
    import re
    asyncio.run(main())
