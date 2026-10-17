# CLAUDE.md — CoinDCX Trade Approval Bot

Read this whole file before writing any code. It records decisions already made. Don't revisit them unless I ask.

## What this project is

A bot for BTC and XAU perpetual futures on CoinDCX (India). It pulls market data, computes signals from strategies that have passed validation, and proposes trades to me on Telegram. It places an order **only after I tap Approve**. It never trades on its own.

This is two systems, and they get built in this order:

1. **Research stack**: data, backtest engine, metrics, deflated Sharpe, walk-forward. This decides whether a strategy is allowed to exist.
2. **Live stack**: signal, risk and sizing, Telegram approval, execution, monitoring. This only ever runs strategies that passed the research stack.

The guiding idea: generating ideas is cheap, and validating them is the actual work. When in doubt, reject the strategy.

## Decisions already made (do not change without asking)

- **No chart images.** "Scanning charts" means fetching OHLCV candles from the CoinDCX API and computing signals in code. No screenshots and no vision models. If something can't be backtested, it can't be traded.
- **Act on the next bar.** Every signal is `shift(1)`-ed before it becomes a position. The signal at bar t may only use data available at the close of bar t.
- **The human approves every live order.** No auto-execution mode exists, and none should be added.
- **The API key never has withdrawal permission.** Trade and read only. Bind it to the server IP if CoinDCX offers that.
- **Hard risk limits live in code and config, not in my judgment.** The bot refuses to propose a trade that breaks a limit, even if I would approve it.
- **Build order is fixed: backtest → paper → live.** Live mode is built last and is gated (see Modes).

## Stack

- Python 3.11+, managed with `uv` (or a venv if uv isn't available)
- pandas, numpy, scipy for research
- httpx for REST calls; a hand-written thin CoinDCX client
  - An unofficial `coindcx` package exists on PyPI. Use it only as a reference, not as a dependency, because I want to see exactly what gets signed and sent.
- python-telegram-bot for approvals
- pydantic-settings for config, `.env` for secrets
- SQLite for the trade and proposal log; parquet for candle cache
- pytest

## Repo layout (target)

```
bot/
  config.py          # pydantic settings, all limits and costs live here
  data/
    coindcx.py       # thin REST client: public candles + signed private calls
    store.py         # parquet candle cache, incremental updates
  research/
    backtest.py      # vectorized engine
    metrics.py
    deflated.py      # deflated Sharpe ratio
    walkforward.py
    regimes.py       # bull/bear/chop split by 200-period MA
  strategies/
    base.py          # Strategy interface: fit(train) -> params, signal(df, params) -> Series
    baseline.py      # a simple baseline used to prove the pipeline end to end
  live/
    sizing.py
    risk.py          # hard limits, daily loss, kill switch
    proposer.py      # turns a signal into a proposal
    telegram_bot.py  # approval UI
    executor.py      # places orders after approval
    health.py        # daily decay check
  log/
    db.py            # SQLite: proposals, decisions, orders, fills
tests/
scripts/
  fetch_history.py
  run_backtest.py
  run_walkforward.py
.env.example
```

## CoinDCX API notes

- Official docs are at https://docs.coindcx.com/ and the REST base URL is `https://api.coindcx.com`. **Treat the official docs as the source of truth.** Verify every endpoint path, parameter and response shape there before coding against it, and don't trust endpoint names from memory or from third-party wrappers.
- Private endpoints need an API key plus an HMAC-SHA256 signature of the JSON body, sent in headers. Write one `_signed_post()` helper and unit-test the signing against the docs' example.
- Futures instruments: discover the exact BTC and XAU instrument names from the active-instruments endpoint. Don't hardcode guesses.
- Handle rate limits with backoff. Log every private request and response, with secrets redacted.
- **Market data first.** Phase 1 only needs public candle endpoints. Don't touch order endpoints until Phase 3.

### Confirmed against docs and the live API (2026-10-17)

- Active instruments: `GET https://api.coindcx.com/exchange/v1/derivatives/futures/data/active_instruments?margin_currency_short_name[]=USDT` returns a list of pair names.
- Instrument details: `GET .../derivatives/futures/data/instrument?pair={pair}&margin_currency_short_name=USDT` returns `{"instrument": {...}}` with `maker_fee`, `taker_fee`, `funding_frequency` (hours), `min_quantity`, `min_notional`, and more.
- Instruments: **BTC = `B-BTC_USDT`**, **XAU = `B-XAU_USDT`**. (`B-PAXG_USDT` also exists; it is a gold token, not XAU.)
- Candles: `GET https://public.coindcx.com/market_data/candlesticks?pair=&from=&to=&resolution=&pcode=f`. `from`/`to` are epoch **seconds**; `time` in the response is the bar **open** time in **milliseconds**; rows come back oldest first.
  - Resolutions: `1`, `5`, `60`, `1D` only. **There is no 4H**, so 4H bars are resampled from 1H inside `store.py`.
  - At most 30,000 rows per request (seen live), so the client pages.
  - The newest row is the bar still forming. The client drops any bar whose close time is after "now".
- History start: BTC 1D from 2021-01-01, BTC 1H from 2022-01-19, **XAU only from 2026-01-09**.
- Live fees on 2026-10-17 (percent, which looks like it includes 18% GST): BTC maker 0.0236 / taker 0.059; XAU maker 0.0118 / taker 0.0118. Funding every 8h for BTC, every 4h for XAU.
- **No public funding-rate history endpoint is documented**, so the backtest uses a constant pessimistic funding cost and labels it in the output.
- The futures section of the docs lists no rate limits, so the client backs off on 429 and 5xx responses.
- Python: `uv` isn't installed, so the project uses `.venv` (Python 3.14). Run things with `.venv/bin/python -m ...`.

## Costs the backtest must model

The article this project started from only modelled fees and slippage. For perpetual futures in India, that's not enough.

| Cost | How to model it | Config key |
|---|---|---|
| Exchange fee | bps on turnover | `fee_bps` (check CoinDCX's current futures fee schedule) |
| Slippage | bps on turnover | `slippage_bps` (default 3; raise for XAU if its book is thin) |
| **Funding rate** | Perps pay or receive funding every funding interval while a position is held. Use historical funding rates if the API provides them; otherwise use a conservative constant and flag it in the output. | `funding_mode`, `funding_bps_per_interval` |
| **1% TDS** | Section 194S TDS is withheld on the transfer value, whether or not the trade profited. It can be claimed back at filing, so treat it as a **liquidity drag**: track withheld TDS separately and report it. Also provide a pessimistic mode that subtracts it as a cost. Make the rate configurable. | `tds_bps` (default 100), `tds_mode: "track" \| "cost"` |

Tax on the profits themselves is unsettled for crypto futures (possibly speculative business income, possibly the 30% VDA regime). Don't model it in the engine. Just report gross and net P&L and the TDS withheld, so I can work it out with a CA.

## Known bugs in the source article's code: fix these, don't copy them

1. **`deflated_sharpe` is wrong as written.** It plugs an *annualized* Sharpe into a formula that expects *per-period* Sharpe, and it never scales the expected maximum by the spread of Sharpes across trials. Implement Bailey & López de Prado properly:

   ```
   SR_hat  = per-period (non-annualized) Sharpe of the best strategy
   V       = variance of per-period Sharpe across ALL N trials
   SR0     = sqrt(V) * ((1 - γ) * Φ⁻¹(1 - 1/N) + γ * Φ⁻¹(1 - 1/(N·e)))     # γ = Euler–Mascheroni
   DSR     = Φ( (SR_hat - SR0) * sqrt(T - 1) / sqrt(1 - skew·SR_hat + ((kurt - 1)/4)·SR_hat²) )
   ```
   Here kurt is the raw (non-excess) kurtosis of the best strategy's returns, and T is the number of return observations. The function therefore needs the per-trial Sharpes (or their variance) as input, not just N. Every trial must be recorded, so the research scripts log every run to a trials table automatically.

2. **`periods_per_year` must match the bar size.** Daily bars use 365, 4H bars use 2190, 1H bars use 8760. Derive it from the timeframe, never hardcode it.

3. **Walk-forward throws away indicator warmup.** `signal_fn(test)` computes indicators on the test slice alone, so the first bars of every fold are garbage. Pass the tail of the train window as warmup, compute the signal over warmup plus test, then keep only the test bars.

4. **Log returns times position is only an approximation**, and it gets worse with leverage and for shorts. Use simple returns for P&L (`position * pct_change`), and compound equity with `cumprod(1 + net)`.

## Validation gates (a strategy must pass ALL before paper trading)

1. **Critic review**: the 8-point checklist below, every item answered PRESENT or ABSENT with the quoted line. Nothing should be summarized.
2. **Deflated Sharpe > 0.95** using the honest trial count.
3. **Walk-forward**: judged on `positive_folds` and `worst_fold`, not the average.
4. **Regime split**: metrics reported separately for bull, bear and chop. If the edge only exists in one regime, say so plainly.
5. Any Sharpe above 2 on daily data is treated as leakage until proven otherwise.

Critic checklist (run it against every strategy's code):
1. Look-ahead: is the signal shifted before becoming a position?
2. Survivorship: is the instrument list point-in-time?
3. Repainting: does any indicator use future data (centered MAs, zigzag, unshifted resample)?
4. Costs: are fees, slippage, funding AND TDS applied?
5. Fill assumption: does it assume a fill at a price that was never available?
6. Parameter fitting: how many parameters, and were they chosen on the full dataset?
7. Sample: does the test period include both a bull and a bear regime?
8. Data alignment: are all series in UTC with the same bar-close convention?

## Risk limits (defaults, all in config)

- `risk_pct_per_trade`: 0.01. Sizing comes from entry and stop distance, as in the article's `position_size`.
- `max_position_pct`: 0.20 of capital (notional, before leverage)
- `max_leverage`: 3. Hard cap; anything above it is refused, never clipped silently.
- `max_open_positions`: 2
- `max_daily_loss_pct`: 0.03. Hitting it halts proposals until the next UTC day.
- **Every order is placed together with its stop.** No naked positions.
- **Kill switch**: a `/halt` Telegram command and a `HALT` file in the repo root. Either one stops all new proposals immediately.
- **Health check**: runs daily. It halts if the 30-day live Sharpe falls below half the backtest Sharpe, or if drawdown exceeds 1.5× the backtest max drawdown.

## Telegram approval flow

- **Telegram is the only approval channel.** Claude Code builds and tests the bot but never places orders, approves proposals, or runs anything that sends a live order. Only my tap on Approve does that.
- Accept messages and callbacks **only from my chat ID** (set in `.env`). Ignore everything else silently.
- A proposal card shows the instrument, direction, entry, stop, take-profit if any, size and notional, leverage, loss if the stop hits (₹ and % of capital), the strategy name, and the signal time.
- It has two inline buttons: **Approve** and **Reject**.
- **Expiry**: proposals expire after `proposal_ttl_minutes` (default 5). An expired proposal can't be approved.
- **Price drift check**: on approval, re-fetch the price. If it has moved more than `max_drift_bps` from the proposed entry, cancel and tell me rather than executing.
- **Idempotency**: each proposal gets a client order ID, so a double tap or a retry can never place two orders.
- Every proposal, decision, order and fill is written to SQLite.

## Modes

`MODE=backtest | paper | live`

- `paper`: the full flow runs, including real Telegram approvals, but the executor logs the order it *would* have placed and simulates the fill. It never calls the order endpoint.
- `live`: requires `MODE=live` **and** `I_UNDERSTAND_LIVE_TRADING=yes` in `.env`. Without both, the bot refuses to start. Live mode starts at the minimum position size.

## Secrets and safety

- `.env` is gitignored from the first commit. Commit `.env.example` with placeholder values.
- Never print, log or commit API keys, secrets or the Telegram token.
- Don't add any code path that calls a withdrawal or transfer endpoint.

## Phases and exit criteria

**Phase 1: data + engine** (start here)
- Scaffold the repo, config, `.env.example` and `.gitignore`.
- CoinDCX public client: list futures instruments; fetch historical candles for BTC and XAU on 1H/4H/1D; cache to parquet with incremental updates.
- Vectorized backtest engine with every cost above, plus metrics (Sharpe, annual return, max drawdown, longest drawdown, Calmar, n_obs).
- Tests, including a **leakage test**: a signal equal to the sign of the *same bar's* return must show no meaningful edge after `shift(1)`. A version without the shift must show an absurd edge, which proves the test can catch leakage.
- Exit: `scripts/run_backtest.py` runs a baseline strategy on real cached BTC data, and all tests pass.

**Phase 2: research tooling**
- Trials table, the corrected deflated Sharpe, walk-forward with warmup, regime split.
- Exit: a full research report for the baseline strategy, which is expected to be rejected. That's fine.

**Phase 3: paper trading**
- Signed client (balances and positions, read only), sizing, risk, Telegram bot, executor in paper mode, SQLite log, health check.
- Exit: two weeks of paper proposals with no bugs in sizing, expiry, drift or idempotency.

**Phase 4: live, minimum size**
- Only for a strategy that passed every gate. Order endpoints with stop attached. Start at minimum size.

## Working agreements for Claude Code

- Write tests alongside the code, not after. Run them before saying a step is done.
- When an API detail isn't confirmed in the official docs, stop and ask instead of guessing.
- Keep strategies out of the engine. The engine must not know about any specific strategy.
- If something you're asked to build would weaken a decision above, say so before building it.

## First task

Do Phase 1. Begin by scaffolding the repo and the public CoinDCX client, and confirm the BTC and XAU futures instrument names from the live API before going further.
