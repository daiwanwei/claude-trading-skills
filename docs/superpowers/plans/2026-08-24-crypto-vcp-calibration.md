# Crypto VCP Calibration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the calibration backtest that determines whether Minervini VCP contraction structure predicts forward outcomes in crypto, and what threshold values it needs.

**Architecture:** Parameterize nine hardcoded thresholds in the shared `vcp-screener` calculators with defaults identical to today's values (guarded by a golden regression test), add a keyless Binance data layer in a new `crypto-vcp-monitor` skill, then run a walk-forward backtest over a frozen 30-50 symbol universe comparing qualifying against non-qualifying contraction structure.

**Tech Stack:** Python 3.9+ (ruff `target-version = "py39"`, `line-length = 100`), pytest, `requests` (lazy-imported; tests never touch the network), Binance public REST API (`api.binance.com`, keyless).

**Spec:** `docs/superpowers/specs/2026-08-24-crypto-vcp-monitor-design.md`

## Global Constraints

- **Equity behavior must not change.** Every new parameter's default equals the value currently hardcoded. Task 1's golden test proves this and must pass unmodified through Tasks 2-5.
- **No network in tests.** `requests` is lazy-imported (`try: import requests / except ImportError: requests = None`), following `skills/crypto-regime-analyzer/scripts/data_client.py`. All tests use fixtures.
- **Python 3.9 floor.** Use `from __future__ import annotations` in any module using `X | None` syntax, as `skills/vcp-screener/scripts/historical_scanner.py` does.
- **Coverage floor 70%** on `skills/crypto-vcp-monitor/scripts`, per `config/ci-test-policy.yaml` `coverage.default_target`. A skill with executable scripts and no tests raises `MatrixError: executable skills are absent from the test matrix`.
- **Test discovery is automatic** from `skills/<name>/scripts/tests/test_*.py`. Extra pip dependencies must be declared under `matrix:` in `config/ci-test-policy.yaml`.
- **No absolute paths** containing usernames — the `no-absolute-paths` pre-commit hook blocks them. Resolve paths via `Path(__file__).resolve().parents[N]`.
- **Reports default to `reports/`**; calibration artifacts go to `reports/crypto_vcp_calibration/`.
- **Run tests with `uv run --extra dev python -m pytest <path> -v`, never bare `python3`.**
  `requests>=2.31.0` is a main dependency in `pyproject.toml`, and
  `skills/vcp-screener/scripts/fmp_client.py:28` calls `sys.exit(1)` at **import
  time** when it is missing. Since `screen_vcp` imports `fmp_client`, running
  these tests outside the project environment terminates the process rather than
  reporting a failure.

## Scope

Covers Delivery-order steps 1-4 of the spec: parameterization, data layer, calibration harness, and the calibration run itself.

**Task 13 is a decision gate.** If no parameter candidate reaches n >= 30, the outcome is a report saying so — not a monitor. `monitor_crypto_vcp.py` is deliberately excluded from this plan and gets its own plan only if the gate passes.

## File Structure

| File | Responsibility |
|---|---|
| `skills/vcp-screener/scripts/tests/fixtures/golden_equity_input.json` | Frozen OHLCV + quote + benchmark for the regression baseline |
| `skills/vcp-screener/scripts/tests/fixtures/golden_equity_output.json` | Frozen `analyze_stock` output captured before any change |
| `skills/vcp-screener/scripts/tests/test_golden_equity_path.py` | Asserts equity output is byte-identical after parameterization |
| `skills/vcp-screener/scripts/calculators/vcp_pattern_calculator.py` | +5 params (`right_shoulder_pct`, `t1_depth_max`, `pattern_duration_min`, `pattern_duration_max`, `wide_and_loose_max_duration`) |
| `skills/vcp-screener/scripts/calculators/trend_template_calculator.py` | +3 params (`min_pct_above_52w_low`, `max_pct_below_52w_high`, `min_rs_rank`) |
| `skills/vcp-screener/scripts/calculators/relative_strength_calculator.py` | `RS_PERIODS` becomes an argument |
| `skills/vcp-screener/scripts/screen_vcp.py` | Threads all new params through `analyze_stock` |
| `skills/vcp-screener/scripts/historical_scanner.py` | Threads `year_window_bars` through `scan_history` |
| `skills/crypto-vcp-monitor/scripts/binance_client.py` | Klines paging, per-UTC-day cache, partial-bar exclusion |
| `skills/crypto-vcp-monitor/scripts/universe.py` | Loads the frozen calibration universe |
| `skills/crypto-vcp-monitor/scripts/benchmark.py` | Equal-weight index + date alignment |
| `skills/crypto-vcp-monitor/scripts/crypto_profile.py` | Single source of truth for crypto thresholds and candidate sets |
| `skills/crypto-vcp-monitor/scripts/calibrate_crypto_vcp.py` | Cursor loop, control-group collection, comparison, CLI |
| `skills/crypto-vcp-monitor/references/calibration_universe.json` | Frozen symbol list with selection date and criteria |

---

### Task 1: Golden regression baseline for the equity path

This is the safety net for Tasks 2-5. Nothing else may proceed until it exists.

**Files:**
- Create: `skills/vcp-screener/scripts/tests/fixtures/golden_equity_input.json`
- Create: `skills/vcp-screener/scripts/tests/fixtures/golden_equity_output.json`
- Create: `skills/vcp-screener/scripts/tests/test_golden_equity_path.py`

**Interfaces:**
- Consumes: `screen_vcp.analyze_stock(symbol, historical, quote, sp500_history, **kwargs)` as it exists today.
- Produces: `test_equity_path_output_unchanged` — the regression gate every later task must keep green.

- [ ] **Step 1: Generate the frozen input fixture**

Run this once from the repo root. The seed makes it deterministic; the series is engineered to actually form contractions so the golden output exercises real code paths rather than an early return.

```bash
mkdir -p skills/vcp-screener/scripts/tests/fixtures
```

```python
# scratch_generate_fixture.py — delete after running
import json, random
from datetime import date, timedelta

rng = random.Random(20260824)
bars, price, day = [], 100.0, date(2024, 1, 1)
# Phase plan: 260 uptrend bars, then contractions of 22%, 13%, 6% depth.
plan = [("up", 260, 0.0022), ("dn", 20, -0.0120), ("up", 18, 0.0125),
        ("dn", 14, -0.0100), ("up", 12, 0.0115), ("dn", 9, -0.0070),
        ("up", 7, 0.0085)]
for _kind, count, drift in plan:
    for _ in range(count):
        price *= 1 + drift + rng.uniform(-0.006, 0.006)
        high = price * (1 + abs(rng.gauss(0, 0.004)))
        low = price * (1 - abs(rng.gauss(0, 0.004)))
        bars.append({"date": day.isoformat(), "open": round(price, 4),
                     "high": round(high, 4), "low": round(low, 4),
                     "close": round(price, 4),
                     "volume": int(1_000_000 * rng.uniform(0.6, 1.6))})
        day += timedelta(days=1)
bars.reverse()  # most-recent-first

bench, bprice, day = [], 400.0, date(2024, 1, 1)
for _ in range(len(bars)):
    bprice *= 1 + 0.0006 + rng.uniform(-0.004, 0.004)
    bench.append({"date": day.isoformat(), "open": round(bprice, 4),
                  "high": round(bprice * 1.003, 4), "low": round(bprice * 0.997, 4),
                  "close": round(bprice, 4), "volume": 90_000_000})
    day += timedelta(days=1)
bench.reverse()

window = bars[:252]
payload = {
    "historical": bars,
    "benchmark": bench,
    "quote": {"price": bars[0]["close"],
              "yearHigh": max(b["high"] for b in window),
              "yearLow": min(b["low"] for b in window),
              "volume": bars[0]["volume"],
              "avgVolume": sum(b["volume"] for b in bars[:50]) / 50,
              "marketCap": 5_000_000_000},
}
with open("skills/vcp-screener/scripts/tests/fixtures/golden_equity_input.json", "w") as f:
    json.dump(payload, f, indent=1, sort_keys=True)
print("bars:", len(bars))
```

Run: `uv run --extra dev python scratch_generate_fixture.py`
Expected: prints `bars: 340`

- [ ] **Step 2: Capture the baseline output — before any source change**

```python
# scratch_capture_baseline.py — delete after running
import json, sys, os
sys.path.insert(0, "skills/vcp-screener/scripts")
from screen_vcp import analyze_stock

p = json.load(open("skills/vcp-screener/scripts/tests/fixtures/golden_equity_input.json"))
result = analyze_stock("GOLD", p["historical"], p["quote"], p["benchmark"],
                       sector="Technology", company_name="Golden Fixture Inc")
with open("skills/vcp-screener/scripts/tests/fixtures/golden_equity_output.json", "w") as f:
    json.dump(result, f, indent=1, sort_keys=True, default=str)
print("composite:", result["composite_score"], "valid_vcp:", result["valid_vcp"],
      "contractions:", result["vcp_pattern"]["num_contractions"])
```

Run: `uv run --extra dev python scratch_capture_baseline.py`
Expected: prints a composite score and `contractions: 3` or more. **If `contractions` is 0 or 1, stop** — the fixture is not exercising the code paths this test exists to protect. Adjust the `plan` drift values in Step 1 until at least 3 contractions form, then re-capture.

- [ ] **Step 3: Write the golden test**

```python
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
```

- [ ] **Step 4: Run the test to verify it passes against unmodified source**

Run: `uv run --extra dev python -m pytest skills/vcp-screener/scripts/tests/test_golden_equity_path.py -v`
Expected: 2 passed

- [ ] **Step 5: Delete the scratch scripts and commit**

```bash
rm -f scratch_generate_fixture.py scratch_capture_baseline.py
git add skills/vcp-screener/scripts/tests/test_golden_equity_path.py \
        skills/vcp-screener/scripts/tests/fixtures/
git commit -m "test(vcp-screener): add golden regression baseline for the equity path"
```

---

### Task 2: Parameterize `vcp_pattern_calculator`

**Files:**
- Modify: `skills/vcp-screener/scripts/calculators/vcp_pattern_calculator.py`
- Test: `skills/vcp-screener/scripts/tests/test_vcp_param_overrides.py` (create)

**Interfaces:**
- Consumes: nothing from earlier tasks except Task 1's green golden test.
- Produces: `calculate_vcp_pattern(..., right_shoulder_pct=5.0, t1_depth_max=35.0, pattern_duration_min=15, pattern_duration_max=325, wide_and_loose_max_duration=10)`. `_build_contractions_from` gains `right_shoulder_pct`; `_validate_vcp` gains `right_shoulder_pct`, `t1_depth_max`, `pattern_duration_min`, `pattern_duration_max`; `_compute_wide_and_loose` gains `max_duration`.

**Note:** `right_shoulder_pct` has **two** call sites — `_build_contractions_from:477` (breaks the loop) and `_validate_vcp:560` (appends an issue). Both must be threaded, or crypto patterns will still be truncated at 5%.

- [ ] **Step 1: Write the failing test**

```python
#!/usr/bin/env python3
"""Overriding the newly parameterized VCP thresholds changes behavior as expected."""

import json
from pathlib import Path

import pytest
from calculators.vcp_pattern_calculator import (
    _compute_wide_and_loose,
    _validate_vcp,
    calculate_vcp_pattern,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture
def golden_bars():
    return json.loads((FIXTURES / "golden_equity_input.json").read_text())["historical"]


def _contractions(depths):
    """Build a minimal contraction list with the given depths."""
    out = []
    for i, depth in enumerate(depths):
        out.append({
            "label": f"T{i + 1}", "depth_pct": depth, "duration_days": 20,
            "high_idx": i * 30, "low_idx": i * 30 + 20,
            "high_price": 100.0, "low_price": 100.0 - depth,
        })
    return out


def test_t1_depth_max_is_overridable():
    """Default flags T1 > 35% as too deep; raising the cap removes that issue."""
    contractions = _contractions([40.0, 10.0])

    default = _validate_vcp(contractions, total_days=300)
    assert any("too deep" in issue for issue in default["issues"])

    relaxed = _validate_vcp(contractions, total_days=300, t1_depth_max=60.0)
    assert not any("too deep" in issue for issue in relaxed["issues"])


def test_pattern_duration_bounds_are_overridable():
    """A 10-bar pattern is invalid by default and valid when the floor is lowered."""
    contractions = _contractions([20.0, 10.0])
    contractions[-1]["low_idx"] = contractions[0]["high_idx"] + 10

    default = _validate_vcp(contractions, total_days=300, t1_depth_min=8.0)
    assert default["valid"] is False
    assert any("too short" in issue for issue in default["issues"])

    relaxed = _validate_vcp(
        contractions, total_days=300, t1_depth_min=8.0, pattern_duration_min=5
    )
    assert not any("too short" in issue for issue in relaxed["issues"])


def test_pattern_duration_max_is_overridable():
    contractions = _contractions([20.0, 10.0])
    contractions[-1]["low_idx"] = contractions[0]["high_idx"] + 400

    default = _validate_vcp(contractions, total_days=500, t1_depth_min=8.0)
    assert any("too long" in issue for issue in default["issues"])

    relaxed = _validate_vcp(
        contractions, total_days=500, t1_depth_min=8.0, pattern_duration_max=500
    )
    assert not any("too long" in issue for issue in relaxed["issues"])


def test_wide_and_loose_max_duration_is_overridable():
    contractions = _contractions([20.0, 18.0])
    contractions[-1]["duration_days"] = 12

    assert _compute_wide_and_loose(contractions, threshold=15.0) is False
    assert _compute_wide_and_loose(contractions, threshold=15.0, max_duration=20) is True


def test_right_shoulder_pct_widens_contraction_search(golden_bars):
    """A wider right-shoulder tolerance may admit at least as many contractions."""
    tight = calculate_vcp_pattern(golden_bars, right_shoulder_pct=5.0)
    wide = calculate_vcp_pattern(golden_bars, right_shoulder_pct=30.0)
    assert wide["num_contractions"] >= tight["num_contractions"]


def test_defaults_match_previous_constants(golden_bars):
    """Explicitly passing the old constants must equal calling with no overrides."""
    implicit = calculate_vcp_pattern(golden_bars)
    explicit = calculate_vcp_pattern(
        golden_bars,
        right_shoulder_pct=5.0,
        t1_depth_max=35.0,
        pattern_duration_min=15,
        pattern_duration_max=325,
        wide_and_loose_max_duration=10,
    )
    assert implicit == explicit
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run --extra dev python -m pytest skills/vcp-screener/scripts/tests/test_vcp_param_overrides.py -v`
Expected: FAIL with `TypeError: _validate_vcp() got an unexpected keyword argument 't1_depth_max'`

- [ ] **Step 3: Add the parameters to `_validate_vcp`**

Change the signature:

```python
def _validate_vcp(
    contractions: list[dict],
    total_days: int,
    min_contractions: int = 2,
    t1_depth_min: float = 8.0,
    contraction_ratio: float = 0.75,
    t1_depth_max: float = 35.0,
    right_shoulder_pct: float = 5.0,
    pattern_duration_min: int = 15,
    pattern_duration_max: int = 325,
) -> dict:
```

Replace the three hardcoded comparisons in the body:

```python
    elif t1_depth > t1_depth_max:
        issues.append(f"T1 depth too deep ({t1_depth:.1f}%, prefer <= {t1_depth_max}%)")
```

```python
            if pct_diff > right_shoulder_pct:
```

```python
        if duration < pattern_duration_min:
            issues.append(f"Pattern too short ({duration} days, need >= {pattern_duration_min})")
            valid = False
        elif duration > pattern_duration_max:
            issues.append(f"Pattern too long ({duration} days, prefer <= {pattern_duration_max})")
```

- [ ] **Step 4: Add `right_shoulder_pct` to `_build_contractions_from`**

Add `right_shoulder_pct: float = 5.0,` as the final parameter of the signature, and replace the check at the former line 477:

```python
        # Right-shoulder validation: subsequent highs within right_shoulder_pct of H1
        if contractions:
            pct_from_h1 = abs(current_high_val - h1_val) / h1_val * 100
            if pct_from_h1 > right_shoulder_pct:
                break
```

- [ ] **Step 5: Add `max_duration` to `_compute_wide_and_loose`**

```python
def _compute_wide_and_loose(
    contractions: list[dict], threshold: float, max_duration: int = 10
) -> bool:
```

```python
    return final_depth > threshold and final_duration < max_duration
```

- [ ] **Step 6: Thread the parameters through `calculate_vcp_pattern`**

Add to the signature after `wide_and_loose_threshold`:

```python
    right_shoulder_pct: float = 5.0,
    t1_depth_max: float = 35.0,
    pattern_duration_min: int = 15,
    pattern_duration_max: int = 325,
    wide_and_loose_max_duration: int = 10,
```

Update all three internal call sites. There are **two** `_build_contractions_from` calls and **two** `_validate_vcp` calls (one inside the multi-start loop, one after it) — update every one:

```python
        candidate = _build_contractions_from(
            start_high,
            swing_highs,
            swing_lows,
            highs,
            lows,
            dates,
            min_contraction_days=min_contraction_days,
            right_shoulder_pct=right_shoulder_pct,
        )
```

```python
            v = _validate_vcp(
                candidate, n, min_contractions, t1_depth_min, contraction_ratio,
                t1_depth_max=t1_depth_max,
                right_shoulder_pct=right_shoulder_pct,
                pattern_duration_min=pattern_duration_min,
                pattern_duration_max=pattern_duration_max,
            )
```

Apply the same keyword block to the post-loop `validation = _validate_vcp(...)` call, and update the wide-and-loose call:

```python
    wide_and_loose = _compute_wide_and_loose(
        contractions, wide_and_loose_threshold, max_duration=wide_and_loose_max_duration
    )
```

- [ ] **Step 7: Run the new test and the golden test**

Run: `uv run --extra dev python -m pytest skills/vcp-screener/scripts/tests/test_vcp_param_overrides.py skills/vcp-screener/scripts/tests/test_golden_equity_path.py -v`
Expected: all passed. **A golden-test failure means a real behavior change — fix the code, never the fixture.**

- [ ] **Step 8: Run the whole vcp-screener suite**

Run: `uv run --extra dev python -m pytest skills/vcp-screener/scripts/tests/ -v`
Expected: all passed

- [ ] **Step 9: Commit**

```bash
git add skills/vcp-screener/scripts/calculators/vcp_pattern_calculator.py \
        skills/vcp-screener/scripts/tests/test_vcp_param_overrides.py
git commit -m "refactor(vcp-screener): parameterize VCP pattern thresholds, defaults unchanged"
```

---

### Task 3: Parameterize `trend_template_calculator`

**Files:**
- Modify: `skills/vcp-screener/scripts/calculators/trend_template_calculator.py`
- Test: `skills/vcp-screener/scripts/tests/test_trend_template_overrides.py` (create)

**Interfaces:**
- Consumes: nothing from Task 2.
- Produces: `calculate_trend_template(historical_prices, quote_data, rs_rank=None, ext_threshold=8.0, max_sma200_extension=50.0, min_pct_above_52w_low=25.0, max_pct_below_52w_high=25.0, min_rs_rank=70)`.

**Note:** the criteria dict keys (`c5_25pct_above_52w_low`, `c6_within_25pct_52w_high`, `c7_rs_rank_above_70`) are consumed by `report_generator.py` and the golden fixture. **Keep the key names literal** — do not interpolate the threshold into them. Only the `detail` strings become dynamic.

- [ ] **Step 1: Write the failing test**

```python
#!/usr/bin/env python3
"""Trend-template criteria 5, 6, and 7 accept overridden thresholds."""

import json
from pathlib import Path

import pytest
from calculators.trend_template_calculator import calculate_trend_template

FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture
def golden():
    return json.loads((FIXTURES / "golden_equity_input.json").read_text())


def test_c6_threshold_is_overridable(golden):
    """A name 40% below its 52w high fails at 25% and passes at 50%."""
    quote = dict(golden["quote"])
    quote["yearHigh"] = quote["price"] / 0.60  # price sits 40% below the high

    strict = calculate_trend_template(golden["historical"], quote, rs_rank=80)
    assert strict["criteria"]["c6_within_25pct_52w_high"]["passed"] is False

    relaxed = calculate_trend_template(
        golden["historical"], quote, rs_rank=80, max_pct_below_52w_high=50.0
    )
    assert relaxed["criteria"]["c6_within_25pct_52w_high"]["passed"] is True


def test_c5_threshold_is_overridable(golden):
    """A name only 10% above its 52w low fails at 25% and passes at 5%."""
    quote = dict(golden["quote"])
    quote["yearLow"] = quote["price"] / 1.10

    strict = calculate_trend_template(golden["historical"], quote, rs_rank=80)
    assert strict["criteria"]["c5_25pct_above_52w_low"]["passed"] is False

    relaxed = calculate_trend_template(
        golden["historical"], quote, rs_rank=80, min_pct_above_52w_low=5.0
    )
    assert relaxed["criteria"]["c5_25pct_above_52w_low"]["passed"] is True


def test_c7_rs_gate_is_overridable(golden):
    strict = calculate_trend_template(golden["historical"], golden["quote"], rs_rank=60)
    assert strict["criteria"]["c7_rs_rank_above_70"]["passed"] is False

    relaxed = calculate_trend_template(
        golden["historical"], golden["quote"], rs_rank=60, min_rs_rank=50
    )
    assert relaxed["criteria"]["c7_rs_rank_above_70"]["passed"] is True


def test_criteria_keys_are_stable(golden):
    """Report generator and the golden fixture depend on these literal keys."""
    result = calculate_trend_template(
        golden["historical"], golden["quote"], rs_rank=80,
        min_pct_above_52w_low=5.0, max_pct_below_52w_high=50.0, min_rs_rank=50,
    )
    assert "c5_25pct_above_52w_low" in result["criteria"]
    assert "c6_within_25pct_52w_high" in result["criteria"]
    assert "c7_rs_rank_above_70" in result["criteria"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run --extra dev python -m pytest skills/vcp-screener/scripts/tests/test_trend_template_overrides.py -v`
Expected: FAIL with `TypeError: calculate_trend_template() got an unexpected keyword argument 'max_pct_below_52w_high'`

- [ ] **Step 3: Add the parameters**

Extend the signature:

```python
def calculate_trend_template(
    historical_prices: list[dict],
    quote_data: dict,
    rs_rank: Optional[int] = None,
    ext_threshold: float = 8.0,
    max_sma200_extension: float = 50.0,
    min_pct_above_52w_low: float = 25.0,
    max_pct_below_52w_high: float = 25.0,
    min_rs_rank: int = 70,
) -> dict:
```

Replace criterion 5:

```python
        c5_pass = pct_above_low >= min_pct_above_52w_low
        criteria["c5_25pct_above_52w_low"] = {
            "passed": c5_pass,
            "detail": (
                f"{pct_above_low:.1f}% above 52w low ${year_low:.2f} "
                f"(need >= {min_pct_above_52w_low}%)"
            ),
        }
```

Replace criterion 6:

```python
        c6_pass = pct_below_high <= max_pct_below_52w_high
        criteria["c6_within_25pct_52w_high"] = {
            "passed": c6_pass,
            "detail": (
                f"{pct_below_high:.1f}% below 52w high ${year_high:.2f} "
                f"(need <= {max_pct_below_52w_high}%)"
            ),
        }
```

Replace criterion 7:

```python
        c7_pass = rs_rank > min_rs_rank
        criteria["c7_rs_rank_above_70"] = {
            "passed": c7_pass,
            "detail": f"RS Rank: {rs_rank} (need > {min_rs_rank})",
        }
```

- [ ] **Step 4: Run the new test plus the golden test**

Run: `uv run --extra dev python -m pytest skills/vcp-screener/scripts/tests/test_trend_template_overrides.py skills/vcp-screener/scripts/tests/test_golden_equity_path.py -v`
Expected: all passed

The golden test passes because the default values reproduce the old `detail` strings exactly — `25.0` formats as `25.0` where the old literal was `25`. **If the golden test fails on a `detail` string mismatch, that is expected and acceptable only here:** re-read the diff, confirm it is purely the numeric formatting of a help string with no `passed` value changed, and if so regenerate `golden_equity_output.json` with the Step-2 script from Task 1, noting the reason in the commit message. Any `passed`, score, or rating difference is a real regression — fix the code instead.

- [ ] **Step 5: Run the whole suite and commit**

Run: `uv run --extra dev python -m pytest skills/vcp-screener/scripts/tests/ -v`
Expected: all passed

```bash
git add skills/vcp-screener/scripts/calculators/trend_template_calculator.py \
        skills/vcp-screener/scripts/tests/test_trend_template_overrides.py
git commit -m "refactor(vcp-screener): parameterize trend template c5/c6/c7 thresholds"
```

---

### Task 4: Make `RS_PERIODS` an argument and thread everything through `analyze_stock`

**Files:**
- Modify: `skills/vcp-screener/scripts/calculators/relative_strength_calculator.py`
- Modify: `skills/vcp-screener/scripts/screen_vcp.py`
- Test: `skills/vcp-screener/scripts/tests/test_rs_periods_override.py` (create)

**Interfaces:**
- Consumes: Task 2's `calculate_vcp_pattern` params and Task 3's `calculate_trend_template` params.
- Produces:
  - `calculate_relative_strength(stock_prices, sp500_prices, rs_periods=None)` where `rs_periods` is a `list[tuple[int, float]]` of `(period_bars, weight)`; `None` means `RS_PERIODS`.
  - `analyze_stock(...)` gains: `right_shoulder_pct=5.0`, `t1_depth_max=35.0`, `pattern_duration_min=15`, `pattern_duration_max=325`, `wide_and_loose_max_duration=10`, `min_pct_above_52w_low=25.0`, `max_pct_below_52w_high=25.0`, `min_rs_rank=70`, `rs_periods=None`.

- [ ] **Step 1: Write the failing test**

```python
#!/usr/bin/env python3
"""RS periods are injectable, and analyze_stock forwards every new parameter."""

import inspect
import json
from pathlib import Path

import pytest
from calculators.relative_strength_calculator import RS_PERIODS, calculate_relative_strength
from screen_vcp import analyze_stock

FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture
def golden():
    return json.loads((FIXTURES / "golden_equity_input.json").read_text())


def test_rs_periods_default_matches_module_constant(golden):
    implicit = calculate_relative_strength(golden["historical"], golden["benchmark"])
    explicit = calculate_relative_strength(
        golden["historical"], golden["benchmark"], rs_periods=RS_PERIODS
    )
    assert implicit == explicit


def test_calendar_rs_periods_change_the_result(golden):
    """Crypto uses 90/180/270/365 instead of 63/126/189/252."""
    equity = calculate_relative_strength(golden["historical"], golden["benchmark"])
    crypto = calculate_relative_strength(
        golden["historical"], golden["benchmark"],
        rs_periods=[(90, 0.40), (180, 0.20), (270, 0.20), (365, 0.20)],
    )
    assert crypto["weighted_rs"] != equity["weighted_rs"]
    assert [d["period_days"] for d in crypto["period_details"]][0] == 90


def test_analyze_stock_accepts_every_new_parameter(golden):
    params = inspect.signature(analyze_stock).parameters
    for name in ("right_shoulder_pct", "t1_depth_max", "pattern_duration_min",
                 "pattern_duration_max", "wide_and_loose_max_duration",
                 "min_pct_above_52w_low", "max_pct_below_52w_high",
                 "min_rs_rank", "rs_periods"):
        assert name in params, f"analyze_stock is missing {name}"


def test_analyze_stock_forwards_trend_overrides(golden):
    """A crypto-style relaxed c6 must actually reach the trend template."""
    quote = dict(golden["quote"])
    quote["yearHigh"] = quote["price"] / 0.60

    strict = analyze_stock("X", golden["historical"], quote, golden["benchmark"])
    relaxed = analyze_stock("X", golden["historical"], quote, golden["benchmark"],
                            max_pct_below_52w_high=50.0)

    assert strict["trend_template"]["criteria"]["c6_within_25pct_52w_high"]["passed"] is False
    assert relaxed["trend_template"]["criteria"]["c6_within_25pct_52w_high"]["passed"] is True
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run --extra dev python -m pytest skills/vcp-screener/scripts/tests/test_rs_periods_override.py -v`
Expected: FAIL with `TypeError: calculate_relative_strength() got an unexpected keyword argument 'rs_periods'`

- [ ] **Step 3: Parameterize the RS calculator**

Change the signature and resolve the default at the top of the body. Keep the module constant `RS_PERIODS` in place — other code and tests import it.

```python
def calculate_relative_strength(
    stock_prices: list[dict],
    sp500_prices: list[dict],
    rs_periods: Optional[list] = None,
) -> dict:
```

Add `from typing import Optional` to the imports if absent, then immediately after the two guard clauses that check input length:

```python
    periods = rs_periods if rs_periods else RS_PERIODS
```

Replace the loop header `for period_days, weight in RS_PERIODS:` with:

```python
    for period_days, weight in periods:
```

- [ ] **Step 4: Thread the parameters through `analyze_stock`**

Add these to the `analyze_stock` signature after `wide_and_loose_threshold: float = 15.0,`:

```python
    right_shoulder_pct: float = 5.0,
    t1_depth_max: float = 35.0,
    pattern_duration_min: int = 15,
    pattern_duration_max: int = 325,
    wide_and_loose_max_duration: int = 10,
    min_pct_above_52w_low: float = 25.0,
    max_pct_below_52w_high: float = 25.0,
    min_rs_rank: int = 70,
    rs_periods: Optional[list] = None,
```

Update the three internal calls:

```python
    rs_result = calculate_relative_strength(historical, sp500_history, rs_periods=rs_periods)
```

```python
    tt_result = calculate_trend_template(
        historical,
        quote,
        rs_rank=rs_rank,
        ext_threshold=ext_threshold,
        max_sma200_extension=max_sma200_extension,
        min_pct_above_52w_low=min_pct_above_52w_low,
        max_pct_below_52w_high=max_pct_below_52w_high,
        min_rs_rank=min_rs_rank,
    )
```

```python
    vcp_result = calculate_vcp_pattern(
        historical,
        lookback_days=lookback_days,
        atr_multiplier=atr_multiplier,
        min_contraction_days=min_contraction_days,
        min_contractions=min_contractions,
        t1_depth_min=t1_depth_min,
        contraction_ratio=contraction_ratio,
        wide_and_loose_threshold=wide_and_loose_threshold,
        right_shoulder_pct=right_shoulder_pct,
        t1_depth_max=t1_depth_max,
        pattern_duration_min=pattern_duration_min,
        pattern_duration_max=pattern_duration_max,
        wide_and_loose_max_duration=wide_and_loose_max_duration,
    )
```

- [ ] **Step 5: Run the new test, the golden test, and the full suite**

Run: `uv run --extra dev python -m pytest skills/vcp-screener/scripts/tests/ -v`
Expected: all passed

- [ ] **Step 6: Commit**

```bash
git add skills/vcp-screener/scripts/calculators/relative_strength_calculator.py \
        skills/vcp-screener/scripts/screen_vcp.py \
        skills/vcp-screener/scripts/tests/test_rs_periods_override.py
git commit -m "refactor(vcp-screener): inject RS periods and forward crypto params through analyze_stock"
```

---

### Task 5: Thread `year_window_bars` through `scan_history`

**Files:**
- Modify: `skills/vcp-screener/scripts/historical_scanner.py:142`
- Test: `skills/vcp-screener/scripts/tests/test_scan_history_year_window.py` (create)

**Interfaces:**
- Consumes: Task 4's `analyze_stock` signature.
- Produces: `scan_history(symbol, historical, sp500_history, *, sector="Unknown", company_name="", stride_days=5, outcome_days=60, lookback_days=120, year_window_bars=252, analyzer_kwargs=None)`.

- [ ] **Step 1: Write the failing test**

```python
#!/usr/bin/env python3
"""scan_history forwards year_window_bars into quote synthesis."""

import json
from pathlib import Path

import historical_scanner
from historical_scanner import build_quote_from_history, scan_history

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _golden():
    return json.loads((FIXTURES / "golden_equity_input.json").read_text())


def test_build_quote_respects_year_window_bars():
    bars = _golden()["historical"]
    narrow = build_quote_from_history(bars, 0, year_window_bars=60)
    wide = build_quote_from_history(bars, 0, year_window_bars=330)
    assert wide["yearHigh"] >= narrow["yearHigh"]
    assert wide["yearLow"] <= narrow["yearLow"]


def test_scan_history_forwards_year_window_bars(monkeypatch):
    bars = _golden()["historical"]
    seen = []

    real_build = historical_scanner.build_quote_from_history

    def spy(historical, offset, year_window_bars=252):
        seen.append(year_window_bars)
        return real_build(historical, offset, year_window_bars=year_window_bars)

    monkeypatch.setattr(historical_scanner, "build_quote_from_history", spy)
    scan_history("GOLD", bars, bars, lookback_days=120, year_window_bars=365)

    assert seen, "build_quote_from_history was never called"
    assert set(seen) == {365}
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run --extra dev python -m pytest skills/vcp-screener/scripts/tests/test_scan_history_year_window.py -v`
Expected: FAIL with `TypeError: scan_history() got an unexpected keyword argument 'year_window_bars'`

- [ ] **Step 3: Add the parameter and forward it**

Add `year_window_bars: int = 252,` to the `scan_history` keyword-only block, after `lookback_days: int = 120,`. Then change line 142 from `quote = build_quote_from_history(historical, offset)` to:

```python
        quote = build_quote_from_history(historical, offset, year_window_bars=year_window_bars)
```

**Important:** the module already binds `screen_vcp` as a module attribute so tests can monkeypatch it. Call `build_quote_from_history` as a plain module-level name (it already is) so the `monkeypatch.setattr(historical_scanner, ...)` in the test intercepts it.

- [ ] **Step 4: Run the test and the full suite**

Run: `uv run --extra dev python -m pytest skills/vcp-screener/scripts/tests/ -v`
Expected: all passed

- [ ] **Step 5: Commit**

```bash
git add skills/vcp-screener/scripts/historical_scanner.py \
        skills/vcp-screener/scripts/tests/test_scan_history_year_window.py
git commit -m "refactor(vcp-screener): thread year_window_bars through scan_history"
```

---

### Task 6: Binance data client

**Files:**
- Create: `skills/crypto-vcp-monitor/scripts/binance_client.py`
- Create: `skills/crypto-vcp-monitor/scripts/tests/conftest.py`
- Create: `skills/crypto-vcp-monitor/scripts/tests/test_binance_client.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `kline_to_bar(raw: list) -> dict` returning `{"date", "open", "high", "low", "close", "volume", "baseVolume", "trades", "closeTime"}`. `volume` carries **quote volume** (`raw[7]`); `baseVolume` carries `raw[5]`.
  - `BinanceClient(cache_dir: str, quiet: bool = False)` with `fetch_daily(symbol: str, now_ms: Optional[int] = None) -> list[dict]` returning **closed bars only, most-recent-first**, and `fetch_price(symbol: str) -> float`.
  - `KLINES_URL`, `TICKER_PRICE_URL`, `DAY_MS = 86_400_000`.

- [ ] **Step 1: Create the test conftest**

```python
"""Shared fixtures for crypto-vcp-monitor tests."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))
```

- [ ] **Step 2: Write the failing test**

```python
#!/usr/bin/env python3
"""Binance client: kline mapping, paging, partial-bar exclusion, caching.

No test in this file touches the network — `_get` is always monkeypatched.
"""

import json

import pytest
from binance_client import DAY_MS, BinanceClient, kline_to_bar

# Binance kline layout:
# [openTime, open, high, low, close, baseVolume, closeTime, quoteVolume, trades, ...]
DAY0 = 1_700_000_000_000 - (1_700_000_000_000 % DAY_MS)


def _kline(open_ms, close_px, base_vol=10.0, quote_vol=1000.0):
    return [open_ms, "1.0", "2.0", "0.5", str(close_px), str(base_vol),
            open_ms + DAY_MS - 1, str(quote_vol), 42, "0", "0", "0"]


def test_kline_to_bar_uses_quote_volume():
    bar = kline_to_bar(_kline(DAY0, 3.5, base_vol=7.0, quote_vol=1234.5))
    assert bar["close"] == 3.5
    assert bar["volume"] == 1234.5, "volume must carry quote (USDT) volume"
    assert bar["baseVolume"] == 7.0
    assert bar["trades"] == 42
    assert bar["date"] == "2023-11-14"


def test_fetch_daily_drops_the_in_progress_bar(tmp_path, monkeypatch):
    """The final bar is still open, so it must not appear in the result."""
    client = BinanceClient(cache_dir=str(tmp_path))
    page = [_kline(DAY0, 1.0), _kline(DAY0 + DAY_MS, 2.0), _kline(DAY0 + 2 * DAY_MS, 3.0)]
    monkeypatch.setattr(client, "_get", lambda url, params: page)

    # "Now" falls inside the third bar, so only the first two are closed.
    bars = client.fetch_daily("BTCUSDT", now_ms=DAY0 + 2 * DAY_MS + 1000)

    assert [b["close"] for b in bars] == [2.0, 1.0], "most-recent-first, open bar dropped"


def test_fetch_daily_pages_until_short_page(tmp_path, monkeypatch):
    client = BinanceClient(cache_dir=str(tmp_path))
    full = [_kline(DAY0 + i * DAY_MS, float(i)) for i in range(1000)]
    tail = [_kline(DAY0 + (1000 + i) * DAY_MS, float(1000 + i)) for i in range(5)]
    calls = []

    def fake_get(url, params):
        calls.append(params["startTime"])
        return full if len(calls) == 1 else tail

    monkeypatch.setattr(client, "_get", fake_get)
    bars = client.fetch_daily("BTCUSDT", now_ms=DAY0 + 5000 * DAY_MS)

    assert len(calls) == 2
    assert calls[0] == 0
    assert calls[1] == full[-1][0] + DAY_MS, "cursor advances past the last open time"
    assert len(bars) == 1005


def test_fetch_daily_uses_cache_on_second_call(tmp_path, monkeypatch):
    client = BinanceClient(cache_dir=str(tmp_path))
    calls = []

    def fake_get(url, params):
        calls.append(params)
        return [_kline(DAY0, 1.0), _kline(DAY0 + DAY_MS, 2.0)]

    monkeypatch.setattr(client, "_get", fake_get)
    now = DAY0 + DAY_MS + 1000

    first = client.fetch_daily("BTCUSDT", now_ms=now)
    second = client.fetch_daily("BTCUSDT", now_ms=now)

    assert len(calls) == 1, "second call must be served from cache"
    assert first == second


def test_fetch_daily_rejects_unsafe_symbol(tmp_path):
    client = BinanceClient(cache_dir=str(tmp_path))
    with pytest.raises(ValueError):
        client.fetch_daily("../../etc/passwd")
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `uv run --extra dev python -m pytest skills/crypto-vcp-monitor/scripts/tests/test_binance_client.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'binance_client'`

- [ ] **Step 4: Implement the client**

```python
#!/usr/bin/env python3
"""Binance public market data client for daily VCP analysis.

Uses only keyless endpoints on api.binance.com:
  /api/v3/klines        -> daily OHLCV, 1000 bars per call, request weight 10
  /api/v3/ticker/price  -> latest trade price

Crypto trades 24/7, so there is always an in-progress daily bar. `fetch_daily`
returns closed bars only; callers that need a live price call `fetch_price`.
Mixing the two would let a partial session's volume contaminate the dry-up
ratio and breakout detection.

The `volume` field carries **quote** (USDT) volume, not base-asset volume.
Over a multi-year window base volume is not comparable across price regimes.

Rate limits: 6000 request weight per minute per IP. A 50-symbol full-history
fetch costs roughly 2000.
"""

from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone
from typing import Optional

try:
    import requests
except ImportError:  # pragma: no cover - exercised only without requests
    requests = None

BINANCE_BASE = "https://api.binance.com"
KLINES_URL = f"{BINANCE_BASE}/api/v3/klines"
TICKER_PRICE_URL = f"{BINANCE_BASE}/api/v3/ticker/price"

DAY_MS = 86_400_000
PAGE_LIMIT = 1000
MAX_RETRIES = 4
BACKOFF_BASE_S = 5
REQUEST_DELAY_S = 0.15

_SYMBOL_RE = re.compile(r"^[A-Z0-9]{4,24}$")


def sanitize_symbol(symbol: str) -> str:
    """Validate an exchange symbol. Raises ValueError on anything path-unsafe."""
    sym = (symbol or "").upper().strip()
    if not _SYMBOL_RE.match(sym):
        raise ValueError(f"Invalid Binance symbol: {symbol!r}. Must match {_SYMBOL_RE.pattern}")
    return sym


def kline_to_bar(raw: list) -> dict:
    """Map one Binance kline row to the OHLCV shape the VCP calculators expect."""
    return {
        "date": datetime.fromtimestamp(raw[0] / 1000, timezone.utc).strftime("%Y-%m-%d"),
        "open": float(raw[1]),
        "high": float(raw[2]),
        "low": float(raw[3]),
        "close": float(raw[4]),
        "volume": float(raw[7]),      # quote (USDT) volume — the equity dollar-volume analog
        "baseVolume": float(raw[5]),
        "trades": int(raw[8]),
        "closeTime": int(raw[6]),
    }


class BinanceClient:
    """Fetch and cache daily klines."""

    def __init__(self, cache_dir: str, quiet: bool = False):
        self.cache_dir = cache_dir
        self.quiet = quiet
        os.makedirs(cache_dir, exist_ok=True)

    def _log(self, message: str) -> None:
        if not self.quiet:
            print(message)

    def _cache_path(self, symbol: str) -> str:
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return os.path.join(self.cache_dir, f"{day}_{symbol}_1d.json")

    def _get(self, url: str, params: dict):
        """GET with 429-aware exponential backoff."""
        if requests is None:
            raise RuntimeError("The 'requests' library is required for live fetches")
        for attempt in range(MAX_RETRIES):
            resp = requests.get(url, params=params, timeout=30)
            if resp.status_code != 429:
                resp.raise_for_status()
                return resp.json()
            delay = float(resp.headers.get("Retry-After") or BACKOFF_BASE_S * (2**attempt))
            self._log(f"  rate limited, sleeping {delay:.0f}s")
            time.sleep(delay)
        raise RuntimeError(f"Binance rate limit not cleared after {MAX_RETRIES} attempts")

    def fetch_daily(self, symbol: str, now_ms: Optional[int] = None) -> list[dict]:
        """Return every closed daily bar for `symbol`, most-recent-first."""
        sym = sanitize_symbol(symbol)
        cache_path = self._cache_path(sym)
        if os.path.exists(cache_path):
            with open(cache_path) as handle:
                return json.load(handle)

        now = now_ms if now_ms is not None else int(time.time() * 1000)
        raw_rows: list = []
        start = 0
        while True:
            page = self._get(
                KLINES_URL,
                {"symbol": sym, "interval": "1d", "startTime": start, "limit": PAGE_LIMIT},
            )
            if not page:
                break
            raw_rows.extend(page)
            if len(page) < PAGE_LIMIT:
                break
            start = page[-1][0] + DAY_MS
            time.sleep(REQUEST_DELAY_S)

        bars = [kline_to_bar(row) for row in raw_rows]
        bars = [bar for bar in bars if bar["closeTime"] < now]  # drop the in-progress bar
        bars.reverse()

        with open(cache_path, "w") as handle:
            json.dump(bars, handle)
        return bars

    def fetch_price(self, symbol: str) -> float:
        """Latest trade price — the live value the in-progress bar would carry."""
        sym = sanitize_symbol(symbol)
        payload = self._get(TICKER_PRICE_URL, {"symbol": sym})
        return float(payload["price"])
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run --extra dev python -m pytest skills/crypto-vcp-monitor/scripts/tests/test_binance_client.py -v`
Expected: 5 passed

- [ ] **Step 6: Commit**

```bash
git add skills/crypto-vcp-monitor/scripts/binance_client.py \
        skills/crypto-vcp-monitor/scripts/tests/
git commit -m "feat(crypto-vcp-monitor): add keyless Binance daily kline client"
```

---

### Task 7: Frozen calibration universe

**Files:**
- Create: `skills/crypto-vcp-monitor/references/calibration_universe.json`
- Create: `skills/crypto-vcp-monitor/scripts/universe.py`
- Create: `skills/crypto-vcp-monitor/scripts/tests/test_universe.py`

**Interfaces:**
- Consumes: `BinanceClient` from Task 6 (only in the one-off freeze step).
- Produces: `load_universe(path: Optional[str] = None) -> dict` returning the parsed manifest, and `universe_symbols(manifest: dict) -> list[str]`. `MONITOR_SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]`.

- [ ] **Step 1: Build the frozen manifest**

Run this once. It queries the live exchange, then **you commit the result** so the backtest never re-derives the universe from today's survivors.

```python
# scratch_freeze_universe.py — delete after running
import json, urllib.request
from datetime import date

EXCLUDE_BASES = {"USDC", "FDUSD", "TUSD", "USD1", "DAI", "BUSD", "EUR", "GBP", "AEUR"}
# Names that traded with real volume but have since been delisted or renamed.
# Binance still serves their klines, so including them removes survivorship bias.
DELISTED = ["MATICUSDT"]

ex = json.load(urllib.request.urlopen("https://api.binance.com/api/v3/exchangeInfo"))
spot = {s["symbol"]: s for s in ex["symbols"]
        if s["quoteAsset"] == "USDT" and s["status"] == "TRADING"
        and s["isSpotTradingAllowed"] and s["baseAsset"] not in EXCLUDE_BASES
        and not s["baseAsset"].endswith(("UP", "DOWN", "BULL", "BEAR"))}

tick = json.load(urllib.request.urlopen("https://api.binance.com/api/v3/ticker/24hr"))
ranked = sorted(((float(t["quoteVolume"]), t["symbol"]) for t in tick if t["symbol"] in spot),
                reverse=True)

selected = []
for volume, symbol in ranked:
    if len(selected) >= 45:
        break
    first = json.load(urllib.request.urlopen(
        f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=1d&startTime=0&limit=1"))
    bars = json.load(urllib.request.urlopen(
        f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=1d&limit=1000"))
    if not first or len(bars) < 1000:
        continue  # fewer than ~3 years of history
    selected.append({"symbol": symbol, "quote_volume_24h": volume,
                     "first_bar": first[0][0]})
    print(f"  {symbol:12} ${volume/1e6:8.1f}M")

manifest = {
    "frozen_on": date.today().isoformat(),
    "criteria": {
        "quote_asset": "USDT", "spot_only": True, "min_bars": 1000,
        "excluded_bases": sorted(EXCLUDE_BASES),
        "excluded_suffixes": ["UP", "DOWN", "BULL", "BEAR"],
        "ranked_by": "24h quote volume", "target_count": 45,
    },
    "note": ("Frozen deliberately. Re-deriving this list from live exchangeInfo would "
             "infer the historical universe from today's survivors. Delisted names are "
             "added manually; Binance still serves their klines."),
    "symbols": [entry["symbol"] for entry in selected] + DELISTED,
    "delisted_manually_added": DELISTED,
    "selection_detail": selected,
}
with open("skills/crypto-vcp-monitor/references/calibration_universe.json", "w") as f:
    json.dump(manifest, f, indent=1)
print("total symbols:", len(manifest["symbols"]))
```

```bash
mkdir -p skills/crypto-vcp-monitor/references
uv run --extra dev python scratch_freeze_universe.py
```

Expected: `total symbols:` between 30 and 46. If fewer than 30 survive the 1000-bar filter, lower `min_bars` to 800 and re-run, recording the change in `criteria`.

- [ ] **Step 2: Write the failing test**

```python
#!/usr/bin/env python3
"""The calibration universe is frozen, well-formed, and keeps delisted names."""

import json
from pathlib import Path

import pytest
from universe import MONITOR_SYMBOLS, load_universe, universe_symbols

REFERENCES = Path(__file__).resolve().parents[2] / "references"


def test_frozen_manifest_is_committed():
    assert (REFERENCES / "calibration_universe.json").is_file()


def test_manifest_has_provenance():
    manifest = load_universe()
    assert manifest["frozen_on"]
    assert manifest["criteria"]["quote_asset"] == "USDT"
    assert manifest["criteria"]["min_bars"] >= 800


def test_universe_is_large_enough_for_calibration():
    symbols = universe_symbols(load_universe())
    assert len(symbols) >= 30, "spec requires a 30-50 symbol calibration universe"
    assert len(symbols) == len(set(symbols)), "duplicate symbols"


def test_delisted_symbols_are_retained():
    """Survivorship-bias guard: removing these silently would bias the backtest."""
    manifest = load_universe()
    delisted = manifest["delisted_manually_added"]
    assert delisted, "at least one delisted name must be carried"
    for symbol in delisted:
        assert symbol in manifest["symbols"]


def test_no_stablecoin_or_leveraged_pairs():
    for symbol in universe_symbols(load_universe()):
        base = symbol[:-4]
        assert base not in {"USDC", "FDUSD", "TUSD", "USD1", "DAI", "BUSD"}
        assert not base.endswith(("UP", "DOWN", "BULL", "BEAR"))


def test_monitor_symbols_are_inside_the_universe():
    symbols = set(universe_symbols(load_universe()))
    for symbol in MONITOR_SYMBOLS:
        assert symbol in symbols


def test_load_universe_rejects_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_universe(str(tmp_path / "nope.json"))
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `uv run --extra dev python -m pytest skills/crypto-vcp-monitor/scripts/tests/test_universe.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'universe'`

- [ ] **Step 4: Implement `universe.py`**

```python
#!/usr/bin/env python3
"""Load the frozen calibration universe.

The symbol list is committed rather than derived at run time. Deriving it from
live exchangeInfo would reconstruct the historical universe out of today's
survivors — MATICUSDT delisted on 2024-09-10 yet Binance still serves its full
history, so an exchange query would silently drop it and bias every result.
"""

from __future__ import annotations

import json
import os
from typing import Optional

# The four names the monitor watches. Kept inside the calibration universe so
# calibrated thresholds are not extrapolated onto unseen symbols.
MONITOR_SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]

_DEFAULT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "references",
    "calibration_universe.json",
)


def load_universe(path: Optional[str] = None) -> dict:
    """Return the frozen universe manifest. Raises FileNotFoundError if absent."""
    target = path or _DEFAULT_PATH
    if not os.path.isfile(target):
        raise FileNotFoundError(f"Frozen calibration universe not found: {target}")
    with open(target) as handle:
        return json.load(handle)


def universe_symbols(manifest: dict) -> list[str]:
    """Return the symbol list, order preserved."""
    return list(manifest["symbols"])
```

- [ ] **Step 5: Run the test, delete the scratch script, commit**

Run: `uv run --extra dev python -m pytest skills/crypto-vcp-monitor/scripts/tests/test_universe.py -v`
Expected: 7 passed

```bash
rm -f scratch_freeze_universe.py
git add skills/crypto-vcp-monitor/references/calibration_universe.json \
        skills/crypto-vcp-monitor/scripts/universe.py \
        skills/crypto-vcp-monitor/scripts/tests/test_universe.py
git commit -m "feat(crypto-vcp-monitor): freeze the calibration universe with delisted names retained"
```

---

### Task 8: Equal-weight benchmark with date alignment

**Files:**
- Create: `skills/crypto-vcp-monitor/scripts/benchmark.py`
- Create: `skills/crypto-vcp-monitor/scripts/tests/test_benchmark.py`

**Interfaces:**
- Consumes: bar dicts from `binance_client.kline_to_bar`.
- Produces:
  - `build_equal_weight_index(histories: dict[str, list[dict]]) -> list[dict]` — most-recent-first bars with `date` and `close`, where each day's return is the equal-weight mean of component daily returns, chained from a base of 100.
  - `align_to(benchmark: list[dict], target: list[dict]) -> list[dict]` — returns a benchmark series **index-aligned** with `target`, forward-filling the last known close for missing dates.

**Why alignment matters:** `scan_history` slices `historical` and `sp500_history` with the same offset. Listing dates differ per symbol, so an unaligned benchmark silently compares different calendar days.

- [ ] **Step 1: Write the failing test**

```python
#!/usr/bin/env python3
"""Equal-weight index construction and index alignment against a target series."""

import pytest
from benchmark import align_to, build_equal_weight_index


def _bars(dates_and_closes):
    """Most-recent-first bars from an oldest-first list of (date, close)."""
    return [{"date": d, "close": c, "high": c, "low": c, "open": c, "volume": 1.0}
            for d, c in reversed(dates_and_closes)]


def test_equal_weight_index_averages_component_returns():
    a = _bars([("2024-01-01", 100.0), ("2024-01-02", 110.0)])   # +10%
    b = _bars([("2024-01-01", 50.0), ("2024-01-02", 45.0)])     # -10%

    index = build_equal_weight_index({"A": a, "B": b})

    assert [bar["date"] for bar in index] == ["2024-01-02", "2024-01-01"]
    assert index[-1]["close"] == pytest.approx(100.0)
    assert index[0]["close"] == pytest.approx(100.0, abs=1e-9)


def test_equal_weight_index_uses_only_symbols_present_that_day():
    """A late-listing component must not distort earlier days."""
    a = _bars([("2024-01-01", 100.0), ("2024-01-02", 200.0)])   # +100%
    b = _bars([("2024-01-02", 10.0), ("2024-01-03", 10.0)])     # no prior day on 01-02

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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run --extra dev python -m pytest skills/crypto-vcp-monitor/scripts/tests/test_benchmark.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'benchmark'`

- [ ] **Step 3: Implement `benchmark.py`**

```python
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
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run --extra dev python -m pytest skills/crypto-vcp-monitor/scripts/tests/test_benchmark.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add skills/crypto-vcp-monitor/scripts/benchmark.py \
        skills/crypto-vcp-monitor/scripts/tests/test_benchmark.py
git commit -m "feat(crypto-vcp-monitor): add equal-weight benchmark with date alignment"
```

---

### Task 9: Crypto parameter profile

**Files:**
- Create: `skills/crypto-vcp-monitor/scripts/crypto_profile.py`
- Create: `skills/crypto-vcp-monitor/scripts/tests/test_crypto_profile.py`

**Interfaces:**
- Consumes: the `analyze_stock` keyword names added in Task 4.
- Produces:
  - `EQUITY_BASELINE: dict` — the equity defaults, used as the control arm of the sweep.
  - `CANDIDATES: dict[str, dict]` — 8 pre-specified candidates including `"equity-baseline"`.
  - `RS_PERIODS_CALENDAR = [(90, 0.40), (180, 0.20), (270, 0.20), (365, 0.20)]`
  - `YEAR_WINDOW_BARS = 365`
  - `analyzer_kwargs(candidate_name: str) -> dict` — kwargs ready to pass to `analyze_stock`.

**Pre-specified candidates only.** The spec forbids a broad grid search; 8 named candidates keeps the multiple-comparisons problem bounded.

- [ ] **Step 1: Write the failing test**

```python
#!/usr/bin/env python3
"""The crypto parameter profile is well-formed and matches analyze_stock's signature."""

import inspect
import sys
from pathlib import Path

import pytest
from crypto_profile import (
    CANDIDATES,
    EQUITY_BASELINE,
    RS_PERIODS_CALENDAR,
    YEAR_WINDOW_BARS,
    analyzer_kwargs,
)

VCP_SCRIPTS = (
    Path(__file__).resolve().parents[3] / "vcp-screener" / "scripts"
)
sys.path.insert(0, str(VCP_SCRIPTS))
from screen_vcp import analyze_stock  # noqa: E402


def test_candidate_count_is_bounded():
    """Spec: 6-12 pre-specified candidates, no broad grid search."""
    assert 6 <= len(CANDIDATES) <= 12


def test_equity_baseline_is_a_candidate():
    assert "equity-baseline" in CANDIDATES
    assert CANDIDATES["equity-baseline"] == EQUITY_BASELINE


def test_every_candidate_key_is_a_real_analyze_stock_parameter():
    """A typo here would be silently ignored as an unused dict key."""
    valid = set(inspect.signature(analyze_stock).parameters)
    for name, params in CANDIDATES.items():
        for key in params:
            assert key in valid, f"candidate {name!r} has unknown parameter {key!r}"


def test_rs_periods_use_calendar_spans():
    """Spec 2e: RS uses 90/180/270/365, not the equity 63/126/189/252."""
    assert [period for period, _weight in RS_PERIODS_CALENDAR] == [90, 180, 270, 365]
    assert sum(weight for _p, weight in RS_PERIODS_CALENDAR) == pytest.approx(1.0)


def test_year_window_is_365_bars():
    """Spec 2e: '52 weeks' is a calendar span, so 365 bars, not 252."""
    assert YEAR_WINDOW_BARS == 365


def test_analyzer_kwargs_injects_calendar_rs_for_crypto_candidates():
    kwargs = analyzer_kwargs("crypto-moderate")
    assert kwargs["rs_periods"] == RS_PERIODS_CALENDAR


def test_analyzer_kwargs_rejects_unknown_candidate():
    with pytest.raises(KeyError):
        analyzer_kwargs("does-not-exist")


def test_crypto_candidates_relax_c6():
    """All four monitor symbols sit 39-63% below their 52w high; 25% gates everything out."""
    for name, params in CANDIDATES.items():
        if name == "equity-baseline":
            continue
        assert params["max_pct_below_52w_high"] >= 40.0
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run --extra dev python -m pytest skills/crypto-vcp-monitor/scripts/tests/test_crypto_profile.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'crypto_profile'`

- [ ] **Step 3: Implement `crypto_profile.py`**

```python
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
    params.update({
        "right_shoulder_pct": 12.0,      # 5% truncates crypto right shoulders
        "max_pct_below_52w_high": 60.0,  # crypto draws down 70-80% routinely
        "min_pct_above_52w_low": 15.0,
        "t1_depth_max": 60.0,
        "min_rs_rank": 60,
    })
    params.update(overrides)
    return params


CANDIDATES = {
    "equity-baseline": EQUITY_BASELINE,
    "crypto-tight": _crypto(
        t1_depth_min=12.0, contraction_ratio=0.70, atr_multiplier=2.0,
        min_contraction_days=7, lookback_days=120,
    ),
    "crypto-moderate": _crypto(
        t1_depth_min=15.0, contraction_ratio=0.75, atr_multiplier=2.5,
        min_contraction_days=7, lookback_days=150,
    ),
    "crypto-loose": _crypto(
        t1_depth_min=15.0, contraction_ratio=0.80, atr_multiplier=2.5,
        min_contraction_days=7, lookback_days=180,
    ),
    "crypto-looser": _crypto(
        t1_depth_min=12.0, contraction_ratio=0.85, atr_multiplier=3.0,
        min_contraction_days=7, lookback_days=180,
    ),
    "crypto-deep-t1": _crypto(
        t1_depth_min=20.0, contraction_ratio=0.75, atr_multiplier=2.5,
        min_contraction_days=7, lookback_days=180,
    ),
    "crypto-long-base": _crypto(
        t1_depth_min=15.0, contraction_ratio=0.75, atr_multiplier=2.5,
        min_contraction_days=10, lookback_days=240, pattern_duration_max=400,
    ),
    "crypto-three-contractions": _crypto(
        t1_depth_min=15.0, contraction_ratio=0.75, atr_multiplier=2.5,
        min_contraction_days=7, lookback_days=180, min_contractions=3,
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
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run --extra dev python -m pytest skills/crypto-vcp-monitor/scripts/tests/test_crypto_profile.py -v`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add skills/crypto-vcp-monitor/scripts/crypto_profile.py \
        skills/crypto-vcp-monitor/scripts/tests/test_crypto_profile.py
git commit -m "feat(crypto-vcp-monitor): add pre-specified crypto parameter candidates"
```

---

### Task 10: Walk-forward scan with control-group collection

**Files:**
- Create: `skills/crypto-vcp-monitor/scripts/walk_forward.py`
- Create: `skills/crypto-vcp-monitor/scripts/tests/test_walk_forward.py`

**Interfaces:**
- Consumes: Task 4's `analyze_stock`, Task 5's `build_quote_from_history`, Task 9's `analyzer_kwargs`.
- Produces:
  - `load_vcp_module(name: str)` — loads a `vcp-screener` module by file path; raises `ImportError` if absent.
  - `scan_with_controls(symbol, historical, benchmark, *, analyzer_kwargs, stride_days=5, outcome_days=60, lookback_days=120, year_window_bars=365, control_min_spacing=60) -> dict` returning `{"treatment": [...], "control": [...]}`. Each record is `{"symbol", "as_of_date", "as_of_offset", "pivot_price", "stop_price", "num_contractions", "composite_score", "forward_outcome"}`.

**Why not `scan_history`:** it drops the control group at `historical_scanner.py:159`. Control-group collection is a calibration concern, so it lives here while reusing `build_quote_from_history` — the no-look-ahead part that is genuinely hard to get right.

**Control-group definition:** `num_contractions >= 1` and `valid_vcp is False`. Those days still have a defined pivot and stop, so the outcome rule is identical across arms. Days with zero contractions are excluded — without a stop, `stop_hit` is undefined.

**Overlap control:** stride 5 with a 60-day forward window makes 12 consecutive cursors near-duplicates. Treatment is deduplicated by pattern identity; control needs an explicit `control_min_spacing` in bars.

- [ ] **Step 1: Write the failing test**

```python
#!/usr/bin/env python3
"""Walk-forward scan collects treatment and control arms with comparable outcomes."""

import json
from pathlib import Path

import pytest
import walk_forward
from walk_forward import load_vcp_module, scan_with_controls

GOLDEN = (
    Path(__file__).resolve().parents[3]
    / "vcp-screener" / "scripts" / "tests" / "fixtures" / "golden_equity_input.json"
)


@pytest.fixture
def bars():
    return json.loads(GOLDEN.read_text())["historical"]


def test_load_vcp_module_finds_the_sibling_skill():
    module = load_vcp_module("historical_scanner")
    assert hasattr(module, "build_quote_from_history")


def test_load_vcp_module_raises_on_unknown_module():
    with pytest.raises(ImportError):
        load_vcp_module("no_such_module_here")


def test_both_arms_have_pivot_and_stop(bars):
    """Outcome rules must be identical across arms, so both need a stop."""
    result = scan_with_controls("GOLD", bars, bars, analyzer_kwargs={}, stride_days=10)
    for arm in ("treatment", "control"):
        for record in result[arm]:
            assert record["pivot_price"] is not None, f"{arm} record without a pivot"
            assert record["stop_price"] is not None, f"{arm} record without a stop"


def test_control_records_have_contractions_but_are_invalid(bars):
    result = scan_with_controls("GOLD", bars, bars, analyzer_kwargs={}, stride_days=10)
    for record in result["control"]:
        assert record["num_contractions"] >= 1
        assert record["valid_vcp"] is False


def test_control_spacing_is_enforced(bars):
    """Without spacing, overlapping forward windows inflate the control arm."""
    spaced = scan_with_controls("GOLD", bars, bars, analyzer_kwargs={},
                                stride_days=5, control_min_spacing=60)
    offsets = sorted(record["as_of_offset"] for record in spaced["control"])
    for earlier, later in zip(offsets, offsets[1:]):
        assert later - earlier >= 60, "control samples closer than the spacing floor"


def test_tighter_spacing_yields_at_least_as_many_controls(bars):
    loose = scan_with_controls("GOLD", bars, bars, analyzer_kwargs={},
                               stride_days=5, control_min_spacing=60)
    tight = scan_with_controls("GOLD", bars, bars, analyzer_kwargs={},
                               stride_days=5, control_min_spacing=5)
    assert len(tight["control"]) >= len(loose["control"])


def test_treatment_records_are_deduplicated(bars):
    result = scan_with_controls("GOLD", bars, bars, analyzer_kwargs={}, stride_days=5)
    keys = [(r["t1_high_date"], r["last_low_date"], round(r["pivot_price"], 2))
            for r in result["treatment"]]
    assert len(keys) == len(set(keys))


def test_short_history_returns_empty_arms():
    result = scan_with_controls("GOLD", [], [], analyzer_kwargs={})
    assert result == {"treatment": [], "control": []}


def test_forward_outcome_is_attached(bars):
    result = scan_with_controls("GOLD", bars, bars, analyzer_kwargs={}, stride_days=10)
    records = result["treatment"] + result["control"]
    assert records, "fixture produced no records at all"
    for record in records:
        assert record["forward_outcome"]["outcome_type"] in {
            "breakout", "stop_hit", "timeout", "insufficient_data"
        }
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run --extra dev python -m pytest skills/crypto-vcp-monitor/scripts/tests/test_walk_forward.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'walk_forward'`

- [ ] **Step 3: Implement `walk_forward.py`**

```python
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
from typing import Optional

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
    analyzer_kwargs: Optional[dict] = None,
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
            symbol, historical, quote, benchmark,
            lookback_days=lookback_days, as_of_offset=offset, **kwargs
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
            if last_control_offset is not None and (
                last_control_offset - offset
            ) < control_min_spacing:
                continue
            last_control_offset = offset
            bucket = control

        outcome = outcome_module.calculate_forward_outcome(
            historical, offset, pivot, stop_price=stop, max_window_days=outcome_days
        )
        bucket.append(_record(symbol, result, offset, as_of_date, outcome, valid_vcp))

    return {"treatment": treatment, "control": control}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run --extra dev python -m pytest skills/crypto-vcp-monitor/scripts/tests/test_walk_forward.py -v`
Expected: 9 passed

If `test_both_arms_have_pivot_and_stop` fails because a control record has a `None` stop, the guard `if stop is None: continue` is missing or misplaced — that record must be dropped, not defaulted.

- [ ] **Step 5: Commit**

```bash
git add skills/crypto-vcp-monitor/scripts/walk_forward.py \
        skills/crypto-vcp-monitor/scripts/tests/test_walk_forward.py
git commit -m "feat(crypto-vcp-monitor): add walk-forward scan retaining a control arm"
```

---

### Task 11: Comparison statistics and calibration CLI

**Files:**
- Create: `skills/crypto-vcp-monitor/scripts/calibrate_crypto_vcp.py`
- Create: `skills/crypto-vcp-monitor/scripts/tests/test_calibrate.py`

**Interfaces:**
- Consumes: Tasks 6-10.
- Produces:
  - `summarize_arm(records: list[dict]) -> dict` returning `{"n", "breakout_rate", "stop_rate", "timeout_rate", "median_max_gain_pct", "median_max_loss_pct"}`. `breakout_rate` is `None` when `n == 0`.
  - `compare(treatment, control) -> dict` adding `{"treatment", "control", "breakout_rate_gap", "usable"}`, where `usable` is `treatment["n"] >= MIN_SAMPLES`.
  - `buy_and_hold_return(historical, outcome_days) -> float`
  - `MIN_SAMPLES = 30`
  - `main(argv=None) -> int` CLI entry point.

- [ ] **Step 1: Write the failing test**

```python
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
    return {"forward_outcome": {"outcome_type": outcome_type,
                                "max_gain_pct": gain, "max_loss_pct": loss}}


def test_summarize_empty_arm_reports_none_not_zero():
    """A 0% breakout rate and 'no data' are different claims."""
    summary = summarize_arm([])
    assert summary["n"] == 0
    assert summary["breakout_rate"] is None
    assert summary["median_max_gain_pct"] is None


def test_summarize_computes_rates_and_medians():
    records = [_record("breakout", 12.0, -3.0), _record("breakout", 20.0, -5.0),
               _record("stop_hit", 2.0, -9.0), _record("timeout", 4.0, -4.0)]
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


def test_compare_marks_large_samples_usable_and_reports_the_gap():
    treatment = [_record("breakout", 10.0, -2.0)] * 40
    control = ([_record("breakout", 5.0, -4.0)] * 10 + [_record("stop_hit", 1.0, -8.0)] * 30)
    result = compare(treatment, control)
    assert result["usable"] is True
    assert result["treatment"]["breakout_rate"] == pytest.approx(1.0)
    assert result["control"]["breakout_rate"] == pytest.approx(0.25)
    assert result["breakout_rate_gap"] == pytest.approx(0.75)


def test_compare_gap_is_none_when_either_arm_is_empty():
    result = compare([], [_record("breakout", 5.0, -4.0)] * 10)
    assert result["breakout_rate_gap"] is None


def test_buy_and_hold_return_uses_the_forward_window():
    bars = [{"date": "2024-03-01", "close": 120.0},
            {"date": "2024-02-01", "close": 110.0},
            {"date": "2024-01-01", "close": 100.0}]
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run --extra dev python -m pytest skills/crypto-vcp-monitor/scripts/tests/test_calibrate.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'calibrate_crypto_vcp'`

- [ ] **Step 3: Implement `calibrate_crypto_vcp.py`**

```python
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
from typing import Optional

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
        return {"n": 0, "breakout_rate": None, "stop_rate": None, "timeout_rate": None,
                "median_max_gain_pct": None, "median_max_loss_pct": None}

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


def compare(treatment: list, control: list) -> dict:
    """Compare the two arms and apply the sample-size gate."""
    t_summary = summarize_arm(treatment)
    c_summary = summarize_arm(control)
    gap = None
    if t_summary["breakout_rate"] is not None and c_summary["breakout_rate"] is not None:
        gap = t_summary["breakout_rate"] - c_summary["breakout_rate"]
    return {
        "treatment": t_summary,
        "control": c_summary,
        "breakout_rate_gap": gap,
        "usable": t_summary["n"] >= MIN_SAMPLES,
        "min_samples": MIN_SAMPLES,
    }


def buy_and_hold_return(historical: list, outcome_days: int) -> Optional[float]:
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
    parser.add_argument("--candidates", nargs="+", default=sorted(CANDIDATES),
                        help="Candidate names from crypto_profile.CANDIDATES")
    parser.add_argument("--stride-days", type=int, default=5)
    parser.add_argument("--outcome-days", type=int, default=60)
    parser.add_argument("--control-min-spacing", type=int, default=60)
    parser.add_argument("--limit", type=int, default=None,
                        help="Only scan the first N universe symbols (for smoke runs)")
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
        for symbol, bars in histories.items():
            arms = scan_with_controls(
                symbol, bars, align_to(index, bars),
                analyzer_kwargs=kwargs,
                stride_days=args.stride_days,
                outcome_days=args.outcome_days,
                lookback_days=lookback,
                year_window_bars=YEAR_WINDOW_BARS,
                control_min_spacing=args.control_min_spacing,
            )
            treatment.extend(arms["treatment"])
            control.extend(arms["control"])

        results[name] = compare(treatment, control)
        summary = results[name]
        flag = "" if summary["usable"] else "  [UNUSABLE: n < %d]" % MIN_SAMPLES
        print(f"{name:28} treatment n={summary['treatment']['n']:>4}  "
              f"control n={summary['control']['n']:>4}  "
              f"gap={summary['breakout_rate_gap']}{flag}")

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "universe_frozen_on": manifest["frozen_on"],
        "symbols_scanned": sorted(histories),
        "settings": {"stride_days": args.stride_days, "outcome_days": args.outcome_days,
                     "control_min_spacing": args.control_min_spacing,
                     "year_window_bars": YEAR_WINDOW_BARS, "min_samples": MIN_SAMPLES},
        "buy_and_hold_reference": {
            symbol: buy_and_hold_return(bars, args.outcome_days)
            for symbol, bars in histories.items()
        },
        "candidates": results,
        "caveat": ("No significance test was run. Crypto assets move together, so n "
                   "signals are far fewer than n independent observations. Treat gaps "
                   "as descriptive."),
    }
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out_path = os.path.join(args.output_dir, f"crypto_vcp_calibration_{stamp}.json")
    with open(out_path, "w") as handle:
        json.dump(payload, handle, indent=1, default=str)
    print(f"\nWrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run --extra dev python -m pytest skills/crypto-vcp-monitor/scripts/tests/test_calibrate.py -v`
Expected: 10 passed

- [ ] **Step 5: Add the end-to-end replay test**

Spec Verification item 6: a fixed fixture must produce a fixed result. This is what
makes a calibration finding auditable — a number nobody can reproduce is not evidence.

Create `skills/crypto-vcp-monitor/scripts/tests/test_end_to_end_replay.py`:

```python
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
    / "vcp-screener" / "scripts" / "tests" / "fixtures" / "golden_equity_input.json"
)


def _universe():
    bars = json.loads(GOLDEN.read_text())["historical"]
    # A second, offset series so the equal-weight index has two components and
    # the date-alignment path is genuinely exercised.
    shifted = [dict(bar, close=bar["close"] * 0.5, high=bar["high"] * 0.5,
                    low=bar["low"] * 0.5, open=bar["open"] * 0.5)
               for bar in bars[:-40]]
    return {"AAAUSDT": bars, "BBBUSDT": shifted}


def _run(candidate="crypto-moderate"):
    histories = _universe()
    index = build_equal_weight_index(histories)
    kwargs = analyzer_kwargs(candidate)
    lookback = kwargs.pop("lookback_days", 120)

    treatment, control = [], []
    for symbol, bars in histories.items():
        arms = scan_with_controls(
            symbol, bars, align_to(index, bars),
            analyzer_kwargs=kwargs, stride_days=5, outcome_days=60,
            lookback_days=lookback, year_window_bars=YEAR_WINDOW_BARS,
            control_min_spacing=60,
        )
        treatment.extend(arms["treatment"])
        control.extend(arms["control"])
    return compare(treatment, control)


def test_pipeline_is_deterministic():
    assert _run() == _run()


def test_pipeline_produces_a_wellformed_comparison():
    result = _run()
    assert set(result) == {
        "treatment", "control", "breakout_rate_gap", "usable", "min_samples"
    }
    assert result["treatment"]["n"] >= 0
    assert isinstance(result["usable"], bool)


def test_small_fixture_is_correctly_reported_as_unusable():
    """Two synthetic symbols cannot clear n>=30; the gate must say so."""
    assert _run()["usable"] is False
```

- [ ] **Step 6: Run the replay test**

Run: `uv run --extra dev python -m pytest skills/crypto-vcp-monitor/scripts/tests/test_end_to_end_replay.py -v`
Expected: 3 passed

- [ ] **Step 7: Run the whole crypto suite and check coverage**

Run: `uv run --extra dev python -m pytest skills/crypto-vcp-monitor/scripts/tests/ --cov=skills/crypto-vcp-monitor/scripts --cov-report=term-missing`
Expected: all passed, coverage >= 70%. If below, add tests for the uncovered branches — do not add a waiver.

- [ ] **Step 8: Commit**

```bash
git add skills/crypto-vcp-monitor/scripts/calibrate_crypto_vcp.py \
        skills/crypto-vcp-monitor/scripts/tests/test_calibrate.py \
        skills/crypto-vcp-monitor/scripts/tests/test_end_to_end_replay.py
git commit -m "feat(crypto-vcp-monitor): add treatment/control calibration CLI"
```

---

### Task 12: Skill documentation and repository registration

**Files:**
- Create: `skills/crypto-vcp-monitor/SKILL.md`
- Create: `skills/crypto-vcp-monitor/references/crypto_vcp_methodology.md`
- Create: `skills/crypto-vcp-monitor/references/VALIDATION.md`
- Modify: `skills-index.yaml`
- Modify: `README.md`, `README.ja.md`, `docs/en/skill-catalog.md`, `docs/ja/skill-catalog.md`

**Interfaces:**
- Consumes: everything above.
- Produces: a skill that passes the `skill-frontmatter` and `docs-completeness` pre-commit hooks.

- [ ] **Step 1: Write `SKILL.md`**

The `skill-frontmatter` hook requires `name` to equal the directory name and `description` to be present.

```markdown
---
name: crypto-vcp-monitor
description: Detects Minervini Volatility Contraction Patterns in crypto (BTC, ETH, SOL, BNB) using keyless Binance daily data, with a treatment/control backtest that calibrates the thresholds. No API key required. Use when the user asks about crypto VCP setups, whether BTC/ETH/SOL/BNB are consolidating or contracting, crypto breakout pivots, or wants VCP thresholds calibrated for crypto volatility.
---

# Crypto VCP Monitor Skill

## Purpose

Apply Mark Minervini's Volatility Contraction Pattern analysis to crypto majors
using Binance public data. The algorithm is shared with `vcp-screener`; only the
thresholds differ.

**No API key required** — Binance's public `/api/v3/klines` endpoint is keyless.

## Current status: calibration only

The monitor is not built yet, by design. Equity VCP thresholds do not transfer to
crypto, and four symbols produce only 8 valid patterns across nine years — far
too few to pick thresholds from. `calibrate_crypto_vcp.py` runs the backtest that
decides whether usable thresholds exist. Until a candidate clears 30 signals,
this skill makes no trading claims.

## Prerequisites

- **Python 3.9+** with `requests` for live fetches
- **The `vcp-screener` skill must be present in the same repository.** This skill
  loads its calculators directly and fails fast if they are missing. It will not
  run as a standalone `.skill` upload.
- **No API keys**

## Workflow

1. Load the frozen calibration universe from `references/calibration_universe.json`.
2. Fetch full daily history per symbol via `binance_client` (closed bars only).
3. Build the equal-weight benchmark index and align it to each symbol's dates.
4. Walk each symbol's history, collecting a treatment arm (valid VCP) and a
   control arm (contractions present, validation failed).
5. Compare breakout rates and median trajectories per parameter candidate.
6. Report any candidate with n >= 30 as usable; everything else yields no conclusion.

## Running the calibration

```bash
python3 skills/crypto-vcp-monitor/scripts/calibrate_crypto_vcp.py \
  --output-dir reports/crypto_vcp_calibration/

# Smoke run over the first 5 symbols and two candidates
python3 skills/crypto-vcp-monitor/scripts/calibrate_crypto_vcp.py \
  --limit 5 --candidates crypto-moderate crypto-loose
```

## What This Skill Does NOT Do

- No position sizing, order generation, or portfolio changes
- No perpetual futures, no intraday or weekly timeframes
- No trading recommendation until calibration clears the sample-size gate

## Resources

- `references/crypto_vcp_methodology.md` — threshold rationale and equity deltas
- `references/VALIDATION.md` — evidence boundary
- `references/calibration_universe.json` — the frozen symbol list
```

- [ ] **Step 2: Write `references/crypto_vcp_methodology.md`**

```markdown
# Crypto VCP Methodology

## Why equity thresholds do not transfer

Measured daily volatility, sampled 2026-08-24 over a 120-bar window:

| Symbol | ATR14 as % of price | Mean daily range |
|---|---|---|
| BTCUSDT | 2.85% | 2.92% |
| ETHUSDT | 4.01% | 3.98% |
| SOLUSDT | 4.39% | 4.41% |
| BNBUSDT | 2.77% | 3.04% |

That is roughly 2-3x a typical S&P 500 large cap, so every depth-percentage
threshold is mis-scaled when applied unchanged.

## Trend template criterion 6

Distance below the 52-week high, same sample date: BTC 38.8%, ETH 49.2%,
SOL 62.8%, BNB 49.4%. All four fail the equity 25% band. Crypto routinely draws
down 70-80%, so 25% admits candidates only during a strong bull market. Crypto
candidates use 60%.

## Period conversion

Bar counts are not converted. SMA50/150/200 stay at 50/150/200 bars, matching
TradingView and crypto convention: if every market participant watches that line,
it carries self-fulfilling weight regardless of the calendar span it covers.

Two exceptions, where the quantity is defined in calendar terms:

- **52-week high/low uses 365 bars.** "200-day moving average" names a bar count;
  "52 weeks" names a calendar span. Using 252 would label an 8.3-month extreme as
  a 52-week extreme.
- **RS periods use 90/180/270/365.** The equity 63/126/189/252 are trading-day
  renderings of 3/6/9/12 months with no crypto convention to preserve, and RS is
  a cross-asset comparison that needs a consistent time axis.

## Parameter sensitivity

`atr_multiplier` dominates: raising it from 1.5 to 2.5 changed BNBUSDT's detected
T1 depth from 25.4% to 8.95%, because the ZigZag skeleton is re-derived and a
different swing sequence is selected. Treat every other threshold as conditional
on it.

## Volume units

The `volume` field carries quote (USDT) volume. SOLUSDT ranged from $8 to $253,
so base-asset volume is not comparable across a multi-year lookback — identical
dollar flow reads as 30x the "volume" at the low end.

## Partial bars

Crypto trades 24/7, so a daily bar is always in progress. Measured at
2026-08-24T01:45Z, BTCUSDT's open bar carried 1,155 base volume against the prior
completed day's 15,367. Open bars are excluded from `historical`; live price comes
from `/api/v3/ticker/price` instead.
```

- [ ] **Step 3: Write `references/VALIDATION.md`**

```markdown
# Validation Boundary

## What is established

- Binance public klines supply complete daily OHLCV for the calibration universe
  back to each symbol's listing (BTCUSDT and ETHUSDT from 2017-08-17).
- The `vcp-screener` calculators run unmodified on Binance-sourced bars.
- Applying equity thresholds unchanged yields 8 valid VCPs across BTC, ETH, SOL,
  and BNB over roughly nine years — too few to support any performance claim.

## What is NOT established

- Whether VCP contraction quality predicts forward outcomes in crypto at all.
- Any specific threshold value. The candidates in `crypto_profile.py` are
  hypotheses awaiting calibration, not validated settings.
- Any win rate, expectancy, or risk-adjusted return figure.

## Method limits that will persist even after calibration

- **No significance test.** Crypto assets are highly correlated, so n signals are
  far fewer than n independent observations. Raw gaps are descriptive only.
- **Correlated regimes.** The available history spans few distinct crypto cycles,
  so results are not independent draws across market conditions.
- **Partial survivorship control.** Delisted names are re-added manually, which
  reduces but does not eliminate survivorship bias.
- **Multiple comparisons.** Eight candidates are swept; the best-looking one is
  optimistically biased by selection alone.

## Required before any performance claim

Record the calibration run's date, universe, per-candidate sample sizes, and the
treatment/control gap. Any candidate below 30 signals yields no conclusion.
```

- [ ] **Step 4: Register in `skills-index.yaml`**

Insert alphabetically — after the `crypto-regime-analyzer` block and before `data-quality-checker`:

```yaml
- id: crypto-vcp-monitor
  display_name: Crypto VCP Monitor
  category: swing-opportunity
  status: experimental
  summary: Calibrates and detects Minervini VCP setups in crypto majors using keyless Binance daily data.
  timeframe: daily
  difficulty: advanced
  integrations:
  - id: binance_public
    type: market_data
    requirement: required
    note: Public spot klines endpoint, no API key; daily OHLCV and latest price
  - id: vcp_screener_calculators
    type: local_file
    requirement: required
    note: Loads skills/vcp-screener/scripts calculators directly; fails fast if absent
  inputs:
  - binance_daily_ohlcv
  - calibration_universe
  outputs:
  - crypto_vcp_calibration_report
  workflows: []
```

- [ ] **Step 5: Generate the doc pages**

Run: `uv run --extra dev python scripts/generate_skill_docs.py --skill crypto-vcp-monitor`
Expected: creates `docs/en/skills/crypto-vcp-monitor.md`, `docs/ja/skills/crypto-vcp-monitor.md`, and updates both `docs/{en,ja}/skills/index.md`.

- [ ] **Step 6: Regenerate the README catalog sections — do not hand-edit them**

`README.md` and `README.ja.md` contain generated regions between
`<!-- skills-index:start name="catalog-en" -->` sentinels, and
`.pre-commit-config.yaml:117` runs `generate_catalog_from_index.py --check` as a
drift gate. Hand-editing either README fails that hook.

Run: `uv run --extra dev python scripts/generate_catalog_from_index.py`
Expected: both READMEs pick up the `crypto-vcp-monitor` row from `skills-index.yaml`.

- [ ] **Step 7: Add the two catalog rows by hand**

`docs/en/skill-catalog.md` and `docs/ja/skill-catalog.md` are **not** covered by
any generator. Each needs two rows.

In `docs/en/skill-catalog.md`, add to the `## 1. Stock Screening` table directly
below the VCP Screener row:

```markdown
| **[Crypto VCP Monitor]({{ '/en/skills/crypto-vcp-monitor/' | relative_url }})** | Applies Minervini's Volatility Contraction Pattern to crypto majors (BTC, ETH, SOL, BNB) using keyless Binance daily data. Ships a treatment/control backtest that calibrates thresholds to crypto volatility before any signal is claimed | <span class="badge badge-free">No API</span> |
```

and to the API Requirements Matrix (near the `| VCP Screener | Required | -- | -- |` row):

```markdown
| Crypto VCP Monitor | -- | -- | -- |
```

In `docs/ja/skill-catalog.md`, the same two places. Note the JA file uses plain
bold names without `relative_url` links, and single `-` in the matrix:

```markdown
| **Crypto VCP Monitor** | Minerviniのボラティリティ収縮パターンを暗号資産主要銘柄（BTC/ETH/SOL/BNB）に適用。APIキー不要のBinance日足データを使用し、シグナルを主張する前に処理群/対照群バックテストで閾値を較正 | <span class="badge badge-free">API不要</span> |
```

```markdown
| Crypto VCP Monitor | - | - | - |
```

- [ ] **Step 8: Verify the hooks pass**

Run: `uv run --extra dev pre-commit run --all-files`
Expected: all hooks pass. `docs-completeness` fails if either doc page is missing;
`skill-frontmatter` fails if `name` does not equal the directory name;
`generate_catalog_from_index --check` fails if Step 6 was skipped.

- [ ] **Step 9: Confirm the CI matrix accepts the new skill**

Run: `uv run --extra dev python scripts/ci_test_matrix.py list`
Expected: `crypto-vcp-monitor` appears. If it raises `executable skills are absent from the test matrix`, the tests directory is misnamed — it must be `skills/crypto-vcp-monitor/scripts/tests/` with `test_*.py` files.

- [ ] **Step 10: Commit**

```bash
git add skills/crypto-vcp-monitor/SKILL.md \
        skills/crypto-vcp-monitor/references/ \
        skills-index.yaml README.md README.ja.md \
        docs/en/ docs/ja/
git commit -m "docs(crypto-vcp-monitor): add skill definition, references, and catalog entries"
```

---

### Task 13: Run the calibration and decide the gate

This task produces a decision, not code.

**Files:**
- Create: `reports/crypto_vcp_calibration/crypto_vcp_calibration_<date>.json` (generated)
- Modify: `skills/crypto-vcp-monitor/references/VALIDATION.md`

**Interfaces:**
- Consumes: Tasks 1-12.
- Produces: the go/no-go decision for a follow-up monitor plan.

- [ ] **Step 1: Smoke-run against five symbols**

Run:

```bash
uv run --with requests python skills/crypto-vcp-monitor/scripts/calibrate_crypto_vcp.py \
  --limit 5 --candidates equity-baseline crypto-moderate \
  --output-dir reports/crypto_vcp_calibration/
```

Expected: per-symbol bar counts print, then two candidate lines with treatment and control counts, then a written JSON path. If any symbol reports `FAILED`, check the symbol name against the frozen manifest before proceeding.

- [ ] **Step 2: Run the full calibration**

Run:

```bash
uv run --with requests python skills/crypto-vcp-monitor/scripts/calibrate_crypto_vcp.py \
  --output-dir reports/crypto_vcp_calibration/
```

Expected: 8 candidate lines. The first run fetches full history for every symbol and takes several minutes; re-runs hit the per-UTC-day cache.

- [ ] **Step 3: Record the results in `VALIDATION.md`**

Replace the "What is NOT established" section's first two bullets with the measured outcome. Include, for every candidate: treatment n, control n, both breakout rates, the gap, and the `usable` flag. State the run date and the universe's `frozen_on` date.

- [ ] **Step 4: Apply the gate**

- **If at least one candidate has treatment n >= 30:** record which candidates cleared, note that the best-looking one is optimistically biased by selection across 8 candidates, and report the gap sizes. A follow-up plan for `monitor_crypto_vcp.py` becomes justified.
- **If no candidate reaches n >= 30:** stop. Write the finding into `VALIDATION.md`, report that crypto VCP signals are too rare at these thresholds to calibrate against, and do **not** build the monitor. This is a valid and useful outcome, not a failure.

- [ ] **Step 5: Commit**

```bash
git add skills/crypto-vcp-monitor/references/VALIDATION.md \
        reports/crypto_vcp_calibration/
git commit -m "docs(crypto-vcp-monitor): record calibration results and gate decision"
```

---

## Final verification

- [ ] Run the full repository suite: `./scripts/run_all_tests.sh`
- [ ] Confirm `skills/vcp-screener/scripts/tests/test_golden_equity_path.py` still passes — the proof that equity behavior never changed
- [ ] Run `uv run --extra dev pre-commit run --all-files`
