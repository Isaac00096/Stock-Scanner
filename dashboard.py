"""
Renders the morning dashboard: today's signals from validated setups,
each with its historical (out-of-sample) statistics and stop/target levels.
"""

import datetime as dt
import html


def _f(v, suffix="", d=1):
    return "–" if v is None else f"{v:.{d}f}{suffix}"


def render(hits, scanned, errors, as_of, validation, validated_names, out_path):
    hits = sorted(hits, key=lambda h: (h["status"] != "validated", -(h["oos"].get("avg") or -99)))

    if hits:
        rows = []
        for h in hits:
            o = h["oos"]
            url = f"https://www.tradingview.com/chart/?symbol={html.escape(h['ticker'])}"
            win = (f"<b>{_f(o.get('win_rate'), '%')}</b> <span class='muted'>({_f(o.get('win_lo'), '', 0)}–{_f(o.get('win_hi'), '%', 0)})</span>"
                   if o.get("n") else "<span class='muted'>–</span>")
            badge = "" if h["status"] == "validated" else f" <span class='st {h['status']}'>{h['status']}</span>"
            rows.append(
                f"<tr><td class='tk'><a href='{url}' target='_blank' rel='noopener'>{html.escape(h['ticker'])}</a></td>"
                f"<td><span class='dir {h['direction']}'>{h['direction'].upper()}</span></td>"
                f"<td>{html.escape(h['setup'])}{badge}</td><td>{win}</td>"
                f"<td>{_f(o.get('avg'), '%', 2)}</td><td>{o.get('n', '–')}</td>"
                f"<td>${h['price']:.2f}</td><td>${h['stop']:.2f}</td><td>${h['target']:.2f}</td>"
                f"<td>{h['max_hold']}d</td></tr>")
        body = ("<div class='wrap'><table><tr><th>Ticker</th><th>Dir</th><th>Setup</th><th>Win rate (95% range)</th>"
                "<th>Avg / trade</th><th>Past trades</th><th>Last close</th><th>Stop</th><th>Target</th><th>Max hold</th></tr>"
                + "".join(rows) + "</table></div>")
    else:
        body = "<div class='empty'>No validated setups triggered on the latest close.</div>"

    if validation:
        vline = (f"{len(validated_names)} of {len(validation['setups'])} setups validated "
                 f"(last validated {html.escape(validation['generated'])}) · <a href='validation.html'>see all setups →</a>")
    else:
        vline = "Setups not validated yet — run the validation workflow first."

    page = f"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Morning Scan</title>
<style>
 body{{margin:0;padding:28px 18px 60px;background:#0f1117;color:#e8e9ed;font-family:-apple-system,"Segoe UI",Helvetica,Arial,sans-serif}}
 h1{{font-size:22px;margin:0 0 6px}} a{{color:#8fb4ff}} .muted{{color:#9098a8}}
 .sub{{color:#9098a8;font-size:14px;margin-bottom:6px}}
 .wrap{{overflow-x:auto;margin-top:18px}} table{{border-collapse:collapse;font-size:14px;min-width:860px;width:100%}}
 th,td{{text-align:left;padding:10px;border-bottom:1px solid #262b38;white-space:nowrap}}
 th{{color:#9098a8;font-size:12px;text-transform:uppercase}}
 .tk a{{color:#e8e9ed;font-weight:700;text-decoration:none}}
 .dir{{font-size:11px;font-weight:700;padding:2px 8px;border-radius:999px}}
 .long{{background:rgba(47,191,113,.15);color:#2fbf71}} .short{{background:rgba(229,72,77,.15);color:#e5484d}}
 .st{{font-size:11px;padding:1px 7px;border-radius:999px;background:rgba(214,169,74,.15);color:#d6a94a}}
 .empty{{margin-top:18px;color:#9098a8;padding:40px;text-align:center;border:1px dashed #262b38;border-radius:10px}}
 .note{{margin-top:28px;font-size:12px;color:#9098a8;line-height:1.5;max-width:800px}}
</style></head><body>
<h1>Morning Scan</h1>
<div class="sub">Signals from the close of {as_of.date() if as_of is not None else '–'} · {scanned} liquid tickers scanned · {len(hits)} signal(s)</div>
<div class="sub">{vline}</div>
{body}
<div class="note">Win rate and average return come from the out-of-sample test (recent years the rules were not tuned on).
Stop and target are based on the last close; the trades were tested entering at the next day's open, so adjust levels to your
actual fill. Historical frequencies, not predictions. Not financial advice.
{f'<br>{errors} ticker(s) skipped for missing data.' if errors else ''}</div>
<div class="muted" style="font-size:12px;margin-top:8px">Generated {dt.datetime.now().strftime('%Y-%m-%d %H:%M')}</div>
</body></html>"""
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(page)
