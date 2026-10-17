"""Split performance into bull, bear and chop, using a 200-period moving average.

    bull: close more than `band` above the MA
    bear: close more than `band` below the MA
    chop: within `band` of the MA (no clear trend)

Each bar's return is labelled with the regime known at the PREVIOUS close, the
same information the position was decided on. Bars before the MA has enough
history get no label and are left out.
"""

import numpy as np
import pandas as pd

from bot.research import metrics

REGIMES = ["bull", "bear", "chop"]


def label(close: pd.Series, period: int = 200, band: float = 0.05) -> pd.Series:
    ma = close.rolling(period).mean()
    regime = pd.Series(np.where(close > ma * (1 + band), "bull",
                                np.where(close < ma * (1 - band), "bear", "chop")),
                       index=close.index, dtype=object)
    regime[ma.isna()] = None
    return regime.shift(1)


def split(net: pd.Series, labels: pd.Series, timeframe: str) -> pd.DataFrame:
    """Metrics per regime. `labels` must cover net's index (compute them on full history)."""
    labels = labels.reindex(net.index)
    known = labels.notna()
    rows = {}
    for regime in REGIMES:
        r = net[labels == regime]
        rows[regime] = {
            "n_obs": len(r),
            "share": len(r) / known.sum() if known.any() else 0.0,
            "sharpe": metrics.sharpe(r, timeframe) if len(r) > 1 else float("nan"),
            # Compounded over just the bars spent in this regime.
            "return": float((1 + r).prod() - 1),
        }
    return pd.DataFrame(rows).T


def edge_verdict(table: pd.DataFrame, min_obs: int = 30) -> str:
    """Plain-language answer to 'where does the edge live?'"""
    present = table[table["n_obs"] >= min_obs]
    missing = [r for r in REGIMES if r not in present.index]
    positive = list(present.index[present["sharpe"] > 0])
    if not positive:
        msg = "No edge in any regime."
    elif len(positive) == 1:
        msg = f"Edge ONLY in {positive[0]}: it depends on one market type."
    else:
        msg = f"Positive Sharpe in {len(positive)} regimes: {', '.join(positive)}."
    if missing:
        msg += f" Too little data (<{min_obs} bars) to judge: {', '.join(missing)}."
    return msg
