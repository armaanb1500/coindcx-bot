"""Every backtest ever run, so the deflated Sharpe gets an honest trial count.

Stored in SQLite (data/research.db). Rows are never deleted: deleting a bad
trial is exactly the kind of self-deception this table exists to prevent.

Counting rule: a trial is a distinct (strategy, params, instrument, timeframe).
Re-running the same config later (e.g. with more data) is not a new idea, so it
counts once, using its most recent Sharpe.
"""

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
from scipy import stats

DEFAULT_DB = Path("data/research.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS trials (
    id                INTEGER PRIMARY KEY,
    run_at            TEXT NOT NULL,
    kind              TEXT NOT NULL,   -- 'backtest' or 'walkforward'
    strategy          TEXT NOT NULL,
    params            TEXT NOT NULL,   -- JSON, sorted keys
    instrument        TEXT NOT NULL,
    timeframe         TEXT NOT NULL,
    data_start        TEXT NOT NULL,
    data_end          TEXT NOT NULL,
    n_obs             INTEGER NOT NULL,
    sharpe_per_period REAL NOT NULL,
    skew              REAL,
    kurtosis          REAL,
    net_return        REAL,
    source            TEXT             -- which script ran it
);
"""


def connect(path: Path = DEFAULT_DB) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute(SCHEMA)
    return conn


def record(conn: sqlite3.Connection, *, kind: str, strategy: str, params: dict,
           instrument: str, timeframe: str, net: pd.Series, source: str) -> int:
    std = net.std(ddof=1)
    cur = conn.execute(
        "INSERT INTO trials (run_at, kind, strategy, params, instrument, timeframe, data_start,"
        " data_end, n_obs, sharpe_per_period, skew, kurtosis, net_return, source)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (datetime.now(UTC).isoformat(), kind, strategy, json.dumps(params, sort_keys=True),
         instrument, timeframe, net.index[0].isoformat(), net.index[-1].isoformat(), len(net),
         float(net.mean() / std) if std > 0 else 0.0, float(stats.skew(net)),
         float(stats.kurtosis(net, fisher=False)), float((1 + net).prod() - 1), source),
    )
    conn.commit()
    return cur.lastrowid


def trial_sharpes(conn: sqlite3.Connection, instrument: str, timeframe: str,
                  kind: str = "backtest") -> list[float]:
    """Per-period Sharpe of every distinct config tried on this instrument and timeframe.

    Per-period Sharpes are only comparable at the same bar size, hence the filter.
    """
    rows = conn.execute(
        """SELECT t.sharpe_per_period FROM trials t
           JOIN (SELECT strategy, params, MAX(id) AS id FROM trials
                 WHERE instrument = ? AND timeframe = ? AND kind = ?
                 GROUP BY strategy, params) latest ON t.id = latest.id""",
        (instrument, timeframe, kind),
    ).fetchall()
    return [r[0] for r in rows]


def count_all(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM trials").fetchone()[0]
