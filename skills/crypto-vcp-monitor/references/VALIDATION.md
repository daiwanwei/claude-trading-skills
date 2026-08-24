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

**Per-candidate results**, sorted by treatment n ascending (all figures
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

Median max-gain / max-loss by arm (percent, relative to detection-day close):

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
  is what the candidate's strictness controls.
- **The structure, not any single gap, is the informative part of this
  result:**
  - The control breakout rate is stable at roughly 0.29-0.35 across **all
    eight** candidates (0.2904 to 0.3459) even though each candidate's
    treatment filter is different. That is what a genuine baseline should
    look like — a rate set by the market and the outcome rule, not by which
    treatment filter happened to be swept — rather than an artifact tied to
    one parameter set.
  - Treatment n and breakout rate move monotonically across
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
    parameter would show. The other three crypto candidates (deep-t1,
    long-base, three-contractions), which tighten along still other axes
    (T1 depth, base duration, contraction count), and equity-baseline,
    which uses an unrelated equity-tuned parameter set, are directionally
    consistent with the same pattern but do not extend it into one single
    monotone ranking — e.g. crypto-tight's rate (64.38%) is slightly higher
    than crypto-long-base's (63.38%) despite crypto-long-base having a
    smaller n. All seven usable candidates show a positive gap, ranging
    from 26.12 pp (crypto-looser) to 39.92 pp (equity-baseline); given the
    document's own no-significance-test position two paragraphs above, that
    is reported as a plain fact, not as evidence that seven positive gaps
    are collectively less likely under chance than one gap alone — the
    candidates share 46 overlapping symbols and, per the point just made,
    are not independent single-axis variants either.
  - Treatment's median max **loss** is smaller in magnitude than control's
    in every one of the 8 candidates (e.g. equity-baseline -9.59% vs
    -18.48%; crypto-deep-t1 -16.11% vs -18.12%). Treatment's median max
    **gain** is close to control's and inconsistent in sign — from -0.16 pp
    (crypto-long-base, where treatment gain is marginally *below* control)
    to +6.27 pp (crypto-deep-t1). The discrimination this calibration finds
    lives mostly in a smaller median close-based drawdown excursion and in
    pivot resolution, not in upside magnitude.
  - `equity-baseline` — the unmodified equity threshold set, carrying none
    of the crypto-specific widening in `crypto_profile.py` — shows the
    **largest gap among usable candidates** (39.92 pp). That the strongest
    result comes from the parameter set least tuned to crypto argues against
    the discrimination being an artifact of crypto-specific calibration
    choices, though its n=52 is the second-smallest usable sample and its
    ratio of history is also the shortest surviving equity-style filtering.

## What is NOT established

- **Statistical significance of the treatment/control breakout-rate gap.**
  As stated above, no significance test was run, and the correlated-regime
  problem means one cannot be retrofitted from this data without a block
  bootstrap or similar method that accounts for the shared market factor.
  The gaps recorded in the table above are real measurements, not evidence
  of a statistically distinguishable effect.
- **Which single parameter set is the "true" edge**, isolated from the bias
  of having swept eight candidates against the same data and picking
  whichever looked best. The monotone trend in treatment n and breakout
  rate across crypto-tight/moderate/loose/looser is suggestive structure,
  not a validated threshold — and, per the note above, those four
  candidates vary `t1_depth_min`, `atr_multiplier`, and `lookback_days`
  simultaneously with `contraction_ratio`, so the trend cannot be
  attributed to `contraction_ratio` specifically. `crypto_profile.py`'s
  candidates remain hypotheses, not settings production code should assume
  are optimal.
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

## Gate decision (Task 13, 2026-08-24)

Gate rule (from the calibration plan): if at least one candidate reaches
treatment n ≥ 30, record which candidates cleared, flag the selection bias
on the best-looking one, and report gap sizes — a follow-up plan for
`monitor_crypto_vcp.py` becomes justified. If no candidate reaches n ≥ 30,
stop and do not build the monitor.

**Result: the gate passes.** Seven of the eight candidates clear treatment
n ≥ 30 (`usable: true` in the artifact): `equity-baseline` (n=52),
`crypto-long-base` (n=71), `crypto-tight` (n=146), `crypto-deep-t1` (n=172),
`crypto-moderate` (n=224), `crypto-loose` (n=240), `crypto-looser` (n=310).
Only `crypto-three-contractions` fails the gate (n=7, `usable: false`) and
yields no conclusion.

Gap sizes among the seven usable candidates range from 26.12 pp
(crypto-looser) to 39.92 pp (equity-baseline), all measured the same way
(treatment breakout rate minus control breakout rate, no significance
test). `equity-baseline`'s gap is the largest of the usable candidates; per
the multiple-comparisons caveat above, that ranking is itself subject to
selection bias from having swept eight candidates against the same 46-symbol
history, and should not be read as proof that the unmodified equity
threshold set is the best crypto candidate — only that it is not
disqualified by this calibration.

This document records what was measured. It does not recommend which
candidate, if any, a follow-up monitor plan should adopt; that decision
belongs to the follow-up plan, informed by this evidence.

## Required before any performance claim

The calibration run's date, universe, per-candidate sample sizes, and the
treatment/control gap are recorded above (run date 2026-08-24, universe
frozen 2026-08-24, 46 symbols, 0 failed). `crypto-three-contractions` (n=7)
remains below 30 signals and yields no conclusion. Still required before any
win-rate, expectancy, or risk-adjusted return claim: an actual P&L backtest
with position sizing, fees, and slippage — `breakout_rate` alone does not
supply one (see "What is NOT established" above).
