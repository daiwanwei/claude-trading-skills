#!/usr/bin/env python3
"""Overriding the newly parameterized VCP thresholds changes behavior as expected."""

import json
from pathlib import Path

import pytest
from calculators.vcp_pattern_calculator import (
    _compute_wide_and_loose,
    _validate_vcp,
    calculate_vcp_pattern,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture
def golden_bars():
    return json.loads((FIXTURES / "golden_equity_input.json").read_text())["historical"]


def _contractions(depths):
    """Build a minimal contraction list with the given depths."""
    out = []
    for i, depth in enumerate(depths):
        out.append(
            {
                "label": f"T{i + 1}",
                "depth_pct": depth,
                "duration_days": 20,
                "high_idx": i * 30,
                "low_idx": i * 30 + 20,
                "high_price": 100.0,
                "low_price": 100.0 - depth,
            }
        )
    return out


def test_t1_depth_max_is_overridable():
    """Default flags T1 > 35% as too deep; raising the cap removes that issue."""
    contractions = _contractions([40.0, 10.0])

    default = _validate_vcp(contractions, total_days=300)
    assert any("too deep" in issue for issue in default["issues"])

    relaxed = _validate_vcp(contractions, total_days=300, t1_depth_max=60.0)
    assert not any("too deep" in issue for issue in relaxed["issues"])


def test_pattern_duration_bounds_are_overridable():
    """A 10-bar pattern is invalid by default and valid when the floor is lowered."""
    contractions = _contractions([20.0, 10.0])
    contractions[-1]["low_idx"] = contractions[0]["high_idx"] + 10

    default = _validate_vcp(contractions, total_days=300, t1_depth_min=8.0)
    assert default["valid"] is False
    assert any("too short" in issue for issue in default["issues"])

    relaxed = _validate_vcp(contractions, total_days=300, t1_depth_min=8.0, pattern_duration_min=5)
    assert not any("too short" in issue for issue in relaxed["issues"])


def test_pattern_duration_max_is_overridable():
    contractions = _contractions([20.0, 10.0])
    contractions[-1]["low_idx"] = contractions[0]["high_idx"] + 400

    default = _validate_vcp(contractions, total_days=500, t1_depth_min=8.0)
    assert any("too long" in issue for issue in default["issues"])

    relaxed = _validate_vcp(
        contractions, total_days=500, t1_depth_min=8.0, pattern_duration_max=500
    )
    assert not any("too long" in issue for issue in relaxed["issues"])


def test_wide_and_loose_max_duration_is_overridable():
    contractions = _contractions([20.0, 18.0])
    contractions[-1]["duration_days"] = 12

    assert _compute_wide_and_loose(contractions, threshold=15.0) is False
    assert _compute_wide_and_loose(contractions, threshold=15.0, max_duration=20) is True


def test_right_shoulder_pct_widens_contraction_search(golden_bars):
    """A wider right-shoulder tolerance may admit at least as many contractions."""
    tight = calculate_vcp_pattern(golden_bars, right_shoulder_pct=5.0)
    wide = calculate_vcp_pattern(golden_bars, right_shoulder_pct=30.0)
    assert wide["num_contractions"] >= tight["num_contractions"]


def test_defaults_match_previous_constants(golden_bars):
    """Explicitly passing the old constants must equal calling with no overrides."""
    implicit = calculate_vcp_pattern(golden_bars)
    explicit = calculate_vcp_pattern(
        golden_bars,
        right_shoulder_pct=5.0,
        t1_depth_max=35.0,
        pattern_duration_min=15,
        pattern_duration_max=325,
        wide_and_loose_max_duration=10,
    )
    assert implicit == explicit
