#!/usr/bin/env python3
"""
ticketwatch.py – Monitor Ticketweb pages for price changes or sell-outs.
Now reads whichever batch file GitHub passes via the URL_FILE env var.
"""

import json, os, re, sys, time, random, requests, cloudscraper
from typing import Dict, Any
from subprocess import run, DEVNULL
from bs4 import BeautifulSoup
from dateutil import parser as dtparse, tz
import datetime as dt

# ── config ────────────────────────────────────────────────────────────────
URL_FILE   = os.getenv("URL_FILE", "urls.txt")   # batch file set by workflow
STATE_FILE = "state.json"

HEADERS        = {"User-Agent": "Mozilla/5.0 (ticketwatch)"}
PRICE_SELECTOR = "lowest"             # or "highest"
EXCLUDE_HINTS  = ("fee", "fees", "service", "processing")
DEBUG_DATE     = False

scraper = cloudscraper.create_scraper(
    browser={"browser": "firefox", "platform": "darwin", "mobile": False},
    delay=3000
)

TG_TOKEN = os.getenv("TG_TOKEN")
TG_CHAT  = os.getenv("TG_CHAT")

# ── helpers ────────────────────────────────────────────────────────────────
def fmt(s: Dict[str, Any]) -> str:
    if s.get("soldout"):
        return "SOLD OUT"
    if s.get("price") is not None:
        return f"${s['price']:.2f}"
    return "unknown"

def is_past(event_iso: str) -> bool:
    if not event_iso:
        return False
    return dtparse.parse(event_iso) < dt.datetime.now(tz.tzutc())

def notify(title: str, message: str, url: str):
    # Telegram
    if TG_TOKEN and TG_CHAT:
        try:
            requests.post(
                f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
                data={"chat_id": TG_CHAT, "text": f"🎟️ <b>{title}</b>\n{message}\n<a href='{url}'>Open event</a>",
                      "parse_mode": "HTML", "disable_web_page_preview": True},
                timeout=10
            )
        except Exception as e:
            print("✖ Telegram error:", e)
    # Local banner when script is run on macOS (ignored on GitHub)
    try:
        run(["terminal-notifier", "-title", title, "-message", message, "-open", url],
            stdout=DEVNULL, stderr=DEVNULL, check=False)
    except FileNotFoundError:
        pass

# ── scrape a page ─────────────────────────────────────────────────────────
def extract_status(html: str) -> Dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True)

    # 1. date
    date_str = None
    for locator in (
        lambda: soup.find("meta", property="event:start_time").get("content"),
        lambda: soup.find("time").get_text(strip=True),
        lambda: soup.find("p", class_="date").get_text(" ", strip=True),
    ):
        try:
            date_str = locator()
            if date_str:
                break
        except Exception:
            pass
    if not date_str:
        m = re.search(r"(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+"
                      r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2}\s+\d{4}", text)
        if m:
            date_str = m.group(0)

    event_dt = None
    if date_str:
        try:
            event_dt = dtparse.parse(date_str).astimezone(tz.tzutc())
        except Exception as e:
            if DEBUG_DATE:
                print("DEBUG parse fail:", e, date_str)

    # 2. title
    meta = soup.find("meta", property="og:title")
    title = (meta["content"].strip() if meta and meta.get("content")
             else soup.title.string.strip() if soup.title and soup.title.string
             else "<unknown event>")
    title = re.sub(r"\s+\|.*$", "", title)

    # 3. price tiers still available
    prices = []
    for m in re.finditer(r"\$([0-9]{1,5}\.[0-9]{2})", text):
        window = text[max(0, m.start() - 20): m.end() + 20].lower()
        if any(h in window for h in EXCLUDE_HINTS) or "sold out" in window:
            continue
        prices.append(float(m.group(1)))

    price   = min(prices) if PRICE_SELECTOR == "lowest" and prices else (max(prices) if prices else None)
    soldout = not prices

    if DEBUG_DATE:
        print("DEBUG date:", title, event_dt)

    return {"title": title,
            "price": price,
            "soldout": soldout,
            "event_dt": event_dt.isoformat() if event_dt else None}

# ── i/o helpers ────────────────────────────────────────────────────────────
def load_lines(path: str) -> list[str]:
    if not os.path.exists(path):
        sys.exit(f"✖ {path} missing – add links first.")
    with open(path) as f:
        return [l.strip() for l in f if l.strip() and not l.lstrip().startswith("#")]

def load_state():  # batch-specific slice of the big state file
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {}

def save_state(data):
    with open(STATE_FILE, "w") as f:
        json.dump(data, f, indent=2)

# ── main ───────────────────────────────────────────────────────────────────
def main():
    urls    = load_lines(URL_FILE)
    before  = load_state()
    after   = {}
    pruned  = []
    changes = []

    for url in urls:
        # gentle throttle just in case
        time.sleep(random.uniform(0.5, 1.0))

        try:
            r = scraper.get(url, headers=HEADERS, timeout=30)
            r.raise_for_status()
        except Exception as e:
            print("✖", url, e)
            continue

        now = extract_status(r.text)
        after[url] = now

        if is_past(now["event_dt"]):
            pruned.append(url)
            continue

        if now["soldout"]:
            notify(now["title"], "SOLD OUT", url)
        elif before.get(url) != now:
            old = before.get(url, {"price": None, "soldout": None})
            notify(now["title"], f"{fmt(now)} (was {fmt(old)})", url)
            changes.append((now["title"], fmt(old), fmt(now), url))

    # prune finished shows from batch file
    if pruned:
        urls = [u for u in urls if u not in pruned]
        with open(URL_FILE, "w") as f:
            f.write("\n".join(urls) + "\n")
        run(["git", "add", URL_FILE], check=False)

    save_state(after)

    if changes:
        changes.sort(key=lambda c: after[c[3]].get("event_dt") or "9999")
        print("\n🚨 Changes detected:")
        for t, o, n, u in changes:
            print(f"  • {t}\n    {o} → {n}\n    {u}")
    else:
        notify("Ticketwatch", "✓ No changes", "https://github.com/your/repo/actions")

if __name__ == "__main__":
    main()
