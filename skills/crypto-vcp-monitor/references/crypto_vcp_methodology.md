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
