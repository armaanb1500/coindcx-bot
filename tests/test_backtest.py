import numpy as np
import pandas as pd
import pytest

from bot.config import InstrumentCosts
from bot.research import backtest, metrics
from bot.strategies.baseline import MACrossover
from bot.timeframes import periods_per_year

FREE = InstrumentCosts(fee_bps=0, slippage_bps=0, funding_bps_per_interval=0)


def run(close, signal, costs=FREE, timeframe="1d", tds_bps=0.0, tds_mode="track", max_leverage=3.0):
    return backtest.run(close, signal, costs, timeframe, tds_bps, tds_mode, max_leverage)


def series(values, freq="D"):
    idx = pd.date_range("2024-01-01", periods=len(values), freq=freq, tz="UTC")
    return pd.Series(values, index=idx, dtype=float)


def random_walk(n, seed):
    rng = np.random.default_rng(seed)
    return series(100 * np.cumprod(1 + rng.normal(0, 0.02, n)))


def test_periods_per_year_matches_bar_size():
    assert periods_per_year("1d") == 365
    assert periods_per_year("4h") == 2190
    assert periods_per_year("1h") == 8760


# --- Leakage: the test that proves the engine catches look-ahead -------------

def test_same_bar_return_signal_has_no_edge_after_shift():
    close = random_walk(5000, seed=1)
    peek = np.sign(close.pct_change())  # sign of THIS bar's return: only known at its close
    result = run(close, peek)
    assert abs(metrics.sharpe(result.net, "1d")) < 1.0


def test_same_bar_signal_without_shift_shows_absurd_edge():
    # Undo the engine's shift by handing it tomorrow's answer. This is what an
    # unshifted signal looks like; if the engine ever stopped shifting, the test
    # above would look like this one.
    close = random_walk(5000, seed=1)
    leaked = np.sign(close.pct_change()).shift(-1)
    result = run(close, leaked)
    assert metrics.sharpe(result.net, "1d") > 20


# --- Engine mechanics --------------------------------------------------------

def test_signal_acts_on_next_bar_with_simple_returns():
    close = series([100, 110, 99, 99])
    result = run(close, series([1, 1, 0, 0]))
    assert list(result.bars["position"]) == [0, 1, 1, 0]
    # Bar 1 return +10% (held from bar 1), bar 2 -10%.
    np.testing.assert_allclose(result.net, [0, 0.10, -0.10, 0])
    assert result.equity.iloc[-1] == pytest.approx(1.10 * 0.90)


def test_short_uses_simple_returns():
    close = series([100, 50])
    result = run(close, series([-1, -1]))
    assert result.net.iloc[1] == pytest.approx(0.5)  # price halves, short gains 50%


def test_leverage_above_cap_is_refused_not_clipped():
    close = series([100, 101, 102])
    with pytest.raises(ValueError, match="max_leverage"):
        run(close, series([3.5, 0, 0]))


def test_fees_and_slippage_charged_on_turnover():
    costs = InstrumentCosts(fee_bps=6, slippage_bps=4, funding_bps_per_interval=0)
    close = series([100, 100, 100, 100])
    result = run(close, series([1, -1, 0, 0]), costs=costs)
    # Turnover: 0->1 = 1, 1->-1 = 2, -1->0 = 1. Each unit costs 10 bps.
    assert list(result.bars["turnover"]) == [0, 1, 2, 1]
    np.testing.assert_allclose(result.net, [0, -0.001, -0.002, -0.001])


def test_funding_scales_with_bar_size_and_charges_both_sides():
    costs = InstrumentCosts(fee_bps=0, slippage_bps=0, funding_bps_per_interval=1.0,
                            funding_interval_hours=8)
    close = series([100, 100, 100])
    result = run(close, series([2, -1, -1]), costs=costs)
    # Daily bar = 3 funding intervals. Position 2 -> 6 bps, position -1 -> 3 bps.
    np.testing.assert_allclose(result.bars["funding_cost"], [0, 0.0006, 0.0003])
    assert "CONSTANT" in result.funding_note


def test_tds_on_sell_legs_tracked_or_costed():
    close = series([100, 100, 100, 100])
    signal = series([1, 0, -1, 0])  # buy, sell (close long), sell (open short), buy back
    tracked = run(close, signal, tds_bps=100, tds_mode="track")
    assert list(tracked.bars["tds"]) == [0, 0, 0.01, 0.01]
    assert tracked.equity.iloc[-1] == 1.0  # tracking doesn't touch equity
    assert tracked.cost_summary()["tds_withheld"] == pytest.approx(0.02)

    costed = run(close, signal, tds_bps=100, tds_mode="cost")
    assert costed.equity.iloc[-1] == pytest.approx(0.99 * 0.99)


def test_engine_rejects_misaligned_signal():
    close = series([100, 101])
    with pytest.raises(ValueError, match="index"):
        run(close, series([1, 1, 1]))


def test_wipeout_floors_equity_at_zero():
    result = run(series([100, 10, 100]), series([3, 3, 3]))  # -90% at 3x leverage
    assert list(result.equity) == [1, 0, 0]


# --- Metrics -----------------------------------------------------------------

def test_drawdown_metrics():
    equity = series([1.0, 1.2, 0.9, 1.0, 1.3, 1.1])
    returns = equity.pct_change().fillna(equity.iloc[0] - 1)
    m = metrics.summary(returns, equity, "1d")
    assert m["max_drawdown"] == pytest.approx(0.9 / 1.2 - 1)
    assert m["longest_drawdown_bars"] == 2
    assert m["longest_drawdown"] == pd.Timedelta(days=2)
    assert m["n_obs"] == 6


def test_sharpe_annualization_uses_timeframe():
    r = series([0.01, -0.005, 0.02, 0.0, 0.003])
    assert metrics.sharpe(r, "1h") / metrics.sharpe(r, "1d") == pytest.approx(np.sqrt(24))


# --- Baseline strategy -------------------------------------------------------

def test_baseline_signal_uses_only_past_data():
    close = random_walk(400, seed=3)
    df = pd.DataFrame({"close": close})
    strat = MACrossover(fast=5, slow=20)
    full = strat.signal(df, strat.fit(df))
    # Changing the future must not change any earlier signal.
    future_changed = df.copy()
    future_changed.iloc[300:, 0] *= 3
    partial = strat.signal(future_changed, strat.fit(df))
    pd.testing.assert_series_equal(full.iloc[:300], partial.iloc[:300])
    assert full.iloc[:19].isna().all() and full.iloc[19:].notna().all()


def test_baseline_stop_distance_is_trailing_and_positive():
    rng = np.random.default_rng(4)
    close = random_walk(300, seed=4)
    df = pd.DataFrame({"close": close, "high": close * (1 + rng.uniform(0, 0.02, 300)),
                       "low": close * (1 - rng.uniform(0, 0.02, 300))})
    strat = MACrossover()
    dist = strat.stop_distance(df, strat.fit(df))
    changed = df.copy()
    changed.iloc[200:] *= 2
    pd.testing.assert_series_equal(dist.iloc[:200], strat.stop_distance(changed, strat.fit(df)).iloc[:200])
    assert dist.iloc[:13].isna().all() and (dist.iloc[14:] > 0).all()
