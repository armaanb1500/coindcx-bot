"""Walk-forward: fit on the past, trade the next slice, slide forward, repeat.

    |---- train ----|-- test --|
              |---- train ----|-- test --|
                        |---- train ----|-- test --|

Fixes the source article's warmup bug: indicators for a test slice are computed
over (warmup + test), where warmup is the tail of the train window, and only the
test bars are kept. Otherwise a 200-bar moving average is NaN for the first 200
bars of every fold.

The test-slice signals are stitched into one out-of-sample signal and run through
the engine once, so costs and positions carry across fold boundaries naturally.
"""

from dataclasses import dataclass

import pandas as pd

from bot.config import InstrumentCosts
from bot.research import backtest, metrics
from bot.strategies.base import Strategy


@dataclass
class Fold:
    train_start: pd.Timestamp
    test_start: pd.Timestamp
    test_end: pd.Timestamp
    params: dict


@dataclass
class WalkForwardResult:
    folds: list[Fold]
    result: backtest.BacktestResult  # the stitched out-of-sample run

    def fold_table(self) -> pd.DataFrame:
        rows = []
        for i, f in enumerate(self.folds):
            net = self.result.net.loc[f.test_start:f.test_end]
            equity = (1 + net).cumprod()
            rows.append({
                "fold": i + 1, "test_start": f.test_start, "test_end": f.test_end,
                "n_obs": len(net), "return": float(equity.iloc[-1] - 1),
                "sharpe": metrics.sharpe(net, self.result.timeframe),
                "max_drawdown": float(metrics.drawdown(equity).min()),
                "params": f.params,
            })
        return pd.DataFrame(rows).set_index("fold")

    def summary(self) -> dict:
        table = self.fold_table()
        worst = table["return"].idxmin()
        return {
            "n_folds": len(table),
            "positive_folds": int((table["return"] > 0).sum()),
            "positive_fold_frac": float((table["return"] > 0).mean()),
            "worst_fold": int(worst),
            "worst_fold_return": float(table.loc[worst, "return"]),
            "worst_fold_sharpe": float(table.loc[worst, "sharpe"]),
            "mean_fold_return": float(table["return"].mean()),  # reported, not judged on
        }


def walk_forward(df: pd.DataFrame, strategy: Strategy, train_bars: int, test_bars: int,
                 costs: InstrumentCosts, timeframe: str, tds_bps: float, tds_mode: str,
                 max_leverage: float, warmup_bars: int | None = None,
                 anchored: bool = False) -> WalkForwardResult:
    """warmup_bars defaults to the whole train window, the most warmup we can honestly give."""
    warmup_bars = train_bars if warmup_bars is None else warmup_bars
    if warmup_bars > train_bars:
        raise ValueError("warmup can't reach further back than the train window")
    if len(df) < train_bars + test_bars:
        raise ValueError(f"need at least {train_bars + test_bars} bars, have {len(df)}")

    folds, signals, stops = [], [], []
    test_start = train_bars
    while test_start + test_bars <= len(df):
        train = df.iloc[(0 if anchored else test_start - train_bars):test_start]
        test = df.iloc[test_start:test_start + test_bars]
        params = strategy.fit(train)

        # Compute over warmup + test, then keep only the test bars.
        window = df.iloc[test_start - warmup_bars:test_start + test_bars]
        signals.append(strategy.signal(window, params).loc[test.index])
        stops.append(strategy.stop_distance(window, params).loc[test.index])
        folds.append(Fold(train.index[0], test.index[0], test.index[-1], params))
        test_start += test_bars

    oos_signal = pd.concat(signals)
    oos = df.loc[oos_signal.index]
    result = backtest.run(oos["close"], oos_signal, costs, timeframe, tds_bps, tds_mode,
                          max_leverage, stop_distance=pd.concat(stops), ohlc=oos)
    return WalkForwardResult(folds, result)
