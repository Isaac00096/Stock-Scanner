"""
Trade simulation and statistics, shared by the validator.
"""

import math

import numpy as np
import pandas as pd

from setups import Setup


def simulate(ind: pd.DataFrame, signal: np.ndarray, setup: Setup, cost_pct: float) -> list[dict]:
    """
    Enter at the next day's open after each signal. Exit on stop, target, or
    after max_hold days. One open trade per setup per ticker at a time.
    If a bar touches both stop and target, the stop is assumed first (conservative).
    """
    o, h, l, c = (ind[k].to_numpy(float) for k in ("Open", "High", "Low", "Close"))
    atr = ind["ATR14"].to_numpy(float)
    dates = ind.index
    n = len(ind)
    is_long = setup.direction == "long"
    trades, next_free = [], 0

    for s in np.flatnonzero(signal):
        e = s + 1
        if s < next_free or e >= n:
            continue
        a, entry = atr[s], o[e]
        if not (np.isfinite(a) and a > 0 and np.isfinite(entry) and entry > 0):
            continue
        if is_long:
            stop, target = entry - setup.stop_atr * a, entry + setup.target_atr * a
        else:
            stop, target = entry + setup.stop_atr * a, entry - setup.target_atr * a

        last = e + setup.max_hold - 1
        if last >= n:
            break  # trade would still be open at the end of the data
        exit_px, reason, j = None, "time", last
        for j in range(e, last + 1):
            if is_long:
                if j > e and o[j] <= stop:
                    exit_px, reason = o[j], "stop"; break
                if l[j] <= stop:
                    exit_px, reason = stop, "stop"; break
                if j > e and o[j] >= target:
                    exit_px, reason = o[j], "target"; break
                if h[j] >= target:
                    exit_px, reason = target, "target"; break
            else:
                if j > e and o[j] >= stop:
                    exit_px, reason = o[j], "stop"; break
                if h[j] >= stop:
                    exit_px, reason = stop, "stop"; break
                if j > e and o[j] <= target:
                    exit_px, reason = o[j], "target"; break
                if l[j] <= target:
                    exit_px, reason = target, "target"; break
        if exit_px is None:
            exit_px, j = c[last], last

        ret = (exit_px / entry - 1) * 100 if is_long else (1 - exit_px / entry) * 100
        trades.append({"date": dates[s], "ret": ret - 2 * cost_pct, "reason": reason})
        next_free = j + 1
    return trades


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (math.nan, math.nan)
    p = k / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (100 * (center - half), 100 * (center + half))


def stats(returns: list[float]) -> dict:
    n = len(returns)
    if n == 0:
        return {"n": 0}
    r = np.asarray(returns, float)
    wins = int((r > 0).sum())
    gains, losses = r[r > 0].sum(), -r[r <= 0].sum()
    sd = r.std(ddof=1) if n > 1 else 0.0
    lo, hi = wilson(wins, n)
    return {
        "n": n,
        "win_rate": 100 * wins / n,
        "win_lo": lo,
        "win_hi": hi,
        "avg": float(r.mean()),
        "median": float(np.median(r)),
        "profit_factor": float(gains / losses) if losses > 0 else None,
        "tstat": float(r.mean() / (sd / math.sqrt(n))) if sd > 0 else 0.0,
        "sd": float(sd),
    }


def edge_tstat(sig: dict, base: dict) -> float:
    """How confidently the setup's average return beats random entries (Welch t-statistic)."""
    if not sig.get("n") or not base.get("n") or sig["n"] < 2 or base["n"] < 2:
        return 0.0
    se = math.sqrt(sig["sd"] ** 2 / sig["n"] + base["sd"] ** 2 / base["n"])
    return float((sig["avg"] - base["avg"]) / se) if se > 0 else 0.0
