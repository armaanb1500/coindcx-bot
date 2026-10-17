"""Baseline: moving-average crossover. It exists to prove the pipeline end to end.

Its parameters are fixed, not fitted, so it can't be overfit to the data it's
tested on. It's expected to fail the Phase 2 gates, and that's fine.

Stop: atr_mult x ATR(atr_period) from the entry close. ATR (average true range)
measures how much the price typically moves per bar, so the stop sits outside
normal noise and widens in volatile markets.
"""

import pandas as pd

from bot.strategies.base import Strategy


class MACrossover(Strategy):
    name = "ma_crossover"

    def __init__(self, fast: int = 50, slow: int = 200, exposure: float = 1.0,
                 atr_period: int = 14, atr_mult: float = 3.0):
        self.defaults = {"fast": fast, "slow": slow, "exposure": exposure,
                         "atr_period": atr_period, "atr_mult": atr_mult}

    def fit(self, train: pd.DataFrame) -> dict:
        return dict(self.defaults)

    def signal(self, df: pd.DataFrame, params: dict) -> pd.Series:
        # Trailing means only: rolling() looks backward, never centered.
        fast = df["close"].rolling(params["fast"]).mean()
        slow = df["close"].rolling(params["slow"]).mean()
        side = (fast > slow).astype(float) * 2 - 1  # +1 long, -1 short
        return (side * params["exposure"]).where(slow.notna())

    def stop_distance(self, df: pd.DataFrame, params: dict) -> pd.Series:
        return params["atr_mult"] * atr(df, params["atr_period"])


def atr(df: pd.DataFrame, period: int) -> pd.Series:
    """Wilder's average true range. Trailing only: each value uses bars up to its own."""
    prev_close = df["close"].shift(1)
    true_range = pd.concat([df["high"] - df["low"], (df["high"] - prev_close).abs(),
                            (df["low"] - prev_close).abs()], axis=1).max(axis=1)
    return true_range.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
