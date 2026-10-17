"""Vectorized backtest engine. It knows nothing about any strategy.

Input: closes and a *signal*, the exposure a strategy wants, decided at each bar's
close using only data up to that close. 1.0 = long 100% of equity in notional,
-0.5 = short 50%, 2.0 = long at 2x leverage.

The engine shifts the signal by one bar itself, so a strategy can't forget to:
a signal at bar t becomes the position held through bar t+1.
"""

from dataclasses import dataclass

import pandas as pd

from bot.config import InstrumentCosts
from bot.timeframes import bar_length


@dataclass
class BacktestResult:
    bars: pd.DataFrame  # per-bar position, returns, costs and equity
    timeframe: str
    tds_mode: str
    funding_note: str

    @property
    def net(self) -> pd.Series:
        return self.bars["net"]

    @property
    def equity(self) -> pd.Series:
        return self.bars["equity"]

    def cost_summary(self) -> dict:
        """Each cost summed in units of starting capital (0.05 = 5% of it)."""
        b = self.bars
        prev_equity = b["equity"].shift(1, fill_value=1.0)
        return {
            "gross_return": b["equity_gross"].iloc[-1] - 1,
            "net_return": b["equity"].iloc[-1] - 1,
            "fees_and_slippage": (b["trading_cost"] * prev_equity).sum(),
            "funding": (b["funding_cost"] * prev_equity).sum(),
            "tds_withheld": (b["tds"] * prev_equity).sum(),
            "tds_mode": self.tds_mode,
            "turnover": b["turnover"].sum(),
            "funding_note": self.funding_note,
        }


def run(close: pd.Series, signal: pd.Series, costs: InstrumentCosts, timeframe: str,
        tds_bps: float, tds_mode: str, max_leverage: float) -> BacktestResult:
    if not close.index.equals(signal.index):
        raise ValueError("signal and close must share the same index")
    if tds_mode not in ("track", "cost"):
        raise ValueError(f"tds_mode must be 'track' or 'cost', not {tds_mode!r}")
    too_big = signal.abs() > max_leverage
    if too_big.any():
        # Refuse, never clip silently.
        raise ValueError(f"signal exceeds max_leverage={max_leverage} at {too_big.idxmax()}: "
                         f"{signal[too_big].iloc[0]}")

    # Act on the next bar. NaN signal (indicator warmup) means flat.
    position = signal.fillna(0.0).shift(1, fill_value=0.0)
    # Simple returns, not log returns: exact for leverage and shorts.
    returns = close.pct_change().fillna(0.0)
    gross = position * returns

    change = position.diff().fillna(position)  # first bar: from flat to position
    turnover = change.abs()
    trading_cost = turnover * (costs.fee_bps + costs.slippage_bps) / 1e4

    # Constant funding, paid on whatever is held, long or short.
    intervals_per_bar = bar_length(timeframe) / pd.Timedelta(hours=costs.funding_interval_hours)
    funding_cost = position.abs() * costs.funding_bps_per_interval / 1e4 * intervals_per_bar

    # TDS is withheld on the sell leg of each trade: closing a long or opening a short.
    sold = (-change).clip(lower=0.0)
    tds = sold * tds_bps / 1e4

    net = gross - trading_cost - funding_cost
    if tds_mode == "cost":
        net = net - tds

    equity = _compound(net)
    bars = pd.DataFrame({
        "close": close, "signal": signal, "position": position, "return": returns,
        "gross": gross, "turnover": turnover, "trading_cost": trading_cost,
        "funding_cost": funding_cost, "tds": tds, "net": net,
        "equity_gross": _compound(gross), "equity": equity,
    })
    note = (f"funding: CONSTANT {costs.funding_bps_per_interval} bps per "
            f"{costs.funding_interval_hours}h on |position|, charged long or short "
            f"(no historical funding data available)")
    return BacktestResult(bars, timeframe, tds_mode, note)


def _compound(returns: pd.Series) -> pd.Series:
    """cumprod(1 + r), floored at zero: once an account is wiped out it stays at zero."""
    growth = (1 + returns).clip(lower=0.0)
    return growth.cumprod()
