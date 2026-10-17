"""Check that .env is filled in and every credential works. Prints no secret values.

    .venv/bin/python -m scripts.check_setup

Sends one test message to your Telegram chat and makes one read-only CoinDCX call.
"""

import stat
import subprocess
from pathlib import Path

import httpx
from pydantic import ValidationError

from bot.config import Settings
from bot.data.coindcx import CoinDCXError, PrivateClient


def line(ok: bool, what: str, detail: str = ""):
    print(f"  [{'OK' if ok else 'FAIL'}] {what}{': ' + detail if detail else ''}")
    return ok


def main():
    print("== .env file")
    env = Path(".env")
    if not line(env.exists(), ".env exists"):
        return
    mode = stat.S_IMODE(env.stat().st_mode)
    line(mode & 0o077 == 0, "only you can read it", f"permissions {oct(mode)}")
    tracked = subprocess.run(["git", "ls-files", "--error-unmatch", ".env"],
                             capture_output=True).returncode == 0
    line(not tracked, "not tracked by git")

    try:
        s = Settings()
    except ValidationError as e:
        # Report field names only: pydantic would otherwise echo the bad value.
        for err in e.errors():
            line(False, f"{'.'.join(map(str, err['loc']))} is invalid", err["type"])
        return

    print("\n== values present (not shown)")
    for name in ("coindcx_api_key", "coindcx_api_secret", "telegram_bot_token"):
        line(bool(getattr(s, name).get_secret_value()), name.upper())
    line(s.telegram_chat_id != 0, "TELEGRAM_CHAT_ID")
    line(s.mode in ("backtest", "paper"), "MODE", s.mode)

    print("\n== Telegram")
    check_telegram(s)

    print("\n== CoinDCX (read-only call)")
    check_coindcx(s)


def check_telegram(s: Settings):
    token = s.telegram_bot_token.get_secret_value()
    base = f"https://api.telegram.org/bot{token}"
    try:
        with httpx.Client(timeout=20) as http:
            me = http.get(f"{base}/getMe").json()
            if not line(me.get("ok", False), "bot token accepted",
                        f"@{me['result']['username']}" if me.get("ok") else me.get("description", "")):
                return
            sent = http.post(f"{base}/sendMessage", json={
                "chat_id": s.telegram_chat_id,
                "text": "CoinDCX bot connected. Trade proposals will arrive in this chat.",
            }).json()
            line(sent.get("ok", False), "test message sent to your chat",
                 "check Telegram" if sent.get("ok") else sent.get("description", ""))
    except httpx.HTTPError as e:
        # The exception text can contain the URL, which contains the token.
        line(False, "could not reach Telegram", type(e).__name__)


def check_coindcx(s: Settings):
    try:
        client = PrivateClient(s.coindcx_api_key.get_secret_value(),
                               s.coindcx_api_secret.get_secret_value())
        wallets = client.futures_wallets()
        currencies = sorted({w.get("currency_short_name", "?") for w in wallets})
        line(True, "key and secret accepted", f"futures wallets: {', '.join(currencies) or 'none'}")
    except CoinDCXError as e:
        line(False, "CoinDCX rejected the request", str(e))
    except httpx.HTTPError as e:
        line(False, "could not reach CoinDCX", type(e).__name__)
    print("  [CHECK] confirm in the CoinDCX API Dashboard that withdrawal is OFF for this key "
          "(the API can't report its own permissions)")


if __name__ == "__main__":
    main()
