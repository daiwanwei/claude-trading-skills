#!/usr/bin/env python3
"""Walk-forward VCP scan that keeps a control arm.

`vcp-screener`'s `scan_history` discards every day that fails VCP validation,
which is exactly the comparison group this calibration needs. This module walks
the same cursor while retaining both arms, reusing `build_quote_from_history`
for no-look-ahead quote synthesis.

Arms:
  treatment — valid_vcp is True, deduplicated by pattern identity
  control   — num_contractions >= 1 and valid_vcp is False

Control days still carry a pivot (last contraction high) and a stop (last
contraction low), so both arms score under an identical outcome rule. Days with
no contractions are excluded: with no stop, `stop_hit` cannot be evaluated and
the arms stop being comparable.

Control samples additionally require a minimum bar spacing. With stride 5 and a
60-bar forward window, 12 consecutive cursor positions share almost the same
forward path; the treatment arm is protected by pattern-identity dedup, so
without spacing the control arm would inflate to roughly 10x while remaining
largely one observation.

Each record also carries band geometry: where the detection-day close sat
between the last contraction's low (stop) and the pivot, via
`pct_to_pivot`/`pct_to_stop`/`band_position`/`pre_resolved`. This exists to
let a downstream comparison separate "contraction quality predicted the
outcome" from "the close was already past the pivot or stop at detection
time, so the race was largely decided before the forward window opened."
"""

from __future__ import annotations

import importlib.util
import os
import sys

_VCP_SCRIPTS = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "vcp-screener",
    "scripts",
)

_MODULE_CACHE: dict = {}


def load_vcp_module(name: str):
    """Load a `vcp-screener` module by path. Dots select a subpackage file,
    so "calculators.forward_outcome" resolves to calculators/forward_outcome.py.

    This is a hard dependency, not an optional enrichment — the calculators are
    the core algorithm. Failing loudly beats silently producing no signals.
    """
    if name in _MODULE_CACHE:
        return _MODULE_CACHE[name]

    module_path = os.path.join(_VCP_SCRIPTS, *name.split(".")) + ".py"
    if not os.path.isfile(module_path):
        raise ImportError(
            f"crypto-vcp-monitor requires the vcp-screener skill; missing {module_path}"
        )

    # vcp-screener modules import their siblings as top-level names, so its
    # scripts/ directory must be importable before any of them is executed.
    if _VCP_SCRIPTS not in sys.path:
        sys.path.insert(0, _VCP_SCRIPTS)

    spec = importlib.util.spec_from_file_location(
        "vcp_screener_" + name.replace(".", "_"), module_path
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load vcp-screener module: {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _MODULE_CACHE[name] = module
    return module


def _record(symbol, result, offset, as_of_date, outcome, valid_vcp):
    pattern = result.get("vcp_pattern", {})
    contractions = pattern.get("contractions") or []
    pivot = pattern.get("pivot_price")
    stop = contractions[-1].get("low_price") if contractions else None
    # `result["price"]` is the as-of-offset close: `analyze_stock` sets it
    # straight from `quote["price"]`, which `build_quote_from_history`
    # synthesizes from `historical[as_of_offset]` — i.e. the detection-day
    # close, not `historical[0]` (the most recent/right-edge bar). This is
    # also the exact `current_price` `calculate_pivot_proximity` used, so the
    # band-geometry fields below describe the same trade the outcome rule
    # scores.
    close = result.get("price")

    # Computed directly rather than reusing `result["distance_from_pivot_pct"]`
    # (= (close - pivot) / pivot * 100): that figure is pivot-relative and
    # opposite in sign from the close-relative pct_to_pivot/pct_to_stop needed
    # here to characterize where detection-day price sat inside the
    # [stop, pivot] band the outcome rule races.
    pct_to_pivot = None
    pct_to_stop = None
    band_position = None
    pre_resolved = None
    if close is not None and close > 0:
        if pivot is not None:
            pct_to_pivot = (pivot - close) / close * 100
        if stop is not None:
            pct_to_stop = (stop - close) / close * 100
        if pivot is not None and stop is not None and pivot > stop:
            # band_position is undefined (not just divide-by-zero-prone) when
            # pivot <= stop, so it — and pre_resolved, which depends on it —
            # stay None rather than defaulting to False in that degenerate case.
            band_position = (close - stop) / (pivot - stop)
            pre_resolved = band_position < 0 or band_position > 1

    return {
        "symbol": symbol,
        "as_of_date": as_of_date,
        "as_of_offset": offset,
        "valid_vcp": valid_vcp,
        "num_contractions": pattern.get("num_contractions", 0),
        "composite_score": result.get("composite_score"),
        "execution_state": result.get("execution_state"),
        "pivot_price": pivot,
        "stop_price": stop,
        "t1_high_date": contractions[0].get("high_date") if contractions else None,
        "last_low_date": contractions[-1].get("low_date") if contractions else None,
        "forward_outcome": outcome,
        "detection_close": close,
        "pct_to_pivot": pct_to_pivot,
        "pct_to_stop": pct_to_stop,
        "band_position": band_position,
        "pre_resolved": pre_resolved,
    }


def scan_with_controls(
    symbol: str,
    historical: list,
    benchmark: list,
    *,
    analyzer_kwargs: dict | None = None,
    stride_days: int = 5,
    outcome_days: int = 60,
    lookback_days: int = 120,
    year_window_bars: int = 365,
    control_min_spacing: int = 60,
) -> dict:
    """Walk `historical` and return both arms. Bars are most-recent-first.

    `analyzer_kwargs` must not carry a `lookback_days` that disagrees with
    the explicit `lookback_days` argument. `crypto_profile.analyzer_kwargs`
    returns candidate dicts whose `lookback_days` varies (120-240) — silently
    preferring the explicit default here would quietly discard the swept
    lookback window this calibration exists to test, producing a clean-
    looking result in which that dimension never actually moved. A matching
    value or an absent key is fine; a mismatch raises `ValueError` naming
    both numbers.
    """
    kwargs = dict(analyzer_kwargs or {})
    kwargs.pop("as_of_offset", None)
    kwargs_lookback = kwargs.pop("lookback_days", None)
    if kwargs_lookback is not None and kwargs_lookback != lookback_days:
        raise ValueError(
            f"analyzer_kwargs['lookback_days']={kwargs_lookback!r} conflicts with "
            f"the explicit lookback_days={lookback_days!r} argument. Pass "
            f"lookback_days={kwargs_lookback!r} explicitly to scan_with_controls "
            "instead of leaving it inside analyzer_kwargs."
        )

    empty = {"treatment": [], "control": []}
    if not historical or len(historical) < lookback_days + 30:
        return empty

    scanner = load_vcp_module("historical_scanner")
    screen = load_vcp_module("screen_vcp")
    outcome_module = load_vcp_module("calculators.forward_outcome")

    max_offset = len(historical) - lookback_days
    if max_offset <= 0:
        return empty

    treatment, control = [], []
    seen_patterns = set()
    last_control_offset = None

    for offset in range(max_offset, -1, -stride_days):
        quote = scanner.build_quote_from_history(
            historical, offset, year_window_bars=year_window_bars
        )
        if quote.get("price", 0) <= 0:
            continue

        result = screen.analyze_stock(
            symbol,
            historical,
            quote,
            benchmark,
            lookback_days=lookback_days,
            as_of_offset=offset,
            **kwargs,
        )
        if result is None:
            continue

        pattern = result.get("vcp_pattern", {})
        contractions = pattern.get("contractions") or []
        pivot = pattern.get("pivot_price")
        if not contractions or pivot is None:
            continue

        stop = contractions[-1].get("low_price")
        if stop is None:
            continue

        valid_vcp = bool(result.get("valid_vcp"))
        as_of_date = historical[offset].get("date")

        if valid_vcp:
            key = (
                contractions[0].get("high_date") or f"idx:{contractions[0].get('high_idx')}",
                contractions[-1].get("low_date") or f"idx:{contractions[-1].get('low_idx')}",
                round(pivot, 8),
            )
            if key in seen_patterns:
                continue
            seen_patterns.add(key)
            bucket = treatment
        else:
            if (
                last_control_offset is not None
                and (last_control_offset - offset) < control_min_spacing
            ):
                continue
            last_control_offset = offset
            bucket = control

        outcome = outcome_module.calculate_forward_outcome(
            historical, offset, pivot, stop_price=stop, max_window_days=outcome_days
        )
        bucket.append(_record(symbol, result, offset, as_of_date, outcome, valid_vcp))

    return {"treatment": treatment, "control": control}
