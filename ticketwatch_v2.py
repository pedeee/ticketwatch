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
import asyncio, aiohttp, time
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
HEADERS         = {"User-Agent": "Mozilla/5.0 (ticketwatch/2.0)"}
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

def telegram_push(title: str, message: str, url: str = None):
    if not (TG_TOKEN and TG_CHAT):
        return
    api = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    if url:
        msg = f"🎟️ <b>{title}</b>\n{message}\n<a href='{url}'>Open event</a>"
    else:
        msg = f"🎟️ <b>{title}</b>\n{message}"
    try:
        requests.post(api,
                      data={"chat_id": TG_CHAT, "text": msg,
                            "parse_mode": "HTML", "disable_web_page_preview": True},
                      timeout=10)
    except Exception as e:
        print("✖ Telegram error:", e)

def telegram_batch_changes(changes: List[Change]):
    """Send batched change notifications to reduce spam"""
    if not (TG_TOKEN and TG_CHAT) or not changes:
        return
    
    # Group changes by type
    sold_out = [c for c in changes if "SOLD OUT" in c.new_status]
    price_changes = [c for c in changes if c not in sold_out]
    
    # Send in batches
    for batch_type, batch_changes in [("SOLD OUT", sold_out), ("PRICE CHANGES", price_changes)]:
        if not batch_changes:
            continue
            
        for i in range(0, len(batch_changes), BATCH_SIZE):
            batch = batch_changes[i:i + BATCH_SIZE]
            
            msg_lines = [f"🚨 <b>{batch_type} DETECTED ({len(batch)} events)</b>\n"]
            for c in batch:
                event_date = ""
                if c.event_dt:
                    try:
                        dt_obj = dtparse.parse(c.event_dt)
                        event_date = f" ({dt_obj.strftime('%b %d')})"
                    except:
                        pass
                msg_lines.append(f"• <b>{c.title}</b>{event_date}")
                msg_lines.append(f"  {c.old_status} → {c.new_status}")
                msg_lines.append("")
            
            msg = "\n".join(msg_lines)
            telegram_push("Ticketwatch Alert", msg)

def notify(title: str, message: str, url: str):
    mac_banner(title, message, url)
    telegram_push(title, message, url)

# ─── File helpers ─────────────────────────────────────────────────────────
def load_lines(path: str) -> list[str]:
    if not os.path.exists(path):
        sys.exit(f"✖ {path} missing – add some Ticketweb URLs first.")
    with open(path) as f:
        return [l.strip() for l in f if l.strip() and not l.lstrip().startswith("#")]

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
                    print(f"✖ {url}: Failed after {RETRY_ATTEMPTS} attempts - {e}")
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
    
    async with aiohttp.ClientSession() as session:
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
    
    # Notify about past events that COULD be removed (but don't remove them)
    if past_events:
        print(f"\n⚠️  Found {len(past_events)} past events (manual cleanup suggested):")
        past_msg_lines = [f"⚠️ <b>Past Events Found ({len(past_events)})</b>"]
        past_msg_lines.append("These events could be removed manually:\n")
        
        for event in sorted(past_events, key=lambda x: x["event_dt"] or ""):
            date_str = "No date"
            if event["event_dt"]:
                try:
                    dt_obj = dtparse.parse(event["event_dt"])
                    date_str = dt_obj.strftime("%b %d, %Y")
                except:
                    pass
            print(f"  • {event['title']} ({date_str})")
            past_msg_lines.append(f"• {event['title']} - {date_str}")
        
        past_msg_lines.append(f"\n💡 To remove: python3 batch_manager.py clean --review")
        
        # Send past events notification 
        if TG_TOKEN and TG_CHAT and len(past_events) > 0:
            past_msg = "\n".join(past_msg_lines)
            telegram_push("Manual Cleanup Suggested", past_msg)
    
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
        # Send single health check (reduce frequency to avoid spam)
        print("✅ No changes detected")
        if os.getenv("PRIMARY", "false").lower() == "true":
            telegram_push("Ticketwatch Status", 
                         f"✅ No changes detected\n"
                         f"📊 Monitored {len(after)} events successfully\n"
                         f"⏰ {dt.datetime.now().strftime('%H:%M %Z')}")

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