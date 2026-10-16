"""
Configuration for the NYSE setup scanner + validator.
Edit values here — no need to touch the other files.
"""

# ---- Universe ----
WATCHLIST_SOURCE = "NYSE"   # "NYSE" (full list, fetched each run) or "CUSTOM"
# Used if WATCHLIST_SOURCE == "CUSTOM", and as a backup if every online ticker source fails.
CUSTOM_WATCHLIST = [
    "JPM", "BAC", "WFC", "C", "GS", "MS", "V", "MA", "AXP", "BRK-B",
    "JNJ", "PFE", "MRK", "ABBV", "LLY", "UNH", "ABT", "TMO", "CVS", "BMY",
    "XOM", "CVX", "COP", "SLB", "OXY", "KO", "PEP", "PG", "WMT", "HD",
    "LOW", "MCD", "NKE", "DIS", "TGT", "CAT", "DE", "GE", "HON", "BA",
    "LMT", "RTX", "UPS", "FDX", "IBM", "ORCL", "CRM", "T", "VZ", "F",
    "GM", "H", "MAR", "HLT", "CCL", "DAL", "UBER", "SHOP", "SPGI", "BLK",
]

# Broker filter: if this file exists (one ticker per line), the DAILY SCAN checks only these
# stocks, so every signal is tradable at your broker (Trade Nation). Validation still uses the
# wide NYSE universe for more history. Lines starting with # are ignored.
BROKER_SYMBOLS_FILE = "broker_symbols.txt"
BROKER_NAME = "Trade Nation"

# ---- Your account (used to show rand risk per trade and what fits your account) ----
ACCOUNT_ZAR = 100           # current Trade Nation balance
GOAL_ZAR = 140              # target (agreed: realistic stretch goal)
GOAL_DATE = "2026-12-31"
RISK_PER_TRADE_PCT = 10.0   # max % of the account to lose on one trade (chosen: 10%)
GOAL_NOTE = ("Simulated on the tested US setup: about a 1 in 3 chance of reaching R140 by December, "
             "about 3 in 4 of finishing in profit, under 1 in 10 of falling below R80.")
TOP_PICKS = 5               # how many plain-language "today's plan" cards to show
MIN_QTY = 0.1               # smallest share quantity Trade Nation accepts on your account

# ---- Markets (everything Trade Nation offers, from markets/instruments.csv) ----
# Every setup is validated SEPARATELY in each market, because a pattern that works on US
# shares may not work on the JSE, forex or gold. A signal only shows if its setup passed in
# that market.
#   cost:      assumed spread + slippage per side, in % (rough Trade Nation-style estimates)
#   benchmark: used for the "market leaders only" setups (None = those setups don't apply)
#   liquidity: apply MIN_PRICE / MIN_AVG_VOLUME (only meaningful for US shares)
INSTRUMENTS_FILE = "markets/instruments.csv"
MARKETS = {
    "us":        {"label": "US shares",     "cost": 0.05, "benchmark": "SPY",       "liquidity": True,  "units": "$"},
    "jse":       {"label": "JSE shares",    "cost": 0.15, "benchmark": "STX40.JO",  "liquidity": False, "units": "c"},
    "uk":        {"label": "UK shares",     "cost": 0.10, "benchmark": "^FTSE",     "liquidity": False, "units": "p"},
    "eu":        {"label": "European shares", "cost": 0.10, "benchmark": "^STOXX50E", "liquidity": False, "units": ""},
    "index":     {"label": "Indices",       "cost": 0.03, "benchmark": None,        "liquidity": False, "units": ""},
    "forex":     {"label": "Forex",         "cost": 0.02, "benchmark": None,        "liquidity": False, "units": ""},
    "commodity": {"label": "Commodities",   "cost": 0.05, "benchmark": None,        "liquidity": False, "units": "$"},
    "crypto":    {"label": "Crypto",        "cost": 0.25, "benchmark": None,        "liquidity": False, "units": "$"},
}
# US shares are validated on the Trade Nation US list PLUS the wider NYSE list (more history,
# clearer verdicts). Other markets are validated on their Trade Nation instruments only.
US_VALIDATE_WITH_NYSE = True

# Liquidity filters (set to None to disable)
MIN_PRICE = 10.0            # Gartley: avoid the low-priced "dogs" (erratic stocks under $10)
MIN_AVG_VOLUME = 200_000    # 20-day average volume

# ---- Daily scan ----
SCAN_PERIOD = "2y"          # history pulled for the daily scan (needs 200+ bars for SMA200)
SHOW_UNVALIDATED = False    # also show setups that haven't passed validation (clearly marked)

# ---- Validation (weekly) ----
VALIDATION_PERIOD = "10y"   # history used to test every setup
VALIDATION_SAMPLE_SIZE = None  # None = every liquid NYSE stock (more trades, clearer verdicts); or a number to sample
VALIDATION_SEED = 42        # keeps the sample the same week to week
OOS_YEARS = 3               # most recent N years held out as the unseen "out-of-sample" test

# A setup is only "validated" if, on the out-of-sample period, it has:
MIN_TRADES_OOS = 100        # at least this many trades
MIN_TSTAT = 2.0             # a t-statistic at least this high (guards against luck)
MIN_EDGE_TSTAT = 2.0        # must beat random entries by a margin unlikely to be luck
# "Paper trade only" tier: passes every other check, and beats random entries,
# but not yet by a clearly significant margin. Shown on the dashboard for practice, never as validated.
WATCHLIST_EDGE_TSTAT = 1.0
# ...plus: positive average return, and was also positive in-sample.

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
