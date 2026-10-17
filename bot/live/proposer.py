"""A proposal: one trade the bot is asking you to approve.

Its id doubles as the client order ID, so the same proposal can never become two
orders, however many times Approve is tapped or a request is retried.
"""

import uuid
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime, timedelta

import pandas as pd

from bot.config import Settings
from bot.live import risk
from bot.live.risk import RiskState
from bot.live.sizing import Instrument, SizingRefused, size_position
from bot.strategies.base import Strategy
from bot.timeframes import bar_length


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
    kind: str = "open"                     # "open", or "flip" (close the open position first)
    closes_position_id: int | None = None
    label: str | None = None               # e.g. "PLUMBING TEST"; shown on the card
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


@dataclass
class Outcome:
    proposal: Proposal | None
    note: str | None  # why nothing was proposed, when worth telling you; None = nothing new


def propose(strategy: Strategy, params: dict, df: pd.DataFrame, timeframe: str, pair: str,
            price: float, usdt_inr: float, inst: Instrument, open_pos, state: RiskState,
            s: Settings, label: str | None = None) -> Outcome:
    """Decide whether the latest CLOSED bar calls for a new proposal.

    A proposal is made only when the signal changed on that bar, mirroring the
    backtest: after a stop-out, or a rejected or expired proposal, nothing is
    proposed again until the signal changes.
    """
    sig = strategy.signal(df, params)
    if len(sig) < 2 or pd.isna(sig.iloc[-1]):
        return Outcome(None, None)  # still warming up
    now, before = sig.iloc[-1], sig.iloc[-2]
    if now == before:
        return Outcome(None, None)

    want = "buy" if now > 0 else "sell" if now < 0 else None
    held = open_pos["side"] if open_pos is not None else None
    if want is None:
        return Outcome(None, f"{pair}: signal went flat. Close-only proposals aren't built yet; "
                             f"any open position keeps its stop.")
    if want == held:
        return Outcome(None, None)

    dist = strategy.stop_distance(df, params).iloc[-1]
    if not dist > 0:
        return Outcome(None, f"{pair}: no stop distance available, so no proposal "
                             f"(no naked positions)")
    stop = price - dist if want == "buy" else price + dist
    try:
        size = size_position(price, stop, s.capital_inr, usdt_inr, inst, s.risk_pct_per_trade,
                             s.max_position_pct, s.leverage, s.max_leverage)
    except SizingRefused as e:
        return Outcome(None, f"{pair}: signal skipped, sizing refused: {e}")

    # A flip closes the open position first, so that position doesn't count against it.
    if held is not None:
        state = replace(state, open_pairs=state.open_pairs - {pair})
    problems = risk.violations(pair, size.loss_at_stop_pct, s.leverage, state, s)
    if problems:
        return Outcome(None, f"{pair}: signal skipped: " + "; ".join(problems))

    return Outcome(Proposal(
        strategy=strategy.name, pair=pair, side=want, entry=price, stop=stop,
        quantity=size.quantity, leverage=s.leverage, notional_usdt=size.notional_usdt,
        usdt_inr=usdt_inr, loss_at_stop_inr=size.loss_at_stop_inr,
        loss_at_stop_pct=size.loss_at_stop_pct,
        signal_time=(df.index[-1] + bar_length(timeframe)).to_pydatetime(),  # the bar's close
        mode=s.mode, ttl_minutes=s.proposal_ttl_minutes,
        kind="flip" if held else "open",
        closes_position_id=open_pos["id"] if open_pos is not None else None,
        label=label), None)
