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
from typing import Callable

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
]

BY_NAME = {s.name: s for s in SETUPS}


def signals(ind: pd.DataFrame, setup: Setup) -> pd.Series:
    """Signal series, only where all indicators are warmed up."""
    ready = ind["SMA200"].notna() & ind["ATR14"].notna() & ind["VOL_AVG20"].notna()
    return (setup.signal(ind) & ready).fillna(False).astype(bool)
