# Research report: ma_crossover on B-BTC_USDT 4h

**Verdict: REJECTED**

| Gate | Result | Detail |
|---|---|---|
| 1. Critic review | PASS | see reports/critic/ma_crossover.md (code f2b68959e581) |
| 2. Deflated Sharpe | FAIL | DSR 0.614 vs required > 0.95 (N = 3 trials, T = 10391 bars) |
| 3. Walk-forward | PASS | 3/5 folds positive (need 60%); worst fold -1.7% (floor -15%) |
| 4. Regime split | PASS | Positive Sharpe in 2 regimes: bull, chop. (need positive Sharpe in >= 2) |
| 5. Leakage check | PASS | annualized Sharpe 0.21 |

Data: 10391 bars, 2022-01-19 to 2026-10-17 UTC. Params: `{'fast': 50, 'slow': 200, 'exposure': 1.0, 'atr_period': 14, 'atr_mult': 3.0, 'sizing': 'risk', 'risk_pct': 0.01, 'max_position_pct': 0.2}`.

## Full-sample backtest

Sized by risk, as live: each entry risks 1.0% of equity at its stop, notional capped at 20.0% of equity.

| Metric | Value |
|---|---|
| Sharpe (annualized) | 0.21 |
| Annual return | 1.3% |
| Max drawdown | -8.7% |
| Longest drawdown | 4412 bars (735 days 08:00:00) |
| Calmar | 0.15 |
| Stop-outs | 42 |
| Exposure when in a trade | median 20.0%, at the 20.0% cap on 68.7% of those bars |
| Gross / net return | 15.9% / 6.2% |
| Fees + slippage | 2.2% of starting capital |
| Funding | 6.6% of starting capital |
| TDS withheld (track mode) | 12.6% of starting capital |

> funding: CONSTANT 1.0 bps per 8h on |position|, charged long or short (no historical funding data available)

## Deflated Sharpe

- Per-period Sharpe: 0.0046
- Expected best-of-N by luck (SR0): 0.0017
- Distinct trials on B-BTC_USDT 4h: N = 3 (trials table holds 22 runs in total)
- Skew 0.01, raw kurtosis 14.70, T = 10391
- **DSR = 0.614**

## Walk-forward (out of sample)

Train 730 days, test 180 days, rolling, warmup = train window.

- Positive folds: **3/5**
- Worst fold: **#4 at -1.7%** (Sharpe -0.49)
- Stitched OOS: Sharpe 0.64, annual 4.7%, max DD -8.7%

| Fold | Test period | Return | Sharpe | Max DD |
|---|---|---|---|---|
| 1 | 2024-01-19 to 2024-07-17 | 5.5% | 1.25 | -4.6% |
| 2 | 2024-07-17 to 2025-01-13 | 6.3% | 1.50 | -6.1% |
| 3 | 2025-01-13 to 2025-07-12 | -0.7% | -0.15 | -3.8% |
| 4 | 2025-07-12 to 2026-01-08 | -1.7% | -0.49 | -4.2% |
| 5 | 2026-01-08 to 2026-07-07 | 2.2% | 0.73 | -3.9% |

## Regimes (out of sample)

| Regime | Bars | Share | Sharpe | Return |
|---|---|---|---|---|
| bull | 1537 | 28.5% | 2.03 | 12.8% |
| bear | 1135 | 21.0% | -0.49 | -2.5% |
| chop | 2728 | 50.5% | 0.26 | 1.8% |

**Positive Sharpe in 2 regimes: bull, chop.**
