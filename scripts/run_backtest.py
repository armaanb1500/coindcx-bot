"""Run the baseline strategy on cached candles and print a report.

    .venv/bin/python -m scripts.run_backtest --instrument BTC --timeframe 1d
"""

import argparse

import pandas as pd

from bot.config import Settings
from bot.data.store import CandleStore
from bot.live.sizing import RiskRule
from bot.research import backtest, metrics, trials
from bot.strategies.baseline import MACrossover


def report(title: str, result: backtest.BacktestResult) -> dict:
    m = metrics.summary(result.net, result.equity, result.timeframe)
    c = result.cost_summary()
    print(f"\n== {title}")
    print(f"  Sharpe (annual)    {m['sharpe']:8.2f}    per-period {m['sharpe_per_period']:.4f}")
    print(f"  Annual return      {m['annual_return']:8.1%}")
    print(f"  Max drawdown       {m['max_drawdown']:8.1%}")
    print(f"  Longest drawdown   {m['longest_drawdown_bars']:8d} bars ({m['longest_drawdown']})")
    print(f"  Calmar             {m['calmar']:8.2f}")
    print(f"  n_obs              {m['n_obs']:8d}    periods/year {m['periods_per_year']:.0f}")
    print(f"  Gross return       {c['gross_return']:8.1%}    net {c['net_return']:.1%}")
    print(f"  Fees + slippage    {c['fees_and_slippage']:8.2%}  of starting capital")
    print(f"  Funding            {c['funding']:8.2%}  of starting capital")
    print(f"  TDS withheld       {c['tds_withheld']:8.2%}  of starting capital ({c['tds_mode']} mode)")
    print(f"  Turnover           {c['turnover']:8.1f}x    stop-outs {int(result.bars['stopped'].sum())}")
    print(f"  ! {c['funding_note']}")
    return m


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--instrument", default="BTC")
    parser.add_argument("--timeframe", default="1d", choices=["1h", "4h", "1d"])
    args = parser.parse_args()

    settings = Settings()
    pair = settings.instruments[args.instrument]
    df = CandleStore().load(pair, args.timeframe)
    print(f"{pair} {args.timeframe}: {len(df)} bars, "
          f"{df.index[0]:%Y-%m-%d} -> {df.index[-1]:%Y-%m-%d} UTC")

    def run(signal: pd.Series, stops: pd.Series | None = None,
            rule: RiskRule | None = None) -> backtest.BacktestResult:
        return backtest.run(df["close"], signal, settings.costs_for(pair), args.timeframe,
                            settings.tds_bps, settings.tds_mode, settings.max_leverage,
                            stop_distance=stops, ohlc=df if stops is not None else None,
                            risk_rule=rule)

    strategy = MACrossover()
    params = strategy.fit(df)  # fixed defaults; nothing is fitted on this data
    rule = RiskRule.from_settings(settings)  # sized by risk, as live trading sizes
    trial_params = {**params, "sizing": "risk", "risk_pct": rule.risk_pct,
                    "max_position_pct": rule.max_position_pct}
    result = run(strategy.signal(df, params), strategy.stop_distance(df, params), rule)
    m = report(f"{strategy.name} {trial_params}", result)
    with trials.connect() as conn:  # every run is a trial, logged automatically
        trials.record(conn, kind="backtest", strategy=strategy.name, params=trial_params,
                      instrument=pair, timeframe=args.timeframe, net=result.net,
                      source="run_backtest")
    report("buy and hold (for comparison)", run(pd.Series(1.0, index=df.index)))

    if args.timeframe == "1d" and m["sharpe"] > 2:
        print("\n!! Sharpe above 2 on daily data: treat as LEAKAGE until proven otherwise.")
    print("\nNo validation gates here. For those: python -m scripts.research_report")


if __name__ == "__main__":
    main()
