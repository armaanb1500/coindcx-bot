from datetime import UTC, datetime, timedelta

import pytest

from bot.live.proposer import Proposal
from bot.log import db


def proposal(**kw):
    base = dict(strategy="s", pair="B-BTC_USDT", side="buy", entry=80000.0, stop=78000.0,
                quantity=0.002, leverage=1.0, notional_usdt=160.0, usdt_inr=102.0,
                loss_at_stop_inr=420.0, loss_at_stop_pct=0.0084,
                signal_time=datetime(2026, 10, 18, tzinfo=UTC), mode="paper", ttl_minutes=5)
    return Proposal(**{**base, **kw})


@pytest.fixture
def conn(tmp_path):
    return db.connect(tmp_path / "trades.db")


def test_double_tap_approves_once(conn):
    p = proposal()
    db.insert_proposal(conn, p)
    assert db.decide(conn, p.id, "approve", 1) == (True, "approved")
    assert db.decide(conn, p.id, "approve", 1) == (False, "already approved")
    rows = conn.execute("SELECT accepted FROM decisions").fetchall()
    assert [r["accepted"] for r in rows] == [1, 0]  # both taps logged


def test_expired_proposal_cannot_be_approved(conn):
    p = proposal(created_at=datetime.now(UTC) - timedelta(minutes=6))
    db.insert_proposal(conn, p)
    assert db.decide(conn, p.id, "approve", 1) == (False, "expired")
    assert db.get_proposal(conn, p.id)["status"] == "expired"


def test_approve_just_before_expiry_works_and_at_expiry_fails(conn):
    p = proposal()
    db.insert_proposal(conn, p)
    assert not db.decide(conn, p.id, "approve", 1, at=p.expires_at)[0]
    q = proposal()
    db.insert_proposal(conn, q)
    assert db.decide(conn, q.id, "approve", 1, at=q.expires_at - timedelta(seconds=1))[0]


def test_reject_then_approve_is_refused(conn):
    p = proposal()
    db.insert_proposal(conn, p)
    db.decide(conn, p.id, "reject", 1)
    assert db.decide(conn, p.id, "approve", 1) == (False, "already rejected")


def test_expire_stale_only_touches_old_pending(conn):
    old, fresh = proposal(created_at=datetime.now(UTC) - timedelta(minutes=10)), proposal()
    db.insert_proposal(conn, old)
    db.insert_proposal(conn, fresh)
    assert db.expire_stale(conn) == [old.id]
    assert db.get_proposal(conn, fresh.id)["status"] == "pending"


def test_one_proposal_can_only_ever_have_one_order(conn):
    p = proposal()
    db.insert_proposal(conn, p)
    first = db.record_order(conn, p.id, "paper", {"qty": 1}, None, "simulated")
    assert first is not None
    assert db.record_order(conn, p.id, "paper", {"qty": 1}, None, "simulated") is None
    assert conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 1


def test_unknown_proposal(conn):
    assert db.decide(conn, "nope", "approve", 1) == (False, "unknown proposal")


def test_timestamps_without_microseconds_still_compare_correctly(conn):
    whole_second = datetime(2026, 10, 18, 12, 0, 0, tzinfo=UTC)
    p = proposal(created_at=whole_second - timedelta(minutes=5))  # expires exactly at whole_second
    db.insert_proposal(conn, p)
    assert not db.decide(conn, p.id, "approve", 1, at=whole_second + timedelta(microseconds=1))[0]


# --- paper positions ------------------------------------------------------------

def open_btc(conn, side="buy", entry=80000.0, qty=0.01, fee=0.5, rate=100.0):
    p = proposal(side=side)
    db.insert_proposal(conn, p)
    return db.open_position(conn, p.id, "paper", "B-BTC_USDT", side, qty, entry, 78000.0, fee, rate)


def test_position_pnl_long_and_short_after_fees(conn):
    long_id = open_btc(conn)
    # +1000 USDT/BTC on 0.01 BTC = +10 USDT, minus 0.5 + 0.5 fees = 9 USDT = 900 INR
    assert db.close_position(conn, long_id, 81000.0, 0.5, "signal") == pytest.approx(900.0)
    short_id = open_btc(conn, side="sell")
    assert db.close_position(conn, short_id, 81000.0, 0.5, "stop") == pytest.approx(-1100.0)


def test_position_can_only_close_once(conn):
    pid = open_btc(conn)
    assert db.close_position(conn, pid, 81000.0, 0.5, "stop") is not None
    assert db.close_position(conn, pid, 70000.0, 0.5, "stop") is None
    assert db.realized_pnl_since(conn, datetime.now(UTC) - timedelta(hours=1)) == pytest.approx(900.0)


def test_only_one_open_position_per_pair(conn):
    open_btc(conn)
    with pytest.raises(Exception):
        open_btc(conn)


def test_open_positions_and_daily_pnl(conn):
    a = open_btc(conn)
    assert db.open_position_for(conn, "B-BTC_USDT")["id"] == a
    db.close_position(conn, a, 81000.0, 0.5, "signal")
    assert db.open_positions(conn) == []
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    assert db.daily_pnl(conn) == {today: pytest.approx(900.0)}
