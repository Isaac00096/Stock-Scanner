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


def rsi_parts(close: pd.Series, n: int) -> tuple[pd.Series, pd.Series]:
    """Wilder average gain and average loss (the two halves of RSI)."""
    d = close.diff()
    gain = d.clip(lower=0).ewm(alpha=1 / n, min_periods=n, adjust=False).mean()
    loss = (-d.clip(upper=0)).ewm(alpha=1 / n, min_periods=n, adjust=False).mean()
    return gain, loss


def fib_swing(df: pd.DataFrame, atr_s: pd.Series, window: int = 60, min_bars: int = 5,
              max_age: int = 20, min_atr: float = 3.0) -> pd.DataFrame:
    """
    Objective up-swing for Fibonacci levels, measured at each day's close:
      swing high = highest high of the last `window` days,
      swing low  = lowest low before that high (inside the window).
    Valid only if the low came at least `min_bars` before the high, the high is
    at most `max_age` days old, and the swing spans at least `min_atr` ATRs.
    """
    hi_a, lo_a = df["High"].to_numpy(float), df["Low"].to_numpy(float)
    n = len(df)
    out = {k: np.full(n, np.nan) for k in ("SW_HI", "SW_LO")}
    if n >= window:
        from numpy.lib.stride_tricks import sliding_window_view
        H = sliding_window_view(hi_a, window)
        Lw = sliding_window_view(lo_a, window).copy()
        hi_idx = H.argmax(axis=1)
        cols = np.arange(window)
        Lw[cols[None, :] > hi_idx[:, None]] = np.inf      # only lows before the high
        lo_idx = Lw.argmin(axis=1)
        rows = np.arange(len(H))
        sw_hi, sw_lo = H[rows, hi_idx], Lw[rows, lo_idx]
        t = rows + window - 1
        a = atr_s.to_numpy(float)[t]
        ok = ((hi_idx - lo_idx) >= min_bars) & ((window - 1 - hi_idx) <= max_age) & \
             np.isfinite(a) & ((sw_hi - sw_lo) >= min_atr * a)
        out["SW_HI"][t[ok]] = sw_hi[ok]
        out["SW_LO"][t[ok]] = sw_lo[ok]
    res = pd.DataFrame(out, index=df.index)
    rng = res["SW_HI"] - res["SW_LO"]
    for p in (0.5, 0.618, 0.786):
        res[f"FIB_{int(p * 1000)}"] = res["SW_HI"] - p * rng
    return res


def gartley_222(df: pd.DataFrame, atr_s: pd.Series, rally_max_age: int = 15,
                rally_window: int = 30, decline_window: int = 80,
                min_decline: float = 0.12, min_decline_bars: int = 10) -> pd.DataFrame:
    """
    Gartley's "one of the best trading opportunities" (Profits in the Stock Market, Ch. VIII),
    detected objectively at each close t:
      C = highest high of the last `rally_max_age` days (top of the minor rally),
      B = lowest low in the `rally_window` days before C (end of the decline),
      A = highest high in the `decline_window` days before B (start of the decline).
    Conditions: decline A->B of at least `min_decline` lasting `min_decline_bars`+ days;
    volume dried up into B (10 days before B quieter than the decline overall);
    rally B->C on expanding volume (louder than the 10 days before B), at least 2 ATR,
    and C still below A (a minor rally, not a new trend);
    since C, a pullback on lighter volume than the rally.
    Returns B, C and the 1/3 and 1/2 retracement levels of the B->C rally (NaN where no pattern).
    """
    H, L, V = (df[k].to_numpy(float) for k in ("High", "Low", "Volume"))
    a = atr_s.to_numpy(float)
    n = len(df)
    outB, outC = np.full(n, np.nan), np.full(n, np.nan)
    start = decline_window + rally_window + rally_max_age
    for t in range(start, n):
        c0 = t - rally_max_age + 1
        ci = c0 + int(np.argmax(H[c0:t + 1]))
        if ci >= t:                                   # need at least one pullback day after C
            continue
        b0 = ci - rally_window
        bi = b0 + int(np.argmin(L[b0:ci]))
        if ci - bi < 3:
            continue
        a0 = bi - decline_window
        ai = a0 + int(np.argmax(H[a0:bi]))
        A, B, C = H[ai], L[bi], H[ci]
        if not (np.isfinite(a[t]) and a[t] > 0):
            continue
        if (A - B) / A < min_decline or bi - ai < min_decline_bars:
            continue
        if not (C < A and C - B >= 2 * a[t]):
            continue
        v_decline = V[ai:bi + 1].mean()
        v_pre_b = V[max(ai, bi - 9):bi + 1].mean()
        v_rally = V[bi + 1:ci + 1].mean()
        v_pull = V[ci + 1:t + 1].mean()
        if not (v_pre_b < v_decline and v_rally > v_pre_b and v_pull < v_rally):
            continue
        outB[t], outC[t] = B, C
    res = pd.DataFrame({"G_B": outB, "G_C": outC}, index=df.index)
    rally = res["G_C"] - res["G_B"]
    res["G_R33"] = res["G_C"] - rally / 3
    res["G_R50"] = res["G_C"] - rally / 2
    return res


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    prev = df["Close"].shift()
    tr = pd.concat([df["High"] - df["Low"], (df["High"] - prev).abs(), (df["Low"] - prev).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, min_periods=n, adjust=False).mean()


def compute_all(df: pd.DataFrame, market: pd.Series | None = None) -> pd.DataFrame:
    d = df.copy()
    c = d["Close"]
    d["SMA20"] = c.rolling(20).mean()
    d["SMA50"] = c.rolling(50).mean()
    d["SMA200"] = c.rolling(200).mean()
    d["RSI14"] = rsi(c, 14)
    d["RSI2"] = rsi(c, 2)
    d["RSI2_G"], d["RSI2_L"] = rsi_parts(c, 2)
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
    d = d.join(fib_swing(d, d["ATR14"]))
    d = d.join(gartley_222(d, d["ATR14"]))
    # Gartley's tested intermediate-trend average: 25-day SMA plotted 3 days ahead ("lead")
    d["SMA25_LEAD3"] = c.rolling(25).mean().shift(3)
    # previous intermediate top: highest high from ~6 months ago up to a week ago
    d["PRIOR_TOP"] = d["High"].rolling(125).max().shift(6)
    # "better-than-market": 3-month return vs the market (S&P 500 via SPY)
    if market is not None and len(market):
        mkt = market.reindex(d.index).ffill()
        d["RS63"] = c / c.shift(63) - mkt / mkt.shift(63)
    else:
        d["RS63"] = np.nan
    return d
