"""Major currency pairs and the politics of both countries in each pair.
  1. Politics first: how EUR/USD, GBP/USD and USD/JPY moved after each event in data/events/events_fx.csv
     (2-day reaction, then 5 and 20 trading days), and whether the currency went the way a textbook expects.
  2. Market first: each pair's 20 biggest one-day moves since 2015 (one per week), for tracing their causes.
Outputs data/events/fx_events.csv, fx_wild.csv, fx_biggest.csv."""
import os
import numpy as np
import pandas as pd
import data

OUT = os.path.join("data", "events")
PAIRS = {"EUR/USD": "EURUSD=X", "GBP/USD": "GBPUSD=X", "USD/JPY": "JPY=X"}
# which currency in each pair belongs to each country, and the sign that turns the pair move into that currency's strength
SIDE = {("EU", "EUR/USD"): ("EUR", 1), ("UK", "GBP/USD"): ("GBP", 1), ("JP", "USD/JPY"): ("JPY", -1),
        ("US", "EUR/USD"): ("USD", -1), ("US", "GBP/USD"): ("USD", -1), ("US", "USD/JPY"): ("USD", 1)}


def clean(c):
    c = c[c.index >= "2015-01-01"].dropna()
    nb = (c.shift(1) + c.shift(-1)) / 2
    bad = ((c / nb - 1).abs() > 0.04) & ((c / c.shift(1) - 1).abs() > 0.04) & ((c / c.shift(-1) - 1).abs() > 0.04)
    c = c[~bad]
    return c[c.pct_change().abs().fillna(0) < 0.15]


def main():
    r = {}
    for name, sym in PAIRS.items():
        for _, df in data.iter_daily([sym], "max"):
            r[name] = clean(df["Close"]).pct_change().dropna() * 100
    ev = pd.read_csv(os.path.join(OUT, "events_fx.csv"), parse_dates=["date"])
    rows = []
    for e in ev.itertuples():
        country = "US" if e.country == "Global" else e.country
        for pair, s in r.items():
            if (country, pair) not in SIDE:
                continue
            ccy, sign = SIDE[(country, pair)]
            i = s.index.searchsorted(e.date)
            if i + 22 >= len(s) and i + 2 > len(s):
                continue
            if i + 1 >= len(s):
                continue
            day0 = ((1 + s.iloc[i] / 100) * (1 + s.iloc[i + 1] / 100) - 1) * 100
            rec = {"date": e.date.date().isoformat(), "country": e.country, "kind": e.kind, "name": e.name,
                   "expected": f"{e.expected} {ccy}", "pair": pair, "currency": ccy,
                   "pair_move": round(day0, 3), "ccy_move": round(sign * day0, 3)}
            for h in (5, 20):
                seg = s.iloc[i + 2:i + 2 + h]
                rec[f"ccy_next{h}"] = round(sign * (((1 + seg / 100).prod() - 1) * 100), 3) if len(seg) == h else np.nan
            want = 1 if e.expected == "Stronger" else -1
            rec["went_as_expected"] = "Yes" if want * rec["ccy_move"] > 0.2 else ("No" if want * rec["ccy_move"] < -0.2 else "Flat")
            rows.append(rec)
    ef = pd.DataFrame(rows)
    ef.to_csv(os.path.join(OUT, "fx_events.csv"), index=False)
    wild = []
    for pair, s in r.items():
        two = ((1 + s / 100) * (1 + s.shift(-1) / 100) - 1) * 100
        normal = two.abs().mean()
        wild.append({"pair": pair, "group": "Normal day", "events": int(two.notna().sum()), "times_normal": 1.0})
        for (c, k), g in ef[ef.pair == pair].groupby(["country", "kind"]):
            wild.append({"pair": pair, "group": f"{c}: {k}", "events": len(g), "times_normal": round(g["pair_move"].abs().mean() / normal, 2)})
    pd.DataFrame(wild).to_csv(os.path.join(OUT, "fx_wild.csv"), index=False)
    big = []
    for pair, s in r.items():
        sd = s.rolling(250, min_periods=60).std().shift(1)
        picked = []
        for d in s.abs().sort_values(ascending=False).index:
            if any(abs((d - p).days) <= 7 for p in picked):
                continue
            picked.append(d)
            if len(picked) == 20:
                break
        for d in picked:
            big.append({"pair": pair, "date": d.date().isoformat(), "move_pct": round(s[d], 2),
                        "prev_day_pct": round(s.shift(1)[d], 2), "next_day_pct": round(s.shift(-1).get(d, np.nan), 2),
                        "times_normal": round(abs(s[d]) / sd[d], 1) if sd.get(d, 0) > 0 else np.nan})
    pd.DataFrame(big).sort_values(["pair", "date"]).to_csv(os.path.join(OUT, "fx_biggest.csv"), index=False)
    print(ef.groupby(["pair", "country"])["went_as_expected"].value_counts().unstack(fill_value=0))
    print(pd.DataFrame(big).sort_values(["pair", "date"]).to_string())


if __name__ == "__main__":
    main()
