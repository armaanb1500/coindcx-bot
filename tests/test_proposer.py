import pandas as pd
import pytest

from bot.config import Settings
from bot.live.proposer import propose
from bot.live.risk import RiskState
from bot.live.sizing import Instrument
from bot.strategies.base import Strategy

BTC = Instrument("B-BTC_USDT", qty_step=0.001, min_qty=0.001, min_notional=60.0,
                 fee_bps=5.9, slippage_bps=3.0)
S = Settings(_env_file=None, mode="paper", capital_inr=1_000_000.0)


class Scripted(Strategy):
    """Signal and stop distance given directly, so each test controls the last bars."""
    name = "scripted"

    def __init__(self, signals, dist=2000.0):
        self.signals, self.dist = signals, dist

    def fit(self, train):
        return {}

    def signal(self, df, params):
        return pd.Series(self.signals, index=df.index, dtype=float)

    def stop_distance(self, df, params):
        return pd.Series(self.dist, index=df.index, dtype=float)


def frame(n):
    idx = pd.date_range("2026-10-18", periods=n, freq="h", tz="UTC")
    return pd.DataFrame({"close": 80000.0}, index=idx)


def run(signals, open_pos=None, state=None, dist=2000.0, s=S):
    df = frame(len(signals))
    return propose(Scripted(signals, dist), {}, df, "1h", "B-BTC_USDT", 80000.0, 100.0, BTC,
                   open_pos, state or RiskState(halted=False), s, label="PLUMBING TEST")


def test_no_change_no_proposal():
    out = run([1, 1, 1])
    assert out.proposal is None and out.note is None


def test_fresh_cross_opens_a_long_with_stop_below():
    out = run([-1, -1, 1])
    p = out.proposal
    assert p.side == "buy" and p.kind == "open" and p.stop == 78000.0
    assert p.label == "PLUMBING TEST" and p.mode == "paper"
    assert p.signal_time == pd.Timestamp("2026-10-18 03:00", tz="UTC")  # close of last bar


def test_cross_against_open_position_is_a_flip():
    out = run([1, 1, -1], open_pos={"id": 7, "side": "buy"},
              state=RiskState(halted=False, open_pairs={"B-BTC_USDT"}))
    p = out.proposal
    assert p.kind == "flip" and p.closes_position_id == 7
    assert p.side == "sell" and p.stop == 82000.0


def test_same_side_as_open_position_proposes_nothing():
    assert run([-1, -1, 1], open_pos={"id": 7, "side": "buy"}).proposal is None


def test_risk_violation_is_explained_not_proposed():
    out = run([-1, -1, 1], state=RiskState(halted=True))
    assert out.proposal is None and "HALT" in out.note


def test_missing_stop_means_no_proposal():
    out = run([-1, -1, 1], dist=float("nan"))
    assert out.proposal is None and "no naked positions" in out.note


def test_sizing_refusal_is_explained():
    out = run([-1, -1, 1], s=Settings(_env_file=None, mode="paper", capital_inr=10_000.0))
    assert out.proposal is None and "minimum" in out.note


def test_warmup_proposes_nothing():
    assert run([float("nan"), float("nan"), float("nan")]).proposal is None
