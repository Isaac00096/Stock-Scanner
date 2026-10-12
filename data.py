"""
Daily price data loading (Yahoo Finance via yfinance), shared by the
scanner and the validator. --csv-dir lets you use local CSVs instead
(one file per ticker, e.g. H.csv, with Date,Open,High,Low,Close,Volume).
"""

import os
import time

import pandas as pd

import config

COLS = ["Open", "High", "Low", "Close", "Volume"]


def _clean(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    if isinstance(df.columns, pd.MultiIndex):
        for lvl in range(df.columns.nlevels):
            if "Close" in df.columns.get_level_values(lvl):
                df = df.copy()
                df.columns = df.columns.get_level_values(lvl)
                break
    if not set(COLS).issubset(df.columns):
        return pd.DataFrame()
    df = df[COLS].dropna(how="any")
    df = df[~df.index.duplicated(keep="last")].sort_index()
    if getattr(df.index, "tz", None) is not None:
        df.index = df.index.tz_localize(None)
    return df


def iter_daily(tickers: list[str], period: str, csv_dir: str | None = None):
    """Yields (ticker, DataFrame). The DataFrame is empty if data was unavailable."""
    if csv_dir:
        for t in tickers:
            path = os.path.join(csv_dir, f"{t}.csv")
            df = pd.read_csv(path, index_col=0, parse_dates=True) if os.path.exists(path) else None
            yield t, _clean(df)
        return

    import yfinance as yf

    size = config.DOWNLOAD_BATCH_SIZE
    batches = [tickers[i:i + size] for i in range(0, len(tickers), size)]
    for i, batch in enumerate(batches, 1):
        print(f"  batch {i}/{len(batches)} ({len(batch)} tickers)")
        try:
            data = yf.download(tickers=batch, period=period, interval="1d", group_by="ticker",
                               threads=config.DOWNLOAD_THREADS, progress=False, auto_adjust=True)
        except Exception as exc:
            print(f"  batch failed: {exc}")
            for t in batch:
                yield t, pd.DataFrame()
            continue
        for t in batch:
            try:
                if isinstance(data.columns, pd.MultiIndex):
                    df = data[t] if t in data.columns.get_level_values(0) else None
                else:
                    df = data
                yield t, _clean(df)
            except Exception:
                yield t, pd.DataFrame()
        time.sleep(1)


def liquid(df: pd.DataFrame) -> bool:
    last = df.tail(20)
    if config.MIN_PRICE is not None and last["Close"].iloc[-1] < config.MIN_PRICE:
        return False
    if config.MIN_AVG_VOLUME is not None and last["Volume"].mean() < config.MIN_AVG_VOLUME:
        return False
    return True


def csv_tickers(csv_dir: str) -> list[str]:
    return sorted(f[:-4] for f in os.listdir(csv_dir) if f.endswith(".csv"))
