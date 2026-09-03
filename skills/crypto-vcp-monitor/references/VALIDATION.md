# Validation Boundary

## What is established

- Binance public klines supply complete daily OHLCV for the calibration universe
  back to each symbol's listing (BTCUSDT and ETHUSDT from 2017-08-17).
- The `vcp-screener` calculators run unmodified on Binance-sourced bars.
- Applying equity thresholds unchanged yields 8 valid VCPs across BTC, ETH, SOL,
  and BNB over roughly nine years — too few to support any performance claim.

## Calibration run (2026-08-24)

Full calibration executed via `calibrate_crypto_vcp.py` against the frozen
universe (`universe_frozen_on: 2026-08-24`, 46 symbols, 0 failed). Settings:
`stride_days=5`, `outcome_days=60`, `control_min_spacing=60`,
`year_window_bars=365`, `min_samples=30`. Artifact:
`reports/crypto_vcp_calibration/crypto_vcp_calibration_2026-08-24.json`.

**What "breakout" means.** Per
`skills/vcp-screener/scripts/calculators/forward_outcome.py`, a resolved
outcome is one of `breakout`, `stop_hit`, or `timeout`, evaluated bar-by-bar
over a 60-bar forward window starting the day after detection: `breakout` is
the first bar whose close exceeds the pivot price, checked before the stop
condition on that bar; `stop_hit` is the first bar whose close falls below
the stop price with no prior breakout; `timeout` is neither within the
window. This is a pivot-resolution label, **not a profit-and-loss outcome** —
a breakout that reverses and closes far below entry on the very next bar
still counts as a breakout, and the reported `median_max_gain_pct` /
`median_max_loss_pct` are the best/worst closes reached anywhere in the
60-bar window measured against the detection-day close, not against the
pivot or an actual fill price. The `treatment` arm is `valid_vcp=True` runs,
deduplicated by pattern identity; the `control` arm is same-symbol days that
produced at least one contraction but failed VCP validation, spaced at least
`control_min_spacing` (60) bars apart so overlapping forward windows don't
inflate the count.

**What actually determines the outcome.** Median `days_to_outcome` is **1**
in both arms — independently re-confirmed by re-scanning `equity-baseline`
and `crypto-moderate` directly from cached records (median exactly 1.0 in
all four: treatment and control, both candidates). And a large share of
samples in both arms are already outside the `[stop, pivot]` band — i.e.
already past the pivot or already past the stop — on the detection day
itself, before the forward window opens at all: 53.4-80.0% of treatment
records and 48.4-60.4% of control records across the eight candidates (see
the band-geometry table below). With outcomes resolving this fast and this
much of the sample already pre-decided at detection, a large share of what
the raw treatment/control gap below measures is which side of the band a
sample already sat on, not what happened afterward. The inside-band
comparison two sections down restricts to samples still inside the band at
detection, to isolate the part of the gap that structure quality can
plausibly explain.

**Per-candidate results (raw)**, sorted by treatment n ascending (all figures
verified against the JSON artifact):

| Candidate | Treatment n | Treatment breakout rate | Control n | Control breakout rate | Gap (pp) | Usable (n≥30) |
|---|---:|---:|---:|---:|---:|:---:|
| crypto-three-contractions | 7 | 71.43% | 1320 | 30.38% | 41.05 | **no** |
| equity-baseline | 52 | 69.23% | 1358 | 29.31% | 39.92 | yes |
| crypto-long-base | 71 | 63.38% | 911 | 33.04% | 30.34 | yes |
| crypto-tight | 146 | 64.38% | 1356 | 34.59% | 29.80 | yes |
| crypto-deep-t1 | 172 | 62.79% | 1300 | 29.85% | 32.94 | yes |
| crypto-moderate | 224 | 62.05% | 1382 | 31.48% | 30.58 | yes |
| crypto-loose | 240 | 59.58% | 1295 | 29.58% | 30.01 | yes |
| crypto-looser | 310 | 55.16% | 1374 | 29.04% | 26.12 | yes |

**Band geometry**, per candidate — where the detection-day close sat inside
`[stop, pivot]` (0 = at the stop, 1 = at the pivot; `pre-resolved` = already
outside `[0,1]`, i.e. past the pivot or past the stop before the forward
window opened):

| Candidate | T median band position | T pre-resolved | C median band position | C pre-resolved |
|---|---:|---:|---:|---:|
| crypto-three-contractions | 1.066 | 57.1% | 0.129 | 56.6% |
| equity-baseline | 1.169 | 80.0% | 0.023 | 60.4% |
| crypto-long-base | 0.740 | 55.4% | 0.229 | 48.4% |
| crypto-tight | 0.855 | 68.4% | 0.208 | 50.9% |
| crypto-deep-t1 | 0.687 | 53.4% | 0.115 | 55.4% |
| crypto-moderate | 0.698 | 58.0% | 0.180 | 52.6% |
| crypto-loose | 0.675 | 56.8% | 0.110 | 55.5% |
| crypto-looser | 0.630 | 54.8% | 0.125 | 53.4% |

A treatment median band position above 1.0 (`equity-baseline`,
`crypto-three-contractions`) means the *median* treatment detection already
sat above its own pivot — over half of those "detections" were already past
the trigger the outcome rule scores against.

**Per-candidate results (inside-band)** — the same comparison restricted to
records with `pre_resolved is False` (still inside `[stop, pivot]` at
detection), sorted by **inside-band gap descending** — deliberately not by
treatment n, to make the reordering visible:

| Candidate | Raw gap (pp) | IB Treatment n | IB Treatment rate | IB Control n | IB Control rate | IB gap (pp) | IB usable (n≥30) |
|---|---:|---:|---:|---:|---:|---:|:---:|
| crypto-looser | 26.12 | 132 | 55.30% | 604 | 30.96% | **24.34** | yes |
| crypto-long-base | 30.34 | 29 | 55.17% | 442 | 32.58% | 22.59 | **no** |
| crypto-moderate | 30.58 | 87 | 56.32% | 617 | 34.20% | 22.12 | yes |
| crypto-deep-t1 | 32.94 | 75 | 54.67% | 546 | 32.78% | 21.88 | yes |
| crypto-tight | 29.80 | 43 | 55.81% | 623 | 36.44% | 19.38 | yes |
| crypto-loose | 30.01 | 98 | 52.04% | 542 | 32.84% | 19.20 | yes |
| equity-baseline | 39.92 | 10 | 50.00% | 503 | 35.79% | 14.21 | **no** |
| crypto-three-contractions | 41.05 | 3 | 33.33% | 537 | 32.59% | 0.74 | **no** |

**The ranking inverts once the confound is removed.** `crypto-looser` has
the *smallest* raw gap (26.12 pp, last of 8) and the *largest* inside-band
gap (24.34 pp, first of 8). `equity-baseline` has the *largest* raw gap
(39.92 pp, first among raw-usable candidates) and falls to 14.21 pp
inside-band — second-to-last, and below the n≥30 gate at IB n=10. The raw
ordering was substantially an ordering of contamination: stricter,
later-triggering candidates (larger `t1_depth_min`, higher `atr_multiplier`,
tighter `contraction_ratio`) detect later in the move, so more of their
treatment samples are already resolved by detection time — which is exactly
what the band-geometry table shows (`equity-baseline`'s treatment
pre-resolved share, 80.0%, is the highest of any candidate; its control
pre-resolved share, 60.4%, is also the highest). A reader who ranked
candidates by the raw gap alone would have ranked them close to backwards.

**A real effect survives, and it is flatter than the raw numbers
suggested.** Five of eight candidates clear the n≥30 gate inside-band
(`crypto-deep-t1`, `crypto-moderate`, `crypto-loose`, `crypto-tight`,
`crypto-looser`), and their inside-band gaps cluster tightly at
**19.20-24.34 pp** — versus a raw gap spread of **26.12-39.92 pp** across the
seven candidates usable on the raw gate (a 13.80 pp spread raw vs. a 5.14 pp
spread inside-band, computed over an overlapping but not identical set of
candidates: two of the seven raw-usable candidates, `equity-baseline` and
`crypto-long-base`, drop out on the stricter inside-band gate;
`crypto-three-contractions` was never raw-usable to begin with and fails
both gates). This is not a negative result: a smaller, tighter effect that barely moves
across five different parameter candidates is a *more* credible shape for a
real effect than a large, widely-scattered raw gap driven by which candidate
happened to detect earliest relative to its own pivot. Say plainly what this
supports: contraction-quality structure predicts *something* — a
19-24 percentage-point inside-band breakout-rate edge, on 442-623 inside-band
control observations per candidate (2,932 combined across the five, though
they draw on overlapping symbol history and are not independent of each
other) and five independently-parameterized candidates that land in the same
narrow band — even after removing the part of the raw gap that barrier
geometry alone explains. It does not support the raw gap's larger magnitude,
and it does not support treating any one candidate's inside-band number as
more precise than the others given they cluster this tightly.

**Withdrawn: the "least crypto-tuned parameter set" argument for
`equity-baseline`.** An earlier version of this document argued that
`equity-baseline` — the unmodified equity threshold set, carrying none of
the crypto-specific widening in `crypto_profile.py` — showed the largest
raw gap among usable candidates, and that the strongest result coming from
the parameter set least tuned to crypto argued against the discrimination
being an artifact of crypto-specific calibration choices. That argument is
withdrawn, not softened: it was tested by cleaning the confound out, and it
failed the test. `equity-baseline` was the *most* contaminated candidate
(80.0% treatment pre-resolved share, the highest of all eight — see the
band-geometry table), its raw gap collapses from 39.92 pp to 14.21 pp
inside-band, and its inside-band n (10) falls below the sample-size gate. A
reader who saw the earlier claim deserves to know it was tested against this
recalibration and did not survive.

Median max-gain / max-loss by arm (percent, relative to detection-day
close; unchanged from the raw-only version of this document — the
instrumentation added here does not touch these figures):

| Candidate | T med gain | C med gain | T med loss | C med loss |
|---|---:|---:|---:|---:|
| crypto-three-contractions | +32.08% | +18.00% | -7.17% | -18.22% |
| equity-baseline | +20.87% | +17.60% | -9.59% | -18.48% |
| crypto-long-base | +16.79% | +16.95% | -14.66% | -18.04% |
| crypto-tight | +22.15% | +18.84% | -12.91% | -18.25% |
| crypto-deep-t1 | +24.36% | +18.09% | -16.11% | -18.12% |
| crypto-moderate | +19.86% | +17.89% | -15.58% | -18.84% |
| crypto-loose | +19.88% | +18.01% | -17.63% | -18.20% |
| crypto-looser | +19.60% | +18.14% | -15.73% | -18.75% |

**What the numbers do and do not support:**

- **No significance test was run, by design.** The 46 symbols move together —
  a broad crypto rally or drawdown moves most of them at once — so they are
  far fewer than 46 independent observations of "does contraction quality
  predict outcomes." The gaps above are descriptive, not inferential; the
  script's own caveat field states this explicitly.
- **Eight candidates were swept** against the same 46-symbol history, so the
  best-looking gap (crypto-three-contractions at 41.05 pp, itself unusable;
  equity-baseline at 39.92 pp among usable candidates) is optimistically
  biased by selection across all eight — it is not evidence that a specific
  parameter set is the "true" edge.
- **Treatment and control arms differ in size substantially, and unevenly
  across candidates.** Among the 7 usable candidates the control/treatment
  ratio ranges from roughly 4.4x (crypto-looser: 1374/310) to roughly 26x
  (equity-baseline: 1358/52); crypto-three-contractions (unusable) pushes
  this to roughly 189x (1320/7). Control arms land in a narrow band
  (911-1382) because they are drawn from the same underlying contraction
  days regardless of which treatment filter is applied; treatment arm size
  is what the candidate's strictness controls. Restricting to the inside-band
  subset shrinks every arm further and unevenly — treatment n drops to
  3-132, control n to 442-623 — which is why the inside-band gate (below) is
  the stricter of the two: two candidates (`equity-baseline`,
  `crypto-long-base`) clear the raw n≥30 gate but fail it.
- **The structure, not any single gap, is the informative part of this
  result:**
  - The control breakout rate is stable at roughly 0.29-0.35 across **all
    eight** candidates (0.2904 to 0.3459) even though each candidate's
    treatment filter is different. That stability is consistent with a
    genuine baseline set by the market and the outcome rule — but it is
    equally consistent with the control arm being dominated by barrier
    geometry that itself barely moves across candidates: the band-geometry
    table above shows control median band position sitting in a narrow
    0.023-0.229 range throughout, regardless of which treatment filter was
    swept. The observation (control rate is stable) stands; the inference
    drawn from it previously (that stability alone marks it as a genuine,
    non-artifactual baseline) does not follow without knowing which of the
    two explanations, or what mix of both, is responsible.
  - Treatment n and raw breakout rate move monotonically across
    crypto-tight → crypto-moderate → crypto-loose → crypto-looser
    (n: 146 → 224 → 240 → 310; breakout rate: 64.38% → 62.05% → 59.58% →
    55.16%), and `contraction_ratio` does progress cleanly across that same
    order (0.70 → 0.75 → 0.80 → 0.85). But per `crypto_profile.py`, this is
    **not** a controlled single-parameter sweep: `t1_depth_min` moves
    non-monotonically across the same four candidates (12.0 → 15.0 → 15.0 →
    12.0), and `atr_multiplier` (2.0 → 2.5 → 2.5 → 3.0) and `lookback_days`
    (120 → 150 → 180 → 180) both vary as well. `crypto_vcp_methodology.md`
    names `atr_multiplier` as the **dominant** knob — the one that
    re-derives the whole ZigZag skeleton — so more than one lever is moving
    at once, and moving in different directions across the sequence. The
    n/breakout-rate monotonicity above is a real, measured observation
    about these four hand-tuned, multi-parameter configurations; it cannot
    be attributed to `contraction_ratio`, or to any single threshold, and
    should not be read as evidence for what a controlled sweep of that one
    parameter would show. It is also a **raw-only** pattern: the same four
    candidates' inside-band treatment breakout rates do not move
    monotonically (55.81% → 56.32% → 52.04% → 55.30% across
    tight/moderate/loose/looser) — another instance of the raw figures
    ordering candidates in a way the cleaned figures do not preserve.
  - Treatment's median max **loss** is smaller in magnitude than control's
    in every one of the 8 candidates (e.g. equity-baseline -9.59% vs
    -18.48%; crypto-deep-t1 -16.11% vs -18.12%). Treatment's median max
    **gain** is close to control's and inconsistent in sign — from -0.16 pp
    (crypto-long-base, where treatment gain is marginally *below* control)
    to +6.27 pp (crypto-deep-t1). The discrimination this calibration finds
    lives mostly in a smaller median close-based drawdown excursion and in
    pivot resolution, not in upside magnitude. (These gain/loss figures
    predate the band-geometry instrumentation and are not split by
    inside/outside band; a candidate whose treatment median is already
    pulled up near or past its pivot has structurally less remaining room to
    register as a large gain, so this discrimination likely shares some of
    the same barrier-geometry confound as the breakout-rate gap. Not
    re-measured here — flagged as a follow-up, not corrected in this pass.)

## What is NOT established

- **Statistical significance of the treatment/control breakout-rate gap.**
  As stated above, no significance test was run, and the correlated-regime
  problem means one cannot be retrofitted from this data without a block
  bootstrap or similar method that accounts for the shared market factor.
  The gaps recorded in the table above are real measurements, not evidence
  of a statistically distinguishable effect.
- **Which single parameter set is the "true" edge**, isolated from the bias
  of having swept eight candidates against the same data and picking
  whichever looked best. The monotone trend in treatment n and raw breakout
  rate across crypto-tight/moderate/loose/looser is suggestive structure,
  not a validated threshold — and, per the note above, those four
  candidates vary `t1_depth_min`, `atr_multiplier`, and `lookback_days`
  simultaneously with `contraction_ratio`, so the trend cannot be
  attributed to `contraction_ratio` specifically, and it does not survive
  into the inside-band breakout rate either. `crypto_profile.py`'s
  candidates remain hypotheses, not settings production code should assume
  are optimal.
- **The raw gap's magnitude**, for any candidate. The inside-band comparison
  above shows a large share of the raw gap is explained by where the
  detection-day close sat relative to the pivot and stop, not by contraction
  quality. The inside-band gap (19.20-24.34 pp across the five candidates
  that clear its stricter n≥30 gate) is the better-supported figure for
  "how much does structure quality predict outcomes" — but it is still a
  raw, undiscounted measurement, not a significance-tested one; see the
  first bullet above.
- Any win rate, expectancy, or risk-adjusted return figure. `breakout_rate`
  is a pivot-resolution rate under the outcome rule described above, not a
  P&L outcome; it says nothing about position sizing, slippage, fees, partial
  fills, or what a trade would have made or lost by the time it was closed.

## Method limits that will persist even after calibration

- **No significance test.** Crypto assets are highly correlated, so n signals are
  far fewer than n independent observations. Raw gaps are descriptive only.
- **Correlated regimes.** The available history spans few distinct crypto cycles,
  so results are not independent draws across market conditions.
- **Partial survivorship control.** Delisted names are re-added manually, which
  reduces but does not eliminate survivorship bias.
- **Multiple comparisons.** Eight candidates are swept; the best-looking one is
  optimistically biased by selection alone.
- **Candidates are not single-axis sweeps.** `crypto-tight` → `crypto-moderate`
  → `crypto-loose` → `crypto-looser` progress cleanly in `contraction_ratio`
  (0.70 → 0.85), but `t1_depth_min`, `atr_multiplier` (the parameter
  `crypto_vcp_methodology.md` calls dominant), and `lookback_days` all vary
  across the same four at the same time. Any monotone trend observed across
  them is a property of these four hand-tuned configurations, not evidence
  attributable to any one threshold.
- **Eight swept parameters never move the artifact.** Arm assignment
  (`valid_vcp`) is set by `_validate_vcp` in `vcp_pattern_calculator.py` from
  exactly four parameters: `min_contractions`, `t1_depth_min`,
  `contraction_ratio`, `pattern_duration_min`. Verified by reading every call
  site: `t1_depth_max` and `pattern_duration_max` only append a
  non-invalidating entry to `_validate_vcp`'s `issues` list (comment: "Don't
  invalidate, just flag") and `_score_vcp` never reads `issues`;
  `wide_and_loose_max_duration` sets the separate `wide_and_loose` flag;
  `min_pct_above_52w_low`, `max_pct_below_52w_high`, `min_rs_rank`, and
  `rs_periods` feed trend-template criteria 5/6/7 and relative strength, which
  reach `execution_state`/`composite_score` but not
  `vcp_pattern_calculator`'s `valid_vcp`; `year_window_bars` only feeds the
  52-week high/low those same criteria use. So `crypto_profile.py`'s
  "always-on crypto adjustments" to `max_pct_below_52w_high` (60.0),
  `min_pct_above_52w_low` (15.0), and `min_rs_rank` (60), and
  `crypto-long-base`'s `pattern_duration_max=400` override, are untested by
  this calibration, not validated by it — this calibration's treatment/control
  split and breakout-rate gaps would be identical at any value of these eight.
  `crypto-long-base`'s only calibration-tested difference from
  `crypto-moderate` is `min_contraction_days` (10 vs 7) and `lookback_days`
  (240 vs 150). (`right_shoulder_pct`, by contrast, is real: it bounds
  contraction-set construction in `_build_contractions_from` before
  `_validate_vcp` ever runs, so equity's 5.0 vs crypto's 12.0 does change
  which contractions exist and therefore can change `valid_vcp`.) See
  `crypto_profile.py`'s module docstring for the same list with source
  references.
- **Treatment-arm overlap is not spacing-controlled, unlike control.** The
  control arm enforces >= `control_min_spacing` (60) bars between same-symbol
  samples (`walk_forward.py`); the treatment arm is deduplicated only by
  pattern identity (T1 high date, last-contraction low date, rounded pivot),
  which does not prevent two distinct-identity treatment patterns from
  landing within 60 bars of each other and sharing most of their forward
  window. Independently re-measured against the full 46-symbol universe
  (2026-08-24, same settings as the calibration run): of `equity-baseline`'s
  52 treatment records, 4 sit within 60 bars of another same-symbol treatment
  record (7.7%); of `crypto-moderate`'s 224, 48 do (21.4%) — both counted as
  adjacent-in-sorted-offset pairs, the same convention as the control arm's
  spacing check. This means the treatment arm's effective (non-overlapping)
  sample size is smaller than its nominal n while the control arm's is not:
  the mirror image of the inflation `control_min_spacing` exists to prevent,
  understating rather than overstating the gap's evidentiary weight. This
  document previously attributed the treatment/control size imbalance solely
  to filter strictness; that remains the dominant driver, but it is not the
  only asymmetry between the two arms.
- **Inside-band filtering trades contamination for sample size.** Removing
  pre-resolved records cleans the barrier-geometry confound out of the gap,
  but it also removes 53.4-80.0% of every candidate's treatment arm (see the
  band-geometry table), which is why `equity-baseline` and `crypto-long-base`
  clear the raw n≥30 gate but not the inside-band one. A larger universe or a
  longer history is the only way to grow the inside-band n for a candidate
  without loosening the filter that makes it inside-band in the first place;
  a future recalibration with more symbols would need to re-check every
  candidate's inside-band n, not just the two that failed it this run.

## Gate decision (Task 13, 2026-08-24)

Gate rule (from the calibration plan): if at least one candidate reaches
treatment n ≥ 30, record which candidates cleared, flag the selection bias
on the best-looking one, and report gap sizes — a follow-up plan for
`monitor_crypto_vcp.py` becomes justified. If no candidate reaches n ≥ 30,
stop and do not build the monitor.

**Two gates now apply, and they disagree on two candidates.** The raw
gate (treatment n ≥ 30 on the unfiltered arm) is what the plan specified;
the inside-band gate (treatment n ≥ 30 restricted to `pre_resolved is
False`) was added by this recalibration once the barrier-geometry confound
was found, because a candidate's raw n can clear 30 almost entirely on
pre-resolved records that the confound explanation, not contraction
quality, accounts for.

- **Raw gate: 7 of 8 pass.** `equity-baseline` (n=52), `crypto-long-base`
  (n=71), `crypto-tight` (n=146), `crypto-deep-t1` (n=172), `crypto-moderate`
  (n=224), `crypto-loose` (n=240), `crypto-looser` (n=310). Only
  `crypto-three-contractions` fails (n=7).
- **Inside-band gate: 5 of 8 pass.** `crypto-deep-t1` (IB n=75),
  `crypto-moderate` (IB n=87), `crypto-loose` (IB n=98), `crypto-tight`
  (IB n=43), `crypto-looser` (IB n=132). `equity-baseline` (IB n=10),
  `crypto-long-base` (IB n=29), and `crypto-three-contractions` (IB n=3)
  fail it — the first two despite passing the raw gate.

**A follow-up monitor plan should use the inside-band gate**, not the raw
one, as the sample-size criterion for which candidates are usable. The raw
gate answers "does this candidate produce at least 30 valid-VCP days"; the
inside-band gate answers "does this candidate produce at least 30 valid-VCP
days whose forward outcome was not already substantially decided at
detection" — the second question is the one a monitor plan actually needs
answered, since a monitor watches for setups *before* they resolve, and the
raw gate's extra candidates (`equity-baseline`, `crypto-long-base`) clear it
almost entirely on records the inside-band analysis shows were already
past their pivot or stop. Both gate results are recorded above so a reader
can see exactly what changes and does not: the same five candidates that
clear the inside-band gate also produced the tightest-clustering,
least-parameter-sensitive gaps (19.20-24.34 pp) in the ranking-inversion
discussion above — the two questions point the same direction.

Gap sizes among the five inside-band-usable candidates range from 19.20 pp
(crypto-loose) to 24.34 pp (crypto-looser), all measured the same way
(treatment breakout rate minus control breakout rate, restricted to
inside-band records, no significance test). Per the multiple-comparisons
caveat above, even this narrower ranking is subject to selection bias from
having swept eight candidates against the same 46-symbol history — it
should not be read as proof that any one of the five is the best crypto
candidate, only that all five are not disqualified by this calibration, and
that `equity-baseline` and `crypto-long-base` now are (on the stricter,
better-justified gate) despite clearing the raw one.

This document records what was measured. It does not recommend which of
the five inside-band-usable candidates, if any, a follow-up monitor plan
should adopt; that finer-grained decision belongs to the follow-up plan,
informed by this evidence.

## Required before any performance claim

The calibration run's date, universe, per-candidate sample sizes, and both
the raw and inside-band treatment/control gaps are recorded above (run date
2026-08-24, universe frozen 2026-08-24, 46 symbols, 0 failed).
`crypto-three-contractions` (raw n=7) remains below 30 signals on either
gate and yields no conclusion; `equity-baseline` (IB n=10) and
`crypto-long-base` (IB n=29) clear the raw gate but not the inside-band one
and should not be treated as validated by this calibration. Any performance
claim should cite the inside-band gap for the five candidates that clear
both gates, not the raw gap — see "The ranking inverts once the confound is
removed" above for why. Still required before any win-rate, expectancy, or
risk-adjusted return claim: an actual P&L backtest with position sizing,
fees, and slippage — `breakout_rate` alone does not supply one, inside-band
or otherwise (see "What is NOT established" above).
