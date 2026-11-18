"""Scheduled shocks for the small-account pairs (AUD/NZD, NZD/CAD, AUD/CAD, NZD/USD, AUD/USD), hourly data ~2 years:
  1. How big is the move after each central-bank decision vs. the same hours on an ordinary day?
  2. News straddle grid (stop k x daily range, target m x stop, 24h max), with news-time spreads and stop slippage.
Outputs data/events/small_event_size.csv, small_straddle_trades.csv, small_straddle_grid.csv."""
import os
import numpy as np
import pandas as pd
from straddle import hourly, leg

OUT = os.path.join("data", "events")
SYMS = {"AUD/NZD": "AUDNZD=X", "NZD/CAD": "NZDCAD=X", "AUD/CAD": "AUDCAD=X", "NZD/USD": "NZDUSD=X", "AUD/USD": "AUDUSD=X"}
SPREAD = {"AUD/NZD": 0.04, "NZD/CAD": 0.06, "AUD/CAD": 0.04, "NZD/USD": 0.03, "AUD/USD": 0.025}   # % per leg at news time
POS_ZAR = {"AUD": 11426, "NZD": 9329}          # rand value of 0.01 lot (1,000 units), Nov 2026
KS, TPS = [0.25, 0.5, 0.75, 1.0], [1.0, 1.5, 2.0, 3.0]


def main():
    ev = pd.read_csv(os.path.join(OUT, "small_pair_events.csv"))
    data = {p: hourly(s) for p, s in SYMS.items()}
    size, trades = [], []
    for e in ev.itertuples():
        t = pd.Timestamp(e.time_utc, tz="UTC")
        start = t.floor("h")
        for pair in e.pairs.split(";"):
            df = data[pair]
            after = df[df.index >= start]
            if after.empty or (after.index[0] - start) > pd.Timedelta(hours=3) or df.index[0] > start - pd.Timedelta(days=30):
                continue
            entry = float(after["Open"].iloc[0])
            # size: 4-hour range after the decision vs. the 4-hour range starting at the same hour on the previous 20 weekdays
            w = after.iloc[:4]
            rng4 = (w["High"].max() - w["Low"].min()) / entry * 100
            same = []
            for k in range(1, 30):
                s0 = start - pd.Timedelta(days=k)
                if s0.weekday() >= 5:
                    continue
                ww = df[(df.index >= s0) & (df.index < s0 + pd.Timedelta(hours=4))]
                if len(ww) >= 3:
                    same.append((ww["High"].max() - ww["Low"].min()) / ww["Open"].iloc[0] * 100)
                if len(same) == 20:
                    break
            normal4 = float(np.median(same)) if same else np.nan
            c24 = after["Close"].iloc[min(23, len(after) - 1)]
            size.append({"time_utc": e.time_utc, "event": e.event, "outcome": e.outcome, "pair": pair,
                         "range_4h_pct": round(rng4, 3), "normal_4h_pct": round(normal4, 3),
                         "times_normal": round(rng4 / normal4, 2) if normal4 else np.nan,
                         "move_24h_pct": round((c24 / entry - 1) * 100, 3)})
            daily = df[df.index < start].resample("D").agg({"High": "max", "Low": "min", "Close": "last"}).dropna().tail(20)
            day_range = float(((daily["High"] - daily["Low"]) / daily["Close"]).median() * 100)
            bars = after.iloc[:24]
            notional = POS_ZAR[pair[:3]]
            for k in KS:
                for m in TPS:
                    stop, target = k * day_range, k * day_range * m
                    b, bo = leg(bars, entry, 1, stop, target, SPREAD[pair])
                    s, so = leg(bars, entry, -1, stop, target, SPREAD[pair])
                    kind = ("Both stopped (whipsaw)" if bo == so == "stop" else
                            "One hit target" if "target" in (bo, so) else "Neither target (closed at 24h)")
                    trades.append({"time_utc": e.time_utc, "event": e.event, "pair": pair, "stop_k": k, "tp_mult": m,
                                   "day_range_pct": round(day_range, 3), "stop_pips": None, "outcome": kind,
                                   "net_pct": round(b + s, 4), "net_zar_001": round((b + s) / 100 * notional, 2)})
    sz = pd.DataFrame(size)
    sz.to_csv(os.path.join(OUT, "small_event_size.csv"), index=False)
    tr = pd.DataFrame(trades)
    tr.to_csv(os.path.join(OUT, "small_straddle_trades.csv"), index=False)
    grid = []
    for (pair, event, k, m), d in tr.groupby(["pair", "event", "stop_k", "tp_mult"]):
        grid.append({"pair": pair, "event": event, "stop_k": k, "tp_mult": m, "straddles": len(d),
                     "whipsaw_pct": round((d.outcome == "Both stopped (whipsaw)").mean() * 100),
                     "target_pct": round((d.outcome == "One hit target").mean() * 100),
                     "avg_zar_001": round(d.net_zar_001.mean(), 2), "total_zar_001": round(d.net_zar_001.sum(), 1),
                     "worst_zar_001": round(d.net_zar_001.min(), 1),
                     "luck_t": round(d.net_zar_001.mean() / d.net_zar_001.std(ddof=1) * np.sqrt(len(d)), 2) if len(d) > 2 and d.net_zar_001.std() > 0 else np.nan})
    g = pd.DataFrame(grid)
    g.to_csv(os.path.join(OUT, "small_straddle_grid.csv"), index=False)
    pd.set_option("display.width", 250)
    print(sz.groupby(["event", "pair"]).times_normal.agg(["count", "median", "mean"]).round(2))
    print(g.sort_values("avg_zar_001", ascending=False).head(25).to_string())


if __name__ == "__main__":
    main()
