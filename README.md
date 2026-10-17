# CoinDCX trade approval bot

Proposes BTC and XAU perpetual-futures trades on Telegram and places an order only
after a human taps Approve. The full spec and every decision behind it are in
[CLAUDE.md](CLAUDE.md).

## Status

- [x] **Phase 1: data + engine.** CoinDCX public client, parquet candle cache, backtest engine with fees, slippage, funding and TDS, metrics, and a leakage test.
- [x] **Phase 2: research tooling.** Trials table, deflated Sharpe (checked against the paper's worked example), walk-forward with warmup, regime split, gate checks. Baseline report: REJECTED (see `reports/`).
- [ ] Phase 3: paper trading with Telegram approvals
- [ ] Phase 4: live, minimum size

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env   # only needed from Phase 3
```

## Commands

```bash
.venv/bin/python -m pytest
.venv/bin/python -m scripts.fetch_history
.venv/bin/python -m scripts.run_backtest --instrument BTC --timeframe 1d
.venv/bin/python -m scripts.research_report --instrument BTC --timeframe 1d
```

Every strategy run is logged to `data/research.db` so the deflated Sharpe knows how
many things were tried. Don't delete that file: it's the honest trial count.

`fetch_history` is incremental: run it again any time to add new bars.
