"""
Isaac's opening-direction strategy (US shares, 1-minute charts).

THE RULE (day 1, at the close; all on the 1-minute chart):
  1. RSI(14) is around 50 at the close             (default: between 40 and 60)
  2. The LAST 1-minute candle shows pressure:      green = buying, red = selling,
     on heavy volume                               (default: 1.5x its usual closing-minute volume)
  3. Price has crossed the 20-period VWMA in that  (close above VWMA20 for buying, below for selling,
     same direction, recently                       having crossed within the last 15 minutes)
  Prediction: day 2 OPENS in that direction.  Trade: buy (or sell) at day 2's open.

HOW IT'S TESTED
  Yahoo only gives ~30 days of free 1-minute candles, so every night this script:
    - downloads the last ~30 days of 1-minute candles for every Trade Nation US share (+ SPY),
    - turns each stock-day into ONE row of facts (RSI at close, last-candle pressure, VWMA cross,
      and what happened at the next day's open), and
    - ADDS new rows to data/opening/days.csv, so the history grows every trading day.
  The report compares the rule with:
    - "every stock, every day": the same trade with no filter, and
    - "last candle only": the direction of the last candle with none of the other conditions,
  and only calls it proven once it beats both, over enough DIFFERENT days (all stocks move together
  on a given day, so 500 stocks on one day is closer to 1 result than to 500).

Usage:
    python opening.py                # download, update history, write docs/opening.html
    python opening.py --no-download  # just re-test the saved history
"""

import argparse
import datetime as dt
import html
import math
import os
import time

import numpy as np
import pandas as pd

import config
import data

# ------------------------------------------------------------------ rule settings
RSI_LEN = 14
RSI_LO, RSI_HI = 40, 60          # "around 50"
LAST_VOL_MULT = 1.5              # last 1-min candle volume vs this stock's usual last-minute volume (prior 10 days)
VWMA_LEN = 20
CROSS_WITHIN_MIN = 15            # VWMA20 crossed in the last N minutes of the session
COST_PCT_SIDE = 0.05             # Trade Nation spread + slippage per side, %
HOLD_MINUTES = [1, 5, 15, 30, 60]
MAIN_HOLD = 15                   # holding time used for the verdict (minutes after the open)

# ------------------------------------------------------------------ proof thresholds
MIN_DAYS = 40                    # different trading days with at least one signal
MIN_TRADES = 150
MIN_TSTAT = 2.0                  # day-clustered t-stat of the average trade

HIST = os.path.join("data", "opening", "days.csv")
REPORT = os.path.join(config.OUTPUT_DIR, "opening.html")
TZ = "America/New_York"


# ------------------------------------------------------------------ download
def download_1m(tickers, days=29):
    """1-minute candles for the last `days` calendar days, in 7-day chunks (Yahoo's limit)."""
    import yfinance as yf
    end = dt.datetime.now(dt.timezone.utc)
    chunks = []
    start = end - dt.timedelta(days=days)
    while start < end:
        stop = min(start + dt.timedelta(days=7), end)
        chunks.append((start, stop))
        start = stop
    out = {t: [] for t in tickers}
    for i in range(0, len(tickers), 50):
        batch = tickers[i:i + 50]
        print(f"  tickers {i + 1}-{i + len(batch)} of {len(tickers)}")
        for a, b in chunks:
            try:
                d = yf.download(tickers=batch, start=a, end=b, interval="1m", group_by="ticker",
                                threads=True, progress=False, auto_adjust=False, prepost=False)
            except Exception as exc:
                print(f"    chunk failed: {exc}")
                continue
            for t in batch:
                try:
                    df = d[t] if isinstance(d.columns, pd.MultiIndex) else d
                    df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()
                    if len(df):
                        out[t].append(df)
                except Exception:
                    pass
            time.sleep(1)
    res = {}
    for t, parts in out.items():
        if parts:
            df = pd.concat(parts)
            df = df[~df.index.duplicated(keep="last")].sort_index()
            df.index = (df.index.tz_convert(TZ) if df.index.tz is not None
                        else df.index.tz_localize("UTC").tz_convert(TZ))
            res[t] = df
    return res


# ------------------------------------------------------------------ indicators
def rsi(close, n=RSI_LEN):
    d = close.diff()
    gain = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    loss = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(100.0)


def vwma(df, n=VWMA_LEN):
    pv = (df["Close"] * df["Volume"]).rolling(n).sum()
    v = df["Volume"].rolling(n).sum()
    return pv / v.replace(0, np.nan)


# ------------------------------------------------------------------ one row per stock-day
def day_rows(ticker, df):
    """Facts at each day's close + what happened at the NEXT day's open."""
    tod = df.index.hour * 60 + df.index.minute
    df = df[(tod >= 9 * 60 + 30) & (tod < 16 * 60)]
    if df.empty:
        return []
    df = df.assign(RSI=rsi(df["Close"]), VWMA=vwma(df))
    days = sorted(set(df.index.date))
    by_day = {d: df[df.index.date == d] for d in days}
    # The last minute always has big volume (closing auction), so "heavy" means heavy compared with
    # this stock's own last minute on the previous 10 days.
    last_vols = pd.Series({d: float(by_day[d]["Volume"].iloc[-1]) for d in days})
    ref = last_vols.shift(1).rolling(10, min_periods=5).median()
    rows = []
    for d1, d2 in zip(days[:-1], days[1:]):
        a, b = by_day[d1], by_day[d2]
        # need a full day 1 (ends 15:59) and the start of day 2 (9:30 bar present)
        if len(a) < 300 or a.index[-1].hour * 60 + a.index[-1].minute < 15 * 60 + 58:
            continue
        if b.index[0].hour * 60 + b.index[0].minute != 9 * 60 + 30 or len(b) < 61:
            continue
        last = a.iloc[-1]
        side = np.sign(a["Close"] - a["VWMA"])
        flips = np.flatnonzero((side != side.shift()).to_numpy()[1:]) + 1
        cross_age = (len(a) - 1 - flips[-1]) if len(flips) else 999
        o = float(b["Open"].iloc[0])
        row = {"date": str(d1), "next_date": str(d2), "ticker": ticker,
               "close": float(last["Close"]), "rsi": float(last["RSI"]),
               "last_dir": int(np.sign(last["Close"] - last["Open"])),
               "last_vol_ratio": float(last["Volume"] / ref[d1]) if ref[d1] > 0 else float("nan"),
               "vwma_side": int(side.iloc[-1]) if not math.isnan(side.iloc[-1]) else 0,
               "cross_age": int(cross_age),
               "day_volume": float(a["Volume"].sum()),
               "open2": o,
               "gap_pct": (o / float(last["Close"]) - 1) * 100}
        for m in HOLD_MINUTES:
            w = b.iloc[:m]
            row[f"ret_{m}"] = (float(w["Close"].iloc[-1]) / o - 1) * 100
            row[f"hi_{m}"] = (float(w["High"].max()) / o - 1) * 100
            row[f"lo_{m}"] = (float(w["Low"].min()) / o - 1) * 100
        rows.append(row)
    return rows


# ------------------------------------------------------------------ the rule and its tests
def signal(h, rsi_lo=RSI_LO, rsi_hi=RSI_HI, vol_mult=LAST_VOL_MULT, cross_within=CROSS_WITHIN_MIN):
    """+1 buy, -1 sell, 0 no signal, for every stock-day row."""
    d = h["last_dir"]
    ok = ((h["rsi"] >= rsi_lo) & (h["rsi"] <= rsi_hi) & (d != 0) &
          (h["last_vol_ratio"] >= vol_mult) &
          (h["vwma_side"] == d) & (h["cross_age"] <= cross_within))
    return d.where(ok, 0)


def evaluate(h, direction, hold=MAIN_HOLD):
    """Trades in `direction` (+1/-1, 0 = skip), entered at day 2's open, closed after `hold` minutes."""
    t = h[direction != 0].copy()
    if t.empty:
        return {"n": 0, "days": 0}
    dirn = direction[direction != 0]
    t["pnl"] = dirn * t[f"ret_{hold}"] - 2 * COST_PCT_SIDE
    t["opened_right"] = (dirn * t["ret_1"] > 0)
    # overnight version: enter at day 1's last price, exit `hold` minutes after day 2's open
    t["pnl_on"] = dirn * (((1 + t["gap_pct"] / 100) * (1 + t[f"ret_{hold}"] / 100) - 1) * 100) - 2 * COST_PCT_SIDE
    t["gap_right"] = (dirn * t["gap_pct"] > 0)
    per_day = t.groupby("date")["pnl"].mean()
    nd = len(per_day)
    tstat = per_day.mean() / (per_day.std(ddof=1) / math.sqrt(nd)) if nd > 2 and per_day.std(ddof=1) > 0 else float("nan")
    return {"n": len(t), "days": nd, "win": (t["pnl"] > 0).mean() * 100, "avg": t["pnl"].mean(),
            "opened_right": t["opened_right"].mean() * 100,
            "avg_overnight": t["pnl_on"].mean(), "win_overnight": (t["pnl_on"] > 0).mean() * 100,
            "t_overnight": _tday(t, "pnl_on"), "gap_right": t["gap_right"].mean() * 100,
            "tstat": tstat, "avg_by_hold": {m: (dirn * t[f"ret_{m}"] - 2 * COST_PCT_SIDE).mean()
                                           for m in HOLD_MINUTES}}


def _tday(t, col):
    per_day = t.groupby("date")[col].mean()
    sd = per_day.std(ddof=1)
    return per_day.mean() / (sd / math.sqrt(len(per_day))) if len(per_day) > 2 and sd > 0 else float("nan")


def verdict(rule, last_only, every):
    if rule["n"] == 0:
        return "no_signals", "The rule hasn't triggered yet in the saved history."
    if rule["days"] < MIN_DAYS or rule["n"] < MIN_TRADES:
        return "collecting", (f"Not enough history yet: {rule['days']} different trading days "
                              f"(need {MIN_DAYS}+ days and {MIN_TRADES}+ trades). Keep collecting; don't trade it.")
    if rule["avg"] <= 0:
        return "failed", "Loses money on average after costs."
    if not (rule["tstat"] >= MIN_TSTAT):
        return "failed", "Average profit is too small to rule out luck."
    if rule["avg"] <= max(last_only.get("avg", -9), every.get("avg", -9)):
        return "failed", "No better than simply following the last candle, or trading every stock every day."
    return "validated", "Passed: profitable after costs, not luck, and better than the simpler versions."


# ------------------------------------------------------------------ report
def _f(x, suf="", nd=1):
    return "–" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:.{nd}f}{suf}"


def render(h, results, status, why, today_signals):
    rule, last_only, every, variants = results
    rows = ""
    for label, r in [("Your rule", rule), ("Last candle only (no RSI / VWMA)", last_only),
                     ("Every stock, every day (buy)", every)]:
        rows += (f"<tr><td><b>{label}</b></td><td>{r.get('n', 0):,}</td><td>{r.get('days', 0)}</td>"
                 f"<td>{_f(r.get('opened_right'), '%')}</td><td>{_f(r.get('gap_right'), '%')}</td>"
                 f"<td>{_f(r.get('win'), '%')}</td><td>{_f(r.get('avg'), '%', 3)}</td><td>{_f(r.get('tstat'), '', 2)}</td></tr>")
    on_rows = "".join(f"<tr><td><b>{lab}</b></td><td>{_f(r.get('win_overnight'), '%')}</td><td>{_f(r.get('avg_overnight'), '%', 3)}</td>"
                      f"<td>{_f(r.get('t_overnight'), '', 2)}</td></tr>"
                      for lab, r in [("Your rule", rule), ("Last candle only", last_only), ("Every stock, every day (buy)", every)])
    hold = "".join(f"<td>{_f(rule.get('avg_by_hold', {}).get(m), '%', 3)}</td>" for m in HOLD_MINUTES)
    var_rows = "".join(f"<tr><td>{html.escape(k)}</td><td>{v.get('n', 0):,}</td><td>{v.get('days', 0)}</td>"
                       f"<td>{_f(v.get('opened_right'), '%')}</td><td>{_f(v.get('avg'), '%', 3)}</td>"
                       f"<td>{_f(v.get('tstat'), '', 2)}</td></tr>" for k, v in variants.items())
    colour = {"validated": "#2fbf71", "failed": "#e5484d"}.get(status, "#d6a94a")
    if status == "validated" and today_signals:
        sig = "".join(f"<tr><td><b>{html.escape(s['ticker'])}</b></td><td>{'BUY' if s['dir'] > 0 else 'SELL'}</td>"
                      f"<td>{_f(s['rsi'], '', 0)}</td><td>{_f(s['vol'], '×', 1)}</td></tr>" for s in today_signals)
        sig_html = ("<h2>Tonight's signals</h2><table><tr><th>Share</th><th>At the open</th><th>RSI</th>"
                    f"<th>Last-candle volume</th></tr>{sig}</table>")
    elif status == "validated":
        sig_html = "<h2>Tonight's signals</h2><p class='muted'>None tonight.</p>"
    else:
        sig_html = ("<h2>Tonight's signals</h2><p class='muted'>Hidden until the rule is proven. "
                    "Nothing here is a trade for real money yet.</p>")
    dates = f"{h['date'].min()} to {h['next_date'].max()}" if len(h) else "–"
    page = f"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Opening Direction Test</title>
<style>body{{margin:0;padding:28px 18px 60px;background:#0f1117;color:#e8e9ed;font-family:-apple-system,"Segoe UI",Helvetica,Arial,sans-serif;line-height:1.5}}
main{{max-width:900px}} h1{{font-size:23px;margin:0 0 4px}} h2{{font-size:17px;margin:30px 0 8px}}
.muted{{color:#9098a8}} .box{{background:#171a23;border:1px solid #262b38;border-left:4px solid {colour};border-radius:10px;padding:14px 16px;margin:16px 0}}
table{{border-collapse:collapse;font-size:14px;width:100%}} td,th{{text-align:left;padding:8px 8px;border-bottom:1px solid #262b38}}
th{{color:#9098a8;font-size:12px;text-transform:uppercase}} .wrap{{overflow-x:auto}} a{{color:#8fb4ff}}</style></head><body><main>
<h1>Opening Direction Test</h1>
<div class="muted">US shares on Trade Nation · 1-minute charts · history {dates} · {h['ticker'].nunique() if len(h) else 0} shares · updated {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC</div>
<div class="box"><b>Verdict: {status.replace('_', ' ').upper()}</b><br>{html.escape(why)}</div>
<h2>The rule</h2>
<ol><li>At the close, RSI({RSI_LEN}) on the 1-minute chart is between {RSI_LO} and {RSI_HI}.</li>
<li>The last 1-minute candle shows pressure: green = buying, red = selling, with at least {LAST_VOL_MULT:g}× this share's usual closing-minute volume (previous 10 days).</li>
<li>Price crossed the {VWMA_LEN}-period VWMA in the same direction within the last {CROSS_WITHIN_MIN} minutes.</li>
<li>Next day: buy (buying pressure) or sell (selling pressure) at the open; close after {MAIN_HOLD} minutes.</li></ol>
<h2>Results</h2><div class="wrap"><table>
<tr><th>Version</th><th>Trades</th><th>Different days</th><th>First minute went the right way</th><th>Gap went the right way</th>
<th>Win rate ({MAIN_HOLD} min)</th><th>Avg per trade after costs</th><th>Luck test (t, need {MIN_TSTAT:g}+)</th></tr>{rows}</table></div>
<h2>Same rule, but entering at day 1's close and holding overnight</h2>
<p class="muted">If the move happens in the overnight gap, entering at the open is too late. This version enters in the last minute of day 1.</p>
<div class="wrap"><table><tr><th>Version</th><th>Win rate</th><th>Avg after costs</th><th>t</th></tr>{on_rows}</table></div>
<p class="muted">Costs: {COST_PCT_SIDE:g}% per side. The luck test treats each day as one result, because all shares tend to move together.</p>
<h2>Your rule: average per trade by holding time</h2><div class="wrap"><table>
<tr>{''.join(f'<th>{m} min</th>' for m in HOLD_MINUTES)}</tr><tr>{hold}</tr></table></div>
<h2>Sensitivity (does it depend on the exact numbers?)</h2><div class="wrap"><table>
<tr><th>Variant</th><th>Trades</th><th>Days</th><th>First minute right</th><th>Avg after costs</th><th>t</th></tr>{var_rows}</table></div>
{sig_html}
<p class="muted" style="margin-top:28px">Proof needs {MIN_TRADES}+ trades over {MIN_DAYS}+ different trading days, a t of {MIN_TSTAT:g}+,
and a better average than both simpler versions. Free 1-minute history only goes back about 30 days, so the
history grows by one day every weeknight. Not financial advice.</p></main></body></html>"""
    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    for path in (REPORT, os.path.join(config.OUTPUT_DIR, config.DASHBOARD_FILE)):   # also the main dashboard
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(page)


def analyse(h):
    sig = signal(h)
    rule = evaluate(h, sig)
    last_only = evaluate(h, h["last_dir"])
    every = evaluate(h, pd.Series(1, index=h.index))
    variants = {
        "RSI 45–55 (tighter)": evaluate(h, signal(h, rsi_lo=45, rsi_hi=55)),
        "RSI 35–65 (looser)": evaluate(h, signal(h, rsi_lo=35, rsi_hi=65)),
        "Last-candle volume 1.2×": evaluate(h, signal(h, vol_mult=1.2)),
        "Last-candle volume 3×": evaluate(h, signal(h, vol_mult=3.0)),
        "VWMA cross within 5 min": evaluate(h, signal(h, cross_within=5)),
        "VWMA cross within 30 min": evaluate(h, signal(h, cross_within=30)),
        "Buy signals only": evaluate(h, sig.where(sig > 0, 0)),
        "Sell signals only": evaluate(h, sig.where(sig < 0, 0)),
    }
    return rule, last_only, every, variants


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-download", action="store_true")
    args = ap.parse_args()

    hist = pd.read_csv(HIST) if os.path.exists(HIST) else pd.DataFrame()
    today_signals = []
    if not args.no_download:
        inst = data.instruments()
        tickers = sorted(set(inst.loc[inst["market"] == "us", "yahoo"]))
        print(f"Downloading 1-minute candles for {len(tickers)} US shares...")
        bars = download_1m(tickers)
        new = []
        for t, df in bars.items():
            new += day_rows(t, df)
            # tonight's set-up: facts at the latest complete close (no next day yet)
            sig = latest_signal(t, df)
            if sig:
                today_signals.append(sig)
        new = pd.DataFrame(new)
        print(f"  {len(new)} stock-days from this download")
        hist = pd.concat([hist, new]) if len(hist) else new
        if len(hist):
            # keep a row's best version: one with a closing-volume reading (needs 10 prior days, which
            # later downloads no longer have for the oldest days) beats one without
            hist = (hist.assign(_ok=hist["last_vol_ratio"].notna()).iloc[::-1]
                    .sort_values("_ok", ascending=False, kind="stable")
                    .drop_duplicates(["ticker", "date"], keep="first").drop(columns="_ok")
                    .sort_values(["date", "ticker"]))
            os.makedirs(os.path.dirname(HIST), exist_ok=True)
            hist.to_csv(HIST, index=False)
    if today_signals:   # tonight's candidates, saved for checking (shown on the page only once proven)
        pd.DataFrame(today_signals).sort_values("vol", ascending=False).to_csv(
            os.path.join("data", "opening", "latest.csv"), index=False)
    if hist.empty:
        raise SystemExit("No history yet.")
    results = analyse(hist)
    status, why = verdict(results[0], results[1], results[2])
    render(hist, results, status, why, today_signals)
    r = results[0]
    print(f"History: {len(hist)} stock-days over {hist['date'].nunique()} days. Rule: {r.get('n', 0)} trades, "
          f"{r.get('days', 0)} days, avg {_f(r.get('avg'), '%', 3)}, t {_f(r.get('tstat'), '', 2)} -> {status}")


def latest_signal(ticker, df):
    """Does the rule fire on the most recent COMPLETE session (for tomorrow's open)?"""
    tod = df.index.hour * 60 + df.index.minute
    df = df[(tod >= 9 * 60 + 30) & (tod < 16 * 60)]
    if df.empty:
        return None
    df = df.assign(RSI=rsi(df["Close"]), VWMA=vwma(df))
    d = df.index[-1].date()
    a = df[df.index.date == d]
    prev = sorted(x for x in set(df.index.date) if x < d)[-10:]
    ref = np.median([float(df[df.index.date == x]["Volume"].iloc[-1]) for x in prev]) if len(prev) >= 5 else np.nan
    if len(a) < 300 or a.index[-1].hour * 60 + a.index[-1].minute < 15 * 60 + 58:
        return None
    last = a.iloc[-1]
    side = np.sign(a["Close"] - a["VWMA"])
    flips = np.flatnonzero((side != side.shift()).to_numpy()[1:]) + 1
    row = pd.DataFrame([{"rsi": last["RSI"], "last_dir": int(np.sign(last["Close"] - last["Open"])),
                         "last_vol_ratio": last["Volume"] / ref if ref and ref > 0 else np.nan,
                         "vwma_side": int(side.iloc[-1]) if not math.isnan(side.iloc[-1]) else 0,
                         "cross_age": (len(a) - 1 - flips[-1]) if len(flips) else 999}])
    s = int(signal(row).iloc[0])
    return {"ticker": ticker, "date": str(d), "close": float(last["Close"]), "dir": s, "rsi": float(last["RSI"]), "vol": float(row["last_vol_ratio"].iloc[0])} if s else None


if __name__ == "__main__":
    main()
