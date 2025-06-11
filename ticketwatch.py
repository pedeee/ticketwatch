#!/usr/bin/env python3
"""
 ticketwatch.py – Monitor Ticketweb event pages for price changes or sell-outs

 CHANGE 2025-06-10 (v3)
 ----------------------
 * **Event title capture** – each snapshot now stores a `title` field scraped
   from `<meta property="og:title">` or the `<title>` tag.  Console output and
   notifications show the event name, making multi-URL lists human-readable.
 * Data structure in `state.json` gains the `title` key.  Older state files
   load fine (missing key defaults to "").

 Knobs at top:
   PRICE_SELECTOR = "lowest" | "highest"  (which tier to watch)
"""
import json, os, re, sys, requests
import cloudscraper
from typing import Dict, Any
from bs4 import BeautifulSoup
from subprocess import run, DEVNULL

URL_FILE   = "urls.txt"
STATE_FILE = "state.json"
HEADERS    = {"User-Agent": "Mozilla/5.0 (ticketwatch)"}
PRICE_SELECTOR = "lowest"   # or "highest" for VIP tiers
EXCLUDE_HINTS  = ("fee", "fees", "service", "processing")

scraper = cloudscraper.create_scraper(
    browser={'browser': 'firefox', 'platform': 'mac', 'mobile': False},
    delay=10
)

def extract_status(html: str) -> Dict[str, Any]:
    """Return {title:str, price:float|None, soldout:bool}."""
    soup  = BeautifulSoup(html, "html.parser")
    text  = soup.get_text(" ", strip=True)

    # ---- grab title ------------------------------------------------------
    meta = soup.find("meta", property="og:title")
    title = (meta["content"].strip() if meta and meta.get("content") else
             soup.title.string.strip() if soup.title and soup.title.string else
             "<unknown event>")
    # remove site suffixes like " | Ticketweb" if present
    title = re.sub(r"\s+\|.*$", "", title)

    # ---- parse prices ----------------------------------------------------
    prices: list[float] = []
    for m in re.finditer(r"\$([0-9]{1,5}\.[0-9]{2})", text):
        price = float(m.group(1))
        window = text[max(0, m.start() - 20): m.end() + 20].lower()
        if any(h in window for h in EXCLUDE_HINTS):
            continue  # skip fee lines
        prices.append(price)

    if prices:
        price = min(prices) if PRICE_SELECTOR == "lowest" else max(prices)
    else:
        price = None

    soldout = (price is None) or ("sold out" in text.lower())
    return {"title": title, "price": price, "soldout": soldout}


# ---------- helpers -------------------------------------------------------

def notify(title: str, message: str, url: str):
    try:
        run(["terminal-notifier", "-title", title, "-message", message, "-open", url],
            stdout=DEVNULL, stderr=DEVNULL, check=False)
    except FileNotFoundError:
        pass


def load_lines(path: str):
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


def fmt(snapshot: Dict[str, Any]):
    if snapshot.get("soldout"):
        return "SOLD OUT"
    if snapshot.get("price") is not None:
        return f"${snapshot['price']:.2f}"
    return "unknown"


# ---------- main loop -----------------------------------------------------

def main():
    urls   = load_lines(URL_FILE)
    before = load_state(STATE_FILE)
    after  = {}
    diff   = []

    for url in urls:
        try:
            r = scraper.get(url, headers=HEADERS, timeout=25)
            r.raise_for_status()
        except Exception as e:
            print(f"✖ {url}: {e}")
            continue

        now = extract_status(r.text)
        after[url] = now

        if before.get(url) != now:
            old = before.get(url, {"title": now["title"], "price": None, "soldout": None})
            notify(now["title"], f"{fmt(now)} (was {fmt(old)})", url)
            diff.append((now["title"], fmt(old), fmt(now), url))

    save_state(STATE_FILE, after)

    if diff:
        print("\n🚨 Changes detected:")
        for title, old, new, url in diff:
            print(f"  • {title}\n    {old}  →  {new}\n    {url}")
    else:
        print("✓ No changes.")


if __name__ == "__main__":
    main()

# ---------------- launchd helper block unchanged ----------------
