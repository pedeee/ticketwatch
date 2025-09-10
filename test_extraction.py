#!/usr/bin/env python3
"""
Test script to debug data extraction issues
"""

import asyncio
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
import re

async def test_single_url():
    """Test data extraction on a single URL"""
    url = "https://www.ticketweb.ca/event/comeback-kid-prowl-punitive-damage-overflow-brewing-co-tickets/14422243"
    
    print(f"🔍 Testing: {url}")
    
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
            print("✅ Page loaded")
            
            # Wait for content
            await page.wait_for_timeout(5000)
            print("✅ Waited 5 seconds")
            
            # Get page content
            html = await page.content()
            print(f"📄 HTML length: {len(html)} characters")
            
            # Parse with BeautifulSoup
            soup = BeautifulSoup(html, 'html.parser')
            text = soup.get_text(" ", strip=True)
            
            # Look for specific patterns
            print("\n🔍 SEARCHING FOR DATA:")
            
            # Check for "not available" message
            not_available = soup.find_all(string=re.compile(r'not available', re.I))
            print(f"❌ 'Not available' messages: {len(not_available)}")
            if not_available:
                print(f"   Found: {not_available[0]}")
            
            # Look for event title
            title_selectors = [
                'meta[property="og:title"]',
                'title',
                'h1',
                '.event-title',
                '.event-name'
            ]
            
            title = None
            for selector in title_selectors:
                element = soup.select_one(selector)
                if element:
                    if selector.startswith('meta'):
                        title = element.get('content', '').strip()
                    else:
                        title = element.get_text(strip=True)
                    if title and title != "Ticketweb":
                        print(f"📝 Title found ({selector}): {title}")
                        break
            
            if not title or title == "Ticketweb":
                print("❌ No valid title found")
            
            # Look for dates
            date_patterns = [
                r'(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2}\s+\d{4}',
                r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2}',
                r'\d{1,2}/\d{1,2}/\d{4}',
                r'\d{4}-\d{2}-\d{2}'
            ]
            
            dates_found = []
            for pattern in date_patterns:
                matches = re.findall(pattern, text)
                if matches:
                    dates_found.extend(matches)
            
            print(f"📅 Dates found: {dates_found}")
            
            # Look for prices
            price_patterns = [
                r'\$([0-9]{1,5}(?:\.[0-9]{2})?)',
                r'\b([0-9]{1,3}(?:\.[0-9]{2})?)\b'
            ]
            
            prices_found = []
            for pattern in price_patterns:
                matches = re.findall(pattern, text)
                if matches:
                    prices_found.extend(matches)
            
            print(f"💰 Prices found: {prices_found}")
            
            # Look for sold out indicators
            sold_out_indicators = soup.find_all(string=re.compile(r'sold out', re.I))
            print(f"🚫 Sold out indicators: {len(sold_out_indicators)}")
            if sold_out_indicators:
                print(f"   Found: {sold_out_indicators[0]}")
            
            # Save HTML for inspection
            with open('test_output.html', 'w', encoding='utf-8') as f:
                f.write(html)
            print("💾 Saved HTML to test_output.html")
            
            # Show first 2000 characters of text
            print(f"\n📝 First 2000 characters of text:")
            print(text[:2000])
            
        except Exception as e:
            print(f"❌ Error: {e}")
        finally:
            await browser.close()

if __name__ == "__main__":
    asyncio.run(test_single_url())
