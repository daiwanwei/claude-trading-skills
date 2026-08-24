#!/usr/bin/env python3
"""Binance public market data client for daily VCP analysis.

Uses only keyless endpoints on api.binance.com:
  /api/v3/klines        -> daily OHLCV, 1000 bars per call, request weight 10
  /api/v3/ticker/price  -> latest trade price

Crypto trades 24/7, so there is always an in-progress daily bar. `fetch_daily`
returns closed bars only; callers that need a live price call `fetch_price`.
Mixing the two would let a partial session's volume contaminate the dry-up
ratio and breakout detection.

The `volume` field carries **quote** (USDT) volume, not base-asset volume.
Over a multi-year window base volume is not comparable across price regimes.

Rate limits: 6000 request weight per minute per IP. A 50-symbol full-history
fetch costs roughly 2000.
"""

from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone

try:
    import requests
except ImportError:  # pragma: no cover - exercised only without requests
    requests = None

BINANCE_BASE = "https://api.binance.com"
KLINES_URL = f"{BINANCE_BASE}/api/v3/klines"
TICKER_PRICE_URL = f"{BINANCE_BASE}/api/v3/ticker/price"

DAY_MS = 86_400_000
PAGE_LIMIT = 1000
MAX_RETRIES = 4
BACKOFF_BASE_S = 5
REQUEST_DELAY_S = 0.15

_SYMBOL_RE = re.compile(r"^[A-Z0-9]{4,24}$")


def sanitize_symbol(symbol: str) -> str:
    """Validate an exchange symbol. Raises ValueError on anything path-unsafe."""
    sym = (symbol or "").upper().strip()
    if not _SYMBOL_RE.match(sym):
        raise ValueError(f"Invalid Binance symbol: {symbol!r}. Must match {_SYMBOL_RE.pattern}")
    return sym


def kline_to_bar(raw: list) -> dict:
    """Map one Binance kline row to the OHLCV shape the VCP calculators expect."""
    return {
        "date": datetime.fromtimestamp(raw[0] / 1000, timezone.utc).strftime("%Y-%m-%d"),
        "open": float(raw[1]),
        "high": float(raw[2]),
        "low": float(raw[3]),
        "close": float(raw[4]),
        "volume": float(raw[7]),  # quote (USDT) volume -- the equity dollar-volume analog
        "baseVolume": float(raw[5]),
        "trades": int(raw[8]),
        "closeTime": int(raw[6]),
    }


class BinanceClient:
    """Fetch and cache daily klines."""

    def __init__(self, cache_dir: str, quiet: bool = False):
        self.cache_dir = cache_dir
        self.quiet = quiet
        os.makedirs(cache_dir, exist_ok=True)

    def _log(self, message: str) -> None:
        if not self.quiet:
            print(message)

    def _cache_path(self, symbol: str) -> str:
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return os.path.join(self.cache_dir, f"{day}_{symbol}_1d.json")

    def _get(self, url: str, params: dict):
        """GET with 429-aware exponential backoff."""
        if requests is None:
            raise RuntimeError("The 'requests' library is required for live fetches")
        for attempt in range(MAX_RETRIES):
            resp = requests.get(url, params=params, timeout=30)
            if resp.status_code != 429:
                resp.raise_for_status()
                return resp.json()
            delay = float(resp.headers.get("Retry-After") or BACKOFF_BASE_S * (2**attempt))
            self._log(f"  rate limited, sleeping {delay:.0f}s")
            time.sleep(delay)
        raise RuntimeError(f"Binance rate limit not cleared after {MAX_RETRIES} attempts")

    def fetch_daily(self, symbol: str, now_ms: int | None = None) -> list[dict]:
        """Return every closed daily bar for `symbol`, most-recent-first."""
        sym = sanitize_symbol(symbol)
        cache_path = self._cache_path(sym)
        if os.path.exists(cache_path):
            with open(cache_path) as handle:
                return json.load(handle)

        now = now_ms if now_ms is not None else int(time.time() * 1000)
        raw_rows: list = []
        start = 0
        while True:
            page = self._get(
                KLINES_URL,
                {"symbol": sym, "interval": "1d", "startTime": start, "limit": PAGE_LIMIT},
            )
            if not page:
                break
            raw_rows.extend(page)
            if len(page) < PAGE_LIMIT:
                break
            start = page[-1][0] + DAY_MS
            time.sleep(REQUEST_DELAY_S)

        bars = [kline_to_bar(row) for row in raw_rows]
        bars = [bar for bar in bars if bar["closeTime"] < now]  # drop the in-progress bar
        bars.reverse()

        with open(cache_path, "w") as handle:
            json.dump(bars, handle)
        return bars

    def fetch_price(self, symbol: str) -> float:
        """Latest trade price -- the live value the in-progress bar would carry."""
        sym = sanitize_symbol(symbol)
        payload = self._get(TICKER_PRICE_URL, {"symbol": sym})
        return float(payload["price"])
