"""Shared helpers for the refresh_*.py scripts."""
import json
import os
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_tickers():
    """Reads tickers.json at repo root. CLI args override this in each script."""
    path = os.path.join(ROOT, "tickers.json")
    with open(path) as f:
        return json.load(f)["tickers"]


def data_path(ticker: str, filename: str) -> str:
    """Returns (and creates) data/{TICKER}/{filename}."""
    d = os.path.join(ROOT, "data", ticker)
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, filename)


def shard_tickers(all_tickers, shard_index: int, shard_count: int):
    """Splits all_tickers into shard_count interleaved slices and returns
    the one at shard_index. Interleaving (not contiguous blocks) keeps
    each shard's runtime roughly even even if the ticker list has some
    ordering bias (e.g. alphabetical clustering by sector)."""
    if shard_count <= 1:
        return list(all_tickers)
    return [t for i, t in enumerate(all_tickers) if i % shard_count == shard_index]


def retry(fn, *args, retries=3, backoff=10, on_error=None, **kwargs):
    """Runs fn(*args, **kwargs), retrying with linear backoff on exception.
    Yahoo Finance's unofficial endpoints don't publish a rate limit, but
    hammering many requests in a tight loop reliably triggers 429s /
    empty responses at a few hundred tickers -- this is the cheap fix
    before reaching for anything more elaborate."""
    last_exc = None
    for attempt in range(1, retries + 1):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            last_exc = e
            if on_error:
                on_error(attempt, e)
            if attempt < retries:
                time.sleep(backoff * attempt)
    raise last_exc
