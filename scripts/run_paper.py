"""Run the bot in PAPER mode: real signals, real Telegram approvals, simulated fills.
No order endpoint is ever called.

    .venv/bin/python -m scripts.run_paper

Needs MODE=paper and CAPITAL_INR in .env. Stop it with Ctrl+C. Restarting is safe:
everything lives in data/trades.db.

Until a strategy passes every gate, this runs the REJECTED baseline on 1h bars purely
to test the plumbing (owner's decision, see CLAUDE.md).
"""

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from bot.config import Settings
from bot.data.coindcx import PrivateClient, PublicClient
from bot.data.store import CandleStore
from bot.live import risk
from bot.live.runner import PaperBot
from bot.live.telegram_bot import ApprovalService, build_app, notify, run_blocking, send_proposal
from bot.log import db
from bot.strategies.baseline import MACrossover

TIMEFRAME = "1h"
LABEL = "PLUMBING TEST: strategy REJECTED by the gates. Paper only."
BAR_CLOSE_DELAY = timedelta(seconds=30)  # give the exchange time to finalise the bar
TICK_SECONDS = 20

log = logging.getLogger("run_paper")


async def scheduler(app, service: ApprovalService, bot: PaperBot):
    reference = await run_blocking(bot.backtest_reference, bot.s.instruments["BTC"])
    await notify(app, service, f"Paper bot started.\n[{LABEL}]\n"
                               f"Strategy {bot.strategy.name} on {TIMEFRAME} bars, "
                               f"capital ₹{bot.s.capital_inr:,.0f}.\n"
                               f"Commands: /status, /halt")
    last_bar = None
    last_health_day = datetime.now(UTC).date()
    while True:
        try:
            now = datetime.now(UTC)
            bar = now.replace(minute=0, second=0, microsecond=0)
            if bar != last_bar and now >= bar + BAR_CLOSE_DELAY:
                last_bar = bar
                ids, notes = await run_blocking(bot.on_bar_close)
                for pid in ids:
                    await send_proposal(app, service, pid)
                for note in notes:
                    await notify(app, service, note)

            expired_msgs, stop_msgs = await run_blocking(bot.every_minute)
            for msg_id in expired_msgs:
                await app.bot.edit_message_reply_markup(bot.s.telegram_chat_id, msg_id,
                                                        reply_markup=None)
                await app.bot.send_message(bot.s.telegram_chat_id, "Expired: no decision in time.",
                                           reply_to_message_id=msg_id)
            for text in stop_msgs:
                await notify(app, service, text)

            if now.date() != last_health_day:
                last_health_day = now.date()
                problems = await run_blocking(bot.daily_health, reference)
                if problems:
                    await notify(app, service, "HEALTH CHECK HALTED THE BOT:\n" + "\n".join(problems))
        except Exception as e:
            log.exception("scheduler tick failed")
            await notify(app, service, f"Error (bot keeps running): {e}")
        await asyncio.sleep(TICK_SECONDS)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # httpx logs every URL at INFO, and Telegram URLs contain the bot token.
    logging.getLogger("httpx").setLevel(logging.WARNING)

    s = Settings()
    if s.mode != "paper":
        raise SystemExit(f"run_paper needs MODE=paper in .env (it is {s.mode!r})")
    if s.capital_inr <= 0:
        raise SystemExit("Set CAPITAL_INR in .env first")
    if risk.is_halted():
        print("Note: a HALT file exists, so no proposals will be made until you delete it.")

    conn = db.connect()
    public = PublicClient()
    private = PrivateClient(s.coindcx_api_key.get_secret_value(),
                            s.coindcx_api_secret.get_secret_value())
    service = ApprovalService(conn, s, public.current_price)
    bot = PaperBot(conn, s, CandleStore(client=public), public, private, MACrossover(),
                   TIMEFRAME, LABEL)

    async def start_scheduler(app):
        app.create_task(scheduler(app, service, bot))

    app = build_app(service, post_init=start_scheduler)
    app.run_polling()


if __name__ == "__main__":
    main()
