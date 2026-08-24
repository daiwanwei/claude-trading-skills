#!/usr/bin/env python3
"""The calibration pipeline is deterministic: same bars in, same numbers out.

No network. The fixture is the vcp-screener golden input reshaped into a
two-symbol universe, so this test also fails loudly if the shared calculators
change behavior underneath us.
"""

import json
from pathlib import Path

from benchmark import align_to, build_equal_weight_index
from calibrate_crypto_vcp import compare
from crypto_profile import YEAR_WINDOW_BARS, analyzer_kwargs
from walk_forward import scan_with_controls

GOLDEN = (
    Path(__file__).resolve().parents[3]
    / "vcp-screener"
    / "scripts"
    / "tests"
    / "fixtures"
    / "golden_equity_input.json"
)


def _universe():
    bars = json.loads(GOLDEN.read_text())["historical"]
    # A second, offset series so the equal-weight index has two components and
    # the date-alignment path is genuinely exercised.
    shifted = [
        dict(
            bar,
            close=bar["close"] * 0.5,
            high=bar["high"] * 0.5,
            low=bar["low"] * 0.5,
            open=bar["open"] * 0.5,
        )
        for bar in bars[:-40]
    ]
    return {"AAAUSDT": bars, "BBBUSDT": shifted}


def _run(candidate="crypto-moderate"):
    histories = _universe()
    index = build_equal_weight_index(histories)
    kwargs = analyzer_kwargs(candidate)
    lookback = kwargs.pop("lookback_days", 120)

    treatment, control = [], []
    for symbol, bars in histories.items():
        arms = scan_with_controls(
            symbol,
            bars,
            align_to(index, bars),
            analyzer_kwargs=kwargs,
            stride_days=5,
            outcome_days=60,
            lookback_days=lookback,
            year_window_bars=YEAR_WINDOW_BARS,
            control_min_spacing=60,
        )
        treatment.extend(arms["treatment"])
        control.extend(arms["control"])
    return compare(treatment, control)


def test_pipeline_is_deterministic():
    first, second = _run(), _run()
    assert first == second
    # Two identical *empty* runs would also satisfy equality, which would
    # defeat the point of a determinism gate on a real pipeline. Pin that the
    # run actually walked the fixture and produced observations in at least
    # one arm, not just that whatever it produced was stable.
    total_n = first["treatment"]["n"] + first["control"]["n"]
    assert total_n > 0, "replay produced zero records in both arms; nothing was tested"


def test_pipeline_produces_a_wellformed_comparison():
    result = _run()
    assert set(result) == {"treatment", "control", "breakout_rate_gap", "usable", "min_samples"}
    assert result["treatment"]["n"] >= 0
    assert isinstance(result["usable"], bool)


def test_small_fixture_is_correctly_reported_as_unusable():
    """Two synthetic symbols cannot clear n>=30; the gate must say so."""
    result = _run()
    assert result["usable"] is False
    # `usable is False` also holds if the scan silently produced nothing at
    # all (e.g. a broken cursor walk) — that would be the gate agreeing with
    # the wrong reason. Pin that the control arm, which has a lower admission
    # bar than the treatment arm, is non-empty so we know scanning actually
    # ran against the fixture.
    assert result["control"]["n"] > 0, "control arm is empty; the scan likely never ran"
