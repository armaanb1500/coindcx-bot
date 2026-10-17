import numpy as np
import pandas as pd
import pytest
from scipy import stats

from bot.research.deflated import (deflated_sharpe_from_returns, deflated_sharpe_ratio,
                                   expected_max_sharpe)


def test_matches_worked_example_in_the_paper():
    # Bailey & López de Prado (2014), section on the numerical example:
    # annualized SR 2.5, daily data (250/yr), T = 1250, N = 100,
    # annualized variance of trial Sharpes 0.5, skew -3, kurtosis 10 -> DSR ~ 0.90.
    sr = 2.5 / np.sqrt(250)
    variance = 0.5 / 250
    assert expected_max_sharpe(variance, 100) == pytest.approx(0.1132, abs=1e-4)
    dsr = deflated_sharpe_ratio(sr, variance, 100, 1250, skew=-3, kurtosis=10)
    assert dsr == pytest.approx(0.9004, abs=1e-3)


def test_single_trial_reduces_to_probabilistic_sharpe_vs_zero():
    sr, t = 0.05, 1000
    expected = stats.norm.cdf(sr * np.sqrt(t - 1) / np.sqrt(1 + 0.5 * sr**2))
    assert deflated_sharpe_ratio(sr, 0.0, 1, t, skew=0, kurtosis=3) == pytest.approx(expected)


def test_more_trials_means_more_deflation():
    args = dict(sr_per_period=0.08, sharpe_variance=0.002, n_obs=1000, skew=0, kurtosis=3)
    values = [deflated_sharpe_ratio(n_trials=n, **args) for n in (2, 10, 100, 1000)]
    assert values == sorted(values, reverse=True)


def test_annualized_sharpe_would_wildly_overstate():
    # The article's bug: an annualized Sharpe makes almost anything look certain.
    honest = deflated_sharpe_ratio(0.5 / np.sqrt(365), 0.001, 20, 730, 0, 3)
    buggy = deflated_sharpe_ratio(0.5, 0.001, 20, 730, 0, 3)
    assert honest < 0.95 < buggy


def test_from_returns_uses_raw_kurtosis_and_all_trials():
    rng = np.random.default_rng(0)
    r = pd.Series(rng.normal(0.001, 0.02, 2000))
    out = deflated_sharpe_from_returns(r, trial_sharpes=[0.0, 0.02, 0.05])
    assert out["kurtosis"] == pytest.approx(3, abs=0.3)  # raw, not excess
    assert out["n_trials"] == 3
    assert out["trial_sharpe_variance"] == pytest.approx(np.var([0.0, 0.02, 0.05], ddof=1))
