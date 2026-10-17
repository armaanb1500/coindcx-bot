# Research report: ma_crossover on B-BTC_USDT 4h

**Verdict: REJECTED**

| Gate | Result | Detail |
|---|---|---|
| 1. Critic review | PASS | see reports/critic/ma_crossover.md |
| 2. Deflated Sharpe | FAIL | DSR 0.520 vs required > 0.95 (N = 1 trials, T = 10389 bars) |
| 3. Walk-forward | FAIL | 3/5 folds positive (need 60%); worst fold -36.8% (floor -15%) |
| 4. Regime split | FAIL | Edge ONLY in bull: it depends on one market type. (need positive Sharpe in >= 2) |
| 5. Leakage check | PASS | annualized Sharpe 0.02 |

Data: 10389 bars, 2022-01-19 to 2026-10-17 UTC. Params: `{'fast': 50, 'slow': 200, 'exposure': 1.0}`.

## Full-sample backtest

| Metric | Value |
|---|---|
| Sharpe (annualized) | 0.02 |
| Annual return | -9.9% |
| Max drawdown | -60.1% |
| Longest drawdown | 5685 bars (947 days 12:00:00) |
| Calmar | -0.17 |
| Gross / net return | 14.3% / -39.1% |
| Fees + slippage | 8.9% of starting capital |
| Funding | 38.1% of starting capital |
| TDS withheld (track mode) | 50.6% of starting capital |

> funding: CONSTANT 1.0 bps per 8h on |position|, charged long or short (no historical funding data available)

## Deflated Sharpe

- Per-period Sharpe: 0.0005
- Expected best-of-N by luck (SR0): 0.0000
- Distinct trials on B-BTC_USDT 4h: N = 1 (trials table holds 6 runs in total)
- Skew -0.05, raw kurtosis 10.79, T = 10389
- **DSR = 0.520**

## Walk-forward (out of sample)

Train 730 days, test 180 days, rolling, warmup = train window.

- Positive folds: **3/5**
- Worst fold: **#4 at -36.8%** (Sharpe -2.21)
- Stitched OOS: Sharpe 0.16, annual -3.7%, max DD -60.1%

| Fold | Test period | Return | Sharpe | Max DD |
|---|---|---|---|---|
| 1 | 2024-01-19 to 2024-07-17 | 12.8% | 0.73 | -32.4% |
| 2 | 2024-07-17 to 2025-01-13 | 4.4% | 0.43 | -43.7% |
| 3 | 2025-01-13 to 2025-07-12 | -1.6% | 0.18 | -21.6% |
| 4 | 2025-07-12 to 2026-01-08 | -36.8% | -2.21 | -45.8% |
| 5 | 2026-01-08 to 2026-07-07 | 24.3% | 1.20 | -23.7% |

## Regimes (out of sample)

| Regime | Bars | Share | Sharpe | Return |
|---|---|---|---|---|
| bull | 1537 | 28.5% | 1.67 | 58.3% |
| bear | 1135 | 21.0% | -1.06 | -35.1% |
| chop | 2728 | 50.5% | -0.03 | -11.5% |

**Edge ONLY in bull: it depends on one market type.**
