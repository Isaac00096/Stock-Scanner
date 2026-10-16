"""
Daily scanner: checks every instrument Trade Nation offers (markets/instruments.csv:
US, JSE, UK and European shares, indices, forex, commodities, crypto) for setups that
triggered on the latest close. Each signal carries the statistics its setup earned
IN THAT MARKET (docs/setups.json), and only setups validated (or on the paper-trade
watchlist) in that market are shown. Writes the morning dashboard (docs/index.html).

Usage:
    python scanner.py
    python scanner.py --csv-dir data/     # local daily CSVs instead of Yahoo (files named by Yahoo symbol)
"""

import argparse
import datetime as dt
import json
import os

import config
import dashboard
import data
import indicators
from setups import SETUPS, levels, signals


def load_validation() -> dict | None:
    path = os.path.join(config.OUTPUT_DIR, config.SETUPS_JSON)
    if not os.path.exists(path):
        return None
    with open(path) as fh:
        return json.load(fh)


def market_stats(validation: dict | None, market: str) -> dict:
    if not validation:
        return {}
    if "markets" in validation:
        return validation["markets"].get(market, {}).get("setups", {})
    return validation.get("setups", {}) if market == "us" else {}   # old single-market file


def exit_rule_text(s) -> str:
    if s.name.startswith("bounce"):
        return "sell on first close above 5-day average"
    if s.exit_signal:
        return "close below 25-day MA (3-day lead)"
    return ""


def scan_instrument(row, ind, setups_stats) -> list[dict]:
    last = ind.iloc[-1]
    hits = []
    for s in SETUPS:
        if not signals(ind, s).iloc[-1]:
            continue
        st = setups_stats.get(s.name, {})
        status = st.get("status", "unvalidated")
        if status not in ("validated", "watchlist") and not config.SHOW_UNVALIDATED:
            continue
        px, a = float(last["Close"]), float(last["ATR14"])
        sign = 1 if s.direction == "long" else -1
        lv = levels(ind, s)
        lv = lv.iloc[-1] if lv is not None else {}
        entry = float(lv["limit"]) if s.is_limit else px
        stop, target = lv.get("stop", float("nan")), lv.get("target", float("nan"))
        if stop != stop:
            stop = entry * (1 - sign * s.stop_pct) if s.stop_pct is not None else entry - sign * s.stop_atr * a
        if target != target:
            target = (entry * (1 + sign * s.target_pct) if s.target_pct is not None
                      else entry + sign * s.target_atr * a)
        hit = {"ticker": row.tn_symbol, "yahoo": row.yahoo, "name": row.name, "market": row.market,
               "tradingview": row.tradingview if isinstance(row.tradingview, str) else row.tn_symbol,
               "price": px, "setup": s.label, "direction": s.direction, "status": status,
               "oos": st.get("oos", {}), "max_hold": s.max_hold,
               "kind": "limit" if s.is_limit else "open",
               "entry": entry, "stop": float(stop),
               # trend-following exits (no fixed target) show the exit rule instead
               "target": None if (s.target_pct or 0) >= 5 else float(target),
               "exit_rule": exit_rule_text(s)}
        if s.is_limit:
            hit["distance_pct"] = (px - entry) / px * 100
        else:
            # Tested entering at the next open. Before the open, use a day buy limit at the last close
            # (tested separately as the "buy limit at last close" versions); during market hours you can
            # buy manually as long as the price is at or below it.
            hit["limit_hint"] = px
        hits.append(hit)
    return hits


FX_SYMBOLS = {"USDZAR=X": "usd", "GBPZAR=X": "gbp", "EURZAR=X": "eur"}


def zar_per(ccy, fx, pairs):
    """Rand value of 1 unit of a currency, from tonight's forex closes."""
    usd = fx.get("usd")
    if ccy == "ZAR":
        return 1.0
    if ccy == "USD":
        return usd
    if ccy == "GBP" and fx.get("gbp"):
        return fx["gbp"]
    if ccy == "EUR" and fx.get("eur"):
        return fx["eur"]
    if usd and pairs.get("USD" + ccy):
        return usd / pairs["USD" + ccy]
    if usd and pairs.get(ccy + "USD"):
        return usd * pairs[ccy + "USD"]
    return None


def add_rand_risk(hits, fx, pairs=None):
    """risk_zar_1 = rand lost at the stop with Amount 1.0 (1 share for shares; 1.0 contract for CFDs).
    min_qty = smallest Amount we size with. Left blank where the contract size isn't known."""
    pairs = pairs or {}
    for h in hits:
        per_unit = abs(h["entry"] - h["stop"])
        m, tn, z, mq, unit = h["market"], h["ticker"], None, config.MIN_QTY, "share"
        if m == "us" and fx.get("usd"):
            z = per_unit * fx["usd"]
        elif m == "jse":
            z = per_unit / 100                       # JSE prices are in cents
        elif m == "uk" and fx.get("gbp"):
            z = per_unit / 100 * fx["gbp"]           # UK prices are in pence
        elif m == "eu" and fx.get("eur") and h["yahoo"].endswith((".DE", ".PA", ".AS", ".MC", ".MI", ".BR", ".HE", ".LS")):
            z = per_unit * fx["eur"]
        elif m == "forex" and len(tn) == 6:
            c, rate = config.CFD["forex"], zar_per(tn[3:], fx, pairs)    # profit is in the second currency
            if rate:
                z, mq, unit = per_unit * c["per_point"] * rate, c["min"], "amount"
        elif m == "index" and tn in config.INDEX_CCY:
            c, rate = config.CFD["index"], zar_per(config.INDEX_CCY[tn], fx, pairs)
            if rate:
                z, mq, unit = per_unit * c["per_point"] * rate, c["min"], "amount"
        elif m == "commodity" and tn in config.CFD["commodity"] and fx.get("usd"):
            c = config.CFD["commodity"][tn]
            z, mq, unit = per_unit * c["per_point"] * fx["usd"], c["min"], "amount"
        h["risk_zar_1"], h["min_qty"], h["unit"] = z, mq, unit
        h["stop_pct"] = per_unit / h["entry"] * 100 if h["entry"] else None


def pick_top(hits, n):
    """Best validated signals for the 'today's plan' cards: one per instrument, highest win chance."""
    seen, picks = set(), []
    max_risk = config.ACCOUNT_ZAR * config.RISK_PER_TRADE_PCT / 100

    def too_big(h):
        r = h.get("risk_zar_1")
        return r is None or r * h.get("min_qty", config.MIN_QTY) > max_risk

    for h in sorted([h for h in hits if h["status"] == "validated"],
                    key=lambda h: (too_big(h), -(h["oos"].get("win_rate") or 0), -(h["oos"].get("avg") or 0))):
        if h["ticker"] in seen:
            continue
        seen.add(h["ticker"])
        picks.append(h)
        if len(picks) == n:
            break
    return picks


def add_news(picks):
    """Recent headlines and the next earnings date for each pick (free, via Yahoo). Politics and
    company news can override any chart pattern, so these are shown as warnings next to the trade."""
    try:
        import yfinance as yf
    except Exception:
        return
    today = dt.date.today()
    for h in picks:
        h["news"], h["earnings"] = [], None
        try:
            t = yf.Ticker(h["yahoo"])
            for item in (t.news or [])[:3]:
                c = item.get("content", item)
                title = c.get("title")
                url = (c.get("canonicalUrl") or {}).get("url") if isinstance(c.get("canonicalUrl"), dict) else c.get("link")
                when = c.get("pubDate") or c.get("providerPublishTime")
                if title:
                    h["news"].append({"title": title, "url": url, "when": str(when)[:10]})
            if h["market"] in ("us", "jse", "uk", "eu"):
                cal = t.calendar or {}
                dates = cal.get("Earnings Date") if isinstance(cal, dict) else None
                if dates:
                    d0 = min(d for d in dates if d is not None)
                    if hasattr(d0, "date"):
                        d0 = d0.date() if callable(getattr(d0, "date")) else d0
                    if d0 >= today:
                        h["earnings"] = str(d0)
        except Exception as exc:
            print(f"  news/earnings lookup failed for {h['yahoo']}: {exc}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv-dir", default=None)
    args = ap.parse_args()

    validation = load_validation()
    if not validation:
        print("No setups.json yet — run validate.py first.")

    inst = data.instruments()
    if inst.empty:
        raise SystemExit(f"ERROR: {config.INSTRUMENTS_FILE} missing — run markets/build_instruments.py")
    if args.csv_dir:
        inst = inst[inst["yahoo"].isin(set(data.csv_tickers(args.csv_dir)))]

    hits, errors, as_of, fx, pairs = [], 0, None, {}, {}
    scanned = {m: 0 for m in config.MARKETS}
    for m, cfg in config.MARKETS.items():
        rows = inst[inst["market"] == m]
        if rows.empty:
            continue
        print(f"[{cfg['label']}] scanning {len(rows)} instruments...")
        bench = data.load_benchmark(cfg["benchmark"], config.SCAN_PERIOD, args.csv_dir)
        stats = market_stats(validation, m)
        by_symbol = {r.yahoo: r for r in rows.itertuples(index=False)}
        for sym, df in data.iter_daily(list(by_symbol), config.SCAN_PERIOD, args.csv_dir):
            if df.empty or len(df) < 210:
                errors += 1
                continue
            if cfg["liquidity"] and not data.liquid(df):
                continue
            if sym in FX_SYMBOLS:
                fx[FX_SYMBOLS[sym]] = float(df["Close"].iloc[-1])
            if m == "forex":
                pairs[by_symbol[sym].tn_symbol] = float(df["Close"].iloc[-1])
            scanned[m] += 1
            ind = indicators.compute_all(df, bench)
            as_of = max(as_of, ind.index[-1]) if as_of is not None else ind.index[-1]
            hits += scan_instrument(by_symbol[sym], ind, stats)

    add_rand_risk(hits, fx, pairs)
    picks = pick_top(hits, config.TOP_PICKS)
    if not args.csv_dir:
        add_news(picks)
    os.makedirs(config.OUTPUT_DIR, exist_ok=True)
    dashboard.render_instruments(data.instruments(), os.path.join(config.OUTPUT_DIR, "instruments.html"))
    dashboard.render(hits, scanned=scanned, errors=errors, as_of=as_of, validation=validation,
                     out_path=os.path.join(config.OUTPUT_DIR, config.DASHBOARD_FILE), picks=picks, fx=fx)
    print(f"Done. {len(hits)} signal(s) across {sum(1 for v in scanned.values() if v)} market(s).")


if __name__ == "__main__":
    main()
