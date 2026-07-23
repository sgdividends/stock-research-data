#!/usr/bin/env python3
"""
refresh_news.py -- pulls recent news via yfinance, strips it down to the
fields that actually matter (title, summary, date, source, url), caps at
8 items, and writes data/{TICKER}/news.json. This drops the thumbnail
URLs / multiple resolutions / storyline nesting that make the raw
yfinance_get_ticker_news payload much bigger than the signal it carries.

Usage:
    python3 scripts/refresh_news.py [TICKER ...]
    (no args = read tickers.json)
"""
import json
import sys
from datetime import datetime, timezone

import yfinance as yf

from common import load_tickers, data_path


def run_ticker(ticker: str) -> None:
    raw = yf.Ticker(ticker).news or []
    items = []
    for item in raw[:8]:
        content = item.get("content", item)
        title = content.get("title")
        if not title:
            continue
        url = ((content.get("clickThroughUrl") or content.get("canonicalUrl") or {})
               .get("url", ""))
        items.append({
            "title": title,
            "summary": content.get("summary", ""),
            "pub_date": content.get("pubDate"),
            "source": (content.get("provider") or {}).get("displayName", ""),
            "url": url,
        })

    out = {
        "ticker": ticker,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "items": items,
    }
    path = data_path(ticker, "news.json")
    with open(path, "w") as f:
        json.dump(out, f, indent=2)
    print(f"[{ticker}] wrote {path} ({len(items)} items)")


def main():
    tickers = sys.argv[1:] or load_tickers()
    for t in tickers:
        try:
            run_ticker(t)
        except Exception as e:
            print(f"[{t}] ERROR: {e}")


if __name__ == "__main__":
    main()
