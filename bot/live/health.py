"""Daily decay check: is the strategy still behaving like its backtest?

Halts if the last 30 days' Sharpe falls below half the backtest Sharpe, or if
drawdown goes beyond 1.5x the backtest's max drawdown. Days are UTC; P&L is
realized P&L as a fraction of capital_inr.
"""

import pandas as pd

from bot.research import metrics

WINDOW_DAYS = 30


def daily_returns(daily_pnl_inr: dict[str, float], capital_inr: float, start: str,
                  end: str) -> pd.Series:
    """Every UTC day from start to end, with 0 for days nothing closed."""
    days = pd.date_range(start, end, freq="D")
    pnl = pd.Series(daily_pnl_inr, dtype=float)
    pnl.index = pd.to_datetime(pnl.index)
    return pnl.reindex(days, fill_value=0.0) / capital_inr


def check(returns: pd.Series, backtest_sharpe: float, backtest_max_dd: float) -> list[str]:
    """Reasons to halt. Empty list means healthy, or too early to judge Sharpe."""
    problems = []
    equity = (1 + returns).cumprod()
    dd = float(metrics.drawdown(equity).min()) if len(returns) else 0.0
    if dd < 1.5 * backtest_max_dd:  # both negative
        problems.append(f"drawdown {dd:.1%} is beyond 1.5x the backtest's {backtest_max_dd:.1%}")
    if len(returns) >= WINDOW_DAYS:
        recent = metrics.sharpe(returns.iloc[-WINDOW_DAYS:], "1d")
        if recent < 0.5 * backtest_sharpe:
            problems.append(f"30-day Sharpe {recent:.2f} is below half the backtest's "
                            f"{backtest_sharpe:.2f}")
    return problems
