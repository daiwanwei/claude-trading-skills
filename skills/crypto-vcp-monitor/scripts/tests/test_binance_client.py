#!/usr/bin/env python3
"""Binance client: kline mapping, paging, partial-bar exclusion, caching.

No test in this file touches the network -- `_get` is always monkeypatched.
"""

import pytest
from binance_client import DAY_MS, BinanceClient, kline_to_bar

# Binance kline layout:
# [openTime, open, high, low, close, baseVolume, closeTime, quoteVolume, trades, ...]
DAY0 = 1_700_000_000_000 - (1_700_000_000_000 % DAY_MS)


def _kline(open_ms, close_px, base_vol=10.0, quote_vol=1000.0):
    return [
        open_ms,
        "1.0",
        "2.0",
        "0.5",
        str(close_px),
        str(base_vol),
        open_ms + DAY_MS - 1,
        str(quote_vol),
        42,
        "0",
        "0",
        "0",
    ]


def test_kline_to_bar_uses_quote_volume():
    bar = kline_to_bar(_kline(DAY0, 3.5, base_vol=7.0, quote_vol=1234.5))
    assert bar["close"] == 3.5
    assert bar["volume"] == 1234.5, "volume must carry quote (USDT) volume"
    assert bar["baseVolume"] == 7.0
    assert bar["trades"] == 42
    assert bar["date"] == "2023-11-14"


def test_fetch_daily_drops_the_in_progress_bar(tmp_path, monkeypatch):
    """The final bar is still open, so it must not appear in the result."""
    client = BinanceClient(cache_dir=str(tmp_path))
    page = [_kline(DAY0, 1.0), _kline(DAY0 + DAY_MS, 2.0), _kline(DAY0 + 2 * DAY_MS, 3.0)]
    monkeypatch.setattr(client, "_get", lambda url, params: page)

    # "Now" falls inside the third bar, so only the first two are closed.
    bars = client.fetch_daily("BTCUSDT", now_ms=DAY0 + 2 * DAY_MS + 1000)

    assert [b["close"] for b in bars] == [2.0, 1.0], "most-recent-first, open bar dropped"


def test_fetch_daily_pages_until_short_page(tmp_path, monkeypatch):
    client = BinanceClient(cache_dir=str(tmp_path))
    full = [_kline(DAY0 + i * DAY_MS, float(i)) for i in range(1000)]
    tail = [_kline(DAY0 + (1000 + i) * DAY_MS, float(1000 + i)) for i in range(5)]
    calls = []

    def fake_get(url, params):
        calls.append(params["startTime"])
        return full if len(calls) == 1 else tail

    monkeypatch.setattr(client, "_get", fake_get)
    bars = client.fetch_daily("BTCUSDT", now_ms=DAY0 + 5000 * DAY_MS)

    assert len(calls) == 2
    assert calls[0] == 0
    assert calls[1] == full[-1][0] + DAY_MS, "cursor advances past the last open time"
    assert len(bars) == 1005


def test_fetch_daily_uses_cache_on_second_call(tmp_path, monkeypatch):
    client = BinanceClient(cache_dir=str(tmp_path))
    calls = []

    def fake_get(url, params):
        calls.append(params)
        return [_kline(DAY0, 1.0), _kline(DAY0 + DAY_MS, 2.0)]

    monkeypatch.setattr(client, "_get", fake_get)
    now = DAY0 + DAY_MS + 1000

    first = client.fetch_daily("BTCUSDT", now_ms=now)
    second = client.fetch_daily("BTCUSDT", now_ms=now)

    assert len(calls) == 1, "second call must be served from cache"
    assert first == second


def test_fetch_daily_rejects_unsafe_symbol(tmp_path):
    client = BinanceClient(cache_dir=str(tmp_path))
    with pytest.raises(ValueError):
        client.fetch_daily("../../etc/passwd")
