#!/usr/bin/env python3
"""Load the frozen calibration universe.

The symbol list is committed rather than derived at run time. Deriving it from
live exchangeInfo would reconstruct the historical universe out of today's
survivors — MATICUSDT delisted on 2024-09-10 yet Binance still serves its full
history, so an exchange query would silently drop it and bias every result.
"""

from __future__ import annotations

import json
import os

# The four names the monitor watches. Kept inside the calibration universe so
# calibrated thresholds are not extrapolated onto unseen symbols.
MONITOR_SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]

_DEFAULT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "references",
    "calibration_universe.json",
)


def load_universe(path: str | None = None) -> dict:
    """Return the frozen universe manifest. Raises FileNotFoundError if absent."""
    target = path or _DEFAULT_PATH
    if not os.path.isfile(target):
        raise FileNotFoundError(f"Frozen calibration universe not found: {target}")
    with open(target) as handle:
        return json.load(handle)


def universe_symbols(manifest: dict) -> list[str]:
    """Return the symbol list, order preserved."""
    return list(manifest["symbols"])
