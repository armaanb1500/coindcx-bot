"""The validation gates. A strategy must pass ALL of them before paper trading.

Each check returns a Gate with a plain reason, so a rejection always says why.
"""

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from bot.config import Settings

CRITIC_DIR = Path("reports/critic")


@dataclass
class Gate:
    name: str
    passed: bool
    detail: str


# The code a critic review covers: the strategy plus the engine it runs through.
# If any of it changes, the review is stale and must be redone.
REVIEWED_CODE = ["bot/research/backtest.py", "bot/data/coindcx.py", "bot/data/store.py"]


def code_hash(strategy_file: str, files: list[str] = REVIEWED_CODE) -> str:
    h = hashlib.sha256()
    for f in [strategy_file, *files]:
        h.update(Path(f).read_bytes())
    return h.hexdigest()[:12]


def critic(strategy_name: str, strategy_file: str, critic_dir: Path = CRITIC_DIR,
           files: list[str] = REVIEWED_CODE) -> Gate:
    """Gate 1. The review is written by hand (or by Claude) as markdown. It must
    contain 'Code hash: <hash>' matching the current code, and end with
    'Verdict: PASS' or 'Verdict: FAIL'."""
    path = critic_dir / f"{strategy_name}.md"
    if not path.exists():
        return Gate("1. Critic review", False, f"not done: {path} missing")
    text = path.read_text()
    current = code_hash(strategy_file, files)
    reviewed = re.search(r"^Code hash:\s*(\w+)", text, re.MULTILINE)
    if not reviewed or reviewed.group(1) != current:
        return Gate("1. Critic review", False,
                    f"STALE: code changed since {path} was written (now {current})")
    found = re.search(r"^Verdict:\s*(PASS|FAIL)\b", text, re.MULTILINE)
    if not found:
        return Gate("1. Critic review", False, f"{path} has no 'Verdict: PASS|FAIL' line")
    return Gate("1. Critic review", found.group(1) == "PASS", f"see {path} (code {current})")


def deflated_sharpe(dsr: dict, s: Settings) -> Gate:
    ok = dsr["dsr"] > s.dsr_min
    return Gate("2. Deflated Sharpe", ok,
                f"DSR {dsr['dsr']:.3f} vs required > {s.dsr_min} "
                f"(N = {dsr['n_trials']} trials, T = {dsr['n_obs']} bars)")


def walk_forward(summary: dict, s: Settings) -> Gate:
    frac_ok = summary["positive_fold_frac"] >= s.wf_min_positive_fold_frac
    worst_ok = summary["worst_fold_return"] >= s.wf_worst_fold_floor
    return Gate("3. Walk-forward", frac_ok and worst_ok,
                f"{summary['positive_folds']}/{summary['n_folds']} folds positive "
                f"(need {s.wf_min_positive_fold_frac:.0%}); worst fold "
                f"{summary['worst_fold_return']:.1%} (floor {s.wf_worst_fold_floor:.0%})")


def regimes(table: pd.DataFrame, verdict: str, s: Settings, min_obs: int = 30) -> Gate:
    usable = table[table["n_obs"] >= min_obs]
    n_positive = int((usable["sharpe"] > 0).sum())
    return Gate("4. Regime split", n_positive >= s.regime_min_positive,
                f"{verdict} (need positive Sharpe in >= {s.regime_min_positive})")


def leakage(sharpe_annual: float, s: Settings) -> Gate:
    ok = sharpe_annual <= s.leakage_sharpe
    detail = f"annualized Sharpe {sharpe_annual:.2f}"
    if not ok:
        detail += f" > {s.leakage_sharpe}: presumed LEAKAGE until proven otherwise"
    return Gate("5. Leakage check", ok, detail)
