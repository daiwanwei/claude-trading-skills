#!/usr/bin/env python3
"""The crypto parameter profile is well-formed and matches analyze_stock's signature."""

import inspect
import sys
from pathlib import Path

import pytest
from crypto_profile import (
    CANDIDATES,
    EQUITY_BASELINE,
    RS_PERIODS_CALENDAR,
    YEAR_WINDOW_BARS,
    analyzer_kwargs,
)

VCP_SCRIPTS = Path(__file__).resolve().parents[3] / "vcp-screener" / "scripts"
sys.path.insert(0, str(VCP_SCRIPTS))
from screen_vcp import analyze_stock  # noqa: E402


def test_candidate_count_is_bounded():
    """Spec: 6-12 pre-specified candidates, no broad grid search."""
    assert 6 <= len(CANDIDATES) <= 12


def test_equity_baseline_is_a_candidate():
    assert "equity-baseline" in CANDIDATES
    assert CANDIDATES["equity-baseline"] == EQUITY_BASELINE


def test_every_candidate_key_is_a_real_analyze_stock_parameter():
    """A typo here would be silently ignored as an unused dict key."""
    valid = set(inspect.signature(analyze_stock).parameters)
    for name, params in CANDIDATES.items():
        for key in params:
            assert key in valid, f"candidate {name!r} has unknown parameter {key!r}"


def test_rs_periods_use_calendar_spans():
    """Spec 2e: RS uses 90/180/270/365, not the equity 63/126/189/252."""
    assert [period for period, _weight in RS_PERIODS_CALENDAR] == [90, 180, 270, 365]
    assert sum(weight for _p, weight in RS_PERIODS_CALENDAR) == pytest.approx(1.0)


def test_year_window_is_365_bars():
    """Spec 2e: '52 weeks' is a calendar span, so 365 bars, not 252."""
    assert YEAR_WINDOW_BARS == 365


def test_analyzer_kwargs_injects_calendar_rs_for_crypto_candidates():
    kwargs = analyzer_kwargs("crypto-moderate")
    assert kwargs["rs_periods"] == RS_PERIODS_CALENDAR


def test_analyzer_kwargs_injects_calendar_rs_for_every_crypto_candidate():
    """Stronger than the single-candidate check above: a fix that special-cases
    'crypto-moderate' (or that injects rs_periods for only a subset of the seven
    crypto candidates) would still pass test_analyzer_kwargs_injects_calendar_rs_
    for_crypto_candidates. Looping over every non-baseline candidate closes that
    gap.
    """
    for name in CANDIDATES:
        if name == "equity-baseline":
            continue
        kwargs = analyzer_kwargs(name)
        assert kwargs["rs_periods"] == RS_PERIODS_CALENDAR, (
            f"candidate {name!r} missing calendar rs_periods"
        )


def test_analyzer_kwargs_does_not_inject_rs_periods_for_equity_baseline():
    """The equity control arm must keep analyze_stock's own trading-day default
    (63/126/189/252). A bug that injects RS_PERIODS_CALENDAR unconditionally would
    pass test_analyzer_kwargs_injects_calendar_rs_for_crypto_candidates (it only
    checks a crypto candidate) but would corrupt the control arm of the sweep.
    """
    kwargs = analyzer_kwargs("equity-baseline")
    assert "rs_periods" not in kwargs


def test_analyzer_kwargs_rejects_unknown_candidate():
    with pytest.raises(KeyError):
        analyzer_kwargs("does-not-exist")


def test_crypto_candidates_relax_c6():
    """All four monitor symbols sit 39-63% below their 52w high; 25% gates everything out."""
    for name, params in CANDIDATES.items():
        if name == "equity-baseline":
            continue
        assert params["max_pct_below_52w_high"] >= 40.0


def test_crypto_candidates_relax_c6_to_measured_drawdown_ceiling():
    """The >= 40.0 check above is satisfied by any value from 40 to 100 and would
    not catch a threshold that is technically "relaxed" but still far short of
    what the measured drawdowns require. The design spec measured BTC -38.8%,
    ETH -49.2%, SOL -62.8%, BNB -49.4% below their 52-week highs — a threshold
    much below ~60 would still gate out ETH/SOL/BNB. Pin the actual relaxed value
    so a regression toward the weak end of the >=40 range is caught.
    """
    for name, params in CANDIDATES.items():
        if name == "equity-baseline":
            continue
        assert params["max_pct_below_52w_high"] == 60.0, (
            f"candidate {name!r} drifted from the measured-ceiling threshold"
        )
