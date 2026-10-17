"""Risk-based sizing in the backtest engine, and parity with live sizing."""

import numpy as np
import pandas as pd
import pytest

from bot.config import InstrumentCosts, Settings
from bot.live.sizing import Instrument, RiskRule, size_position
from bot.research import backtest
from bot.research.walkforward import walk_forward
from bot.strategies.baseline import MACrossover

FREE = InstrumentCosts(fee_bps=0, slippage_bps=0, funding_bps_per_interval=0)
RULE = RiskRule(risk_pct=0.01, max_position_pct=0.20)
FLAT = (100, 100, 100, 100)


def bars(rows):
    """rows: (open, high, low, close)"""
    idx = pd.date_range("2024-01-01", periods=len(rows), freq="D", tz="UTC")
    return pd.DataFrame(rows, columns=["open", "high", "low", "close"], index=idx, dtype=float)


def run(df, signal, dist, rule=RULE, costs=FREE):
    sig = pd.Series(signal, index=df.index, dtype=float)
    d = pd.Series(dist, index=df.index, dtype=float)
    return backtest.run(df["close"], sig, costs, "1d", 0.0, "track", 3.0,
                        stop_distance=d, ohlc=df, risk_rule=rule)


def test_rule_comes_from_the_same_settings_live_uses():
    s = Settings(_env_file=None, risk_pct_per_trade=0.02, max_position_pct=0.5)
    assert RiskRule.from_settings(s) == RiskRule(0.02, 0.5)


@pytest.mark.parametrize("entry,stop", [(80000.0, 70000.0), (80000.0, 77000.0),
                                        (80000.0, 79000.0), (3000.0, 3100.0)])
def test_engine_exposure_matches_live_size(entry, stop):
    """Same entry, stop and capital: the engine's exposure is live's notional / capital,
    up to live rounding quantity down to the exchange step."""
    capital_inr, usdt_inr = 5_000_000.0, 100.0
    inst = Instrument("X", qty_step=1e-6, min_qty=1e-6, min_notional=1.0,
                      fee_bps=0, slippage_bps=0)
    live = size_position(entry, stop, capital_inr, usdt_inr, inst, RULE.risk_pct,
                         RULE.max_position_pct, leverage=1.0, max_leverage=3.0)
    live_fraction = live.notional_usdt * usdt_inr / capital_inr

    df = bars([(entry, entry, entry, entry)] * 3)
    side = 1 if live.side == "buy" else -1
    r = run(df, [side] * 3, [abs(entry - stop)] * 3)
    engine_fraction = r.bars["position"].iloc[1]

    assert np.sign(engine_fraction) == side
    step_fraction = inst.qty_step * entry * usdt_inr / capital_inr
    assert 0 <= abs(engine_fraction) - live_fraction <= step_fraction
    assert live.capped == (abs(engine_fraction) == RULE.max_position_pct)


def test_wide_stop_risks_exactly_risk_pct_at_the_stop():
    # Entry 100, stop 10 away: 10% move x 10% exposure = 1% of equity lost.
    df = bars([FLAT, FLAT, (100, 100, 85, 88), FLAT])
    r = run(df, [1, 1, 1, 1], [10] * 4)
    assert r.bars["position"].iloc[1] == pytest.approx(0.10)
    assert r.bars["stopped"].iloc[2]
    assert r.net.iloc[2] == pytest.approx(-0.01)


def test_cap_binds_when_the_stop_is_tight():
    # Stop 1 away would want 100% exposure; the cap holds it to 20%, so less is lost.
    df = bars([FLAT, FLAT, (100, 100, 98, 99), FLAT])
    r = run(df, [1, 1, 1, 1], [1] * 4)
    assert r.bars["position"].iloc[1] == pytest.approx(0.20)
    assert r.net.iloc[2] == pytest.approx(-0.002)


def test_signal_magnitude_is_ignored_only_its_sign_counts():
    df = bars([FLAT] * 4)
    a = run(df, [1, 1, 1, 1], [10] * 4)
    b = run(df, [2.5, 0.3, 1.7, 0.1], [10] * 4)
    assert a.bars["position"].tolist() == b.bars["position"].tolist() == [0, 0.1, 0.1, 0.1]


def test_size_fixed_at_entry_and_resized_on_flip():
    # Stop distance changes after entry: the open position keeps its entry size,
    # like a live order's quantity. The flip is sized from its own stop.
    df = bars([FLAT] * 5)
    r = run(df, [1, 1, 1, -1, -1], [10, 4, 4, 20, 20])
    assert r.bars["position"].tolist() == pytest.approx([0, 0.1, 0.1, 0.1, -0.05])


def test_risk_sizing_needs_stops():
    df = bars([FLAT] * 3)
    with pytest.raises(ValueError, match="stop_distance"):
        backtest.run(df["close"], df["close"] * 0 + 1, FREE, "1d", 0, "track", 3.0,
                     risk_rule=RULE)


def test_cap_above_max_leverage_is_refused():
    df = bars([FLAT] * 3)
    with pytest.raises(ValueError, match="max_leverage"):
        run(df, [1, 1, 1], [10] * 3, rule=RiskRule(0.01, 5.0))


def test_default_mode_unchanged_with_or_without_stops():
    """No risk_rule: the signal is the exposure, exactly as before."""
    df = bars([FLAT, (100, 102, 99, 101), (101, 103, 100, 102), (102, 104, 101, 103)])
    sig = pd.Series([0.5, 0.5, -1.0, -1.0], index=df.index)
    plain = backtest.run(df["close"], sig, FREE, "1d", 0, "track", 3.0)
    assert plain.bars["position"].tolist() == [0, 0.5, 0.5, -1.0]
    stops = pd.Series(50.0, index=df.index)
    stopped = backtest.run(df["close"], sig, FREE, "1d", 0, "track", 3.0,
                           stop_distance=stops, ohlc=df, risk_rule=None)
    assert stopped.bars["position"].tolist() == [0, 0.5, 0.5, -1.0]


def test_walk_forward_passes_the_rule_through():
    rng = np.random.default_rng(0)
    close = pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.02, 600))),
                      index=pd.date_range("2022-01-01", periods=600, freq="D", tz="UTC"))
    df = pd.DataFrame({"open": close.shift(1).fillna(close.iloc[0]), "close": close})
    df["high"] = df[["open", "close"]].max(axis=1) * 1.005
    df["low"] = df[["open", "close"]].min(axis=1) * 0.995
    wf = walk_forward(df, MACrossover(fast=5, slow=20), 200, 100, FREE, "1d", 0, "track", 3.0,
                      risk_rule=RULE)
    held = wf.result.bars["position"].abs()
    assert held.max() <= RULE.max_position_pct + 1e-12
    assert (held > 0).any()
