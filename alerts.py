"""Entry alerts before scheduled shocks for the small-account pairs.
Reads data/alerts/calendar.csv; for decisions due between 1 and 26 hours from now, works out today's stop and
target in pips from the pair's normal daily range (last 20 days), the entry time in SA time, and the rand risk
per side at size 0.01. Writes data/alerts/next.json and next.md (read by the daily phone-alert check).
Rules come from the hourly backtests (straddle_small.py): RBNZ -> NZD/USD opened the evening before,
stop 1 day's range, target 2x stop; US Fed -> AUD/USD opened just before, stop 0.75 day, target 2x stop."""
import json
import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd
import data

SA = ZoneInfo("Africa/Johannesburg")
YAHOO = {"NZD/USD": "NZDUSD=X", "AUD/USD": "AUDUSD=X", "AUD/NZD": "AUDNZD=X"}
EVIDENCE = {"NZD/USD": "best tested: 14 NZ decisions, avg about +R26 per straddle, worst -R53, luck test 2.8",
            "AUD/USD": "weaker evidence: 16 Fed decisions, avg about +R10 per straddle, worst -R57, luck test 1.2"}


def last_close_and_range(sym):
    for _, df in data.iter_daily([sym], "3mo"):
        d = df.dropna().tail(20)
        return float(d["Close"].iloc[-1]), float(((d["High"] - d["Low"]) / d["Close"]).median())
    return None, None


def main():
    now = datetime.now(timezone.utc)
    cal = pd.read_csv("data/alerts/calendar.csv")
    cal["t"] = pd.to_datetime(cal["time_utc"], utc=True)
    usdzar, _ = last_close_and_range("USDZAR=X")
    nzdzar, _ = last_close_and_range("NZDZAR=X")
    alerts = []
    for e in cal.itertuples():
        hours = (e.t - now).total_seconds() / 3600
        if not 1 <= hours <= 26:
            continue
        price, rng = last_close_and_range(YAHOO[e.pair])
        if price is None:
            continue
        pip = 0.0001
        range_pips = rng * price / pip
        stop = round(e.stop_day_ranges * range_pips)
        target = round(e.target_x_stop * stop)
        pip_zar = 1000 * pip * (nzdzar if e.pair.endswith("NZD") else usdzar)
        dec_sa = e.t.tz_convert(SA)
        if e.entry == "evening_before":
            entry_sa = (dec_sa - timedelta(days=1)).replace(hour=22, minute=0) if dec_sa.hour < 12 else dec_sa.replace(hour=dec_sa.hour - 5, minute=0)
        else:
            entry_sa = dec_sa - timedelta(minutes=5)
        alerts.append({
            "event": e.event, "decision_sa": dec_sa.strftime("%a %d %b %Y %H:%M"), "pair": e.pair,
            "open_both_sa": entry_sa.strftime("%a %d %b %H:%M"), "close_by_sa": (dec_sa + timedelta(hours=24)).strftime("%a %d %b %H:%M"),
            "price_now": round(price, 5), "normal_day_pips": round(range_pips), "stop_pips": stop, "target_pips": target,
            "buy_stop_at": round(price - stop * pip, 5), "buy_target_at": round(price + target * pip, 5),
            "sell_stop_at": round(price + stop * pip, 5), "sell_target_at": round(price - target * pip, 5),
            "risk_zar_per_side_001": round(stop * pip_zar), "worst_case_zar_001": round(2 * stop * pip_zar),
            "win_zar_if_target_001": round(target * pip_zar - stop * pip_zar),
            "evidence": EVIDENCE[e.pair], "alternative": e.alternative})
    os.makedirs("data/alerts", exist_ok=True)
    upcoming = cal[cal.t > now].head(4)
    out = {"generated_utc": now.strftime("%Y-%m-%d %H:%M"), "alerts": alerts,
           "next_events": [f"{r.event}: {r.t.tz_convert(SA).strftime('%a %d %b %Y %H:%M')} SA time ({r.pair})" for r in upcoming.itertuples()],
           "calendar_ends": cal["t"].max().tz_convert(SA).strftime("%d %b %Y")}
    with open("data/alerts/next.json", "w") as fh:
        json.dump(out, fh, indent=1)
    lines = []
    for a in alerts:
        lines += [f"ENTRY ALERT: {a['event']}, {a['decision_sa']} SA time",
                  f"Pair {a['pair']} at size 0.01. Open BOTH a buy and a sell at {a['open_both_sa']}; close anything left by {a['close_by_sa']}.",
                  f"Stop {a['stop_pips']} pips, target {a['target_pips']} pips on each (normal day = {a['normal_day_pips']} pips).",
                  f"At today's price {a['price_now']}: buy stop {a['buy_stop_at']} / target {a['buy_target_at']}; sell stop {a['sell_stop_at']} / target {a['sell_target_at']}. Re-set from your actual fill.",
                  f"Risk about R{a['risk_zar_per_side_001']} per side, R{a['worst_case_zar_001']} if both stop out; about +R{a['win_zar_if_target_001']} if one hits target.",
                  f"Evidence: {a['evidence']}. Practise on demo first.", ""]
    with open("data/alerts/next.md", "w") as fh:
        fh.write("\n".join(lines) if lines else "No entry alerts in the next 26 hours.\n")
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
