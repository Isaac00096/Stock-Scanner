"""
Weekly validator: tests every setup in setups.py on years of history and
decides which ones have earned a probability on the dashboard.

For each setup it measures:
  - in-sample (older data) and out-of-sample (last OOS_YEARS, never used to judge the rules)
  - win rate with a 95% confidence range, average return per trade after costs,
    profit factor, t-statistic
  - a baseline: same exits and direction but entered on RANDOM days.
    The setup must beat this, or its "edge" is just the market's drift.

Writes docs/setups.json (read by the daily scanner) and docs/validation.html.

Usage:
    python validate.py
    python validate.py --csv-dir data/     # use local daily CSVs instead of Yahoo
"""

import argparse
import datetime as dt
import html
import json
import os
import random

import numpy as np
import pandas as pd

import config
import data
import engine
import indicators
import universe
from setups import SETUPS, signals


def pick_tickers(csv_dir: str | None) -> list[str]:
    tickers = data.csv_tickers(csv_dir) if csv_dir else universe.get_universe()
    n = config.VALIDATION_SAMPLE_SIZE
    if n and len(tickers) > n:
        tickers = sorted(random.Random(config.VALIDATION_SEED).sample(tickers, n))
    return tickers


def judge(is_s: dict, oos_s: dict, base_s: dict) -> tuple[str, list[str]]:
    if oos_s.get("n", 0) < config.MIN_TRADES_OOS:
        return "insufficient", [f"only {oos_s.get('n', 0)} out-of-sample trades (need {config.MIN_TRADES_OOS})"]
    reasons = []
    if oos_s["avg"] <= 0:
        reasons.append("loses money out-of-sample after costs")
    edge_t = engine.edge_tstat(oos_s, base_s)
    oos_s["edge"] = oos_s["avg"] - base_s.get("avg", 0.0)
    oos_s["edge_t"] = edge_t
    if base_s.get("n") and edge_t < config.MIN_EDGE_TSTAT:
        reasons.append(f"edge over random entries ({oos_s['edge']:+.2f}%/trade) isn't clearly real (t {edge_t:.1f}, need {config.MIN_EDGE_TSTAT})")
    if is_s.get("n", 0) == 0 or is_s["avg"] <= 0:
        reasons.append("wasn't profitable in-sample either")
    if oos_s["tstat"] < config.MIN_TSTAT:
        reasons.append(f"t-stat {oos_s['tstat']:.1f} below {config.MIN_TSTAT} (could be luck)")
    return ("validated", []) if not reasons else ("failed", reasons)


def f(v, suffix="", d=2):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "–"
    return f"{v:.{d}f}{suffix}"


def render(result: dict, path: str) -> None:
    order = {"validated": 0, "failed": 1, "insufficient": 2}
    rows = []
    for name, r in sorted(result["setups"].items(),
                          key=lambda kv: (order[kv[1]["status"]], -(kv[1]["oos"].get("avg") or -99))):
        o, b, i = r["oos"], r["baseline_oos"], r["in_sample"]
        win = f"{f(o.get('win_rate'), '%', 1)} <span class='muted'>({f(o.get('win_lo'), '', 0)}–{f(o.get('win_hi'), '%', 0)})</span>" if o.get("n") else "–"
        notes = "; ".join(r["reasons"]) or "passed all checks"
        rows.append(
            f"<tr><td><b>{html.escape(r['label'])}</b><div class='muted small'>{html.escape(r['description'])}</div></td>"
            f"<td>{r['direction']}</td><td><span class='st {r['status']}'>{r['status']}</span></td>"
            f"<td>{o.get('n', 0)}</td><td>{win}</td><td>{f(o.get('avg'), '%')}</td>"
            f"<td>{f(b.get('avg'), '%')}</td><td>{f(o.get('edge'), '%')} <span class='muted'>(t {f(o.get('edge_t'), '', 1)})</span></td><td>{f(o.get('tstat'), '', 1)}</td><td>{f(i.get('avg'), '%')}</td>"
            f"<td class='small'>{html.escape(notes)}</td></tr>")

    page = f"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Setup Validation</title>
<style>
 body{{margin:0;padding:28px 18px 60px;background:#0f1117;color:#e8e9ed;font-family:-apple-system,"Segoe UI",Helvetica,Arial,sans-serif}}
 h1{{font-size:22px;margin:0 0 6px}} a{{color:#8fb4ff}} .muted{{color:#9098a8}} .small{{font-size:12px}}
 .box{{background:#171a23;border:1px solid #262b38;border-radius:8px;padding:14px 16px;margin:18px 0;line-height:1.5;font-size:14px}}
 .wrap{{overflow-x:auto}} table{{border-collapse:collapse;font-size:14px;min-width:900px}}
 th,td{{text-align:left;padding:9px 10px;border-bottom:1px solid #262b38;vertical-align:top}}
 th{{color:#9098a8;font-size:12px;text-transform:uppercase}}
 .st{{padding:2px 9px;border-radius:999px;font-size:12px;font-weight:600}}
 .validated{{background:rgba(47,191,113,.15);color:#2fbf71}} .failed{{background:rgba(229,72,77,.15);color:#e5484d}}
 .insufficient{{background:rgba(214,169,74,.15);color:#d6a94a}}
</style></head><body>
<h1>Setup Validation</h1>
<div class="muted">Generated {result['generated']} · {result['tickers_tested']} tickers · {result['start']} → {result['end']} ·
out-of-sample from {result['split_date']} · <a href="index.html">← dashboard</a></div>
<div class="box"><b>How to read this.</b> Every setup is tested on older data (in-sample), then on the most recent
{config.OOS_YEARS} years (out-of-sample), which is the number that counts. "Win rate" is how often past trades made money,
with the 95% confidence range in brackets. "Baseline" is the same trade entered on random days; a setup has to beat it.
Only <b>validated</b> setups appear on the daily dashboard. Returns are per trade, after {config.COST_PCT_PER_SIDE}% cost per side.
<br><br><span class="muted">Caveats: tested only on stocks listed today (delisted losers are missing, which flatters results);
trades across many stocks on the same day move together, so the t-stat is optimistic. Past results don't guarantee future ones.</span></div>
<div class="wrap"><table><tr><th>Setup</th><th>Dir</th><th>Status</th><th>OOS trades</th><th>OOS win rate</th>
<th>OOS avg/trade</th><th>Baseline avg</th><th>Edge vs random</th><th>t-stat</th><th>In-sample avg</th><th>Notes</th></tr>{''.join(rows)}</table></div>
</body></html>"""
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(page)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv-dir", default=None)
    args = ap.parse_args()

    tickers = pick_tickers(args.csv_dir)
    if not tickers:
        raise SystemExit("ERROR: no tickers to validate.")
    print(f"Validating {len(SETUPS)} setups on {len(tickers)} tickers ({config.VALIDATION_PERIOD})...")

    split = pd.Timestamp(dt.date.today()) - pd.DateOffset(years=config.OOS_YEARS)
    trades = {s.name: [] for s in SETUPS}
    base = {s.name: [] for s in SETUPS}
    rng = np.random.default_rng(config.VALIDATION_SEED)
    tested, start, end = 0, None, None

    for ticker, df in data.iter_daily(tickers, config.VALIDATION_PERIOD, args.csv_dir):
        if df.empty or len(df) < 300 or not data.liquid(df):
            continue
        tested += 1
        start = min(start, df.index[0]) if start is not None else df.index[0]
        end = max(end, df.index[-1]) if end is not None else df.index[-1]
        ind = indicators.compute_all(df)
        ready = np.flatnonzero((ind["SMA200"].notna() & ind["ATR14"].notna()).to_numpy())
        for s in SETUPS:
            trades[s.name] += engine.simulate(ind, signals(ind, s).to_numpy(), s, config.COST_PCT_PER_SIDE)
            if len(ready):
                mask = np.zeros(len(ind), bool)
                mask[rng.choice(ready, min(config.BASELINE_SAMPLES_PER_TICKER, len(ready)), replace=False)] = True
                base[s.name] += engine.simulate(ind, mask, s, config.COST_PCT_PER_SIDE)

    if tested == 0:
        raise SystemExit("ERROR: no tickers had usable data.")

    out = {}
    for s in SETUPS:
        is_r = [t["ret"] for t in trades[s.name] if t["date"] < split]
        oos_r = [t["ret"] for t in trades[s.name] if t["date"] >= split]
        b_r = [t["ret"] for t in base[s.name] if t["date"] >= split]
        is_s, oos_s, b_s = engine.stats(is_r), engine.stats(oos_r), engine.stats(b_r)
        status, reasons = judge(is_s, oos_s, b_s)
        out[s.name] = {"label": s.label, "direction": s.direction, "description": s.description,
                       "stop_atr": s.stop_atr, "target_atr": s.target_atr, "max_hold": s.max_hold,
                       "status": status, "reasons": reasons,
                       "in_sample": is_s, "oos": oos_s, "baseline_oos": b_s}
        print(f"  {s.label:32s} {status:12s} OOS n={oos_s.get('n', 0)}")

    result = {"generated": dt.datetime.now().strftime("%Y-%m-%d %H:%M"), "tickers_tested": tested,
              "start": str(start.date()), "end": str(end.date()), "split_date": str(split.date()),
              "setups": out}
    os.makedirs(config.OUTPUT_DIR, exist_ok=True)
    with open(os.path.join(config.OUTPUT_DIR, config.SETUPS_JSON), "w") as fh:
        json.dump(result, fh, indent=1)
    render(result, os.path.join(config.OUTPUT_DIR, config.VALIDATION_FILE))
    print(f"Done. {sum(r['status'] == 'validated' for r in out.values())} setup(s) validated.")


if __name__ == "__main__":
    main()
