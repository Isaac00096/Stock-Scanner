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

    tickers = data.csv_tickers(args.csv_dir) if args.csv_dir else universe.get_universe()
    if not tickers:
        raise SystemExit("ERROR: no tickers to scan.")
    print(f"Scanning {len(tickers)} tickers...")

    hits, errors, scanned, as_of = [], 0, 0, None
    for ticker, df in data.iter_daily(tickers, config.SCAN_PERIOD, args.csv_dir):
        if df.empty or len(df) < 210:
            errors += 1
            continue
        if not data.liquid(df):
            continue
        scanned += 1
        ind = indicators.compute_all(df)
        last = ind.iloc[-1]
        as_of = max(as_of, ind.index[-1]) if as_of is not None else ind.index[-1]
        for s in SETUPS:
            if not signals(ind, s).iloc[-1]:
                continue
            st = vstats.get(s.name, {})
            status = st.get("status", "unvalidated")
            if status != "validated" and not config.SHOW_UNVALIDATED:
                continue
            px, a = float(last["Close"]), float(last["ATR14"])
            sign = 1 if s.direction == "long" else -1
            hit = {"ticker": ticker, "price": px, "setup": s.label, "direction": s.direction,
                   "status": status, "oos": st.get("oos", {}), "max_hold": s.max_hold,
                   "kind": "limit" if s.is_limit else "open"}
            if s.is_limit:
                lv = levels(ind, s).iloc[-1]
                entry = float(lv["limit"])
                stop = lv.get("stop", float("nan"))
                target = lv.get("target", float("nan"))
                hit["entry"] = entry
                hit["stop"] = float(stop) if stop == stop else entry - sign * s.stop_atr * a
                hit["target"] = float(target) if target == target else entry + sign * s.target_atr * a
                hit["distance_pct"] = (px - entry) / px * 100
            else:
                hit["entry"] = px
                hit["stop"] = px - sign * s.stop_atr * a
                hit["target"] = px + sign * s.target_atr * a
            hits.append(hit)

    validated_names = [v["label"] for v in vstats.values() if v["status"] == "validated"]
    os.makedirs(config.OUTPUT_DIR, exist_ok=True)
    dashboard.render(hits, scanned=scanned, errors=errors, as_of=as_of,
                     validation=validation, validated_names=validated_names,
                     out_path=os.path.join(config.OUTPUT_DIR, config.DASHBOARD_FILE))
    print(f"Done. {len(hits)} signal(s). Dashboard: {os.path.join(config.OUTPUT_DIR, config.DASHBOARD_FILE)}")


if __name__ == "__main__":
    main()
