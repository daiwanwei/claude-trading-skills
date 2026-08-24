#!/usr/bin/env python3
"""Equal-weight crypto index used as the relative-strength benchmark.

Crypto has no SPY. An equal-weight index of the frozen calibration universe
answers "did this coin outperform the average coin", which is the question RS
is meant to answer. Market-cap weighting would make the index roughly equal to
BTC and turn every alt's RS into a vs-BTC reading.

Each day's index return is the mean of the daily returns of every component
that has both that day and the prior day, chained from a base of 100. A coin
that lists mid-history therefore joins the index without distorting earlier days.
"""

from __future__ import annotations

BASE_VALUE = 100.0


def build_equal_weight_index(histories: dict) -> list[dict]:
    """Build the index from {symbol: most-recent-first bars}. Returns most-recent-first."""
    returns_by_date: dict = {}
    for bars in histories.values():
        chronological = list(reversed(bars))
        for prev, curr in zip(chronological, chronological[1:]):
            prev_close = prev.get("close", 0.0)
            if prev_close <= 0:
                continue
            daily = curr["close"] / prev_close - 1.0
            returns_by_date.setdefault(curr["date"], []).append(daily)

    all_dates = sorted({bar["date"] for bars in histories.values() for bar in bars})
    if not all_dates:
        return []

    level = BASE_VALUE
    chronological_index = [{"date": all_dates[0], "close": level}]
    for day in all_dates[1:]:
        daily_returns = returns_by_date.get(day)
        if daily_returns:
            level *= 1.0 + sum(daily_returns) / len(daily_returns)
        chronological_index.append({"date": day, "close": level})

    chronological_index.reverse()
    return chronological_index


def align_to(benchmark: list[dict], target: list[dict]) -> list[dict]:
    """Return `benchmark` re-indexed onto `target`'s dates, most-recent-first.

    `scan_history` slices the stock and benchmark arrays with the same offset,
    so the two must line up positionally. Missing benchmark days forward-fill
    the last known close; dates before the benchmark starts use its first close.
    """
    if not target:
        return []
    if not benchmark:
        return [{"date": bar["date"], "close": 0.0} for bar in target]

    by_date = {bar["date"]: bar["close"] for bar in benchmark}
    chronological_dates = sorted(by_date)
    earliest_close = by_date[chronological_dates[0]]

    aligned_chronological = []
    last_close = earliest_close
    for bar in reversed(target):
        if bar["date"] in by_date:
            last_close = by_date[bar["date"]]
        aligned_chronological.append({"date": bar["date"], "close": last_close})

    aligned_chronological.reverse()
    return aligned_chronological
