"""Per-symbol fallback when the plan does not support batch quotes.

FMP's /stable/quote returns HTTP 200 with an empty list when handed a
comma-separated symbol list on a plan without batch access (the dedicated
/stable/batch-quote endpoint 402s outright), and /api/v3/quote 403s for keys
created after 2025-08-31. The batch path therefore yields nothing while
single-symbol requests keep working, silently emptying the screener universe.

get_batch_quotes must notice this and fall back to per-symbol requests.
"""

import os
import sys
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fmp_client import FMPClient


def _make_client():
    return FMPClient(api_key="test_key")  # pragma: allowlist secret


def _mock_response(status_code, json_payload, text=""):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_payload
    resp.text = text
    return resp


def _quote_row(symbol):
    return {"symbol": symbol, "price": 100.0, "volume": 1_000_000}


class _BatchUnsupportedAPI:
    """Mimics a plan where batch quotes are unavailable but singles work."""

    def __init__(self):
        self.requested_symbols = []

    def __call__(self, url, params=None, timeout=None):
        params = params or {}
        if "/stable/" in url:
            symbols = params.get("symbol", "")
        else:
            symbols = url.rstrip("/").split("/")[-1]
        self.requested_symbols.append(symbols)

        if "," in symbols:
            # Batch request: stable returns an empty 200, v3 rejects the key.
            if "/stable/" in url:
                return _mock_response(200, [])
            return _mock_response(403, None, text="Legacy Endpoint")

        if "/stable/" in url:
            return _mock_response(200, [_quote_row(symbols)])
        return _mock_response(403, None, text="Legacy Endpoint")


class TestBatchQuoteFallsBackToPerSymbol:
    def test_returns_every_symbol_when_batch_returns_empty(self):
        client = _make_client()
        client.session.get = _BatchUnsupportedAPI()

        result = client.get_batch_quotes(["AAPL", "MSFT", "NVDA"])

        assert set(result) == {"AAPL", "MSFT", "NVDA"}
        assert result["AAPL"]["price"] == 100.0

    def test_stops_retrying_batches_after_first_unsupported_batch(self):
        client = _make_client()
        api = _BatchUnsupportedAPI()
        client.session.get = api

        # 12 symbols => 3 batches of 5/5/2 under the current batch_size.
        symbols = [f"S{i}" for i in range(12)]
        result = client.get_batch_quotes(symbols)

        assert set(result) == set(symbols)
        # One logical probe spans two HTTP calls (stable, then the v3
        # fallback), so count distinct batches rather than requests.
        probed_batches = {s for s in api.requested_symbols if "," in s}
        assert probed_batches == {"S0,S1,S2,S3,S4"}, (
            f"expected batch probing to stop after the first failure, "
            f"got {len(probed_batches)} distinct batches: {sorted(probed_batches)}"
        )


class TestWorkingBatchIsLeftAlone:
    def test_batch_response_is_used_without_per_symbol_requests(self):
        client = _make_client()
        seen = []

        def mock_get(url, params=None, timeout=None):
            params = params or {}
            symbols = params.get("symbol", "") if "/stable/" in url else ""
            seen.append(symbols)
            return _mock_response(200, [_quote_row(s) for s in symbols.split(",")])

        client.session.get = mock_get
        result = client.get_batch_quotes(["AAPL", "MSFT"])

        assert set(result) == {"AAPL", "MSFT"}
        assert seen == ["AAPL,MSFT"]
