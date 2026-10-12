"""
Renders the morning dashboard:
  1. Limit orders for the next session (prices you wait for; no chasing the open)
  2. Setups that triggered at the close (entered at the next open)
Each row carries the setup's validated out-of-sample statistics.
"""

import datetime as dt
import html


def _f(v, suffix="", d=1):
    return "–" if v is None else f"{v:.{d}f}{suffix}"


def _win(o):
    if not o.get("n"):
        return "<span class='muted'>–</span>"
    return (f"<b>{_f(o.get('win_rate'), '%')}</b> "
            f"<span class='muted'>({_f(o.get('win_lo'), '', 0)}–{_f(o.get('win_hi'), '%', 0)})</span>")


def _tgt(h):
    if h.get("target") is None:
        return f"<span class='muted'>{html.escape(h.get('exit_rule') or 'exit rule')}</span>"
    return f"${h['target']:.2f}"


def _ticker(h):
    url = f"https://www.tradingview.com/chart/?symbol={html.escape(h['ticker'])}"
    badge = "" if h["status"] == "validated" else f" <span class='st'>{h['status']}</span>"
    return (f"<td class='tk'><a href='{url}' target='_blank' rel='noopener'>{html.escape(h['ticker'])}</a></td>",
            badge)


def _limit_table(rows):
    out = []
    for h in sorted(rows, key=lambda h: h.get("distance_pct", 99)):
        tk, badge = _ticker(h)
        o = h["oos"]
        out.append(
            f"<tr>{tk}<td>{html.escape(h['setup'])}{badge}</td>"
            f"<td class='hl'>${h['entry']:.2f}</td><td>{h['distance_pct']:.1f}% below</td>"
            f"<td>${h['stop']:.2f}</td><td>{_tgt(h)}</td><td>{h['max_hold']}d</td>"
            f"<td>{_win(o)}</td><td>{_f(o.get('avg'), '%', 2)}</td><td>{o.get('n', '–')}</td>"
            f"<td>${h['price']:.2f}</td></tr>")
    return ("<div class='wrap'><table><tr><th>Ticker</th><th>Setup</th><th>Buy limit</th><th>Distance</th>"
            "<th>Stop</th><th>Target</th><th>Max hold</th><th>Win rate (95% range)</th><th>Avg / trade</th>"
            "<th>Past trades</th><th>Last close</th></tr>" + "".join(out) + "</table></div>")


def _open_table(rows):
    out = []
    for h in sorted(rows, key=lambda h: -(h["oos"].get("avg") or -99)):
        tk, badge = _ticker(h)
        o = h["oos"]
        out.append(
            f"<tr>{tk}<td><span class='dir {h['direction']}'>{h['direction'].upper()}</span></td>"
            f"<td>{html.escape(h['setup'])}{badge}</td><td>{_win(o)}</td>"
            f"<td>{_f(o.get('avg'), '%', 2)}</td><td>{o.get('n', '–')}</td>"
            f"<td>${h['price']:.2f}</td><td>${h['stop']:.2f}</td><td>{_tgt(h)}</td>"
            f"<td>{h['max_hold']}d</td></tr>")
    return ("<div class='wrap'><table><tr><th>Ticker</th><th>Dir</th><th>Setup</th><th>Win rate (95% range)</th>"
            "<th>Avg / trade</th><th>Past trades</th><th>Last close</th><th>Stop</th><th>Target</th>"
            "<th>Max hold</th></tr>" + "".join(out) + "</table></div>")


def render(hits, scanned, errors, as_of, validation, validated_names, out_path):
    limit_rows = [h for h in hits if h.get("kind") == "limit"]
    open_rows = [h for h in hits if h.get("kind") != "limit"]

    limit_block = (_limit_table(limit_rows) if limit_rows else
                   "<div class='empty'>No limit orders from validated setups for the next session.</div>")
    open_block = (_open_table(open_rows) if open_rows else
                  "<div class='empty'>No validated setups triggered on the latest close.</div>")

    if validation:
        vline = (f"{len(validated_names)} of {len(validation['setups'])} setups validated "
                 f"(last validated {html.escape(validation['generated'])}) · <a href='validation.html'>see all setups →</a>"
                 " · <a href='rules.html'>trading rules</a>")
    else:
        vline = "Setups not validated yet — run the validation workflow first."

    date = as_of.date() if as_of is not None else "–"
    page = f"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Morning Scan</title>
<style>
 body{{margin:0;padding:28px 18px 60px;background:#0f1117;color:#e8e9ed;font-family:-apple-system,"Segoe UI",Helvetica,Arial,sans-serif}}
 h1{{font-size:22px;margin:0 0 6px}} h2{{font-size:17px;margin:34px 0 4px}} a{{color:#8fb4ff}} .muted{{color:#9098a8}}
 .sub{{color:#9098a8;font-size:14px;margin-bottom:6px}} .lead{{color:#9098a8;font-size:13px;max-width:760px;line-height:1.5}}
 .wrap{{overflow-x:auto;margin-top:12px}} table{{border-collapse:collapse;font-size:14px;min-width:900px;width:100%}}
 th,td{{text-align:left;padding:10px;border-bottom:1px solid #262b38;white-space:nowrap}}
 th{{color:#9098a8;font-size:12px;text-transform:uppercase}}
 .tk a{{color:#e8e9ed;font-weight:700;text-decoration:none}} .hl{{color:#2fbf71;font-weight:700}}
 .dir{{font-size:11px;font-weight:700;padding:2px 8px;border-radius:999px}}
 .long{{background:rgba(47,191,113,.15);color:#2fbf71}} .short{{background:rgba(229,72,77,.15);color:#e5484d}}
 .st{{font-size:11px;padding:1px 7px;border-radius:999px;background:rgba(214,169,74,.15);color:#d6a94a}}
 .empty{{margin-top:12px;color:#9098a8;padding:28px;text-align:center;border:1px dashed #262b38;border-radius:10px}}
 .note{{margin-top:28px;font-size:12px;color:#9098a8;line-height:1.5;max-width:800px}}
</style></head><body>
<h1>Morning Scan</h1>
<div class="sub">Based on the close of {date} · {scanned} liquid tickers scanned · {len(limit_rows)} limit order(s) · {len(open_rows)} open signal(s)</div>
<div class="sub">{vline}</div>

<h2>Limit orders for the next session</h2>
<div class="lead">Place a <b>day</b> buy limit order at the price shown before the US open (15:30 SA time).
If the price dips to it, you're filled; if not, the order expires and there's no trade. Once filled,
set the stop and target, and close the trade after the max hold if neither is hit.
Sorted by how close the price already is.</div>
{limit_block}

<h2>Triggered at the close (enter at the next open)</h2>
<div class="lead">These were tested entering at the next day's open price.</div>
{open_block}

<div class="note">Win rate and average return come from the out-of-sample test (recent years the rules were not
tuned on). Historical frequencies, not predictions. Not financial advice.
{f'<br>{errors} ticker(s) skipped for missing data.' if errors else ''}</div>
<div class="muted" style="font-size:12px;margin-top:8px">Generated {dt.datetime.now().strftime('%Y-%m-%d %H:%M')}</div>
</body></html>"""
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(page)
