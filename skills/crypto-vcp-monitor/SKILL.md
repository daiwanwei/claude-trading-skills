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
