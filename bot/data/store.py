"""Parquet candle cache with incremental updates.

One file per (pair, timeframe): data/candles/B-BTC_USDT_1h.parquet.
Index is the bar OPEN time in UTC. A bar's data is known at open time + bar length.
"""

from pathlib import Path

import pandas as pd

from bot.data.coindcx import PublicClient
from bot.timeframes import api_resolution, bar_length

DEFAULT_DIR = Path("data/candles")
# Earlier than any CoinDCX futures history; the API just starts where its data starts.
HISTORY_START = pd.Timestamp("2020-01-01", tz="UTC")


class CandleStore:
    def __init__(self, root: Path = DEFAULT_DIR, client: PublicClient | None = None):
        self.root = Path(root)
        self.client = client or PublicClient()

    def path(self, pair: str, timeframe: str) -> Path:
        return self.root / f"{pair}_{timeframe}.parquet"

    def load(self, pair: str, timeframe: str) -> pd.DataFrame:
        path = self.path(pair, timeframe)
        if not path.exists():
            raise FileNotFoundError(f"No cached {pair} {timeframe}. Run scripts/fetch_history.py first.")
        return pd.read_parquet(path)

    def update(self, pair: str, timeframe: str) -> pd.DataFrame:
        """Fetch only what's new since the last cached bar, then save."""
        resolution = api_resolution(timeframe)
        if resolution is None:  # 4h: refresh 1h, then rebuild
            hourly = self.update(pair, "1h")
            df = resample(hourly, timeframe, source_timeframe="1h")
        else:
            path = self.path(pair, timeframe)
            old = pd.read_parquet(path) if path.exists() else None
            # Re-fetch the last cached bar too, in case it was revised.
            start = old.index[-1] if old is not None and len(old) else HISTORY_START
            new = self.client.candles(pair, resolution, start)
            df = new if old is None else pd.concat([old, new])
            df = df[~df.index.duplicated(keep="last")].sort_index()

        self.root.mkdir(parents=True, exist_ok=True)
        df.to_parquet(self.path(pair, timeframe))
        return df


def resample(df: pd.DataFrame, timeframe: str, source_timeframe: str) -> pd.DataFrame:
    """Build bigger bars from smaller ones, keeping only bars that have fully closed.

    Bins are left-closed and labelled by open time (00:00, 04:00, ... UTC), the
    same convention as the API's own bars. Bins the source data doesn't fully
    span are dropped: at the end that's the forming bar (using it would repaint),
    at the start it's a bin that history begins partway through.
    """
    size = bar_length(timeframe)
    out = df.resample(size, closed="left", label="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    ).dropna(subset=["close"])
    data_ends = df.index[-1] + bar_length(source_timeframe)
    return out[(out.index >= df.index[0]) & (out.index + size <= data_ends)]
