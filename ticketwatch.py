#!/usr/bin/env python3
"""
ticketwatch.py – Monitor Ticketweb event pages for price changes or sell-outs.

Features
────────
• Cloudflare-aware fetch (cloudscraper)
• Stores last-seen price/availability in state.json
• Telegram push with event title + price diff
• Optional macOS banner when run on your own Mac

Knobs
─────
PRICE_SELECTOR = "lowest" | "highest"   # watch GA or VIP tier
"""

import json, os, re, sys, requests, cloudscraper
from typing import Dict, Any
from bs4 import BeautifulSoup
from subprocess import run, DEVNULL

# ─── Files & constants ──────────────────────────────────────────────────────
URL_FILE   = "urls.txt"
STATE_FILE = "state.json"
HEADERS    = {"User-Agent": "Mozilla/5.0 (ticketwatch)"}
PRICE_SELECTOR = "lowest"            # or "highest"
EXCLUDE_HINTS  = ("fee", "fees", "service", "processing")

# ─── Cloudflare-bypass session (re-used for all URLs) ───────────────────────
scraper = cloudscraper.create_scraper(
    browser={'browser': 'firefox', 'platform': 'darwin', 'mobile': False},
    delay=10
)

# ─── Telegram credentials (supplied by GitHub Actions secrets) ──────────────
TG_TOKEN = os.getenv("TG_TOKEN")      # 123456789:AAE…
TG_CHAT  = os.getenv("TG_CHAT")       # 987654321   or  -100…  or  @channel

# ─── Utility: format snapshots ──────────────────────────────────────────────
def fmt(s: Dict[str, Any]) -> str:
    if s.get("soldout"):
        return "SOLD OUT"
    if s.get("price") is not None:
        return f"${s['price']:.2f}"
    return "unknown"

# ─── Extract title, price, sold-out flag from raw HTML ──────────────────────
def extract_status(html: str) -> Dict[str, Any]:
    soup  = BeautifulSoup(html, "html.parser")
    text  = soup.get_text(" ", strip=True)

    # Title
    meta  = soup.find("meta", property="og:title")
    title = (meta["content"].strip() if meta and meta.get("content")
             else soup.title.string.strip() if soup.title and soup.title.string
             else "<unknown event>")
    title = re.sub(r"\s+\|.*$", "", title)      # strip " | Ticketweb"

    # Prices (skip fee lines)
    prices: list[float] = []
    for m in re.finditer(r"\$([0-9]{1,5}\.[0-9]{2})", text):
        window = text[max(0, m.start() - 20): m.end() + 20].lower()
        if any(hint in window for hint in EXCLUDE_HINTS):
            continue
        prices.append(float(m.group(1)))

    price = (min(prices) if PRICE_SELECTOR == "lowest" else max(prices)) if prices else None
    soldout = price is None or "sold out" in text.lower()
    return {"title": title, "price": price, "soldout": soldout}

# ─── Notification helpers ───────────────────────────────────────────────────
def mac_banner(title: str, message: str, url: str):
    """Local macOS banner – ignored on GitHub runner."""
    try:
        run(["terminal-notifier", "-title", title, "-message", message, "-open", url],
            stdout=DEVNULL, stderr=DEVNULL, check=False)
    except FileNotFoundError:
        pass

def telegram_push(title: str, message: str, url: str):
    if not (TG_TOKEN and TG_CHAT):
        return                      # secrets absent on local run
    api = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    text = f"🎟️ <b>{title}</b>\n{message}\n<a href='{url}'>Open event</a>"
    try:
        requests.post(
            api,
            data={
                "chat_id": TG_CHAT,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=10,
        )
    except Exception as e:
        print("✖ Telegram error:", e)

def notify(title: str, message: str, url: str):
    mac_banner(title, message, url)
    telegram_push(title, message, url)

# ─── File helpers ───────────────────────────────────────────────────────────
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

# ─── Main loop ──────────────────────────────────────────────────────────────
def main():
    urls   = load_lines(URL_FILE)
    before = load_state(STATE_FILE)
    after  = {}
    changes: list[tuple[str, str, str, str]] = []

    for url in urls:
        try:
            r = scraper.get(url, headers=HEADERS, timeout=30)
            r.raise_for_status()
        except Exception as e:
            print(f"✖ {url}: {e}")
            continue

        now = extract_status(r.text)
        after[url] = now

        if before.get(url) != now:
            old = before.get(url, {"price": None, "soldout": None})
            notify(now["title"], f"{fmt(now)} (was {fmt(old)})", url)
            changes.append((now["title"], fmt(old), fmt(now), url))

    save_state(STATE_FILE, after)

    if changes:
        print("\n🚨 Changes detected:")
        for title, old, new, url in changes:
            print(f"  • {title}\n    {old}  →  {new}\n    {url}")
    else:
        print("✓ No changes.")

# ────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    main()
