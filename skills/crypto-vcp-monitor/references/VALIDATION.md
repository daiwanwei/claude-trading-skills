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
