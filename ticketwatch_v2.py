#!/usr/bin/env python3
"""
ticketwatch_v2.py — High-performance monitor for Ticketweb event pages.

Features
────────
• Batch processing system (handles 281 URLs across 5 batches)
• Intelligent rate limiting to avoid IP blocks
• Enhanced anti-bot protection for GitHub Actions
• Batched notifications (summarizes changes, reduces spam)
• Single health check when no changes occur
• Robust error handling with retries
• Progress reporting and execution metrics
• Cloudflare-aware fallback when needed

Configuration
─────────────
• Conservative settings for GitHub Actions to avoid IP blocking
• MAX_CONCURRENT = 3 (GitHub Actions) / 20 (local)
• REQUEST_DELAY = 3.0s (GitHub Actions) / 0.1s (local)
• BATCH_SIZE = 10 changes per notification batch
"""

import json, os, re, sys, requests, random
import asyncio, time
from typing import Dict, Any, List, Tuple, Optional
from bs4 import BeautifulSoup
from subprocess import run, DEVNULL
from dateutil import parser as dtparse, tz
import datetime as dt
from dataclasses import dataclass
from playwright.async_api import async_playwright

# ─── Files & constants ────────────────────────────────────────────────────
# Batch system: each batch file has its own state and failed URLs tracking
if len(sys.argv) > 1 and sys.argv[1]:
    URL_FILE = sys.argv[1]  # e.g. url_batches/batch1.txt
    STATE_FILE = f"{URL_FILE}.state.json"
    FAILED_URLS_FILE = f"{URL_FILE}.failed.json"
else:
    # Fallback for local testing (not used in production)
    URL_FILE = "urls.txt"
    STATE_FILE = "state.json"
    FAILED_URLS_FILE = "failed_urls.json"

# ─── Configuration ────────────────────────────────────────────────────────
# ─── Enhanced headers for GitHub Actions ─────────────────────────────────
def get_enhanced_headers():
    """Get enhanced headers that work better in GitHub Actions"""
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Cache-Control": "max-age=0",
        "sec-ch-ua": '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"'
    }

HEADERS = get_enhanced_headers()
PRICE_SELECTOR  = "lowest"           # or "highest"
EXCLUDE_HINTS   = ("fee", "fees", "service", "processing")

# Playwright settings - enhanced anti-bot evasion
IS_GITHUB_ACTIONS = os.getenv("GITHUB_ACTIONS") == "true"
if IS_GITHUB_ACTIONS:
    # Ultra-conservative anti-bot evasion settings
    MAX_CONCURRENT  = 1              # Process 1 URL at a time (most human-like)
    REQUEST_DELAY   = 10.0           # 10 second delay between requests
    RETRY_ATTEMPTS  = 2              # 2 retries for reliability
else:
    MAX_CONCURRENT  = 2              # Moderate for local runs
    REQUEST_DELAY   = 3.0            # 3 second delay for local
    RETRY_ATTEMPTS  = 2              # 2 retries

BATCH_SIZE      = 10                 # changes per notification batch
DEBUG_DATE      = False              # detailed date parsing debug

@dataclass
class Change:
    """Represents a detected change in event status"""
    title: str
    old_status: str
    new_status: str
    url: str
    event_dt: Optional[str] = None

# ─── Simple HTTP session ───────────────────────────────────────────────────

# ─── Telegram credentials (set as repo Secrets) ───────────────────────────
TG_TOKEN = os.getenv("TG_TOKEN")
TG_CHAT  = os.getenv("TG_CHAT")

# ─── Helpers ──────────────────────────────────────────────────────────────
def fmt(s: Dict[str, Any]) -> str:
    if s.get("soldout"):
        return "SOLD OUT"
    if s.get("price") is not None:
        return f"${s['price']:.2f}"
    return "unknown"

def is_past(event_iso: str) -> bool:
    if not event_iso:
        return False
    event_dt = dtparse.parse(event_iso)
    return event_dt < dt.datetime.now(tz.tzutc())

# ─── Scrape one event page ────────────────────────────────────────────────
def extract_status(html: str) -> Dict[str, Any]:
    soup  = BeautifulSoup(html, "html.parser")
    text  = soup.get_text(" ", strip=True)
    
    # Debug: Log HTML length and first 500 chars in GitHub Actions
    if IS_GITHUB_ACTIONS:
        print(f"🔍 HTML length: {len(html)} chars, text length: {len(text)} chars")
        if len(text) < 1000:
            print(f"🔍 First 500 chars of text: {text[:500]}")
        else:
            print(f"🔍 Text looks normal (length: {len(text)})")

    # 1. Check for various event status indicators first -------------------
    is_cancelled = False
    is_terminated = False
    is_presale = False
    is_sold_out = False
    
    # Check for "not available" message (current Ticketweb issue)
    not_available_indicators = soup.find_all(string=re.compile(r'(the event you\'re looking for is not available|event not available|not available)', re.I))
    if not_available_indicators:
        if DEBUG_DATE:
            print("DEBUG: Event shows 'not available' - likely Angular app issue")
        # Don't mark as sold out, just return unknown status
    
    # Check for cancelled/postponed events
    cancelled_indicators = soup.find_all(string=re.compile(r'(event cancelled|event canceled|event postponed)', re.I))
    if cancelled_indicators:
        is_cancelled = True
        if DEBUG_DATE:
            print("DEBUG: Event is cancelled/postponed")
    
    # Check for terminated events (past events)
    terminated_indicators = soup.find_all(string=re.compile(r'(ticket sales terminated|tickets are currently unavailable)', re.I))
    if terminated_indicators:
        is_terminated = True
        if DEBUG_DATE:
            print("DEBUG: Event ticket sales are terminated")
    
    # Check for presale events
    presale_indicators = soup.find_all(string=re.compile(r'(on sale soon|sale starts|presale)', re.I))
    if presale_indicators:
        is_presale = True
        if DEBUG_DATE:
            print("DEBUG: Event is on presale/coming soon")
    
    # Check for sold out events (comprehensive patterns)
    soldout_indicators = soup.find_all(string=re.compile(r'(this show is currently sold out|sold out|check back soon|advance tickets sold out|not currently available|event is canceled|event is cancelled|tickets unavailable|no tickets available)', re.I))
    if soldout_indicators:
        is_sold_out = True
        if DEBUG_DATE:
            print("DEBUG: Event is sold out")

    # 2. Event date ---------------------------------------------------------
    date_str = None

    # Try structured data first (JSON-LD)
    json_scripts = soup.find_all('script', type='application/ld+json')
    for script in json_scripts:
        try:
            data = json.loads(script.string)
            if isinstance(data, dict) and data.get('@type') == 'Event':
                if data.get('startDate'):
                    date_str = data['startDate']
                    break
        except:
            pass

    # meta property="event:start_time"
    if not date_str:
        mtag = soup.find("meta", property="event:start_time")
        if mtag and mtag.get("content"):
            date_str = mtag["content"]

    # <time> tag
    if not date_str:
        ttag = soup.find("time")
        if ttag and ttag.get_text(strip=True):
            date_str = ttag.get_text(strip=True)

    # <p class="date"> (mobile)
    if not date_str:
        pdate = soup.find("p", class_="date")
        if pdate and pdate.get_text(strip=True):
            date_str = pdate.get_text(" ", strip=True)

    # Fallback regex e.g. "Sat Jun 28 2025"
    if not date_str:
        m = re.search(
            r"(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+"
            r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+"
            r"\d{1,2}\s+\d{4}", text
        )
        if m:
            date_str = m.group(0)
    
    # Additional patterns for current Ticketweb structure
    if not date_str:
        # Look for patterns like "Fri, 12 Sep, 7:30 PM EDT"
        date_patterns = [
            r"(Mon|Tue|Wed|Thu|Fri|Sat|Sun),\s+\d{1,2}\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec),\s+\d{1,2}:\d{2}\s+(AM|PM)\s+(EST|EDT|PST|PDT|CST|CDT|MST|MDT)",
            r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2}",
            r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2}",
            r"\d{1,2}/\d{1,2}/\d{4}",
            r"\d{4}-\d{2}-\d{2}"
        ]
        
        for pattern in date_patterns:
            m = re.search(pattern, text)
            if m:
                date_str = m.group(0)
                break

    event_dt = None
    if date_str:
        try:
            event_dt = dtparse.parse(date_str).astimezone(tz.tzutc())
        except (ValueError, TypeError, dtparse.ParserError) as e:
            if DEBUG_DATE:
                print("DEBUG parse fail:", e, date_str)

    # 3. Title --------------------------------------------------------------
    meta = soup.find("meta", property="og:title")
    title = (meta["content"].strip() if meta and meta.get("content")
             else soup.title.string.strip() if soup.title and soup.title.string
             else "<unknown event>")
    title = re.sub(r"\s+\|.*$", "", title)

    # 4. Price detection (updated for new Ticketweb structure) -------------
    price = None
    price_range = None
    
    # First, try to get price from structured data
    for script in json_scripts:
        try:
            data = json.loads(script.string)
            if isinstance(data, dict) and data.get('@type') == 'Event':
                offers = data.get('offers', {})
                if isinstance(offers, dict):
                    price_str = offers.get('price', '')
                    if price_str and price_str.strip():
                        try:
                            # Remove currency symbols and parse
                            price_value = float(re.sub(r'[^\d.]', '', price_str))
                            price = price_value
                            break
                        except ValueError:
                            pass
        except:
            pass
    
    # Enhanced HTML text search for prices (handles new Ticketweb patterns)
    if price is None:
        prices: List[float] = []
        
        # Look for single prices like "$25", "$40.00"
        for m in re.finditer(r"\$([0-9]{1,5}(?:\.[0-9]{2})?)", text):
            window = text[max(0, m.start() - 30): m.end() + 30].lower()
            # Be more restrictive about excluding prices
            if any(h in window for h in EXCLUDE_HINTS) or "sold out" in window or "unavailable" in window:
                continue
            prices.append(float(m.group(1)))
        
        # Look for price ranges like "$26.39 - $38.08"
        price_ranges = re.findall(r"\$([0-9]{1,5}(?:\.[0-9]{2})?)\s*-\s*\$([0-9]{1,5}(?:\.[0-9]{2})?)", text)
        if price_ranges:
            try:
                min_price = float(price_ranges[0][0])
                max_price = float(price_ranges[0][1])
                price_range = f"${min_price:.2f} - ${max_price:.2f}"
                prices.append(min_price)  # Use minimum price as the main price
            except ValueError:
                pass
        
        # Look for prices without $ symbol (e.g., "25.00", "40")
        for m in re.finditer(r"\b([0-9]{1,3}(?:\.[0-9]{2})?)\b", text):
            window = text[max(0, m.start() - 20): m.end() + 20].lower()
            # Only consider if it looks like a price (not a date, time, etc.)
            # Exclude time patterns like "7:30", "7:30 PM", "7:30 AM"
            if (("price" in window or "ticket" in window or "cost" in window) and 
                not any(h in window for h in EXCLUDE_HINTS) and
                not re.search(r'\d+:\d+', window) and  # Exclude time patterns
                not re.search(r'\d+\s*(am|pm)', window)):  # Exclude AM/PM patterns
                try:
                    price_val = float(m.group(1))
                    if 5 <= price_val <= 1000:  # Reasonable price range
                        prices.append(price_val)
                except ValueError:
                    pass
        
        if prices:
            price = (min(prices) if PRICE_SELECTOR == "lowest" else max(prices))
    
    # Determine if sold out based on all status indicators
    soldout = False
    
    # Only mark as sold out if we have EXPLICIT indicators
    if is_cancelled or is_terminated or is_presale or is_sold_out:
        soldout = True
    # Be more conservative - only mark as sold out if we find explicit "sold out" text
    elif is_sold_out or any('sold out' in text.lower() for text in soup.find_all(string=re.compile(r'sold out', re.I))):
        soldout = True
    # If we have "not available" message, don't assume sold out - just mark as unknown
    elif not_available_indicators:
        soldout = False  # Don't assume sold out for "not available" messages
    # If no price found, don't assume sold out - price might be hidden or in different format
    else:
        soldout = False  # Conservative approach - only mark sold out with explicit indicators

    if DEBUG_DATE:
        print("DEBUG:", title, "Price:", price, "Price Range:", price_range, "Sold out:", soldout, 
              "Cancelled:", is_cancelled, "Terminated:", is_terminated, "Presale:", is_presale, "Sold Out Banner:", is_sold_out)

    result = {
        "title": title,
        "price": price,
        "price_range": price_range,
        "soldout": soldout,
        "cancelled": is_cancelled,
        "terminated": is_terminated,
        "presale": is_presale,
        "sold_out_banner": is_sold_out,
        "event_dt": event_dt.isoformat() if event_dt else None,
    }
    
    # Debug: Log extraction result in GitHub Actions
    if IS_GITHUB_ACTIONS:
        print(f"🔍 Extraction result: {result}")
    
    return result

# ─── Notification wrappers ────────────────────────────────────────────────
def mac_banner(title: str, message: str, url: str):
    try:
        run(["terminal-notifier", "-title", title, "-message", message, "-open", url],
            stdout=DEVNULL, stderr=DEVNULL, check=False)
    except FileNotFoundError:
        pass

def get_status_emoji(old_status: str, new_status: str) -> str:
    """Get appropriate emoji based on status change"""
    if "SOLD OUT" in new_status:
        return "🚫"  # Sold out
    elif "unknown" in old_status:
        return "🆕"  # New price discovered
    elif old_status != new_status:
        try:
            old_price = float(old_status.replace("$", "")) if "$" in old_status else 0
            new_price = float(new_status.replace("$", "")) if "$" in new_status else 0
            if new_price > old_price:
                return "📈"  # Price increase
            else:
                return "📉"  # Price decrease
        except:
            return "🔄"  # General change
    return "🎟️"

def get_urgency_emoji(event_dt: str) -> str:
    """Get urgency emoji based on how soon the event is"""
    if not event_dt:
        return "📅"
    try:
        event_date = dtparse.parse(event_dt)
        days_until = (event_date - dt.datetime.now(tz.tzutc())).days
        if days_until <= 7:
            return "🔥"  # Very urgent (this week)
        elif days_until <= 30:
            return "⚡"  # Urgent (this month)
        elif days_until <= 90:
            return "⏰"  # Soon (next 3 months)
        else:
            return "📅"  # Future
    except:
        return "📅"

def telegram_push(title: str, message: str, url: str = None):
    if not (TG_TOKEN and TG_CHAT):
        print(f"⚠️ Telegram credentials missing: TG_TOKEN={'✓' if TG_TOKEN else '✗'}, TG_CHAT={'✓' if TG_CHAT else '✗'}")
        return
    api = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    
    # Enhanced formatting with better emojis
    if url:
        msg = f"🎫 <b>{title}</b>\n\n{message}\n\n🔗 <a href='{url}'>View Event</a>"
    else:
        msg = f"🎫 <b>{title}</b>\n\n{message}"
    
    try:
        print(f"📱 Sending Telegram notification: {title}")
        response = requests.post(api,
                      data={"chat_id": TG_CHAT, "text": msg,
                            "parse_mode": "HTML", "disable_web_page_preview": True},
                      timeout=10)
        print(f"✅ Telegram sent successfully: {response.status_code}")
    except (requests.RequestException, requests.Timeout) as e:
        print("✖ Telegram error:", e)

def send_sold_out_reminders(sold_out_events):
    """Send hourly reminders for sold-out events with clickable links"""
    if not (TG_TOKEN and TG_CHAT) or not sold_out_events:
        return
    
    # Sort all events by date (earliest first)
    sorted_events = sorted(sold_out_events, key=lambda x: x["event_dt"] or "9999")
    
    # Create simple sold-out reminder
    reminder_msg = f"""🔴 <b>{len(sold_out_events)} events sold out:</b>

"""
    
    # Show all sold-out events in date order
    for i, event in enumerate(sorted_events[:15], 1):  # Show up to 15 events
        title = event['title'].replace("Tickets for ", "").strip()
        if len(title) > 45:
            title = title[:42] + "..."
        
        date_str = "TBD"
        if event["event_dt"]:
            try:
                dt_obj = dtparse.parse(event["event_dt"])
                date_str = dt_obj.strftime("%a, %b %d")
            except:
                pass
        
        reminder_msg += f" {i:2}. 🚫 <b>{title}</b>\n"
        reminder_msg += f"    📅 {date_str}\n"
        reminder_msg += f"    🔗 <a href='{event['url']}'>Check Availability</a>\n\n"
    
    # Show remaining count if there are more
    if len(sorted_events) > 15:
        reminder_msg += f"    ... and {len(sorted_events) - 15} more sold-out events\n\n"
    
    # No extra footer text needed
    
    # Send reminder
    telegram_push("🚫 Sold Out Reminder", reminder_msg)

def telegram_batch_changes(changes: List[Change]):
    """Send beautifully formatted batch change notifications"""
    if not (TG_TOKEN and TG_CHAT) or not changes:
        return
    
    # Group changes by urgency and type
    urgent_sold_out = []    # This week sold out
    urgent_changes = []     # This week price changes
    soon_sold_out = []      # This month sold out
    soon_changes = []       # This month price changes
    future_sold_out = []    # Future sold out
    future_changes = []     # Future price changes
    
    for change in changes:
        is_sold_out = "SOLD OUT" in change.new_status
        urgency = get_urgency_emoji(change.event_dt)
        
        if urgency == "🔥":  # This week
            if is_sold_out:
                urgent_sold_out.append(change)
            else:
                urgent_changes.append(change)
        elif urgency == "⚡":  # This month
            if is_sold_out:
                soon_sold_out.append(change)
            else:
                soon_changes.append(change)
        else:  # Future
            if is_sold_out:
                future_sold_out.append(change)
            else:
                future_changes.append(change)
    
    # Send notifications in priority order
    notification_groups = [
        ("🔥 URGENT SOLD OUT (This Week)", urgent_sold_out, "🚫"),
        ("🔥 URGENT PRICE CHANGES (This Week)", urgent_changes, "📊"),
        ("⚡ SOLD OUT (This Month)", soon_sold_out, "🚫"),
        ("⚡ PRICE CHANGES (This Month)", soon_changes, "📊"),
        ("📅 FUTURE SOLD OUT", future_sold_out, "🚫"),
        ("📅 FUTURE PRICE CHANGES", future_changes, "📊")
    ]
    
    for group_title, group_changes, group_emoji in notification_groups:
        if not group_changes:
            continue
            
        # Sort by date within each group
        group_changes.sort(key=lambda x: x.event_dt or "9999")
        
        for i in range(0, len(group_changes), BATCH_SIZE):
            batch = group_changes[i:i + BATCH_SIZE]
            
            # Create simple header
            header = f"{group_emoji} <b>{group_title}</b>\n"
            header += f"📊 {len(batch)} events found\n\n"
            
            msg_lines = [header]
            
            for j, change in enumerate(batch, 1):
                # Get status and urgency emojis
                status_emoji = get_status_emoji(change.old_status, change.new_status)
                urgency_emoji = get_urgency_emoji(change.event_dt)
                
                # Format date nicely
                date_str = "TBD"
                if change.event_dt:
                    try:
                        dt_obj = dtparse.parse(change.event_dt)
                        date_str = dt_obj.strftime("%b %d, %Y")
                        # Add day of week for near events
                        if urgency_emoji in ["🔥", "⚡"]:
                            day_of_week = dt_obj.strftime("%a")
                            date_str = f"{day_of_week}, {date_str}"
                    except:
                        pass
                
                # Clean up event title
                title = change.title.replace("Tickets for ", "").strip()
                if len(title) > 45:
                    title = title[:42] + "..."
                
                # Format the change beautifully
                msg_lines.append(f"{j:2}. {status_emoji} <b>{title}</b>")
                msg_lines.append(f"    {urgency_emoji} {date_str}")
                msg_lines.append(f"    💰 {change.old_status} → <b>{change.new_status}</b>")
                msg_lines.append(f"    🔗 <a href='{change.url}'>View Event</a>")
                msg_lines.append("")
            
            # No footer needed
            
            msg = "\n".join(msg_lines)
            
            # Send with appropriate title
            if "URGENT" in group_title:
                title = f"🚨 URGENT ALERT"
            elif "This Month" in group_title:
                title = f"⚡ Monthly Alert"
            else:
                title = f"📅 Future Alert"
            
            telegram_push(title, msg)

def notify(title: str, message: str, url: str):
    mac_banner(title, message, url)
    telegram_push(title, message, url)

# ─── File helpers ─────────────────────────────────────────────────────────
def load_lines(path: str) -> list[str]:
    if not os.path.exists(path):
        sys.exit(f"✖ {path} missing – add some Ticketweb URLs first.")
    with open(path) as f:
        urls = []
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                # Extract URL part before any comment
                url = line.split('#')[0].strip()
                if url:
                    urls.append(url)
        return urls

def load_failed_urls() -> set:
    """Load URLs that failed in previous runs"""
    try:
        if os.path.exists(FAILED_URLS_FILE):
            with open(FAILED_URLS_FILE) as f:
                failed_data = json.load(f)
                return set(failed_data.get("failed_urls", []))
    except:
        pass
    return set()

def save_failed_urls(failed_urls: set):
    """Save URLs that failed this run for priority next time"""
    try:
        failed_data = {
            "failed_urls": list(failed_urls),
            "timestamp": dt.datetime.now().isoformat(),
            "count": len(failed_urls)
        }
        with open(FAILED_URLS_FILE, "w") as f:
            json.dump(failed_data, f, indent=2)
    except Exception as e:
        print(f"⚠️ Could not save failed URLs: {e}")

def select_urls_with_priority(all_urls: list[str], target_count: int = 250) -> list[str]:
    """Select URLs with priority for previously failed ones"""
    # Load previously failed URLs
    failed_urls = load_failed_urls()
    
    # Separate failed and successful URLs
    priority_urls = [url for url in all_urls if url in failed_urls]
    other_urls = [url for url in all_urls if url not in failed_urls]
    
    # Always include all failed URLs (they get priority)
    selected_urls = priority_urls[:]
    
    # Fill remaining slots with random selection from other URLs
    remaining_slots = target_count - len(priority_urls)
    if remaining_slots > 0 and other_urls:
        # Shuffle other URLs for random selection
        random.shuffle(other_urls)
        selected_urls.extend(other_urls[:remaining_slots])
    
    # If we have fewer URLs than target, just return all
    if len(selected_urls) < target_count and len(all_urls) < target_count:
        selected_urls = all_urls[:]
    
    print(f"📊 URL Selection Strategy:")
    print(f"   🔴 Priority (failed): {len(priority_urls)} URLs")
    print(f"   🔀 Random selection: {min(remaining_slots, len(other_urls))} URLs") 
    print(f"   🎯 Total selected: {len(selected_urls)}/{len(all_urls)} URLs")
    
    return selected_urls

def load_state(path: str):
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {}

def save_state(path: str, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)

def sort_urls_by_date(urls: List[str], event_data: Dict[str, Dict[str, Any]]) -> Tuple[List[str], List[str]]:
    """Sort URLs by event date, return (sorted_urls, urls_without_dates)"""
    urls_with_dates = []
    urls_without_dates = []
    
    for url in urls:
        event_info = event_data.get(url)
        if event_info and event_info.get("event_dt"):
            urls_with_dates.append((url, event_info["event_dt"]))
        else:
            urls_without_dates.append(url)
    
    # Sort by date (earliest first)
    urls_with_dates.sort(key=lambda x: x[1])
    sorted_urls = [url for url, _ in urls_with_dates]
    
    return sorted_urls + urls_without_dates, urls_without_dates

def save_sorted_urls(path: str, urls: List[str], event_data: Dict[str, Dict[str, Any]]):
    """Save URLs sorted by event date with date comments"""
    sorted_urls, urls_without_dates = sort_urls_by_date(urls, event_data)
    
    with open(path, "w") as f:
        f.write("# Ticketwatch URLs - Automatically sorted by event date\n")
        f.write("# Format: URL  # Event Name - Date\n\n")
        
        current_month = None
        for url in sorted_urls:
            event_info = event_data.get(url, {})
            title = event_info.get("title", "Unknown Event")
            
            if event_info.get("event_dt"):
                try:
                    event_dt = dtparse.parse(event_info["event_dt"])
                    month_year = event_dt.strftime("%B %Y")
                    date_str = event_dt.strftime("%b %d")
                    
                    # Add month headers
                    if current_month != month_year:
                        if current_month is not None:
                            f.write("\n")
                        f.write(f"# === {month_year} ===\n")
                        current_month = month_year
                    
                    f.write(f"{url}  # {title} - {date_str}\n")
                except:
                    f.write(f"{url}  # {title} - Date parsing error\n")
            else:
                if current_month is not None:
                    f.write("\n# === Events without dates ===\n")
                    current_month = None
                f.write(f"{url}  # {title} - No date found\n")
    
    print(f"📅 Saved {len(sorted_urls)} URLs sorted by date")
    if urls_without_dates:
        print(f"⚠️  {len(urls_without_dates)} URLs missing event dates")

# ─── Async fetching with rate limiting ───────────────────────────────────
async def fetch_url_with_playwright(url: str, semaphore: asyncio.Semaphore) -> Tuple[str, Optional[Dict[str, Any]]]:
    """Fetch a single URL using Playwright with retry logic and rate limiting"""
    # Strip comments from URL (URLs in batch files may have comments after #)
    clean_url = url.split('#')[0].strip()
    
    async with semaphore:
        # Add delay between requests
        if REQUEST_DELAY > 0:
            await asyncio.sleep(REQUEST_DELAY)
            
        for attempt in range(RETRY_ATTEMPTS):
            try:
                # Add randomized delay to look more human-like
                if IS_GITHUB_ACTIONS:
                    base_delay = REQUEST_DELAY
                    randomized_delay = base_delay + random.uniform(0, base_delay * 0.5)  # Add 0-50% random variation
                    await asyncio.sleep(randomized_delay)
                
                async with async_playwright() as p:
                    # Enhanced anti-bot evasion browser settings
                    browser = await p.chromium.launch(
                        headless=True,
                        args=[
                            '--no-sandbox',
                            '--disable-dev-shm-usage',
                            '--disable-blink-features=AutomationControlled',
                            '--disable-features=VizDisplayCompositor',
                            '--disable-web-security',
                            '--disable-features=TranslateUI',
                            '--disable-ipc-flooding-protection',
                            '--disable-renderer-backgrounding',
                            '--disable-backgrounding-occluded-windows',
                            '--disable-client-side-phishing-detection',
                            '--disable-sync',
                            '--disable-default-apps',
                            '--disable-extensions',
                            '--no-first-run',
                            '--no-default-browser-check',
                            '--disable-background-timer-throttling',
                            '--disable-backgrounding-occluded-windows',
                            '--disable-renderer-backgrounding'
                        ]
                    )
                    
                    # Rotate user agents for better evasion
                    user_agents = [
                        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
                        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                        'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0',
                        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15'
                    ]
                    selected_user_agent = random.choice(user_agents)
                    
                    # Create context with enhanced realistic settings
                    context = await browser.new_context(
                        viewport={'width': 1366, 'height': 768},  # More common resolution
                        user_agent=selected_user_agent,
                        locale='en-US',
                        timezone_id='America/New_York',
                        # Add more realistic browser features
                        java_script_enabled=True,
                        accept_downloads=False,
                        has_touch=False,
                        is_mobile=False,
                        device_scale_factor=1,
                        # Add extra headers
                        extra_http_headers={
                            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
                            'Accept-Language': 'en-US,en;q=0.9',
                            'Accept-Encoding': 'gzip, deflate, br',
                            'DNT': '1',
                            'Connection': 'keep-alive',
                            'Upgrade-Insecure-Requests': '1',
                            'Sec-Fetch-Dest': 'document',
                            'Sec-Fetch-Mode': 'navigate',
                            'Sec-Fetch-Site': 'none',
                            'Cache-Control': 'max-age=0'
                        }
                    )
                    
                    # Create page
                    page = await context.new_page()
                    
                    # Navigate to URL and wait for network to be idle
                    await page.goto(clean_url, timeout=30000, wait_until='networkidle')
                    
                    # Add human-like behavior patterns
                    if IS_GITHUB_ACTIONS:
                        # Random mouse movement
                        await page.mouse.move(random.randint(100, 800), random.randint(100, 600))
                        await page.wait_for_timeout(random.randint(500, 1500))
                        
                        # Random scroll behavior
                        await page.evaluate(f"window.scrollTo(0, {random.randint(100, 500)})")
                        await page.wait_for_timeout(random.randint(800, 2000))
                        
                        # Random click (not on anything important)
                        await page.mouse.click(random.randint(50, 200), random.randint(50, 200))
                        await page.wait_for_timeout(random.randint(300, 800))
                    
                    # Wait for Angular app to load and render content
                    # Try multiple approaches to ensure content is loaded
                    
                    # Approach 1: Wait for any dynamic content to appear
                    try:
                        await page.wait_for_function(
                            "document.querySelector('.event-details, .ticket-info, .price-info, .event-info, .event-title, .event-date') !== null",
                            timeout=15000
                        )
                    except:
                        pass
                    
                    # Approach 2: Wait for the "not available" message to disappear
                    try:
                        await page.wait_for_function(
                            "!document.querySelector('p.message-sub') || !document.querySelector('p.message-sub').textContent.includes('not available')",
                            timeout=15000
                        )
                    except:
                        pass
                    
                    # Approach 3: Wait for any text content to change from initial state
                    try:
                        await page.wait_for_function(
                            "document.body.textContent.length > 1000 && !document.body.textContent.includes('The event you')",
                            timeout=15000
                        )
                    except:
                        pass
                    
                    # Final fallback: wait a bit more with human-like timing
                    await page.wait_for_timeout(random.randint(3000, 7000))
                    
                    # Additional human-like delay
                    await page.wait_for_timeout(random.randint(1000, 3000))
                    
                    # Get page content
                    html = await page.content()
                    
                    # Extract data before closing browser
                    event_data = extract_status(html)
                    
                    # Close browser
                    await browser.close()
                    
                    return clean_url, event_data
                    
            except Exception as e:
                if attempt == RETRY_ATTEMPTS - 1:
                    print(f"✖ {url}: Failed after {RETRY_ATTEMPTS} attempts (playwright: {e})")
                    return url, None
                await asyncio.sleep(2 ** attempt)  # Exponential backoff
                
    return url, None

async def fetch_all_urls(urls: List[str]) -> Dict[str, Dict[str, Any]]:
    """Fetch all URLs concurrently with progress reporting"""
    semaphore = asyncio.Semaphore(MAX_CONCURRENT)
    results = {}
    completed = 0
    
    print(f"🔄 Starting to check {len(urls)} URLs with Playwright...")
    start_time = time.time()
    
    # Create tasks for all URLs using Playwright
    tasks = [fetch_url_with_playwright(url, semaphore) for url in urls]
    
    # Process completed tasks
    for coro in asyncio.as_completed(tasks):
        url, status = await coro
        completed += 1
        
        if status:
            results[url] = status
        
        # Progress reporting (more frequent for GitHub Actions)
        report_interval = 10 if IS_GITHUB_ACTIONS else 20
        if completed % report_interval == 0 or completed == len(urls):
            elapsed = time.time() - start_time
            rate = completed / elapsed if elapsed > 0 else 0
            success_rate = len(results) / completed * 100 if completed > 0 else 0
            print(f"📊 Progress: {completed}/{len(urls)} ({completed/len(urls)*100:.1f}%) "
                  f"- {rate:.1f} URLs/sec - {success_rate:.1f}% success")
    
    elapsed = time.time() - start_time
    failed_count = len(urls) - len(results)
    success_rate = len(results) / len(urls) * 100 if len(urls) > 0 else 0
    
    print(f"✅ Completed in {elapsed:.1f}s - {len(results)} successful, {failed_count} failed")
    print(f"📊 Success rate: {success_rate:.1f}% ({len(results)}/{len(urls)})")
    
    if failed_count > 0:
        print(f"⚠️  {failed_count} URLs failed to fetch - this may indicate anti-bot protection")
        if IS_GITHUB_ACTIONS:
            print("🔧 GitHub Actions: Using Playwright for better anti-bot evasion")
    
    return results

# ─── Main processing logic ────────────────────────────────────────────────
async def main():
    """Main async processing function"""
    print("🎟️ Ticketwatch starting...")
    
    # Load all URLs from file
    all_urls = load_lines(URL_FILE)
    
    # For batch system: scan ALL URLs in the batch file
    # For consolidated system: use smart selection
    if len(sys.argv) > 1 and sys.argv[1]:
        # Running with batch file - scan ALL URLs in this batch
        selected_urls = all_urls
        print(f"🎯 Batch mode: Scanning ALL {len(selected_urls)} URLs")
    else:
        # Running with consolidated urls.txt - use smart selection
        # Process all URLs in GitHub Actions, or up to 280 locally
        target_count = len(all_urls) if IS_GITHUB_ACTIONS else min(280, len(all_urls))
        try:
            selected_urls = select_urls_with_priority(all_urls, target_count)
            print(f"🎯 Consolidated mode: Selected {len(selected_urls)}/{len(all_urls)} URLs")
        except Exception as e:
            print(f"❌ URL selection failed: {e}, using all URLs")
            selected_urls = all_urls[:target_count]
    
    before = load_state(STATE_FILE)
    
    # Fetch selected URLs concurrently  
    after = await fetch_all_urls(selected_urls)
    
    # Process results
    past_events = []  # Store past events for notification (but don't remove)
    changes = []
    
    for url, now in after.items():
        # Skip failed fetches
        if not now:
            continue
            
        # Identify past shows (but don't remove them)
        if is_past(now["event_dt"]):
            past_events.append({
                "url": url,
                "title": now["title"],
                "event_dt": now["event_dt"]
            })
            # Continue processing (don't skip past events)
        
        # Check for changes
        old = before.get(url, {"price": None, "soldout": None})
        if now != old:
            change = Change(
                title=now["title"],
                old_status=fmt(old),
                new_status=fmt(now),
                url=url,
                event_dt=now.get("event_dt")
            )
            changes.append(change)
        else:
            # Debug: show why no change was detected
            if IS_GITHUB_ACTIONS and len(changes) < 5:  # Only show first few for debugging
                print(f"🔍 No change for {now['title'][:30]}... - old: {fmt(old)}, new: {fmt(now)}")
    
    # Track failed URLs for priority next time
    successful_urls = set(after.keys())
    failed_urls = set(selected_urls) - successful_urls
    save_failed_urls(failed_urls)
    
    if failed_urls:
        print(f"🔴 {len(failed_urls)} URLs failed - will get priority next run")
    else:
        print("🟢 All selected URLs succeeded!")
    
    # Only re-sort URLs if we successfully fetched REAL data (not "Unknown Event")
    if after and len(after) > 0:
        # Check if we have any real event data (not just "Unknown Event" entries)
        real_events = [url for url, data in after.items() 
                      if data and data.get("title") and not data.get("title").startswith("Unknown Event")]
        
        if real_events:
            save_sorted_urls(URL_FILE, all_urls, after)
            print("✅ URLs re-sorted by date")
        else:
            print("⚠️ Skipping URL re-sort - no real event data found (all Unknown Events)")
    else:
        print("⚠️ Skipping URL re-sort due to fetch failure")
    
    # Send beautiful past events notification
    if past_events:
        print(f"\n⚠️  Found {len(past_events)} past events (manual cleanup suggested):")
        
        # Sort past events by how long ago they were
        sorted_past_events = sorted(past_events, key=lambda x: x["event_dt"] or "")
        
        cleanup_msg = f"""⚠️ Found <b>{len(past_events)} past events</b> that could be removed

🗓️ <b>Past Events:</b>"""
        
        for i, event in enumerate(sorted_past_events[:8], 1):  # Show up to 8
            date_str = "No date"
            days_ago = ""
            if event["event_dt"]:
                try:
                    dt_obj = dtparse.parse(event["event_dt"])
                    date_str = dt_obj.strftime("%b %d, %Y")
                    days_passed = (dt.datetime.now(tz.tzutc()) - dt_obj).days
                    if days_passed > 0:
                        days_ago = f" ({days_passed} days ago)"
                except:
                    pass
            
            title = event['title'].replace("Tickets for ", "").strip()
            if len(title) > 35:
                title = title[:32] + "..."
            
            print(f"  • {title} ({date_str})")
            cleanup_msg += f"\n {i:2}. 📅 <b>{title}</b>"
            cleanup_msg += f"\n     🕐 {date_str}{days_ago}"
        
        if len(past_events) > 8:
            cleanup_msg += f"\n    ... and {len(past_events) - 8} more events"
        
        cleanup_msg += f"""

🛠️ <b>Manual Cleanup Required:</b>
<code>python3 batch_manager.py clean --review</code>"""
        
        # Send past events notification 
        if TG_TOKEN and TG_CHAT and len(past_events) > 0:
            telegram_push("🧹 Cleanup Suggestion", cleanup_msg)
    
    # Save state
    save_state(STATE_FILE, after)
    
    # In GitHub Actions, commit the state file so it persists between runs
    if IS_GITHUB_ACTIONS:
        try:
            import subprocess
            # Configure git user
            subprocess.run(["git", "config", "user.email", "bot@github-actions.com"], check=True, capture_output=True)
            subprocess.run(["git", "config", "user.name", "GitHub Actions Bot"], check=True, capture_output=True)
            
            # Add and commit state file
            result = subprocess.run(["git", "add", STATE_FILE], capture_output=True, text=True)
            if result.returncode != 0:
                print(f"⚠️ Git add failed: {result.stderr}")
                return
            
            result = subprocess.run(["git", "commit", "-m", f"Update state file - {len(after)} events monitored"], capture_output=True, text=True)
            if result.returncode != 0:
                print(f"⚠️ Git commit failed: {result.stderr}")
                return
                
            result = subprocess.run(["git", "push", "origin", "main"], capture_output=True, text=True)
            if result.returncode != 0:
                print(f"⚠️ Git push failed: {result.stderr}")
                return
                
            print("✅ State file committed to repository")
        except Exception as e:
            print(f"⚠️ Error committing state file: {e}")
    
    # Save batch stats for aggregation
    batch_stats = {
        "monitored_count": len(after),
        "sold_out_events": []
    }
    
    # Collect sold-out events from current batch
    for url, event_data in after.items():
        if event_data.get("soldout"):
            batch_stats["sold_out_events"].append({
                "url": url,
                "title": event_data.get("title", "Unknown Event"),
                "event_dt": event_data.get("event_dt")
            })
    
    # Save stats to shared file for primary batch to aggregate
    if len(sys.argv) > 1 and sys.argv[1]:
        # For batch files, save in url_batches directory
        stats_file = f"{URL_FILE}.stats.json"
    else:
        # For consolidated urls.txt, save in root
        stats_file = "batch_stats.json"
    
    print(f"📊 Saving stats to: {stats_file}")
    with open(stats_file, "w") as f:
        json.dump(batch_stats, f, indent=2)
    print(f"✅ Stats saved: {batch_stats['monitored_count']} monitored, {len(batch_stats['sold_out_events'])} sold out")
    
    print(f"🔴 Found {len(batch_stats['sold_out_events'])} sold-out events in this batch")
    
    # Aggregate all batch stats (only for primary batch)
    is_primary = os.getenv("PRIMARY", "false").lower() == "true"
    if is_primary:
        # Collect stats from all batches
        total_monitored = 0
        all_sold_out_events = []
        
        # Check all possible batch stats files
        for batch_num in range(1, 6):  # batch1.txt to batch5.txt
            batch_stats_path = f"url_batches/batch{batch_num}.txt.stats.json"
            print(f"🔍 Checking: {batch_stats_path}")
            try:
                if os.path.exists(batch_stats_path):
                    with open(batch_stats_path, 'r') as f:
                        batch_data = json.load(f)
                        total_monitored += batch_data.get("monitored_count", 0)
                        all_sold_out_events.extend(batch_data.get("sold_out_events", []))
                        print(f"📊 Batch {batch_num}: {batch_data.get('monitored_count', 0)} monitored, {len(batch_data.get('sold_out_events', []))} sold out")
                else:
                    print(f"❌ File not found: {batch_stats_path}")
            except (FileNotFoundError, json.JSONDecodeError) as e:
                print(f"❌ Error reading {batch_stats_path}: {e}")
                # Batch file doesn't exist or is invalid, skip
                pass
        
        print(f"🎯 TOTAL AGGREGATED: {total_monitored} monitored, {len(all_sold_out_events)} sold out")
        sold_out_events = all_sold_out_events
        monitored_count = total_monitored
    else:
        # Non-primary batches use their own counts
        sold_out_events = batch_stats["sold_out_events"] 
        monitored_count = len(after)
    
    # Handle notifications
    if changes:
        # Sort by event date (soonest first)
        changes.sort(key=lambda c: c.event_dt or "9999")
        
        print(f"\n🚨 {len(changes)} changes detected!")
        for change in changes:
            print(f"  • {change.title}: {change.old_status} → {change.new_status}")
        
        # Send batched notifications
        telegram_batch_changes(changes)
    else:
        print(f"\n✅ No changes detected")
        print(f"📊 Monitored {len(after)} events")
        print(f"🔍 Debug: before={len(before)} entries, after={len(after)} entries")
        
        # Show sample of current data
        if after:
            sample_url = list(after.keys())[0]
            sample_data = after[sample_url]
            print(f"📋 Sample data: {sample_data}")
            print(f"📋 Sample formatted: {fmt(sample_data)}")
        
    # Always send sold-out reminders (every hour) regardless of changes
    if sold_out_events and is_primary:
        send_sold_out_reminders(sold_out_events)
        
    # Send health check notification only if no changes AND no sold-out reminders
    if not changes and is_primary:
        # Send health check notification
        print("✅ No changes detected")
        print(f"📊 Monitored {monitored_count} events, {len(sold_out_events)} sold out")
        current_time = dt.datetime.now().strftime('%H:%M %Z')
        health_msg = f"""✅ No price changes detected
📊 Monitored {monitored_count} events
🔴 Currently sold out: {len(sold_out_events)} events"""
        print("📱 Attempting to send health check notification...")
        telegram_push("🟢 Health Check", health_msg)

def run_main():
    """Wrapper to run async main function"""
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n⏹️ Stopped by user")
    except Exception as e:
        print(f"💥 Error: {e}")
        telegram_push("Ticketwatch Error", f"💥 System error: {e}")
        raise

# ──────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    run_main()