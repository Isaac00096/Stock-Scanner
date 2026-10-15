"""
Weekly validator: tests every setup in setups.py on years of history and
decides which ones have earned a probability on the dashboard.

For each setup it measures:
  - in-sample (older data) and out-of-sample (last OOS_YEARS, never used to judge the rules)
  - win rate with a 95% confidence range, average return per trade after costs,
    profit factor, t-statistic
  - a baseline: same exits and direction but entered on RANDOM days.
    The setup must beat this, or its "edge" is just the market's drift.

Every market Trade Nation offers (US, JSE, UK, European shares, indices, forex,
commodities, crypto) is tested SEPARATELY, with its own trading-cost assumption.

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
from setups import SETUPS, exit_mask, levels, signals


def pick_tickers(csv_dir: str | None) -> list[str]:
    tickers = data.csv_tickers(csv_dir) if csv_dir else universe.get_universe()
    n = config.VALIDATION_SAMPLE_SIZE
    if n and len(tickers) > n:
        tickers = sorted(random.Random(config.VALIDATION_SEED).sample(tickers, n))
    return tickers


def judge(is_s: dict, oos_s: dict, base_s: dict, base_is: dict | None = None) -> tuple[str, list[str]]:
    if oos_s.get("n", 0) < config.MIN_TRADES_OOS:
        return "insufficient", [f"only {oos_s.get('n', 0)} out-of-sample trades (need {config.MIN_TRADES_OOS})"]
    reasons = []
    if not base_s.get("n"):
        reasons.append("no random-entry baseline to compare against")
    if oos_s["avg"] <= 0:
        reasons.append("loses money out-of-sample after costs")
    edge_t = engine.edge_tstat(oos_s, base_s)
    oos_s["edge"] = oos_s["avg"] - base_s.get("avg", 0.0)
    oos_s["edge_t"] = edge_t
    edge_short = base_s.get("n") and edge_t < config.MIN_EDGE_TSTAT
    if edge_short:
        reasons.append(f"edge over random entries ({oos_s['edge']:+.2f}%/trade) isn't clearly real (t {edge_t:.1f}, need {config.MIN_EDGE_TSTAT})")
    if is_s.get("n", 0) == 0 or is_s["avg"] <= 0:
        reasons.append("wasn't profitable in-sample either")
    elif base_is and base_is.get("n") and is_s["avg"] <= base_is["avg"]:
        reasons.append("didn't beat random entries in the older data (edge not consistent)")
    if oos_s["tstat"] < config.MIN_TSTAT:
        reasons.append(f"t-stat {oos_s['tstat']:.1f} below {config.MIN_TSTAT} (could be luck)")
    if not reasons:
        return "validated", []
    # near-miss: the edge test is the only thing it failed, and it still beats random entries
    if len(reasons) == 1 and edge_short and edge_t >= config.WATCHLIST_EDGE_TSTAT:
        return "watchlist", reasons
    return "failed", reasons


def f(v, suffix="", d=2):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "–"
    return f"{v:.{d}f}{suffix}"


ORDER = {"validated": 0, "watchlist": 1, "failed": 2, "insufficient": 3}


def _table(setups: dict) -> str:
    rows = []
    for name, r in sorted(setups.items(),
                          key=lambda kv: (ORDER[kv[1]["status"]], -(kv[1]["oos"].get("avg") or -99))):
        o, b, i = r["oos"], r["baseline_oos"], r["in_sample"]
        win = f"{f(o.get('win_rate'), '%', 1)} <span class='muted'>({f(o.get('win_lo'), '', 0)}–{f(o.get('win_hi'), '%', 0)})</span>" if o.get("n") else "–"
        notes = "; ".join(r["reasons"]) or "passed all checks"
        rows.append(
            f"<tr><td><b>{html.escape(r['label'])}</b><div class='muted small'>{html.escape(r['description'])}</div></td>"
            f"<td><span class='st {r['status']}'>{r['status']}</span></td>"
            f"<td>{o.get('n', 0)}</td><td>{win}</td><td>{f(o.get('avg'), '%')}</td>"
            f"<td>{f(b.get('avg'), '%')}</td><td>{f(o.get('edge'), '%')} <span class='muted'>(t {f(o.get('edge_t'), '', 1)})</span></td>"
            f"<td>{f(i.get('avg'), '%')}</td><td class='small'>{html.escape(notes)}</td></tr>")
    return ("<div class='wrap'><table><tr><th>Setup</th><th>Status</th><th>OOS trades</th><th>Chance of a win</th>"
            "<th>Avg / trade</th><th>Random entries</th><th>Edge vs random</th><th>In-sample avg</th><th>Notes</th></tr>"
            + "".join(rows) + "</table></div>")


def render(result: dict, path: str) -> None:
    summary, sections = [], []
    for m, res in result["markets"].items():
        sets = res["setups"]
        nv = sum(r["status"] == "validated" for r in sets.values())
        nw = sum(r["status"] == "watchlist" for r in sets.values())
        summary.append(f"<tr><td><a href='#{m}'>{html.escape(res['label'])}</a></td><td>{res['tickers_tested']}</td>"
                       f"<td class='{'v' if nv else 'muted'}'>{nv}</td><td>{nw}</td><td>{res['cost']}%</td></tr>")
        period = f"{res['start']} → {res['end']}" if res["start"] else "no data"
        sections.append(f"<h2 id='{m}'>{html.escape(res['label'])}</h2><div class='muted small'>{res['tickers_tested']} instruments · "
                        f"{period} · cost {res['cost']}% per side</div>{_table(sets)}")

    page = f"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Setup Validation</title>
<style>
 body{{margin:0;padding:28px 18px 60px;background:#0f1117;color:#e8e9ed;font-family:-apple-system,"Segoe UI",Helvetica,Arial,sans-serif}}
 h1{{font-size:22px;margin:0 0 6px}} h2{{font-size:18px;margin:36px 0 4px}} a{{color:#8fb4ff}} .muted{{color:#9098a8}} .small{{font-size:12px}}
 .v{{color:#2fbf71;font-weight:700}}
 .box{{background:#171a23;border:1px solid #262b38;border-radius:8px;padding:14px 16px;margin:18px 0;line-height:1.5;font-size:14px;max-width:900px}}
 .wrap{{overflow-x:auto;margin-top:10px}} table{{border-collapse:collapse;font-size:14px}}
 th,td{{text-align:left;padding:9px 10px;border-bottom:1px solid #262b38;vertical-align:top}}
 th{{color:#9098a8;font-size:12px;text-transform:uppercase}}
 .st{{padding:2px 9px;border-radius:999px;font-size:12px;font-weight:600}}
 .validated{{background:rgba(47,191,113,.15);color:#2fbf71}} .failed{{background:rgba(229,72,77,.15);color:#e5484d}}
 .insufficient{{background:rgba(144,152,168,.15);color:#9098a8}}
 .watchlist{{background:rgba(214,169,74,.15);color:#d6a94a}}
</style></head><body>
<h1>Setup Validation</h1>
<div class="muted">Generated {result['generated']} · out-of-sample from {result['split_date']} ·
<a href="index.html">← dashboard</a> · <a href="rules.html">trading rules</a></div>
<div class="box"><b>How to read this.</b> Every setup is tested separately in each market Trade Nation offers.
Older data is the in-sample test; the most recent {config.OOS_YEARS} years (out-of-sample) is the number that counts.
"Chance of a win" is how often past trades made money, with the 95% range in brackets. "Random entries" is the same
trade taken on random days; a setup has to beat it. Only <b>validated</b> setups give trade signals in that market;
<b>watchlist</b> setups appear marked "paper trade only". Returns are per trade, after that market's cost.
<br><br><span class="muted">Caveats: only instruments listed today are tested (delisted losers are missing, which
flatters results); small markets (indices, commodities, crypto) have few instruments, so most setups there will show
"insufficient" until more history builds up. Past results don't guarantee future ones.</span></div>
<div class="wrap"><table><tr><th>Market</th><th>Instruments</th><th>Validated</th><th>Watchlist</th><th>Cost/side</th></tr>
{''.join(summary)}</table></div>
{''.join(sections)}
</body></html>"""
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(page)


def validate_market(tickers, benchmark, cost, use_liquidity, split, rng, csv_dir):
    """Runs every setup on one market's instruments. Returns (setup results, tested, start, end)."""
    trades = {s.name: [] for s in SETUPS}
    base = {s.name: [] for s in SETUPS}
    tested, start, end = 0, None, None
    for ticker, df in data.iter_daily(tickers, config.VALIDATION_PERIOD, csv_dir):
        if df.empty or len(df) < 300 or (use_liquidity and not data.liquid(df)):
            continue
        tested += 1
        start = min(start, df.index[0]) if start is not None else df.index[0]
        end = max(end, df.index[-1]) if end is not None else df.index[-1]
        ind = indicators.compute_all(df, benchmark)
        ready = np.flatnonzero((ind["SMA200"].notna() & ind["ATR14"].notna()).to_numpy())
        for s in SETUPS:
            lv, xm = levels(ind, s), exit_mask(ind, s)
            trades[s.name] += engine.simulate(ind, signals(ind, s).to_numpy(), s, cost, lv, xm)
            # baseline: same entry/exit mechanics on random days. For limit setups, only days
            # where the same kind of order could have been placed.
            pool = ready
            if lv is not None:
                placeable = lv.notna().all(axis=1)
                if "limit" in lv:
                    placeable &= lv["limit"] <= ind["Close"]
                pool = np.intersect1d(ready, np.flatnonzero(placeable.to_numpy()))
            if len(pool):
                mask = np.zeros(len(ind), bool)
                mask[rng.choice(pool, min(config.BASELINE_SAMPLES_PER_TICKER, len(pool)), replace=False)] = True
                base[s.name] += engine.simulate(ind, mask, s, cost, lv, xm)

    out = {}
    for s in SETUPS:
        is_r = [t["ret"] for t in trades[s.name] if t["date"] < split]
        oos_r = [t["ret"] for t in trades[s.name] if t["date"] >= split]
        b_r = [t["ret"] for t in base[s.name] if t["date"] >= split]
        b_is = engine.stats([t["ret"] for t in base[s.name] if t["date"] < split])
        is_s, oos_s, b_s = engine.stats(is_r), engine.stats(oos_r), engine.stats(b_r)
        status, reasons = judge(is_s, oos_s, b_s, b_is)
        out[s.name] = {"label": s.label, "direction": s.direction, "description": s.description,
                       "stop_atr": s.stop_atr, "target_atr": s.target_atr, "max_hold": s.max_hold,
                       "entry": "limit" if s.is_limit else "next open",
                       "status": status, "reasons": reasons,
                       "in_sample": is_s, "oos": oos_s, "baseline_oos": b_s}
    return out, tested, start, end


def market_tickers(market: str, csv_dir: str | None) -> list[str]:
    inst = data.instruments()
    tickers = inst.loc[inst["market"] == market, "yahoo"].tolist()
    if market == "us" and config.US_VALIDATE_WITH_NYSE and not csv_dir:
        tickers = sorted(set(tickers) | set(pick_tickers(csv_dir)))
    if csv_dir:
        have = set(data.csv_tickers(csv_dir))
        tickers = [t for t in tickers if t in have]
    return tickers


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv-dir", default=None)
    ap.add_argument("--markets", default=None, help="comma-separated subset, e.g. us,jse")
    args = ap.parse_args()

    split = pd.Timestamp(dt.date.today()) - pd.DateOffset(years=config.OOS_YEARS)
    rng = np.random.default_rng(config.VALIDATION_SEED)
    wanted = args.markets.split(",") if args.markets else list(config.MARKETS)

    markets = {}
    for m in wanted:
        cfg = config.MARKETS[m]
        tickers = market_tickers(m, args.csv_dir)
        print(f"\n[{cfg['label']}] validating {len(SETUPS)} setups on {len(tickers)} instruments...")
        if not tickers:
            continue
        bench = data.load_benchmark(cfg["benchmark"], config.VALIDATION_PERIOD, args.csv_dir)
        out, tested, start, end = validate_market(tickers, bench, cfg["cost"], cfg["liquidity"],
                                                  split, rng, args.csv_dir)
        markets[m] = {"label": cfg["label"], "cost": cfg["cost"], "tickers_tested": tested,
                      "start": str(start.date()) if start is not None else "",
                      "end": str(end.date()) if end is not None else "", "setups": out}
        good = [r["label"] for r in out.values() if r["status"] == "validated"]
        print(f"  {tested} instruments with data · validated: {', '.join(good) or 'none'}")

    if not markets:
        raise SystemExit("ERROR: no market had usable data.")

    result = {"generated": dt.datetime.now().strftime("%Y-%m-%d %H:%M"), "split_date": str(split.date()),
              "markets": markets}
    # backwards compatibility: top-level "setups" = US results
    first = markets.get("us") or next(iter(markets.values()))
    result.update({"setups": first["setups"], "tickers_tested": first["tickers_tested"],
                   "start": first["start"], "end": first["end"]})
    os.makedirs(config.OUTPUT_DIR, exist_ok=True)
    with open(os.path.join(config.OUTPUT_DIR, config.SETUPS_JSON), "w") as fh:
        json.dump(result, fh, indent=1)
    render(result, os.path.join(config.OUTPUT_DIR, config.VALIDATION_FILE))
    tot_v = sum(r["status"] == "validated" for mk in markets.values() for r in mk["setups"].values())
    print(f"\nDone. {tot_v} setup/market combination(s) validated across {len(markets)} market(s).")


if __name__ == "__main__":
    main()
