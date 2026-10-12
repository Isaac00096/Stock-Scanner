"""
Indicator calculations on a daily OHLCV DataFrame (pure pandas/numpy).
"""

import numpy as np
import pandas as pd


def rsi(close: pd.Series, n: int) -> pd.Series:
    d = close.diff()
    gain = d.clip(lower=0).ewm(alpha=1 / n, min_periods=n, adjust=False).mean()
    loss = (-d.clip(upper=0)).ewm(alpha=1 / n, min_periods=n, adjust=False).mean()
    out = 100 - 100 / (1 + gain / loss.replace(0, np.nan))
    return out.where(loss != 0, 100.0)


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    prev = df["Close"].shift()
    tr = pd.concat([df["High"] - df["Low"], (df["High"] - prev).abs(), (df["Low"] - prev).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, min_periods=n, adjust=False).mean()


def compute_all(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    c = d["Close"]
    d["SMA20"] = c.rolling(20).mean()
    d["SMA50"] = c.rolling(50).mean()
    d["SMA200"] = c.rolling(200).mean()
    d["RSI14"] = rsi(c, 14)
    d["RSI2"] = rsi(c, 2)
    ema12, ema26 = c.ewm(span=12, adjust=False).mean(), c.ewm(span=26, adjust=False).mean()
    d["MACD"] = ema12 - ema26
    d["MACD_signal"] = d["MACD"].ewm(span=9, adjust=False).mean()
    std20 = c.rolling(20).std()
    d["BB_UP"] = d["SMA20"] + 2 * std20
    d["BB_LO"] = d["SMA20"] - 2 * std20
    d["ATR14"] = atr(d, 14)
    # prior-20-day references (shifted so today is compared to the days BEFORE it)
    d["VOL_AVG20"] = d["Volume"].rolling(20).mean().shift(1)
    d["HIGH_20"] = d["High"].rolling(20).max().shift(1)
    d["LOW_20"] = d["Low"].rolling(20).min().shift(1)
    return d
