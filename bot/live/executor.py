"""Turns an APPROVED proposal into an order. Paper mode only, for now.

Paper mode never calls an order endpoint. It records the order it would have
placed and simulates the fill at the re-fetched price plus slippage.
Live order placement is Phase 4 and deliberately doesn't exist yet.
"""

from collections.abc import Callable
from dataclasses import dataclass

from bot.config import Settings
from bot.log import db

PriceFn = Callable[[str], float]  # pair -> current price in USDT


@dataclass
class ExecResult:
    ok: bool
    message: str


def execute(conn, proposal_id: str, current_price: PriceFn, s: Settings) -> ExecResult:
    p = db.get_proposal(conn, proposal_id)
    if p is None or p["status"] != "approved":
        return ExecResult(False, f"not executable (status: {p['status'] if p else 'unknown'})")

    # Drift check: the market may have moved since the proposal was made.
    price = current_price(p["pair"])
    drift_bps = abs(price - p["entry"]) / p["entry"] * 1e4
    if drift_bps > s.max_drift_bps:
        note = f"price moved {drift_bps:.0f} bps ({p['entry']} -> {price}), max {s.max_drift_bps:.0f}"
        db.set_status(conn, proposal_id, "cancelled", note)
        return ExecResult(False, f"Cancelled: {note}")
    stop_already_hit = price <= p["stop"] if p["side"] == "buy" else price >= p["stop"]
    if stop_already_hit:
        db.set_status(conn, proposal_id, "cancelled", f"price {price} is past the stop")
        return ExecResult(False, f"Cancelled: price {price} is already past the stop {p['stop']}")

    if s.mode != "paper":
        raise RuntimeError(f"mode={s.mode}: only paper execution exists (live is Phase 4)")

    request = {  # what a live order would carry; field names get verified in Phase 4
        "client_order_id": proposal_id, "pair": p["pair"], "side": p["side"],
        "type": "market", "quantity": p["quantity"], "leverage": p["leverage"],
        "stop_loss": p["stop"], "take_profit": p["take_profit"],
        "margin_currency": s.margin_currency,
    }
    order_id = db.record_order(conn, proposal_id, "paper", request, None, "simulated")
    if order_id is None:  # idempotency: this proposal already has its one order
        return ExecResult(False, "Already executed; ignoring duplicate")

    costs = s.costs_for(p["pair"])
    direction = 1 if p["side"] == "buy" else -1
    fill_price = price * (1 + direction * costs.slippage_bps / 1e4)
    fee = fill_price * p["quantity"] * costs.fee_bps / 1e4
    db.record_fill(conn, order_id, fill_price, p["quantity"], fee, simulated=True)
    db.set_status(conn, proposal_id, "filled", "paper fill")
    return ExecResult(True, f"PAPER fill: {p['side']} {p['quantity']} {p['pair']} at "
                            f"{fill_price:.2f} (stop {p['stop']}). No real order was sent.")
