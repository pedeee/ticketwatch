#!/usr/bin/env python3
"""
Test the extract_status function with real HTML
"""

import sys
sys.path.append('.')

from ticketwatch_v2 import extract_status

# Read the HTML we saved
with open('test_output.html', 'r', encoding='utf-8') as f:
    html = f.read()

print("🔍 Testing extract_status function...")
result = extract_status(html)

print("\n📊 EXTRACTION RESULTS:")
print(f"Title: {result.get('title', 'NOT FOUND')}")
print(f"Price: {result.get('price', 'NOT FOUND')}")
print(f"Price Range: {result.get('price_range', 'NOT FOUND')}")
print(f"Sold Out: {result.get('soldout', 'NOT FOUND')}")
print(f"Event Date: {result.get('event_dt', 'NOT FOUND')}")
print(f"Cancelled: {result.get('cancelled', 'NOT FOUND')}")
print(f"Terminated: {result.get('terminated', 'NOT FOUND')}")
print(f"Presale: {result.get('presale', 'NOT FOUND')}")
print(f"Sold Out Banner: {result.get('sold_out_banner', 'NOT FOUND')}")
