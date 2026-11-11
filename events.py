"""
Event study: how political and policy announcements move the rand and gold, and whether the
scanner's passed strategies do worse when a trade is held through one.

Inputs:  data/events/events.csv  (date, kind, group, outcome, name)
Outputs: data/events/*.csv       (tables used by the strategy report page)

Tests
  1. Ripple after rate decisions: does the decision day's move continue or reverse over 1, 5, 20 days?
  2. Passed strategies: trades held through an event vs trades that weren't.
  3. Big political shocks: move on the day and over the next 5 and 20 days.
  4. How wild event days are: average size of the daily move on event days vs all days.

    python events.py
"""

import json
import os

import numpy as np
import pandas as pd

import config
import data
import engine
import indicators
from setups import SETUPS, exit_mask, levels, signals

OUT = os.path.join("data", "events")
SA_SHOCKS = {"SA finance minister Nene fired", "Pravin Gordhan reappointed finance minister",
             "SA finance minister Gordhan fired", "S&P cuts SA to junk", "Ramaphosa elected ANC leader",
             "Zuma resigns as SA president", "Moody's cuts SA to junk", "US says SA supplied arms to Russia",
             "SA unity government formed", "SA budget postponed (VAT row)"}
ASSETS = {"rand": ("USDZAR=X", -1, "Rand vs US dollar (up = rand stronger)"),
          "gold": ("GC=F", 1, "Gold (US$)"),
          "spx": ("^GSPC", 1, "S&P 500"),
          "jse": ("STX40.JO", 1, "JSE Top 40")}
HORIZONS = [1, 5, 20]


def load_events():
    ev = pd.read_csv(os.path.join(OUT, "events.csv"), parse_dates=["date"])
    ev["outcome"] = ev["outcome"].fillna("")
    sa = ev["kind"].str.startswith("SA") | ev["name"].str.startswith("SA") | ev["name"].isin(SA_SHOCKS)
    ev["region"] = np.where(sa, "SA", "US/global")
    return ev


def series():
    out = {}
    for key, (sym, sign, _) in ASSETS.items():
        for t, df in data.iter_daily([sym], "max"):
            c = df["Close"].dropna()
            c = c[c.index >= "2015-01-01"]
            nb = (c.shift(1) + c.shift(-1)) / 2      # drop bad ticks that snap straight back
            bad = ((c / nb - 1).abs() > 0.06) & ((c / c.shift(1) - 1).abs() > 0.06) & ((c / c.shift(-1) - 1).abs() > 0.06)
            c = c[~bad]
            c = c[c.pct_change().abs().fillna(0) < 0.25]
            out[key] = sign * c.pct_change() * 100     # daily % move, rand flipped so up = stronger
    return out


def day_index(r, d):
    i = r.index.searchsorted(d)
    return i if i < len(r) else None


def event_moves(r, ev):
    rows = []
    for e in ev.itertuples():
        i = day_index(r, e.date)
        if i is None or i < 1 or i + 1 >= len(r) or np.isnan(r.iloc[i]):
            continue
        # reaction = event day + the next day (free FX data is sometimes dated a day late)
        day0 = ((1 + r.iloc[i] / 100) * (1 + np.nan_to_num(r.iloc[i + 1]) / 100) - 1) * 100
        rec = {"date": e.date.date().isoformat(), "kind": e.kind, "outcome": e.outcome, "name": e.name,
               "region": e.region, "day0": day0}
        for h in HORIZONS:
            seg = r.iloc[i + 2:i + 2 + h]
            rec[f"next{h}"] = ((1 + seg / 100).prod() - 1) * 100 if len(seg) == h else np.nan
        rows.append(rec)
    return pd.DataFrame(rows)


def continuation(df):
    """Share of events where the next-k-day move went the same way as the decision-day move."""
    res = {"events": len(df)}
    for h in HORIZONS:
        a = np.sign(df["day0"]) * df[f"next{h}"]
        a = a.dropna()
        res[f"cont{h}_pct"] = (a > 0).mean() * 100 if len(a) else np.nan
        res[f"aligned{h}_avg"] = a.mean() if len(a) else np.nan
    return res


def all_days_baseline(r):
    rows = []
    v = r.dropna()
    for i in range(1, len(v) - 23):
        rec = {"day0": ((1 + v.iloc[i] / 100) * (1 + v.iloc[i + 1] / 100) - 1) * 100}
        for h in HORIZONS:
            seg = v.iloc[i + 2:i + 2 + h]
            rec[f"next{h}"] = ((1 + seg / 100).prod() - 1) * 100
        rows.append(rec)
    return pd.DataFrame(rows)


def tests_1_3_4(ev):
    rs = series()
    ripple, shocks, wild = [], [], []
    for key, r in rs.items():
        label = ASSETS[key][2]
        mv = event_moves(r, ev)
        base = all_days_baseline(r)
        b = continuation(base)
        ripple.append({"asset": label, "group": "Any normal day (baseline)", "outcome": "", **b})
        for kind in ("US Fed rate decision", "SA Reserve Bank rate decision"):
            k = mv[mv["kind"] == kind]
            ripple.append({"asset": label, "group": kind, "outcome": "all", **continuation(k)})
            for o in ("hike", "cut", "hold"):
                ko = k[k["outcome"] == o]
                rec = {"asset": label, "group": kind, "outcome": o, **continuation(ko)}
                rec["day0_avg"] = ko["day0"].mean()
                rec["next20_avg"] = ko["next20"].mean()
                ripple.append(rec)
        sh = mv[mv["kind"] == "Political shock"].copy()
        sh["asset"] = label
        shocks.append(sh)
        absall = base["day0"].abs().mean()      # 2-day move on any day, same window as events
        wild.append({"asset": label, "kind": "Normal day (all days)", "events": len(base),
                     "avg_size_pct": absall, "times_normal": 1.0})
        for kind, g in mv.groupby("kind"):
            wild.append({"asset": label, "kind": kind, "events": len(g), "avg_size_pct": g["day0"].abs().mean(),
                         "times_normal": g["day0"].abs().mean() / absall})
    pd.DataFrame(ripple).round(3).to_csv(os.path.join(OUT, "ripple.csv"), index=False)
    pd.concat(shocks).round(3).to_csv(os.path.join(OUT, "shocks.csv"), index=False)
    pd.DataFrame(wild).round(3).to_csv(os.path.join(OUT, "wild.csv"), index=False)


def welch_t(a, b):
    if len(a) < 2 or len(b) < 2:
        return np.nan
    return (a.mean() - b.mean()) / np.sqrt(a.var(ddof=1) / len(a) + b.var(ddof=1) / len(b))


def test_2(ev):
    v = json.load(open(os.path.join(config.OUTPUT_DIR, config.SETUPS_JSON)))
    by_name = {s.name: s for s in SETUPS}
    groups = {
        "US Fed decision": ev[ev["kind"] == "US Fed rate decision"]["date"],
        "SA Reserve Bank decision": ev[ev["kind"] == "SA Reserve Bank rate decision"]["date"],
        "Election or SA budget": ev[ev["kind"].isin(["Election", "SA national budget"])]["date"],
        "Political shock": ev[ev["kind"] == "Political shock"]["date"],
    }
    allev = pd.concat(groups.values())
    rows = []
    for m in ("us", "jse", "uk", "eu"):
        passed = [n for n, s in v["markets"].get(m, {}).get("setups", {}).items() if s.get("status") == "validated"]
        if not passed:
            continue
        cfg = config.MARKETS[m]
        inst = data.instruments()
        tickers = inst.loc[inst["market"] == m, "yahoo"].tolist()
        bench = data.load_benchmark(cfg["benchmark"], config.VALIDATION_PERIOD)
        trades = []
        print(f"[{cfg['label']}] {len(passed)} passed strategies on {len(tickers)} instruments")
        for t, df in data.iter_daily(tickers, config.VALIDATION_PERIOD):
            if df.empty or len(df) < 300 or (cfg["liquidity"] and not data.liquid(df)):
                continue
            ind = indicators.compute_all(df, bench)
            for n in passed:
                s = by_name[n]
                for tr in engine.simulate(ind, signals(ind, s).to_numpy(), s, cfg["cost"], levels(ind, s), exit_mask(ind, s)):
                    trades.append({"setup": s.label, "entry": tr["entry_date"], "exit": tr["exit_date"], "ret": tr["ret"]})
        tdf = pd.DataFrame(trades)
        if tdf.empty:
            continue

        def through(dates):
            d = np.sort(pd.to_datetime(dates).to_numpy())
            lo = np.searchsorted(d, tdf["entry"].to_numpy(), side="left")
            hi = np.searchsorted(d, tdf["exit"].to_numpy(), side="left")
            return hi > lo

        tdf.to_csv(os.path.join(OUT, f"trades_{m}.csv.gz"), index=False, compression="gzip")
        # Longer trades cross more events, and in trend strategies the long trades are the winners.
        # So compare each trade only with trades of the SAME strategy held for the SAME number of days.
        tdf["days"] = np.busday_count(tdf["entry"].values.astype("datetime64[D]"), tdf["exit"].values.astype("datetime64[D]"))
        tdf["win"] = (tdf["ret"] > 0).astype(float)
        key = [tdf["setup"], tdf["days"]]
        tdf["ret_vs_peers"] = tdf["ret"] - tdf.groupby(key)["ret"].transform("mean")
        tdf["win_vs_peers"] = tdf["win"] - tdf.groupby(key)["win"].transform("mean")
        none = ~through(allev)
        for g, dates in list(groups.items()) + [("Any of these events", allev)]:
            th = through(dates)
            a, b = tdf[th], tdf[none]
            rows.append({"market": cfg["label"], "event": g, "trades_through": len(a), "trades_clear": len(b),
                         "win_through_pct": a["win"].mean() * 100 if len(a) else np.nan,
                         "win_clear_pct": b["win"].mean() * 100,
                         "matched_win_diff_pts": (a["win_vs_peers"].mean() - b["win_vs_peers"].mean()) * 100 if len(a) else np.nan,
                         "matched_avg_diff_pct": (a["ret_vs_peers"].mean() - b["ret_vs_peers"].mean()) if len(a) else np.nan,
                         "luck_t": welch_t(a["ret_vs_peers"], b["ret_vs_peers"])})
    pd.DataFrame(rows).round(3).to_csv(os.path.join(OUT, "strategies_through_events.csv"), index=False)


def main():
    ev = load_events()
    tests_1_3_4(ev)
    print("tests 1, 3, 4 done")
    if os.environ.get("SKIP_TEST2") != "1":
        test_2(ev)
        print("test 2 done")


if __name__ == "__main__":
    main()
