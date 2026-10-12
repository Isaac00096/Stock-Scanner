"""
Trade simulation and statistics, shared by the validator.
"""

import math

import numpy as np
import pandas as pd

from setups import Setup


def simulate(ind: pd.DataFrame, signal: np.ndarray, setup: Setup, cost_pct: float,
             levels: pd.DataFrame | None = None, exit_mask: np.ndarray | None = None) -> list[dict]:
    """
    Simulates one setup on one ticker. One open trade at a time.

    Entry (decided at the close of signal day s, executed on day e = s + 1):
      - market setups: buy at day e's open.
      - limit setups (levels["limit"] set): a day order at the limit price. Filled only if
        day e trades through it (low <= limit for longs), at the limit, or at the open if
        the stock opens beyond it. Unfilled orders simply expire.
    Exits: stop, target, or the close of the max_hold-th day.
      Stop/target come from levels["stop"]/["target"] when given, otherwise ATR multiples
      around the fill price.
    Conservative assumptions: if a bar touches both stop and target, the stop counts;
    on a limit order's fill day the target is ignored (the high may have come before the fill).
    """
    o, h, l, c = (ind[k].to_numpy(float) for k in ("Open", "High", "Low", "Close"))
    atr = ind["ATR14"].to_numpy(float)
    lim = levels["limit"].to_numpy(float) if levels is not None and "limit" in levels else None
    lv_stop = levels["stop"].to_numpy(float) if levels is not None and "stop" in levels else None
    lv_tgt = levels["target"].to_numpy(float) if levels is not None and "target" in levels else None
    dates = ind.index
    n = len(ind)
    is_long = setup.direction == "long"
    trades, next_free = [], 0

    for s in np.flatnonzero(signal):
        e = s + 1
        if s < next_free or e >= n:
            continue
        a = atr[s]
        if not (np.isfinite(a) and a > 0 and np.isfinite(o[e]) and o[e] > 0):
            continue

        limit_fill = lim is not None
        if limit_fill:
            L = lim[s]
            if not (np.isfinite(L) and L > 0):
                continue
            if is_long:
                if l[e] > L:
                    continue                      # never traded down to the limit: no fill
                entry = min(o[e], L)
            else:
                if h[e] < L:
                    continue
                entry = max(o[e], L)
        else:
            entry = o[e]

        sgn = 1 if is_long else -1
        if lv_stop is not None and np.isfinite(lv_stop[s]):
            stop = lv_stop[s]
        elif setup.stop_pct is not None:
            stop = entry * (1 - sgn * setup.stop_pct)
        else:
            stop = entry - sgn * setup.stop_atr * a
        if lv_tgt is not None and np.isfinite(lv_tgt[s]):
            target = lv_tgt[s]
        elif setup.target_pct is not None:
            target = entry * (1 + sgn * setup.target_pct)
        else:
            target = entry + sgn * setup.target_atr * a

        last = e + setup.max_hold - 1
        if last >= n:
            break  # trade would still be open at the end of the data
        exit_px, reason, j = None, "time", last
        # filled already beyond the stop (e.g. a gap): out at the fill price
        if (is_long and entry <= stop) or (not is_long and entry >= stop):
            exit_px, reason, j = entry, "stop", e
        else:
            for j in range(e, last + 1):
                first = j == e
                tgt_ok = not (first and limit_fill)
                if is_long:
                    if not first and o[j] <= stop:
                        exit_px, reason = o[j], "stop"; break
                    if l[j] <= stop:
                        exit_px, reason = stop, "stop"; break
                    if not first and o[j] >= target:
                        exit_px, reason = o[j], "target"; break
                    if tgt_ok and h[j] >= target:
                        exit_px, reason = target, "target"; break
                else:
                    if not first and o[j] >= stop:
                        exit_px, reason = o[j], "stop"; break
                    if h[j] >= stop:
                        exit_px, reason = stop, "stop"; break
                    if not first and o[j] <= target:
                        exit_px, reason = o[j], "target"; break
                    if tgt_ok and l[j] <= target:
                        exit_px, reason = target, "target"; break
                # rule-based exit decided at this close, executed at the next open
                if exit_mask is not None and exit_mask[j] and j < last:
                    exit_px, reason, j = o[j + 1], "exit rule", j + 1
                    break
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
