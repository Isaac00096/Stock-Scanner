"""
The setup library. Each setup = an entry signal (evaluated on the daily close)
plus exit rules. Trades enter at the NEXT day's open.

Exits (whichever comes first):
  stop   = entry -/+ stop_atr   x ATR(14)
  target = entry +/- target_atr x ATR(14)
  time   = close of the max_hold-th day

To add a setup: write its signal function and append a Setup(...) to SETUPS.
"""

from dataclasses import dataclass
from typing import Callable, Optional

import numpy as np

import pandas as pd


@dataclass(frozen=True)
class Setup:
    name: str
    label: str
    direction: str            # "long" or "short"
    signal: Callable[[pd.DataFrame], pd.Series]
    description: str
    stop_atr: float = 1.5
    target_atr: float = 2.5
    max_hold: int = 10
    # Limit-order setups: returns a DataFrame with "limit" (and optionally "stop"/"target")
    # computed at each close. The order is placed for the next session only.
    levels: Optional[Callable[[pd.DataFrame], pd.DataFrame]] = None
    # Optional exit rule evaluated at each close; when true, the trade is closed at the next open.
    exit_signal: Optional[Callable[[pd.DataFrame], pd.Series]] = None
    # Optional stop/target as a fraction of the fill price (e.g. 0.15 = 15%); override ATR multiples.
    stop_pct: Optional[float] = None
    target_pct: Optional[float] = None

    entry_type: str = "open"          # "open" = next day's open, "limit" = day limit order at levels["limit"]

    @property
    def is_limit(self) -> bool:
        return self.entry_type == "limit"


def cross_above(a, b) -> pd.Series:
    b_prev = b.shift() if isinstance(b, pd.Series) else b
    return (a > b) & (a.shift() <= b_prev)


def cross_below(a, b) -> pd.Series:
    b_prev = b.shift() if isinstance(b, pd.Series) else b
    return (a < b) & (a.shift() >= b_prev)


def _close_near_high(d):
    return (d.Close - d.Low) >= 0.75 * (d.High - d.Low)


def _close_near_low(d):
    return (d.High - d.Close) >= 0.75 * (d.High - d.Low)


# ---------- Limit-order setups (orders placed after the close, filled only if price comes to you) ----------
def _rsi2_limit_price(d):
    """Price at which tomorrow's RSI(2) would drop below 10 (solved from Wilder's averages)."""
    drop = (9 * d.RSI2_G - d.RSI2_L).clip(lower=0.01 * d.ATR14)
    return d.Close - drop


def _rsi2_limit_levels(d):
    return pd.DataFrame({"limit": _rsi2_limit_price(d)}, index=d.index)


def _rsi2_limit_signal(d):
    p = _rsi2_limit_price(d)
    return (d.Close > d.SMA200) & (d.RSI2 >= 10) & ((d.Close - p) <= 2 * d.ATR14)


def _fib_levels(level_col):
    def f(d):
        return pd.DataFrame({"limit": d[level_col],
                             "stop": d.FIB_786 - 0.25 * d.ATR14,
                             "target": d.SW_HI}, index=d.index)
    return f


def _fib_signal(level_col):
    def f(d):
        lv = d[level_col]
        return (d.Close > d.SMA200) & lv.notna() & (d.Close > lv) & ((d.Close - lv) <= 2 * d.ATR14)
    return f


# ---------- H.M. Gartley, "Profits in the Stock Market" (1935) ----------
def _g222_levels_limit(d):
    return pd.DataFrame({"limit": d.G_R50, "stop": d.G_B - 0.25 * d.ATR14}, index=d.index)


def _g222_limit_signal(d):
    return d.G_C.notna() & (d.Close > d.G_R50) & (d.Close < d.G_C) & ((d.Close - d.G_R50) <= 2 * d.ATR14)


def _g222_levels_stop(d):
    return pd.DataFrame({"stop": d.G_B - 0.25 * d.ATR14}, index=d.index)


def _g222_confirm_signal(d):
    recent_low = d.Low.rolling(5).min()
    return (d.G_C.notna() & (recent_low <= d.G_R33) & (recent_low > d.G_B) &
            (d.Close > d.G_R50) & (d.Close < d.G_C) & (d.Close > d.Close.shift()) & (d.Close > d.Open))


def _gartley_breakout(d):
    lvl = d.PRIOR_TOP * 1.02
    return (d.Close > lvl) & (d.Close.shift() <= lvl.shift()) & (d.Volume > 1.5 * d.VOL_AVG20)


def _ma25_cross_up(d):
    return (d.Close > d.SMA25_LEAD3) & (d.Close.shift() <= d.SMA25_LEAD3.shift())


def _ma25_exit(d):
    return d.Close < d.SMA25_LEAD3


SETUPS = [
    # ---------- Trend ----------
    Setup("golden_cross", "Golden Cross", "long",
          lambda d: cross_above(d.SMA50, d.SMA200),
          "50-day SMA crosses above 200-day SMA", 2.0, 4.0, 20),
    Setup("death_cross", "Death Cross", "short",
          lambda d: cross_below(d.SMA50, d.SMA200),
          "50-day SMA crosses below 200-day SMA", 2.0, 4.0, 20),
    Setup("macd_bull_uptrend", "MACD Bull Cross (uptrend)", "long",
          lambda d: cross_above(d.MACD, d.MACD_signal) & (d.Close > d.SMA200),
          "MACD crosses above signal while price is above the 200-day SMA"),
    Setup("macd_bear_downtrend", "MACD Bear Cross (downtrend)", "short",
          lambda d: cross_below(d.MACD, d.MACD_signal) & (d.Close < d.SMA200),
          "MACD crosses below signal while price is below the 200-day SMA"),
    Setup("sma50_pullback", "50-SMA Pullback", "long",
          lambda d: (d.SMA50 > d.SMA200) & (d.Low <= d.SMA50) & (d.Close > d.SMA50) & (d.Close > d.Open),
          "In an uptrend, price dips to the 50-day SMA and closes back above it, green"),

    # ---------- Mean reversion ----------
    Setup("rsi_oversold_bounce", "RSI Oversold Bounce", "long",
          lambda d: cross_above(d.RSI14, 30),
          "RSI(14) crosses back above 30", 1.5, 2.0, 7),
    Setup("rsi_overbought_fade", "RSI Overbought Fade", "short",
          lambda d: cross_below(d.RSI14, 70),
          "RSI(14) crosses back below 70", 1.5, 2.0, 7),
    Setup("rsi2_pullback_uptrend", "RSI(2) Pullback (uptrend)", "long",
          lambda d: (d.Close > d.SMA200) & (d.RSI2 < 10),
          "Price above 200-day SMA and RSI(2) below 10 (short-term dip in an uptrend)", 2.0, 1.5, 5),
    Setup("rsi2_rally_downtrend", "RSI(2) Rally (downtrend)", "short",
          lambda d: (d.Close < d.SMA200) & (d.RSI2 > 90),
          "Price below 200-day SMA and RSI(2) above 90 (short-term pop in a downtrend)", 2.0, 1.5, 5),
    Setup("bb_lower_reversal", "Bollinger Lower Reversal", "long",
          lambda d: (d.Close.shift() < d.BB_LO.shift()) & (d.Close > d.BB_LO),
          "Closes back inside the lower Bollinger Band after closing below it", 1.5, 2.0, 7),
    Setup("bb_upper_rejection", "Bollinger Upper Rejection", "short",
          lambda d: (d.Close.shift() > d.BB_UP.shift()) & (d.Close < d.BB_UP),
          "Closes back inside the upper Bollinger Band after closing above it", 1.5, 2.0, 7),

    # ---------- Breakout / volume ----------
    Setup("breakout_20d_volume", "20D Breakout + Volume", "long",
          lambda d: (d.Close > d.HIGH_20) & (d.Volume > 1.5 * d.VOL_AVG20),
          "Close above the prior 20-day high on 1.5x average volume"),
    Setup("breakdown_20d_volume", "20D Breakdown + Volume", "short",
          lambda d: (d.Close < d.LOW_20) & (d.Volume > 1.5 * d.VOL_AVG20),
          "Close below the prior 20-day low on 1.5x average volume"),
    Setup("volume_spike_green", "Volume Spike (bullish)", "long",
          lambda d: (d.Volume > 2.5 * d.VOL_AVG20) & (d.Close > d.Open) & _close_near_high(d),
          "Volume over 2.5x average, green candle closing near its high"),
    Setup("volume_spike_red", "Volume Spike (bearish)", "short",
          lambda d: (d.Volume > 2.5 * d.VOL_AVG20) & (d.Close < d.Open) & _close_near_low(d),
          "Volume over 2.5x average, red candle closing near its low"),

    # ---------- Limit orders: placed tonight, filled only if price dips to the level ----------
    Setup("rsi2_pullback_limit", "RSI(2) Pullback — limit order", "long", _rsi2_limit_signal,
          "Uptrend stock; buy limit at the price where RSI(2) would drop below 10", 2.0, 1.5, 5,
          levels=_rsi2_limit_levels, entry_type="limit"),
    Setup("fib_618_limit", "Fibonacci 61.8% — limit order", "long", _fib_signal("FIB_618"),
          "Uptrend stock pulling back from a fresh swing high; buy limit at the 61.8% retracement, "
          "stop just below 78.6%, target the swing high", 0, 0, 20, levels=_fib_levels("FIB_618"), entry_type="limit"),
    Setup("fib_500_limit", "Fibonacci 50% — limit order", "long", _fib_signal("FIB_500"),
          "Uptrend stock pulling back from a fresh swing high; buy limit at the 50% retracement, "
          "stop just below 78.6%, target the swing high", 0, 0, 20, levels=_fib_levels("FIB_500"), entry_type="limit"),

    # ---------- Gartley, "Profits in the Stock Market" ----------
    Setup("gartley_222_limit", "Gartley 222 buying spot — limit order", "long", _g222_limit_signal,
          "Gartley Ch. VIII: after a 12%+ decline with volume drying up, a minor rally on rising volume, "
          "then a quieter pullback; buy limit at the 1/2 retracement of the rally, stop under the low, "
          "target +15% (his 10-20%)", 0, 0, 40,
          levels=_g222_levels_limit, entry_type="limit", target_pct=0.15),
    Setup("gartley_222_confirm", "Gartley 222 buying spot — on the turn", "long", _g222_confirm_signal,
          "Same pattern, but buy at the next open once the pullback has reached the 1/3-1/2 zone and "
          "closes up (Gartley's 'signs of terminating'); stop under the low, target +15%", 0, 0, 40,
          levels=_g222_levels_stop, target_pct=0.15),
    Setup("gartley_breakout", "Gartley breakout above previous top", "long", _gartley_breakout,
          "Gartley Ch. VIII: decisive (2%+) close above the previous intermediate top, on 1.5x volume; "
          "target +15% (his 10-20%), stop -7.5%", 0, 0, 60, stop_pct=0.075, target_pct=0.15),
    Setup("gartley_ma25", "Gartley 25-day moving average", "long", _ma25_cross_up,
          "Gartley Ch. XI: his best-tested system, close crosses above the 25-day average plotted 3 days "
          "ahead; exit when it closes back below (protective stop 3 ATR)", 3.0, 0, 120,
          exit_signal=_ma25_exit, target_pct=10.0),
    Setup("gartley_ma25_leader", "Gartley 25-day MA — market leaders only", "long",
          lambda d: _ma25_cross_up(d) & (d.RS63 > 0),
          "Same, only for stocks beating the S&P 500 over 3 months (Gartley Ch. XVII, 'better-than-market')",
          3.0, 0, 120, exit_signal=_ma25_exit, target_pct=10.0),
    Setup("rsi2_pullback_leader", "RSI(2) Pullback — market leaders only", "long",
          lambda d: (d.Close > d.SMA200) & (d.RSI2 < 10) & (d.RS63 > 0),
          "RSI(2) Pullback, only for stocks beating the S&P 500 over 3 months (Gartley's stock selection)",
          2.0, 1.5, 5),
]

BY_NAME = {s.name: s for s in SETUPS}


def signals(ind: pd.DataFrame, setup: Setup) -> pd.Series:
    """Signal series, only where all indicators are warmed up."""
    ready = ind["SMA200"].notna() & ind["ATR14"].notna() & ind["VOL_AVG20"].notna()
    return (setup.signal(ind) & ready).fillna(False).astype(bool)


def levels(ind: pd.DataFrame, setup: Setup) -> Optional[pd.DataFrame]:
    return setup.levels(ind) if setup.levels else None


def exit_mask(ind: pd.DataFrame, setup: Setup) -> Optional[np.ndarray]:
    if not setup.exit_signal:
        return None
    return setup.exit_signal(ind).fillna(False).astype(bool).to_numpy()
