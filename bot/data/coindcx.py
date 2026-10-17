"""Thin CoinDCX REST client.

PublicClient: market data, no key needed.
PrivateClient: signed calls, limited to an explicit allowlist of read-only paths.
Every endpoint here was checked against https://docs.coindcx.com/ and the live API.
"""

import hashlib
import hmac
import json
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

    def current_price(self, pair: str, max_disagreement: float = 0.005) -> float:
        """Last traded price, cross-checked against the last closed 1-minute candle.

        `ls` from the live-prices endpoint has no description in the docs; it is
        used as the last price (owner's decision), but only if it agrees with the
        documented candle endpoint to within max_disagreement (0.5%).
        """
        data = self._get(f"{PUBLIC_BASE}/market_data/v3/current_prices/futures/rt", {})
        live = float(data["prices"][pair]["ls"])
        now = pd.Timestamp.now(tz="UTC")
        minute = self.candles(pair, "1", now - pd.Timedelta(minutes=10), now)
        if minute.empty:
            raise CoinDCXError(f"no recent 1-minute candle for {pair} to cross-check against")
        check = float(minute["close"].iloc[-1])
        if abs(live - check) / check > max_disagreement:
            raise CoinDCXError(f"{pair}: live price {live} and last 1m close {check} disagree "
                               f"by more than {max_disagreement:.1%}")
        return live


def _utc(ts) -> pd.Timestamp:
    ts = pd.Timestamp(ts)
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def _to_frame(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=["time", *CANDLE_COLUMNS])
    df.index = pd.to_datetime(df.pop("time"), unit="ms", utc=True)
    df.index.name = "open_time"
    return df.astype(float)


# The ONLY private paths this client will call. Order paths get added in Phase 4.
# Withdrawal and transfer endpoints must never appear here.
READ_ONLY_PATHS = {
    "/exchange/v1/derivatives/futures/wallets",
    "/exchange/v1/derivatives/futures/positions",
    "/api/v1/derivatives/futures/data/conversions",
}


def sign(body: dict, secret: str) -> tuple[str, str]:
    """Docs: payload = compact JSON of the body; signature = HMAC-SHA256(payload, secret) hex.

    Returns (payload, signature). The exact payload string must be what gets sent,
    or the signature won't match on CoinDCX's side.
    """
    payload = json.dumps(body, separators=(",", ":"))
    signature = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return payload, signature


class PrivateClient:
    def __init__(self, api_key: str, api_secret: str, http: httpx.Client | None = None):
        if not api_key or not api_secret:
            raise CoinDCXError("COINDCX_API_KEY / COINDCX_API_SECRET missing from .env")
        self._key = api_key
        self._secret = api_secret
        self.http = http or httpx.Client(timeout=30)

    def __repr__(self) -> str:
        return "PrivateClient(<redacted>)"

    def _signed_request(self, method: str, path: str, body: dict | None = None) -> object:
        if path not in READ_ONLY_PATHS:
            raise CoinDCXError(f"{path} is not on the allowlist of private paths")
        # Docs' code examples use milliseconds.
        body = {**(body or {}), "timestamp": int(time.time() * 1000)}
        payload, signature = sign(body, self._secret)
        headers = {"Content-Type": "application/json",
                   "X-AUTH-APIKEY": self._key, "X-AUTH-SIGNATURE": signature}
        resp = self.http.request(method, API_BASE + path, content=payload, headers=headers)
        # Log what was sent and what came back, never the key or signature.
        log.info("%s %s body=%s -> %s", method, path, payload, resp.status_code)
        if resp.status_code != 200:
            raise CoinDCXError(f"{method} {path} -> {resp.status_code}: {resp.text[:200]}")
        return resp.json()

    def futures_wallets(self) -> list[dict]:
        # The docs send this one as GET with a signed JSON body.
        return self._signed_request("GET", "/exchange/v1/derivatives/futures/wallets")

    def positions(self, margin: str = "INR") -> list[dict]:
        # Docs: POST, page/size as strings. active_pos < 0 means short.
        return self._signed_request("POST", "/exchange/v1/derivatives/futures/positions",
                                    {"page": "1", "size": "100",
                                     "margin_currency_short_name": [margin]})

    def usdt_inr_rate(self) -> float:
        # The docs' header says POST, but POST returns 404 live; their example uses GET.
        rows = self._signed_request("GET", "/api/v1/derivatives/futures/data/conversions")
        return float(next(r["conversion_price"] for r in rows if r["symbol"] == "USDTINR"))
