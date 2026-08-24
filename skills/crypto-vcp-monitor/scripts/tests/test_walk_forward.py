#!/usr/bin/env python3
"""Walk-forward scan collects treatment and control arms with comparable outcomes."""

import json
from pathlib import Path

import pytest
from walk_forward import load_vcp_module, scan_with_controls

GOLDEN = (
    Path(__file__).resolve().parents[3]
    / "vcp-screener"
    / "scripts"
    / "tests"
    / "fixtures"
    / "golden_equity_input.json"
)


@pytest.fixture
def bars():
    return json.loads(GOLDEN.read_text())["historical"]


def test_load_vcp_module_finds_the_sibling_skill():
    module = load_vcp_module("historical_scanner")
    assert hasattr(module, "build_quote_from_history")


def test_load_vcp_module_raises_on_unknown_module():
    with pytest.raises(ImportError):
        load_vcp_module("no_such_module_here")


def test_both_arms_have_pivot_and_stop(bars):
    """Outcome rules must be identical across arms, so both need a stop."""
    result = scan_with_controls("GOLD", bars, bars, analyzer_kwargs={}, stride_days=10)
    for arm in ("treatment", "control"):
        for record in result[arm]:
            assert record["pivot_price"] is not None, f"{arm} record without a pivot"
            assert record["stop_price"] is not None, f"{arm} record without a stop"


def test_control_records_have_contractions_but_are_invalid(bars):
    result = scan_with_controls("GOLD", bars, bars, analyzer_kwargs={}, stride_days=10)
    for record in result["control"]:
        assert record["num_contractions"] >= 1
        assert record["valid_vcp"] is False


def test_control_spacing_is_enforced(bars):
    """Without spacing, overlapping forward windows inflate the control arm."""
    spaced = scan_with_controls(
        "GOLD", bars, bars, analyzer_kwargs={}, stride_days=5, control_min_spacing=60
    )
    offsets = sorted(record["as_of_offset"] for record in spaced["control"])
    for earlier, later in zip(offsets, offsets[1:]):
        assert later - earlier >= 60, "control samples closer than the spacing floor"


def test_tighter_spacing_yields_at_least_as_many_controls(bars):
    loose = scan_with_controls(
        "GOLD", bars, bars, analyzer_kwargs={}, stride_days=5, control_min_spacing=60
    )
    tight = scan_with_controls(
        "GOLD", bars, bars, analyzer_kwargs={}, stride_days=5, control_min_spacing=5
    )
    assert len(tight["control"]) >= len(loose["control"])


def test_looser_spacing_strictly_increases_control_count(bars):
    """Strengthens the >= check above: on this fixture spacing=60 admits
    fewer control samples than spacing=5. A `>=` comparison alone would still
    pass if control_min_spacing were ignored entirely (both calls would
    degrade identically and tie); this asserts the strict inequality that
    only holds when the floor actually gates admission."""
    loose = scan_with_controls(
        "GOLD", bars, bars, analyzer_kwargs={}, stride_days=5, control_min_spacing=60
    )
    tight = scan_with_controls(
        "GOLD", bars, bars, analyzer_kwargs={}, stride_days=5, control_min_spacing=5
    )
    assert len(tight["control"]) > len(loose["control"])


def test_treatment_records_are_deduplicated(bars):
    result = scan_with_controls("GOLD", bars, bars, analyzer_kwargs={}, stride_days=5)
    keys = [
        (r["t1_high_date"], r["last_low_date"], round(r["pivot_price"], 2))
        for r in result["treatment"]
    ]
    assert len(keys) == len(set(keys))


def test_short_history_returns_empty_arms():
    result = scan_with_controls("GOLD", [], [], analyzer_kwargs={})
    assert result == {"treatment": [], "control": []}


def test_forward_outcome_is_attached(bars):
    result = scan_with_controls("GOLD", bars, bars, analyzer_kwargs={}, stride_days=10)
    records = result["treatment"] + result["control"]
    assert records, "fixture produced no records at all"
    for record in records:
        assert record["forward_outcome"]["outcome_type"] in {
            "breakout",
            "stop_hit",
            "timeout",
            "insufficient_data",
        }
