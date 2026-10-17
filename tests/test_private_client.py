"""Signing and safety tests for the private client. No network calls."""

import hashlib
import hmac
import json

import httpx
import pytest

from bot.data.coindcx import CoinDCXError, PrivateClient, sign


def test_sign_matches_the_docs_recipe():
    # The docs' Python example, step by step, with made-up values.
    secret = "YYYY"
    body = {"side": "buy", "order_type": "limit_order", "market": "SNTBTC",
            "price_per_unit": 0.03244, "total_quantity": 400, "timestamp": 1700000000000}
    json_body = json.dumps(body, separators=(",", ":"))
    expected = hmac.new(bytes(secret, encoding="utf-8"), json_body.encode(),
                        hashlib.sha256).hexdigest()

    payload, signature = sign(body, secret)
    assert payload == json_body
    assert " " not in payload  # compact JSON, or the signature won't match
    assert signature == expected


def test_request_sends_exactly_the_signed_payload():
    seen = {}

    def handler(request: httpx.Request):
        seen["body"] = request.content.decode()
        seen["headers"] = request.headers
        return httpx.Response(200, json=[{"currency_short_name": "USDT"}])

    client = PrivateClient("KEY", "SECRET", http=httpx.Client(transport=httpx.MockTransport(handler)))
    assert client.futures_wallets() == [{"currency_short_name": "USDT"}]
    body = json.loads(seen["body"])
    assert set(body) == {"timestamp"} and body["timestamp"] > 1e12  # milliseconds
    assert seen["headers"]["X-AUTH-APIKEY"] == "KEY"
    assert seen["headers"]["X-AUTH-SIGNATURE"] == sign(body, "SECRET")[1]


def test_paths_off_the_allowlist_are_refused_before_any_request():
    def handler(request):
        raise AssertionError("no request should be sent")

    client = PrivateClient("KEY", "SECRET", http=httpx.Client(transport=httpx.MockTransport(handler)))
    for path in ("/exchange/v1/derivatives/futures/wallets/transfer",
                 "/exchange/v1/derivatives/futures/orders/create"):
        with pytest.raises(CoinDCXError, match="allowlist"):
            client._signed_request("POST", path)


def test_secrets_never_appear_in_repr_or_logs(caplog):
    caplog.set_level("INFO")
    client = PrivateClient("MYKEY123", "MYSECRET456", http=httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json=[]))))
    client.futures_wallets()
    assert "MYKEY123" not in repr(client) and "MYSECRET456" not in repr(client)
    assert "MYKEY123" not in caplog.text and "MYSECRET456" not in caplog.text


def test_missing_credentials_fail_clearly():
    with pytest.raises(CoinDCXError, match="missing"):
        PrivateClient("", "")
