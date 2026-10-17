import numpy as np
import pandas as pd
import pytest

from bot.config import InstrumentCosts
from bot.research.walkforward import walk_forward
from bot.strategies.base import Strategy
from bot.strategies.baseline import MACrossover

FREE = InstrumentCosts(fee_bps=0, slippage_bps=0, funding_bps_per_interval=0)


def prices(n=200, seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC")
    close = 100 * np.cumprod(1 + rng.normal(0, 0.02, n))
    return pd.DataFrame({"open": close, "high": close * 1.01, "low": close * 0.99,
                         "close": close}, index=idx)


def wf(df, strategy, train=50, test=25, **kw):
    return walk_forward(df, strategy, train, test, FREE, "1d", tds_bps=0, tds_mode="track",
                        max_leverage=3, **kw)


class Spy(Strategy):
    """Records what it was shown, so tests can check nothing leaks."""
    name = "spy"

    def __init__(self):
        self.fit_windows, self.signal_windows = [], []

    def fit(self, train):
        self.fit_windows.append((train.index[0], train.index[-1]))
        return {}

    def signal(self, df, params):
        self.signal_windows.append((df.index[0], df.index[-1]))
        return pd.Series(1.0, index=df.index)

    def stop_distance(self, df, params):
        return df["close"] * 0.5  # far away: never hit


def test_fit_never_sees_test_data_and_signal_never_sees_the_future():
    df, spy = prices(), Spy()
    out = wf(df, spy)
    for fold, (fit_start, fit_end), (_, sig_end) in zip(out.folds, spy.fit_windows,
                                                         spy.signal_windows):
        assert fit_end < fold.test_start
        assert sig_end == fold.test_end  # nothing after the test slice


def test_folds_tile_the_out_of_sample_period():
    df = prices(200)
    out = wf(df, Spy(), train=50, test=25)
    assert len(out.folds) == 6  # (200 - 50) // 25
    assert out.result.bars.index.equals(df.index[50:200])


def test_warmup_means_no_nan_at_fold_starts():
    df = prices(200)
    with_warmup = wf(df, MACrossover(fast=5, slow=20))
    assert with_warmup.result.bars["signal"].notna().all()

    # The article's bug: no warmup -> every fold starts with a 19-bar blind spot.
    no_warmup = wf(df, MACrossover(fast=5, slow=20), warmup_bars=0)
    assert no_warmup.result.bars["signal"].isna().sum() == 6 * 19


def test_stops_are_computed_with_warmup_too():
    out = wf(prices(200), MACrossover(fast=5, slow=20, atr_period=10))
    held = out.result.bars["position"] != 0
    assert out.result.bars.loc[held, "stop"].notna().all()


def test_anchored_train_window_grows_from_the_start():
    df, spy = prices(), Spy()
    wf(df, spy, anchored=True)
    assert {start for start, _ in spy.fit_windows} == {df.index[0]}


def test_summary_judges_folds_individually():
    df = prices(200)
    out = wf(df, MACrossover(fast=5, slow=20))
    table, s = out.fold_table(), out.summary()
    assert s["positive_folds"] == int((table["return"] > 0).sum())
    assert s["worst_fold_return"] == table["return"].min()


def test_not_enough_data_is_an_error():
    with pytest.raises(ValueError, match="need at least"):
        wf(prices(60), Spy(), train=50, test=25)
