"""The paper bot's work, as plain methods the scheduler calls. No Telegram in here.

    every hour, just after the bar closes:  on_bar_close()  -> new proposals
    every minute:                           every_minute()  -> expiries, stop hits
    once a day:                             daily_health()  -> may HALT
"""

import logging
from datetime import UTC, datetime, timedelta

from bot.config import Settings
from bot.data.coindcx import PrivateClient, PublicClient
from bot.data.store import CandleStore
from bot.live import executor, health, risk
from bot.live.proposer import propose
from bot.live.risk import RiskState
from bot.live.sizing import Instrument
from bot.log import db
from bot.research import backtest, metrics
from bot.strategies.base import Strategy

log = logging.getLogger(__name__)


class PaperBot:
    def __init__(self, conn, s: Settings, store: CandleStore, public: PublicClient,
                 private: PrivateClient, strategy: Strategy, timeframe: str, label: str | None,
                 halt_file=risk.HALT_FILE):
        if s.mode != "paper":
            raise RuntimeError(f"PaperBot needs MODE=paper, not {s.mode}")
        self.conn, self.s, self.store = conn, s, store
        self.public, self.private = public, private
        self.strategy, self.timeframe, self.label = strategy, timeframe, label
        self.halt_file = halt_file
        self._instruments: dict[str, Instrument] = {}

    def instrument(self, pair: str) -> Instrument:
        if pair not in self._instruments:
            info = self.public.instrument(pair, self.s.margin_currency)
            costs = self.s.costs_for(pair)
            self._instruments[pair] = Instrument(
                pair, qty_step=float(info["quantity_increment"]),
                min_qty=float(info["min_quantity"]), min_notional=float(info["min_notional"]),
                fee_bps=costs.fee_bps, slippage_bps=costs.slippage_bps)
        return self._instruments[pair]

    def risk_state(self) -> RiskState:
        start_of_day = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        return RiskState(
            halted=risk.is_halted(self.halt_file),
            open_pairs={p["pair"] for p in db.open_positions(self.conn)},
            pending_pairs=db.pending_pairs(self.conn),
            realized_pnl_today_inr=db.realized_pnl_since(self.conn, start_of_day))

    def on_bar_close(self) -> tuple[list[str], list[str]]:
        """Returns (new proposal ids, notes worth telling you)."""
        ids, notes = [], []
        usdt_inr = self.private.usdt_inr_rate()
        for pair in self.s.instruments.values():
            try:
                df = self.store.update(pair, self.timeframe)
                params = self.strategy.fit(df)
                price = self.public.current_price(pair)
                out = propose(self.strategy, params, df, self.timeframe, pair, price, usdt_inr,
                              self.instrument(pair), db.open_position_for(self.conn, pair),
                              self.risk_state(), self.s, label=self.label)
            except Exception as e:  # one instrument failing mustn't stop the other
                log.exception("bar close failed for %s", pair)
                notes.append(f"{pair}: error at bar close: {e}")
                continue
            if out.proposal is not None:
                db.insert_proposal(self.conn, out.proposal)
                ids.append(out.proposal.id)
            if out.note:
                notes.append(out.note)
        return ids, notes

    def every_minute(self) -> tuple[list[int], list[str]]:
        """Returns (Telegram message ids of proposals that just expired, stop-hit messages)."""
        expired = db.expire_stale(self.conn)
        message_ids = [db.get_proposal(self.conn, pid)["telegram_message_id"] for pid in expired]
        stops = executor.check_stops(self.conn, self.public.current_price, self.s)
        return [m for m in message_ids if m is not None], stops

    def backtest_reference(self, pair: str) -> tuple[float, float]:
        """(annualized Sharpe, max drawdown) of the strategy's backtest, for the health check."""
        df = self.store.load(pair, self.timeframe)
        params = self.strategy.fit(df)
        result = backtest.run(df["close"], self.strategy.signal(df, params), self.s.costs_for(pair),
                              self.timeframe, self.s.tds_bps, self.s.tds_mode,
                              self.s.max_leverage,
                              stop_distance=self.strategy.stop_distance(df, params), ohlc=df)
        m = metrics.summary(result.net, result.equity, self.timeframe)
        return m["sharpe"], m["max_drawdown"]

    def daily_health(self, reference: tuple[float, float]) -> list[str]:
        start = db.first_activity(self.conn)
        if start is None:
            return []
        end = (datetime.now(UTC) - timedelta(days=1)).strftime("%Y-%m-%d")  # last full day
        if start[:10] > end:
            return []
        returns = health.daily_returns(db.daily_pnl(self.conn), self.s.capital_inr,
                                       start[:10], end)
        problems = health.check(returns, *reference)
        if problems:
            risk.halt("health check: " + "; ".join(problems), self.halt_file)
        return problems
