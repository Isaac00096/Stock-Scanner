"""
Backtest: "fade the opening pop" setup.

THE SETUP (your theory, made mechanical):
  Day D (signal day):
    1. Closing volume spike: in the last SPIKE_WINDOW_MIN minutes of the session,
       one bar's volume is > SPIKE_MULT x that day's median bar volume.
    2. That spike bar is green (buyers pushing into the close)  [optional].
    3. Higher timeframe is bearish: on HTF_RULE bars (default 30-min),
       VWMA(HTF_FAST) < VWMA(HTF_SLOW) at the close of day D.
  Day D+1 (trade day):
    4. Optional: the open gaps up above D's close / the first bar is green (the "pop").
    5. SHORT at the close of the first ENTRY_AFTER_MIN minutes.
    6. Exit at whichever comes first: stop (STOP_PCT above entry), target
       (TARGET_PCT below entry), or EXIT_TIME.

It also runs a BASELINE: the exact same trade taken on EVERY day with no
signal filter. If the signal doesn't beat the baseline, the "edge" is just
whatever the stock did anyway.

Usage:
    python backtest.py                       # Hyatt (H), 5-min data, last ~60 days
    python backtest.py --ticker H --interval 1m
    python backtest.py --csv mydata.csv      # use your own intraday data instead
"""

import argparse
import html
import os
import sys

import numpy as np
import pandas as pd

# =========================================================================
# SETUP PARAMETERS — edit these to test variations of your theory
# =========================================================================
TICKER = "H"                  # Hyatt Hotels on NYSE
INTERVAL = "5m"               # "5m" (~60 days history) or "1m" (~30 days)

SPIKE_WINDOW_MIN = 10         # look for the spike in the last N minutes of the session
SPIKE_MULT = 3.0              # spike bar volume must exceed N x the day's median bar volume
REQUIRE_GREEN_SPIKE = True    # spike bar must close above its open

HTF_RULE = "30min"            # higher timeframe to judge the trend on
HTF_FAST = 20                 # VWMA fast period (on HTF bars)
HTF_SLOW = 200                # VWMA slow period (on HTF bars) — 200 x 30min ≈ 15 trading days warm-up
REQUIRE_HTF_BEARISH = True    # VWMA fast < VWMA slow at the signal day's close

REQUIRE_GAP_UP = False        # trade day must open above the signal day's close
REQUIRE_OPEN_POP = True       # trade day's first bar must be green

ENTRY_AFTER_MIN = 5           # short at the close of the first N minutes (09:30 + N)
STOP_PCT = 0.75               # stop loss, % above entry
TARGET_PCT = 1.00             # take profit, % below entry
EXIT_TIME = "11:30"           # time exit if neither stop nor target hit

SLIPPAGE_PCT = 0.02           # cost per side, % (spread + slippage)

OUTPUT_DIR = "docs"
REPORT_FILE = "backtest.html"
TRADES_FILE = "backtest_trades.csv"
# =========================================================================

TZ = "America/New_York"
SESSION_OPEN = pd.Timedelta(hours=9, minutes=30)
SESSION_CLOSE = pd.Timedelta(hours=16)


# ------------------------------------------------------------------ data
def _clean(df: pd.DataFrame) -> pd.DataFrame:
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df[["Open", "High", "Low", "Close", "Volume"]].copy()
    if df.index.tz is None:
        df.index = df.index.tz_localize(TZ)
    else:
        df.index = df.index.tz_convert(TZ)
    df = df[~df.index.duplicated(keep="last")].sort_index().dropna()
    tod = df.index - df.index.normalize()
    return df[(tod >= SESSION_OPEN) & (tod < SESSION_CLOSE)]


def load_data(ticker: str, interval: str, csv_path: str | None) -> pd.DataFrame:
    if csv_path:
        df = pd.read_csv(csv_path, index_col=0, parse_dates=True)
        return _clean(df)

    import yfinance as yf

    if interval == "1m":
        # Yahoo serves 1-min data in <=7-day chunks, max ~30 days back
        frames, end = [], pd.Timestamp.now(tz="UTC")
        for _ in range(4):
            start = end - pd.Timedelta(days=7)
            try:
                f = yf.download(ticker, start=start, end=end, interval="1m",
                                progress=False, auto_adjust=False, prepost=False)
                if not f.empty:
                    frames.append(f)
            except Exception as exc:
                print(f"note: 1m chunk ending {end.date()} unavailable ({exc})", file=sys.stderr)
            end = start
        if not frames:
            return pd.DataFrame()
        df = pd.concat(frames)
    else:
        df = yf.download(ticker, period="60d", interval=interval,
                         progress=False, auto_adjust=False, prepost=False)
    if df.empty:
        return df
    return _clean(df)


# ------------------------------------------------------------ indicators
def htf_vwma(df: pd.DataFrame) -> pd.DataFrame:
    htf = df.resample(HTF_RULE).agg(
        {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}
    ).dropna()
    pv = htf["Close"] * htf["Volume"]
    for n, col in ((HTF_FAST, "VWMA_FAST"), (HTF_SLOW, "VWMA_SLOW")):
        htf[col] = pv.rolling(n).sum() / htf["Volume"].rolling(n).sum()
    return htf


def signal_for_day(day_bars: pd.DataFrame, htf: pd.DataFrame) -> dict:
    """Evaluate the signal-day conditions. Returns a dict of what passed."""
    day = day_bars.index[0].normalize()
    cutoff = day + SESSION_CLOSE - pd.Timedelta(minutes=SPIKE_WINDOW_MIN)
    window = day_bars[day_bars.index >= cutoff]
    info = {"spike": False, "green": False, "htf_bearish": False, "spike_ratio": np.nan}
    if window.empty:
        return info

    median_vol = day_bars["Volume"].median()
    spike_bar = window.loc[window["Volume"].idxmax()]
    if median_vol > 0:
        info["spike_ratio"] = spike_bar["Volume"] / median_vol
        info["spike"] = info["spike_ratio"] > SPIKE_MULT
    info["green"] = spike_bar["Close"] > spike_bar["Open"]

    htf_day = htf[(htf.index >= day) & (htf.index < day + pd.Timedelta(days=1))]
    if not htf_day.empty:
        last = htf_day.iloc[-1]
        if pd.notna(last["VWMA_FAST"]) and pd.notna(last["VWMA_SLOW"]):
            info["htf_bearish"] = last["VWMA_FAST"] < last["VWMA_SLOW"]
            info["htf_ready"] = True
    return info


def signal_passes(info: dict) -> bool:
    if not info["spike"]:
        return False
    if REQUIRE_GREEN_SPIKE and not info["green"]:
        return False
    if REQUIRE_HTF_BEARISH and not info["htf_bearish"]:
        return False
    return True


# -------------------------------------------------------------- trading
def simulate_short(day_bars: pd.DataFrame, prev_close: float) -> dict | None:
    day = day_bars.index[0].normalize()
    first = day_bars.iloc[0]

    if REQUIRE_GAP_UP and first["Open"] <= prev_close:
        return None
    if REQUIRE_OPEN_POP and first["Close"] <= first["Open"]:
        return None

    entry_cutoff = day + SESSION_OPEN + pd.Timedelta(minutes=ENTRY_AFTER_MIN)
    opening = day_bars[day_bars.index < entry_cutoff]
    if opening.empty:
        return None

    entry = opening["Close"].iloc[-1] * (1 - SLIPPAGE_PCT / 100)
    stop = entry * (1 + STOP_PCT / 100)
    target = entry * (1 - TARGET_PCT / 100)

    h, m = map(int, EXIT_TIME.split(":"))
    exit_cutoff = day + pd.Timedelta(hours=h, minutes=m)
    after = day_bars[(day_bars.index >= entry_cutoff) & (day_bars.index < exit_cutoff)]

    exit_px, reason = None, "time"
    for _, bar in after.iterrows():
        # conservative: if a bar touches both, assume the stop hit first
        if bar["High"] >= stop:
            exit_px, reason = stop, "stop"
            break
        if bar["Low"] <= target:
            exit_px, reason = target, "target"
            break
    if exit_px is None:
        exit_px = after["Close"].iloc[-1] if not after.empty else entry

    exit_px *= 1 + SLIPPAGE_PCT / 100
    return {
        "date": day.date().isoformat(),
        "entry": round(float(entry), 2),
        "exit": round(float(exit_px), 2),
        "exit_reason": reason,
        "return_pct": round(float((entry - exit_px) / entry * 100), 3),
    }


def stats(trades: list[dict]) -> dict:
    if not trades:
        return {"n": 0}
    r = pd.Series([t["return_pct"] for t in trades])
    wins, losses = r[r > 0], r[r <= 0]
    equity = r.cumsum()
    drawdown = (equity - equity.cummax()).min()
    pf = wins.sum() / abs(losses.sum()) if losses.sum() != 0 else np.inf
    return {
        "n": len(r),
        "win_rate": 100 * len(wins) / len(r),
        "avg": r.mean(),
        "median": r.median(),
        "total": r.sum(),
        "profit_factor": pf,
        "max_dd": drawdown,
        "best": r.max(),
        "worst": r.min(),
    }


# --------------------------------------------------------------- report
def verdict(sig: dict, base: dict) -> str:
    if sig["n"] == 0:
        return ("The setup never triggered in the available history. Try loosening "
                "SPIKE_MULT or turning off REQUIRE_GREEN_SPIKE / REQUIRE_OPEN_POP, "
                "or test on more tickers.")
    parts = []
    if sig["n"] < 30:
        parts.append(f"Only {sig['n']} trade(s) — far too few to trust. Treat any result "
                     "below as anecdotal, not evidence. You'd want 30+ at minimum, ideally 100+.")
    if base["n"] and sig["avg"] > base["avg"] and sig["avg"] > 0:
        parts.append("The signal trades averaged better than shorting every day blindly, "
                     "which is what you'd hope to see if the pattern has an edge.")
    elif base["n"]:
        parts.append("The signal did NOT beat the baseline of shorting every day — on this "
                     "data, the filter isn't adding an edge.")
    return " ".join(parts)


def fmt(v, suffix="%"):
    if isinstance(v, (int, np.integer)):
        return str(v)
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "–"
    if np.isinf(v):
        return "∞"
    return f"{v:.2f}{suffix}"


def render(ticker, df, sig_trades, base_trades, sig_stats, base_stats, days_eval, out_path):
    params = {
        "Data": f"{INTERVAL} bars, {df.index[0].date()} → {df.index[-1].date()} ({days_eval} days evaluated)",
        "Closing spike": f"bar in last {SPIKE_WINDOW_MIN} min > {SPIKE_MULT}× day's median volume"
                         + (", green" if REQUIRE_GREEN_SPIKE else ""),
        "Trend filter": f"{HTF_RULE} VWMA{HTF_FAST} < VWMA{HTF_SLOW}" if REQUIRE_HTF_BEARISH else "off",
        "Trade-day filter": ", ".join(x for x in [
            "gap up" if REQUIRE_GAP_UP else "", "green first bar" if REQUIRE_OPEN_POP else ""] if x) or "none",
        "Trade": f"short at 09:30+{ENTRY_AFTER_MIN}min, stop +{STOP_PCT}%, target −{TARGET_PCT}%, "
                 f"time exit {EXIT_TIME}, {SLIPPAGE_PCT}% cost/side",
    }
    param_rows = "".join(f"<tr><td class='k'>{html.escape(k)}</td><td>{html.escape(v)}</td></tr>"
                         for k, v in params.items())

    metric_rows = ""
    for label, key, suf in [("Trades", "n", ""), ("Win rate", "win_rate", "%"),
                            ("Avg return / trade", "avg", "%"), ("Median return", "median", "%"),
                            ("Total return (sum)", "total", "%"), ("Profit factor", "profit_factor", ""),
                            ("Max drawdown", "max_dd", "%"), ("Best trade", "best", "%"),
                            ("Worst trade", "worst", "%")]:
        metric_rows += (f"<tr><td class='k'>{label}</td>"
                        f"<td>{fmt(sig_stats.get(key), suf)}</td>"
                        f"<td>{fmt(base_stats.get(key), suf)}</td></tr>")

    trade_rows = "".join(
        f"<tr><td>{t['date']}</td><td>{t['signal_day']}</td><td>{t['spike_ratio']:.1f}×</td>"
        f"<td>${t['entry']:.2f}</td><td>${t['exit']:.2f}</td><td>{t['exit_reason']}</td>"
        f"<td class='{'pos' if t['return_pct'] > 0 else 'neg'}'>{t['return_pct']:+.2f}%</td></tr>"
        for t in sig_trades
    ) or "<tr><td colspan='7' class='muted'>No signal trades.</td></tr>"

    page = f"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Backtest — {html.escape(ticker)}</title>
<style>
 body{{margin:0;padding:28px 20px 60px;background:#0f1117;color:#e8e9ed;
  font-family:-apple-system,"Segoe UI",Helvetica,Arial,sans-serif;max-width:1000px}}
 h1{{font-size:22px;margin:0 0 4px}} h2{{font-size:15px;margin:32px 0 10px;color:#9098a8;
  text-transform:uppercase;letter-spacing:.05em}}
 .verdict{{background:#171a23;border:1px solid #262b38;border-left:4px solid #d6a94a;
  border-radius:8px;padding:14px 16px;line-height:1.5}}
 .wrap{{overflow-x:auto}} table{{width:100%;border-collapse:collapse;font-size:14px}}
 th,td{{text-align:left;padding:8px 10px;border-bottom:1px solid #262b38;white-space:nowrap}}
 th{{color:#9098a8;font-size:12px;text-transform:uppercase}} .k{{color:#9098a8}}
 .pos{{color:#2fbf71;font-weight:600}} .neg{{color:#e5484d;font-weight:600}} .muted{{color:#9098a8}}
</style></head><body>
<h1>Backtest: fade the opening pop — {html.escape(ticker)}</h1>
<div class="muted">Generated {pd.Timestamp.now(tz=TZ).strftime('%Y-%m-%d %H:%M')} ET</div>
<h2>Verdict</h2><div class="verdict">{html.escape(verdict(sig_stats, base_stats))}</div>
<h2>Setup tested</h2><div class="wrap"><table>{param_rows}</table></div>
<h2>Results</h2><div class="wrap"><table>
<tr><th></th><th>With your signal</th><th>Baseline (short every day)</th></tr>{metric_rows}</table></div>
<h2>Signal trades</h2><div class="wrap"><table>
<tr><th>Trade day</th><th>Signal day</th><th>Spike</th><th>Entry</th><th>Exit</th><th>Exit reason</th><th>Return</th></tr>
{trade_rows}</table></div>
<p class="muted" style="margin-top:28px;font-size:12px">Historical simulation on free Yahoo Finance data.
Past results don't guarantee future results; not financial advice.</p>
</body></html>"""
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(page)


# ----------------------------------------------------------------- main
def main():
    global INTERVAL
    ap = argparse.ArgumentParser()
    ap.add_argument("--ticker", default=TICKER)
    ap.add_argument("--interval", default=INTERVAL, choices=["1m", "5m"])
    ap.add_argument("--csv", default=None, help="optional CSV of intraday OHLCV (datetime index, NY time)")
    args = ap.parse_args()
    INTERVAL = args.interval

    print(f"Loading {args.ticker} {args.interval} data...")
    df = load_data(args.ticker, args.interval, args.csv)
    if df.empty:
        sys.exit("ERROR: no data returned. Check the ticker and your connection.")

    htf = htf_vwma(df)
    days = sorted(df.index.normalize().unique())
    by_day = {d: df[df.index.normalize() == d] for d in days}

    sig_trades, base_trades, days_eval = [], [], 0
    for d, nxt in zip(days[:-1], days[1:]):
        today, tomorrow = by_day[d], by_day[nxt]
        if today.empty or tomorrow.empty:
            continue
        info = signal_for_day(today, htf)
        if REQUIRE_HTF_BEARISH and not info.get("htf_ready"):
            continue  # still in indicator warm-up
        days_eval += 1

        trade = simulate_short(tomorrow, prev_close=today["Close"].iloc[-1])
        if trade is None:
            continue
        base_trades.append(trade)
        if signal_passes(info):
            sig_trades.append({**trade, "signal_day": d.date().isoformat(),
                               "spike_ratio": float(info["spike_ratio"])})

    sig_stats, base_stats = stats(sig_trades), stats(base_trades)

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    render(args.ticker, df, sig_trades, base_trades, sig_stats, base_stats, days_eval,
           os.path.join(OUTPUT_DIR, REPORT_FILE))
    pd.DataFrame(sig_trades).to_csv(os.path.join(OUTPUT_DIR, TRADES_FILE), index=False)

    print(f"\nDays evaluated: {days_eval}")
    print(f"Signal trades: {sig_stats['n']}  |  Baseline trades: {base_stats['n']}")
    if sig_stats["n"]:
        print(f"Signal: win {sig_stats['win_rate']:.1f}%, avg {sig_stats['avg']:+.2f}%/trade")
    if base_stats["n"]:
        print(f"Baseline: win {base_stats['win_rate']:.1f}%, avg {base_stats['avg']:+.2f}%/trade")
    print(f"Report: {os.path.abspath(os.path.join(OUTPUT_DIR, REPORT_FILE))}")


if __name__ == "__main__":
    main()
