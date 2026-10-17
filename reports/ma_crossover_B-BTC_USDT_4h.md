# Research report: ma_crossover on B-BTC_USDT 4h

**Verdict: REJECTED**

| Gate | Result | Detail |
|---|---|---|
| 1. Critic review | PASS | see reports/critic/ma_crossover.md (code 51ef75899427) |
| 2. Deflated Sharpe | FAIL | DSR 0.567 vs required > 0.95 (N = 2 trials, T = 10391 bars) |
| 3. Walk-forward | PASS | 3/5 folds positive (need 60%); worst fold -10.1% (floor -15%) |
| 4. Regime split | PASS | Positive Sharpe in 2 regimes: bull, chop. (need positive Sharpe in >= 2) |
| 5. Leakage check | PASS | annualized Sharpe 0.11 |

Data: 10391 bars, 2022-01-19 to 2026-10-17 UTC. Params: `{'fast': 50, 'slow': 200, 'exposure': 1.0, 'atr_period': 14, 'atr_mult': 3.0}`.

## Full-sample backtest

| Metric | Value |
|---|---|
| Sharpe (annualized) | 0.11 |
| Annual return | -3.1% |
| Max drawdown | -48.7% |
| Longest drawdown | 10183 bars (1697 days 04:00:00) |
| Calmar | -0.06 |
| Stop-outs | 42 |
| Gross / net return | 37.5% / -14.0% |
| Fees + slippage | 9.2% of starting capital |
| Funding | 27.0% of starting capital |
| TDS withheld (track mode) | 52.8% of starting capital |

> funding: CONSTANT 1.0 bps per 8h on |position|, charged long or short (no historical funding data available)

## Deflated Sharpe

- Per-period Sharpe: 0.0023
- Expected best-of-N by luck (SR0): 0.0007
- Distinct trials on B-BTC_USDT 4h: N = 2 (trials table holds 16 runs in total)
- Skew -0.17, raw kurtosis 15.18, T = 10391
- **DSR = 0.567**

## Walk-forward (out of sample)

Train 730 days, test 180 days, rolling, warmup = train window.

- Positive folds: **3/5**
- Worst fold: **#4 at -10.1%** (Sharpe -0.49)
- Stitched OOS: Sharpe 0.53, annual 14.1%, max DD -45.2%

| Fold | Test period | Return | Sharpe | Max DD |
|---|---|---|---|---|
| 1 | 2024-01-19 to 2024-07-17 | 20.3% | 1.05 | -26.2% |
| 2 | 2024-07-17 to 2025-01-13 | 24.8% | 1.22 | -32.7% |
| 3 | 2025-01-13 to 2025-07-12 | -6.3% | -0.14 | -18.3% |
| 4 | 2025-07-12 to 2026-01-08 | -10.1% | -0.49 | -19.9% |
| 5 | 2026-01-08 to 2026-07-07 | 9.4% | 0.73 | -18.2% |

## Regimes (out of sample)

| Regime | Bars | Share | Sharpe | Return |
|---|---|---|---|---|
| bull | 1537 | 28.5% | 2.04 | 74.4% |
| bear | 1135 | 21.0% | -0.77 | -22.1% |
| chop | 2728 | 50.5% | 0.21 | 2.0% |

**Positive Sharpe in 2 regimes: bull, chop.**
