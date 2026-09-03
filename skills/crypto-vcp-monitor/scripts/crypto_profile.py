#!/usr/bin/env python3
"""Pre-specified parameter candidates for the crypto VCP calibration.

Measured context that motivates these values (see the design spec):
  - ATR14 as a share of price: BTC 2.85%, ETH 4.01%, SOL 4.39%, BNB 2.77% —
    roughly 2-3x a typical S&P 500 large cap, so depth thresholds must widen.
  - All four monitor symbols sit 39-63% below their 52-week high, so the
    equity 25% band on trend-template c6 rejects everything.
  - `atr_multiplier` is the dominant knob: 1.5 -> 2.5 moved BNB's detected T1
    depth from 25.4% to 8.95% by re-deriving the ZigZag skeleton.

Only these named candidates are swept. A broad grid search over this few
signals would fit noise.

Which knobs the calibration actually moves. Arm assignment (`valid_vcp`,
computed by `_validate_vcp` in `vcp_pattern_calculator.py`) is set from
exactly four parameters: `min_contractions`, `t1_depth_min`,
`contraction_ratio`, and `pattern_duration_min`. `right_shoulder_pct` also
affects the artifact -- but earlier, in `_build_contractions_from`, where it
bounds how many contractions get built into a candidate set at all, not
inside `_validate_vcp`.

Verified by reading every call site (2026-08-24): the following eight
parameters, though threaded through as candidate kwargs, cannot change
`valid_vcp` or any downstream measured number in a calibration artifact --
`_validate_vcp` only appends a non-invalidating entry to `issues`, or the
parameter feeds a code path `valid_vcp` never touches:
  - `t1_depth_max`, `pattern_duration_max` -- `_validate_vcp` flags-not-gates
    ("Don't invalidate, just flag"); `_score_vcp` does not consume `issues`.
  - `wide_and_loose_max_duration` -- sets the separate `wide_and_loose` flag
    (pattern_type/composite-score input), independent of `valid_vcp`.
  - `min_pct_above_52w_low`, `max_pct_below_52w_high`, `min_rs_rank` --
    trend-template criteria 5/6/7, which feed `execution_state` and
    `composite_score`, not `vcp_pattern_calculator`'s `valid_vcp`.
  - `rs_periods` -- feeds relative-strength/criterion 7 only, same as above.
  - `year_window_bars` -- feeds `yearHigh`/`yearLow` for criteria 5/6 only.

So this calibration's "always-on crypto adjustments" for
`max_pct_below_52w_high` (60.0), `min_pct_above_52w_low` (15.0), and
`min_rs_rank` (60) below, and `crypto-long-base`'s `pattern_duration_max=400`
override, never moved a single number in `references/VALIDATION.md` -- they
are untested by this calibration, not validated by it. `crypto-long-base`'s
only calibration-tested difference from `crypto-moderate` is
`min_contraction_days` (10 vs 7) and `lookback_days` (240 vs 150).
"""

from __future__ import annotations

# "52 weeks" is a calendar span, so 365 bars in a 24/7 market — not the 252
# trading-day equivalent. Bar-count conventions (SMA50/150/200) are left alone.
YEAR_WINDOW_BARS = 365

# 3/6/9/12 months in calendar days. The equity 63/126/189/252 are trading-day
# renderings of the same spans with no crypto convention to preserve.
RS_PERIODS_CALENDAR = [(90, 0.40), (180, 0.20), (270, 0.20), (365, 0.20)]

EQUITY_BASELINE = {
    "lookback_days": 120,
    "t1_depth_min": 10.0,
    "contraction_ratio": 0.70,
    "atr_multiplier": 1.5,
    "min_contraction_days": 5,
    "min_contractions": 2,
    "right_shoulder_pct": 5.0,
    "t1_depth_max": 35.0,
    "pattern_duration_min": 15,
    "pattern_duration_max": 325,
    "wide_and_loose_max_duration": 10,
    "min_pct_above_52w_low": 25.0,
    "max_pct_below_52w_high": 25.0,
    "min_rs_rank": 70,
}


def _crypto(**overrides) -> dict:
    """An equity baseline with the always-on crypto adjustments, plus overrides."""
    params = dict(EQUITY_BASELINE)
    params.update(
        {
            "right_shoulder_pct": 12.0,  # 5% truncates crypto right shoulders
            "max_pct_below_52w_high": 60.0,  # crypto draws down 70-80% routinely
            "min_pct_above_52w_low": 15.0,
            "t1_depth_max": 60.0,
            "min_rs_rank": 60,
        }
    )
    params.update(overrides)
    return params


CANDIDATES = {
    "equity-baseline": EQUITY_BASELINE,
    "crypto-tight": _crypto(
        t1_depth_min=12.0,
        contraction_ratio=0.70,
        atr_multiplier=2.0,
        min_contraction_days=7,
        lookback_days=120,
    ),
    "crypto-moderate": _crypto(
        t1_depth_min=15.0,
        contraction_ratio=0.75,
        atr_multiplier=2.5,
        min_contraction_days=7,
        lookback_days=150,
    ),
    "crypto-loose": _crypto(
        t1_depth_min=15.0,
        contraction_ratio=0.80,
        atr_multiplier=2.5,
        min_contraction_days=7,
        lookback_days=180,
    ),
    "crypto-looser": _crypto(
        t1_depth_min=12.0,
        contraction_ratio=0.85,
        atr_multiplier=3.0,
        min_contraction_days=7,
        lookback_days=180,
    ),
    "crypto-deep-t1": _crypto(
        t1_depth_min=20.0,
        contraction_ratio=0.75,
        atr_multiplier=2.5,
        min_contraction_days=7,
        lookback_days=180,
    ),
    "crypto-long-base": _crypto(
        t1_depth_min=15.0,
        contraction_ratio=0.75,
        atr_multiplier=2.5,
        min_contraction_days=10,
        lookback_days=240,
        pattern_duration_max=400,
    ),
    "crypto-three-contractions": _crypto(
        t1_depth_min=15.0,
        contraction_ratio=0.75,
        atr_multiplier=2.5,
        min_contraction_days=7,
        lookback_days=180,
        min_contractions=3,
    ),
}


def analyzer_kwargs(candidate_name: str) -> dict:
    """Return kwargs for `analyze_stock`. Raises KeyError on an unknown name."""
    if candidate_name not in CANDIDATES:
        raise KeyError(f"Unknown candidate: {candidate_name!r}")
    kwargs = dict(CANDIDATES[candidate_name])
    if candidate_name != "equity-baseline":
        kwargs["rs_periods"] = RS_PERIODS_CALENDAR
    return kwargs
