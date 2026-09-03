---
layout: default
title: "Crypto VCP Monitor"
grand_parent: English
parent: Skill Guides
nav_order: 16
lang_peer: /ja/skills/crypto-vcp-monitor/
permalink: /en/skills/crypto-vcp-monitor/
generated: true
---

# Crypto VCP Monitor
{: .no_toc }

Calibrates Minervini Volatility Contraction Pattern thresholds for crypto (BTC, ETH, SOL, BNB) using a keyless-Binance treatment/control backtest over a frozen 46-symbol universe, and reports which parameter sets clear a sample-size gate. No API key required. There is no live/current-day detector yet — daily monitoring of BTC/ETH/SOL/BNB VCP setups is future work, not something this skill does today. Use when the user asks to calibrate or validate crypto VCP thresholds, or asks what evidence exists for a crypto VCP edge; do not use it to ask whether BTC/ETH/SOL/BNB are consolidating right now or where today's pivot is — no code path answers that.
{: .fs-6 .fw-300 }

<span class="badge badge-free">No API</span>

[Download Skill Package (.skill)](https://github.com/tradermonty/claude-trading-skills/raw/main/skill-packages/crypto-vcp-monitor.skill){: .btn .btn-primary .fs-5 .mb-4 .mb-md-0 .mr-2 }
[View Source on GitHub](https://github.com/tradermonty/claude-trading-skills/tree/main/skills/crypto-vcp-monitor){: .btn .fs-5 .mb-4 .mb-md-0 }

<details open markdown="block">
  <summary>Table of Contents</summary>
  {: .text-delta }
- TOC
{:toc}
</details>

---

## 1. Overview

# Crypto VCP Monitor Skill

---

## 2. Prerequisites

- **Python 3.9+** with `requests` for live fetches
- **The `vcp-screener` skill must be present in the same repository.** This skill
  loads its calculators directly and fails fast if they are missing. It will not
  run as a standalone `.skill` upload.
- **No API keys**

---

## 3. Quick Start

1. Load the frozen calibration universe from `references/calibration_universe.json`.
2. Fetch full daily history per symbol via `binance_client` (closed bars only).
3. Build the equal-weight benchmark index and align it to each symbol's dates.
4. Walk each symbol's history, collecting a treatment arm (valid VCP) and a
   control arm (contractions present, validation failed).
5. Compare breakout rates and median trajectories per parameter candidate.
6. Report any candidate with n >= 30 as usable; everything else yields no conclusion.

---

## 4. Workflow

1. Load the frozen calibration universe from `references/calibration_universe.json`.
2. Fetch full daily history per symbol via `binance_client` (closed bars only).
3. Build the equal-weight benchmark index and align it to each symbol's dates.
4. Walk each symbol's history, collecting a treatment arm (valid VCP) and a
   control arm (contractions present, validation failed).
5. Compare breakout rates and median trajectories per parameter candidate.
6. Report any candidate with n >= 30 as usable; everything else yields no conclusion.

---

## 5. Resources

**References:**

- `skills/crypto-vcp-monitor/references/VALIDATION.md`
- `skills/crypto-vcp-monitor/references/calibration_universe.json`
- `skills/crypto-vcp-monitor/references/crypto_vcp_methodology.md`

**Scripts:**

- `skills/crypto-vcp-monitor/scripts/benchmark.py`
- `skills/crypto-vcp-monitor/scripts/binance_client.py`
- `skills/crypto-vcp-monitor/scripts/calibrate_crypto_vcp.py`
- `skills/crypto-vcp-monitor/scripts/crypto_profile.py`
- `skills/crypto-vcp-monitor/scripts/universe.py`
- `skills/crypto-vcp-monitor/scripts/walk_forward.py`
