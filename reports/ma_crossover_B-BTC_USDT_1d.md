# Research report: ma_crossover on B-BTC_USDT 1d

**Verdict: REJECTED**

| Gate | Result | Detail |
|---|---|---|
| 1. Critic review | PASS | see reports/critic/ma_crossover.md (code 51ef75899427) |
| 2. Deflated Sharpe | FAIL | DSR 0.462 vs required > 0.95 (N = 2 trials, T = 2115 bars) |
| 3. Walk-forward | FAIL | 5/7 folds positive (need 60%); worst fold -38.8% (floor -15%) |
| 4. Regime split | FAIL | Edge ONLY in bull: it depends on one market type. (need positive Sharpe in >= 2) |
| 5. Leakage check | PASS | annualized Sharpe 0.04 |

Data: 2115 bars, 2021-01-01 to 2026-10-16 UTC. Params: `{'fast': 50, 'slow': 200, 'exposure': 1.0, 'atr_period': 14, 'atr_mult': 3.0}`.

## Full-sample backtest

| Metric | Value |
|---|---|
| Sharpe (annualized) | 0.04 |
| Annual return | -7.3% |
| Max drawdown | -51.2% |
| Longest drawdown | 947 bars (947 days 00:00:00) |
| Calmar | -0.14 |
| Stop-outs | 6 |
| Gross / net return | -1.6% / -35.5% |
| Fees + slippage | 1.6% of starting capital |
| Funding | 35.0% of starting capital |
| TDS withheld (track mode) | 8.9% of starting capital |

> funding: CONSTANT 1.0 bps per 8h on |position|, charged long or short (no historical funding data available)

## Deflated Sharpe

- Per-period Sharpe: 0.0019
- Expected best-of-N by luck (SR0): 0.0040
- Distinct trials on B-BTC_USDT 1d: N = 2 (trials table holds 14 runs in total)
- Skew 0.37, raw kurtosis 11.12, T = 2115
- **DSR = 0.462**

## Walk-forward (out of sample)

Train 730 days, test 180 days, rolling, warmup = train window.

- Positive folds: **5/7**
- Worst fold: **#5 at -38.8%** (Sharpe -2.08)
- Stitched OOS: Sharpe 0.21, annual 0.4%, max DD -49.0%

| Fold | Test period | Return | Sharpe | Max DD |
|---|---|---|---|---|
| 1 | 2023-01-01 to 2023-06-29 | -16.4% | -1.54 | -16.4% |
| 2 | 2023-06-30 to 2023-12-26 | 9.9% | 0.85 | -9.3% |
| 3 | 2023-12-27 to 2024-06-23 | 40.8% | 1.54 | -21.4% |
| 4 | 2024-06-24 to 2024-12-20 | 6.6% | 0.50 | -29.9% |
| 5 | 2024-12-21 to 2025-06-18 | -38.8% | -2.08 | -43.1% |
| 6 | 2025-06-19 to 2025-12-15 | 6.3% | 0.79 | -10.4% |
| 7 | 2025-12-16 to 2026-06-13 | 13.0% | 0.75 | -29.9% |

## Regimes (out of sample)

| Regime | Bars | Share | Sharpe | Return |
|---|---|---|---|---|
| bull | 795 | 63.1% | 0.42 | 21.3% |
| bear | 272 | 21.6% | -0.07 | -11.1% |
| chop | 193 | 15.3% | -0.13 | -6.0% |

**Edge ONLY in bull: it depends on one market type.**
