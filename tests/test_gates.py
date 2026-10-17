import pandas as pd

from bot.config import Settings
from bot.research import gates

S = Settings(_env_file=None)


def critic(tmp_path, text=None):
    code = tmp_path / "strategy.py"
    if not code.exists():
        code.write_text("x = 1\n")
    if text is not None:
        (tmp_path / "x.md").write_text(text)
    return gates.critic("x", str(code), tmp_path, files=[])


def test_critic_missing_or_unclear_fails(tmp_path):
    assert not critic(tmp_path).passed
    h = gates.code_hash(str(tmp_path / "strategy.py"), files=[])
    assert not critic(tmp_path, f"Code hash: {h}\nlooks fine to me").passed


def test_critic_reads_verdict_line(tmp_path):
    critic(tmp_path)  # creates the strategy file
    h = gates.code_hash(str(tmp_path / "strategy.py"), files=[])
    assert critic(tmp_path, f"# review\nCode hash: {h}\nVerdict: PASS\n").passed
    assert not critic(tmp_path, f"# review\nCode hash: {h}\nVerdict: FAIL\n").passed


def test_critic_goes_stale_when_code_changes(tmp_path):
    critic(tmp_path)
    h = gates.code_hash(str(tmp_path / "strategy.py"), files=[])
    assert critic(tmp_path, f"Code hash: {h}\nVerdict: PASS\n").passed
    (tmp_path / "strategy.py").write_text("x = 2\n")
    result = critic(tmp_path)
    assert not result.passed and "STALE" in result.detail


def test_dsr_gate_is_strictly_above_threshold():
    assert not gates.deflated_sharpe({"dsr": 0.95, "n_trials": 3, "n_obs": 100}, S).passed
    assert gates.deflated_sharpe({"dsr": 0.951, "n_trials": 3, "n_obs": 100}, S).passed


def test_walk_forward_judged_on_positive_folds_and_worst_fold_not_average():
    # Great average, but one fold lost 40%: must fail.
    s = {"positive_folds": 5, "n_folds": 6, "positive_fold_frac": 5 / 6,
         "worst_fold_return": -0.40, "mean_fold_return": 0.30}
    assert not gates.walk_forward(s, S).passed
    s.update(worst_fold_return=-0.05)
    assert gates.walk_forward(s, S).passed
    s.update(positive_folds=3, positive_fold_frac=0.5)
    assert not gates.walk_forward(s, S).passed


def test_regime_gate_needs_edge_in_two_regimes():
    table = pd.DataFrame({"n_obs": [100, 100, 100], "sharpe": [1.0, -0.2, -0.1]},
                         index=["bull", "bear", "chop"])
    assert not gates.regimes(table, "", S).passed
    table.loc["chop", "sharpe"] = 0.3
    assert gates.regimes(table, "", S).passed


def test_leakage_gate():
    assert gates.leakage(1.5, S).passed
    result = gates.leakage(2.4, S)
    assert not result.passed and "LEAKAGE" in result.detail
