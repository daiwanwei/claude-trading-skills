---
name: crypto-vcp-monitor
description: Calibrates Minervini Volatility Contraction Pattern thresholds for crypto (BTC, ETH, SOL, BNB) using a keyless-Binance treatment/control backtest over a frozen 46-symbol universe, and reports which parameter sets clear a sample-size gate. No API key required. There is no live/current-day detector yet — daily monitoring of BTC/ETH/SOL/BNB VCP setups is future work, not something this skill does today. Use when the user asks to calibrate or validate crypto VCP thresholds, or asks what evidence exists for a crypto VCP edge; do not use it to ask whether BTC/ETH/SOL/BNB are consolidating right now or where today's pivot is — no code path answers that.
---

# Crypto VCP Monitor Skill

## Purpose

Apply Mark Minervini's Volatility Contraction Pattern analysis to crypto majors
using Binance public data. The algorithm is shared with `vcp-screener`; only the
thresholds differ.

**No API key required** — Binance's public `/api/v3/klines` endpoint is keyless.

## Current status: calibration only, run and recorded

There is no live/current-day monitor. That is by design, not a gap: equity VCP
thresholds do not transfer to crypto, and four symbols produce only 8 valid
patterns across nine years — far too few to pick thresholds from. This skill's
only deliverable so far is `calibrate_crypto_vcp.py`, a treatment/control
backtest over the frozen 46-symbol universe in
`references/calibration_universe.json` that decides whether usable thresholds
exist at all.

**That calibration has already been run**, on 2026-08-24, and its results are
committed — do not re-run the full 46-symbol backtest to answer "does a crypto
VCP edge look real"; read `references/VALIDATION.md` instead. Summary of what
it found: 7 of 8 pre-specified candidates cleared the n >= 30 sample-size gate,
with raw treatment/control breakout-rate gaps of 26-40 percentage points, but
`VALIDATION.md` documents that a substantial share of that gap is confounded
by where the pivot and stop sit relative to the detection-day close — read its
inside-band comparison before treating the raw gap as the headline number, and
read its "swept but inert parameters" note before assuming every crypto
threshold override was calibration-tested.

Nothing here answers "is BTC/ETH/SOL/BNB consolidating right now" or "where is
today's pivot" — there is no code path that runs the calculators against a
live/current date and reports a state. That is `monitor_crypto_vcp.py`,
explicitly out of scope for this skill as it exists today (see "What This
Skill Does NOT Do" below).

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

- **No live/current-day detection.** `monitor_crypto_vcp.py` does not exist.
  This skill cannot say whether BTC/ETH/SOL/BNB are consolidating today, or
  where today's pivot/stop sits — only whether a calibration backtest found
  usable thresholds historically. Building the monitor is future work.
- No position sizing, order generation, or portfolio changes
- No perpetual futures, no intraday or weekly timeframes
- No trading recommendation — `VALIDATION.md`'s inside-band comparison and
  inert-parameter note qualify even the calibration's own gap figures

## Resources

- `references/crypto_vcp_methodology.md` — threshold rationale and equity deltas
- `references/VALIDATION.md` — evidence boundary
- `references/calibration_universe.json` — the frozen symbol list
