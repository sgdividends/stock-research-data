
#!/usr/bin/env python3
"""
fetch_sp500_constituents.py -- pulls the current S&P 500 constituent list
and overwrites tickers.json.

PRIMARY source: the community-maintained "datasets/s-and-p-500-companies"
GitHub repo's constituents.csv -- a plain CSV kept in sync with Wikipedia
by an automated bot (verified last-updated within days of writing this).
Much less fragile than scraping Wikipedia directly: no HTML parsing, no
User-Agent tricks needed.

FALLBACK: scrapes Wikipedia's "List of S&P 500 companies" page directly,
used only if the primary CSV source is unreachable. Wikipedia blocks
requests without a browser-like User-Agent header -- a common gotcha with
pandas.read_html(), which sends none by default and gets a 403. This
fallback sets one explicitly via requests, then hands the HTML text to
pandas.read_html() instead of letting it fetch the URL itself.

Refuses to overwrite tickers.json if either source returns a suspiciously
small list (<400 tickers) -- better to fail loudly than silently replace
a good ticker list with a broken/partial one.

Run this occasionally (membership changes roughly quarterly, not daily).
Ticker symbols are normalized to Yahoo Finance's convention (dots become
hyphens, e.g. BRK.B -> BRK-B, BF.B -> BF-B).

Usage:
    python3 scripts/fetch_sp500_constituents.py
"""
import json
import os
from io import StringIO

import pandas as pd
import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CSV_URL = "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/master/data/constituents.csv"
WIKI_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; stock-research-data-bot/1.0)"}
MIN_EXPECTED = 400  # sanity floor -- real S&P 500 lists are ~500-503 rows


def normalize(symbols) -> list:
    symbols = [str(s).strip().replace(".", "-") for s in symbols]
    return sorted(set(symbols))


def fetch_from_csv() -> list:
    resp = requests.get(CSV_URL, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    df = pd.read_csv(StringIO(resp.text))
    return normalize(df["Symbol"])


def fetch_from_wikipedia() -> list:
    resp = requests.get(WIKI_URL, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    tables = pd.read_html(StringIO(resp.text))
    table = tables[0]  # first table on the page is the constituent list
    return normalize(table["Symbol"])


def fetch_constituents() -> list:
    try:
        symbols = fetch_from_csv()
        print(f"Fetched {len(symbols)} constituents from the GitHub CSV source")
        if len(symbols) >= MIN_EXPECTED:
            return symbols
        print(f"Only {len(symbols)} tickers from CSV source, trying Wikipedia fallback")
    except Exception as e:
        print(f"CSV source failed ({e}), falling back to Wikipedia")

    symbols = fetch_from_wikipedia()
    print(f"Fetched {len(symbols)} constituents from Wikipedia")
    return symbols


def main():
    symbols = fetch_constituents()
    if len(symbols) < MIN_EXPECTED:
        raise SystemExit(
            f"Only found {len(symbols)} tickers (expected ~500) from both sources -- "
            f"refusing to overwrite tickers.json with likely-bad data."
        )

    path = os.path.join(ROOT, "tickers.json")
    with open(path, "w") as f:
        json.dump({"tickers": symbols}, f, indent=2)
    print(f"Wrote {path} ({len(symbols)} tickers)")


if __name__ == "__main__":
    main()
