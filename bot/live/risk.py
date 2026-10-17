"""Hard limits. The bot refuses to propose anything that breaks one, even if
you would have approved it.

Kill switch: a HALT file in the repo root stops all new proposals. The /halt
Telegram command creates that same file, so both routes leave the same trace and
survive a restart. Delete the file by hand to resume: that's deliberate.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from bot.config import Settings

HALT_FILE = Path("HALT")


def is_halted(halt_file: Path = HALT_FILE) -> bool:
    return halt_file.exists()


def halt(reason: str, halt_file: Path = HALT_FILE) -> None:
    with halt_file.open("a") as f:
        f.write(f"{datetime.now(UTC).isoformat()} {reason}\n")


@dataclass
class RiskState:
    halted: bool
    open_pairs: set[str] = field(default_factory=set)       # filled, not yet closed
    pending_pairs: set[str] = field(default_factory=set)    # proposed or approved
    realized_pnl_today_inr: float = 0.0                     # since 00:00 UTC


def violations(pair: str, loss_at_stop_pct: float, leverage: float, state: RiskState,
               s: Settings) -> list[str]:
    """Every rule this proposal would break. Empty list means it may be proposed."""
    out = []
    if state.halted:
        out.append("HALT is active (HALT file or /halt)")
    if s.capital_inr <= 0:
        out.append("capital_inr is not set")
    elif state.realized_pnl_today_inr <= -s.max_daily_loss_pct * s.capital_inr:
        out.append(f"daily loss limit hit ({state.realized_pnl_today_inr:.0f} INR today); "
                   f"no proposals until 00:00 UTC")
    if leverage > s.max_leverage:
        out.append(f"leverage {leverage} > max_leverage {s.max_leverage}")
    if len(state.open_pairs) >= s.max_open_positions:
        out.append(f"{len(state.open_pairs)} positions open (max {s.max_open_positions})")
    if pair in state.open_pairs or pair in state.pending_pairs:
        out.append(f"{pair} already has an open position or live proposal")
    # Sizing already targets risk_pct; this catches fees pushing it meaningfully over.
    if loss_at_stop_pct > s.risk_pct_per_trade * 1.25:
        out.append(f"loss at stop {loss_at_stop_pct:.2%} > {s.risk_pct_per_trade:.2%} risk limit")
    return out
