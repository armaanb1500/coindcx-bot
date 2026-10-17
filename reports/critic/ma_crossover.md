# Critic review: ma_crossover

Reviewed: `bot/strategies/baseline.py` (MA crossover with an ATR stop), plus the engine,
sizing and data code it runs through. Reviewer: Claude Code, 2026-10-18. Supersedes the
earlier 2026-10-18 review, which predates risk-based sizing in the engine.

Code hash: f2b68959e581

(Hash of `baseline.py`, `backtest.py`, `sizing.py`, `coindcx.py` and `store.py`. If any
of them change, gate 1 reports this review as STALE until it is redone.)

What changed since the last review: the reports, walk-forward and the paper health
check now run the engine with a `RiskRule`, the same rule live sizing uses. Each entry
is sized so that hitting its stop loses `risk_pct_per_trade` (1%) of equity, capped at
`max_position_pct` (20%) notional. The signal's sign picks the side; its size is ignored.

**Caveat: the same agent wrote this code and this review.** A self-review catches less
than an independent one, so read the quoted lines yourself before trusting the verdict.

PRESENT means the safeguard the question asks about is in the code; ABSENT means it isn't.

## 1. Look-ahead: is the signal shifted before becoming a position?

**PRESENT.** The engine applies the shift itself, inside its bar loop:

> `bot/research/backtest.py:153` `want = want_by_bar[t - 1]  # decided at the previous close: act on the next bar`

The stop for a position opened at bar t-1's close uses `dist[t - 1]`, which is computed
from data up to that close. The position size uses the same two inputs, both known at
that close:

> `bot/research/backtest.py:167` `size = risk_rule.fraction(c[t - 1], dist[t - 1]) if opening else abs(held)`
 `tests/test_backtest.py` proves the shift: a same-bar-return
signal scores Sharpe ≈ 0 through the engine and ≈ 25 with the shift undone.

## 2. Survivorship: is the instrument list point-in-time?

**ABSENT.** Instruments come from today's active list:

> `scripts/fetch_history.py:20` `active = set(client.active_instruments())`

Impact is low: the strategy trades two instruments picked in advance (BTC, XAU), not a
universe filtered by who survived. A future strategy that selects among many pairs
would need a point-in-time list.

## 3. Repainting: does any indicator use future data?

**PRESENT** (no repainting). Moving averages are trailing:

> `bot/strategies/baseline.py:29` `fast = df["close"].rolling(params["fast"]).mean()`

ATR is a trailing exponential average:

> `bot/strategies/baseline.py:43` `return true_range.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()`

The 4h resample drops any bin that hasn't fully closed:

> `bot/data/store.py:66` `return out[(out.index >= df.index[0]) & (out.index + size <= data_ends)]`

and the client drops the still-forming bar (`coindcx.py:96` `return df[df.index + bar <= now]`).
Tests check that changing future prices leaves earlier signals and stop distances unchanged.

## 4. Costs: are fees, slippage, funding AND TDS applied?

**PRESENT**, with one weak spot.

> `bot/research/backtest.py:108` `trading_cost = turnover * (costs.fee_bps + costs.slippage_bps) / 1e4`
> `bot/research/backtest.py:112` `funding_cost = position.abs() * costs.funding_bps_per_interval / 1e4 * intervals_per_bar`
> `bot/research/backtest.py:115` `sold = (-entry_change).clip(lower=0.0) + (-exit_change).clip(lower=0.0)`

Stop exits count as turnover and, for longs, as TDS sell legs. Funding is a **constant**
1 bp per interval, charged long or short, because CoinDCX publishes no funding history.
It is still the largest single cost. All four scale with the risk-sized position, as
they would live.

## 5. Fill assumption: does it assume a fill at a price that was never available?

**PRESENT** (fills are realistic), with a caveat about stops.

Entries fill at the signal bar's close. In the cached BTC data the next bar's open
matches the previous close (1h: median gap 0 bps, 99th percentile 0.24 bps), so that
price really was available.

Stops exit at the stop price, or at the open when the bar gapped through it:

> `bot/research/backtest.py:179` `exit_price, hit = min(o[t], stop), True  # gap down through the stop fills at the open`
> `bot/research/backtest.py:181` `exit_price, hit = max(o[t], stop), True`

Caveat: a real stop-market order in a fast move can fill a little worse than its
trigger. The engine charges the same 3 bps slippage as any other trade, which may be
optimistic for stops in volatile bars.

Sizing matches live, with three known differences, none of them a fill the market
couldn't give. The engine and live share one formula:

> `bot/live/sizing.py:38` `return min(self.for_risk(entry, stop_distance), self.max_position_pct)`
> `bot/live/sizing.py:80` `qty = _floor_to_step(rule.fraction(entry, per_unit_loss) * capital_usdt / entry,`

(1) Live rounds quantity down to the exchange step and refuses sizes below the minimum;
the engine doesn't round, so it can hold slightly more than live would. (2) Live sizes
against `capital_inr`, which the owner sets; the engine sizes against current equity,
so it compounds. (3) The engine holds a constant fraction of equity while in a trade,
while live holds a fixed quantity. Tests in `tests/test_risk_sizing.py` check that the
engine's entry exposure equals live's notional / capital to within one quantity step.

## 6. Parameter fitting: how many parameters, and were they chosen on the full dataset?

**PRESENT** (not fitted on this data). Five parameters, all fixed textbook defaults:

> `bot/strategies/baseline.py:19` `def __init__(self, fast: int = 50, slow: int = 200, exposure: float = 1.0,`
> `bot/strategies/baseline.py:20` `atr_period: int = 14, atr_mult: float = 3.0):`
> `bot/strategies/baseline.py:25` `return dict(self.defaults)`

`fit()` ignores the data. Caveat: 50/200 and ATR(14)×3 are popular because they looked
good on past data elsewhere, so they aren't completely free of selection. Adding the stop
created a new trial; the trials table counts both versions.

Under risk sizing, `exposure` no longer does anything (only the signal's sign is used),
and two config values join in: `risk_pct_per_trade` 0.01 and `max_position_pct` 0.20.
Both are the live risk limits from the spec, not chosen on this data. The research
report records them in the trial's params, so the risk-sized runs count as new trials.

## 7. Sample: does the test period include both a bull and a bear regime?

**PRESENT for BTC** (1d, 4h and 1h). The out-of-sample periods contain bull, bear and
chop bars (see each report's regime table).

**ABSENT for XAU**: 9 months of history (from 2026-01-09) is shorter than one 2-year
training window. XAU strategies can't be validated yet.

## 8. Data alignment: are all series in UTC with the same bar-close convention?

**PRESENT.** One source, one convention: index = bar open time in UTC.

> `bot/data/coindcx.py:125` `df.index = pd.to_datetime(df.pop("time"), unit="ms", utc=True)`

Resampled 4h bars keep the same open-time labels (`closed="left", label="left"`), and
stop checks use the same bar's open/high/low as its close.

## Summary

The review found no look-ahead, repainting, alignment or unrealistic entry fills. Item 2
doesn't apply to a fixed two-instrument strategy. Item 7 blocks XAU. The two biggest
uncertainties are constant funding (item 4) and stop slippage in fast markets (item 5).
Risk sizing uses only data known at the entry bar's close and the same formula as live.

This verdict is about the code being honest, not the strategy being good. The strategy
still has to pass gates 2 to 5, and it doesn't.

Verdict: PASS
