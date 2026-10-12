"""
Configuration for the NYSE setup scanner + validator.
Edit values here — no need to touch the other files.
"""

# ---- Universe ----
WATCHLIST_SOURCE = "NYSE"   # "NYSE" (full list, fetched each run) or "CUSTOM"
CUSTOM_WATCHLIST = []       # used if WATCHLIST_SOURCE == "CUSTOM"

# Liquidity filters (set to None to disable)
MIN_PRICE = 5.0
MIN_AVG_VOLUME = 200_000    # 20-day average volume

# ---- Daily scan ----
SCAN_PERIOD = "2y"          # history pulled for the daily scan (needs 200+ bars for SMA200)
SHOW_UNVALIDATED = False    # also show setups that haven't passed validation (clearly marked)

# ---- Validation (weekly) ----
VALIDATION_PERIOD = "10y"   # history used to test every setup
VALIDATION_SAMPLE_SIZE = 500   # random NYSE tickers to test on (None = all; slower)
VALIDATION_SEED = 42        # keeps the sample the same week to week
OOS_YEARS = 3               # most recent N years held out as the unseen "out-of-sample" test

# A setup is only "validated" if, on the out-of-sample period, it has:
MIN_TRADES_OOS = 100        # at least this many trades
MIN_TSTAT = 2.0             # a t-statistic at least this high (guards against luck)
# ...plus: positive average return, beats the baseline, and was also positive in-sample.

COST_PCT_PER_SIDE = 0.05    # spread + slippage per side, in %
BASELINE_SAMPLES_PER_TICKER = 40   # random entries per ticker for the "no-signal" baseline

# ---- Output (GitHub Pages serves the docs/ folder) ----
OUTPUT_DIR = "docs"
DASHBOARD_FILE = "index.html"
VALIDATION_FILE = "validation.html"
SETUPS_JSON = "setups.json"

# ---- Download ----
DOWNLOAD_BATCH_SIZE = 100
DOWNLOAD_THREADS = 8
