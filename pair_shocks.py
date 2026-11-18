"""Biggest one-day moves since 2015 (one per week) for the small-account pairs, so each can be traced to a cause.
Writes data/events/pair_shocks.csv. Yahoo currency data is dated one trading day late, so news_day = previous weekday."""
import pandas as pd
import data
from fx_study import clean

PAIRS = {"AUD/NZD": "AUDNZD=X", "NZD/CAD": "NZDCAD=X", "AUD/CAD": "AUDCAD=X", "NZD/USD": "NZDUSD=X", "AUD/USD": "AUDUSD=X"}
rows = []
for pair, sym in PAIRS.items():
    for _, df in data.iter_daily([sym], "max"):
        s = clean(df["Close"]).pct_change().dropna() * 100
        sd = s.rolling(250, min_periods=60).std().shift(1)
        picked = []
        for d in s.abs().sort_values(ascending=False).index:
            if any(abs((d - p).days) <= 7 for p in picked):
                continue
            picked.append(d)
            if len(picked) == 15:
                break
        for d in picked:
            rows.append({"pair": pair, "data_date": d.date().isoformat(),
                         "news_day": (d - pd.offsets.BDay(1)).date().isoformat(), "move_pct": round(s[d], 2),
                         "times_normal": round(abs(s[d]) / sd[d], 1) if sd.get(d, 0) > 0 else None})
out = pd.DataFrame(rows).sort_values(["pair", "data_date"])
out.to_csv("data/events/pair_shocks.csv", index=False)
print(out.to_string())
