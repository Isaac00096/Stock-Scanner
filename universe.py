"""
Builds the ticker universe to scan.

NYSE-listed symbols are pulled from the NASDAQ Trader symbol directory,
which lists every symbol across US exchanges along with its listing
exchange code. We filter for Exchange == 'N' (NYSE).

Source: https://www.nasdaqtrader.com/dynamic/SymDirectory/nasdaqtraded.txt
"""

import io
import sys
import urllib.request

import config

NASDAQ_TRADER_URL = "https://www.nasdaqtrader.com/dynamic/SymDirectory/nasdaqtraded.txt"


def fetch_nyse_tickers() -> list[str]:
    """Download and parse the full list of currently-listed NYSE tickers."""
    try:
        with urllib.request.urlopen(NASDAQ_TRADER_URL, timeout=30) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except Exception as exc:
        print(f"ERROR: could not fetch NYSE symbol directory: {exc}", file=sys.stderr)
        print("Falling back to CUSTOM_WATCHLIST in config.py if set.", file=sys.stderr)
        return []

    lines = raw.strip().split("\n")
    header = lines[0].split("|")
    rows = lines[1:-1]  # first line is header, last line is a file-footer record

    try:
        symbol_idx = header.index("Symbol")
        exchange_idx = header.index("Listing Exchange")
        test_idx = header.index("Test Issue")
        etf_idx = header.index("ETF")
    except ValueError as exc:
        print(f"ERROR: unexpected file format from NASDAQ Trader: {exc}", file=sys.stderr)
        return []

    tickers = []
    for line in rows:
        fields = line.split("|")
        if len(fields) <= max(symbol_idx, exchange_idx, test_idx, etf_idx):
            continue
        if fields[exchange_idx] != "N":       # NYSE only
            continue
        if fields[test_idx] == "Y":           # skip test issues
            continue
        if fields[etf_idx] == "Y":            # skip ETFs — stocks only
            continue
        symbol = fields[symbol_idx].strip()
        if symbol and "$" not in symbol:      # skip preferred/unit share classes
            tickers.append(symbol)

    return sorted(set(tickers))


def get_universe() -> list[str]:
    """Return the ticker list to scan, per config.py."""
    if config.WATCHLIST_SOURCE == "CUSTOM":
        return list(config.CUSTOM_WATCHLIST)

    tickers = fetch_nyse_tickers()
    if not tickers and config.CUSTOM_WATCHLIST:
        print("Using CUSTOM_WATCHLIST as fallback.", file=sys.stderr)
        return list(config.CUSTOM_WATCHLIST)
    return tickers


if __name__ == "__main__":
    t = get_universe()
    print(f"Fetched {len(t)} NYSE tickers.")
    print(t[:20])
