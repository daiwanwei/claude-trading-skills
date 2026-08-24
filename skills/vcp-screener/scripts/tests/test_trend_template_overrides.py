#!/usr/bin/env python3
"""Trend-template criteria 5, 6, and 7 accept overridden thresholds."""

import json
from pathlib import Path

import pytest
from calculators.trend_template_calculator import calculate_trend_template

FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture
def golden():
    return json.loads((FIXTURES / "golden_equity_input.json").read_text())


def test_c6_threshold_is_overridable(golden):
    """A name 40% below its 52w high fails at 25% and passes at 50%."""
    quote = dict(golden["quote"])
    quote["yearHigh"] = quote["price"] / 0.60  # price sits 40% below the high

    strict = calculate_trend_template(golden["historical"], quote, rs_rank=80)
    assert strict["criteria"]["c6_within_25pct_52w_high"]["passed"] is False

    relaxed = calculate_trend_template(
        golden["historical"], quote, rs_rank=80, max_pct_below_52w_high=50.0
    )
    assert relaxed["criteria"]["c6_within_25pct_52w_high"]["passed"] is True


def test_c5_threshold_is_overridable(golden):
    """A name only 10% above its 52w low fails at 25% and passes at 5%."""
    quote = dict(golden["quote"])
    quote["yearLow"] = quote["price"] / 1.10

    strict = calculate_trend_template(golden["historical"], quote, rs_rank=80)
    assert strict["criteria"]["c5_25pct_above_52w_low"]["passed"] is False

    relaxed = calculate_trend_template(
        golden["historical"], quote, rs_rank=80, min_pct_above_52w_low=5.0
    )
    assert relaxed["criteria"]["c5_25pct_above_52w_low"]["passed"] is True


def test_c7_rs_gate_is_overridable(golden):
    strict = calculate_trend_template(golden["historical"], golden["quote"], rs_rank=60)
    assert strict["criteria"]["c7_rs_rank_above_70"]["passed"] is False

    relaxed = calculate_trend_template(
        golden["historical"], golden["quote"], rs_rank=60, min_rs_rank=50
    )
    assert relaxed["criteria"]["c7_rs_rank_above_70"]["passed"] is True


def test_criteria_keys_are_stable(golden):
    """Report generator and the golden fixture depend on these literal keys."""
    result = calculate_trend_template(
        golden["historical"],
        golden["quote"],
        rs_rank=80,
        min_pct_above_52w_low=5.0,
        max_pct_below_52w_high=50.0,
        min_rs_rank=50,
    )
    assert "c5_25pct_above_52w_low" in result["criteria"]
    assert "c6_within_25pct_52w_high" in result["criteria"]
    assert "c7_rs_rank_above_70" in result["criteria"]


def test_c5_default_message_has_no_decimal(golden):
    """Regression: min_pct_above_52w_low defaults to the float 25.0, but the
    pre-refactor message text interpolated the bare int literal 25 and rendered
    "need >= 25%". An unformatted {min_pct_above_52w_low} would silently change
    that to "need >= 25.0%" for every ticker -- pin the exact rendering."""
    result = calculate_trend_template(golden["historical"], golden["quote"], rs_rank=80)
    detail = result["criteria"]["c5_25pct_above_52w_low"]["detail"]
    assert "need >= 25%" in detail
    assert "25.0%" not in detail


def test_c6_default_message_has_no_decimal(golden):
    """Regression: max_pct_below_52w_high defaults to the float 25.0, but the
    pre-refactor message text interpolated the bare int literal 25 and rendered
    "need <= 25%". An unformatted {max_pct_below_52w_high} would silently change
    that to "need <= 25.0%" for every ticker -- pin the exact rendering."""
    result = calculate_trend_template(golden["historical"], golden["quote"], rs_rank=80)
    detail = result["criteria"]["c6_within_25pct_52w_high"]["detail"]
    assert "need <= 25%" in detail
    assert "25.0%" not in detail


def test_c7_default_message_is_unaffected_by_int_type(golden):
    """min_rs_rank is int-typed (unlike the c5/c6 float thresholds), so the
    default f"{70}" already renders "70" with no decimal -- verify this holds."""
    result = calculate_trend_template(golden["historical"], golden["quote"], rs_rank=60)
    detail = result["criteria"]["c7_rs_rank_above_70"]["detail"]
    assert "need > 70" in detail
    assert "70.0" not in detail
