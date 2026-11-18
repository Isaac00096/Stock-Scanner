"""Which Trade Nation currency pairs fit a small account at size 0.01 (1,000 units of the first currency)?
For each pair: rand value of the position, rand value of one pip, the normal daily range, and what a stop of
half a day's range and a full day's range would cost in rand. Writes data/events/fx_afford.csv."""
import numpy as np
import pandas as pd
import data
from fx_study import clean

inst = data.instruments()
fx = inst[inst["market"] == "forex"]
ccys = sorted({s[:3] for s in fx["tn_symbol"]} | {s[3:6] for s in fx["tn_symbol"]})
to_zar = {"ZAR": 1.0}
for c in ccys:
    if c == "ZAR":
        continue
    for _, df in data.iter_daily([f"{c}ZAR=X"], "1mo"):
        if not df.empty:
            to_zar[c] = float(df["Close"].dropna().iloc[-1])
rows = []
for r in fx.itertuples():
    base, quote = r.tn_symbol[:3], r.tn_symbol[3:6]
    for _, df in data.iter_daily([r.yahoo], "1y"):
        if df.empty or base not in to_zar or quote not in to_zar:
            continue
        d = df.dropna().tail(60)
        rng = float(((d["High"] - d["Low"]) / d["Close"]).median() * 100)
        price = float(d["Close"].iloc[-1])
        pip = 0.01 if quote == "JPY" else 0.0001
        notional = 1000 * to_zar[base]
        pip_zar = 1000 * pip * to_zar[quote]
        rows.append({"pair": f"{base}/{quote}", "price": round(price, 5), "position_zar_001": round(notional),
                     "pip_value_zar_001": round(pip_zar, 2), "day_range_pct": round(rng, 2),
                     "day_range_pips": round(rng / 100 * price / pip),
                     "stop_half_day_zar": round(notional * rng / 100 / 2, 1),
                     "stop_full_day_zar": round(notional * rng / 100, 1),
                     "margin_zar_1to30": round(notional / 30), "margin_zar_1to200": round(notional / 200)})
out = pd.DataFrame(rows).sort_values("stop_full_day_zar")
out.to_csv("data/events/fx_afford.csv", index=False)
pd.set_option("display.width", 250)
print(out.to_string())
