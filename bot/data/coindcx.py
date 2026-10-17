"""Thin CoinDCX REST client.

Phase 1 is public endpoints only. Signed private calls get added in Phase 3.
Every endpoint here was checked against https://docs.coindcx.com/ and the live API.
"""

import logging
import time

import httpx
import pandas as pd

log = logging.getLogger(__name__)

API_BASE = "https://api.coindcx.com"
PUBLIC_BASE = "https://public.coindcx.com"

# Seen live: the candle endpoint returns at most 30,000 rows per request.
MAX_CANDLES_PER_REQUEST = 30_000
CANDLE_COLUMNS = ["open", "high", "low", "close", "volume"]
RESOLUTION_LENGTH = {"1": pd.Timedelta(minutes=1), "5": pd.Timedelta(minutes=5),
                     "60": pd.Timedelta(hours=1), "1D": pd.Timedelta(days=1)}


class CoinDCXError(RuntimeError):
    pass


class PublicClient:
    def __init__(self, http: httpx.Client | None = None, max_retries: int = 5,
                 backoff_seconds: float = 1.0):
        self.http = http or httpx.Client(timeout=30)
        self.max_retries = max_retries
        self.backoff_seconds = backoff_seconds

    def _get(self, url: str, params: dict) -> object:
        """GET with exponential backoff on rate limits (429) and server errors (5xx)."""
        for attempt in range(self.max_retries + 1):
            resp = self.http.get(url, params=params)
            if resp.status_code == 429 or resp.status_code >= 500:
                if attempt == self.max_retries:
                    break
                wait = self.backoff_seconds * 2**attempt
                log.warning("GET %s -> %s, retrying in %.1fs", url, resp.status_code, wait)
                time.sleep(wait)
                continue
            if resp.status_code != 200:
                raise CoinDCXError(f"GET {url} -> {resp.status_code}: {resp.text[:200]}")
            return resp.json()
        raise CoinDCXError(f"GET {url} still failing after {self.max_retries} retries")

    def active_instruments(self, margin: str = "USDT") -> list[str]:
        url = f"{API_BASE}/exchange/v1/derivatives/futures/data/active_instruments"
        return self._get(url, {"margin_currency_short_name[]": margin})

    def instrument(self, pair: str, margin: str = "USDT") -> dict:
        url = f"{API_BASE}/exchange/v1/derivatives/futures/data/instrument"
        return self._get(url, {"pair": pair, "margin_currency_short_name": margin})["instrument"]

    def candles(self, pair: str, resolution: str, start: pd.Timestamp,
                end: pd.Timestamp | None = None) -> pd.DataFrame:
        """Closed bars whose open time is in [start, end], indexed by open time (UTC).

        Pages through the 30k-row cap. Drops the bar that is still forming.
        """
        bar = RESOLUTION_LENGTH[resolution]
        now = pd.Timestamp.now(tz="UTC")
        end = min(end or now, now)
        start = _utc(start)
        url = f"{PUBLIC_BASE}/market_data/candlesticks"

        frames = []
        page_start = start
        while page_start <= end:
            page_end = min(end, page_start + bar * (MAX_CANDLES_PER_REQUEST - 1))
            data = self._get(url, {"pair": pair, "resolution": resolution, "pcode": "f",
                                   "from": int(page_start.timestamp()),
                                   "to": int(page_end.timestamp())})
            # "no_data" (seen live) means the window is before the instrument's history.
            if data.get("s") not in ("ok", "no_data"):
                raise CoinDCXError(f"candles {pair} {resolution}: {data}")
            if data.get("data"):
                frames.append(_to_frame(data["data"]))
            page_start = page_end + bar

        if not frames:
            return _to_frame([])
        df = pd.concat(frames)
        df = df[~df.index.duplicated(keep="last")].sort_index()
        df = df[(df.index >= start) & (df.index <= end)]
        # A bar is only usable once it has closed.
        return df[df.index + bar <= now]


def _utc(ts) -> pd.Timestamp:
    ts = pd.Timestamp(ts)
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def _to_frame(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=["time", *CANDLE_COLUMNS])
    df.index = pd.to_datetime(df.pop("time"), unit="ms", utc=True)
    df.index.name = "open_time"
    return df.astype(float)
