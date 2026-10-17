"""Performance metrics. Annualization always comes from the timeframe."""

import numpy as np
import pandas as pd

from bot.timeframes import bar_length, periods_per_year


def sharpe_per_period(returns: pd.Series) -> float:
    """Non-annualized Sharpe (deflated Sharpe needs this one in Phase 2)."""
    std = returns.std(ddof=1)
    return float(returns.mean() / std) if std > 0 else 0.0


def sharpe(returns: pd.Series, timeframe: str) -> float:
    return sharpe_per_period(returns) * np.sqrt(periods_per_year(timeframe))


def drawdown(equity: pd.Series) -> pd.Series:
    """Fraction below the running peak, with starting capital (1.0) as the first peak."""
    peak = equity.cummax().clip(lower=1.0)
    return equity / peak - 1


def longest_drawdown_bars(equity: pd.Series) -> int:
    underwater = (drawdown(equity) < 0).to_numpy()
    longest = run = 0
    for below in underwater:
        run = run + 1 if below else 0
        longest = max(longest, run)
    return longest


def summary(returns: pd.Series, equity: pd.Series, timeframe: str) -> dict:
    n = len(returns)
    ppy = periods_per_year(timeframe)
    final = float(equity.iloc[-1])
    annual = final ** (ppy / n) - 1 if final > 0 else -1.0
    max_dd = float(drawdown(equity).min())
    longest = longest_drawdown_bars(equity)
    return {
        "sharpe": sharpe(returns, timeframe),
        "sharpe_per_period": sharpe_per_period(returns),
        "annual_return": annual,
        "max_drawdown": max_dd,
        "longest_drawdown_bars": longest,
        "longest_drawdown": longest * bar_length(timeframe),
        "calmar": annual / abs(max_dd) if max_dd < 0 else float("inf"),
        "n_obs": n,
        "periods_per_year": ppy,
    }
