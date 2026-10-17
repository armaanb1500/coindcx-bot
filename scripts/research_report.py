"""Full research report for a strategy: backtest, deflated Sharpe, walk-forward,
regimes and every gate. Logs its runs to the trials table automatically.

    .venv/bin/python -m scripts.research_report --instrument BTC --timeframe 1d

Writes reports/<strategy>_<pair>_<timeframe>.md and prints the same text.
"""

import argparse
import inspect
from pathlib import Path

import pandas as pd

from bot.config import Settings
from bot.data.store import CandleStore
from bot.research import backtest, gates, metrics, regimes, trials
from bot.research.deflated import deflated_sharpe_from_returns
from bot.research.walkforward import walk_forward
from bot.strategies.baseline import MACrossover
from bot.timeframes import bar_length

REPORT_DIR = Path("reports")


def pct(x):
    return f"{x:.1%}"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--instrument", default="BTC")
    parser.add_argument("--timeframe", default="1d", choices=["1h", "4h", "1d"])
    parser.add_argument("--train-days", type=int, default=730)
    parser.add_argument("--test-days", type=int, default=180)
    args = parser.parse_args()

    s = Settings()
    pair = s.instruments[args.instrument]
    tf = args.timeframe
    costs = s.costs_for(pair)
    df = CandleStore().load(pair, tf)
    strategy = MACrossover()
    run_args = dict(costs=costs, timeframe=tf, tds_bps=s.tds_bps, tds_mode=s.tds_mode,
                    max_leverage=s.max_leverage)

    # 1. Full-sample backtest (the trial the DSR judges).
    params = strategy.fit(df)
    full = backtest.run(df["close"], strategy.signal(df, params), **run_args,
                        stop_distance=strategy.stop_distance(df, params), ohlc=df)
    full_m = metrics.summary(full.net, full.equity, tf)

    # 2. Walk-forward, out of sample.
    train_bars = int(pd.Timedelta(days=args.train_days) / bar_length(tf))
    test_bars = int(pd.Timedelta(days=args.test_days) / bar_length(tf))
    wf = walk_forward(df, strategy, train_bars, test_bars, **run_args)
    wf_m = metrics.summary(wf.result.net, wf.result.equity, tf)
    wf_s = wf.summary()

    # 3. Log both runs, then deflate against every distinct trial on this market.
    with trials.connect() as conn:
        for kind, net in (("backtest", full.net), ("walkforward", wf.result.net)):
            trials.record(conn, kind=kind, strategy=strategy.name, params=params,
                          instrument=pair, timeframe=tf, net=net, source="research_report")
        dsr = deflated_sharpe_from_returns(full.net, trials.trial_sharpes(conn, pair, tf))
        total_rows = trials.count_all(conn)

    # 4. Regimes, on the out-of-sample returns.
    labels = regimes.label(df["close"], s.regime_ma_period, s.regime_band)
    regime_table = regimes.split(wf.result.net, labels, tf)
    verdict = regimes.edge_verdict(regime_table)

    results = [
        gates.critic(strategy.name, inspect.getfile(type(strategy))),
        gates.deflated_sharpe(dsr, s),
        gates.walk_forward(wf_s, s),
        gates.regimes(regime_table, verdict, s),
        gates.leakage(full_m["sharpe"], s),
    ]
    passed = all(g.passed for g in results)

    text = render(strategy.name, params, pair, tf, df, args, full, full_m, wf, wf_m, wf_s, dsr,
                  total_rows, regime_table, verdict, results, passed)
    REPORT_DIR.mkdir(exist_ok=True)
    out = REPORT_DIR / f"{strategy.name}_{pair}_{tf}.md"
    out.write_text(text)
    print(text)
    print(f"\nWritten to {out}")


def render(name, params, pair, tf, df, args, full, full_m, wf, wf_m, wf_s, dsr, total_rows,
           regime_table, verdict, results, passed):
    c = full.cost_summary()
    lines = [
        f"# Research report: {name} on {pair} {tf}",
        "",
        f"**Verdict: {'PASS, eligible for paper trading' if passed else 'REJECTED'}**",
        "",
        "| Gate | Result | Detail |", "|---|---|---|",
        *[f"| {g.name} | {'PASS' if g.passed else 'FAIL'} | {g.detail} |" for g in results],
        "",
        f"Data: {len(df)} bars, {df.index[0]:%Y-%m-%d} to {df.index[-1]:%Y-%m-%d} UTC. "
        f"Params: `{params}`.",
        "",
        "## Full-sample backtest",
        "",
        "| Metric | Value |", "|---|---|",
        f"| Sharpe (annualized) | {full_m['sharpe']:.2f} |",
        f"| Annual return | {pct(full_m['annual_return'])} |",
        f"| Max drawdown | {pct(full_m['max_drawdown'])} |",
        f"| Longest drawdown | {full_m['longest_drawdown_bars']} bars ({full_m['longest_drawdown']}) |",
        f"| Calmar | {full_m['calmar']:.2f} |",
        f"| Stop-outs | {int(full.bars['stopped'].sum())} |",
        f"| Gross / net return | {pct(c['gross_return'])} / {pct(c['net_return'])} |",
        f"| Fees + slippage | {pct(c['fees_and_slippage'])} of starting capital |",
        f"| Funding | {pct(c['funding'])} of starting capital |",
        f"| TDS withheld ({c['tds_mode']} mode) | {pct(c['tds_withheld'])} of starting capital |",
        "",
        f"> {c['funding_note']}",
        "",
        "## Deflated Sharpe",
        "",
        f"- Per-period Sharpe: {dsr['sr_per_period']:.4f}",
        f"- Expected best-of-N by luck (SR0): {dsr['sr0_per_period']:.4f}",
        f"- Distinct trials on {pair} {tf}: N = {dsr['n_trials']} "
        f"(trials table holds {total_rows} runs in total)",
        f"- Skew {dsr['skew']:.2f}, raw kurtosis {dsr['kurtosis']:.2f}, T = {dsr['n_obs']}",
        f"- **DSR = {dsr['dsr']:.3f}**",
        "",
        "## Walk-forward (out of sample)",
        "",
        f"Train {args.train_days} days, test {args.test_days} days, rolling, warmup = train window.",
        "",
        f"- Positive folds: **{wf_s['positive_folds']}/{wf_s['n_folds']}**",
        f"- Worst fold: **#{wf_s['worst_fold']} at {pct(wf_s['worst_fold_return'])}** "
        f"(Sharpe {wf_s['worst_fold_sharpe']:.2f})",
        f"- Stitched OOS: Sharpe {wf_m['sharpe']:.2f}, annual {pct(wf_m['annual_return'])}, "
        f"max DD {pct(wf_m['max_drawdown'])}",
        "",
        "| Fold | Test period | Return | Sharpe | Max DD |", "|---|---|---|---|---|",
    ]
    for i, row in wf.fold_table().iterrows():
        lines.append(f"| {i} | {row.test_start:%Y-%m-%d} to {row.test_end:%Y-%m-%d} | "
                     f"{pct(row['return'])} | {row.sharpe:.2f} | {pct(row.max_drawdown)} |")
    lines += [
        "",
        "## Regimes (out of sample)",
        "",
        "| Regime | Bars | Share | Sharpe | Return |", "|---|---|---|---|---|",
    ]
    for regime, row in regime_table.iterrows():
        lines.append(f"| {regime} | {int(row.n_obs)} | {pct(row.share)} | "
                     f"{row.sharpe:.2f} | {pct(row['return'])} |")
    lines += ["", f"**{verdict}**", ""]
    return "\n".join(lines)


if __name__ == "__main__":
    main()
