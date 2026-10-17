"""Telegram approval UI.

ApprovalService holds the logic and is tested without Telegram. The handlers at
the bottom are thin wiring that pass Telegram events into it.

Only messages and button taps from TELEGRAM_CHAT_ID are handled; everything
else is ignored silently.
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

from bot.config import Settings
from bot.live import executor, risk
from bot.live.executor import PriceFn
from bot.log import db


# All blocking work (SQLite, HTTP) runs on this ONE thread, so it never runs
# concurrently and never blocks Telegram's event loop.
_WORKER = ThreadPoolExecutor(max_workers=1, thread_name_prefix="bot-worker")


async def run_blocking(fn, *args):
    return await asyncio.get_running_loop().run_in_executor(_WORKER, fn, *args)


def format_card(p, s: Settings) -> str:
    direction = "LONG" if p["side"] == "buy" else "SHORT"
    lines = [f"[{p['label']}]"] if p["label"] else []
    lines += [
        f"{'PAPER ' if p['mode'] == 'paper' else ''}PROPOSAL: {direction} {p['pair']}",
        f"Entry   {p['entry']:,.2f} USDT",
        f"Stop    {p['stop']:,.2f} USDT",
    ]
    if p["take_profit"] is not None:
        lines.append(f"Target  {p['take_profit']:,.2f} USDT")
    lines += [
        f"Size    {p['quantity']} ({p['notional_usdt']:,.2f} USDT notional)",
        f"Leverage {p['leverage']:g}x",
        f"Loss if stop hits: ₹{p['loss_at_stop_inr']:,.0f} ({p['loss_at_stop_pct']:.2%} of capital)",
        f"Strategy {p['strategy']}",
        *([f"FLIP: closes your open {'SHORT' if direction == 'LONG' else 'LONG'} first"]
          if p["kind"] == "flip" else []),
        f"Signal  {p['signal_time']}",
        f"Expires {p['expires_at'][11:19]} UTC",
    ]
    return "\n".join(lines)


def keyboard(proposal_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("Approve", callback_data=f"approve:{proposal_id}"),
        InlineKeyboardButton("Reject", callback_data=f"reject:{proposal_id}"),
    ]])


class ApprovalService:
    def __init__(self, conn, s: Settings, current_price: PriceFn, halt_file=risk.HALT_FILE):
        self.conn, self.s, self.current_price, self.halt_file = conn, s, current_price, halt_file

    def authorized(self, chat_id: int | None) -> bool:
        return chat_id is not None and chat_id == self.s.telegram_chat_id

    def on_button(self, chat_id: int, data: str) -> str | None:
        """Returns the text to show under the card, or None to ignore silently."""
        if not self.authorized(chat_id):
            return None
        decision, _, proposal_id = data.partition(":")
        if decision not in ("approve", "reject"):
            return None
        accepted, reason = db.decide(self.conn, proposal_id, decision, chat_id)
        if not accepted:
            return f"Not done: {reason}"
        if decision == "reject":
            return "Rejected."
        return executor.execute(self.conn, proposal_id, self.current_price, self.s).message

    def on_halt(self, chat_id: int) -> str | None:
        if not self.authorized(chat_id):
            return None
        risk.halt("/halt from Telegram", self.halt_file)
        return "HALTED. No new proposals. Delete the HALT file in the repo root to resume."

    def on_status(self, chat_id: int) -> str | None:
        if not self.authorized(chat_id):
            return None
        pending = self.conn.execute(
            "SELECT COUNT(*) FROM proposals WHERE status = 'pending'").fetchone()[0]
        return (f"Mode: {self.s.mode}\nHalted: {'YES' if risk.is_halted(self.halt_file) else 'no'}\n"
                f"Pending proposals: {pending}")


# --- Telegram wiring ------------------------------------------------------------

def build_app(service: ApprovalService, post_init=None) -> Application:
    token = service.s.telegram_bot_token.get_secret_value()
    builder = Application.builder().token(token)
    if post_init is not None:
        builder = builder.post_init(post_init)
    app = builder.build()

    async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        chat_id = update.effective_chat.id if update.effective_chat else None
        if not service.authorized(chat_id):
            return  # silent: don't even acknowledge the tap
        await query.answer()
        text = await run_blocking(service.on_button, chat_id, query.data or "")
        if text:
            await query.edit_message_text(f"{query.message.text}\n\n{text}")

    async def halt(update: Update, context: ContextTypes.DEFAULT_TYPE):
        text = await run_blocking(service.on_halt, update.effective_chat.id)
        if text:
            await update.message.reply_text(text)

    async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
        text = await run_blocking(service.on_status, update.effective_chat.id)
        if text:
            await update.message.reply_text(text)

    app.add_handler(CallbackQueryHandler(button))
    app.add_handler(CommandHandler("halt", halt))
    app.add_handler(CommandHandler("status", status))
    return app


async def send_proposal(app: Application, service: ApprovalService, proposal_id: str) -> None:
    p = await run_blocking(db.get_proposal, service.conn, proposal_id)
    msg = await app.bot.send_message(service.s.telegram_chat_id, format_card(p, service.s),
                                     reply_markup=keyboard(proposal_id))
    await run_blocking(db.set_message_id, service.conn, proposal_id, msg.message_id)


async def notify(app: Application, service: ApprovalService, text: str) -> None:
    await app.bot.send_message(service.s.telegram_chat_id, text)
