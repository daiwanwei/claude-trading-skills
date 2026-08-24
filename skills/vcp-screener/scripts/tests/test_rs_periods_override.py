#!/usr/bin/env python3
"""RS periods are injectable, and analyze_stock forwards every new parameter."""

import inspect
import json
from pathlib import Path

import pytest
from calculators.relative_strength_calculator import RS_PERIODS, calculate_relative_strength
from screen_vcp import analyze_stock

FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture
def golden():
    return json.loads((FIXTURES / "golden_equity_input.json").read_text())


def test_rs_periods_default_matches_module_constant(golden):
    implicit = calculate_relative_strength(golden["historical"], golden["benchmark"])
    explicit = calculate_relative_strength(
        golden["historical"], golden["benchmark"], rs_periods=RS_PERIODS
    )
    assert implicit == explicit


def test_calendar_rs_periods_change_the_result(golden):
    """Crypto uses 90/180/270/365 instead of 63/126/189/252."""
    equity = calculate_relative_strength(golden["historical"], golden["benchmark"])
    crypto = calculate_relative_strength(
        golden["historical"],
        golden["benchmark"],
        rs_periods=[(90, 0.40), (180, 0.20), (270, 0.20), (365, 0.20)],
    )
    assert crypto["weighted_rs"] != equity["weighted_rs"]
    assert [d["period_days"] for d in crypto["period_details"]][0] == 90


def test_analyze_stock_accepts_every_new_parameter(golden):
    params = inspect.signature(analyze_stock).parameters
    for name in (
        "right_shoulder_pct",
        "t1_depth_max",
        "pattern_duration_min",
        "pattern_duration_max",
        "wide_and_loose_max_duration",
        "min_pct_above_52w_low",
        "max_pct_below_52w_high",
        "min_rs_rank",
        "rs_periods",
    ):
        assert name in params, f"analyze_stock is missing {name}"


def test_analyze_stock_forwards_trend_overrides(golden):
    """A crypto-style relaxed c6 must actually reach the trend template."""
    quote = dict(golden["quote"])
    quote["yearHigh"] = quote["price"] / 0.60

    strict = analyze_stock("X", golden["historical"], quote, golden["benchmark"])
    relaxed = analyze_stock(
        "X", golden["historical"], quote, golden["benchmark"], max_pct_below_52w_high=50.0
    )

    assert strict["trend_template"]["criteria"]["c6_within_25pct_52w_high"]["passed"] is False
    assert relaxed["trend_template"]["criteria"]["c6_within_25pct_52w_high"]["passed"] is True
