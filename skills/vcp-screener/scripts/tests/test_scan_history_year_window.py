#!/usr/bin/env python3
"""scan_history forwards year_window_bars into quote synthesis."""

import json
from pathlib import Path

import historical_scanner
from historical_scanner import build_quote_from_history, scan_history

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _golden():
    return json.loads((FIXTURES / "golden_equity_input.json").read_text())


def test_build_quote_respects_year_window_bars():
    bars = _golden()["historical"]
    narrow = build_quote_from_history(bars, 0, year_window_bars=60)
    wide = build_quote_from_history(bars, 0, year_window_bars=330)
    assert wide["yearHigh"] >= narrow["yearHigh"]
    assert wide["yearLow"] <= narrow["yearLow"]


def test_scan_history_forwards_year_window_bars(monkeypatch):
    bars = _golden()["historical"]
    seen = []

    real_build = historical_scanner.build_quote_from_history

    def spy(historical, offset, year_window_bars=252):
        seen.append(year_window_bars)
        return real_build(historical, offset, year_window_bars=year_window_bars)

    monkeypatch.setattr(historical_scanner, "build_quote_from_history", spy)
    scan_history("GOLD", bars, bars, lookback_days=120, year_window_bars=365)

    assert seen, "build_quote_from_history was never called"
    assert set(seen) == {365}
