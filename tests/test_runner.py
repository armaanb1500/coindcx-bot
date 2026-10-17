"""PaperBot with fake exchange clients: no network, no Telegram."""

from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from bot.config import Settings
from bot.live.runner import PaperBot
from bot.log import db
from tests.test_proposer import Scripted


class FakeStore:
    def __init__(self, df):
        self.df = df

    def update(self, pair, timeframe):
        return self.df

    def load(self, pair, timeframe):
        return self.df


class FakePublic:
    def __init__(self, price=80000.0, fail_pairs=()):
        self.price, self.fail_pairs = price, set(fail_pairs)

    def instrument(self, pair, margin):
        return {"quantity_increment": "0.001", "min_quantity": "0.001", "min_notional": "6"}

    def current_price(self, pair):
        if pair in self.fail_pairs:
            raise RuntimeError("prices disagree")
        return self.price


class FakePrivate:
    def usdt_inr_rate(self):
        return 100.0


def frame(n=5):
    idx = pd.date_range("2026-10-18", periods=n, freq="h", tz="UTC")
    return pd.DataFrame({"open": 80000.0, "high": 80100.0, "low": 79900.0, "close": 80000.0},
                        index=idx)


@pytest.fixture
def make(tmp_path):
    def _make(signals, public=None, instruments=None):
        s = Settings(_env_file=None, mode="paper", capital_inr=1_000_000.0,
                     instruments=instruments or {"BTC": "B-BTC_USDT"})
        conn = db.connect(tmp_path / "trades.db")
        bot = PaperBot(conn, s, FakeStore(frame(len(signals))), public or FakePublic(),
                       FakePrivate(), Scripted(signals), "1h", "PLUMBING TEST",
                       halt_file=tmp_path / "HALT")
        return bot, conn
    return _make


def test_refuses_any_mode_but_paper(tmp_path):
    s = Settings(_env_file=None, mode="backtest")
    with pytest.raises(RuntimeError, match="paper"):
        PaperBot(None, s, None, None, None, None, "1h", None)


def test_signal_change_creates_one_proposal_and_repeat_bar_creates_none(make):
    bot, conn = make([-1, -1, -1, -1, 1])
    ids, notes = bot.on_bar_close()
    assert len(ids) == 1 and notes == []
    p = db.get_proposal(conn, ids[0])
    assert p["label"] == "PLUMBING TEST" and p["side"] == "buy" and p["status"] == "pending"
    # Same bar again (e.g. a restart): the BTC proposal is still pending, so it's refused.
    ids, notes = bot.on_bar_close()
    assert ids == [] and "already has an open position or live proposal" in notes[0]


def test_one_failing_instrument_does_not_stop_the_other(make):
    bot, _ = make([-1, -1, 1], public=FakePublic(fail_pairs={"B-XAU_USDT"}),
                  instruments={"BTC": "B-BTC_USDT", "XAU": "B-XAU_USDT"})
    ids, notes = bot.on_bar_close()
    assert len(ids) == 1 and "B-XAU_USDT: error" in notes[0]


def test_every_minute_expires_and_reports_message_ids(make):
    bot, conn = make([-1, -1, 1])
    [pid] = bot.on_bar_close()[0]
    db.set_message_id(conn, pid, 4242)
    conn.execute("UPDATE proposals SET expires_at = ? WHERE id = ?",
                 ((datetime.now(UTC) - timedelta(seconds=1)).isoformat(timespec="microseconds"), pid))
    expired, stops = bot.every_minute()
    assert expired == [4242] and stops == []
    assert db.get_proposal(conn, pid)["status"] == "expired"


def test_halt_file_blocks_new_proposals(make):
    bot, _ = make([-1, -1, 1])
    bot.halt_file.write_text("manual\n")
    ids, notes = bot.on_bar_close()
    assert ids == [] and "HALT" in notes[0]


def test_daily_health_can_halt(make):
    bot, conn = make([-1, -1, 1])
    bot.on_bar_close()
    conn.execute("UPDATE proposals SET created_at = ?",
                 ((datetime.now(UTC) - timedelta(days=40)).isoformat(timespec="microseconds"),))
    # 39 flat days: 30-day Sharpe 0 is below half of a backtest Sharpe of 1.0
    problems = bot.daily_health((1.0, -0.2))
    assert problems and bot.halt_file.exists()
