#!/usr/bin/env python3
"""Calibrate crypto VCP thresholds against a treatment/control backtest.

Answers one question: does qualifying VCP contraction structure predict better
forward outcomes than non-qualifying structure, on the same symbols, over the
same period, under an identical pivot/stop rule?

The control arm holds days that produced contractions but failed validation.
That controls for the largest confounder — crypto rising broadly — and sharpens
the claim from "patterns work" to "contraction quality predicts outcomes".

Sample size is the binding constraint. Four symbols produce only 8 valid VCPs
across nine years, so calibration runs over the frozen 30-50 symbol universe.
Any candidate below MIN_SAMPLES is reported as unusable and yields no conclusion.

Significance testing is deliberately absent. Crypto assets move together, so n
signals are far fewer than n independent observations, and a naive t-test would
badly overstate significance. A block bootstrap is only worth building if a raw
gap looks large enough to matter.

Usage:
  python3 calibrate_crypto_vcp.py --output-dir reports/crypto_vcp_calibration/
  python3 calibrate_crypto_vcp.py --candidates crypto-moderate crypto-loose --limit 10
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from benchmark import align_to, build_equal_weight_index  # noqa: E402
from binance_client import BinanceClient  # noqa: E402
from crypto_profile import CANDIDATES, YEAR_WINDOW_BARS, analyzer_kwargs  # noqa: E402
from universe import load_universe, universe_symbols  # noqa: E402
from walk_forward import scan_with_controls  # noqa: E402

# Below this, a candidate produces no conclusion. Chosen in the design spec.
MIN_SAMPLES = 30

_RESOLVED = {"breakout", "stop_hit", "timeout"}


def summarize_arm(records: list) -> dict:
    """Outcome rates and median trajectory for one arm."""
    outcomes = [r["forward_outcome"] for r in records]
    resolved = [o for o in outcomes if o.get("outcome_type") in _RESOLVED]
    n = len(resolved)
    if n == 0:
        return {
            "n": 0,
            "breakout_rate": None,
            "stop_rate": None,
            "timeout_rate": None,
            "median_max_gain_pct": None,
            "median_max_loss_pct": None,
        }

    gains = [o["max_gain_pct"] for o in resolved if o.get("max_gain_pct") is not None]
    losses = [o["max_loss_pct"] for o in resolved if o.get("max_loss_pct") is not None]

    def rate(kind):
        return sum(1 for o in resolved if o["outcome_type"] == kind) / n

    return {
        "n": n,
        "breakout_rate": rate("breakout"),
        "stop_rate": rate("stop_hit"),
        "timeout_rate": rate("timeout"),
        "median_max_gain_pct": statistics.median(gains) if gains else None,
        "median_max_loss_pct": statistics.median(losses) if losses else None,
    }


def _band_geometry_stats(records: list) -> dict:
    """Median band position and pre-resolved share across a full arm
    (unfiltered — this describes the raw arm the caller passed in, not the
    inside-band subset). `band_position`/`pre_resolved` are `None` on records
    predating this instrumentation or with a degenerate pivot<=stop, so both
    stats are computed over only the records that carry a real value."""
    positions = [r["band_position"] for r in records if r.get("band_position") is not None]
    flags = [r["pre_resolved"] for r in records if r.get("pre_resolved") is not None]
    return {
        "median_band_position": statistics.median(positions) if positions else None,
        "pre_resolved_share": (sum(1 for f in flags if f) / len(flags)) if flags else None,
    }


def compare(treatment: list, control: list) -> dict:
    """Compare the two arms and apply the sample-size gate.

    Alongside the raw (unfiltered) arms — kept unchanged, since a reader must
    be able to see both — also reports an inside-band comparison restricted to
    records where the detection-day close sat inside [stop, pivot]
    (`pre_resolved` is False). Records outside that band already had their
    forward race largely decided at detection time, so folding them into the
    headline gap conflates "contraction quality predicted the outcome" with
    "the close started past the pivot or stop." The same MIN_SAMPLES gate
    applies to the inside-band treatment n, reported separately as
    `inside_band_usable` — clearing the raw gate does not imply clearing this
    stricter one.
    """
    t_summary = summarize_arm(treatment)
    c_summary = summarize_arm(control)
    gap = None
    if t_summary["breakout_rate"] is not None and c_summary["breakout_rate"] is not None:
        gap = t_summary["breakout_rate"] - c_summary["breakout_rate"]

    treatment_inside = [r for r in treatment if r.get("pre_resolved") is False]
    control_inside = [r for r in control if r.get("pre_resolved") is False]
    t_inside_summary = summarize_arm(treatment_inside)
    c_inside_summary = summarize_arm(control_inside)
    inside_gap = None
    if (
        t_inside_summary["breakout_rate"] is not None
        and c_inside_summary["breakout_rate"] is not None
    ):
        inside_gap = t_inside_summary["breakout_rate"] - c_inside_summary["breakout_rate"]
    inside_band_usable = t_inside_summary["n"] >= MIN_SAMPLES

    return {
        "treatment": t_summary,
        "control": c_summary,
        "breakout_rate_gap": gap,
        "usable": t_summary["n"] >= MIN_SAMPLES,
        "min_samples": MIN_SAMPLES,
        "band_geometry": {
            "treatment": _band_geometry_stats(treatment),
            "control": _band_geometry_stats(control),
        },
        "inside_band": {
            "treatment": t_inside_summary,
            "control": c_inside_summary,
        },
        "inside_band_breakout_rate_gap": inside_gap,
        "inside_band_usable": inside_band_usable,
    }


def buy_and_hold_return(historical: list, outcome_days: int) -> float | None:
    """Percent return over the most recent `outcome_days` bars. None if too short."""
    if not historical or len(historical) <= outcome_days:
        return None
    start = historical[outcome_days].get("close", 0)
    if start <= 0:
        return None
    return (historical[0]["close"] - start) / start * 100


def parse_arguments(argv=None):
    parser = argparse.ArgumentParser(
        description="Calibrate crypto VCP thresholds via treatment/control backtest"
    )
    parser.add_argument("--output-dir", default="reports/crypto_vcp_calibration/")
    parser.add_argument("--cache-dir", default=".cache/binance/")
    parser.add_argument(
        "--candidates",
        nargs="+",
        default=sorted(CANDIDATES),
        help="Candidate names from crypto_profile.CANDIDATES",
    )
    parser.add_argument("--stride-days", type=int, default=5)
    parser.add_argument("--outcome-days", type=int, default=60)
    parser.add_argument("--control-min-spacing", type=int, default=60)
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Only scan the first N universe symbols (for smoke runs)",
    )
    parser.add_argument("--quiet", action="store_true")

    args = parser.parse_args(argv)
    if not 1 <= args.stride_days <= 60:
        parser.error("--stride-days must be 1-60")
    if not 5 <= args.outcome_days <= 252:
        parser.error("--outcome-days must be 5-252")
    if not 0 <= args.control_min_spacing <= 365:
        parser.error("--control-min-spacing must be 0-365")
    for name in args.candidates:
        if name not in CANDIDATES:
            parser.error(f"unknown candidate: {name}")
    return args


def main(argv=None) -> int:
    args = parse_arguments(argv)
    os.makedirs(args.output_dir, exist_ok=True)

    manifest = load_universe()
    symbols = universe_symbols(manifest)
    if args.limit:
        symbols = symbols[: args.limit]

    client = BinanceClient(cache_dir=args.cache_dir, quiet=args.quiet)
    histories = {}
    for symbol in symbols:
        try:
            histories[symbol] = client.fetch_daily(symbol)
            if not args.quiet:
                print(f"  {symbol:12} {len(histories[symbol])} bars")
        except Exception as exc:  # noqa: BLE001 — one bad symbol must not kill the run
            print(f"  {symbol:12} FAILED: {exc}", file=sys.stderr)

    if not histories:
        print("No symbol history retrieved; aborting.", file=sys.stderr)
        return 1

    index = build_equal_weight_index(histories)

    results = {}
    for name in args.candidates:
        kwargs = analyzer_kwargs(name)
        lookback = kwargs.pop("lookback_days", 120)
        treatment, control = [], []
        failed_symbols = []
        for symbol, bars in histories.items():
            try:
                arms = scan_with_controls(
                    symbol,
                    bars,
                    align_to(index, bars),
                    analyzer_kwargs=kwargs,
                    stride_days=args.stride_days,
                    outcome_days=args.outcome_days,
                    lookback_days=lookback,
                    year_window_bars=YEAR_WINDOW_BARS,
                    control_min_spacing=args.control_min_spacing,
                )
            except Exception as exc:  # noqa: BLE001 — one bad symbol must not kill the scan
                print(f"  {symbol:12} scan failed for {name}: {exc}", file=sys.stderr)
                failed_symbols.append(symbol)
                continue
            treatment.extend(arms["treatment"])
            control.extend(arms["control"])

        results[name] = compare(treatment, control)
        results[name]["failed_symbols"] = failed_symbols
        summary = results[name]
        flag = "" if summary["usable"] else f"  [UNUSABLE: n < {MIN_SAMPLES}]"
        if failed_symbols:
            flag += f"  [{len(failed_symbols)} symbol(s) failed]"
        print(
            f"{name:28} treatment n={summary['treatment']['n']:>4}  "
            f"control n={summary['control']['n']:>4}  "
            f"gap={summary['breakout_rate_gap']}{flag}"
        )
        inside = summary["inside_band"]
        inside_flag = "" if summary["inside_band_usable"] else f"  [UNUSABLE: n < {MIN_SAMPLES}]"
        print(
            f"{'':28} inside-band treatment n={inside['treatment']['n']:>4}  "
            f"control n={inside['control']['n']:>4}  "
            f"gap={summary['inside_band_breakout_rate_gap']}{inside_flag}"
        )

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "universe_frozen_on": manifest["frozen_on"],
        "symbols_scanned": sorted(histories),
        "settings": {
            "stride_days": args.stride_days,
            "outcome_days": args.outcome_days,
            "control_min_spacing": args.control_min_spacing,
            "year_window_bars": YEAR_WINDOW_BARS,
            "min_samples": MIN_SAMPLES,
        },
        "buy_and_hold_reference": {
            symbol: buy_and_hold_return(bars, args.outcome_days)
            for symbol, bars in histories.items()
        },
        "candidates": results,
        "caveat": (
            "No significance test was run. Crypto assets move together, so n "
            "signals are far fewer than n independent observations. Treat gaps "
            "as descriptive."
        ),
    }
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out_path = os.path.join(args.output_dir, f"crypto_vcp_calibration_{stamp}.json")
    with open(out_path, "w") as handle:
        json.dump(payload, handle, indent=1, default=str)
    print(f"\nWrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
