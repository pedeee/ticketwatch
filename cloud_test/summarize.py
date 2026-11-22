#!/usr/bin/env python3
"""Summarize a cloud test scan: did TicketWeb serve real event pages to this machine?

Usage: python cloud_test/summarize.py cloud_test/urls.txt

Reads the state/stats files the scanner wrote next to the URL file and prints a verdict.
On GitHub Actions it also publishes the verdict as a notice and in the run summary.
Always exits 0: a blocked scan is a test result, not a workflow error.
"""
import json
import os
import sys

BLOCKED_TITLE_MARKERS = ("identity verified", "502 bad gateway", "504 gateway", "gateway time-out", "<unknown event>")


def load(path):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return {}


def classify(entry):
    """real | blocked | no_ticket_data | failed"""
    if not entry:
        return "failed"
    title = (entry.get("title") or "").lower()
    if any(m in title for m in BLOCKED_TITLE_MARKERS) or title.strip() in ("ticketweb", "") or title.startswith("unknown event"):
        return "blocked"
    if not entry.get("ticket_data_ok"):
        return "no_ticket_data"
    return "real"


def main():
    url_file = sys.argv[1]
    urls = [l.split("#")[0].strip() for l in open(url_file) if l.strip().startswith("http")]
    state = load(f"{url_file}.state.json")
    stats = load(f"{url_file}.stats.json")
    reasons = {}
    for row in stats.get("failed_urls", []):
        if isinstance(row, dict):
            reasons[row.get("url")] = row.get("reason")

    counts = {"real": 0, "blocked": 0, "no_ticket_data": 0, "failed": 0}
    lines = []
    for u in urls:
        entry = state.get(u)
        kind = classify(entry)
        counts[kind] += 1
        event_id = u.rstrip("/").split("/")[-1]
        if kind == "real":
            price = entry.get("price")
            price_txt = "SOLD OUT" if entry.get("soldout") else (f"${price:.2f}" if price is not None else "no price")
            detail = f"{(entry.get('title') or '')[:45]} | {price_txt} | {entry.get('ticket_type')} | limit {entry.get('purchase_limit')}"
        elif kind == "failed":
            detail = reasons.get(u) or "no data returned"
        else:
            detail = (entry.get("title") or "")[:60]
        lines.append(f"[{kind}] {event_id}: {detail}")

    total = len(urls)
    if not state:
        # Nothing was written at all: the scanner itself failed (setup/crash), which says
        # nothing about whether TicketWeb blocks this machine.
        verdict = "NO RESULT (scanner produced no data - see the scan step's log)"
    elif total and counts["real"] == total:
        verdict = "PASS"
    elif counts["real"] == 0:
        verdict = "BLOCKED"
    else:
        verdict = "PARTIAL"
    headline = (
        f"{verdict}: {counts['real']}/{total} real event pages, {counts['blocked']} blocked/identity-check, "
        f"{counts['failed']} failed, {counts['no_ticket_data']} without ticket data"
    )

    print(headline)
    for line in lines:
        print("  " + line)

    if os.getenv("GITHUB_ACTIONS") == "true":
        # One-line notice (readable from the run page and the public API)
        compact = " ; ".join(lines).replace("\n", " ").replace("%", "%25")
        print(f"::notice title=Cloud test result::{headline}")
        print(f"::notice title=Cloud test details::{compact[:3500]}")
        summary_path = os.getenv("GITHUB_STEP_SUMMARY")
        if summary_path:
            with open(summary_path, "a") as f:
                f.write(f"## TicketWeb cloud test\n\n**{headline}**\n\n```\n" + "\n".join(lines) + "\n```\n")


if __name__ == "__main__":
    main()
