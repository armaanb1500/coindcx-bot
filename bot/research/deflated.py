"""Deflated Sharpe ratio (Bailey & López de Prado, 2014).

Answers: "given that I tried N things, how likely is it that this Sharpe is real
and not just the luckiest of N coin flips?"

Everything here is PER-PERIOD (non-annualized) Sharpe. Passing an annualized
Sharpe is the bug in the source article, so the inputs are named to make that hard.
"""

import numpy as np
import pandas as pd
from scipy import stats

EULER_GAMMA = 0.5772156649015329


def expected_max_sharpe(sharpe_variance: float, n_trials: int) -> float:
    """SR0: the Sharpe the best of N skill-less trials would show by luck alone."""
    if n_trials < 2:
        return 0.0  # one trial: nothing to deflate against
    z1 = stats.norm.ppf(1 - 1 / n_trials)
    z2 = stats.norm.ppf(1 - 1 / (n_trials * np.e))
    return float(np.sqrt(sharpe_variance) * ((1 - EULER_GAMMA) * z1 + EULER_GAMMA * z2))


def deflated_sharpe_ratio(sr_per_period: float, sharpe_variance: float, n_trials: int,
                          n_obs: int, skew: float, kurtosis: float) -> float:
    """Probability that the true Sharpe is above SR0. Gate: > 0.95.

    kurtosis is RAW (a normal distribution has 3), not excess.
    """
    sr0 = expected_max_sharpe(sharpe_variance, n_trials)
    denom = 1 - skew * sr_per_period + (kurtosis - 1) / 4 * sr_per_period**2
    if denom <= 0:
        raise ValueError(f"DSR undefined: variance term {denom:.4f} <= 0")
    z = (sr_per_period - sr0) * np.sqrt(n_obs - 1) / np.sqrt(denom)
    return float(stats.norm.cdf(z))


def deflated_sharpe_from_returns(returns: pd.Series, trial_sharpes: list[float]) -> dict:
    """DSR for one strategy's per-period returns, given per-period Sharpes of ALL trials.

    trial_sharpes must include this strategy's own trial.
    """
    sr = float(returns.mean() / returns.std(ddof=1))
    n = len(trial_sharpes)
    variance = float(np.var(trial_sharpes, ddof=1)) if n > 1 else 0.0
    skew = float(stats.skew(returns))
    kurt = float(stats.kurtosis(returns, fisher=False))
    return {
        "dsr": deflated_sharpe_ratio(sr, variance, n, len(returns), skew, kurt),
        "sr_per_period": sr,
        "sr0_per_period": expected_max_sharpe(variance, n),
        "n_trials": n,
        "trial_sharpe_variance": variance,
        "skew": skew,
        "kurtosis": kurt,
        "n_obs": len(returns),
    }
