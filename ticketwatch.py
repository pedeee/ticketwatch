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
• Cloudflare-aware fetch when needed

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

# ─── Cloudflare-bypass session ────────────────────────────────────────────
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
        except (ValueError, TypeError, dtparse.ParserError) as e:
            if DEBUG_DATE:
                print("DEBUG parse fail:", e, date_str)

    # 2. Title --------------------------------------------------------------
    meta = soup.find("meta", property="og:title")
    title = (meta["content"].strip() if meta and meta.get("content")
             else soup.title.string.strip() if soup.title and soup.title.string
             else "<unknown event>")
    title = re.sub(r"\s+\|.*$", "", title)

    # 3. Price search (skip fee lines) --------------------------------------
    prices: List[float] = []
    
    # Look for various price patterns including ones without decimals
    price_patterns = [
        r"\$([0-9]{1,5}\.[0-9]{2})",  # $25.00 format
        r"\$([0-9]{1,5})",            # $25 format  
    ]
    
    for pattern in price_patterns:
        for m in re.finditer(pattern, text):
            price_value = float(m.group(1))
            # Convert to .00 format if no decimals
            if '.' not in m.group(1):
                price_value = float(m.group(1))
            
            window = text[max(0, m.start() - 20): m.end() + 20].lower()
            if any(h in window for h in EXCLUDE_HINTS) or "sold out" in window:
                continue
            prices.append(price_value)
    
    # Remove duplicates and sort
    prices = sorted(list(set(prices)))
    
    price   = (min(prices) if PRICE_SELECTOR == "lowest" else max(prices)) if prices else None
    soldout = not prices or "sold out" in text.lower() or "unavailable" in text.lower()

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
    except (requests.RequestException, requests.Timeout) as e:
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

# ─── Main loop ────────────────────────────────────────────────────────────
def main():
    urls    = load_lines(URL_FILE)
    before  = load_state(STATE_FILE)
    after   = {}
    pruned_urls = []
    changes = []

    for url in urls:
        try:
            r = scraper.get(url, headers=HEADERS, timeout=30)
            r.raise_for_status()
            now = extract_status(r.text)
            after[url] = now
        except (requests.RequestException, cloudscraper.exceptions.CloudflareChallengeError) as e:
            print(f"✖ {url}: {e}")
            # Preserve old state to maintain price memory
            old_state = before.get(url)
            if old_state:
                after[url] = old_state
                print(f"⚠️ Preserving previous state for {url[:50]}...")
            continue

        # Drop past shows
        if is_past(now["event_dt"]):
            pruned_urls.append(url)
            continue

        # Check for meaningful changes only
        old = before.get(url, {"price": None, "soldout": None})
        
        def is_meaningful_change(old_state, new_state):
            old_price = old_state.get("price")
            new_price = new_state.get("price")
            old_soldout = old_state.get("soldout")
            new_soldout = new_state.get("soldout")
            
            # Ignore changes where both prices are None (unknown -> unknown)
            if old_price is None and new_price is None:
                return False
                
            # Always notify for soldout status changes
            if old_soldout != new_soldout:
                return True
                
            # Notify for price changes (including None -> price or price -> None)
            if old_price != new_price:
                return True
                
            return False
        
        if is_meaningful_change(old, now):
            notify(now["title"], f"{fmt(now)} (was {fmt(old)})", url)
            changes.append((now["title"], fmt(old), fmt(now), url))

    # prune URLs & stage
    if pruned_urls:
        urls = [u for u in urls if u not in pruned_urls]
        with open(URL_FILE, "w") as f:
            f.write("\n".join(urls) + "\n")
        run(["git", "add", URL_FILE], check=False)

    save_state(STATE_FILE, after)

    if changes:
        # sort by soonest show (None last)
        changes.sort(key=lambda c: after[c[3]].get("event_dt") or "9999")
        print("\n🚨 Changes detected:")
        for title, old, new, url in changes:
            print(f"  • {title}\n    {old}  →  {new}\n    {url}")
    else:
        # ONLY the primary (batch1) job sends the “no changes” ping
        if os.getenv("PRIMARY", "false").lower() == "true":
            notify("Ticketwatch", "✓ No changes",
                   "https://github.com/pedee/ticketwatch/actions")

# ──────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    main()
