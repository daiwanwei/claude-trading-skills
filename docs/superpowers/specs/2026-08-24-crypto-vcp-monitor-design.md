# Crypto VCP Monitor Design

## Problem

We want Minervini VCP analysis for BTC, ETH, SOL, and BNB using Binance data.
The `vcp-screener` calculators already implement the algorithm and are pure
functions over OHLCV records, so a Binance adapter runs them unchanged. A
throwaway probe confirmed this end-to-end.

The algorithm's thresholds, however, are calibrated for S&P 500 large caps and
do not transfer:

- Measured ATR14 as a share of price: BTC 2.85%, ETH 4.01%, SOL 4.39%, BNB 2.77%
  — roughly 2-3x a typical large-cap. Every depth-percentage threshold is
  mis-scaled.
- All four names fail trend-template criterion 6 (within 25% of the 52-week
  high) by a wide margin: BTC -38.8%, ETH -49.2%, SOL -62.8%, BNB -49.4%.
  Crypto routinely draws down 70-80%, so a 25% band gates out everything
  outside a raging bull market.
- Nine values that need to move for crypto are hardcoded or not threaded
  through to the CLI.

Picking replacement numbers by intuition would be guesswork, and the parameters
are fragile: raising `atr_multiplier` from 1.5 to 2.5 changes BNB's detected T1
depth from 25.4% to 8.95%, because it re-derives the whole ZigZag skeleton.

So the first deliverable is a **calibration backtest**, not a monitor.

### Sample-size constraint

A walk-forward scan over full history produced these valid-VCP counts:

| Parameter set | BTC | ETH | SOL | BNB | 4-symbol total | 15-symbol total |
|---|---|---|---|---|---|---|
| equity defaults | 1 | 2 | 1 | 4 | **8** | 29 |
| loosened | 0 | 7 | 2 | 4 | **13** | 36 |
| loosened further | 0 | 9 | 2 | 10 | **21** | 49 |

Eight signals across nine years cannot support a claim about edge. Calibration
therefore runs over a 30-50 symbol universe (estimated 60-160 signals) even
though the monitor itself only watches four names.

## Approved design

### Scope

New skill `skills/crypto-vcp-monitor/`. Spot daily bars only. Output is an
observation report — VCP state, pivot, last contraction low, distance — and
nothing else.

**Non-goals:** no position sizing, no `trader-memory-core` integration, no 4H or
weekly timeframes, no perpetual futures, no order generation.

### Components

```
skills/crypto-vcp-monitor/
├── SKILL.md
├── references/
│   ├── crypto_vcp_methodology.md    # parameter rationale, deltas vs equity VCP
│   ├── VALIDATION.md                # evidence boundary
│   └── calibration_universe.json    # frozen symbol list
└── scripts/
    ├── binance_client.py            # klines paging, caching, partial-bar handling
    ├── universe.py                  # loads the frozen universe
    ├── crypto_profile.py            # single source of truth for crypto thresholds
    ├── calibrate_crypto_vcp.py      # deliverable 1: calibration backtest
    ├── monitor_crypto_vcp.py        # deliverable 2: daily monitor
    ├── report_generator.py
    └── tests/
```

| Component | Responsibility | Depends on |
|---|---|---|
| `binance_client` | symbol -> most-recent-first OHLCV list | stdlib + `requests` |
| `universe` | the frozen 30-50 symbol calibration list | `binance_client` |
| `crypto_profile` | all crypto-specific thresholds in one place | nothing |
| `calibrate` / `monitor` | compose the above, drive the shared calculators | the three above + `vcp-screener` |

### Cross-skill dependency

`calibrate` and `monitor` load `vcp-screener`'s modules via
`importlib.util.spec_from_file_location`, following the existing pattern in
`skills/pre-trade-discipline-gate/scripts/check_pre_trade_discipline.py`. Unlike
that case the dependency is **fail-fast, not graceful** — the calculators are the
core algorithm, not an optional enrichment.

Declare the dependency in SKILL.md Prerequisites and as an
`integrations[].type: local_file` entry in `skills-index.yaml`.

Accepted cost: `crypto-vcp-monitor.skill` will not run standalone in the Claude
web app. A 30-50 symbol backtest is inherently a repo-context task. If standalone
distribution is ever needed, `package_skills.py` can vendor the shared
calculators at build time; not now.

### Data layer

**Endpoint.** `GET /api/v3/klines`, keyless, `limit=1000`, weight 10. Page with a
`startTime` cursor advancing `raw[-1][0] + 86_400_000` until a short page
returns. Cache one JSON per UTC day. Budget: 50 symbols x ~4 pages x weight 10 =
2000 against a 6000/min IP limit.

**Partial bars.** Crypto trades 24/7, so there is always an in-progress daily
bar. Measured: BTC's in-progress bar carried 1,155 volume against the prior full
day's 15,367. `historical` contains **closed bars only**; `quote.price` comes
separately from `/api/v3/ticker/price`.

This split matches `analyze_stock`'s internals — it reads `quote["price"]` for
pivot proximity and the trend template, and `historical[0]` for pattern and
volume. Result: volume math only ever sees complete sessions, pivot distance
always sees the live price.

**Volume units.** Feed `quoteVolume` (USDT notional) as the `volume` field, not
base-asset volume. SOL ranged from $8 to $253; base volume is not comparable
across a 120-180 bar lookback, since identical dollar flow reads as 30x the
"volume" at the low end. `quoteVolume` is the direct analog of equity dollar
volume. Retain base volume in the raw record for reference.

**Frozen universe.** Select USDT spot pairs, excluding stablecoin pairs
(USDC/FDUSD/TUSD/USD1/DAI) and leveraged tokens (UP/DOWN/BULL/BEAR), requiring
>= 1095 bars, ranked by 24h `quoteVolume`, top 30-50.

Do **not** re-derive this from live `exchangeInfo` on each run — that infers the
historical universe from today's survivors. MATICUSDT delisted 2024-09-10 yet
Binance still returns its full 1,965-bar history, so delisted names are
recoverable if we keep the list ourselves. Freeze the selection into
`references/calibration_universe.json` with selection date, criteria, and
manually re-added delisted symbols. Commit it; the backtest must be replayable.

### Parameterization of shared calculators

Nine hardcoded thresholds become parameters. **Every default equals its current
value**, so equity behavior is unchanged.

| File | Parameter | Current |
|---|---|---|
| `calculators/vcp_pattern_calculator.py:477` | `right_shoulder_pct` | 5.0 |
| `calculators/vcp_pattern_calculator.py:528` | `t1_depth_max` | 35.0 |
| `calculators/vcp_pattern_calculator.py:570,573` | `pattern_duration_min` / `max` | 15 / 325 |
| `calculators/vcp_pattern_calculator.py:603` | `wide_and_loose_max_duration` | 10 |
| `calculators/trend_template_calculator.py` c5 | `min_pct_above_52w_low` | 25.0 |
| `calculators/trend_template_calculator.py` c6 | `max_pct_below_52w_high` | 25.0 |
| `calculators/trend_template_calculator.py` c7 | `min_rs_rank` | 70 |
| `calculators/relative_strength_calculator.py:27` | `RS_PERIODS` module constant -> argument | 63/126/189/252 |
| `historical_scanner.py:142` | thread `year_window_bars` through `scan_history` | 252 |

`vcp-screener` is `status: production` and part of the `swing-opportunity-daily`
workflow, so this change carries risk. It is contained by keeping defaults
identical and proving it with a golden test (see Verification).

### Period conversion

Bar counts are **not** converted to trading-day equivalents. SMA50/150/200 stay
at 50/150/200 bars, matching TradingView and crypto convention.

Two deliberate exceptions, where the quantity is defined in calendar terms
rather than by bar-count convention:

- **52-week high/low: 365 bars, not 252.** "200-day moving average" names a bar
  count; "52 weeks" names a calendar span, and crypto usage means 365 days. Using
  252 would label an 8.3-month extreme as a 52-week extreme.
- **RS periods: 90/180/270/365, not 63/126/189/252.** Those four numbers are
  trading-day renderings of 3/6/9/12 months, with no crypto convention to
  preserve. RS is a cross-asset momentum comparison, so the time axis must be
  consistent.

### Relative strength benchmark

Replace SPY with an **equal-weight index** built from the frozen universe (equal
weighting of component returns, not market-cap weighting). Compare BTC against
the index; compute an additional vs-BTC RS for alts.

Implementation contract: `scan_history` assumes `sp500_history` is **index-aligned**
with `historical`, but listing dates differ per symbol. The benchmark series must
be **date-aligned first**. This was hit in the probe and is covered by a test.

### Calibration harness

Frozen universe -> full history -> date-aligned equal-weight benchmark -> per
symbol walk-forward (stride 5, `outcome_days` 60) -> collect two groups ->
compare.

**Why not reuse `scan_history` directly.** It drops the control group at
`historical_scanner.py:159` (`if not result.get("valid_vcp"): continue`). Rather
than widen the production-side change further, `calibrate` implements its own
~40-line cursor loop while reusing `build_quote_from_history` — the genuinely
hard part (no-look-ahead quote synthesis). Control-group collection is a
calibration concern and does not belong in `vcp-screener`.

**Control group definition.** Not "valid VCP vs nothing", but days where
`num_contractions >= 1` and `valid_vcp is False`. Two reasons:

1. Those days still have a defined pivot and stop (last contraction's high and
   low), so the outcome rule is identical across groups. Without a stop,
   `stop_hit` is undefined and the groups are not comparable.
2. The comparison becomes sharper: it tests whether **contraction structure
   quality** predicts outcomes, which is exactly the VCP claim.

**Overlap control.** With stride 5 and a 60-day forward window, 12 consecutive
cursor positions produce near-identical forward windows. The treatment group is
protected by pattern-identity dedup; the control group is not. Control samples
require a **minimum 60-day spacing per symbol**, or the control group inflates to
roughly 10x the treatment group while being largely one observation.

**Outputs.** Breakout rate, median `max_gain_pct`, median `max_loss_pct`, and
sample count for treatment vs control, plus same-period buy-and-hold as
background.

**Overfitting controls.** Run 6-12 **pre-specified** parameter candidates only; no
broad grid search. Report sample count per candidate. **Any candidate with n < 30
is marked unusable and yields no conclusion.**

Significance testing (block bootstrap by date, to handle the fact that crypto
assets move together and n signals are not n independent observations) is
deliberately deferred. The first pass reports raw gaps; formal testing is only
worth building if a gap looks large enough to matter.

### Monitor output

Markdown plus JSON. Per symbol: VCP state with each contraction's depth and
duration, `execution_state`, pivot price, last contraction low (natural stop),
distance from pivot, risk percentage (pivot to stop), all seven trend-template
criteria with pass/fail, and `atr_compression_ratio`.

`atr_compression_ratio` is the load-bearing VCP metric — measured at 1.50-1.74
for all four names, meaning volatility is currently expanding, the opposite of a
contraction pattern.

Every report states which calibration produced its thresholds and that run's
sample size. Parameters that failed the n >= 30 bar are labeled unverified.

## Delivery order

Calibration is the first deliverable; the monitor consumes its output, so it
comes second.

1. **Parameterize the shared calculators** with identical defaults, guarded by
   the golden test. Nothing else can proceed safely until equity behavior is
   proven unchanged.
2. **Data layer** — `binance_client`, `universe`, frozen
   `calibration_universe.json`. The exact symbol count inside the 30-50 range is
   fixed at freeze time and recorded in that file alongside the selection date
   and criteria.
3. **`calibrate_crypto_vcp.py`** — cursor loop, control-group collection,
   treatment-vs-control comparison, pre-specified candidate sweep.
4. **Run the calibration**, record results in `references/VALIDATION.md`, and
   choose the crypto defaults for `crypto_profile.py`. If no candidate clears
   n >= 30, stop here and report that instead of shipping a monitor built on
   unusable numbers.
5. **`monitor_crypto_vcp.py`** and the report generator.
6. **Documentation obligations** (below).

## Verification

Tests are written first, per CLAUDE.md.

| # | Coverage | Rationale |
|---|---|---|
| 1 | Full `vcp-screener` suite green, plus a golden test comparing equity-path output byte-for-byte before and after parameterization | The only proof that the production skill is behaviorally unchanged. Highest priority |
| 2 | `binance_client`: paging boundaries, partial-bar exclusion, cache hits (fixtures, no network) | |
| 3 | `universe`: frozen-list loading, delisted symbols retained | Guards against survivorship-bias regression |
| 4 | Benchmark date alignment across differing listing dates | Hit during probing |
| 5 | Control-group 60-day minimum spacing | Guards against sample inflation |
| 6 | End-to-end replay: fixed fixture produces fixed output | Follows the `parabolic-short-trade-planner` convention |

Post-implementation documentation obligations from CLAUDE.md apply: run
`scripts/generate_skill_docs.py --skill crypto-vcp-monitor`, add catalog category
and API-matrix rows in both languages, and update both READMEs.
