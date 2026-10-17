"""SQLite log of every proposal, decision, order and fill (data/trades.db).

The approval rules that must never be broken are enforced here, in SQL, so no
code path can skip them:
- a proposal moves out of 'pending' exactly once (double taps lose the race)
- an expired proposal can't be approved
- one proposal can produce at most one order (UNIQUE client_order_id)
"""

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from bot.live.proposer import Proposal, iso

DEFAULT_DB = Path("data/trades.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS proposals (
    id TEXT PRIMARY KEY, created_at TEXT NOT NULL, expires_at TEXT NOT NULL,
    mode TEXT NOT NULL, strategy TEXT NOT NULL, pair TEXT NOT NULL, side TEXT NOT NULL,
    entry REAL NOT NULL, stop REAL NOT NULL, take_profit REAL, quantity REAL NOT NULL,
    leverage REAL NOT NULL, notional_usdt REAL NOT NULL, usdt_inr REAL NOT NULL,
    loss_at_stop_inr REAL NOT NULL, loss_at_stop_pct REAL NOT NULL,
    signal_time TEXT NOT NULL, ttl_minutes INTEGER NOT NULL,
    status TEXT NOT NULL,            -- pending, approved, rejected, expired, cancelled, filled
    status_note TEXT,
    telegram_message_id INTEGER
);
CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY, proposal_id TEXT NOT NULL REFERENCES proposals(id),
    at TEXT NOT NULL, decision TEXT NOT NULL, chat_id INTEGER, accepted INTEGER NOT NULL,
    note TEXT
);
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY, proposal_id TEXT NOT NULL UNIQUE REFERENCES proposals(id),
    client_order_id TEXT NOT NULL UNIQUE, mode TEXT NOT NULL, placed_at TEXT NOT NULL,
    request TEXT NOT NULL, response TEXT, status TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS fills (
    id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL REFERENCES orders(id),
    at TEXT NOT NULL, price REAL NOT NULL, quantity REAL NOT NULL, fee_usdt REAL NOT NULL,
    simulated INTEGER NOT NULL
);
"""


def now_iso() -> str:
    return iso(datetime.now(UTC))


def connect(path: Path = DEFAULT_DB) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, isolation_level=None)  # autocommit; each statement is atomic
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def insert_proposal(conn: sqlite3.Connection, p: Proposal) -> None:
    row = p.as_row()
    cols = ", ".join(row)
    conn.execute(f"INSERT INTO proposals ({cols}) VALUES ({', '.join('?' * len(row))})",
                 list(row.values()))


def get_proposal(conn: sqlite3.Connection, proposal_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM proposals WHERE id = ?", (proposal_id,)).fetchone()


def set_message_id(conn: sqlite3.Connection, proposal_id: str, message_id: int) -> None:
    conn.execute("UPDATE proposals SET telegram_message_id = ? WHERE id = ?",
                 (message_id, proposal_id))


def decide(conn: sqlite3.Connection, proposal_id: str, decision: str, chat_id: int,
           at: datetime | None = None) -> tuple[bool, str]:
    """Approve or reject. Returns (accepted, reason). Every attempt is logged."""
    if decision not in ("approve", "reject"):
        raise ValueError(decision)
    at_iso = iso(at or datetime.now(UTC))
    new_status = "approved" if decision == "approve" else "rejected"
    # One statement: only a pending proposal can move, and only before it expires
    # (rejecting an expired one is harmless, so expiry only blocks approval).
    expiry_rule = "AND expires_at > ?" if decision == "approve" else ""
    params = [new_status, proposal_id] + ([at_iso] if decision == "approve" else [])
    cur = conn.execute(f"UPDATE proposals SET status = ? WHERE id = ? AND status = 'pending' "
                       f"{expiry_rule}", params)
    accepted = cur.rowcount == 1
    if accepted:
        reason = new_status
    else:
        row = get_proposal(conn, proposal_id)
        if row is None:
            reason = "unknown proposal"
        elif row["status"] == "pending":  # still pending, so it failed the expiry rule
            set_status(conn, proposal_id, "expired", "approval arrived after expiry")
            reason = "expired"
        else:
            reason = f"already {row['status']}"
    conn.execute("INSERT INTO decisions (proposal_id, at, decision, chat_id, accepted, note)"
                 " VALUES (?,?,?,?,?,?)",
                 (proposal_id, at_iso, decision, chat_id, int(accepted), reason))
    return accepted, reason


def set_status(conn: sqlite3.Connection, proposal_id: str, status: str, note: str = "") -> None:
    conn.execute("UPDATE proposals SET status = ?, status_note = ? WHERE id = ?",
                 (status, note, proposal_id))


def expire_stale(conn: sqlite3.Connection, at: datetime | None = None) -> list[str]:
    at_iso = iso(at or datetime.now(UTC))
    rows = conn.execute("SELECT id FROM proposals WHERE status = 'pending' AND expires_at <= ?",
                        (at_iso,)).fetchall()
    for r in rows:
        set_status(conn, r["id"], "expired", "no decision before expiry")
    return [r["id"] for r in rows]


def record_order(conn: sqlite3.Connection, proposal_id: str, mode: str, request: dict,
                 response: dict | None, status: str) -> int | None:
    """Returns the order id, or None if this proposal already has an order."""
    try:
        cur = conn.execute(
            "INSERT INTO orders (proposal_id, client_order_id, mode, placed_at, request, response,"
            " status) VALUES (?,?,?,?,?,?,?)",
            (proposal_id, proposal_id, mode, now_iso(), json.dumps(request),
             json.dumps(response) if response is not None else None, status))
    except sqlite3.IntegrityError:
        return None
    return cur.lastrowid


def record_fill(conn: sqlite3.Connection, order_id: int, price: float, quantity: float,
                fee_usdt: float, simulated: bool) -> int:
    cur = conn.execute("INSERT INTO fills (order_id, at, price, quantity, fee_usdt, simulated)"
                       " VALUES (?,?,?,?,?,?)",
                       (order_id, now_iso(), price, quantity, fee_usdt, int(simulated)))
    return cur.lastrowid


def pending_or_open_pairs(conn: sqlite3.Connection) -> set[str]:
    """Pairs with a live proposal or a filled order. Position closing comes with stop tracking."""
    rows = conn.execute("SELECT DISTINCT pair FROM proposals"
                        " WHERE status IN ('pending', 'approved', 'filled')").fetchall()
    return {r["pair"] for r in rows}
