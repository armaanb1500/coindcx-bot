"""Position size from entry and stop distance.

Risk-based sizing: decide how many rupees you're willing to lose if the stop hits
(risk_pct_per_trade x capital), then buy exactly enough that hitting the stop
loses that much. A wide stop means a small position; a tight stop, a bigger one.

Then cap it: notional may not exceed max_position_pct of capital. Shrinking a
position only lowers risk, so the cap shrinks rather than refuses. Leverage above
the hard cap is refused outright.
"""

from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal


class SizingRefused(Exception):
    pass


@dataclass
class Instrument:
    pair: str
    qty_step: float      # quantity_increment
    min_qty: float       # min_quantity
    min_notional: float  # min_notional, USDT
    fee_bps: float       # taker fee, per side
    slippage_bps: float


@dataclass
class Size:
    side: str
    quantity: float
    notional_usdt: float
    margin_inr: float
    loss_at_stop_inr: float  # price loss + round-trip fees and slippage
    loss_at_stop_pct: float
    capped: bool             # True if max_position_pct shrank it


def size_position(entry: float, stop: float, capital_inr: float, usdt_inr: float,
                  inst: Instrument, risk_pct: float, max_position_pct: float,
                  leverage: float, max_leverage: float) -> Size:
    if capital_inr <= 0:
        raise SizingRefused("capital_inr is not set")
    if leverage > max_leverage:
        raise SizingRefused(f"leverage {leverage} exceeds max_leverage {max_leverage}")
    if leverage < 1:
        raise SizingRefused(f"leverage {leverage} is below 1")
    if entry <= 0 or stop <= 0 or stop == entry:
        raise SizingRefused(f"invalid entry/stop: {entry} / {stop}")
    side = "buy" if stop < entry else "sell"

    per_unit_loss = abs(entry - stop)                      # USDT per 1 unit of the asset
    risk_usdt = capital_inr * risk_pct / usdt_inr
    max_notional_usdt = capital_inr * max_position_pct / usdt_inr

    qty_for_risk = risk_usdt / per_unit_loss
    qty_cap = max_notional_usdt / entry
    qty = _floor_to_step(min(qty_for_risk, qty_cap), inst.qty_step)

    notional = qty * entry
    if qty < inst.min_qty or notional < inst.min_notional:
        raise SizingRefused(
            f"size {qty} ({notional:.2f} USDT) is below the exchange minimum "
            f"({inst.min_qty} / {inst.min_notional} USDT). Capital too small for this stop.")

    # Loss if the stop hits: the price move, plus taker fee and slippage on entry and exit.
    cost_rate = 2 * (inst.fee_bps + inst.slippage_bps) / 1e4
    loss_usdt = qty * per_unit_loss + notional * cost_rate
    loss_inr = loss_usdt * usdt_inr
    return Size(side=side, quantity=qty, notional_usdt=notional,
                margin_inr=notional * usdt_inr / leverage, loss_at_stop_inr=loss_inr,
                loss_at_stop_pct=loss_inr / capital_inr, capped=qty_cap < qty_for_risk)


def _floor_to_step(qty: float, step: float) -> float:
    """Round DOWN to the exchange's quantity step, so rounding never adds risk."""
    d_step = Decimal(str(step))
    return float((Decimal(str(qty)) / d_step).to_integral_value(ROUND_DOWN) * d_step)
