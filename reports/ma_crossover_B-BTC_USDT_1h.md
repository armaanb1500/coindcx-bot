# Research report: ma_crossover on B-BTC_USDT 1h

**Verdict: REJECTED**

| Gate | Result | Detail |
|---|---|---|
| 1. Critic review | PASS | see reports/critic/ma_crossover.md (code f2b68959e581) |
| 2. Deflated Sharpe | FAIL | DSR 0.538 vs required > 0.95 (N = 2 trials, T = 41561 bars) |
| 3. Walk-forward | FAIL | 2/5 folds positive (need 60%); worst fold -4.1% (floor -15%) |
| 4. Regime split | FAIL | Edge ONLY in bull: it depends on one market type. (need positive Sharpe in >= 2) |
| 5. Leakage check | PASS | annualized Sharpe 0.04 |

Data: 41561 bars, 2022-01-19 to 2026-10-17 UTC. Params: `{'fast': 50, 'slow': 200, 'exposure': 1.0, 'atr_period': 14, 'atr_mult': 3.0, 'sizing': 'risk', 'risk_pct': 0.01, 'max_position_pct': 0.2}`.

## Full-sample backtest

Sized by risk, as live: each entry risks 1.0% of equity at its stop, notional capped at 20.0% of equity.

| Metric | Value |
|---|---|
| Sharpe (annualized) | 0.04 |
| Annual return | 0.0% |
| Max drawdown | -14.8% |
| Longest drawdown | 19276 bars (803 days 04:00:00) |
| Calmar | 0.00 |
| Stop-outs | 174 |
| Exposure when in a trade | median 20.0%, at the 20.0% cap on 99.5% of those bars |
| Gross / net return | 18.8% / 0.1% |
| Fees + slippage | 10.2% of starting capital |
| Funding | 6.9% of starting capital |
| TDS withheld (track mode) | 57.3% of starting capital |

> funding: CONSTANT 1.0 bps per 8h on |position|, charged long or short (no historical funding data available)

## Deflated Sharpe

- Per-period Sharpe: 0.0005
- Expected best-of-N by luck (SR0): 0.0000
- Distinct trials on B-BTC_USDT 1h: N = 2 (trials table holds 24 runs in total)
- Skew 0.06, raw kurtosis 23.72, T = 41561
- **DSR = 0.538**

## Walk-forward (out of sample)

Train 730 days, test 180 days, rolling, warmup = train window.

- Positive folds: **2/5**
- Worst fold: **#2 at -4.1%** (Sharpe -0.97)
- Stitched OOS: Sharpe 0.03, annual -0.1%, max DD -14.8%

| Fold | Test period | Return | Sharpe | Max DD |
|---|---|---|---|---|
| 1 | 2024-01-20 to 2024-07-17 | 8.0% | 1.71 | -3.7% |
| 2 | 2024-07-18 to 2025-01-14 | -4.1% | -0.97 | -8.5% |
| 3 | 2025-01-14 to 2025-07-13 | -2.7% | -0.63 | -7.4% |
| 4 | 2025-07-13 to 2026-01-09 | -3.6% | -1.11 | -5.3% |
| 5 | 2026-01-09 to 2026-07-08 | 2.7% | 0.72 | -6.9% |

## Regimes (out of sample)

| Regime | Bars | Share | Sharpe | Return |
|---|---|---|---|---|
| bull | 2328 | 10.8% | 2.87 | 7.0% |
| bear | 1671 | 7.7% | -1.91 | -5.6% |
| chop | 17601 | 81.5% | -0.04 | -1.1% |

**Edge ONLY in bull: it depends on one market type.**
