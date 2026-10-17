"""Vectorized backtest engine. It knows nothing about any strategy.

Input: closes and a *signal*, the exposure a strategy wants, decided at each bar's
close using only data up to that close. 1.0 = long 100% of equity in notional,
-0.5 = short 50%, 2.0 = long at 2x leverage.

The engine shifts the signal by one bar itself, so a strategy can't forget to:
a signal at bar t becomes the position held through bar t+1.

Stops (optional): a stop distance per bar, in price units. A position opened at
bar t's close gets its stop at close_t -/+ distance_t. During each later bar, if
the low (long) or high (short) reaches the stop, the position exits at the stop,
or at the open if the bar gapped through it. After a stop-out the position stays
flat until the signal changes. A new position with no stop distance isn't taken.

Position tracking is a plain loop because exits depend on the path; everything
after it (costs, equity) is vectorized.
"""

from dataclasses import dataclass

import numpy as np
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
        tds_bps: float, tds_mode: str, max_leverage: float,
        stop_distance: pd.Series | None = None, ohlc: pd.DataFrame | None = None
        ) -> BacktestResult:
    if not close.index.equals(signal.index):
        raise ValueError("signal and close must share the same index")
    if tds_mode not in ("track", "cost"):
        raise ValueError(f"tds_mode must be 'track' or 'cost', not {tds_mode!r}")
    too_big = signal.abs() > max_leverage
    if too_big.any():
        # Refuse, never clip silently.
        raise ValueError(f"signal exceeds max_leverage={max_leverage} at {too_big.idxmax()}: "
                         f"{signal[too_big].iloc[0]}")

    if stop_distance is not None:
        if ohlc is None:
            raise ValueError("stops need ohlc with open/high/low columns")
        if not (stop_distance.index.equals(close.index) and ohlc.index.equals(close.index)):
            raise ValueError("stop_distance and ohlc must share close's index")

    sim = _simulate(close, signal.fillna(0.0), stop_distance, ohlc)
    idx = close.index
    position = pd.Series(sim["position"], index=idx)
    # Simple returns, not log returns: exact for leverage and shorts.
    returns = close.pct_change().fillna(0.0)
    gross = pd.Series(sim["gross"], index=idx)

    entry_change = pd.Series(sim["entry_change"], index=idx)  # at the bar's start
    exit_change = pd.Series(sim["exit_change"], index=idx)    # stop exits, during the bar
    turnover = entry_change.abs() + exit_change.abs()
    trading_cost = turnover * (costs.fee_bps + costs.slippage_bps) / 1e4

    # Constant funding, paid on whatever is held, long or short.
    intervals_per_bar = bar_length(timeframe) / pd.Timedelta(hours=costs.funding_interval_hours)
    funding_cost = position.abs() * costs.funding_bps_per_interval / 1e4 * intervals_per_bar

    # TDS is withheld on the sell leg of each trade: closing a long or opening a short.
    sold = (-entry_change).clip(lower=0.0) + (-exit_change).clip(lower=0.0)
    tds = sold * tds_bps / 1e4

    net = gross - trading_cost - funding_cost
    if tds_mode == "cost":
        net = net - tds

    equity = _compound(net)
    bars = pd.DataFrame({
        "close": close, "signal": signal, "position": position, "return": returns,
        "gross": gross, "turnover": turnover, "trading_cost": trading_cost,
        "funding_cost": funding_cost, "tds": tds, "net": net,
        "stop": sim["stop"], "stopped": sim["stopped"],
        "equity_gross": _compound(gross), "equity": equity,
    })
    note = (f"funding: CONSTANT {costs.funding_bps_per_interval} bps per "
            f"{costs.funding_interval_hours}h on |position|, charged long or short "
            f"(no historical funding data available)")
    return BacktestResult(bars, timeframe, tds_mode, note)


def _simulate(close: pd.Series, target: pd.Series, stop_distance: pd.Series | None,
              ohlc: pd.DataFrame | None) -> dict:
    """Walk bar by bar: what's held during each bar, and what it earned."""
    c = close.to_numpy(dtype=float)
    want_by_bar = target.to_numpy(dtype=float)
    stops_on = stop_distance is not None
    if stops_on:
        dist = stop_distance.to_numpy(dtype=float)
        o, h, lo = (ohlc[k].to_numpy(dtype=float) for k in ("open", "high", "low"))

    n = len(c)
    out = {k: np.zeros(n) for k in ("position", "gross", "entry_change", "exit_change")}
    out["stop"] = np.full(n, np.nan)
    out["stopped"] = np.zeros(n, dtype=bool)

    held, stop, blocked = 0.0, np.nan, None  # blocked: a target we were stopped out of
    for t in range(1, n):
        want = want_by_bar[t - 1]  # decided at the previous close: act on the next bar
        if blocked is not None:
            if want == blocked:
                want = 0.0  # stay out until the signal changes
            else:
                blocked = None
        opening = want != 0 and (held == 0 or np.sign(want) != np.sign(held))
        if opening and stops_on:
            if dist[t - 1] > 0:
                stop = c[t - 1] - np.sign(want) * dist[t - 1]
            else:
                want = 0.0  # no stop available: no naked positions
        out["entry_change"][t] = want - held
        held = want
        if held == 0:
            stop = np.nan
        out["position"][t] = held
        out["stop"][t] = stop

        exit_price = c[t]
        hit = False
        if stops_on and held > 0 and lo[t] <= stop:
            exit_price, hit = min(o[t], stop), True  # gap down through the stop fills at the open
        elif stops_on and held < 0 and h[t] >= stop:
            exit_price, hit = max(o[t], stop), True
        out["gross"][t] = held * (exit_price / c[t - 1] - 1)
        if hit:
            out["stopped"][t] = True
            out["exit_change"][t] = -held
            blocked = want_by_bar[t - 1]
            held, stop = 0.0, np.nan
    return out


def _compound(returns: pd.Series) -> pd.Series:
    """cumprod(1 + r), floored at zero: once an account is wiped out it stays at zero."""
    growth = (1 + returns).clip(lower=0.0)
    return growth.cumprod()
