"""Download or top up cached candles for every configured instrument.

    .venv/bin/python -m scripts.fetch_history
"""

import logging

from bot.config import Settings
from bot.data.coindcx import PublicClient
from bot.data.store import CandleStore

TIMEFRAMES = ["1h", "4h", "1d"]


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    settings = Settings()
    client = PublicClient()

    active = set(client.active_instruments())
    store = CandleStore(client=client)
    for name, pair in settings.instruments.items():
        if pair not in active:
            raise SystemExit(f"{name} ({pair}) is not in CoinDCX's active futures list")
        for tf in TIMEFRAMES:
            df = store.update(pair, tf)
            print(f"{name:4} {pair:12} {tf:3} {len(df):6} bars  "
                  f"{df.index[0]:%Y-%m-%d %H:%M} -> {df.index[-1]:%Y-%m-%d %H:%M} UTC")


if __name__ == "__main__":
    main()
