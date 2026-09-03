#!/usr/bin/env python3
"""Golden regression: the equity path must produce byte-identical output.

This test exists to prove that parameterizing previously hardcoded thresholds
(with defaults equal to the old constants) changed no equity behavior. Do not
regenerate the fixtures to make it pass — a diff here means a real behavior change.
"""

import json
from pathlib import Path

from screen_vcp import analyze_stock

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load(name):
    return json.loads((FIXTURES / name).read_text())


def test_equity_path_output_unchanged():
    payload = _load("golden_equity_input.json")
    expected = _load("golden_equity_output.json")

    result = analyze_stock(
        "GOLD",
        payload["historical"],
        payload["quote"],
        payload["benchmark"],
        sector="Technology",
        company_name="Golden Fixture Inc",
    )

    # Round-trip through JSON so the comparison matches how the baseline was stored.
    actual = json.loads(json.dumps(result, sort_keys=True, default=str))
    assert actual == expected


def test_golden_fixture_exercises_contractions():
    """Guard the guard: a fixture that detects nothing would make the test vacuous."""
    expected = _load("golden_equity_output.json")
    assert expected["vcp_pattern"]["num_contractions"] >= 3
