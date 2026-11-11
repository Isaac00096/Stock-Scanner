"""
Multi-timeframe version of Isaac's opening-direction strategy, last ~3 months, on Alpaca 1-minute data.

For every Trade Nation US share and every trading day it records, at the 15:59 close (New York):
  * which side of its 20-period VWMA the price is on, on the Day, 4hr, 1hr, 30min, 15min, 5min and 1min charts
    (all built from regular-hours 1-minute bars, candles anchored at 09:30), the colour of each chart's last candle,
    and how many candles ago each chart last crossed its VWMA
  * RSI(14) on the 1-minute chart, the last 1-minute candle's colour and its volume vs. the median of the
    stock's closing-minute volume over the 10 days before
and the next day's outcome from the 09:30 open: close / high / low after 1, 5, 15 and 30 minutes.

Writes data/opening/mtf_rows.csv.gz (one row per stock-day). The analysis is done by report_mtf.py.

    python backtest_mtf.py --start 2026-07-01 --end 2026-11-11
"""

import argparse
import os
import time

import numpy as np
import pandas as pd
import requests

import data

URL = "https://data.alpaca.markets/v2/stocks/bars"
NY = "America/New_York"
OUT = os.path.join("data", "opening", "mtf_rows.csv.gz")
TFS = {"5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240, "day": 390}
LEN = 20


def fetch(sess, symbols, start, end):
    params = {"symbols": ",".join(symbols), "timeframe": "1Min", "start": start, "end": end,
              "limit": 10000, "feed": "sip", "adjustment": "split"}
    out = {}
    while True:
        for attempt in range(8):
            r = sess.get(URL, params=params, timeout=90)
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(5 * (attempt + 1))
                continue
            break
        r.raise_for_status()
        j = r.json()
        for sym, rows in (j.get("bars") or {}).items():
            out.setdefault(sym, []).extend(rows)
        time.sleep(0.31)
        tok = j.get("next_page_token")
        if not tok:
            return out
        params["page_token"] = tok


def rsi(c, n=14):
    d = c.diff()
    g = d.clip(lower=0).ewm(alpha=1 / n, min_periods=n, adjust=False).mean()
    l = (-d.clip(upper=0)).ewm(alpha=1 / n, min_periods=n, adjust=False).mean()
    return 100 - 100 / (1 + g / l.replace(0, np.nan))


def side_and_age(close, vol):
    """sign(close - VWMA20) and number of candles since that side last changed."""
    vw = (close * vol).rolling(LEN).sum() / vol.rolling(LEN).sum()
    side = np.sign(close - vw)
    grp = (side != side.shift()).cumsum()
    age = side.groupby(grp).cumcount()
    return side, age


def facts(rows):
    df = pd.DataFrame(rows)
    df.index = pd.to_datetime(df["t"], utc=True).dt.tz_convert(NY)
    df = df.rename(columns={"o": "o", "h": "h", "l": "l", "c": "c", "v": "v"})[["o", "h", "l", "c", "v"]]
    m = df.index.hour * 60 + df.index.minute - 570          # minute of the session, 0 = 09:30
    df = df[(m >= 0) & (m < 390)].copy()
    if df.empty:
        return []
    df["date"] = df.index.date
    df["m"] = df.index.hour * 60 + df.index.minute - 570
    dates = sorted(df["date"].unique())
    # full days only (closes at 16:00 with a 15:59 bar)
    last_m = df.groupby("date")["m"].max()
    first_m = df.groupby("date")["m"].min()
    out = {d: {} for d in dates}

    # 1-minute chart
    s1, a1 = side_and_age(df["c"], df["v"])
    r1 = rsi(df["c"])
    at_close = df["m"] == 389
    cl = df[at_close]
    for ts, row in cl.iterrows():
        d = row["date"]
        out[d].update({"close": row["c"], "rsi": r1.loc[ts], "last_dir": int(np.sign(row["c"] - row["o"])),
                       "last_vol": row["v"], "side_1m": s1.loc[ts], "age_1m": int(a1.loc[ts])})

    # higher timeframes, candles anchored at 09:30
    for name, n in TFS.items():
        b = df.assign(k=df["m"] // n).groupby(["date", "k"]).agg(
            o=("o", "first"), c=("c", "last"), v=("v", "sum"))
        s, a = side_and_age(b["c"], b["v"])
        b = b.assign(side=s, age=a, col=np.sign(b["c"] - b["o"]))
        lastb = b.groupby(level=0).tail(1)
        for (d, k), row in lastb.iterrows():
            out[d].update({f"side_{name}": row["side"], f"age_{name}": row["age"], f"col_{name}": row["col"]})

    # next-day outcomes from the 09:30 open
    rows_out = []
    lv_hist = []
    for i, d in enumerate(dates):
        f = out[d]
        ok_close = last_m.get(d) == 389 and "close" in f
        if ok_close:
            ref = np.median(lv_hist[-10:]) if len(lv_hist) >= 5 else np.nan
            f["last_vol_ratio"] = f["last_vol"] / ref if ref and ref > 0 else np.nan
            lv_hist.append(f["last_vol"])
        if not ok_close or i + 1 >= len(dates):
            continue
        nd = dates[i + 1]
        if first_m.get(nd) != 0:
            continue
        b = df[(df["date"] == nd) & (df["m"] < 30)].set_index("m").reindex(range(30))
        b["c"] = b["c"].ffill()
        for c in ("o", "h", "l"):
            b[c] = b[c].fillna(b["c"])
        o = b["o"].iloc[0]
        rec = {"date": str(d), "next_date": str(nd), **f, "gap_pct": (o / f["close"] - 1) * 100}
        for mm in (1, 5, 15, 30):
            w = b.iloc[:mm]
            rec[f"ret_{mm}"] = (w["c"].iloc[-1] / o - 1) * 100
            rec[f"hi_{mm}"] = (w["h"].max() / o - 1) * 100
            rec[f"lo_{mm}"] = (w["l"].min() / o - 1) * 100
        rows_out.append(rec)
    return rows_out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2026-07-01")
    ap.add_argument("--end", default=None)
    a = ap.parse_args()
    end = a.end or str(pd.Timestamp.now(tz=NY).date())
    inst = data.instruments()
    syms = sorted({y.replace("-", ".") for y in inst.loc[inst["market"] == "us", "yahoo"]})
    sess = requests.Session()
    sess.headers.update({"APCA-API-KEY-ID": os.environ["ALPACA_KEY"],
                         "APCA-API-SECRET-KEY": os.environ["ALPACA_SECRET"]})
    start_ts = pd.Timestamp(a.start, tz=NY).tz_convert("UTC").isoformat()
    # free plan: SIP data from the last 15 minutes is not allowed, so never ask past now - 20 min
    end_ts = min(pd.Timestamp(end, tz=NY) + pd.Timedelta(hours=23),
                 pd.Timestamp.now(tz=NY) - pd.Timedelta(minutes=20)).tz_convert("UTC").isoformat()
    allrows, t0 = [], time.time()
    for i in range(0, len(syms), 20):
        batch = syms[i:i + 20]
        got = fetch(sess, batch, start_ts, end_ts)
        for sym, rows in got.items():
            try:
                for r in facts(rows):
                    r["ticker"] = sym.replace(".", "-")
                    allrows.append(r)
            except Exception as exc:
                print("  failed", sym, exc)
        print(f"{i + len(batch)}/{len(syms)} shares, {len(allrows)} rows, {time.time() - t0:.0f}s", flush=True)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    pd.DataFrame(allrows).round(4).to_csv(OUT, index=False, compression="gzip")
    print("saved", OUT)


if __name__ == "__main__":
    main()
