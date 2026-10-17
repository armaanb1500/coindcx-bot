import pytest

from bot.config import Settings
from bot.live import risk
from bot.live.risk import RiskState
from bot.live.sizing import Instrument, SizingRefused, size_position

BTC = Instrument("B-BTC_USDT", qty_step=0.001, min_qty=0.001, min_notional=60.0,
                 fee_bps=5.9, slippage_bps=3.0)


def size(entry=80000.0, stop=78000.0, capital=500_000.0, rate=100.0, **kw):
    args = dict(risk_pct=0.01, max_position_pct=0.20, leverage=1.0, max_leverage=3.0)
    return size_position(entry, stop, capital, rate, BTC, **{**args, **kw})


def test_risk_based_size_loses_risk_pct_at_stop():
    # Capital 5,00,000 INR at 100 INR/USDT = 5,000 USDT. Risk 1% = 50 USDT.
    # Stop 2,000 below entry -> 0.025 BTC. Cap: 20% = 1,000 USDT notional = 0.0125 BTC.
    s = size(stop=78000.0)
    assert s.side == "buy"
    assert s.capped and s.quantity == 0.012  # capped, then floored to the 0.001 step
    s = size(stop=40000.0)  # wide stop: risk sizing is the binding constraint
    assert not s.capped and s.quantity == 0.001
    assert s.notional_usdt == pytest.approx(80.0)


def test_stop_above_entry_is_a_short():
    assert size(stop=82000.0).side == "sell"


def test_rounding_is_always_down():
    s = size(stop=79000.0, max_position_pct=1.0)  # 50 USDT / 1000 = 0.05 exactly
    assert s.quantity == 0.05
    s = size(stop=79001.0, max_position_pct=1.0)  # 0.050050... -> 0.05, never 0.051
    assert s.quantity == 0.05


def test_loss_at_stop_includes_round_trip_costs():
    s = size(stop=79000.0, max_position_pct=1.0)
    price_loss_inr = 0.05 * 1000 * 100
    costs_inr = 0.05 * 80000 * 2 * (5.9 + 3.0) / 1e4 * 100
    assert s.loss_at_stop_inr == pytest.approx(price_loss_inr + costs_inr)
    assert s.loss_at_stop_pct == pytest.approx(s.loss_at_stop_inr / 500_000)


def test_leverage_above_cap_is_refused():
    with pytest.raises(SizingRefused, match="max_leverage"):
        size(leverage=5.0)


def test_too_small_for_exchange_minimum_is_refused():
    with pytest.raises(SizingRefused, match="minimum"):
        size(capital=20_000.0)  # 20% cap = 40 USDT, below the 60 USDT minimum


def test_unset_capital_is_refused():
    with pytest.raises(SizingRefused, match="capital"):
        size(capital=0.0)


# --- risk limits ---------------------------------------------------------------

S = Settings(_env_file=None, capital_inr=500_000.0)


def test_clean_state_has_no_violations():
    assert risk.violations("B-BTC_USDT", 0.01, 1.0, RiskState(halted=False), S) == []


def test_halt_blocks_everything(tmp_path):
    f = tmp_path / "HALT"
    assert not risk.is_halted(f)
    risk.halt("/halt from Telegram", f)
    assert risk.is_halted(f)
    assert "HALT" in risk.violations("B-BTC_USDT", 0.01, 1.0, RiskState(halted=True), S)[0]


def test_daily_loss_limit_halts_proposals():
    state = RiskState(halted=False, realized_pnl_today_inr=-15_000.0)  # exactly -3%
    assert any("daily loss" in v for v in risk.violations("B-BTC_USDT", 0.01, 1.0, state, S))


def test_max_open_positions_and_no_stacking():
    state = RiskState(halted=False, open_pairs={"B-BTC_USDT", "B-XAU_USDT"})
    v = risk.violations("B-ETH_USDT", 0.01, 1.0, state, S)
    assert any("positions open" in x for x in v)
    state = RiskState(halted=False, pending_pairs={"B-BTC_USDT"})
    assert any("already" in x for x in risk.violations("B-BTC_USDT", 0.01, 1.0, state, S))


def test_unset_capital_blocks_proposals():
    s = Settings(_env_file=None)
    assert any("capital" in v for v in risk.violations("B-BTC_USDT", 0.01, 1.0,
                                                       RiskState(halted=False), s))
