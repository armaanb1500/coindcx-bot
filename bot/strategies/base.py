"""The interface every strategy implements. The engine only ever sees the signal."""

from abc import ABC, abstractmethod

import pandas as pd


class Strategy(ABC):
    name: str

    @abstractmethod
    def fit(self, train: pd.DataFrame) -> dict:
        """Choose parameters using ONLY the training slice. Returns the params."""

    @abstractmethod
    def signal(self, df: pd.DataFrame, params: dict) -> pd.Series:
        """Desired exposure at each bar's close, using data up to that close only.

        NaN means "no opinion yet" (indicator warmup) and is treated as flat.
        Do NOT shift: the engine does that.
        """

    @abstractmethod
    def stop_distance(self, df: pd.DataFrame, params: dict) -> pd.Series:
        """Stop distance in price units for a position opened at each bar's close.

        Every strategy must have one: live orders always carry a stop, so the
        backtest must too. Same rule as signal(): data up to that close only.
        """
