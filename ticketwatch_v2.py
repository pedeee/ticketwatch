#!/usr/bin/env python3
"""
ticketwatch.py — High-performance monitor for Ticketweb event pages.

Features
────────
• Concurrent processing (handles 400-500 URLs efficiently)
• Intelligent rate limiting to avoid IP blocks
• Batched notifications (summarizes changes, reduces spam)
• Single health check when no changes occur
• Robust error handling with retries
• Progress reporting and execution metrics
• Cloudflare-aware fallback when needed

Configuration
─────────────
PRICE_SELECTOR = "lowest" | "highest"
MAX_CONCURRENT = 20        # concurrent requests
REQUEST_DELAY  = 0.1       # seconds between requests
BATCH_SIZE     = 10        # changes per notification batch
DEBUG_DATE     = False     # detailed date parsing debug
"""

import json, os, re, sys, requests, cloudscraper
import asyncio, aiohttp, time, ssl
from typing import Dict, Any, List, Tuple, Optional
from bs4 import BeautifulSoup
from subprocess import run, DEVNULL
from dateutil import parser as dtparse, tz
import datetime as dt
from dataclasses import dataclass

# ─── Files & constants ────────────────────────────────────────────────────
URL_FILE   = "urls.txt"        # default when you run locally
STATE_FILE = "state.json"

# If the workflow passes a batch file (url_batches/batchN.txt),
# use that for both URLs and state so each job is isolated.
if len(sys.argv) > 1 and sys.argv[1]:
    URL_FILE   = sys.argv[1]
    STATE_FILE = f"{URL_FILE}.state.json"   # e.g. url_batches/batch3.txt.state.json

# ─── Configuration ────────────────────────────────────────────────────────
HEADERS         = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
PRICE_SELECTOR  = "lowest"           # or "highest"
EXCLUDE_HINTS   = ("fee", "fees", "service", "processing")
MAX_CONCURRENT  = 20                 # concurrent requests
REQUEST_DELAY   = 0.1                # seconds between requests  
BATCH_SIZE      = 10                 # changes per notification batch
RETRY_ATTEMPTS  = 3                  # retry failed requests
DEBUG_DATE      = False              # detailed date parsing debug

@dataclass
class Change:
    """Represents a detected change in event status"""
    title: str
    old_status: str
    new_status: str
    url: str
    event_dt: Optional[str] = None

# ─── Cloudflare-bypass session (fallback only) ───────────────────────────
scraper = cloudscraper.create_scraper(
    browser={'browser': 'firefox', 'platform': 'darwin', 'mobile': False},
    delay=3000                       # ms between CF challenge retries
)

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

    # 1. Event date ---------------------------------------------------------
    date_str = None

    # meta property="event:start_time"
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

    event_dt = None
    if date_str:
        try:
            event_dt = dtparse.parse(date_str).astimezone(tz.tzutc())
        except Exception as e:
            if DEBUG_DATE:
                print("DEBUG parse fail:", e, date_str)

    # 2. Title --------------------------------------------------------------
    meta = soup.find("meta", property="og:title")
    title = (meta["content"].strip() if meta and meta.get("content")
             else soup.title.string.strip() if soup.title and soup.title.string
             else "<unknown event>")
    title = re.sub(r"\s+\|.*$", "", title)

    # 3. Price search (skip fee lines) --------------------------------------
    prices: list[float] = []
    for m in re.finditer(r"\$([0-9]{1,5}\.[0-9]{2})", text):
        window = text[max(0, m.start() - 20): m.end() + 20].lower()
        if any(h in window for h in EXCLUDE_HINTS) or "sold out" in window:
            continue
        prices.append(float(m.group(1)))

    price   = (min(prices) if PRICE_SELECTOR == "lowest" else max(prices)) if prices else None
    soldout = not prices

    if DEBUG_DATE:
        print("DEBUG date:", title, event_dt)

    return {
        "title": title,
        "price": price,
        "soldout": soldout,
        "event_dt": event_dt.isoformat() if event_dt else None,
    }

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
        return
    api = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    
    # Enhanced formatting with better emojis
    if url:
        msg = f"🎫 <b>{title}</b>\n\n{message}\n\n🔗 <a href='{url}'>View Event</a>"
    else:
        msg = f"🎫 <b>{title}</b>\n\n{message}"
    
    try:
        requests.post(api,
                      data={"chat_id": TG_CHAT, "text": msg,
                            "parse_mode": "HTML", "disable_web_page_preview": True},
                      timeout=10)
    except Exception as e:
        print("✖ Telegram error:", e)

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
            
            # Create beautiful header
            header = f"{group_emoji} <b>{group_title}</b>\n"
            header += f"{'═' * 30}\n"
            header += f"📊 <i>{len(batch)} events found</i>\n\n"
            
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
                msg_lines.append("")
            
            # Add footer
            msg_lines.append("─" * 25)
            msg_lines.append("🎫 <i>Ticketwatch Alert System</i>")
            
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
async def fetch_url_with_retry(session: aiohttp.ClientSession, url: str, semaphore: asyncio.Semaphore) -> Tuple[str, Optional[Dict[str, Any]]]:
    """Fetch a single URL with retry logic and rate limiting"""
    async with semaphore:  # Limit concurrent requests
        for attempt in range(RETRY_ATTEMPTS):
            try:
                await asyncio.sleep(REQUEST_DELAY)  # Rate limiting
                async with session.get(url, headers=HEADERS, timeout=30) as response:
                    response.raise_for_status()
                    html = await response.text()
                    return url, extract_status(html)
            except Exception as e:
                if attempt == RETRY_ATTEMPTS - 1:
                    # Try cloudscraper as fallback for the final attempt
                    try:
                        scraper = cloudscraper.create_scraper(
                            browser={'browser': 'firefox', 'platform': 'darwin', 'mobile': False},
                            delay=3000
                        )
                        response = scraper.get(url, timeout=30)
                        response.raise_for_status()
                        return url, extract_status(response.text)
                    except Exception as cloudscraper_e:
                        print(f"✖ {url}: Failed after {RETRY_ATTEMPTS} attempts (aiohttp: {e}, cloudscraper: {cloudscraper_e})")
                        return url, None
                await asyncio.sleep(2 ** attempt)  # Exponential backoff
    return url, None

async def fetch_all_urls(urls: List[str]) -> Dict[str, Dict[str, Any]]:
    """Fetch all URLs concurrently with progress reporting"""
    semaphore = asyncio.Semaphore(MAX_CONCURRENT)
    results = {}
    completed = 0
    
    print(f"🔄 Starting to check {len(urls)} URLs...")
    start_time = time.time()
    
    # Create SSL context that handles certificate verification issues
    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE
    
    connector = aiohttp.TCPConnector(ssl=ssl_context)
    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = [fetch_url_with_retry(session, url, semaphore) for url in urls]
        
        for coro in asyncio.as_completed(tasks):
            url, status = await coro
            completed += 1
            
            if status:
                results[url] = status
            
            # Progress reporting
            if completed % 50 == 0 or completed == len(urls):
                elapsed = time.time() - start_time
                rate = completed / elapsed if elapsed > 0 else 0
                print(f"📊 Progress: {completed}/{len(urls)} ({completed/len(urls)*100:.1f}%) "
                      f"- {rate:.1f} URLs/sec")
    
    elapsed = time.time() - start_time
    print(f"✅ Completed in {elapsed:.1f}s - {len(results)} successful, {len(urls) - len(results)} failed")
    return results

# ─── Main processing logic ────────────────────────────────────────────────
async def main():
    """Main async processing function"""
    print("🎟️ Ticketwatch starting...")
    
    urls = load_lines(URL_FILE)
    before = load_state(STATE_FILE)
    
    # Fetch all URLs concurrently  
    after = await fetch_all_urls(urls)
    
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
    
    # Always re-sort URLs by date for better organization
    save_sorted_urls(URL_FILE, urls, after)
    
    # Send beautiful past events notification
    if past_events:
        print(f"\n⚠️  Found {len(past_events)} past events (manual cleanup suggested):")
        
        # Sort past events by how long ago they were
        sorted_past_events = sorted(past_events, key=lambda x: x["event_dt"] or "")
        
        cleanup_msg = f"""🧹 <b>Cleanup Suggestion</b>
═══════════════════════════

⚠️ Found <b>{len(past_events)} past events</b> that could be removed

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
<code>python3 batch_manager.py clean --review</code>

💡 <i>Past events are kept until manual removal</i>
───────────────────────
🎫 <i>Ticketwatch Alert System</i>"""
        
        # Send past events notification 
        if TG_TOKEN and TG_CHAT and len(past_events) > 0:
            telegram_push("🧹 Cleanup Suggestion", cleanup_msg)
    
    # Save state
    save_state(STATE_FILE, after)
    
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
        # Send beautiful health check notification
        print("✅ No changes detected")
        if os.getenv("PRIMARY", "false").lower() == "true":
            current_time = dt.datetime.now().strftime('%H:%M %Z')
            health_msg = f"""🟢 <b>System Status: All Clear</b>
═══════════════════════════

✅ <b>No price changes detected</b>
📊 Successfully monitored <b>{len(after)} events</b>
🕐 Scan completed at <b>{current_time}</b>

💡 <i>Your tickets are being watched!</i>
───────────────────────
🎫 <i>Ticketwatch Alert System</i>"""
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