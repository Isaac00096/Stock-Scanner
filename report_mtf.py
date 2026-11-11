"""
Analysis of data/opening/mtf_rows.csv.gz (built by backtest_mtf.py) -> docs/backtest_mtf.html.

Rule (Isaac, 11 Nov 2026):
  * Day, 4hr, 1hr, 30min, 15min and 5min charts all on the same side of their 20 VWMA at the close
    (= the direction; 6 of 6, with a 5-of-6 version alongside)
  * RSI(14) on the 1-minute chart between 40 and 60
  * last 1-minute candle on >= 3x the stock's usual closing-minute volume (its colour doesn't matter)
  * a VWMA cross in that direction recently - tested on each chart to find which one works best
  * enter at the next open, 3% stop from the fill; held 1, 5, 15, 30 minutes; time exit or 1% take-profit
"""

import html
import os
import sys

import numpy as np
import pandas as pd

ROWS = os.path.join("data", "opening", os.environ.get("MTF_OUT", "mtf_rows.csv.gz"))
OUT = os.path.join("docs", os.environ.get("MTF_HTML", "backtest_mtf.html"))
FROM = os.environ.get("MTF_FROM", "2026-08-11")
SIX = ["day", "4h", "1h", "30m", "15m", "5m"]
CROSS = {"none": ("No cross needed", None, None),
         "1m": ("1min chart crossed in last 15 min", "age_1m", 14),
         "5m": ("5min chart crossed in last 15 min", "age_5m", 2),
         "15m": ("15min chart crossed in last 30 min", "age_15m", 1),
         "30m": ("30min chart crossed in last hour", "age_30m", 1),
         "1h": ("1hr chart crossed in last 2 hours", "age_1h", 1)}
HOLDS = [1, 5, 15, 30]
COST = 0.05          # % per side
STOP = 3.0


def direction(h, need=6):
    sides = h[[f"side_{t}" for t in SIX]].fillna(0)
    up, dn = (sides > 0).sum(axis=1), (sides < 0).sum(axis=1)
    return pd.Series(np.where(up >= need, 1, np.where(dn >= need, -1, 0)), index=h.index)


def rule(h, d, cross="none"):
    ok = (d != 0) & h["rsi"].between(40, 60) & (h["last_vol_ratio"] >= 3)
    _, col, mx = CROSS[cross]
    if col:
        ok &= (h[f"side_{cross}"] == d) & (h[col] <= mx)
    return d.where(ok, 0)


def pnl(t, d, hold, tp=None):
    fav = np.where(d > 0, t[f"hi_{hold}"], -t[f"lo_{hold}"])
    adv = np.where(d > 0, -t[f"lo_{hold}"], t[f"hi_{hold}"])
    r = t[f"ret_{hold}"] * d
    out = np.where(adv >= STOP, -STOP, np.where((tp is not None) & (fav >= (tp or 0)), tp or 0, r))
    return pd.Series(out - 2 * COST, index=t.index)


def stats(h, d, hold, tp=None):
    m = d != 0
    t, dd = h[m], d[m]
    if not len(t):
        return {"n": 0}
    p = pnl(t, dd, hold, tp)
    raw = t[f"ret_{hold}"] * dd
    day = p.groupby(t["date"]).mean()
    tstat = day.mean() / day.std(ddof=1) * np.sqrt(len(day)) if len(day) > 2 and day.std(ddof=1) > 0 else np.nan
    return {"n": len(t), "days": t["date"].nunique(), "right": (raw > 0).mean() * 100,
            "win": (p > 0).mean() * 100, "avg": p.mean(), "t": tstat}


def load():
    import glob
    files = sorted(glob.glob(ROWS.replace(".csv.gz", "_*.csv.gz"))) or [ROWS]
    h = pd.concat([pd.read_csv(f) for f in files], ignore_index=True)
    return h[h["date"] >= FROM].reset_index(drop=True)


def fmt(s):
    if not s.get("n"):
        return ["0", "–", "–", "–", "–", "–"]
    return [f"{s['n']:,}", str(s["days"]), f"{s['right']:.0f}%", f"{s['win']:.0f}%", f"{s['avg']:+.2f}%",
            "–" if s["t"] != s["t"] else f"{s['t']:.2f}"]


def table(head, rows):
    th = "".join(f"<th>{html.escape(x)}</th>" for x in head)
    tr = "".join("<tr>" + "".join(f"<td>{html.escape(str(c))}</td>" for c in r) + "</tr>" for r in rows)
    return f"<div class=wrap><table><tr>{th}</tr>{tr}</table></div>"


def main():
    h = load()
    d6, d5 = direction(h, 6), direction(h, 5)
    head = ["Version", "Hold", "Exit", "Trades", "Days", "Moved right way", "Win after costs", "Avg after costs", "Luck test t"]
    parts, console = [], []

    def block(title, dvec):
        rows = []
        for c, (lab, _, _) in CROSS.items():
            s = rule(h, dvec, c)
            for hold in HOLDS:
                for tp, tl in ((None, "Time exit"), (1.0, "1% take-profit")):
                    st = stats(h, s, hold, tp)
                    rows.append([lab, f"{hold} min", tl] + fmt(st))
                    console.append(f"{title[:10]} | {lab:36} | {hold:>2}m | {tl:15} | " + " | ".join(fmt(st)))
        parts.append(f"<h2>{html.escape(title)}</h2>" + table(head, rows))

    block("All 6 charts agree (Day, 4hr, 1hr, 30min, 15min, 5min)", d6)
    block("At least 5 of the 6 charts agree", d5)
    # the version that looked best on 3 months: last 1-min candle WITH the charts
    block("All 6 agree AND last 1-min candle in the same direction", d6.where(h["last_dir"] == d6, 0))

    # simpler versions for comparison
    cmp_rows = []
    for lab, s in (("All 6 agree only (no RSI, volume or cross)", d6),
                   ("All 6 agree + RSI 40-60 + 3x volume", rule(h, d6)),
                   ("Buy every share at the open (random baseline)", pd.Series(1, index=h.index))):
        for hold in (1, 5, 15):
            cmp_rows.append([lab, f"{hold} min"] + fmt(stats(h, s, hold)))
    parts.append("<h2>Compared with simpler versions (time exit)</h2>" +
                 table(["Version", "Hold", "Trades", "Days", "Moved right way", "Win after costs", "Avg after costs", "t"], cmp_rows))

    # last 1-min candle with or against the charts
    s = rule(h, d6)
    split = []
    for lab, m in (("Last 1-min candle WITH the charts", h["last_dir"] == s),
                   ("Last 1-min candle AGAINST the charts", h["last_dir"] == -s)):
        for hold in (1, 5, 15):
            split.append([lab, f"{hold} min"] + fmt(stats(h, s.where(m, 0), hold)))
    parts.append("<h2>Last 1-minute candle: with vs against the bigger charts (6 of 6, no cross needed)</h2>" +
                 table(["Group", "Hold", "Trades", "Days", "Moved right way", "Win after costs", "Avg after costs", "t"], split))

    n_days = h["date"].nunique()
    css = ("body{margin:0;padding:28px 18px 60px;background:#0f1117;color:#e8e9ed;font-family:-apple-system,'Segoe UI',"
           "Helvetica,Arial,sans-serif;line-height:1.5}main{max-width:1000px}h1{font-size:23px;margin:0 0 4px}"
           "h2{font-size:17px;margin:30px 0 8px}.muted{color:#9098a8}table{border-collapse:collapse;font-size:13px;width:100%}"
           "td,th{text-align:left;padding:6px 8px;border-bottom:1px solid #262b38}th{color:#9098a8;font-size:11px;"
           "text-transform:uppercase}.wrap{overflow-x:auto}")
    page = f"""<!doctype html><html><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>Multi-Timeframe Backtest</title><style>{css}</style></head><body><main>
<h1>Opening strategy: multi-timeframe backtest</h1>
<p class=muted>{h['date'].min()} to {h['date'].max()} · {n_days} trading days · {h['ticker'].nunique()} US shares · {len(h):,} stock-days</p>
<p>Direction = the side of the 20 VWMA that the Day, 4hr, 1hr, 30min, 15min and 5min charts are on at the close.
Plus RSI(14) 40–60 on the 1-minute chart and the last 1-minute candle on ≥3× its usual closing-minute volume (either colour).
Each VWMA-cross version is tested to see which chart's cross helps. Enter at the next open, 3% stop from the fill,
costs 0.05% each way. "Moved right way" is before costs. Where the stop and take-profit were both touched, the stop counts first.</p>
{''.join(parts)}
<p class=muted>Fewer than ~150 trades or a t below 2 means the result could easily be luck.
Shares: today's Trade Nation US list. Data: Alpaca, consolidated US tape. Not financial advice.</p>
</main></body></html>"""
    with open(OUT, "w") as fh:
        fh.write(page)
    if "-v" in sys.argv:
        print("\n".join(console))
    print("wrote", OUT)


if __name__ == "__main__":
    main()
