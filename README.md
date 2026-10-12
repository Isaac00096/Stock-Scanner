# NYSE Setup Scanner

Tests a library of technical-analysis setups on 10 years of history, keeps only
the ones that prove themselves on data they were never tuned on, and each
morning shows you which stocks triggered a validated setup, with its
historical win rate, average return, stop and target.

It never places trades. You review and decide.

## How it works

| Piece | What it does | When |
|---|---|---|
| `setups.py` | The setup library (14 setups: trend, mean-reversion, breakout/volume) | – |
| `validate.py` | Tests every setup; writes `docs/setups.json` + `docs/validation.html` | Weekly (Sat) |
| `scanner.py` | Scans NYSE, shows validated signals on `docs/index.html` | Weekdays after close |
| `backtest.py` | Separate intraday test of the "fade the opening pop" idea | Manual |

A setup is **validated** only if, on the most recent 3 years (out-of-sample):
it has 100+ trades, makes money after costs, beats random entries with the same
exits, was also profitable on the older data, and has a t-stat of 2+.
All of these are adjustable in `config.py`.

## Gartley framework

Setups and rules from H.M. Gartley, *Profits in the Stock Market* (1935): the "222" buying spot
(limit-order and confirmation versions), breakouts above a previous intermediate top, his 25-day
moving average with a 3-day lead, and a "better-than-market" filter (3-month return vs SPY).
Each is validated like every other setup. His money-management and discipline rules are
summarised on `docs/rules.html`, linked from the dashboard.

## Limit-order setups

Some setups don't enter at the open. After each close, the scanner calculates a **buy limit
price** (e.g. the exact price where RSI(2) would drop below 10, or a Fibonacci 50% / 61.8%
retracement of a fresh up-swing). The dashboard lists these under **Limit orders for the next
session**: place a day order at that price before the US open; if the price dips to it you're
filled, otherwise it expires. They are backtested the same way, filled only if the day's low
actually reached the limit, and judged against random limit orders.

## Cloud setup (GitHub, free)

1. Upload all files to your GitHub repo, keeping the `.github/workflows/` folder.
   **Delete `rules.py`** from the repo if it's there from the earlier version.
2. Settings → Pages → Deploy from a branch → `main`, folder `/docs`.
3. Actions tab → **Weekly Setup Validation** → Run workflow. Run this once first,
   since the dashboard needs its results. Takes roughly 15–40 minutes.
4. Actions tab → **Daily NYSE Scan** → Run workflow (after that it runs automatically).
5. Open `https://<username>.github.io/<repo>/` each morning.
   The full validation report is at `.../validation.html`.

## Adding a setup

Add one `Setup(...)` entry to `SETUPS` in `setups.py`: a signal function plus
stop/target (in ATR multiples) and max hold days. The next weekly validation
tests it automatically; it only appears on the dashboard if it passes.

## Limitations

- Free Yahoo daily data. Only stocks listed today are tested (delisted stocks
  are missing), which makes results look somewhat better than reality.
- Win rates are historical frequencies, not forecasts. Edges can fade, which is
  why validation re-runs every week.
- Not financial advice.
