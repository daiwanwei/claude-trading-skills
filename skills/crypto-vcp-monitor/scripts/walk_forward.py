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
    return {
        "symbol": symbol,
        "as_of_date": as_of_date,
        "as_of_offset": offset,
        "valid_vcp": valid_vcp,
        "num_contractions": pattern.get("num_contractions", 0),
        "composite_score": result.get("composite_score"),
        "execution_state": result.get("execution_state"),
        "pivot_price": pattern.get("pivot_price"),
        "stop_price": contractions[-1].get("low_price") if contractions else None,
        "t1_high_date": contractions[0].get("high_date") if contractions else None,
        "last_low_date": contractions[-1].get("low_date") if contractions else None,
        "forward_outcome": outcome,
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
    """Walk `historical` and return both arms. Bars are most-recent-first."""
    empty = {"treatment": [], "control": []}
    if not historical or len(historical) < lookback_days + 30:
        return empty

    scanner = load_vcp_module("historical_scanner")
    screen = load_vcp_module("screen_vcp")
    outcome_module = load_vcp_module("calculators.forward_outcome")

    kwargs = dict(analyzer_kwargs or {})
    kwargs.pop("as_of_offset", None)
    kwargs.pop("lookback_days", None)

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
