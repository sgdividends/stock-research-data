#!/usr/bin/env python3
"""
fetch_sp500_constituents.py -- pulls the current S&P 500 constituent list
from Wikipedia's public "List of S&P 500 companies" page and overwrites
tickers.json with it.

Run this occasionally (membership changes roughly quarterly, not daily)
-- NOT on the same nightly cron as the data refreshes, since reshuffling
the universe mid-cycle just adds noise to what the other workflows are
tracking.

Ticker symbols are normalized to Yahoo Finance's convention (dots become
hyphens, e.g. BRK.B -> BRK-B, BF.B -> BF-B) since that's what yfinance
expects.

Usage:
    python3 scripts/fetch_sp500_constituents.py
"""
import json
import os

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WIKI_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"


def fetch_constituents() -> list:
    tables = pd.read_html(WIKI_URL)
    table = tables[0]  # first table on the page is the constituent list
    symbols = table["Symbol"].astype(str).str.strip().tolist()
    symbols = [s.replace(".", "-") for s in symbols]
    return sorted(set(symbols))


def main():
    symbols = fetch_constituents()
    print(f"Fetched {len(symbols)} S&P 500 constituents from Wikipedia")

    path = os.path.join(ROOT, "tickers.json")
    with open(path, "w") as f:
        json.dump({"tickers": symbols}, f, indent=2)
    print(f"Wrote {path}")


if __name__ == "__main__":
    main()
