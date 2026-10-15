"""
Daily scanner: checks every NYSE ticker for setups that triggered on the
latest close, attaches each setup's validated statistics from
docs/setups.json, and writes the morning dashboard (docs/index.html).

Usage:
    python scanner.py
    python scanner.py --csv-dir data/     # local daily CSVs instead of Yahoo
"""

import argparse
import json
import os

import config
import dashboard
import data
import indicators
import universe
from setups import SETUPS, levels, signals


def load_validation() -> dict | None:
    path = os.path.join(config.OUTPUT_DIR, config.SETUPS_JSON)
    if not os.path.exists(path):
        return None
    with open(path) as fh:
        return json.load(fh)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv-dir", default=None)
    args = ap.parse_args()

    validation = load_validation()
    vstats = validation["setups"] if validation else {}
    if not validation:
        print("No setups.json yet — run validate.py first. Showing all triggers as unvalidated.")

    broker = universe.broker_symbols()
    if args.csv_dir:
        tickers = data.csv_tickers(args.csv_dir)
        if broker:
            tickers = [t for t in tickers if t in set(broker)]
    elif broker:
        tickers = broker
        print(f"Scanning only the {len(broker)} stocks offered by {config.BROKER_NAME}.")
    else:
        tickers = universe.get_universe()
    if not tickers:
        raise SystemExit("ERROR: no tickers to scan.")
    print(f"Scanning {len(tickers)} tickers...")

    market = data.load_market(config.SCAN_PERIOD, args.csv_dir)
    hits, errors, scanned, as_of = [], 0, 0, None
    for ticker, df in data.iter_daily(tickers, config.SCAN_PERIOD, args.csv_dir):
        if df.empty or len(df) < 210:
            errors += 1
            continue
        if not data.liquid(df):
            continue
        scanned += 1
        ind = indicators.compute_all(df, market)
        last = ind.iloc[-1]
        as_of = max(as_of, ind.index[-1]) if as_of is not None else ind.index[-1]
        for s in SETUPS:
            if not signals(ind, s).iloc[-1]:
                continue
            st = vstats.get(s.name, {})
            status = st.get("status", "unvalidated")
            if status not in ("validated", "watchlist") and not config.SHOW_UNVALIDATED:
                continue
            px, a = float(last["Close"]), float(last["ATR14"])
            sign = 1 if s.direction == "long" else -1
            hit = {"ticker": ticker, "price": px, "setup": s.label, "direction": s.direction,
                   "status": status, "oos": st.get("oos", {}), "max_hold": s.max_hold,
                   "kind": "limit" if s.is_limit else "open"}
            lv = levels(ind, s)
            lv = lv.iloc[-1] if lv is not None else {}
            entry = float(lv["limit"]) if s.is_limit else px
            stop, target = lv.get("stop", float("nan")), lv.get("target", float("nan"))
            if stop != stop:
                stop = entry * (1 - sign * s.stop_pct) if s.stop_pct is not None else entry - sign * s.stop_atr * a
            if target != target:
                target = (entry * (1 + sign * s.target_pct) if s.target_pct is not None
                          else entry + sign * s.target_atr * a)
            hit["entry"], hit["stop"] = entry, float(stop)
            # trend-following exits (no fixed target) show as "exit rule"
            hit["target"] = None if (s.target_pct or 0) >= 5 else float(target)
            hit["exit_rule"] = ("sell on first close above 5-day average" if s.name.startswith("bounce")
                                else "close below 25-day MA (3-day lead)" if s.exit_signal else "")
            if s.is_limit:
                hit["distance_pct"] = (px - entry) / px * 100
            hits.append(hit)

    validated_names = [v["label"] for v in vstats.values() if v["status"] == "validated"]
    os.makedirs(config.OUTPUT_DIR, exist_ok=True)
    dashboard.render(hits, scanned=scanned, broker=(config.BROKER_NAME if broker else None), errors=errors, as_of=as_of,
                     validation=validation, validated_names=validated_names,
                     out_path=os.path.join(config.OUTPUT_DIR, config.DASHBOARD_FILE))
    print(f"Done. {len(hits)} signal(s). Dashboard: {os.path.join(config.OUTPUT_DIR, config.DASHBOARD_FILE)}")


if __name__ == "__main__":
    main()
