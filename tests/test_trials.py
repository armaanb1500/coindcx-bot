import numpy as np
import pandas as pd
import pytest

from bot.research import trials


def returns(seed, mean=0.0):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-01-01", periods=300, freq="D", tz="UTC")
    return pd.Series(rng.normal(mean, 0.02, 300), index=idx)


@pytest.fixture
def conn(tmp_path):
    return trials.connect(tmp_path / "research.db")


def log(conn, params, net, instrument="B-BTC_USDT", timeframe="1d", kind="backtest"):
    return trials.record(conn, kind=kind, strategy="s", params=params, instrument=instrument,
                         timeframe=timeframe, net=net, source="test")


def test_rerunning_the_same_config_counts_once_with_latest_sharpe(conn):
    log(conn, {"a": 1}, returns(1))
    log(conn, {"a": 1}, latest := returns(2, mean=0.01))
    log(conn, {"a": 2}, returns(3))
    sharpes = trials.trial_sharpes(conn, "B-BTC_USDT", "1d")
    assert len(sharpes) == 2
    assert latest.mean() / latest.std(ddof=1) == pytest.approx(max(sharpes))
    assert trials.count_all(conn) == 3  # nothing is ever deleted


def test_param_order_does_not_create_a_new_trial(conn):
    log(conn, {"a": 1, "b": 2}, returns(1))
    log(conn, {"b": 2, "a": 1}, returns(2))
    assert len(trials.trial_sharpes(conn, "B-BTC_USDT", "1d")) == 1


def test_trials_are_separated_by_timeframe_instrument_and_kind(conn):
    log(conn, {"a": 1}, returns(1))
    log(conn, {"a": 1}, returns(1), timeframe="4h")
    log(conn, {"a": 1}, returns(1), instrument="B-XAU_USDT")
    log(conn, {"a": 1}, returns(1), kind="walkforward")
    assert len(trials.trial_sharpes(conn, "B-BTC_USDT", "1d")) == 1
