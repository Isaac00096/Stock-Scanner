"""Cross pairs (no US dollar) vs politics: same events as fx_study.py.
Outputs data/events/minors_events.csv, minors_wild.csv, minors_biggest.csv."""
import os
import numpy as np
import pandas as pd
import data
from fx_study import clean

OUT = os.path.join("data", "events")
PAIRS = {"EUR/GBP": "EURGBP=X", "GBP/JPY": "GBPJPY=X", "EUR/JPY": "EURJPY=X", "AUD/NZD": "AUDNZD=X", "NZD/CAD": "NZDCAD=X"}
# (country, pair) -> (currency, sign turning the pair move into that currency's strength)
SIDE = {("EU", "EUR/GBP"): ("EUR", 1), ("UK", "EUR/GBP"): ("GBP", -1), ("UK", "GBP/JPY"): ("GBP", 1),
        ("JP", "GBP/JPY"): ("JPY", -1), ("EU", "EUR/JPY"): ("EUR", 1), ("JP", "EUR/JPY"): ("JPY", -1)}


def main():
    r = {}
    for name, sym in PAIRS.items():
        for _, df in data.iter_daily([sym], "max"):
            r[name] = clean(df["Close"]).pct_change().dropna() * 100
    ev = pd.read_csv(os.path.join(OUT, "events_fx.csv"), parse_dates=["date"])
    rows = []
    for e in ev.itertuples():
        for pair, s in r.items():
            i = s.index.searchsorted(e.date)
            if i + 1 >= len(s):
                continue
            day0 = ((1 + s.iloc[i] / 100) * (1 + s.iloc[i + 1] / 100) - 1) * 100
            seg = s.iloc[i + 2:i + 22]
            n20 = ((1 + seg / 100).prod() - 1) * 100 if len(seg) == 20 else np.nan
            rec = {"date": e.date.date().isoformat(), "country": e.country, "kind": e.kind, "name": e.name, "pair": pair,
                   "pair_move": round(day0, 3), "pair_next20": round(n20, 3), "currency": "", "ccy_move": np.nan, "went_as_expected": ""}
            if (e.country, pair) in SIDE:
                ccy, sign = SIDE[(e.country, pair)]
                want = 1 if e.expected == "Stronger" else -1
                rec.update({"currency": ccy, "ccy_move": round(sign * day0, 3),
                            "went_as_expected": "Yes" if want * sign * day0 > 0.2 else ("No" if want * sign * day0 < -0.2 else "Flat")})
            rows.append(rec)
    ef = pd.DataFrame(rows)
    ef.to_csv(os.path.join(OUT, "minors_events.csv"), index=False)
    wild = []
    for pair, s in r.items():
        two = ((1 + s / 100) * (1 + s.shift(-1) / 100) - 1) * 100
        normal = two.abs().mean()
        g = ef[ef.pair == pair].copy()
        g["who"] = np.where(g.country.isin(["US", "Global"]), "US & global events", g.country + " events")
        wild.append({"pair": pair, "group": "Normal day", "events": int(two.notna().sum()), "avg_2day_pct": round(normal, 3), "times_normal": 1.0})
        for who, gg in g.groupby("who"):
            wild.append({"pair": pair, "group": who, "events": len(gg), "avg_2day_pct": round(gg.pair_move.abs().mean(), 3),
                         "times_normal": round(gg.pair_move.abs().mean() / normal, 2)})
    pd.DataFrame(wild).to_csv(os.path.join(OUT, "minors_wild.csv"), index=False)
    big = []
    for pair, s in r.items():
        picked = []
        for d in s.abs().sort_values(ascending=False).index:
            if any(abs((d - p).days) <= 7 for p in picked):
                continue
            picked.append(d)
            if len(picked) == 12:
                break
        for d in picked:
            big.append({"pair": pair, "data_date": d.date().isoformat(), "move_pct": round(s[d], 2)})
    pd.DataFrame(big).sort_values(["pair", "data_date"]).to_csv(os.path.join(OUT, "minors_biggest.csv"), index=False)
    print(pd.DataFrame(wild).to_string())
    print(ef[ef.currency != ""].groupby(["pair", "country"]).went_as_expected.value_counts().unstack(fill_value=0))
    print(pd.DataFrame(big).sort_values(["pair", "data_date"]).to_string())


if __name__ == "__main__":
    main()
