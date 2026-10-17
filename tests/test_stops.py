"""Stop-loss behaviour in the backtest engine."""

import numpy as np
import pandas as pd
import pytest

from bot.config import InstrumentCosts
from bot.research import backtest

FREE = InstrumentCosts(fee_bps=0, slippage_bps=0, funding_bps_per_interval=0)


def bars(rows):
    """rows: (open, high, low, close)"""
    idx = pd.date_range("2024-01-01", periods=len(rows), freq="D", tz="UTC")
    return pd.DataFrame(rows, columns=["open", "high", "low", "close"], index=idx, dtype=float)


def run(df, signal, dist, costs=FREE, tds_bps=0.0):
    sig = pd.Series(signal, index=df.index, dtype=float)
    d = pd.Series(dist, index=df.index, dtype=float)
    return backtest.run(df["close"], sig, costs, "1d", tds_bps, "track", 3.0,
                        stop_distance=d, ohlc=df)


FLAT = (100, 100, 100, 100)


def test_long_stop_hit_intrabar_exits_at_stop_and_stays_out():
    df = bars([FLAT, FLAT, (100, 101, 95, 99), FLAT, FLAT])
    r = run(df, [1, 1, 1, 1, 1], [3] * 5)  # entry at 100, stop at 97
    assert list(r.bars["position"]) == [0, 1, 1, 0, 0]
    assert r.bars["stopped"].tolist() == [False, False, True, False, False]
    assert r.net.iloc[2] == pytest.approx(-0.03)  # exited at 97, not the 99 close
    assert r.equity.iloc[-1] == pytest.approx(0.97)


def test_gap_through_stop_fills_at_open_not_stop():
    df = bars([FLAT, FLAT, (90, 92, 88, 91), FLAT])
    r = run(df, [1, 1, 1, 1], [3] * 4)
    assert r.net.iloc[2] == pytest.approx(-0.10)  # stop 97 never traded; open 90 did


def test_short_stop_uses_high():
    df = bars([FLAT, FLAT, (100, 104, 99, 101), FLAT])
    r = run(df, [-1, -1, -1, -1], [3] * 4)  # short at 100, stop at 103
    assert r.bars["stopped"].iloc[2]
    assert r.net.iloc[2] == pytest.approx(-0.03)


def test_reenters_only_after_signal_changes():
    df = bars([FLAT, FLAT, (100, 100, 90, 95), FLAT, FLAT, FLAT, FLAT])
    r = run(df, [1, 1, 1, 0, 1, 1, 1], [3] * 7)
    # stopped on bar 2; signal stays 1 (bar 3 flat), goes 0 at bar 3, back to 1 at bar 4.
    assert list(r.bars["position"]) == [0, 1, 1, 0, 0, 1, 1]


def test_no_stop_distance_means_no_position():
    df = bars([FLAT] * 4)
    r = run(df, [1, 1, 1, 1], [np.nan, np.nan, 3, 3])
    assert list(r.bars["position"]) == [0, 0, 0, 1]


def test_stop_set_at_entry_and_kept_when_only_size_changes():
    df = bars([FLAT, FLAT, FLAT, FLAT])
    r = run(df, [1, 0.5, 0.5, 0.5], [3, 10, 10, 10])
    assert r.bars["stop"].iloc[1:].tolist() == [97, 97, 97]


def test_flip_gets_a_fresh_stop():
    df = bars([FLAT, FLAT, FLAT, FLAT])
    r = run(df, [1, -1, -1, -1], [3, 4, 4, 4])
    assert r.bars["stop"].iloc[1] == 97 and r.bars["stop"].iloc[2] == 104


def test_stop_exit_pays_costs_and_long_exit_counts_as_sell_for_tds():
    costs = InstrumentCosts(fee_bps=5, slippage_bps=5, funding_bps_per_interval=0)
    df = bars([FLAT, FLAT, (100, 100, 95, 96), FLAT])
    r = run(df, [1, 1, 1, 1], [3] * 4, costs=costs, tds_bps=100)
    assert r.bars["turnover"].tolist() == [0, 1, 1, 0]  # entry, then stop exit
    assert r.net.iloc[2] == pytest.approx(-0.03 - 0.001)
    assert r.bars["tds"].iloc[2] == pytest.approx(0.01)


def test_stops_require_ohlc():
    df = bars([FLAT] * 3)
    with pytest.raises(ValueError, match="ohlc"):
        backtest.run(df["close"], df["close"] * 0 + 1, FREE, "1d", 0, "track", 3.0,
                     stop_distance=df["close"] * 0 + 3)
