# DCA Validation Domain Contract

Status: domain fixture contract for DCA Shadow-Mode Validation
Scope: scan-history reconstruction fixtures and machine-readable expected values only
Fixture file: `backend/tests/fixtures/dca_validation_expected.json`

## Purpose

This contract defines deterministic scan-history cases that backend, frontend, QA, and reviewer cards can use to verify DCA validation without depending on live exchange data. It is intentionally scan-to-scan, not candle-level replay. The companion JSON fixture is the source of exact expected values.

## Default assumptions

All fixture cases use these visible defaults unless a case overrides them:

| Assumption | Value |
| --- | --- |
| Reconstruction method | `scan-to-scan` |
| Long RSI thresholds | 30 / 24 / 16 |
| Short RSI thresholds | 80 / 92 / 95 |
| Allocation ladder | 20% / 20% / 60% |
| Entry fee | 0.04% per simulated fill |
| Exit fee | 0.04% per simulated exit/valuation close |
| Slippage | 0.05% per simulated entry/exit |
| Ambiguous fill rule | Mark `fill_confirmation = assumed_scan_gap` when crossing evidence spans a scan gap greater than 48 hours or intermediate price data is unavailable |
| Insufficient history minimum | 2 usable scans |

Fee rate is represented as `0.0004`; slippage rate is represented as `0.0005`. Fees are calculated from executed notional. For deterministic math, fixture quantities are sized from executed fill notional (`allocation_notional / fill_price`).

## Direction and slippage rules

Long entries are simulated buys:

- Entry fill price = scan mark price × (1 + slippage rate).
- Exit/valuation sell price = scan mark price × (1 - slippage rate).
- Gross PnL is calculated from scan mark prices before slippage.
- Net PnL = gross PnL - entry slippage impact - exit slippage impact - total fees.

Short entries are simulated sells:

- Entry fill price = scan mark price × (1 - slippage rate).
- Exit/valuation buy price = scan mark price × (1 + slippage rate).
- Gross PnL is calculated from scan mark prices before slippage.
- Net PnL = gross PnL - entry slippage impact - exit slippage impact - total fees.

## Deterministic long case: `long_btc_closed_three_entries`

Symbol: `BTC/USDT:USDT`
Direction: `LONG`
Position budget: 10,000 USDT
Lifecycle: closed by validation exit signal at the final scan
Maximum scan gap: 72 hours
Data-quality warnings:

- `scan_gap_over_48h`
- `fewer_than_30_reconstructed_events`
- `assumed_fill_due_to_scan_gap`

Scan sequence:

| Scan | Timestamp | Mark price | Daily RSI | Expected event |
| --- | --- | ---: | ---: | --- |
| L0 | 2026-01-01T00:00:00Z | 100.00 | 35 | No fill; RSI is above first long threshold |
| L1 | 2026-01-02T00:00:00Z | 96.00 | 29 | Entry 1 confirmed: RSI crossed/hit 30; allocation 20% |
| L2 | 2026-01-05T00:00:00Z | 88.00 | 20 | Entry 2 assumed: RSI crossed/hit 24 across a 72-hour scan gap; allocation 20% |
| L3 | 2026-01-06T00:00:00Z | 80.00 | 15 | Entry 3 confirmed: RSI crossed/hit 16; allocation 60% |
| L4 | 2026-01-07T00:00:00Z | 110.00 | 55 | Closed by validation exit signal |

Expected fills:

| Entry | RSI threshold | Allocation | Mark price | Fill price | Quantity | Fee | Slippage impact | Confirmation |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 1 | 30 | 20% | 96.00 | 96.048000 | 20.822922 | 0.80 | 0.9995 | confirmed |
| 2 | 24 | 20% | 88.00 | 88.044000 | 22.715915 | 0.80 | 0.9995 | assumed_scan_gap |
| 3 | 16 | 60% | 80.00 | 80.040000 | 74.962519 | 2.40 | 2.9985 | confirmed |

Closed-position expected metrics:

| Metric | Expected value |
| --- | ---: |
| Total quantity | 118.501355 |
| Average mark entry | 84.345048 |
| Average executed entry | 84.387220 |
| Exit mark price | 110.00 |
| Exit fill price | 109.945000 |
| Exit fee | 5.21 |
| Gross PnL | 3040.15 |
| Entry slippage impact | 5.00 |
| Exit slippage impact | 6.52 |
| Total fees | 9.21 |
| Net PnL | 3019.42 |
| Status | closed |

## Deterministic short case: `short_eth_open_three_entries`

Symbol: `ETH/USDT:USDT`
Direction: `SHORT`
Position budget: 5,000 USDT
Lifecycle: open at latest usable scan and valued against latest mark price
Maximum scan gap: 72 hours
Data-quality warnings:

- `scan_gap_over_48h`
- `fewer_than_30_reconstructed_events`
- `assumed_fill_due_to_scan_gap`

Scan sequence:

| Scan | Timestamp | Mark price | Daily RSI | Expected event |
| --- | --- | ---: | ---: | --- |
| S0 | 2026-02-01T00:00:00Z | 2000.00 | 70 | No fill; RSI is below first short threshold |
| S1 | 2026-02-02T00:00:00Z | 2100.00 | 81 | Entry 1 confirmed: RSI crossed/hit 80; allocation 20% |
| S2 | 2026-02-05T00:00:00Z | 2250.00 | 93 | Entry 2 assumed: RSI crossed/hit 92 across a 72-hour scan gap; allocation 20% |
| S3 | 2026-02-06T00:00:00Z | 2400.00 | 96 | Entry 3 confirmed: RSI crossed/hit 95; allocation 60% |
| S4 | 2026-02-07T00:00:00Z | 1980.00 | 61 | Latest valuation scan; position remains open |

Expected fills:

| Entry | RSI threshold | Allocation | Mark price | Fill price | Quantity | Fee | Slippage impact | Confirmation |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 1 | 80 | 20% | 2100.00 | 2098.950000 | 0.476429 | 0.40 | 0.5003 | confirmed |
| 2 | 92 | 20% | 2250.00 | 2248.875000 | 0.444667 | 0.40 | 0.5003 | assumed_scan_gap |
| 3 | 95 | 60% | 2400.00 | 2398.800000 | 1.250625 | 1.20 | 1.5008 | confirmed |

Open-position expected valuation metrics:

| Metric | Expected value |
| --- | ---: |
| Total quantity | 2.171721 |
| Average mark entry | 2303.473492 |
| Average executed entry | 2302.321755 |
| Latest mark price | 1980.00 |
| Valuation buy fill price | 1980.990000 |
| Valuation close fee | 1.72 |
| Gross open PnL | 702.49 |
| Entry slippage impact | 2.50 |
| Exit/valuation slippage impact | 2.15 |
| Total fees including valuation close | 3.72 |
| Net open PnL | 694.12 |
| Status | open |

## Machine-readable skip reasons

Validation must skip or degrade bad scans with stable skip reason codes. The fixture file includes one case for each required reason:

| Code | Required when |
| --- | --- |
| `insufficient_history` | Fewer than 2 usable scans exist for the symbol |
| `missing_rsi` | Daily RSI is absent or non-numeric |
| `missing_mark_price` | Mark/current price is absent or non-numeric |
| `malformed_scan_result` | Scan result is not an object or has an unusable top-level shape |
| `unsupported_direction` | Position or scan direction is not `LONG` or `SHORT` |
| `missing_position_context` | The validator cannot determine the position symbol, side/direction, or budget context needed to reconstruct fills |

The JSON fixture uses these exact codes under `edge_cases[*].expected.skip_reason` so backend tests can assert against stable values rather than prose.

## Metric contract

A reconstructed symbol result must expose these separable values, even when the implementation later adds more metrics:

- Fill assumptions: method, fee percent/rate, slippage percent/rate, thresholds, allocation percentages.
- Fill details: entry level, threshold, allocation percentage, mark price, fill price, quantity, fee amount, slippage impact, fill confirmation, and whether the fill is eligible for metrics.
- PnL details: gross PnL, entry fees, exit/valuation fees, total fees, entry slippage impact, exit/valuation slippage impact, net PnL.
- Status: `open`, `closed`, or `skipped`.
- Scan-quality details: first scan timestamp, last scan timestamp, usable scan count, max scan gap hours, and data-quality warning codes.

Metrics with insufficient sample size should return `null` plus a reason. For example, Sharpe/Sortino with fewer than 2 return observations should not return `0` as a misleading numeric value.
