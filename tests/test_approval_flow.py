"""The approval flow end to end, without Telegram or the network."""

from datetime import UTC, datetime, timedelta

import pytest

from bot.config import Settings
from bot.live.telegram_bot import ApprovalService, format_card, keyboard
from bot.log import db
from tests.test_log_db import proposal

ME, STRANGER = 111, 999


@pytest.fixture
def setup(tmp_path):
    s = Settings(_env_file=None, mode="paper", telegram_chat_id=ME, capital_inr=500_000.0,
                 max_drift_bps=20.0)
    conn = db.connect(tmp_path / "trades.db")
    price = {"B-BTC_USDT": 80000.0}
    service = ApprovalService(conn, s, lambda pair: price[pair], halt_file=tmp_path / "HALT")
    return service, conn, price


def add(conn, **kw):
    p = proposal(**kw)
    db.insert_proposal(conn, p)
    return p


def test_approve_paper_fills_once_and_never_twice(setup):
    service, conn, _ = setup
    p = add(conn)
    assert "PAPER fill" in service.on_button(ME, f"approve:{p.id}")
    assert service.on_button(ME, f"approve:{p.id}") == "Not done: already filled"
    assert conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 1
    assert conn.execute("SELECT simulated FROM fills").fetchone()[0] == 1


def test_strangers_are_ignored_silently(setup):
    service, conn, _ = setup
    p = add(conn)
    assert service.on_button(STRANGER, f"approve:{p.id}") is None
    assert service.on_halt(STRANGER) is None
    assert service.on_status(STRANGER) is None
    assert db.get_proposal(conn, p.id)["status"] == "pending"
    assert conn.execute("SELECT COUNT(*) FROM decisions").fetchone()[0] == 0


def test_expired_proposal_is_not_executed(setup):
    service, conn, _ = setup
    p = add(conn, created_at=datetime.now(UTC) - timedelta(minutes=6))
    assert service.on_button(ME, f"approve:{p.id}") == "Not done: expired"
    assert conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 0


def test_drift_cancels_instead_of_executing(setup):
    service, conn, price = setup
    p = add(conn)
    price["B-BTC_USDT"] = 80000.0 * 1.003  # 30 bps away, max is 20
    assert service.on_button(ME, f"approve:{p.id}").startswith("Cancelled: price moved 30 bps")
    assert db.get_proposal(conn, p.id)["status"] == "cancelled"
    assert conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 0


def test_price_already_past_stop_cancels(setup):
    service, conn, price = setup
    p = add(conn, entry=80000.0, stop=79990.0)
    price["B-BTC_USDT"] = 79985.0  # within drift limit, but below the stop
    assert "past the stop" in service.on_button(ME, f"approve:{p.id}")


def test_reject(setup):
    service, conn, _ = setup
    p = add(conn)
    assert service.on_button(ME, f"reject:{p.id}") == "Rejected."
    assert db.get_proposal(conn, p.id)["status"] == "rejected"


def test_halt_writes_file_and_status_reports_it(setup):
    service, conn, _ = setup
    assert "HALTED" in service.on_halt(ME)
    assert service.halt_file.exists()
    assert "Halted: YES" in service.on_status(ME)


def test_garbage_callback_data_is_ignored(setup):
    service, _, _ = setup
    assert service.on_button(ME, "delete:everything") is None


def test_card_shows_everything_the_spec_requires(setup):
    service, conn, _ = setup
    p = add(conn, take_profit=84000.0)
    text = format_card(db.get_proposal(conn, p.id), service.s)
    for needed in ("LONG B-BTC_USDT", "Entry", "Stop", "Target", "Size", "notional", "Leverage",
                   "Loss if stop hits: ₹420", "% of capital", "Strategy", "Signal", "Expires"):
        assert needed in text
    buttons = keyboard(p.id).inline_keyboard[0]
    assert [b.text for b in buttons] == ["Approve", "Reject"]
    assert all(len(b.callback_data.encode()) <= 64 for b in buttons)  # Telegram's limit


# --- flips, stops, health -------------------------------------------------------

from bot.live import executor, health  # noqa: E402


def test_flip_closes_old_position_and_opens_new(setup):
    service, conn, _ = setup
    first = add(conn)
    service.on_button(ME, f"approve:{first.id}")
    old = db.open_position_for(conn, "B-BTC_USDT")
    flip = add(conn, side="sell", stop=82000.0, kind="flip", closes_position_id=old["id"])
    text = service.on_button(ME, f"approve:{flip.id}")
    assert "Closed buy" in text and "PAPER fill: sell" in text
    positions = conn.execute("SELECT side, closed_at, exit_reason FROM positions ORDER BY id").fetchall()
    assert [(r["side"], r["closed_at"] is not None, r["exit_reason"]) for r in positions] == \
        [("buy", True, "signal"), ("sell", False, None)]


def test_stop_monitor_closes_at_the_worse_price(setup):
    service, conn, price = setup
    p = add(conn)  # long, stop 78000
    service.on_button(ME, f"approve:{p.id}")
    price["B-BTC_USDT"] = 78500.0
    assert executor.check_stops(conn, lambda pair: price[pair], service.s) == []
    price["B-BTC_USDT"] = 77000.0  # gapped through the stop
    [msg] = executor.check_stops(conn, lambda pair: price[pair], service.s)
    assert "STOP HIT" in msg
    pos = conn.execute("SELECT * FROM positions").fetchone()
    assert pos["exit_price"] < 77000.0 and pos["exit_reason"] == "stop"
    assert executor.check_stops(conn, lambda pair: price[pair], service.s) == []  # closed once


def test_health_halts_on_drawdown_and_decayed_sharpe():
    flat = health.daily_returns({}, 100_000, "2026-09-01", "2026-09-30")
    assert health.check(flat, backtest_sharpe=1.0, backtest_max_dd=-0.2) != []  # Sharpe 0 < 0.5
    bad = health.daily_returns({"2026-09-02": -40_000}, 100_000, "2026-09-01", "2026-09-05")
    assert any("drawdown" in p for p in health.check(bad, 1.0, -0.2))  # -40% < -30%
    ok = health.daily_returns({"2026-09-02": 1_000}, 100_000, "2026-09-01", "2026-09-05")
    assert health.check(ok, 1.0, -0.2) == []  # too early to judge Sharpe, drawdown fine


def test_card_shows_label_and_flip(setup):
    service, conn, _ = setup
    p = add(conn, side="sell", stop=82000.0, kind="flip", closes_position_id=1,
            label="PLUMBING TEST")
    text = format_card(db.get_proposal(conn, p.id), service.s)
    assert text.startswith("[PLUMBING TEST]")
    assert "FLIP: closes your open LONG first" in text
