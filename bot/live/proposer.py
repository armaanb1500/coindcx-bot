"""A proposal: one trade the bot is asking you to approve.

Its id doubles as the client order ID, so the same proposal can never become two
orders, however many times Approve is tapped or a request is retried.
"""

import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta


def new_id() -> str:
    return uuid.uuid4().hex


@dataclass
class Proposal:
    strategy: str
    pair: str
    side: str            # "buy" (long) or "sell" (short)
    entry: float         # USDT
    stop: float          # USDT; every order goes in with its stop
    quantity: float      # in the underlying (e.g. BTC)
    leverage: float
    notional_usdt: float
    usdt_inr: float      # CoinDCX conversion rate used for sizing
    loss_at_stop_inr: float  # includes estimated fees and slippage
    loss_at_stop_pct: float  # of capital
    signal_time: datetime
    mode: str
    ttl_minutes: int
    take_profit: float | None = None
    id: str = field(default_factory=new_id)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    status: str = "pending"

    @property
    def expires_at(self) -> datetime:
        return self.created_at + timedelta(minutes=self.ttl_minutes)

    def as_row(self) -> dict:
        row = asdict(self)
        row["expires_at"] = self.expires_at
        return {k: (iso(v) if isinstance(v, datetime) else v) for k, v in row.items()}


def iso(dt: datetime) -> str:
    """Fixed-width UTC timestamp, so SQLite can compare them as text."""
    return dt.astimezone(UTC).isoformat(timespec="microseconds")
