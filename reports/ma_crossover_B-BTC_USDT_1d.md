# Research report: ma_crossover on B-BTC_USDT 1d

**Verdict: REJECTED**

| Gate | Result | Detail |
|---|---|---|
| 1. Critic review | PASS | see reports/critic/ma_crossover.md (code f2b68959e581) |
| 2. Deflated Sharpe | FAIL | DSR 0.482 vs required > 0.95 (N = 3 trials, T = 2115 bars) |
| 3. Walk-forward | PASS | 5/7 folds positive (need 60%); worst fold -4.5% (floor -15%) |
| 4. Regime split | FAIL | Edge ONLY in bull: it depends on one market type. (need positive Sharpe in >= 2) |
| 5. Leakage check | PASS | annualized Sharpe 0.10 |

Data: 2115 bars, 2021-01-01 to 2026-10-16 UTC. Params: `{'fast': 50, 'slow': 200, 'exposure': 1.0, 'atr_period': 14, 'atr_mult': 3.0, 'sizing': 'risk', 'risk_pct': 0.01, 'max_position_pct': 0.2}`.

## Full-sample backtest

Sized by risk, as live: each entry risks 1.0% of equity at its stop, notional capped at 20.0% of equity.

| Metric | Value |
|---|---|
| Sharpe (annualized) | 0.10 |
| Annual return | 0.3% |
| Max drawdown | -5.8% |
| Longest drawdown | 668 bars (668 days 00:00:00) |
| Calmar | 0.05 |
| Stop-outs | 6 |
| Exposure when in a trade | median 7.6%, at the 20.0% cap on 0.0% of those bars |
| Gross / net return | 5.4% / 1.8% |
| Fees + slippage | 0.2% of starting capital |
| Funding | 3.4% of starting capital |
| TDS withheld (track mode) | 0.9% of starting capital |

> funding: CONSTANT 1.0 bps per 8h on |position|, charged long or short (no historical funding data available)

## Deflated Sharpe

- Per-period Sharpe: 0.0054
- Expected best-of-N by luck (SR0): 0.0064
- Distinct trials on B-BTC_USDT 1d: N = 3 (trials table holds 20 runs in total)
- Skew 0.57, raw kurtosis 10.77, T = 2115
- **DSR = 0.482**

## Walk-forward (out of sample)

Train 730 days, test 180 days, rolling, warmup = train window.

- Positive folds: **5/7**
- Worst fold: **#5 at -4.5%** (Sharpe -1.93)
- Stitched OOS: Sharpe 0.21, annual 0.7%, max DD -5.8%

| Fold | Test period | Return | Sharpe | Max DD |
|---|---|---|---|---|
| 1 | 2023-01-01 to 2023-06-29 | -2.1% | -1.81 | -2.1% |
| 2 | 2023-06-30 to 2023-12-26 | 0.9% | 0.72 | -1.1% |
| 3 | 2023-12-27 to 2024-06-23 | 4.0% | 1.54 | -2.1% |
| 4 | 2024-06-24 to 2024-12-20 | 2.5% | 1.03 | -2.5% |
| 5 | 2024-12-21 to 2025-06-18 | -4.5% | -1.93 | -5.4% |
| 6 | 2025-06-19 to 2025-12-15 | 0.5% | 0.79 | -0.8% |
| 7 | 2025-12-16 to 2026-06-13 | 1.3% | 0.75 | -2.5% |

## Regimes (out of sample)

| Regime | Bars | Share | Sharpe | Return |
|---|---|---|---|---|
| bull | 795 | 63.1% | 0.40 | 3.2% |
| bear | 272 | 21.6% | -0.10 | -0.4% |
| chop | 193 | 15.3% | -0.17 | -0.4% |

**Edge ONLY in bull: it depends on one market type.**
