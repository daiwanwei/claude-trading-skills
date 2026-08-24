#!/usr/bin/env python3
"""Calibration statistics, the n>=30 usability gate, and CLI argument handling."""

import json
from pathlib import Path

import calibrate_crypto_vcp as cal
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


def _band_record(outcome_type, gain, loss, pre_resolved, band_position=None):
    record = _record(outcome_type, gain, loss)
    record["pre_resolved"] = pre_resolved
    record["band_position"] = band_position
    return record


def test_compare_inside_band_excludes_pre_resolved_records():
    """The inside-band arm must drop records whose close already sat outside
    [stop, pivot] at detection — the confound `compare` exists to isolate."""
    treatment = [
        _band_record("breakout", 10.0, -2.0, pre_resolved=False, band_position=0.5)
    ] * 5 + [_band_record("breakout", 10.0, -2.0, pre_resolved=True, band_position=1.5)] * 20
    control = [_band_record("stop_hit", 1.0, -8.0, pre_resolved=False, band_position=0.3)] * 5
    result = compare(treatment, control)
    assert result["inside_band"]["treatment"]["n"] == 5
    assert result["inside_band"]["control"]["n"] == 5
    assert result["inside_band"]["treatment"]["breakout_rate"] == pytest.approx(1.0)
    assert result["inside_band_breakout_rate_gap"] == pytest.approx(1.0)
    # The raw (unfiltered) arms must still be reported unchanged alongside it.
    assert result["treatment"]["n"] == 25
    assert result["control"]["n"] == 5


def test_inside_band_usable_gate_is_independent_of_raw_gate():
    """A candidate can clear the raw n>=MIN_SAMPLES gate while its inside-band
    subset does not — the two usability flags must not be conflated."""
    treatment = [
        _band_record("breakout", 10.0, -2.0, pre_resolved=False, band_position=0.5)
    ] * 10 + [_band_record("breakout", 10.0, -2.0, pre_resolved=True, band_position=1.5)] * 25
    control = [_band_record("stop_hit", 1.0, -8.0, pre_resolved=False, band_position=0.3)] * 50
    result = compare(treatment, control)
    assert result["usable"] is True  # raw n = 35 >= MIN_SAMPLES
    assert result["inside_band_usable"] is False  # inside-band n = 10 < MIN_SAMPLES


def test_band_geometry_reports_median_position_and_pre_resolved_share():
    treatment = [
        _band_record("breakout", 10.0, -2.0, pre_resolved=False, band_position=0.2),
        _band_record("breakout", 10.0, -2.0, pre_resolved=False, band_position=0.4),
        _band_record("breakout", 10.0, -2.0, pre_resolved=True, band_position=1.5),
        _band_record("breakout", 10.0, -2.0, pre_resolved=True, band_position=-0.5),
    ]
    result = compare(treatment, [])
    stats = result["band_geometry"]["treatment"]
    assert stats["median_band_position"] == pytest.approx(0.3)
    assert stats["pre_resolved_share"] == pytest.approx(0.5)


def test_band_geometry_handles_missing_fields_as_none():
    """Records predating this instrumentation (no band_position/pre_resolved
    keys) must not crash the geometry stats — they're simply excluded."""
    treatment = [_record("breakout", 10.0, -2.0)] * 5
    result = compare(treatment, [])
    stats = result["band_geometry"]["treatment"]
    assert stats["median_band_position"] is None
    assert stats["pre_resolved_share"] is None


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


class _FakeClient:
    """Stands in for BinanceClient: no network, fixed short history."""

    def __init__(self, cache_dir, quiet=False):
        pass

    def fetch_daily(self, symbol, now_ms=None):
        return [
            {
                "date": f"2024-01-{i + 1:02d}",
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.0 + i,
                "volume": 1000.0,
            }
            for i in reversed(range(5))
        ]


def test_main_threads_candidate_lookback_days_into_scan_with_controls(monkeypatch, tmp_path):
    """Regression guard for the lookback pop-then-pass: main() must hand
    scan_with_controls the candidate's own lookback_days (crypto-loose sets
    180, not the 120 default) as the explicit keyword, and analyzer_kwargs
    must no longer carry the key. Asserting merely that main() 'does not
    raise' would be weaker than it looks — it would also pass if both values
    were wrongly 120, since scan_with_controls only raises on a *conflict*,
    not on a wrong-but-matching pair."""
    captured_calls = []

    def fake_scan_with_controls(symbol, historical, benchmark, **kwargs):
        captured_calls.append(kwargs)
        return {"treatment": [], "control": []}

    monkeypatch.setattr(cal, "BinanceClient", _FakeClient)
    monkeypatch.setattr(cal, "scan_with_controls", fake_scan_with_controls)
    monkeypatch.setattr(
        cal, "load_universe", lambda path=None: {"frozen_on": "2026-08-24", "symbols": ["AAAUSDT"]}
    )
    monkeypatch.setattr(cal, "universe_symbols", lambda manifest: list(manifest["symbols"]))

    rc = cal.main(
        [
            "--candidates",
            "crypto-loose",
            "--limit",
            "1",
            "--output-dir",
            str(tmp_path),
            "--cache-dir",
            str(tmp_path),
            "--quiet",
        ]
    )

    assert rc == 0
    assert len(captured_calls) == 1
    kwargs = captured_calls[0]
    assert kwargs["lookback_days"] == 180, "crypto-loose's configured lookback, not the 120 default"
    assert "lookback_days" not in kwargs["analyzer_kwargs"]


def test_main_isolates_a_per_symbol_scan_failure_and_records_it_in_the_json(monkeypatch, tmp_path):
    """A bad symbol must not abort the candidate, and the failure must be
    readable in the artifact a human actually opens — the written JSON, not
    just in-memory state."""
    good_record = {
        "forward_outcome": {"outcome_type": "breakout", "max_gain_pct": 10.0, "max_loss_pct": -2.0}
    }

    def fake_scan_with_controls(symbol, historical, benchmark, **kwargs):
        if symbol == "BADUSDT":
            raise RuntimeError("simulated cursor failure")
        return {"treatment": [good_record], "control": []}

    monkeypatch.setattr(cal, "BinanceClient", _FakeClient)
    monkeypatch.setattr(cal, "scan_with_controls", fake_scan_with_controls)
    monkeypatch.setattr(
        cal,
        "load_universe",
        lambda path=None: {"frozen_on": "2026-08-24", "symbols": ["GOODUSDT", "BADUSDT"]},
    )
    monkeypatch.setattr(cal, "universe_symbols", lambda manifest: list(manifest["symbols"]))

    rc = cal.main(
        [
            "--candidates",
            "crypto-loose",
            "--output-dir",
            str(tmp_path),
            "--cache-dir",
            str(tmp_path),
            "--quiet",
        ]
    )

    assert rc == 0

    out_files = list(Path(tmp_path).glob("crypto_vcp_calibration_*.json"))
    assert len(out_files) == 1
    payload = json.loads(out_files[0].read_text())

    candidate = payload["candidates"]["crypto-loose"]
    assert candidate["failed_symbols"] == ["BADUSDT"]
    assert candidate["treatment"]["n"] == 1, "GOODUSDT's record must still make it into the arm"
