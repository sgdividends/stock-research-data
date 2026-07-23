#!/usr/bin/env python3
"""
refresh_technicals.py -- BATCH version, scales to the full S&P 500.

Pulls OHLCV via yf.download() for many tickers per HTTP round-trip
instead of looping Ticker().history() once per name -- this is the
single highest-leverage change for staying under Yahoo Finance's
informal rate limits once you're tracking hundreds of tickers instead
of a handful. At 8 tickers this doesn't matter; at 500 it's the
difference between a 2-minute job and one that gets 429'd halfway
through.

Computes the same RSI / SMA20-50-200 / MACD / Bollinger / ATR indicators
as ta_from_ibkr.py, plus 1-year percentile ranks for RSI(14) and
Bollinger %B, and writes a compact per-ticker summary to
data/{TICKER}/technicals.json.

Usage:
    python3 scripts/refresh_technicals.py [TICKER ...]
    (no args = read tickers.json, batched into chunks of CHUNK_SIZE)
"""
import json
import sys
import time
from datetime import datetime, timezone

import pandas as pd
import pandas_ta_classic as ta
import yfinance as yf

from common import load_tickers, data_path

CHUNK_SIZE = 100        # tickers per yf.download() call
RETRIES = 3
BACKOFF_SECONDS = 15    # base backoff between retries; grows with attempt number


def chunked(seq, size):
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


def download_with_retry(tickers_chunk):
    for attempt in range(1, RETRIES + 1):
        try:
            data = yf.download(
                tickers=tickers_chunk,
                period="1y",
                interval="1d",
                group_by="ticker",
                threads=True,
                auto_adjust=False,
                progress=False,
            )
            if data is not None and not data.empty:
                return data
        except Exception as e:
            print(f"  chunk download attempt {attempt} failed: {e}")
        if attempt < RETRIES:
            wait = BACKOFF_SECONDS * attempt
            print(f"  retrying in {wait}s...")
            time.sleep(wait)
    return None


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["rsi_14"] = ta.rsi(out["close"], length=14)
    out["sma_20"] = ta.sma(out["close"], length=20)
    out["sma_50"] = ta.sma(out["close"], length=50)
    out["sma_200"] = ta.sma(out["close"], length=200)

    macd = ta.macd(out["close"], fast=12, slow=26, signal=9)
    out["macd"] = macd["MACD_12_26_9"]
    out["macd_signal"] = macd["MACDs_12_26_9"]
    out["macd_hist"] = macd["MACDh_12_26_9"]

    bb = ta.bbands(out["close"], length=20, std=2)
    col = lambda prefix: [c for c in bb.columns if c.startswith(prefix)][0]
    out["bb_lower"] = bb[col("BBL_")]
    out["bb_mid"] = bb[col("BBM_")]
    out["bb_upper"] = bb[col("BBU_")]
    out["bb_pctb"] = bb[col("BBP_")]

    out["atr_14"] = ta.atr(out["high"], out["low"], out["close"], length=14)
    out["atr_pct"] = out["atr_14"] / out["close"] * 100
    return out


def percentile_rank(series: pd.Series, value: float):
    clean = series.dropna()
    if len(clean) == 0 or pd.isna(value):
        return None
    return round(float((clean < value).mean()) * 100, 1)


def extract_ticker_frame(batch_data: pd.DataFrame, ticker: str, single_ticker_mode: bool):
    """yf.download(group_by='ticker') returns MultiIndex columns for
    multi-ticker batches, but a flat frame if the chunk collapsed to one
    ticker (or yfinance drops the outer level for a 1-ticker request) --
    handle both shapes rather than assuming."""
    if single_ticker_mode:
        sub = batch_data
    else:
        top_level = batch_data.columns.get_level_values(0)
        if ticker not in top_level:
            return None
        sub = batch_data[ticker]

    sub = sub.dropna(how="all").reset_index()
    sub.columns = [str(c).lower() for c in sub.columns]
    # yfinance names the index "Date" (daily) or "Datetime" (intraday); an
    # unnamed index falls back to "index" after reset_index() -- handle all three
    if "date" not in sub.columns:
        for candidate in ("datetime", "index"):
            if candidate in sub.columns:
                sub = sub.rename(columns={candidate: "date"})
                break

    needed = ["date", "open", "high", "low", "close", "volume"]
    if not all(c in sub.columns for c in needed):
        return None
    return sub[needed].dropna(subset=["close"])


def build_summary(ticker: str, df: pd.DataFrame) -> dict:
    ind = compute_indicators(df)
    latest = ind.iloc[-1]
    macd_state = "bullish" if latest["macd_hist"] > 0 else "bearish"

    def pct_from_price(level):
        if pd.isna(level) or level == 0:
            return None
        return round((latest["close"] / level - 1) * 100, 2)

    def r(v, n=2):
        return round(float(v), n) if not pd.isna(v) else None

    return {
        "ticker": ticker,
        "as_of": latest["date"].strftime("%Y-%m-%d"),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "close": r(latest["close"]),
        "rsi_14": r(latest["rsi_14"]),
        "rsi_14_pctile_1y": percentile_rank(ind["rsi_14"], latest["rsi_14"]),
        "sma_20": r(latest["sma_20"]),
        "sma_20_pct_from_price": pct_from_price(latest["sma_20"]),
        "sma_50": r(latest["sma_50"]),
        "sma_50_pct_from_price": pct_from_price(latest["sma_50"]),
        "sma_200": r(latest["sma_200"]),
        "sma_200_pct_from_price": pct_from_price(latest["sma_200"]),
        "macd": r(latest["macd"], 3),
        "macd_signal": r(latest["macd_signal"], 3),
        "macd_hist": r(latest["macd_hist"], 3),
        "macd_state": macd_state,
        "bb_upper": r(latest["bb_upper"]),
        "bb_mid": r(latest["bb_mid"]),
        "bb_lower": r(latest["bb_lower"]),
        "bb_pctb": r(latest["bb_pctb"], 3),
        "bb_pctb_pctile_1y": percentile_rank(ind["bb_pctb"], latest["bb_pctb"]),
        "atr_14": r(latest["atr_14"]),
        "atr_pct": r(latest["atr_pct"]),
        "week52_high": r(ind["high"].max()),
        "week52_low": r(ind["low"].min()),
        "note": "Support/resistance still needs a manual read of price action "
                "-- not automated here. Percentile ranks are vs this ticker's "
                "own trailing 1yr distribution, not cross-sectional vs the "
                "rest of the universe (see data/_screener.json for that).",
    }


def main():
    tickers = sys.argv[1:] or load_tickers()
    print(f"Refreshing technicals for {len(tickers)} tickers in chunks of {CHUNK_SIZE}")

    written, failed = 0, []
    for chunk in chunked(tickers, CHUNK_SIZE):
        print(f"Downloading chunk: {chunk[0]}..{chunk[-1]} ({len(chunk)} tickers)")
        data = download_with_retry(chunk)
        if data is None:
            print(f"  chunk failed after {RETRIES} retries, skipping {len(chunk)} tickers")
            failed.extend(chunk)
            continue

        single_ticker_mode = len(chunk) == 1
        for ticker in chunk:
            try:
                df = extract_ticker_frame(data, ticker, single_ticker_mode)
                if df is None or df.empty or len(df) < 20:
                    print(f"  [{ticker}] insufficient data, skipping")
                    failed.append(ticker)
                    continue
                summary = build_summary(ticker, df)
                path = data_path(ticker, "technicals.json")
                with open(path, "w") as f:
                    json.dump(summary, f, indent=2)
                written += 1
            except Exception as e:
                print(f"  [{ticker}] ERROR: {e}")
                failed.append(ticker)

    print(f"Done. Wrote {written} tickers, {len(failed)} failed.")
    if failed:
        print("Failed tickers:", ", ".join(failed))


if __name__ == "__main__":
    main()
