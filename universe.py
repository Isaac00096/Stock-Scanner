"""
Builds the list of NYSE tickers to scan.

Tries several free sources in order, so one site being down or blocking
automated requests doesn't stop the run:
  1. NASDAQ Trader symbol directory (official; all US listings with exchange code)
  2. NASDAQ stock screener API (NYSE filter)
  3. US-Stock-Symbols list on GitHub (refreshed daily by its maintainer)
"""

import json
import sys
import urllib.request

import config

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept": "text/plain,application/json,*/*",
    "Accept-Language": "en-US,en;q=0.9",
}


def _get(url: str, timeout: int = 30) -> str:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _clean(symbols) -> list[str]:
    out = set()
    for s in symbols:
        s = str(s).strip().upper()
        # skip blanks, preferred shares, warrants/units/rights-style suffixes
        if not s or any(ch in s for ch in "$^/ ") or len(s) > 6:
            continue
        out.add(s.replace(".", "-"))   # BRK.B -> BRK-B (Yahoo's format)
    return sorted(out)


def from_nasdaqtrader() -> list[str]:
    raw = _get("https://www.nasdaqtrader.com/dynamic/SymDirectory/nasdaqtraded.txt")
    lines = raw.strip().split("\n")
    head = lines[0].split("|")
    i_sym, i_ex = head.index("Symbol"), head.index("Listing Exchange")
    i_test, i_etf = head.index("Test Issue"), head.index("ETF")
    syms = []
    for line in lines[1:-1]:
        f = line.split("|")
        if len(f) > max(i_sym, i_ex, i_test, i_etf) and f[i_ex] == "N" and f[i_test] != "Y" and f[i_etf] != "Y":
            syms.append(f[i_sym])
    return _clean(syms)


def from_nasdaq_screener() -> list[str]:
    raw = _get("https://api.nasdaq.com/api/screener/stocks?tableonly=true&limit=10000&exchange=nyse&download=true")
    rows = json.loads(raw)["data"]["rows"]
    return _clean(r["symbol"] for r in rows)


def from_github_list() -> list[str]:
    raw = _get("https://raw.githubusercontent.com/rreichel3/US-Stock-Symbols/main/nyse/nyse_tickers.txt")
    return _clean(raw.split())


SOURCES = [
    ("NASDAQ Trader directory", from_nasdaqtrader),
    ("NASDAQ screener", from_nasdaq_screener),
    ("US-Stock-Symbols (GitHub)", from_github_list),
]


def fetch_nyse_tickers() -> list[str]:
    for name, fn in SOURCES:
        try:
            tickers = fn()
            if len(tickers) > 500:      # sanity check: NYSE has well over 1,000 listings
                print(f"Ticker list: {len(tickers)} NYSE symbols from {name}")
                return tickers
            print(f"Ticker source '{name}' returned only {len(tickers)} symbols, trying next", file=sys.stderr)
        except Exception as exc:
            print(f"Ticker source '{name}' failed: {exc}", file=sys.stderr)
    return []


def get_universe() -> list[str]:
    if config.WATCHLIST_SOURCE == "CUSTOM":
        return list(config.CUSTOM_WATCHLIST)
    tickers = fetch_nyse_tickers()
    if not tickers and config.CUSTOM_WATCHLIST:
        print("All ticker sources failed; using CUSTOM_WATCHLIST.", file=sys.stderr)
        return list(config.CUSTOM_WATCHLIST)
    return tickers


if __name__ == "__main__":
    t = get_universe()
    print(f"{len(t)} tickers, e.g. {t[:15]}")
