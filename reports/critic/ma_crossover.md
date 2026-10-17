# Critic review: ma_crossover

Reviewed: `bot/strategies/baseline.py` plus the engine and data code it runs through,
at commit after 7470ad8 (Phase 2). Reviewer: Claude Code, 2026-10-17.

**Caveat: the same agent wrote this code and this review.** A self-review catches less
than an independent one, so read the quoted lines yourself before trusting the verdict.

PRESENT means the safeguard the question asks about is in the code; ABSENT means it isn't.

## 1. Look-ahead: is the signal shifted before becoming a position?

**PRESENT.** The engine shifts every signal, so a strategy can't skip it:

> `bot/research/backtest.py:63` `position = signal.fillna(0.0).shift(1, fill_value=0.0)`

`tests/test_backtest.py` proves it: a same-bar-return signal scores Sharpe ≈ 0 through
the engine and ≈ 25 with the shift undone.

## 2. Survivorship: is the instrument list point-in-time?

**ABSENT.** Instruments come from today's active list:

> `scripts/fetch_history.py:20` `active = set(client.active_instruments())`

Impact here is low: the strategy trades two instruments picked in advance (BTC, XAU),
not a universe filtered by who survived. It would matter for any future strategy that
selects among many pairs, and that strategy would need a point-in-time list.

## 3. Repainting: does any indicator use future data?

**PRESENT** (no repainting). Moving averages are trailing:

> `bot/strategies/baseline.py:23` `fast = df["close"].rolling(params["fast"]).mean()`

The only resample (4h from 1h) drops any bin that hasn't fully closed:

> `bot/data/store.py:66` `return out[(out.index >= df.index[0]) & (out.index + size <= data_ends)]`

The client drops the still-forming bar from API responses (`coindcx.py`,
`return df[df.index + bar <= now]`). `test_baseline_signal_uses_only_past_data` checks
that changing future prices leaves earlier signals unchanged.

## 4. Costs: are fees, slippage, funding AND TDS applied?

**PRESENT**, with one weak spot.

> `bot/research/backtest.py:70` `trading_cost = turnover * (costs.fee_bps + costs.slippage_bps) / 1e4`
> `bot/research/backtest.py:74` `funding_cost = position.abs() * costs.funding_bps_per_interval / 1e4 * intervals_per_bar`
> `bot/research/backtest.py:78` `tds = sold * tds_bps / 1e4`

Funding is a **constant** 1 bp per 8h, charged long or short, because CoinDCX
publishes no funding history. It is the largest cost in the report (32% of starting
capital vs 1% for fees and slippage), so this one assumption moves results the most.

## 5. Fill assumption: does it assume a fill at a price that was never available?

**PRESENT** (fills are realistic). A position decided at bar t's close earns from that
close onward, i.e. it assumes a fill at close t. CoinDCX futures trade 24/7, and in the
cached BTC data the next bar's open matches the previous close: median gap 0 bps, 95th
percentile 0.2 bps (1d and 1h). Slippage of 3 bps per unit of turnover is charged on
top. The rare large gaps (up to 113 bps on 1h) sit next to the 6 missing hourly bars.

## 6. Parameter fitting: how many parameters, and were they chosen on the full dataset?

**PRESENT** (not fitted on this data). Three parameters, all fixed textbook defaults:

> `bot/strategies/baseline.py:15` `def __init__(self, fast: int = 50, slow: int = 200, exposure: float = 1.0):`
> `bot/strategies/baseline.py:19` `return dict(self.defaults)`

`fit()` ignores the data. Caveat: 50/200 is popular because it looked good on past
data elsewhere, so it isn't completely free of selection.

## 7. Sample: does the test period include both a bull and a bear regime?

**PRESENT for BTC 1d.** The out-of-sample period (2023-01-01 to 2026-06-13) has
795 bull, 272 bear and 193 chop bars (see the report's regime table).

**ABSENT for XAU**: 9 months of history (from 2026-01-09) isn't enough for a
200-day MA, let alone walk-forward. XAU strategies can't be validated yet.

## 8. Data alignment: are all series in UTC with the same bar-close convention?

**PRESENT.** One source, one convention: index = bar open time in UTC.

> `bot/data/coindcx.py:102` `df.index = pd.to_datetime(df.pop("time"), unit="ms", utc=True)`

Resampled 4h bars keep the same open-time labels (`closed="left", label="left"`).

## Summary

The code has no look-ahead, repainting, fill or alignment problems that this review
could find. Item 2 doesn't apply to a fixed two-instrument strategy. Item 7 blocks XAU.
The constant funding assumption (item 4) is the biggest source of uncertainty.

This verdict is about the code being honest, not about the strategy being good. The
strategy still has to pass gates 2 to 5.

Verdict: PASS
