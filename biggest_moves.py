"""Finds the biggest market moves since 2015 (rand, gold, S&P 500, JSE Top 40) so their causes can be traced.
Writes data/events/biggest_moves.csv: the largest daily moves per market, one per 5-day cluster."""
import os
import numpy as np
import pandas as pd
import data

MARKETS = {"Rand (up = stronger)": ("USDZAR=X", -1), "Gold": ("GC=F", 1),
           "S&P 500": ("^GSPC", 1), "JSE Top 40": ("STX40.JO", 1)}
TOP = 20

rows = []
for name, (sym, sign) in MARKETS.items():
    for _, df in data.iter_daily([sym], "max"):
        c = df["Close"].dropna()
        c = c[c.index >= "2015-01-01"]
        # drop bad ticks: a price far from both neighbours that snaps straight back
        nb = (c.shift(1) + c.shift(-1)) / 2
        bad = ((c / nb - 1).abs() > 0.06) & ((c / c.shift(1) - 1).abs() > 0.06) & ((c / c.shift(-1) - 1).abs() > 0.06)
        c = c[~bad]
        c = c[c.pct_change().abs().fillna(0) < 0.25]
        r = sign * c.pct_change().dropna() * 100
        sd = r.rolling(250, min_periods=60).std().shift(1)
        z = (r / sd).dropna()
        picked = []
        for d in r.abs().sort_values(ascending=False).index:
            if any(abs((d - p).days) <= 7 for p in picked):
                continue
            picked.append(d)
            if len(picked) == TOP:
                break
        for d in picked:
            rows.append({"market": name, "date": d.date().isoformat(), "move_pct": round(r[d], 2),
                         "times_normal": round(abs(r[d]) / sd[d], 1) if d in sd.index and sd[d] > 0 else np.nan})
os.makedirs("data/events", exist_ok=True)
pd.DataFrame(rows).sort_values(["market", "date"]).to_csv("data/events/biggest_moves.csv", index=False)
print(pd.DataFrame(rows).to_string())
