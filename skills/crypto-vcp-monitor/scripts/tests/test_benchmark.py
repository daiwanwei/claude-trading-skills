#!/usr/bin/env python3
"""Equal-weight index construction and index alignment against a target series."""

import pytest
from benchmark import align_to, build_equal_weight_index


def _bars(dates_and_closes):
    """Most-recent-first bars from an oldest-first list of (date, close)."""
    return [
        {"date": d, "close": c, "high": c, "low": c, "open": c, "volume": 1.0}
        for d, c in reversed(dates_and_closes)
    ]


def test_equal_weight_index_averages_component_returns():
    a = _bars([("2024-01-01", 100.0), ("2024-01-02", 110.0)])  # +10%
    b = _bars([("2024-01-01", 50.0), ("2024-01-02", 45.0)])  # -10%

    index = build_equal_weight_index({"A": a, "B": b})

    assert [bar["date"] for bar in index] == ["2024-01-02", "2024-01-01"]
    assert index[-1]["close"] == pytest.approx(100.0)
    assert index[0]["close"] == pytest.approx(100.0, abs=1e-9)


def test_equal_weight_index_reflects_nonzero_net_return():
    """The +10%/-10% pair in the test above nets to zero, so a function that
    ignored returns entirely and always emitted the base value would also
    pass it (verified by mutation). Use a pair whose average return is
    nonzero and asymmetric so the expected value pins down the actual
    averaging math, not just a coincidental net-zero outcome."""
    a = _bars([("2024-01-01", 100.0), ("2024-01-02", 120.0)])  # +20%
    b = _bars([("2024-01-01", 100.0), ("2024-01-02", 130.0)])  # +30%

    index = build_equal_weight_index({"A": a, "B": b})
    by_date = {bar["date"]: bar["close"] for bar in index}

    # mean daily return = (0.20 + 0.30) / 2 = 0.25 -> 100 * 1.25 = 125.0
    assert by_date["2024-01-02"] == pytest.approx(125.0)


def test_equal_weight_index_uses_only_symbols_present_that_day():
    """A late-listing component must not distort earlier days."""
    a = _bars([("2024-01-01", 100.0), ("2024-01-02", 200.0)])  # +100%
    b = _bars([("2024-01-02", 10.0), ("2024-01-03", 10.0)])  # no prior day on 01-02

    index = build_equal_weight_index({"A": a, "B": b})
    by_date = {bar["date"]: bar["close"] for bar in index}

    assert by_date["2024-01-02"] == pytest.approx(200.0)


def test_align_to_matches_target_length_and_dates():
    target = _bars([("2024-01-01", 1.0), ("2024-01-02", 2.0), ("2024-01-03", 3.0)])
    bench = _bars([("2024-01-01", 100.0), ("2024-01-03", 300.0)])  # 01-02 missing

    aligned = align_to(bench, target)

    assert len(aligned) == len(target)
    assert [bar["date"] for bar in aligned] == [bar["date"] for bar in target]


def test_align_to_forward_fills_missing_days():
    target = _bars([("2024-01-01", 1.0), ("2024-01-02", 2.0), ("2024-01-03", 3.0)])
    bench = _bars([("2024-01-01", 100.0), ("2024-01-03", 300.0)])

    aligned = align_to(bench, target)
    by_date = {bar["date"]: bar["close"] for bar in aligned}

    assert by_date["2024-01-02"] == 100.0, "missing day carries the last known close"


def test_align_to_backfills_dates_before_benchmark_start():
    target = _bars([("2023-12-30", 1.0), ("2024-01-01", 2.0)])
    bench = _bars([("2024-01-01", 100.0)])

    aligned = align_to(bench, target)

    assert len(aligned) == 2
    assert aligned[-1]["close"] == 100.0, "pre-start days use the earliest known close"


def test_align_to_backfill_uses_earliest_not_latest_close():
    """The test above uses a single-bar benchmark, where "earliest" and
    "latest" close are the same value -- it cannot distinguish a correct
    backfill from one that (incorrectly) carries the benchmark's most recent
    close backward (verified by mutation). Use a 2-bar benchmark where the
    two differ so the assertion pins down which one pre-start days get."""
    target = _bars([("2023-12-30", 1.0), ("2024-01-01", 2.0), ("2024-01-02", 3.0)])
    bench = _bars([("2024-01-01", 100.0), ("2024-01-02", 300.0)])

    aligned = align_to(bench, target)
    by_date = {bar["date"]: bar["close"] for bar in aligned}

    assert by_date["2023-12-30"] == 100.0, "pre-start day uses the earliest close, not the latest"
