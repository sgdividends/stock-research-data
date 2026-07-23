# stock-research-data

Offloads the fetch-and-compute step of the stock-research-workflow to
GitHub Actions, so Claude reads one small pre-computed JSON file per
ticker instead of pulling raw OHLCV/news/financials into its own context
and reprocessing them there.

## Setup

1. Create a new GitHub repo (public -- see note below) and add these
   files at the paths shown.
2. That's it. No secrets or API keys needed -- `yfinance` hits Yahoo
   directly from the runner, and the built-in `GITHUB_TOKEN` (via
   `permissions: contents: write` in each workflow) is enough to commit
   results back to the repo.
3. Go to the Actions tab and manually run each workflow once
   (`workflow_dispatch`) to generate the first `data/` files, or just
   wait for the first scheduled run.

## What runs when

| Workflow | Schedule | Writes |
|---|---|---|
| `refresh-sp500-list.yml` | quarterly (Jan/Apr/Jul/Oct 1st) | `tickers.json` (pulls current S&P 500 membership from Wikipedia) |
| `refresh-technicals.yml` | Tue-Sat 06:00 UTC (after each US session settles) | `data/{TICKER}/technicals.json`, `data/_screener.json` |
| `refresh-news.yml` | every 4 hours | `data/{TICKER}/news.json` |
| `refresh-fundamentals.yml` | 1st of each month | `data/{TICKER}/dcf_inputs.json`, `data/{TICKER}/historical_multiples.json` |

Edit `tickers.json` by hand for a small curated watchlist, or run
`refresh-sp500-list.yml` once to populate it with all ~500 current S&P
500 constituents. All workflows also accept a manual `workflow_dispatch`
with a space-separated `tickers` input if you want to refresh just one
name on demand (still subject to the ~30s-2min runner startup time --
this is for "run before I ask Claude", not "run while I'm mid-conversation
and waiting").

### Scaling to the full S&P 500

These two scripts are already built to handle ~500 tickers without
hitting GitHub's limits or Yahoo Finance's informal rate limiting:

- **`refresh_technicals.py`** batches OHLCV pulls via `yf.download()`
  across chunks of 100 tickers per HTTP round-trip (instead of one
  `Ticker().history()` call per name), with retry/backoff per chunk.
  At 500 tickers this comfortably finishes in a single job well under
  GitHub's 6-hour job limit -- no sharding needed.
- **`build_screener.py`** runs right after and rolls every ticker's
  `technicals.json` into one `data/_screener.json` with ranked lists
  (most oversold RSI, furthest below SMA200, etc). This is the file to
  fetch for cross-sectional questions ("which S&P 500 names look
  oversold") -- fetching 500 individual files for a screen would be
  hundreds of thousands of tokens; fetching one rollup file is not.
- **`refresh_fundamentals.py`** has no good batch API in yfinance for
  quarterly financials, so at 500 tickers it's sharded across a matrix
  instead (`refresh-fundamentals.yml`, default 10 parallel shards, capped
  at 20 to stay inside the free plan's concurrent-job limit). Each shard
  writes to a build artifact rather than pushing directly -- 10 jobs
  pushing to the same branch at once would race each other -- and a
  final `merge-shards` job downloads all the artifacts and makes exactly
  one commit.

For a small watchlist (the original 8 tickers), none of this sharding
machinery kicks in -- `SHARD_COUNT` defaults to 1 effectively, or you can
just pass explicit tickers to `workflow_dispatch` and it runs as a single
job like before.

## How Claude reads this

Once the repo is public, the compact files are at:

```
https://raw.githubusercontent.com/{you}/{repo}/main/data/GOOGL/technicals.json
https://raw.githubusercontent.com/{you}/{repo}/main/data/GOOGL/news.json
https://raw.githubusercontent.com/{you}/{repo}/main/data/GOOGL/dcf_inputs.json
https://raw.githubusercontent.com/{you}/{repo}/main/data/GOOGL/historical_multiples.json
https://raw.githubusercontent.com/{you}/{repo}/main/data/_screener.json   <- cross-sectional rollup, for "screen the universe" asks
```

`raw.githubusercontent.com` is already on Claude's sandbox network
allowlist, so a single `web_fetch` per file replaces the multi-call,
multi-thousand-token yfmcp round trips for the parts that don't need to
be live (technicals, news digest, TTM DCF inputs, historical multiples).
Live price and the day's breaking headline should still be pulled
directly via yfmcp -- those are intentionally NOT cached here.

## Known gaps -- don't trust these outputs blindly

- **`sbc_est` in `dcf_inputs.json` is always `null`.** yfinance has no
  stock-based-comp line anywhere. Patch it by hand from the 10-K (or
  carry forward a previously verified value) before feeding this into
  `enhanced_iv.py`.
- **`ev_ebitda` in `historical_multiples.json` is always `null`.** It
  needs point-in-time enterprise value (market cap + debt - cash *as of
  that historical fiscal year end*, not today), which yfinance doesn't
  expose cleanly for past years, and small errors compound. Fill by hand
  per the project's existing methodology.
- **Only ~4 years of history**, not 5. yfinance's annual financials
  window is short. The oldest year needs filling from a public 10-K
  aggregator (macrotrends, stockanalysis.net) and merging in by hand, same
  as the project already does today.
- **Support/resistance is not computed at all.** That section of the
  research brief still needs a human (or Claude) read of the price
  action -- it's a judgment call, not a mechanical calculation.
- **Dividend-adjustment**: `refresh_fundamentals.py` uses unadjusted
  close by default. For high-yield names (banks, REITs) where that
  materially skews historical multiples, this needs a manual check.

None of these are meant to be "solved" by more automation necessarily --
some of this (EV/EBITDA net debt, the oldest historical year, SBC) is
exactly the kind of judgment-call data quality issue the project's
existing skill file already flags as needing a careful human/Claude
pass, not a fully mechanical one.

## Repo layout

```
.github/workflows/
  refresh-sp500-list.yml
  refresh-technicals.yml
  refresh-news.yml
  refresh-fundamentals.yml
scripts/
  common.py                     (shared helpers: ticker loading, sharding, retry/backoff)
  fetch_sp500_constituents.py
  refresh_technicals.py         (batch yf.download(), chunked)
  build_screener.py             (rolls up all technicals.json into one file)
  refresh_news.py
  refresh_fundamentals.py       (shard-aware for the matrix workflow)
tickers.json
requirements.txt
data/                (generated by the workflows, committed automatically)
  _screener.json      (cross-sectional rollup across the whole universe)
  GOOGL/
    technicals.json
    news.json
    dcf_inputs.json
    historical_multiples.json
  ...
```
