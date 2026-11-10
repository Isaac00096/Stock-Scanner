"""
Multi-year backtest of Isaac's opening-direction strategy, on Alpaca's free 1-minute history
(US consolidated "SIP" data, from 2016). Needs two GitHub secrets: ALPACA_KEY and ALPACA_SECRET.

For every trading day it downloads only the two windows the rule needs, for all ~570 Trade Nation
US shares:  15:00-16:00 New York (day 1's close)  and  09:30-10:30 (day 2's open).
It turns them into one row per stock-day (same facts as opening.py), saved to
data/opening/bt/<year>.csv.gz. Progress is saved as it goes; if a run stops, the next run carries on.

Then it writes docs/backtest_opening.html: the rule (3x closing volume) with buy and sell signals,
held 5 / 15 / 30 minutes, with no take-profit, 1% and 1.5% take-profits, a 3% stop, at 0.05% and
0.10% costs per side, compared with simpler versions, and split by year.

Usage:
    python backtest_opening.py                 # download (resumes) + report
    python backtest_opening.py --report-only
    python backtest_opening.py --start 2016-01-04 --max-minutes 330
"""

import argparse
import datetime as dt
import html
import json
import math
import os
import time

import numpy as np
import pandas as pd
import requests

import config
import data
import opening as op

ROWS_DIR = os.path.join("data", "opening", "bt")   # one gzip file per year
KEEP_COLS = ["date", "next_date", "ticker", "close", "rsi", "last_dir", "last_vol_ratio", "vwma_side", "cross_age",
             "gap_pct", "sample"] + [f"{k}_{m}" for m in (1, 5, 15, 30) for k in ("ret", "hi", "lo")]
SAMPLE_PCT = 5   # % of ALL stock-days kept for the "simpler versions" comparisons
STATE = os.path.join("data", "opening", "bt_state.json")
REPORT = os.path.join(config.OUTPUT_DIR, "backtest_opening.html")
URL = "https://data.alpaca.markets/v2/stocks/bars"
NY = "America/New_York"
VOL_MULT = 3.0
HOLDS = [5, 15, 30]
COSTS = [0.05, 0.10]


# ------------------------------------------------------------------ download
class Alpaca:
    def __init__(self):
        self.s = requests.Session()
        self.s.headers.update({"APCA-API-KEY-ID": os.environ["ALPACA_KEY"],
                               "APCA-API-SECRET-KEY": os.environ["ALPACA_SECRET"]})
        self.calls = 0

    def bars(self, symbols, start, end):
        """1-minute bars for many symbols between two NY-time timestamps -> {symbol: DataFrame}."""
        out = {}
        for i in range(0, len(symbols), 100):
            params = {"symbols": ",".join(symbols[i:i + 100]), "timeframe": "1Min",
                      "start": start.tz_convert("UTC").isoformat(), "end": end.tz_convert("UTC").isoformat(),
                      "limit": 10000, "feed": "sip", "adjustment": "raw"}
            while True:
                for attempt in range(6):
                    r = self.s.get(URL, params=params, timeout=60)
                    self.calls += 1
                    if r.status_code == 429 or r.status_code >= 500:
                        time.sleep(5 * (attempt + 1))
                        continue
                    break
                r.raise_for_status()
                j = r.json()
                for sym, rows in (j.get("bars") or {}).items():
                    out.setdefault(sym, []).extend(rows)
                tok = j.get("next_page_token")
                if not tok:
                    break
                params["page_token"] = tok
            time.sleep(0.32)        # free plan: 200 requests/minute
        res = {}
        for sym, rows in out.items():
            df = pd.DataFrame(rows)
            df.index = pd.to_datetime(df["t"], utc=True).dt.tz_convert(NY)
            df = df.rename(columns={"o": "Open", "h": "High", "l": "Low", "c": "Close", "v": "Volume"})
            res[sym] = df[["Open", "High", "Low", "Close", "Volume"]].sort_index()
        return res


def close_facts(df):
    """Day-1 facts from the 15:00-15:59 window (60 one-minute bars)."""
    tod = df.index.hour * 60 + df.index.minute
    a = df[(tod >= 15 * 60) & (tod < 16 * 60)]
    if len(a) < 45 or (a.index[-1].hour, a.index[-1].minute) != (15, 59):
        return None
    a = a.assign(RSI=op.rsi(a["Close"]), VWMA=op.vwma(a))
    last = a.iloc[-1]
    side = np.sign(a["Close"] - a["VWMA"])
    flips = np.flatnonzero((side != side.shift()).to_numpy()[1:]) + 1
    flips = flips[flips >= op.VWMA_LEN]           # ignore the warm-up of the average
    return {"close": float(last["Close"]), "rsi": float(last["RSI"]),
            "last_dir": int(np.sign(last["Close"] - last["Open"])), "last_vol": float(last["Volume"]),
            "vwma_side": 0 if math.isnan(side.iloc[-1]) else int(side.iloc[-1]),
            "cross_age": int(len(a) - 1 - flips[-1]) if len(flips) else 999,
            "window_volume": float(a["Volume"].sum())}


def open_facts(df):
    """Day-2 outcomes from the 09:30-10:29 window."""
    tod = df.index.hour * 60 + df.index.minute
    b = df[(tod >= 9 * 60 + 30) & (tod < 10 * 60 + 30)]
    if len(b) < 61 - 15 or (b.index[0].hour, b.index[0].minute) != (9, 30):
        return None
    # fill missing minutes forward so "after N minutes" means clock minutes
    idx = pd.date_range(b.index[0], periods=60, freq="min")
    b = b.reindex(idx)
    b["Close"] = b["Close"].ffill()
    for c in ("Open", "High", "Low"):
        b[c] = b[c].fillna(b["Close"])
    o = float(b["Open"].iloc[0])
    res = {"open2": o}
    for m in op.HOLD_MINUTES:
        w = b.iloc[:m]
        res[f"ret_{m}"] = (float(w["Close"].iloc[-1]) / o - 1) * 100
        res[f"hi_{m}"] = (float(w["High"].max()) / o - 1) * 100
        res[f"lo_{m}"] = (float(w["Low"].min()) / o - 1) * 100
    return res


def run_download(start, max_minutes):
    inst = data.instruments()
    syms = sorted({y.replace("-", ".") for y in inst.loc[inst["market"] == "us", "yahoo"]})
    api = Alpaca()
    st = json.load(open(STATE)) if os.path.exists(STATE) else {"next_day": start, "pending": {}, "last_vols": {}}
    day = pd.Timestamp(st["next_day"]).date()
    last_day = (pd.Timestamp.now(tz=NY) - pd.Timedelta(days=1)).date()
    t0, new_rows = time.time(), []
    while day <= last_day and (time.time() - t0) / 60 < max_minutes:
        if day.weekday() < 5:
            ts = lambda h, m: pd.Timestamp(dt.datetime(day.year, day.month, day.day, h, m), tz=NY)
            opens = api.bars(syms, ts(9, 30), ts(10, 30))
            if opens:   # a trading day
                pend = st["pending"]
                for sym, df in opens.items():
                    f = pend.get(sym)
                    if f:
                        o = open_facts(df)
                        if o:
                            new_rows.append({**f, **o, "next_date": str(day), "ticker": sym.replace(".", "-"),
                                             "gap_pct": (o["open2"] / f["close"] - 1) * 100})
                closes = api.bars(syms, ts(15, 0), ts(16, 0))
                pend = {}
                for sym, df in closes.items():
                    f = close_facts(df)
                    if not f:
                        continue
                    hist = st["last_vols"].get(sym, [])
                    ref = float(np.median(hist[-10:])) if len(hist) >= 5 else float("nan")
                    f["last_vol_ratio"] = f["last_vol"] / ref if ref and ref > 0 else float("nan")
                    f["date"] = str(day)
                    st["last_vols"][sym] = (hist + [f["last_vol"]])[-10:]
                    pend[sym] = f
                st["pending"] = pend
                print(f"{day}: {len(closes)} shares, {len(new_rows)} new rows so far, {api.calls} calls")
        day += dt.timedelta(days=1)
        st["next_day"] = str(day)
        if len(new_rows) >= 20000 or day > last_day:
            _save(new_rows, st)
            new_rows = []
    _save(new_rows, st)
    return day > last_day


def _save(rows, st):
    """Keep every stock-day with heavy closing volume (1.5x+) and a random 5% of all stock-days
    (marked sample=1, used for the baselines). Saved per year, gzip-compressed."""
    os.makedirs(ROWS_DIR, exist_ok=True)
    if rows:
        df = pd.DataFrame(rows)
        key = pd.util.hash_pandas_object(df[["ticker", "date"]], index=False) % 100
        df["sample"] = (key < SAMPLE_PCT).astype(int)
        df = df[(df["last_vol_ratio"] >= 1.5) | (df["sample"] == 1)][KEEP_COLS].round(4)
        for y, g in df.groupby(df["date"].str[:4]):
            path = os.path.join(ROWS_DIR, f"{y}.csv.gz")
            g.to_csv(path, mode="a", header=not os.path.exists(path), index=False, compression="gzip")
    with open(STATE, "w") as fh:
        json.dump(st, fh)


# ------------------------------------------------------------------ report
def _f(x, suf="", nd=1):
    return "–" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:.{nd}f}{suf}"


def load_rows():
    files = sorted(f for f in os.listdir(ROWS_DIR) if f.endswith(".csv.gz")) if os.path.isdir(ROWS_DIR) else []
    if not files:
        return pd.DataFrame()
    h = pd.concat(pd.read_csv(os.path.join(ROWS_DIR, f)) for f in files)
    # appended gzip members each carry a header row; drop any that slipped in as data
    h = h[h["date"] != "date"]
    for c in h.columns:
        if c not in ("date", "next_date", "ticker"):
            h[c] = pd.to_numeric(h[c])
    for m in (60,):
        for k in ("ret", "hi", "lo"):
            h[f"{k}_{m}"] = h[f"{k}_30"]          # not stored; evaluate() expects the column
    return h.drop_duplicates(["ticker", "date"]).reset_index(drop=True)


def report(done):
    h = load_rows()
    if h.empty:
        return
    base = h[h["sample"] == 1]
    sig = op.signal(h, vol_mult=VOL_MULT)
    trades = int((sig != 0).sum())
    blocks = []
    for cost in COSTS:
        op.COST_PCT_SIDE = cost
        rows = ""
        for hold in HOLDS:
            for name, r in op.exits(h, sig, hold=hold).items():
                rows += (f"<tr><td>{hold} min</td><td>{html.escape(name.replace(f'Close after {hold} min', 'Time exit only'))}</td>"
                         f"<td>{_f(r['reached'], '%')}</td><td><b>{_f(r['win'], '%')}</b></td>"
                         f"<td><b>{_f(r['avg'], '%', 3)}</b></td><td>{_f(r['tstat'], '', 2)}</td></tr>")
        blocks.append(f"<h2>Costs {cost:g}% per side</h2><div class='wrap'><table><tr><th>Hold</th><th>Exit</th>"
                      f"<th>Reached take-profit</th><th>Win rate</th><th>Avg per trade</th><th>Luck test t</th></tr>{rows}</table></div>")
    op.COST_PCT_SIDE = 0.05
    comp = ""
    for label, d in [("Your rule (3× volume)", sig), ("Your rule, normal volume (1.5×)", op.signal(h)),
                     ("Last candle only (5% sample of all days)", "last"),
                     ("Buy everything (5% sample of all days)", "buy")]:
        hh = h
        if isinstance(d, str):
            hh = base
            d = base["last_dir"] if d == "last" else pd.Series(1, index=base.index)
        r = op.exits(hh, d, hold=15).get("Close after 15 min (no take-profit)", {})
        comp += (f"<tr><td><b>{label}</b></td><td>{r.get('n', 0):,}</td><td>{_f(r.get('win'), '%')}</td>"
                 f"<td>{_f(r.get('avg'), '%', 3)}</td><td>{_f(r.get('tstat'), '', 2)}</td></tr>")
    years = ""
    h["year"] = h["date"].str[:4]
    for y, g in h.groupby("year"):
        r = op.exits(g, op.signal(g, vol_mult=VOL_MULT), hold=15)
        a, b = r.get("Close after 15 min (no take-profit)", {}), r.get("Take profit at 1%", {})
        years += (f"<tr><td>{y}</td><td>{a.get('n', 0):,}</td><td>{_f(a.get('win'), '%')}</td><td>{_f(a.get('avg'), '%', 3)}</td>"
                  f"<td>{_f(b.get('win'), '%')}</td><td>{_f(b.get('avg'), '%', 3)}</td></tr>")
    side = ""
    for label, d in [("Buy signals", sig.where(sig > 0, 0)), ("Sell signals", sig.where(sig < 0, 0)),
                     ("Under $10", sig.where(h["close"] < 10, 0)), ("$10 and over", sig.where(h["close"] >= 10, 0))]:
        r = op.exits(h, d, hold=15).get("Close after 15 min (no take-profit)", {})
        side += (f"<tr><td>{label}</td><td>{r.get('n', 0):,}</td><td>{_f(r.get('win'), '%')}</td>"
                 f"<td>{_f(r.get('avg'), '%', 3)}</td><td>{_f(r.get('tstat'), '', 2)}</td></tr>")
    status = "complete" if done else "IN PROGRESS: still downloading, numbers will change"
    page = f"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Opening Strategy Backtest</title>
<style>body{{margin:0;padding:28px 18px 60px;background:#0f1117;color:#e8e9ed;font-family:-apple-system,"Segoe UI",Helvetica,Arial,sans-serif;line-height:1.5}}
main{{max-width:960px}} h1{{font-size:23px;margin:0 0 4px}} h2{{font-size:17px;margin:30px 0 8px}} .muted{{color:#9098a8}}
table{{border-collapse:collapse;font-size:14px;width:100%}} td,th{{text-align:left;padding:7px 8px;border-bottom:1px solid #262b38}}
th{{color:#9098a8;font-size:12px;text-transform:uppercase}} .wrap{{overflow-x:auto}}</style></head><body><main>
<h1>Opening Strategy Backtest</h1>
<div class="muted">{h['date'].min()} to {h['next_date'].max()} · {h['date'].nunique():,} trading days · {h['ticker'].nunique()} shares ·
{len(h):,} stored stock-days · {trades:,} signals · status: {status}</div>
<p>Rule: RSI(14) 40–60 at the close · last 1-min candle green (buy) or red (sell) on {VOL_MULT:g}× its usual closing-minute
volume · VWMA(20) crossed the same way in the last 15 minutes · enter at the next open · {op.STOP_PCT:g}% stop from the fill.
Where the stop and the take-profit were both touched, the stop is counted first.</p>
{''.join(blocks)}
<h2>Compared with simpler versions (15 min, 0.05% costs)</h2><div class="wrap"><table>
<tr><th>Version</th><th>Trades</th><th>Win rate</th><th>Avg</th><th>t</th></tr>{comp}</table></div>
<h2>By year (15 min, 0.05% costs): does it hold up every year?</h2><div class="wrap"><table>
<tr><th>Year</th><th>Trades</th><th>Win (time exit)</th><th>Avg (time exit)</th><th>Win (1% TP)</th><th>Avg (1% TP)</th></tr>{years}</table></div>
<h2>Split (15 min, 0.05% costs)</h2><div class="wrap"><table>
<tr><th>Group</th><th>Trades</th><th>Win rate</th><th>Avg</th><th>t</th></tr>{side}</table></div>
<p class="muted">Shares: today's Trade Nation US list, so companies that were delisted along the way are missing (this flatters
results slightly). Data: Alpaca, consolidated US tape. Not financial advice.</p></main></body></html>"""
    with open(REPORT, "w", encoding="utf-8") as fh:
        fh.write(page)
    print(f"Report: {len(h):,} stored stock-days, {trades:,} signals")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--report-only", action="store_true")
    ap.add_argument("--start", default="2016-01-04")
    ap.add_argument("--max-minutes", type=float, default=320)
    a = ap.parse_args()
    done = True
    if not a.report_only:
        done = run_download(a.start, a.max_minutes)
    report(done)


if __name__ == "__main__":
    main()
