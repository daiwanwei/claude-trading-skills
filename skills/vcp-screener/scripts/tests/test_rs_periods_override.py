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


def test_empty_rs_periods_list_is_honored_not_treated_as_default(golden):
    """rs_periods=[] is an explicit (if degenerate) request, distinct from
    rs_periods=None. An empty list must not be silently swapped for RS_PERIODS
    -- it should flow through to the "no periods overlapped" error path."""
    result = calculate_relative_strength(golden["historical"], golden["benchmark"], rs_periods=[])
    assert result["weighted_rs"] is None
    assert result["error"] == "Unable to calculate weighted RS (insufficient overlapping data)"


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


# ---------------------------------------------------------------------------
# Per-parameter forwarding tests: each calls analyze_stock (not the calculator
# directly) with a default and an overridden value on the golden fixture, and
# asserts an observable difference in analyze_stock's *returned result*. If
# analyze_stock silently dropped the parameter before it reached its
# calculator, the override call would behave identically to the default call
# and these assertions would fail. See task-4-report.md for the mutation
# check that confirms each test actually does fail when its forwarding line
# is removed.
# ---------------------------------------------------------------------------


def test_analyze_stock_forwards_right_shoulder_pct(golden):
    """A tight right-shoulder tolerance breaks contraction-building early on
    the golden bars, dropping the pattern from 3 contractions (valid) to 1
    (invalid)."""
    default = analyze_stock("X", golden["historical"], golden["quote"], golden["benchmark"])
    tightened = analyze_stock(
        "X", golden["historical"], golden["quote"], golden["benchmark"], right_shoulder_pct=0.5
    )

    assert default["vcp_pattern"]["valid_vcp"] is True
    assert tightened["vcp_pattern"]["valid_vcp"] is False
    assert tightened["vcp_pattern"]["num_contractions"] < default["vcp_pattern"]["num_contractions"]


def test_analyze_stock_forwards_t1_depth_max(golden):
    """The golden fixture's T1 depth is 21.95%. Lowering the cap below that
    must surface a 'too deep' issue that the default (35.0) does not."""
    default = analyze_stock("X", golden["historical"], golden["quote"], golden["benchmark"])
    strict = analyze_stock(
        "X", golden["historical"], golden["quote"], golden["benchmark"], t1_depth_max=15.0
    )

    default_issues = default["vcp_pattern"]["validation"]["issues"]
    strict_issues = strict["vcp_pattern"]["validation"]["issues"]
    assert not any("too deep" in issue for issue in default_issues)
    assert any("too deep" in issue for issue in strict_issues)


def test_analyze_stock_forwards_pattern_duration_min(golden):
    """The golden fixture's pattern spans 73 days. Raising the floor above
    that must invalidate the pattern; the default (15) does not."""
    default = analyze_stock("X", golden["historical"], golden["quote"], golden["benchmark"])
    strict = analyze_stock(
        "X", golden["historical"], golden["quote"], golden["benchmark"], pattern_duration_min=100
    )

    assert default["vcp_pattern"]["valid_vcp"] is True
    assert strict["vcp_pattern"]["valid_vcp"] is False
    assert any("too short" in issue for issue in strict["vcp_pattern"]["validation"]["issues"])


def test_analyze_stock_forwards_pattern_duration_max(golden):
    """The golden fixture's pattern spans 73 days. Lowering the ceiling below
    that must surface a 'too long' issue (non-invalidating); the default
    (325) does not."""
    default = analyze_stock("X", golden["historical"], golden["quote"], golden["benchmark"])
    strict = analyze_stock(
        "X", golden["historical"], golden["quote"], golden["benchmark"], pattern_duration_max=50
    )

    default_issues = default["vcp_pattern"]["validation"]["issues"]
    strict_issues = strict["vcp_pattern"]["validation"]["issues"]
    assert not any("too long" in issue for issue in default_issues)
    assert any("too long" in issue for issue in strict_issues)


def test_analyze_stock_forwards_wide_and_loose_max_duration(golden):
    """The golden fixture's final contraction is 6.47% deep over 9 days.
    Holding wide_and_loose_threshold=5.0 fixed (so depth clears the depth
    leg) isolates wide_and_loose_max_duration: default (10) flags the 9-day
    final leg as wide-and-loose; tightening the duration cap to 5 does not."""
    base = analyze_stock(
        "X",
        golden["historical"],
        golden["quote"],
        golden["benchmark"],
        wide_and_loose_threshold=5.0,
    )
    tightened = analyze_stock(
        "X",
        golden["historical"],
        golden["quote"],
        golden["benchmark"],
        wide_and_loose_threshold=5.0,
        wide_and_loose_max_duration=5,
    )

    assert base["vcp_pattern"]["wide_and_loose"] is True
    assert tightened["vcp_pattern"]["wide_and_loose"] is False


def test_analyze_stock_forwards_min_pct_above_52w_low(golden):
    """The golden fixture's price sits 46.0% above its 52-week low, clearing
    the default 25% floor for c5. Raising the floor above 46.0% must flip c5
    to failing."""
    default = analyze_stock("X", golden["historical"], golden["quote"], golden["benchmark"])
    strict = analyze_stock(
        "X",
        golden["historical"],
        golden["quote"],
        golden["benchmark"],
        min_pct_above_52w_low=50.0,
    )

    assert default["trend_template"]["criteria"]["c5_25pct_above_52w_low"]["passed"] is True
    assert strict["trend_template"]["criteria"]["c5_25pct_above_52w_low"]["passed"] is False


def test_analyze_stock_forwards_min_rs_rank(golden):
    """The golden fixture's RS rank estimate is 80, clearing the default
    exclusive floor of 70 for c7. Raising the floor above 80 must flip c7 to
    failing."""
    default = analyze_stock("X", golden["historical"], golden["quote"], golden["benchmark"])
    strict = analyze_stock(
        "X", golden["historical"], golden["quote"], golden["benchmark"], min_rs_rank=85
    )

    assert default["relative_strength"]["rs_rank_estimate"] == 80
    assert default["trend_template"]["criteria"]["c7_rs_rank_above_70"]["passed"] is True
    assert strict["trend_template"]["criteria"]["c7_rs_rank_above_70"]["passed"] is False


def test_analyze_stock_forwards_rs_periods(golden):
    """Crypto-style calendar periods must reach calculate_relative_strength
    through analyze_stock, not just when called directly."""
    default = analyze_stock("X", golden["historical"], golden["quote"], golden["benchmark"])
    crypto = analyze_stock(
        "X",
        golden["historical"],
        golden["quote"],
        golden["benchmark"],
        rs_periods=[(90, 0.40), (180, 0.20), (270, 0.20), (365, 0.20)],
    )

    default_period_days = [d["period_days"] for d in default["relative_strength"]["period_details"]]
    crypto_period_days = [d["period_days"] for d in crypto["relative_strength"]["period_details"]]
    assert default_period_days[0] == 63
    assert crypto_period_days[0] == 90
    assert crypto["relative_strength"]["weighted_rs"] != default["relative_strength"]["weighted_rs"]
