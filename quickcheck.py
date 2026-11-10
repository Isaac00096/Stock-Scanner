"""Print today's opening minutes for a few tickers (run from GitHub: Quick Check)."""
import sys
import yfinance as yf

for t in sys.argv[1].split(","):
    d = yf.download(t, period="1d", interval="1m", progress=False, auto_adjust=False)
    if d.empty:
        print(t, "no data"); continue
    d.columns = d.columns.get_level_values(0)
    d.index = d.index.tz_convert("America/New_York")
    o = float(d["Open"].iloc[0])
    print(f"\n{t} open {o:.2f} at {d.index[0]:%H:%M} NY")
    for i, (ts, r) in enumerate(d.iterrows()):
        if i < 20 or i % 5 == 0:
            print(f"  {ts:%H:%M}  close {r.Close:.2f} ({(r.Close / o - 1) * 100:+.2f}%)  high {r.High:.2f} low {r.Low:.2f}")
