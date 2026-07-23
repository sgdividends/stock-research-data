#!/usr/bin/env python3
"""
refresh_fundamentals.py -- quarterly-ish refresh of two things:

  1. sample_inputs.json-style TTM DCF inputs for enhanced_iv.py: OCF/capex/
     D&A summed over the trailing 4 reported quarters, cash, debt, shares,
     rev_cagr, latest_rev_yoy. Written to data/{TICKER}/dcf_inputs.json.

  2. historical_multiples.json-style fiscal-year-end P/E, P/B, P/S snapshots
     (as many years as yfinance's annual financials cover -- usually ~4).
     Written to data/{TICKER}/historical_multiples.json.

READ BEFORE TRUSTING THE OUTPUT BLINDLY:
  - yfinance's annual financials typically only go back ~4 years. A real
    5-year table needs the oldest year filled from a public 10-K
    aggregator (macrotrends, stockanalysis.net) by hand -- this script
    does not do that, it just leaves the array shorter.
  - sbc_est (stock-based comp) is NOT a line yfinance exposes anywhere.
    It is written as null here -- patch it manually from the 10-K, or
    carry forward the last manually-verified value before using this
    output in enhanced_iv.py.
  - EV/EBITDA is intentionally NOT auto-computed here. It needs enterprise
    value at that specific historical date (market cap + debt - cash at
    THAT fiscal year end, not today's), which yfinance doesn't give you
    cleanly for past years, and small errors compound badly. Fill this by
    hand per the project's existing methodology, or extend this script if
    you find a reliable point-in-time EV source.
  - impliedSharesOutstanding is used for the share count, which is the
    project convention for multi-class names (GOOGL etc). Fine for
    single-class names too since it's just the diluted count either way.
  - Uses unadjusted close by default. For high-yield names (banks/REITs)
    where dividend adjustment materially skews historical multiples,
    double check with auto_adjust flipped for that name specifically.

Usage:
    python3 scripts/refresh_fundamentals.py [TICKER ...]
    (no args = read tickers.json)
"""
import json
import os
import sys
import time
from datetime import datetime, timezone

import pandas as pd
import yfinance as yf

from common import load_tickers, data_path, shard_tickers, retry


def safe_get(df, row, col):
    if df is None or row not in getattr(df, "index", []):
        return None
    try:
        v = df.loc[row, col]
        return None if pd.isna(v) else float(v)
    except Exception:
        return None


def sum_last_4(df, row_names, cols):
    if df is None:
        return None
    for name in row_names:
        if name in df.index:
            vals = [safe_get(df, name, c) for c in cols]
            vals = [v for v in vals if v is not None]
            if vals:
                return sum(vals)
    return None


def build_ttm_inputs(ticker: str, tk: yf.Ticker) -> dict:
    q_cf = tk.quarterly_cashflow
    info = tk.info
    cols = list(q_cf.columns)[:4] if q_cf is not None else []

    ocf_ttm = sum_last_4(q_cf, ["Operating Cash Flow",
                                 "Cash Flow From Continuing Operating Activities"], cols)
    capex_ttm = sum_last_4(q_cf, ["Capital Expenditure", "Capital Expenditures"], cols)
    da_ttm = sum_last_4(q_cf, ["Depreciation And Amortization",
                                "Depreciation Amortization Depletion"], cols)
    if capex_ttm is not None:
        capex_ttm = abs(capex_ttm)

    rev_annual = None
    if tk.income_stmt is not None and "Total Revenue" in tk.income_stmt.index:
        rev_annual = tk.income_stmt.loc["Total Revenue"].dropna().sort_index()

    rev_cagr = None
    if rev_annual is not None and len(rev_annual) >= 2 and rev_annual.iloc[0] > 0:
        n = len(rev_annual) - 1
        rev_cagr = round((rev_annual.iloc[-1] / rev_annual.iloc[0]) ** (1 / n) - 1, 4)

    latest_rev_yoy = info.get("revenueGrowth")

    return {
        "ticker": ticker,
        "price": info.get("currentPrice"),
        "beta": info.get("beta"),
        "market_cap": info.get("marketCap"),
        "ocf_ttm": ocf_ttm,
        "capex_ttm": capex_ttm,
        "da_ttm": da_ttm,
        "sbc_est": None,
        "cash": info.get("totalCash"),
        "debt": info.get("totalDebt"),
        "shares": info.get("impliedSharesOutstanding") or info.get("sharesOutstanding"),
        "rev_cagr": rev_cagr,
        "latest_rev_yoy": round(latest_rev_yoy, 4) if latest_rev_yoy is not None else None,
        "last_updated": (datetime.now(timezone.utc).strftime("%Y-%m-%d")
                          + " -- auto-refreshed via GitHub Actions (refresh_fundamentals.py); "
                            "sbc_est needs manual patch from the 10-K before use in enhanced_iv.py"),
    }


def build_historical_multiples(ticker: str, tk: yf.Ticker) -> dict:
    annual_is = tk.income_stmt
    annual_bs = tk.balance_sheet
    price_hist = tk.history(period="5y", interval="1mo", auto_adjust=False)

    years = {}
    if annual_is is not None and "Diluted EPS" in annual_is.index:
        for col in annual_is.columns:
            fy = col.year
            eps = safe_get(annual_is, "Diluted EPS", col)
            if eps is None or eps == 0:
                continue
            equity = safe_get(annual_bs, "Stockholders Equity", col)
            shares = safe_get(annual_is, "Diluted Average Shares", col)
            revenue = safe_get(annual_is, "Total Revenue", col)

            year_prices = price_hist[price_hist.index.year == fy]
            if year_prices.empty:
                continue
            price = float(year_prices["Close"].iloc[-1])

            bvps = (equity / shares) if equity and shares else None
            rev_per_share = (revenue / shares) if revenue and shares else None

            years[str(fy)] = {
                "price": round(price, 2),
                "diluted_eps": round(eps, 3),
                "bvps": round(bvps, 3) if bvps else None,
                "rev_per_share": round(rev_per_share, 3) if rev_per_share else None,
                "pe": round(price / eps, 2) if eps else None,
                "pb": round(price / bvps, 2) if bvps else None,
                "ps": round(price / rev_per_share, 2) if rev_per_share else None,
                "ev_ebitda": None,
            }

    def stat(field):
        vals = [y[field] for y in years.values() if y.get(field) is not None]
        if not vals:
            return None
        vals_sorted = sorted(vals)
        return {
            "high": round(max(vals), 2),
            "low": round(min(vals), 2),
            "avg": round(sum(vals) / len(vals), 2),
            "median": round(vals_sorted[len(vals_sorted) // 2], 2),
        }

    return {
        "methodology": "Auto-generated by refresh_fundamentals.py -- fiscal year-end "
                        "closing price divided by that year's reported diluted EPS, book "
                        "value/share, revenue/share. EV/EBITDA is NOT auto-computed (needs "
                        "point-in-time net debt) -- fill manually per project convention. "
                        "yfinance typically only covers ~4 years -- fill the oldest year "
                        "from a public 10-K aggregator and merge by hand if a true 5yr "
                        "table is needed.",
        "last_updated": datetime.now(timezone.utc).strftime("%Y-%m-%d") + " -- auto-refreshed via GitHub Actions",
        "current_price_at_calc": tk.info.get("currentPrice"),
        "years": years,
        "summary_stats": {
            "pe": stat("pe"),
            "pb": stat("pb"),
            "ps": stat("ps"),
        },
    }


def run_ticker(ticker: str) -> None:
    tk = yf.Ticker(ticker)

    ttm = build_ttm_inputs(ticker, tk)
    with open(data_path(ticker, "dcf_inputs.json"), "w") as f:
        json.dump(ttm, f, indent=2)

    mult = build_historical_multiples(ticker, tk)
    with open(data_path(ticker, "historical_multiples.json"), "w") as f:
        json.dump(mult, f, indent=2)

    print(f"[{ticker}] wrote dcf_inputs.json and historical_multiples.json")


def resolve_tickers():
    """CLI args always win (manual/explicit run). Otherwise, if SHARD_INDEX
    and SHARD_COUNT env vars are set (the matrix-parallel workflow sets
    these per job), take this job's interleaved slice of tickers.json.
    With neither, process everything -- fine for a small watchlist, not
    recommended for the full S&P 500 in a single job (see README)."""
    if len(sys.argv) > 1:
        return sys.argv[1:]

    all_tickers = load_tickers()
    shard_index = int(os.environ.get("SHARD_INDEX", "0"))
    shard_count = int(os.environ.get("SHARD_COUNT", "1"))
    tickers = shard_tickers(all_tickers, shard_index, shard_count)
    if shard_count > 1:
        print(f"Shard {shard_index}/{shard_count}: {len(tickers)} of {len(all_tickers)} tickers")
    return tickers


def main():
    tickers = resolve_tickers()
    for t in tickers:
        try:
            retry(run_ticker, t, retries=3, backoff=10,
                  on_error=lambda attempt, e: print(f"[{t}] attempt {attempt} failed: {e}"))
        except Exception as e:
            print(f"[{t}] FAILED after retries: {e}")
        time.sleep(1.5)  # small pacing delay between tickers to avoid request bursts


if __name__ == "__main__":
    main()
