"""Recent South African market shocks: days in the last year when the rand or JSE Top 40 moved
more than 2.5x their normal daily move. Writes data/events/recent_sa_shocks.csv."""
import pandas as pd
import data
from fx_study import clean

rows = []
for name, sym, sign in [("Rand (up = stronger)", "USDZAR=X", -1), ("JSE Top 40", "STX40.JO", 1)]:
    for _, df in data.iter_daily([sym], "2y"):
        c = clean(df["Close"])
        r = sign * c.pct_change().dropna() * 100
        sd = r.rolling(250, min_periods=60).std().shift(1)
        z = (r / sd).dropna()
        recent = z[z.index >= z.index[-1] - pd.Timedelta(days=365)]
        for d in recent[recent.abs() >= 2.5].index:
            rows.append({"market": name, "date": d.date().isoformat(), "move_pct": round(r[d], 2),
                         "times_normal": round(abs(z[d]), 1), "last_data_day": z.index[-1].date().isoformat()})
out = pd.DataFrame(rows).sort_values("date", ascending=False)
out.to_csv("data/events/recent_sa_shocks.csv", index=False)
print(out.to_string())
