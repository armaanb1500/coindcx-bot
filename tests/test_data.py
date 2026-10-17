"""Client and cache tests. A fake transport stands in for CoinDCX: no network calls."""

import httpx
import pandas as pd
import pytest

from bot.data import coindcx
from bot.data.coindcx import CoinDCXError, PublicClient
from bot.data.store import CandleStore, resample

HOUR_MS = 3_600_000


def fake_exchange(first_open: pd.Timestamp, last_open: pd.Timestamp, calls: list):
    """Serves hourly bars in [first_open, last_open], honouring from/to like the real API."""

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(dict(request.url.params))
        lo = max(int(request.url.params["from"]) * 1000, int(first_open.timestamp() * 1000))
        hi = min(int(request.url.params["to"]) * 1000, int(last_open.timestamp() * 1000))
        start = lo + (-lo % HOUR_MS)
        rows = [{"open": 1.0, "high": 2.0, "low": 0.5, "close": t / HOUR_MS, "volume": 1.0, "time": t}
                for t in range(start, hi + 1, HOUR_MS)]
        return httpx.Response(200, json={"s": "ok", "data": rows})

    return PublicClient(http=httpx.Client(transport=httpx.MockTransport(handler)))


def test_candles_index_is_utc_open_time_and_forming_bar_dropped():
    now = pd.Timestamp.now(tz="UTC").floor("h")
    client = fake_exchange(now - pd.Timedelta(hours=5), now, calls := [])
    df = client.candles("B-BTC_USDT", "60", now - pd.Timedelta(hours=10))
    assert str(df.index.tz) == "UTC"
    assert df.index[-1] == now - pd.Timedelta(hours=1)  # bar opened at `now` is still forming
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]


def test_candles_pages_past_the_row_cap(monkeypatch):
    monkeypatch.setattr(coindcx, "MAX_CANDLES_PER_REQUEST", 10)
    start = pd.Timestamp("2024-01-01", tz="UTC")
    client = fake_exchange(start, start + pd.Timedelta(hours=34), calls := [])
    df = client.candles("B-BTC_USDT", "60", start, start + pd.Timedelta(hours=34))
    assert len(calls) == 4
    assert len(df) == 35 and df.index.is_unique and df.index.is_monotonic_increasing


def test_no_data_before_history_start_is_empty_not_an_error():
    reply = httpx.Response(200, json={"s": "no_data", "data": []})
    client = PublicClient(http=httpx.Client(transport=httpx.MockTransport(lambda r: reply)))
    df = client.candles("B-XAU_USDT", "60", pd.Timestamp("2020-01-01", tz="UTC"),
                        pd.Timestamp("2020-02-01", tz="UTC"))
    assert df.empty


def test_unexpected_status_raises():
    reply = httpx.Response(200, json={"s": "error", "data": []})
    client = PublicClient(http=httpx.Client(transport=httpx.MockTransport(lambda r: reply)))
    with pytest.raises(CoinDCXError):
        client.candles("B-BTC_USDT", "60", pd.Timestamp("2024-01-01", tz="UTC"),
                       pd.Timestamp("2024-01-02", tz="UTC"))


def test_backoff_on_429_then_success(monkeypatch):
    monkeypatch.setattr(coindcx.time, "sleep", lambda s: None)
    replies = iter([httpx.Response(429), httpx.Response(503), httpx.Response(200, json=["B-BTC_USDT"])])
    client = PublicClient(http=httpx.Client(transport=httpx.MockTransport(lambda r: next(replies))))
    assert client.active_instruments() == ["B-BTC_USDT"]


def test_gives_up_after_max_retries(monkeypatch):
    monkeypatch.setattr(coindcx.time, "sleep", lambda s: None)
    client = PublicClient(http=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(429))),
                          max_retries=2)
    with pytest.raises(CoinDCXError):
        client.active_instruments()


def test_incremental_update_only_fetches_new_bars(tmp_path):
    start = pd.Timestamp("2024-01-01", tz="UTC")
    store = CandleStore(tmp_path, fake_exchange(start, start + pd.Timedelta(hours=49), calls := []))
    first = store.update("B-BTC_USDT", "1h")
    assert len(first) == 50

    store.client = fake_exchange(start, start + pd.Timedelta(hours=59), calls := [])
    second = store.update("B-BTC_USDT", "1h")
    assert len(second) == 60 and second.index.is_unique
    # The second run asked only from the last cached bar onward.
    assert int(calls[0]["from"]) == int(first.index[-1].timestamp())
    pd.testing.assert_frame_equal(store.load("B-BTC_USDT", "1h"), second, check_freq=False)


def test_resample_4h_is_aligned_and_drops_forming_bar():
    idx = pd.date_range("2024-01-01 00:00", periods=10, freq="h", tz="UTC")  # 00:00 .. 09:00
    hourly = pd.DataFrame({"open": range(10), "high": range(10, 20), "low": range(10),
                           "close": range(1, 11), "volume": 1.0}, index=idx, dtype=float)
    four = resample(hourly, "4h", source_timeframe="1h")
    # 08:00 bin only has 08:00 and 09:00, so it hasn't closed yet and must go.
    assert list(four.index.hour) == [0, 4]
    first = four.iloc[0]
    assert (first.open, first.high, first.low, first.close, first.volume) == (0, 13, 0, 4, 4)


def test_resample_drops_bin_that_history_starts_inside():
    idx = pd.date_range("2024-01-01 02:00", periods=6, freq="h", tz="UTC")  # 02:00 .. 07:00
    hourly = pd.DataFrame({"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0}, index=idx)
    four = resample(hourly, "4h", source_timeframe="1h")
    assert list(four.index.hour) == [4]  # 00:00 bin only has 02:00-03:00


def price_client(ls, minute_close):
    def handler(request: httpx.Request):
        if "current_prices" in request.url.path:
            return httpx.Response(200, json={"prices": {"B-BTC_USDT": {"ls": ls}}})
        t = int((pd.Timestamp.now(tz="UTC").floor("min") - pd.Timedelta(minutes=2)).timestamp() * 1000)
        return httpx.Response(200, json={"s": "ok", "data": [
            {"open": 1, "high": 1, "low": 1, "close": minute_close, "volume": 1, "time": t}]})
    return PublicClient(http=httpx.Client(transport=httpx.MockTransport(handler)))


def test_current_price_uses_live_price_when_it_agrees_with_candle():
    assert price_client(80000.0, 80100.0).current_price("B-BTC_USDT") == 80000.0


def test_current_price_refuses_when_sources_disagree():
    with pytest.raises(CoinDCXError, match="disagree"):
        price_client(80000.0, 81000.0).current_price("B-BTC_USDT")  # 1.2% apart
