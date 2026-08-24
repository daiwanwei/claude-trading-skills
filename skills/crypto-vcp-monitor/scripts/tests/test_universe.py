#!/usr/bin/env python3
"""The calibration universe is frozen, well-formed, and keeps delisted names."""

from pathlib import Path

import pytest
from universe import MONITOR_SYMBOLS, load_universe, universe_symbols

REFERENCES = Path(__file__).resolve().parents[2] / "references"


def test_frozen_manifest_is_committed():
    assert (REFERENCES / "calibration_universe.json").is_file()


def test_manifest_has_provenance():
    manifest = load_universe()
    assert manifest["frozen_on"]
    assert manifest["criteria"]["quote_asset"] == "USDT"
    assert manifest["criteria"]["min_bars"] >= 800


def test_universe_is_large_enough_for_calibration():
    symbols = universe_symbols(load_universe())
    assert len(symbols) >= 30, "spec requires a 30-50 symbol calibration universe"
    assert len(symbols) == len(set(symbols)), "duplicate symbols"


def test_delisted_symbols_are_retained():
    """Survivorship-bias guard: removing these silently would bias the backtest."""
    manifest = load_universe()
    delisted = manifest["delisted_manually_added"]
    assert delisted, "at least one delisted name must be carried"
    for symbol in delisted:
        assert symbol in manifest["symbols"]


def test_no_stablecoin_or_leveraged_pairs():
    for symbol in universe_symbols(load_universe()):
        base = symbol[:-4]
        assert base not in {"USDC", "FDUSD", "TUSD", "USD1", "DAI", "BUSD"}
        assert not base.endswith(("UP", "DOWN", "BULL", "BEAR"))


def test_monitor_symbols_are_inside_the_universe():
    symbols = set(universe_symbols(load_universe()))
    for symbol in MONITOR_SYMBOLS:
        assert symbol in symbols


def test_load_universe_rejects_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_universe(str(tmp_path / "nope.json"))
