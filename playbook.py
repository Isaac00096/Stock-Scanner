"""Political shock playbook: every event in data/events/playbook_events.csv measured across seven markets.
Writes data/events/playbook_moves.csv (event x market) and playbook_home.csv (the event's own currency)."""
import os
import numpy as np
import pandas as pd
import data
from fx_study import clean

OUT = os.path.join("data", "events")
MARKETS = {"Rand": ("USDZAR=X", -1), "JSE Top 40": ("STX40.JO", 1), "S&P 500": ("^GSPC", 1), "Gold": ("GC=F", 1),
           "EUR/USD": ("EURUSD=X", 1), "GBP/USD": ("GBPUSD=X", 1), "USD/JPY": ("JPY=X", 1)}
HOME = {"SA": [("Rand", 1)], "EU": [("EUR/USD", 1)], "UK": [("GBP/USD", 1)], "JP": [("USD/JPY", -1)],
        "US": [("EUR/USD", -1), ("GBP/USD", -1), ("USD/JPY", 1)], "Global": [("EUR/USD", -1), ("GBP/USD", -1), ("USD/JPY", 1)]}
HOME_CCY = {"SA": "Rand", "EU": "Euro", "UK": "Pound", "JP": "Yen", "US": "US dollar", "Global": "US dollar"}


def two_day(s, i):
    return ((1 + s.iloc[i] / 100) * (1 + s.iloc[i + 1] / 100) - 1) * 100


def main():
    r, normal = {}, {}
    for name, (sym, sign) in MARKETS.items():
        for _, df in data.iter_daily([sym], "max"):
            s = sign * clean(df["Close"]).pct_change().dropna() * 100
            r[name] = s
            normal[name] = (((1 + s / 100) * (1 + s.shift(-1) / 100) - 1) * 100).abs().mean()
    ev = pd.read_csv(os.path.join(OUT, "playbook_events.csv"), parse_dates=["date"])
    moves, home = [], []
    for e in ev.itertuples():
        got = {}
        for m, s in r.items():
            i = s.index.searchsorted(e.date)
            if i + 1 >= len(s):
                continue
            d0 = two_day(s, i)
            seg = s.iloc[i + 2:i + 22]
            n20 = ((1 + seg / 100).prod() - 1) * 100 if len(seg) == 20 else np.nan
            got[m] = (d0, n20)
            moves.append({"date": e.date.date().isoformat(), "name": e.name, "type": e.type, "country": e.country, "market": m,
                          "move_2d": round(d0, 3), "next20": round(n20, 3) if n20 == n20 else np.nan,
                          "times_normal": round(abs(d0) / normal[m], 2)})
        legs = [(got[m][0] * sg, got[m][1] * sg) for m, sg in HOME[e.country] if m in got]
        if legs:
            d0 = float(np.mean([a for a, _ in legs]))
            n20 = [b for _, b in legs if b == b]
            n20 = float(np.mean(n20)) if n20 else np.nan
            want = {"Stronger": 1, "Weaker": -1}.get(e.expected, 0)
            home.append({"date": e.date.date().isoformat(), "name": e.name, "type": e.type, "country": e.country,
                         "currency": HOME_CCY[e.country], "expected": e.expected, "ccy_2d": round(d0, 3),
                         "ccy_next20": round(n20, 3) if n20 == n20 else np.nan,
                         "as_expected": "" if not want else ("Yes" if want * d0 > 0.2 else ("No" if want * d0 < -0.2 else "Flat")),
                         "lasted_20d": "" if n20 != n20 or abs(d0) < 0.2 else ("Kept going" if np.sign(n20) == np.sign(d0) else "Reversed")})
    pd.DataFrame(moves).to_csv(os.path.join(OUT, "playbook_moves.csv"), index=False)
    h = pd.DataFrame(home)
    h.to_csv(os.path.join(OUT, "playbook_home.csv"), index=False)
    m = pd.DataFrame(moves)
    print(m.pivot_table(index="type", columns="market", values="times_normal", aggfunc="mean").round(2).to_string())
    print(h.groupby("type").as_expected.value_counts().unstack(fill_value=0))
    print(h.groupby("type").lasted_20d.value_counts().unstack(fill_value=0))


if __name__ == "__main__":
    main()
