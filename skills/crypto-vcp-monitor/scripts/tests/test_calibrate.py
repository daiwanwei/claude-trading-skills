#!/usr/bin/env python3
"""Calibration statistics, the n>=30 usability gate, and CLI argument handling."""

import pytest
from calibrate_crypto_vcp import (
    MIN_SAMPLES,
    buy_and_hold_return,
    compare,
    parse_arguments,
    summarize_arm,
)


def _record(outcome_type, gain, loss):
    return {
        "forward_outcome": {
            "outcome_type": outcome_type,
            "max_gain_pct": gain,
            "max_loss_pct": loss,
        }
    }


def test_summarize_empty_arm_reports_none_not_zero():
    """A 0% breakout rate and 'no data' are different claims."""
    summary = summarize_arm([])
    assert summary["n"] == 0
    assert summary["breakout_rate"] is None
    assert summary["median_max_gain_pct"] is None


def test_summarize_computes_rates_and_medians():
    records = [
        _record("breakout", 12.0, -3.0),
        _record("breakout", 20.0, -5.0),
        _record("stop_hit", 2.0, -9.0),
        _record("timeout", 4.0, -4.0),
    ]
    summary = summarize_arm(records)
    assert summary["n"] == 4
    assert summary["breakout_rate"] == pytest.approx(0.5)
    assert summary["stop_rate"] == pytest.approx(0.25)
    assert summary["timeout_rate"] == pytest.approx(0.25)
    assert summary["median_max_gain_pct"] == pytest.approx(8.0)


def test_summarize_ignores_insufficient_data_records():
    records = [_record("breakout", 10.0, -2.0), _record("insufficient_data", None, None)]
    summary = summarize_arm(records)
    assert summary["n"] == 1
    assert summary["breakout_rate"] == pytest.approx(1.0)


def test_compare_marks_small_samples_unusable():
    """Spec: any candidate with n < 30 yields no conclusion."""
    treatment = [_record("breakout", 10.0, -2.0)] * (MIN_SAMPLES - 1)
    control = [_record("stop_hit", 1.0, -8.0)] * 50
    result = compare(treatment, control)
    assert result["usable"] is False


def test_compare_marks_exactly_min_samples_usable():
    """Pins the boundary itself: n == MIN_SAMPLES must clear the gate, not
    just n < MIN_SAMPLES failing it. A '>' instead of '>=' gate would pass
    the n=MIN_SAMPLES-1 test above but fail this one."""
    treatment = [_record("breakout", 10.0, -2.0)] * MIN_SAMPLES
    control = [_record("stop_hit", 1.0, -8.0)] * 50
    result = compare(treatment, control)
    assert result["usable"] is True


def test_compare_marks_large_samples_usable_and_reports_the_gap():
    treatment = [_record("breakout", 10.0, -2.0)] * 40
    control = [_record("breakout", 5.0, -4.0)] * 10 + [_record("stop_hit", 1.0, -8.0)] * 30
    result = compare(treatment, control)
    assert result["usable"] is True
    assert result["treatment"]["breakout_rate"] == pytest.approx(1.0)
    assert result["control"]["breakout_rate"] == pytest.approx(0.25)
    assert result["breakout_rate_gap"] == pytest.approx(0.75)


def test_compare_gap_is_none_when_either_arm_is_empty():
    result = compare([], [_record("breakout", 5.0, -4.0)] * 10)
    assert result["breakout_rate_gap"] is None


def test_buy_and_hold_return_uses_the_forward_window():
    bars = [
        {"date": "2024-03-01", "close": 120.0},
        {"date": "2024-02-01", "close": 110.0},
        {"date": "2024-01-01", "close": 100.0},
    ]
    assert buy_and_hold_return(bars, outcome_days=2) == pytest.approx(20.0)


def test_buy_and_hold_returns_none_for_short_history():
    assert buy_and_hold_return([{"date": "2024-01-01", "close": 100.0}], 60) is None


def test_cli_defaults():
    args = parse_arguments([])
    assert args.output_dir == "reports/crypto_vcp_calibration/"
    assert args.stride_days == 5
    assert args.outcome_days == 60
    assert args.control_min_spacing == 60


def test_cli_rejects_bad_stride():
    with pytest.raises(SystemExit):
        parse_arguments(["--stride-days", "0"])
