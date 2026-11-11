"""News straddle test: just before a timed announcement, open a buy AND a sell on the same pair,
each with a stop of k x (typical daily range) and a target of 3x the stop. Hourly Yahoo data (~2 years).
If a stop and a target are both touched within one hour, the stop counts first (conservative).
Costs: a news-time spread on each leg, and one extra spread of slippage on every stop.
Outputs data/events/straddle_trades.csv and straddle_summary.csv."""
import os
import numpy as np
import pandas as pd
import yfinance as yf

OUT = os.path.join("data", "events")
SYMS = {"EUR/USD": "EURUSD=X", "GBP/USD": "GBPUSD=X", "USD/JPY": "JPY=X", "USD/ZAR": "USDZAR=X"}
SPREAD_PCT = {"EUR/USD": 0.02, "GBP/USD": 0.025, "USD/JPY": 0.02, "USD/ZAR": 0.15}   # wide, news-time spreads
KS = [0.10, 0.25, 0.50]          # stop as a share of the typical daily range; 0.25 is Isaac's "1/4"
TP_MULT = 3                       # target = 3 x stop (his "3/4" with a "1/4" stop)
GRID_KS = [0.25, 0.5, 0.75, 1.0]
GRID_TPS = [1.0, 1.5, 2.0, 3.0]
MAX_HOURS = 24


def hourly(sym):
    df = yf.download(sym, period="730d", interval="1h", progress=False, auto_adjust=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.index = pd.to_datetime(df.index, utc=True)
    df = df[["Open", "High", "Low", "Close"]].dropna()
    # drop bad ticks: bars whose range is absurd
    rng = (df["High"] - df["Low"]) / df["Close"]
    return df[rng < rng.rolling(500, min_periods=50).median() * 25]


def leg(bars, entry, side, stop, target, spread):
    """side +1 buy / -1 sell; stop, target as % distances. Returns (pnl %, outcome)."""
    for _, b in bars.iterrows():
        up = (b["High"] / entry - 1) * 100
        dn = (b["Low"] / entry - 1) * 100
        adverse = -dn if side > 0 else up
        favour = up if side > 0 else -dn
        if adverse >= stop:
            return -stop - spread - spread, "stop"
        if favour >= target:
            return target - spread, "target"
    last = (bars["Close"].iloc[-1] / entry - 1) * 100 * side
    return last - spread, "time"


def main():
    ev = pd.read_csv(os.path.join(OUT, "straddle_events.csv"))
    data = {p: hourly(s) for p, s in SYMS.items()}
    zar = data["USD/ZAR"]["Close"]
    rows = []
    for e in ev.itertuples():
        t = pd.Timestamp(e.time_utc, tz="UTC")
        for pair in e.pairs.split(";"):
            df = data[pair]
            start = t.floor("h")
            after = df[df.index >= start]
            if after.empty or (after.index[0] - start) > pd.Timedelta(hours=3) or df.index[0] > start - pd.Timedelta(days=30):
                continue
            entry = after["Open"].iloc[0]
            bars = after.iloc[:MAX_HOURS]
            daily = df[df.index < start].resample("D").agg({"High": "max", "Low": "min", "Close": "last"}).dropna().tail(20)
            day_range = float(((daily["High"] - daily["Low"]) / daily["Close"]).median() * 100)
            usdzar = float(zar[zar.index <= start].iloc[-1])
            base_usd = entry if pair in ("EUR/USD", "GBP/USD") else 1.0
            notional_zar = 1000 * base_usd * usdzar          # size 0.01 = 1,000 units of the first currency
            sp = SPREAD_PCT[pair]
            combos = [(k, TP_MULT) for k in KS] + ([(k, m) for k in GRID_KS for m in GRID_TPS] if e.group != "SARB decision" else [])
            for k, m in combos:
                stop, target = k * day_range, k * day_range * m
                b_pnl, b_out = leg(bars, entry, 1, stop, target, sp)
                s_pnl, s_out = leg(bars, entry, -1, stop, target, sp)
                net = b_pnl + s_pnl
                kind = ("Both stopped (whipsaw)" if b_out == s_out == "stop" else
                        "One hit target" if "target" in (b_out, s_out) else "Neither target (closed at 24h)")
                rows.append({"time_utc": e.time_utc, "group": e.group, "name": e.name, "pair": pair, "stop_k": k, "tp_mult": m,
                             "day_range_pct": round(day_range, 3), "stop_pct": round(stop, 3), "target_pct": round(target, 3),
                             "buy": b_out, "sell": s_out, "outcome": kind, "net_pct": round(net, 4),
                             "net_r": round(net / stop, 3), "net_zar_001": round(net / 100 * notional_zar, 2)})
    tr = pd.DataFrame(rows).drop_duplicates(["time_utc", "pair", "stop_k", "tp_mult"])
    tr.to_csv(os.path.join(OUT, "straddle_trades.csv"), index=False)
    g = tr[tr.group != "SARB decision"]
    grid = []
    for (k, m), d in g.groupby(["stop_k", "tp_mult"]):
        if k not in GRID_KS or m not in GRID_TPS:
            continue
        ev = d.groupby("time_utc").net_zar_001.sum()
        grid.append({"stop_k": k, "tp_mult": m, "straddles": len(d), "events": len(ev),
                     "whipsaw_pct": round((d.outcome == "Both stopped (whipsaw)").mean() * 100, 1),
                     "target_pct": round((d.outcome == "One hit target").mean() * 100, 1),
                     "avg_zar_001": round(d.net_zar_001.mean(), 2), "total_zar_001": round(d.net_zar_001.sum(), 2),
                     "worst_event_zar": round(ev.min(), 2),
                     "luck_t": round(ev.mean() / ev.std(ddof=1) * np.sqrt(len(ev)), 2) if len(ev) > 2 else np.nan})
    pd.DataFrame(grid).to_csv(os.path.join(OUT, "straddle_grid.csv"), index=False)
    print(pd.DataFrame(grid).to_string())
    tr = tr[tr.tp_mult == TP_MULT]
    summ = []
    for (k, g), d in tr.groupby(["stop_k", "group"]):
        summ.append({"stop_k": k, "group": g, "straddles": len(d),
                     "whipsaw_pct": round((d.outcome == "Both stopped (whipsaw)").mean() * 100, 1),
                     "target_pct": round((d.outcome == "One hit target").mean() * 100, 1),
                     "avg_net_r": round(d.net_r.mean(), 3), "total_zar_001": round(d.net_zar_001.sum(), 2),
                     "avg_zar_001": round(d.net_zar_001.mean(), 2), "worst_zar_001": round(d.net_zar_001.min(), 2),
                     "best_zar_001": round(d.net_zar_001.max(), 2), "win_pct": round((d.net_pct > 0).mean() * 100, 1)})
    for k, d in tr.groupby("stop_k"):
        summ.append({"stop_k": k, "group": "All announcements", "straddles": len(d),
                     "whipsaw_pct": round((d.outcome == "Both stopped (whipsaw)").mean() * 100, 1),
                     "target_pct": round((d.outcome == "One hit target").mean() * 100, 1),
                     "avg_net_r": round(d.net_r.mean(), 3), "total_zar_001": round(d.net_zar_001.sum(), 2),
                     "avg_zar_001": round(d.net_zar_001.mean(), 2), "worst_zar_001": round(d.net_zar_001.min(), 2),
                     "best_zar_001": round(d.net_zar_001.max(), 2), "win_pct": round((d.net_pct > 0).mean() * 100, 1)})
    sm = pd.DataFrame(summ)
    sm.to_csv(os.path.join(OUT, "straddle_summary.csv"), index=False)
    pd.set_option("display.width", 250)
    print(sm.to_string())
    print(tr[tr.stop_k == 0.25].to_string())


if __name__ == "__main__":
    main()
