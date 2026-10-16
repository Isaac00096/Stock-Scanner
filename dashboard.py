"""
Renders the morning dashboard, grouped by market (US, JSE, UK, Europe, indices, forex,
commodities, crypto). Only instruments Trade Nation offers are scanned, and each signal
shows the statistics its setup earned in that market.
"""

import datetime as dt
import html

import config


def _f(v, suffix="", d=1):
    return "–" if v is None else f"{v:.{d}f}{suffix}"


def _px(v, market):
    """Price in the instrument's own units: $ for US shares, cents for JSE, pence for UK."""
    if v is None:
        return "–"
    d = 5 if market == "forex" and abs(v) < 20 else 2
    u = config.MARKETS.get(market, {}).get("units", "")
    if u == "$":
        return f"${v:,.{d}f}"
    if u in ("c", "p"):
        return f"{v:,.{d}f}{u}"
    return f"{v:,.{d}f}"


def _zar(v):
    return "–" if v is None else f"R{v:,.0f}"


def _goal_box():
    try:
        days_left = max(1, int((dt.date.fromisoformat(config.GOAL_DATE) - dt.date.today()).days * 5 / 7))
    except Exception:
        days_left = 1
    growth = config.GOAL_ZAR / config.ACCOUNT_ZAR
    per_day = (growth ** (1 / days_left) - 1) * 100
    max_risk = config.ACCOUNT_ZAR * config.RISK_PER_TRADE_PCT / 100
    return f"""<div class='goal'><b>Your account:</b> R{config.ACCOUNT_ZAR:,.0f} &nbsp;→&nbsp; goal R{config.GOAL_ZAR:,.0f} by {config.GOAL_DATE}
<span class='muted'>({growth:.0f}× in about {days_left} trading days = <b>+{per_day:.1f}% every trading day</b>)</span><br>
<span class='muted'>For comparison, today's best tested setups average roughly +0.3% to +1% <i>per trade</i>. Trading alone is very
unlikely to reach this goal safely; adding deposits is the realistic route. Safe size: risk at most
<b>R{max_risk:,.0f}</b> per trade ({config.RISK_PER_TRADE_PCT:g}% of your account).</span></div>"""


def _fit(h):
    """(fits_account, html). Size = the most you can buy while risking at most RISK_PER_TRADE_PCT."""
    risk = h.get("risk_zar_1")
    max_risk = config.ACCOUNT_ZAR * config.RISK_PER_TRADE_PCT / 100
    if risk is None:
        return None, ("<span class='bad'>Size unknown for this market: on the order screen, choose a size whose loss at the "
                      f"stop is at most {_zar(max_risk)}. If the smallest size loses more, don't trade it.</span>")
    qty = max_risk / risk if risk else 0
    min_loss = risk * config.MIN_QTY
    if qty >= config.MIN_QTY:
        q = int(qty / config.MIN_QTY) * config.MIN_QTY
        return True, (f"<span class='ok'><b>Your size: {q:g} share(s).</b> Loss if the stop is hit: about "
                      f"{_zar(risk * q)} (within your {_zar(max_risk)} limit).</span>")
    return False, (f"<span class='bad'><b>Too big for your account. Don't use real money.</b> Even the smallest size "
                   f"({config.MIN_QTY:g} share) loses about {_zar(min_loss)} at the stop, which is "
                   f"{min_loss / config.ACCOUNT_ZAR * 100:.0f}% of your account (your limit is {_zar(max_risk)}). "
                   f"Paper trade it on demo instead.</span>")


def _card(i, h):
    m, o = h["market"], h["oos"]
    cfg = config.MARKETS[m]
    entry = h["entry"] if h["kind"] == "limit" else h.get("limit_hint", h["price"])
    when = OPEN_TIMES.get(m, "next session")
    if h.get("target") is not None:
        exit_txt = f"Take profit at <b>{_px(h['target'], m)}</b>"
    else:
        exit_txt = f"No fixed take profit: <b>{html.escape(h.get('exit_rule') or 'exit rule')}</b>"
    exit_txt += f", or close after <b>{h['max_hold']} trading days</b> if neither happens."
    fits, fit = _fit(h)
    news = ""
    if h.get("earnings"):
        news += f"<div class='warn'>Earnings report due <b>{html.escape(h['earnings'])}</b>: results can move the price sharply, whatever the chart says.</div>"
    if h.get("news"):
        items = "".join(f"<li><a href='{html.escape(n['url'] or '#')}' target='_blank' rel='noopener'>{html.escape(n['title'])}</a>"
                        f" <span class='muted'>{html.escape(n['when'])}</span></li>" for n in h["news"])
        news += f"<div class='news'><b>Latest news</b> (check for political or company events before trading):<ul>{items}</ul></div>"
    return f"""<div class='card'>
<div class='ct'><span class='num'>{i}</span> <b>BUY {html.escape(str(h.get('name') or h['ticker']))}</b>
<span class='sym'>{html.escape(h['ticker'])} · {html.escape(cfg['label'])}</span></div>
<div class='why'>{html.escape(h['setup'])}: won <b>{_f(o.get('win_rate'), '%')}</b> of {o.get('n', 0):,} past trades in this market,
averaging <b>{_f(o.get('avg'), '%', 2)}</b> per trade after costs.</div>
<ol>
<li><b>Before the {html.escape(when)}:</b> place a <b>BUY LIMIT</b> order at <b class='hl'>{_px(entry, m)}</b>, Expiry <b>Day</b>
<span class='muted'>(if only GTC is offered, cancel it yourself tonight if it hasn't filled)</span>.
<br><span class='muted'>Market already open? Buy now only if the price is at or below {_px(entry, m)}. If it never gets there, skip it.</span></li>
<li><b>Stop loss:</b> {_px(h['stop'], m)} <span class='muted'>({_f(h.get('stop_pct'), '%')} below entry)</span>. Set it on the order.</li>
<li><b>Exit:</b> {exit_txt}</li>
</ol>
<div class='fit'>{fit}</div>{news}</div>"""


def render_instruments(inst, path):
    """'What you can trade' page: every Trade Nation instrument the scanner covers, by market."""
    blocks = []
    for m, cfg in config.MARKETS.items():
        rows = inst[inst["market"] == m]
        if rows.empty:
            continue
        cells = "".join(f"<tr><td><b>{html.escape(r.tn_symbol)}</b></td><td>{html.escape(str(r.name))}</td>"
                        f"<td class='muted'>{html.escape(r.yahoo)}</td></tr>" for r in rows.itertuples())
        blocks.append(f"<details><summary>{html.escape(cfg['label'])} <span class='cnt'>{len(rows)}</span></summary>"
                      f"<table><tr><th>Trade Nation</th><th>Name</th><th>Data symbol</th></tr>{cells}</table></details>")
    page = f"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>What You Can Trade</title>
<style>body{{margin:0;padding:28px 18px 60px;background:#0f1117;color:#e8e9ed;font-family:-apple-system,"Segoe UI",Helvetica,Arial,sans-serif}}
a{{color:#8fb4ff}} .muted{{color:#9098a8}} .cnt{{color:#9098a8;font-weight:400;font-size:13px}}
summary{{cursor:pointer;font-size:17px;font-weight:700;padding:12px 0;border-bottom:1px solid #262b38}}
table{{border-collapse:collapse;font-size:14px;margin:8px 0 18px}} td,th{{text-align:left;padding:6px 12px 6px 0;border-bottom:1px solid #1d212c}}
th{{color:#9098a8;font-size:12px;text-transform:uppercase}}</style></head><body>
<h1 style="font-size:22px">What you can trade</h1>
<div class="muted" style="margin-bottom:14px">{len(inst)} Trade Nation instruments the scanner checks every night ·
<a href="index.html">← morning scan</a> · source: markets/trade_nation_raw.csv in the repo</div>
{''.join(blocks)}</body></html>"""
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(page)


def _win(o):
    if not o.get("n"):
        return "<span class='muted'>–</span>"
    return (f"<b>{_f(o.get('win_rate'), '%')}</b> "
            f"<span class='muted'>({_f(o.get('win_lo'), '', 0)}–{_f(o.get('win_hi'), '%', 0)})</span>")


def _tgt(h):
    if h.get("target") is None:
        return f"<span class='muted'>{html.escape(h.get('exit_rule') or 'exit rule')}</span>"
    return _px(h["target"], h["market"])


def _ticker(h):
    url = f"https://www.tradingview.com/chart/?symbol={html.escape(str(h['tradingview']))}"
    label = {"watchlist": "paper trade only"}.get(h["status"], h["status"])
    badge = "" if h["status"] == "validated" else f" <span class='st'>{label}</span>"
    cell = (f"<td class='tk'><a href='{url}' target='_blank' rel='noopener'>{html.escape(h['ticker'])}</a>"
            f"<div class='nm'>{html.escape(str(h.get('name') or ''))}</div></td>")
    return cell, badge


def _sort_key(h):
    return (h["status"] != "validated", -(h["oos"].get("win_rate") or 0), -(h["oos"].get("avg") or -99))


def _limit_table(rows):
    out = []
    for h in sorted(rows, key=lambda h: _sort_key(h) + (h.get("distance_pct", 99),)):
        tk, badge = _ticker(h)
        o, m = h["oos"], h["market"]
        out.append(
            f"<tr>{tk}<td>{html.escape(h['setup'])}{badge}</td>"
            f"<td class='hl'>{_px(h['entry'], m)}</td><td>{h['distance_pct']:.1f}% below</td>"
            f"<td>{_px(h['stop'], m)}</td><td>{_tgt(h)}</td><td>{h['max_hold']}d</td>"
            f"<td>{_win(o)}</td><td>{_f(o.get('avg'), '%', 2)}</td><td>{o.get('n', '–')}</td>"
            f"<td>{_px(h['price'], m)}</td></tr>")
    return ("<div class='wrap'><table><tr><th>Trade Nation symbol</th><th>Setup</th><th>Buy limit</th><th>Distance</th>"
            "<th>Stop</th><th>Target / exit</th><th>Max hold</th><th>Chance of a win (95% range)</th><th>Avg / trade</th>"
            "<th>Past trades</th><th>Last close</th></tr>" + "".join(out) + "</table></div>")


def _open_table(rows):
    out = []
    for h in sorted(rows, key=_sort_key):
        tk, badge = _ticker(h)
        o, m = h["oos"], h["market"]
        out.append(
            f"<tr>{tk}<td><span class='dir {h['direction']}'>{h['direction'].upper()}</span></td>"
            f"<td>{html.escape(h['setup'])}{badge}</td><td>{_win(o)}</td>"
            f"<td>{_f(o.get('avg'), '%', 2)}</td><td>{o.get('n', '–')}</td>"
            f"<td class='hl'>{_px(h.get('limit_hint', h['price']), m)}</td><td>{_px(h['stop'], m)}</td><td>{_tgt(h)}</td>"
            f"<td>{h['max_hold']}d</td><td>{_zar(h.get('risk_zar_1'))}</td></tr>")
    return ("<div class='wrap'><table><tr><th>Trade Nation symbol</th><th>Dir</th><th>Setup</th><th>Chance of a win (95% range)</th>"
            "<th>Avg / trade</th><th>Past trades</th><th>Buy limit</th><th>Stop</th><th>Target / exit</th>"
            "<th>Max hold</th><th>Loss at stop, 1 share</th></tr>" + "".join(out) + "</table></div>")


OPEN_TIMES = {"us": "US open, 15:30 SA time", "jse": "JSE open, 09:00 SA time", "uk": "London open, 09:00 SA time",
              "eu": "European open, 09:00 SA time", "index": "next session", "forex": "next session",
              "commodity": "next session", "crypto": "next session (trades 24/7)"}


def _market_section(m, rows, scanned, validated_here):
    cfg = config.MARKETS[m]
    limit_rows = [h for h in rows if h["kind"] == "limit"]
    open_rows = [h for h in rows if h["kind"] != "limit"]
    parts = [f"<details id='{m}'><summary>{html.escape(cfg['label'])} <span class='cnt'>{len(rows)} signal(s)</span></summary>"
             f"<div class='lead'>{scanned} instruments scanned · {validated_here} setup(s) validated in this market · "
             f"orders for the {OPEN_TIMES.get(m, 'next session')}"
             + (" · prices in cents, as on the JSE" if m == "jse" else "")
             + (" · prices in pence" if m == "uk" else "") + "</div>"]
    if limit_rows:
        parts.append("<h3>Limit orders</h3>" + _limit_table(limit_rows))
    if open_rows:
        parts.append("<h3>Next-session entries</h3>" + _open_table(open_rows))
    parts.append("</details>")
    return "".join(parts)


def render(hits, scanned, errors, as_of, validation, out_path, picks=None, fx=None):
    by_market = {m: [h for h in hits if h["market"] == m] for m in config.MARKETS}
    vmk = (validation or {}).get("markets", {})

    def n_valid(m):
        return sum(r["status"] == "validated" for r in vmk.get(m, {}).get("setups", {}).values())

    sections, chips = [], []
    for m, cfg in config.MARKETS.items():
        rows = by_market[m]
        if not scanned.get(m):
            continue
        chips.append(f"<a class='chip{' on' if rows else ''}' href='#{m}'>{html.escape(cfg['label'])} · {len(rows)}</a>")
        if rows:
            sections.append(_market_section(m, rows, scanned[m], n_valid(m)))
    empty_markets = [config.MARKETS[m]["label"] for m in config.MARKETS if scanned.get(m) and not by_market[m]]

    if validation:
        vline = (f"Last validated {html.escape(validation['generated'])} · "
                 "<a href='validation.html'>results by market →</a> · <a href='rules.html'>trading rules</a>")
    else:
        vline = "Setups not validated yet — run the validation workflow first."

    picks = picks or []
    fit_picks = [h for h in picks if _fit(h)[0] is not False]
    big_picks = [h for h in picks if _fit(h)[0] is False]
    if fit_picks:
        plan = "".join(_card(i, h) for i, h in enumerate(fit_picks, 1))
    else:
        plan = ("<div class='empty'><b>No trade fits your account today.</b> Every tested signal would risk more than "
                f"{config.RISK_PER_TRADE_PCT:g}% of your balance, even at the smallest size. Don't place real orders today.</div>")
    if big_picks:
        plan += ("<h3 class='bigh'>Too big for your account: paper trade only (demo)</h3>"
                 + "".join(_card(i, h) for i, h in enumerate(big_picks, len(fit_picks) + 1)))
    details = "".join(sections) or "<div class='empty'>No signals from validated setups on the latest close, in any market.</div>"
    fx_line = " · ".join(f"{k.upper()}/ZAR {v:.2f}" for k, v in (fx or {}).items())
    date = as_of.date() if as_of is not None else "–"
    page = f"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Morning Scan</title>
<style>
 body{{margin:0;padding:28px 18px 60px;background:#0f1117;color:#e8e9ed;font-family:-apple-system,"Segoe UI",Helvetica,Arial,sans-serif}}
 h1{{font-size:22px;margin:0 0 6px}} h2{{font-size:19px;margin:38px 0 4px}} h3{{font-size:14px;margin:18px 0 0;color:#c8ccd6}}
 a{{color:#8fb4ff}} .muted{{color:#9098a8}}
 .sub{{color:#9098a8;font-size:14px;margin-bottom:6px}} .lead{{color:#9098a8;font-size:13px;max-width:780px;line-height:1.5}}
 .chips{{display:flex;flex-wrap:wrap;gap:8px;margin:14px 0 4px}}
 .chip{{font-size:13px;padding:5px 11px;border-radius:999px;border:1px solid #262b38;color:#9098a8;text-decoration:none}}
 .chip.on{{color:#e8e9ed;border-color:#3b4560;background:#171a23}}
 .cnt{{font-size:13px;color:#9098a8;font-weight:400}}
 .wrap{{overflow-x:auto;margin-top:8px}} table{{border-collapse:collapse;font-size:14px;min-width:900px;width:100%}}
 th,td{{text-align:left;padding:9px 10px;border-bottom:1px solid #262b38;white-space:nowrap;vertical-align:top}}
 th{{color:#9098a8;font-size:12px;text-transform:uppercase}}
 .tk a{{color:#e8e9ed;font-weight:700;text-decoration:none}} .nm{{font-size:11px;color:#9098a8;max-width:180px;overflow:hidden;text-overflow:ellipsis}}
 .hl{{color:#2fbf71;font-weight:700}}
 .dir{{font-size:11px;font-weight:700;padding:2px 8px;border-radius:999px}}
 .long{{background:rgba(47,191,113,.15);color:#2fbf71}} .short{{background:rgba(229,72,77,.15);color:#e5484d}}
 .st{{font-size:11px;padding:1px 7px;border-radius:999px;background:rgba(214,169,74,.15);color:#d6a94a}}
 .empty{{margin-top:18px;color:#9098a8;padding:28px;text-align:center;border:1px dashed #262b38;border-radius:10px}}
 .note{{margin-top:32px;font-size:12px;color:#9098a8;line-height:1.5;max-width:800px}}
 .goal{{background:#171a23;border:1px solid #262b38;border-left:4px solid #8fb4ff;border-radius:10px;padding:14px 16px;margin:16px 0;line-height:1.55;font-size:14px;max-width:820px}}
 .card{{background:#171a23;border:1px solid #262b38;border-radius:12px;padding:16px 18px;margin:12px 0;max-width:820px;line-height:1.55;font-size:14px}}
 .ct{{font-size:17px;margin-bottom:6px}} .num{{display:inline-block;width:24px;height:24px;border-radius:50%;background:#2fbf71;color:#0f1117;text-align:center;font-weight:700;font-size:14px;line-height:24px}}
 .sym{{color:#9098a8;font-size:13px;margin-left:6px}} .why{{color:#c8ccd6;margin-bottom:6px}}
 .card ol{{padding-left:20px;margin:8px 0}} .card li{{margin:6px 0}}
 .bigh{{color:#e5a14a;margin-top:26px}} .ok{{color:#2fbf71}} .bad{{color:#e5a14a}} .fit{{margin-top:8px}}
 .warn{{margin-top:10px;padding:8px 10px;border-radius:8px;background:rgba(229,72,77,.12);color:#f0a0a3}}
 .news{{margin-top:10px;font-size:13px}} .news ul{{margin:4px 0;padding-left:18px}}
 details{{max-width:1200px}} summary{{cursor:pointer;font-size:17px;font-weight:700;padding:14px 0;border-bottom:1px solid #262b38}}
</style></head><body>
<h1>Morning Scan</h1>
<div class="sub">Based on the close of {date} · {sum(scanned.values())} Trade Nation instruments checked · {len(hits)} signal(s){' · ' + fx_line if fx_line else ''}</div>
<div class="sub">{vline} · <a href='instruments.html'>what you can trade</a></div>
{_goal_box()}
<h2>Today's plan</h2>
<div class="lead">Only trades whose loss at the stop fits your account are listed first. Anything bigger is shown
separately for demo practice. If a card says <b>don't use real money</b>, don't.</div>
{plan}
<h2>All signals by market</h2>
<div class="lead">Tap a market to open it. Rows marked <span class='st'>paper trade only</span> beat random entries in testing,
but not yet convincingly: practise those on demo.</div>
<div class="chips">{''.join(chips)}</div>
{details}
<div class="note">{('No signals today in: ' + ', '.join(empty_markets) + '.<br>') if empty_markets else ''}
Chance of a win and average return come from the out-of-sample test in that market (recent years the rules were not
tuned on). Historical frequencies, not predictions. Not financial advice.
{f'<br>{errors} instrument(s) skipped for missing data.' if errors else ''}</div>
<div class="muted" style="font-size:12px;margin-top:8px">Generated {dt.datetime.now().strftime('%Y-%m-%d %H:%M')}</div>
</body></html>"""
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(page)
