# Crypto VCP Core Design

## Status and relationship to the earlier design

This design supersedes the cross-skill dependency and shared-calculator portions
of `2026-08-24-crypto-vcp-monitor-design.md`. The data collection, frozen
universe, calibration-first delivery order, and evidence-boundary decisions from
that document remain in force unless this document changes them explicitly.

The approved direction is a private Crypto VCP Core owned by
`crypto-vcp-monitor`. It is not a repository-wide shared library and is not an
interface for equity or other skills.

## Problem

The current crypto calibration dynamically imports `historical_scanner`,
`screen_vcp`, and `forward_outcome` from the production `vcp-screener` skill.
That creates three problems:

1. `crypto-vcp-monitor.skill` cannot run standalone.
2. An equity detector change can silently change a previously reproducible
   crypto calibration.
3. Two inherited detector defects produce incorrect crypto observations:
   prices are rounded to two decimals inside the detector, and contraction
   geometry does not require `low < high` or `stop < pivot`.

The equity detector is already in production and has downstream report
consumers. The user has explicitly required that it remain unchanged. The
crypto implementation therefore needs its own core while preserving the proven
parts of the existing detector algorithm.

## Goals

- Make crypto calibration independent of `skills/vcp-screener/` at runtime,
  test time, and package time.
- Preserve the existing ATR ZigZag, fixed-window fallback, multi-start, and VCP
  qualification behavior for legal, ordinary-price inputs.
- Keep full floating-point price precision throughout detection and outcome
  calculation; round only in presentation code.
- Make legal, rejected, illegal, and absent patterns distinct domain results.
- Apply one sampling and overlap policy to treatment and control observations.
- Make calibration reproducible by pinning its right edge and recording input
  provenance.
- Keep the Module's Interface small enough that calibration and a future crypto
  monitor can use it without knowing detector internals.
- Leave the equity source tree, equity package, equity CLI, and equity report
  schema unchanged.

## Non-goals

- No changes under `skills/vcp-screener/` or to
  `skill-packages/vcp-screener.skill`.
- No generic equity/crypto market abstraction, `EquityProfile`, or FMP adapter.
- No migration of other VCP skills to this core.
- No full copy of the equity `analyze_stock` pipeline: relative strength, trend
  template, volume score, composite score, rating, and execution state are not
  part of core v1.
- No new position sizing, order generation, intraday timeframes, perpetual
  futures, or statistical significance model.
- No unrelated Binance retry/cache, CLI, universe, or documentation cleanup.

## Module and Interface

The private Module lives at:

```text
skills/crypto-vcp-monitor/scripts/crypto_vcp_core/
├── __init__.py
├── models.py
├── detector.py
├── outcome.py
└── study.py
```

Only `__init__.py` is the supported Interface. Calibration and future monitor
code may import the following names from it:

```python
def assess_crypto_vcp(
    series: PriceSeries,
    *,
    as_of: date,
    profile: DetectorProfile,
) -> Assessment: ...


def scan_crypto_vcp(
    series: PriceSeries,
    *,
    benchmark: BenchmarkSeries,
    profile: DetectorProfile,
    protocol: StudyProtocol,
) -> StudyResult: ...
```

Callers do not import swing, contraction, validation, pattern-identity,
sampling, or outcome helpers. Tests exercise the same Interface, with focused
private tests allowed only where failure localization would otherwise be poor.

This is a crypto-private interface. Other skills must not import it. The module
does not contain a market selector or claim compatibility with equity data.

## Domain model

### Market data

`Bar` contains a UTC date plus finite, positive `open`, `high`, `low`, `close`,
and finite, non-negative quote volume. It enforces:

```text
low <= open <= high
low <= close <= high
```

`PriceSeries` contains one symbol and a non-empty tuple of unique bars ordered
strictly oldest to newest. The Binance adapter remains responsible for
converting its most-recent-first dictionaries and excluding the current partial
daily bar before constructing a series.

`BenchmarkSeries` is deliberately smaller: a name and strictly chronological,
unique `(date, close)` points with finite positive closes. The equal-weight
index does not need fabricated OHLC or volume fields merely to satisfy the
Interface.

Prices remain `float` to preserve compatibility with current data and fixtures.
The core rejects non-finite values and never rounds a price.

### Configuration

`DetectorProfile` contains only parameters that the crypto VCP detector uses:

- lookback bars;
- ATR period and multiplier;
- minimum contraction duration and count;
- T1 depth minimum and maximum;
- contraction ratio;
- right-shoulder percentage;
- pattern duration minimum and maximum;
- wide-and-loose threshold and maximum duration.

Every count is positive where zero has no meaning. Percentages and ratios are
finite and constrained to their meaningful ranges. Invalid profiles raise
`ConfigurationError` before any bars are scanned.

The current `equity-baseline` calibration candidate becomes
`legacy-equity-thresholds`. It remains a crypto experiment that applies the old
equity numbers to crypto bars; it does not invoke equity code.

`StudyProtocol` contains:

- a required UTC `as_of` date;
- stride bars;
- forward-outcome bars;
- one per-symbol sample-spacing value used across the combined treatment and
  control timeline.

The same profile and protocol objects, including all values, are serialized
into calibration provenance.

`DetectorProfile` has no implicit field defaults. Each named candidate factory
must provide every value so a new field cannot silently change an old study.
Its types and constraints are:

| Field | Type and constraint |
|---|---|
| `lookback_bars` | integer, at least 30 |
| `atr_period` | integer, at least 2 and less than `lookback_bars` |
| `atr_multiplier` | finite float, greater than zero |
| `min_contraction_bars` | integer, at least 1 and less than `lookback_bars` |
| `min_contractions` | integer from 1 through 4 |
| `t1_depth_min_pct` | finite float, at least zero |
| `t1_depth_max_pct` | finite float, at least `t1_depth_min_pct` |
| `contraction_ratio` | finite float, greater than zero and at most 1 |
| `right_shoulder_pct` | finite float from zero through 100 |
| `pattern_duration_min_bars` | integer, at least 1 |
| `pattern_duration_max_bars` | integer, at least the minimum |
| `wide_and_loose_threshold_pct` | finite float, at least zero |
| `wide_and_loose_max_bars` | integer, at least 1 |

`StudyProtocol.as_of` has no default. Its remaining defaults are the approved
calibration settings: `stride_bars=5`, `outcome_bars=60`, and
`sample_spacing_bars=60`. Stride and outcome must be positive integers;
spacing must be a non-negative integer. The aggregate `MIN_SAMPLES` publication
gate remains in the calibration orchestrator because a single-symbol scan
cannot evaluate it. Inside-band strictness is an invariant, not configuration.

### Assessment

`Assessment` is a closed union:

- `ValidPattern`: legal geometry that passes every gating VCP criterion;
- `RejectedPattern`: legal geometry with at least one contraction but failing
  one or more gating VCP criteria;
- `InvalidPattern`: a candidate exists but violates a geometric invariant;
- `NoPattern`: the detector cannot form a candidate with a defined pivot and
  stop.

The result fields are:

```text
Contraction
  label, high_index, high_date, high_price,
  low_index, low_date, low_price, depth_pct, duration_bars

Pattern
  contractions, pivot_price, stop_price, score,
  duration_bars, atr_value, atr_compression_ratio,
  wide_and_loose, right_side_range_ratio, advisory_issues

ValidPattern
  pattern

RejectedPattern
  pattern, rejection_reasons

InvalidPattern
  reason, candidate_contractions, candidate_pivot, candidate_stop

NoPattern
  reason
```

`rejection_reasons` are stable qualification codes rather than rendered prose.
Their exhaustive enum is `TOO_FEW_CONTRACTIONS`, `T1_TOO_SHALLOW`,
`CONTRACTION_NOT_TIGHTENING`, `RIGHT_SHOULDER_TOO_FAR`, or
`PATTERN_TOO_SHORT`. The legacy non-gating findings `T1_TOO_DEEP` and
`PATTERN_TOO_LONG` remain advisory issue codes on `Pattern`; they do not move an
otherwise valid pattern into the rejected cohort.

`NoPattern.reason` is one of `INSUFFICIENT_HISTORY`, `NO_SWING_POINTS`,
`NO_CONTRACTIONS`, or `NO_COMPLETE_CANDIDATE`.

`InvalidPattern.reason` is an exhaustive enum:

- `CONTRACTION_LOW_NOT_BELOW_HIGH`;
- `NON_CHRONOLOGICAL_CONTRACTION`;
- `PIVOT_NOT_ABOVE_STOP`.

Malformed input bars are `DataError`, not `InvalidPattern`: input validity and
candidate validity are different concerns.

`Pattern.score` is an integer from 0 through 100. `atr_value` is finite and
non-negative. `atr_compression_ratio` and `right_side_range_ratio` may be
`None` when their longer ATR window is unavailable or zero; otherwise they are
finite and non-negative. No legal pattern price, depth, ratio, or score is
rounded.

## Detector Implementation

The detector is a behavioral fork of the existing VCP pattern calculator, not
a new trading hypothesis. It retains:

- ATR-based ZigZag swing discovery;
- fixed-window swing fallback when ZigZag yields too few points;
- the top three swing highs as alternative starts;
- at most four contractions;
- minimum contraction duration;
- T1 depth, contraction ratio, right shoulder, and total-duration checks;
- the existing score, ATR compression, wide-and-loose, and right-side tightness
  calculations when they are meaningful to the pattern result.

The implementation changes the inherited behavior only where required by the
crypto contract:

1. No high, low, pivot, stop, ATR, ratio, or depth is rounded inside the core.
2. A contraction is appended only after checking chronological and price
   geometry.
3. A candidate cannot become `ValidPattern` or `RejectedPattern` unless
   `pivot > stop > 0`.
4. Illegal geometry produces `InvalidPattern`; it is not converted into an
   ordinary failed VCP.

The first illegal candidate selected by the existing valid-first/score/length
ordering must not hide a legal candidate from another starting high. The
detector evaluates all configured starts, ranks legal candidates using the
existing ordering, and returns an invalid result only when no legal candidate
exists and at least one illegal candidate was observed.

Start highs are traversed deterministically by descending price and then
ascending chronological index. Each start records its first geometry failure in
construction order. If no legal candidate exists, the `InvalidPattern` from the
first failed start in that traversal order is returned. This fixes both the
reported reason and candidate details when several starts are illegal.

`assess_crypto_vcp` requires `as_of` to match an actual bar date. It ignores all
bars after that date even when the supplied series contains them. If fewer than
`profile.lookback_bars` bars exist through that date, it returns
`NoPattern(INSUFFICIENT_HISTORY)`; a missing as-of bar is `DataError` because
the caller requested an observation that does not exist.

## Study and cohort semantics

`scan_crypto_vcp` uses the latest series bar on or before `protocol.as_of` as
its effective data right edge. This deliberately supports delisted symbols
whose final bar predates the global study date. A series with no bar on or
before the global date returns an empty `StudyResult`; insufficient length is a
normal empty study, not `DataError`.

The first detection cursor is index `profile.lookback_bars - 1` in the
chronological series. Later cursors advance by `protocol.stride_bars` from that
fixed oldest anchor. A cursor is eligible only when exactly
`protocol.outcome_bars` later bars can be read on or before the effective right
edge; additional later bars are ignored for that observation. Therefore every
retained observation has a complete forward window and outcome never has an
insufficient-data state. At each cursor the detector receives only bars through
that cursor.

Cohort assignment is canonical:

| Assessment | Cohort | Outcome eligible |
|---|---|---|
| `ValidPattern` | treatment | yes |
| `RejectedPattern` | control | yes |
| `InvalidPattern` | invalid count only | no |
| `NoPattern` | no-pattern count only | no |

Pattern identity is the complete tuple of every contraction's
`(high_date, low_date)` pair. It does not round or include price. Repeated
detections of the same identity collapse before spacing is applied, and the
earliest chronological observation survives. This first-observation rule also
governs an unexpected later classification change: a pattern first observed as
rejected remains a control observation rather than being relabeled with future
knowledge.

After deduplication, all outcome-eligible observations are sorted together by
detection index. The first survives; a later treatment or control observation
survives only when its detection index is at least `sample_spacing_bars` after
the last retained observation. Spacing therefore operates across the combined
timeline without cohort priority. This chronological first-observation policy
is deterministic and cannot let a later valid pattern displace an earlier
control through look-ahead. A spacing value of zero disables this filter for an
explicit sensitivity run.

Inside-band state is defined only for legal geometry:

```text
band_position = (close - stop) / (pivot - stop)
```

The observation is inside the band only when `0 < band_position < 1`.
Positions exactly zero or one are outside because the outcome race uses strict
barriers.

## Outcome and benchmark semantics

Outcome calculation starts on the bar after detection and reads at most the
configured forward window. On each bar it applies the existing strict rules:

```text
close > pivot  -> breakout
close < stop   -> stop_hit
otherwise      -> continue, then timeout
```

With close-only barriers and legal `pivot > stop`, a same-bar dual hit is
unreachable. The implementation asserts this invariant rather than defining a
tie-breaking policy for an impossible state.

Maximum gain and loss remain measured from detection-day close over the same
forward window. The benchmark return is computed from the benchmark close on
the observation date to the benchmark close aligned with the final configured
forward-window date, even when breakout or stop occurs earlier. It is therefore
contemporaneous and horizon-matched for every observation rather than one tail
window calculated on the CLI execution date.

The benchmark series is supplied to the core already date-aligned. Missing
benchmark coverage for either endpoint is recorded as `None`; it does not alter
cohort assignment or the raw outcome.

## Error handling

- `ConfigurationError`: an invalid profile or protocol; fail before scanning.
- `DataError`: malformed, duplicate, or unsorted bar data; the
  calibration orchestrator records the symbol in `failed_symbols` and continues
  with other symbols.
- `InvalidPattern`: expected candidate-level domain result; count and continue.
- `NoPattern`: expected absence result; count and continue.
- Network, HTTP, cache, and JSON failures remain outside the core in
  `BinanceClient`.

The core performs no filesystem writes, logging, printing, network requests, or
clock reads. `as_of` is required input, which makes tests and replay
deterministic.

## Calibration integration and output

`walk_forward.scan_with_controls` remains temporarily as a compatibility
facade. It converts legacy dictionaries into `PriceSeries`, constructs the
typed profile and protocol, calls `scan_crypto_vcp`, and renders the current
record shape needed by `calibrate_crypto_vcp.compare`. Once callers and tests
use the new Interface directly, the facade may be removed in a separate change.

`calibrate_crypto_vcp.py` no longer builds or passes an equal-weight benchmark
for relative-strength scoring. It may still build the index as the study
benchmark, date-align it per symbol, and pass it to the core for contemporaneous
background returns.

The calibration CLI adds a required `--as-of YYYY-MM-DD` argument with no
execution-date default. It is parsed as an ISO UTC date and copied verbatim into
every `StudyProtocol` and the output provenance. Invalid dates fail argument
parsing; symbols ending before that date use their latest prior bar according to
the scan semantics above.

The calibration output gains an explicit schema version and records:

- core version;
- pinned `as_of`;
- universe version and frozen date;
- complete detector profile and study protocol;
- per-symbol first/last dates and deterministic bar checksum;
- treatment, control, invalid, and no-pattern counts;
- invalid reason counts;
- failed symbols;
- contemporaneous benchmark summaries.

The raw treatment and control records need not be added to the public artifact;
the current aggregate output remains sufficient. Any material change to
headline counts or rates requires intentional regeneration of
`references/VALIDATION.md`, with old and new numbers identified as different
core versions.

Fields inherited from the equity analyzer but unused by calibration—such as
`composite_score` and `execution_state`—are removed from the private scan record
rather than emitted as fabricated or unvalidated values.

The scan Interface returns these concrete result shapes:

```text
Outcome
  outcome_type, event_date, bars_to_event,
  max_gain_pct, max_loss_pct, final_return_pct

Observation
  symbol, detection_index, detection_date, detection_close,
  cohort, pattern, band_position, inside_band,
  outcome, benchmark_return_pct

StudyResult
  symbol, requested_as_of, effective_as_of,
  profile, protocol,
  treatment, control,
  cursor_count, valid_count, rejected_count,
  invalid_count, no_pattern_count,
  invalid_reason_counts,
  duplicate_discard_count, spacing_discard_count,
  first_bar_date, last_bar_date, bar_checksum
```

Treatment and control are chronological immutable observation tuples. Count
fields describe raw cursor assessments before deduplication and spacing, while
the tuple lengths describe retained outcome-eligible samples. Raw assessment
counts sum to `cursor_count`. Dates are UTC `date` values, indices and bar counts
are non-negative integers, and every price in a legal pattern is finite and
positive. `effective_as_of`, `first_bar_date`, and `last_bar_date` are optional
only for an empty study.

`Outcome.outcome_type` is `BREAKOUT`, `STOP_HIT`, or `TIMEOUT`. Its event date is
the first triggering bar date, or the final forward-window date for a timeout;
`bars_to_event` is in `1..protocol.outcome_bars`. Outcome traversal always
continues through the complete forward window after recording the first event.
Gain, loss, and `final_return_pct` are therefore measured over the full window
relative to detection close; final return uses the close of the final configured
forward bar, not the early trigger close. Benchmark return may be `None` only
when an aligned endpoint is unavailable. `Observation.cohort` is `TREATMENT` or
`CONTROL`, and its `pattern` is always legal.

The provenance checksum is SHA-256 over UTF-8 lines for the symbol and every
normalized closed bar on or before `requested_as_of`, in chronological order.
Each bar line contains ISO date plus `float.hex()` encodings of open, high, low,
close, and quote volume separated by ASCII commas. A final newline is included.
This avoids locale and decimal-rendering drift.

## Packaging and dependency rules

All core source files live below the crypto skill directory, so the current
skill packaging mechanism includes them without build-time vendoring. The
packaged crypto skill must contain no imports or relative path lookups into
`vcp-screener`.

The crypto `SKILL.md` and `skills-index.yaml` integration entry are updated to
remove the required local-file dependency and to state that the detector is a
crypto-private behavioral fork. Other VCP skills keep their existing code and
packages.

## Verification strategy

Implementation follows red-green-refactor. The minimum regression matrix is:

1. Legal ordinary-price fixture reproduces the frozen expected detector
   behavior without importing an equity module.
2. Sub-cent pivot remains non-zero through detection and outcome calculation.
3. `low == high` returns `InvalidPattern`.
4. `low > high` returns `InvalidPattern`.
5. `pivot <= stop` never enters treatment, control, inside-band, or outcome.
6. Band positions exactly zero and one are outside; values strictly between are
   inside.
7. Detection cannot observe bars after its cursor, and outcome cannot observe
   bars on or before its cursor.
8. Treatment and control obey the same spacing rule.
9. Duplicate pattern identity collapses without price rounding.
10. Benchmark return uses each observation's actual date range.
11. End-to-end replay is deterministic for bars, profile, protocol, and
    `as_of`.
12. The packaged crypto skill runs without a `vcp-screener` directory.

Before completion, run the crypto tests, package/drift checks, repository format
and lint gates, and the existing equity VCP tests. At implementation start,
record the exact pre-core commit as `<PROTECTED_BASE_COMMIT>`. Verify explicitly
that:

```bash
git diff --exit-code <PROTECTED_BASE_COMMIT> -- \
  skills/vcp-screener skill-packages/vcp-screener.skill
test -z "$(git ls-files --others --exclude-standard -- \
  skills/vcp-screener skill-packages/vcp-screener.skill)"
```

The first command rejects committed or tracked working-tree changes relative to
the baseline. The second rejects untracked additions in either protected path.

## Migration order

1. Freeze crypto-owned legal and pathological fixtures.
2. Add domain models and configuration validation.
3. Fork the detector behind `assess_crypto_vcp`, preserving legal behavior and
   fixing price/geometry invariants.
4. Add outcome calculation and strict band semantics.
5. Add canonical study traversal, pattern deduplication, symmetric spacing, and
   contemporaneous benchmark returns.
6. Replace `walk_forward` dynamic imports with the compatibility facade over the
   new core.
7. Update calibration profiles, provenance, summaries, tests, and docs.
8. Rebuild only `crypto-vcp-monitor.skill` and generated crypto documentation.
9. Run the full verification and equity-zero-diff gates.

Each implementation task must be independently testable and committed as one
logical change. No task may include an edit to the equity VCP implementation or
package.
