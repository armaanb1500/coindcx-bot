# Research report: ma_crossover on B-BTC_USDT 1d

**Verdict: REJECTED**

| Gate | Result | Detail |
|---|---|---|
| 1. Critic review | PASS | see reports/critic/ma_crossover.md |
| 2. Deflated Sharpe | FAIL | DSR 0.341 vs required > 0.95 (N = 1 trials, T = 2115 bars) |
| 3. Walk-forward | FAIL | 3/7 folds positive (need 60%); worst fold -50.5% (floor -15%) |
| 4. Regime split | FAIL | Edge ONLY in bull: it depends on one market type. (need positive Sharpe in >= 2) |
| 5. Leakage check | PASS | annualized Sharpe -0.17 |

Data: 2115 bars, 2021-01-01 to 2026-10-16 UTC. Params: `{'fast': 50, 'slow': 200, 'exposure': 1.0}`.

## Full-sample backtest

| Metric | Value |
|---|---|
| Sharpe (annualized) | -0.17 |
| Annual return | -18.8% |
| Max drawdown | -72.9% |
| Longest drawdown | 1914 bars (1914 days 00:00:00) |
| Calmar | -0.26 |
| Gross / net return | -45.7% / -70.1% |
| Fees + slippage | 1.0% of starting capital |
| Funding | 32.0% of starting capital |
| TDS withheld (track mode) | 6.2% of starting capital |

> funding: CONSTANT 1.0 bps per 8h on |position|, charged long or short (no historical funding data available)

## Deflated Sharpe

- Per-period Sharpe: -0.0089
- Expected best-of-N by luck (SR0): 0.0000
- Distinct trials on B-BTC_USDT 1d: N = 1 (trials table holds 4 runs in total)
- Skew 0.26, raw kurtosis 7.47, T = 2115
- **DSR = 0.341**

## Walk-forward (out of sample)

Train 730 days, test 180 days, rolling, warmup = train window.

- Positive folds: **3/7**
- Worst fold: **#5 at -50.5%** (Sharpe -2.80)
- Stitched OOS: Sharpe -0.21, annual -19.1%, max DD -64.6%

| Fold | Test period | Return | Sharpe | Max DD |
|---|---|---|---|---|
| 1 | 2023-01-01 to 2023-06-29 | -13.4% | -0.33 | -40.8% |
| 2 | 2023-06-30 to 2023-12-26 | -27.6% | -1.50 | -41.9% |
| 3 | 2023-12-27 to 2024-06-23 | 40.8% | 1.54 | -21.4% |
| 4 | 2024-06-24 to 2024-12-20 | 6.6% | 0.50 | -29.9% |
| 5 | 2024-12-21 to 2025-06-18 | -50.5% | -2.80 | -55.3% |
| 6 | 2025-06-19 to 2025-12-15 | -8.7% | -0.32 | -26.5% |
| 7 | 2025-12-16 to 2026-06-13 | 13.0% | 0.75 | -29.9% |

## Regimes (out of sample)

| Regime | Bars | Share | Sharpe | Return |
|---|---|---|---|---|
| bull | 795 | 63.1% | 0.09 | -13.0% |
| bear | 272 | 21.6% | -0.34 | -20.2% |
| chop | 193 | 15.3% | -1.28 | -30.8% |

**Edge ONLY in bull: it depends on one market type.**
