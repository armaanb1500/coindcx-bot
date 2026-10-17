"""Baseline: moving-average crossover. It exists to prove the pipeline end to end.

Its parameters are fixed, not fitted, so it can't be overfit to the data it's
tested on. It's expected to fail the Phase 2 gates, and that's fine.
"""

import pandas as pd

from bot.strategies.base import Strategy


class MACrossover(Strategy):
    name = "ma_crossover"

    def __init__(self, fast: int = 50, slow: int = 200, exposure: float = 1.0):
        self.defaults = {"fast": fast, "slow": slow, "exposure": exposure}

    def fit(self, train: pd.DataFrame) -> dict:
        return dict(self.defaults)

    def signal(self, df: pd.DataFrame, params: dict) -> pd.Series:
        # Trailing means only: rolling() looks backward, never centered.
        fast = df["close"].rolling(params["fast"]).mean()
        slow = df["close"].rolling(params["slow"]).mean()
        side = (fast > slow).astype(float) * 2 - 1  # +1 long, -1 short
        return (side * params["exposure"]).where(slow.notna())
