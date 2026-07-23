#!/usr/bin/env python3
"""
build_screener.py -- reads every data/{TICKER}/technicals.json already
written by refresh_technicals.py and rolls them up into ONE compact
data/_screener.json file, ranked several ways.

This is the file Claude should fetch for cross-sectional questions
("which S&P 500 names are oversold right now") instead of fetching
hundreds of individual per-ticker files -- one small file vs. N large
ones is the whole point of doing this server-side.

Run as the last step of refresh-technicals.yml, after
refresh_technicals.py has written the per-ticker files it reads.

Usage:
    python3 scripts/build_screener.py
"""
import glob
import json
import os
from datetime import datetime, timezone

from common import ROOT


def load_all_technicals():
    rows = []
    pattern = os.path.join(ROOT, "data", "*", "technicals.json")
    for path in glob.glob(pattern):
        try:
            with open(path) as f:
                rows.append(json.load(f))
        except Exception as e:
            print(f"skip {path}: {e}")
    return rows


def top_n(rows, key, n=15, reverse=False):
    valid = [r for r in rows if r.get(key) is not None]
    valid.sort(key=lambda r: r[key], reverse=reverse)
    return [{"ticker": r["ticker"], key: r[key], "close": r.get("close")}
            for r in valid[:n]]


def main():
    rows = load_all_technicals()
    if not rows:
        print("No technicals.json files found -- run refresh_technicals.py first")
        return

    screener = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "universe_size": len(rows),
        "most_oversold_rsi": top_n(rows, "rsi_14_pctile_1y", n=15, reverse=False),
        "most_overbought_rsi": top_n(rows, "rsi_14_pctile_1y", n=15, reverse=True),
        "most_below_bollinger": top_n(rows, "bb_pctb_pctile_1y", n=15, reverse=False),
        "most_above_bollinger": top_n(rows, "bb_pctb_pctile_1y", n=15, reverse=True),
        "furthest_below_sma200": top_n(rows, "sma_200_pct_from_price", n=15, reverse=False),
        "furthest_above_sma200": top_n(rows, "sma_200_pct_from_price", n=15, reverse=True),
        "bullish_macd_count": sum(1 for r in rows if r.get("macd_state") == "bullish"),
        "bearish_macd_count": sum(1 for r in rows if r.get("macd_state") == "bearish"),
        "note": "Rankings are each ticker's own trailing-1yr RSI/%%B percentile "
                "(how extreme vs its OWN history), not a cross-sectional rank vs "
                "the rest of the universe on the same day -- sma_200_pct_from_price "
                "columns ARE directly cross-sectional (plain %% distance) though. "
                "Use this file for 'which names look extreme' screens; fetch the "
                "individual data/{TICKER}/*.json files for a full single-name brief.",
    }

    path = os.path.join(ROOT, "data", "_screener.json")
    with open(path, "w") as f:
        json.dump(screener, f, indent=2)
    print(f"Wrote {path} from {len(rows)} tickers")


if __name__ == "__main__":
    main()
