import numpy as np
import pandas as pd

from bot.research import regimes


def series(values):
    idx = pd.date_range("2024-01-01", periods=len(values), freq="D", tz="UTC")
    return pd.Series(values, index=idx, dtype=float)


def test_labels_use_previous_close_and_band():
    close = series([100, 100, 100, 120, 80, 102])
    labels = regimes.label(close, period=3, band=0.05)
    # MA(3) known from bar 2. Bar 3's label is bar 2's state (flat -> chop).
    assert labels.iloc[:3].isna().all()
    assert list(labels.iloc[3:]) == ["chop", "bull", "bear"]


def test_split_reports_each_regime_separately():
    net = series([0.01, 0.01, -0.02, -0.02, 0.0, 0.0])
    labels = series([0, 0, 0, 0, 0, 0]).astype(object)
    labels[:] = ["bull", "bull", "bear", "bear", "chop", None]
    table = regimes.split(net, labels, "1d")
    assert table.loc["bull", "n_obs"] == 2
    assert table.loc["bull", "return"] == (1.01 * 1.01 - 1)
    assert table.loc["bear", "return"] == (0.98 * 0.98 - 1)
    assert table.loc["chop", "share"] == 1 / 5  # unlabelled bar excluded


def test_verdict_says_plainly_when_edge_is_in_one_regime():
    table = pd.DataFrame({"n_obs": [100, 100, 100], "sharpe": [1.2, -0.3, -0.1]},
                         index=["bull", "bear", "chop"])
    assert "ONLY in bull" in regimes.edge_verdict(table)


def test_verdict_flags_regimes_with_too_little_data():
    table = pd.DataFrame({"n_obs": [100, 5, 100], "sharpe": [1.0, np.nan, 0.5]},
                         index=["bull", "bear", "chop"])
    assert "Too little data" in regimes.edge_verdict(table)
    assert "bear" in regimes.edge_verdict(table)
