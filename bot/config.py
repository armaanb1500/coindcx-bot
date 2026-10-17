"""All settings, limits and costs live here.

Values come from defaults below, overridden by environment variables or `.env`.
Secrets are SecretStr so they never show up when a Settings object is printed.
"""

from typing import Literal

from pydantic import BaseModel, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class InstrumentCosts(BaseModel):
    """Trading costs for one instrument, all in basis points (1 bp = 0.01%)."""

    # Taker fee, because the backtest assumes market orders. CoinDCX publishes
    # fees in percent (0.059 means 0.059%), which is 5.9 bps.
    fee_bps: float
    slippage_bps: float = 3.0
    # No public funding history exists, so we charge a constant every interval,
    # whatever the position's side. That's pessimistic on purpose.
    funding_mode: Literal["constant"] = "constant"
    funding_bps_per_interval: float = 1.0
    funding_interval_hours: int = 8


# Live values from the instrument-details endpoint on 2026-10-17.
DEFAULT_COSTS = {
    "B-BTC_USDT": InstrumentCosts(fee_bps=5.9, slippage_bps=3.0, funding_interval_hours=8),
    "B-XAU_USDT": InstrumentCosts(fee_bps=1.18, slippage_bps=5.0, funding_interval_hours=4),
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    mode: Literal["backtest", "paper", "live"] = "backtest"
    i_understand_live_trading: str = "no"

    # Secrets (Phase 3+). Empty by default so research runs need no .env.
    coindcx_api_key: SecretStr = SecretStr("")
    coindcx_api_secret: SecretStr = SecretStr("")
    telegram_bot_token: SecretStr = SecretStr("")
    telegram_chat_id: int = 0

    # Instruments, confirmed from the active-instruments endpoint.
    instruments: dict[str, str] = {"BTC": "B-BTC_USDT", "XAU": "B-XAU_USDT"}
    costs: dict[str, InstrumentCosts] = Field(default_factory=lambda: dict(DEFAULT_COSTS))

    # Section 194S TDS. "track" reports it as a liquidity drag; "cost" subtracts it.
    tds_bps: float = 100.0
    tds_mode: Literal["track", "cost"] = "track"

    # Risk limits.
    risk_pct_per_trade: float = 0.01
    max_position_pct: float = 0.20
    max_leverage: float = 3.0
    max_open_positions: int = 2
    max_daily_loss_pct: float = 0.03

    # Approval flow (Phase 3).
    proposal_ttl_minutes: int = 5
    max_drift_bps: float = 20.0

    @model_validator(mode="after")
    def _live_needs_both_flags(self):
        if self.mode == "live" and self.i_understand_live_trading != "yes":
            raise ValueError("MODE=live also needs I_UNDERSTAND_LIVE_TRADING=yes in .env")
        return self

    def costs_for(self, pair: str) -> InstrumentCosts:
        if pair not in self.costs:
            raise KeyError(f"No cost config for {pair}. Add it to Settings.costs.")
        return self.costs[pair]
