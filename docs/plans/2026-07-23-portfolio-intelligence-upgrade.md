# Portfolio Intelligence Upgrade Plan

## Goal
Turn the Portfolio page from a collection of account tables into a read-only decision and performance desk that answers, at a glance:

- What do I own and what is currently at risk?
- How much did I actually make today, this week, this month, and over the selected period?
- Which pairs, directions, holding periods, and leverage levels generate or destroy profit?
- How much capital was deposited, transferred, deployed, and withdrawn?
- Are the displayed numbers current, complete, and sourced from MEXC?

The exchange integration remains read-only. This plan adds no order placement, cancellation, leverage changes, or transfers.

## Audit findings

### What already exists
- Authenticated MEXC balances, open positions, trades, closed-position history, and order history are fetched and cached.
- Position history currently contains the useful base fields: symbol, side, size, entry/exit, reported net PnL, position ROI, leverage, and open/close times.
- The UI already has performance cards, an equity chart, daily PnL heatmap, allocation chart, trade attribution, health score, and BTC benchmark components.
- Live production data currently verifies 49 closed positions, 48 wins, one loss, and $49.23 reported net realised PnL.
- **This 49-position / $49.23 sample is frozen as a deterministic redacted fixture contract.** It is not a moving test target — production counts are audit evidence, not test assertions. The fixture is checked into a dedicated test module, redacted of secrets, and reproduced via a factory that takes the frozen positions dict. Regression tests pin each position's `closeProfitLoss` and `profitRatio` values; any production count shift updates the audit evidence, not the fixture.

### Correctness problems to solve before adding more charts
1. **The current “Equity Curve” is not an equity curve.** `PortfolioSnapshot.total_balance_usd` is always stored as `None`; the fallback plots each snapshot’s current open-position unrealised PnL. It therefore resets to zero when flat, can go negative, emits thousands of five-minute points, and does not represent cumulative realised PnL or account equity.
2. **`total_pnl_percent` is mathematically invalid as portfolio return.** It sums every position’s leveraged ROI, producing 378.5% for the present sample. Position ROIs cannot be added to derive account return.
3. **Drawdown is mislabeled.** The existing value is drawdown of cumulative closed-trade PnL from a zero baseline. It is not account-equity drawdown and excludes unrealised adverse excursion.
4. **Sharpe is only a per-trade PnL dispersion score.** It uses absolute trade PnL, so sizing changes affect it; it should not be presented as a conventional portfolio Sharpe.
5. **Futures risk uses spot assets as the balance denominator.** Spot USDT/ADA/DOGE/POL must not be treated as available MEXC futures collateral.
6. **Health score is misleading while flat.** Production currently shows grade B / 65 with no open positions; “not applicable” is more honest than a synthetic portfolio grade.
7. **Allocation is not labeled by account type.** The existing chart is MEXC spot allocation, not total portfolio or futures collateral allocation.
8. **Daily grouping is hard-coded to UTC.** Period analytics should accept a user timezone and clearly display the selected timezone.
9. **History is capped at 200 rows.** Both fetch and load paths silently truncate history and do not expose coverage, pagination, or oldest/newest synchronized timestamps.
10. **The deduplication key is fragile.** `(user, exchange, symbol, close_time)` can collide for partial closes or multiple records at the same timestamp. Persist MEXC’s stable position/history identifier.
11. **Liquidation reason is inferred from ROI.** A very negative ROI is not proof of liquidation; the UI should show `unknown` unless MEXC supplies an authoritative reason.
12. **Analytics lack focused tests.** There are no dedicated backend tests for the current performance, daily PnL, or equity calculations.
13. **Information hierarchy is too deep.** Analytics is the last top-level tab and then adds six nested tabs, hiding the information users need most.

## Non-negotiable accounting rules
- MEXC’s closed-position `closeProfitLoss` is the authoritative reported realised PnL for a closed position. **Do not assert whether this field is net or gross of fees until MEXC's API documentation or a verified test fixture confirms the treatment.** Until proven, label the field exactly as `MEXC-reported closed-position PnL`; do not deduct estimated trading fees and do not silently treat it as net-of-fees.
- Funding, rebates, bonuses, deposits, withdrawals, and transfers are separate ledger categories unless MEXC explicitly embeds them in a field.
- Never label margin used, notional, the first recorded trade, current spot balance, or cumulative PnL as “starting investment.”
- Starting equity and account return stay `unknown` until an opening balance or complete capital-flow history is available.
- Keep spot assets, futures wallet equity, open-position margin, realised PnL, unrealised PnL, and cash flows separate in storage, APIs, and UI.
- Every calculated metric must carry a basis/source label, for example `MEXC reported realised PnL`, `closed-position reconstruction`, or `account snapshot`.
- Public market prices may value assets but may never replace authenticated MEXC account truth.

## Target information architecture

### 1. Portfolio Overview — default view
Persistent freshness bar:
- Exchange and account type.
- Last successful MEXC sync.
- History coverage: oldest/newest record and fetched/available count.
- Fresh / stale / partial / error state with retry action.

Primary KPI strip:
- Futures equity.
- Available futures balance.
- Realised PnL for selected period.
- Unrealised PnL now.
- Net cash flow for selected period.
- Margin usage and liquidation-risk state.

Performance summary strip:
- Today, current week, current month, selected-period net PnL.
- Profit per calendar day and per active trading day.
- Trades, win rate, expectancy, and profit factor.
- Portfolio return only when opening equity and cash flows support it; otherwise show `Unavailable — capital history incomplete`.

Main visual grid:
- Account equity line: actual futures wallet equity snapshots, adjusted for cash flows when available.
- Realised PnL line/bar: cumulative closed-position PnL and daily/weekly bars.
- PnL calendar with timezone selector and daily drill-down.
- Exposure card: long, short, net, margin used, available balance, nearest liquidation distance.

### 2. Performance Lab
Period selector: 7D, 30D, month-to-date, quarter-to-date, year-to-date, all synchronized history, and custom dates.

Visuals:
- Weekly/monthly PnL bars with trade count overlay.
- Symbol contribution horizontal bars with contribution percentage.
- Long versus short comparison: PnL, win rate, expectancy, ROI, and count.
- Pair × direction matrix to reveal concentration such as SNDK-short dependence.
- Holding-duration buckets: under 15m, 15–60m, 1–4h, 4–24h, 1–3d, over 3d.
- PnL/ROI distribution histogram and outcome scatter plot (duration versus ROI, bubble size = margin/notional where available).
- Leverage buckets and time-of-day/day-of-week heatmaps.
- Winning/losing streak timeline.

Calculated statistics:
- Gross profit, gross loss, net realised PnL.
- Average/median PnL and ROI.
- Average win/loss, payoff ratio, profit factor, expectancy per trade.
- Wins, losses, break-even trades, longest streaks.
- Best/worst trade and best/worst active day.
- Calendar-day, active-day, weekly, and 30-day pace, clearly labeled as actual or normalized.
- Realised-PnL drawdown from closed trades, explicitly separate from account-equity drawdown.
- Concentration: top pair, top direction, top-three pairs, and Herfindahl-style contribution concentration.
- Sample-quality flags: short history, too few losses, incomplete capital ledger, or highly concentrated results.

### 3. Trade Explorer
Replace the static closed-position table with:
- Server-side pagination and complete-history coverage.
- Filters for date, symbol, side, result, leverage, duration, and close reason.
- Sort by PnL, ROI, duration, and close time.
- Search and CSV export.
- Expandable trade drawer showing entry/exit, duration, margin/notional, MEXC reported PnL, orders/fills, fees, funding if available, linked Miraj scan, journal tags, and notes.
- Clear badges for `MEXC reported`, `derived`, `unknown`, and `partial history`.

### 4. Cash Flow & Account Ledger
Read-only ledger grouped into:
- Deposits and withdrawals.
- Spot ↔ futures transfers.
- Realised trading PnL.
- Funding payments/receipts.
- Trading fees and rebates.
- Bonuses/credits where MEXC exposes them.
- Manual opening-balance adjustment only as an explicitly labeled fallback.

This view enables truthful starting equity, ending equity, net deposits, and time-weighted account return. If complete history is unavailable, show coverage gaps instead of inventing a return.

### 5. Holdings & Risk
- Separate `Spot Holdings`, `Futures Wallet`, and `Open Futures Positions` sections.
- Spot allocation chart stays in the spot section.
- Futures collateral chart uses authenticated futures assets only.
- Open-position risk shows notional, margin, leverage, maintenance margin, liquidation price/distance, unrealised PnL, and concentration.
- When flat, risk and health cards show `No open futures risk` / `Not applicable`, not an arbitrary grade.

## MEXC ingestion upgrade

### Account truth to fetch and normalize
Use the existing encrypted, server-side MEXC credential path and first add a capability probe with redacted raw fixtures. Normalize only fields observed from the authenticated response.

1. Futures account assets:
   - wallet/equity balance by settlement asset;
   - available balance;
   - frozen/order margin;
   - position margin;
   - unrealised PnL;
   - account asset timestamp.
2. Open positions:
   - stable position ID;
   - side, size, entry, mark, leverage, margin mode;
   - position margin, maintenance margin, liquidation price;
   - realised/unrealised PnL where supplied.
3. Closed-position history:
   - MEXC history/position ID;
   - authoritative `closeProfitLoss` and `profitRatio`;
   - close volume, average entry/exit, leverage, open/close timestamps;
   - raw close state/reason without ROI-based inference.
4. Orders and fills:
   - stable order/trade IDs;
   - side action, filled size/price, reduce-only, fee, fee currency;
   - linkage to a position where IDs/timestamps permit deterministic matching.
5. Funding and cash flows:
   - funding payment history;
   - spot/futures transfer history;
   - deposits, withdrawals, rebates, or bonuses when supported and authorized.

### Synchronization behavior
- Replace the hard 200-row truncation with cursor/page synchronization until the endpoint is exhausted or a documented exchange boundary is reached.
- Persist source IDs and use idempotent upserts.
- Store per-stream sync cursors and coverage metadata: status, last success, oldest/newest item, rows fetched, source total if known, and error.
- Refresh current account/open positions frequently; sync immutable history incrementally.
- Rate-limit and back off on MEXC failures; serve last-known data with a visible stale/partial state.
- Never log API secrets or complete raw private payloads. Keep only redacted fixtures needed for normalization tests.

## Data model changes

Update `backend/models.py` and the project’s schema-initialization/migration path.

### Extend `PositionHistory`
- `exchange_position_id` (unique within user/exchange).
- `source_state` / authoritative close reason when available.
- `reported_pnl` and `reported_roi_pct` naming or compatibility aliases to clarify origin.
- `margin_used`, `notional_usd`, and `duration_seconds` where derivable with known contract size.
- `raw_fees`, `funding_pnl`, and `net_accounting_status` only when the source supports them.
- `source_updated_at` and `synced_at`.

### Add account/ledger tables
- `FuturesAccountSnapshot`: equity, available balance, margin fields, unrealised PnL, settlement asset, timestamp.
- `ExchangeLedgerEntry`: stable source ID, category, asset, amount, USD value, timestamp, linked position/order IDs, and provenance.
- `ExchangeSyncState`: stream, cursor, coverage timestamps/counts, status, error, and last successful sync.

### Snapshot retention
- **Stop writing a duplicate high-frequency snapshot when no material account value changed.** A change is material when equity, available balance, unrealised PnL, or open-position count differs from the prior snapshot by more than 0.01 USD / 1 position.
- **Deterministic downsampling windows:**
  - Fresh (≤ 7 days): 5-minute granularity, keep all points.
  - Recent (8–30 days): keep every 4th point (20-minute effective granularity).
  - Near (31–90 days): hourly on the hour.
  - Archive (> 90 days): daily at 00:00 UTC snapshot.
- **Phase 0 must not require a production migration.** Phase 0 operates entirely within the existing `PortfolioSnapshot` table and `PositionHistory` data. No new tables, columns, or indexes are added in Phase 0.
- **Future schema migration steps (Phases 1–4):** each new table/column addition must specify:
  - Exact forward migration: `alembic revision --autogenerate` with the exact table/column DDL.
  - Exact backward migration (rollback): `alembic downgrade` with the exact `downgrade()` DDL.
  - Data backfill: the SQL or script that populates the new column/table from existing data, with a `backfill_complete` flag.
  - Compatibility: which older API versions can still serve while the migration runs (backward-compatible reads, dual-write period if needed).
  - Rollback: the exact steps to revert a migration that has already partially run (e.g. `ALTER TABLE ... DROP COLUMN` after backfill reversal).
  - Failure behavior: if a migration step fails (connection loss, constraint violation, timeout), the system must report the error and remain in the last-known-good schema state; no partial migration blocks the application.
- **Unrecoverable historical gaps:** explicitly state which gaps cannot be backfilled (e.g. pre‑Phase-2 snapshots that lack `total_balance_usd` are permanently null; pre‑Phase-2 position history that lacks `exchange_position_id` cannot be retroactively linked). These gaps are documented in the API response under `coverage.unrecoverable_gaps`.

## API design

Keep existing routes temporarily for compatibility, but add a single versioned analytics contract so all widgets share filters and provenance.

Suggested endpoints:
- `GET /api/v1/portfolio/{exchange}/overview?from=&to=&timezone=`
- `GET /api/v1/portfolio/{exchange}/performance?from=&to=&timezone=&group_by=day|week|month`
- `GET /api/v1/portfolio/{exchange}/breakdowns?dimension=symbol|side|duration|leverage|weekday|hour`
- `GET /api/v1/portfolio/{exchange}/equity?basis=account|realised_pnl&resolution=`
- `GET /api/v1/portfolio/{exchange}/positions/history?...filters...&page=&per_page=`
- `GET /api/v1/portfolio/{exchange}/ledger?category=&from=&to=&page=`
- `GET /api/v1/portfolio/{exchange}/sync-status`
- `POST /api/v1/portfolio/{exchange}/refresh` returning per-stream results, not one ambiguous success flag.

Every analytics response should include:
- `period`, `timezone`, and `coverage`;
- `source` and `basis`;
- `complete` plus reason codes such as `capital_history_missing` or `history_partial`;
- numeric values as null when not supportable, never misleading zeroes.

## Formula contract

Create one documented and tested calculator layer in `backend/services/analytics_service.py` (or split into `portfolio_analytics_service.py`).

Key definitions:
- `net_realised_pnl = sum(MEXC reported closeProfitLoss)` for selected closed positions. This is a dollar sum of closed-position PnL, **not** account profit or account return.
- `win_rate = wins / all closed positions`, with break-even count exposed separately.
- `expectancy = mean(reported PnL per closed position)`.
- `profit_factor = gross_profit / abs(gross_loss)`, null/infinite state represented explicitly.
- `active_day_average = net PnL / count(distinct local close dates)`.
- `calendar_day_average = net PnL / elapsed calendar dates in selected period`.
- `position ROI` remains per-trade; never sum it into account return.
- `net_account_profit_usd = ending_equity - opening_equity - net_external_flows`. This is a dollar measure of absolute account profit, not a percentage return. It is null until an opening equity baseline and complete capital-flow coverage exist.
- `account_return_pct` (percentage return) is defined **only** when capital-flow coverage is complete. Use one of: cash-flow-adjusted period return (`(ending_equity - net_external_flows) / opening_equity - 1`) or time-weighted return using sub-period equity snapshots. Return `null` plus reason code `capital_history_missing` when coverage is incomplete. **Keep realised-PnL reconstruction (`net_account_profit_usd`) separate from percentage return.** The UI exposes both only when their respective data prerequisites are met.
- `realised_pnl_drawdown` uses cumulative closed-position PnL.
- `account_equity_drawdown` uses futures equity snapshots adjusted for external flows.
- Conventional Sharpe/Sortino are calculated from periodic account returns only when sufficient valid equity data exists; otherwise null. A trade-quality score may be retained but must use a different name.

Use Decimal or carefully defined rounding boundaries for accounting sums; round only at serialization/display.

## Frontend implementation map

### Modify
- `frontend/components/portfolio/portfolio-dashboard.tsx`: make Overview the default information hierarchy and reduce nested-tab depth.
- `frontend/components/portfolio/analytics-dashboard.tsx`: consume the unified filtered analytics contract.
- `frontend/components/portfolio/performance-metrics.tsx`: correct labels and unavailable states.
- `frontend/components/portfolio/equity-curve.tsx`: support account-equity and realised-PnL bases, resolution, and cash-flow markers.
- `frontend/components/portfolio/pnl-heatmap.tsx`: timezone, period, summary, and drill-down.
- `frontend/components/portfolio/position-history-table.tsx`: filters, pagination, export, and detail drawer.
- `frontend/components/portfolio/risk-metrics-panel.tsx`: futures-only denominators and flat/not-applicable state.
- `frontend/components/portfolio/health-score-panel.tsx`: honest unavailable/flat states.
- `frontend/lib/types.ts`: versioned response types with provenance and completeness.

### Add
- `frontend/components/portfolio/portfolio-overview.tsx`
- `frontend/components/portfolio/period-filter.tsx`
- `frontend/components/portfolio/pnl-period-chart.tsx`
- `frontend/components/portfolio/performance-breakdown.tsx`
- `frontend/components/portfolio/trade-distribution.tsx`
- `frontend/components/portfolio/trade-detail-drawer.tsx`
- `frontend/components/portfolio/cash-flow-ledger.tsx`
- `frontend/components/portfolio/sync-health.tsx`
- Shared accessible chart tooltip/legend helpers to keep the visual language consistent.

Visual standard:
- Retain the existing dark Miraj palette and Recharts stack.
- Use tabular numerals and consistent green/red semantics.
- Charts need titles, basis labels, period labels, legends, tooltips, empty states, and accessible non-color cues.
- Avoid decorative gauges where a value plus threshold is clearer.
- Desktop should prioritize comparison; mobile should stack KPIs, charts, and filtered lists without horizontal tab overflow.

## Phased delivery

### Phase 0 — Metric correctness and truth labels

**Scope:** Phase 0 is local-only. No commits, pushes, PRs, merges, deployment, VPS access/mutation, production DB/config changes, credentials, or live exchange writes. All changes run in the local repo and are verified via local tests.

**Fixture contract:**
- A deterministic, redacted fixture of the 49 frozen positions (see §Audit findings) is checked into `backend/tests/fixtures/frozen_positions.py`.
- The fixture exports `FROZEN_POSITIONS: list[dict]` with exact `closeProfitLoss`, `profitRatio`, `symbol`, `side`, `size`, `open_time`, `close_time`, `leverage`, `close_reason` values.
- Production queries that return 49 / $49.23 are audit evidence only — the fixture is the test target, not production counts.
- Before asserting `closeProfitLoss` is net or gross of fees, add a verification step that reads the MEXC API response schema (documented fields, not inferred behaviour) and records the result. Until then, label as `MEXC-reported closed-position PnL`.

#### Acceptance criteria (each = exact backend/API name + source/basis + unavailable-reason + synthetic tests + local-only exclusion)

**AC-0.1: Equity-curve fix — PortfolioSnapshot equity line**
- **Backend/API name:** `GET /api/v1/analytics/{exchange}/equity-curve` → `EquityCurveResponse.points[].total_value`
- **Source:** `PortfolioSnapshot` table. `total_value` = `total_balance_usd` when non-null. When `total_balance_usd` is null, return `null` for that point (not a fallback to unrealised PnL).
- **Basis label in response:** `basis: "account_snapshot"` when `total_balance_usd` is used, `basis: null` when null.
- **Unavailable behavior:** if all snapshots have `total_balance_usd = null`, return `{"points": [], "basis": null, "unavailable_reason": "no_account_equity_data"}`.
- **Synthetic tests:**
  - Flat account: no open positions, all snapshots with `total_balance_usd=None` → returns `unavailable_reason`.
  - Partial history: mix of null and non-null snapshots → non-null points returned with `basis: "account_snapshot"`, null points omitted.
  - Timezone rollover: snapshots at 23:59 UTC and 00:01 UTC → both appear in the correct UTC day.
- **Local-only exclusion:** no production data is written; existing `PortfolioSnapshot` rows are read-only.

**AC-0.2: Remove invalid `total_pnl_percent`**
- **Backend/API name:** `GET /api/v1/analytics/{exchange}/performance` → `PerformanceMetricsResponse.total_pnl_percent`
- **Change:** return `null` (not `0.0`) with a `null_reason` field. The API response model gains an optional `total_pnl_percent_reason: str | None`.
- **Source/basis:** `total_pnl_percent` is mathematically invalid as portfolio return (sum of per-position leveraged ROIs). It is replaced by `null`.
- **Unavailable behavior:** `total_pnl_percent = null`, `total_pnl_percent_reason = "capital_history_missing"` (until Phase 3 provides the ledger).
- `total_pnl` (dollar sum) remains as-is, clearly labeled `MEXC-reported closed-position PnL`.
- **Synthetic tests:**
  - 3 positions with ROIs +10%, -5%, +20% → `total_pnl_percent = null`, `total_pnl` = correct dollar sum.
  - Empty position set → `total_pnl = 0.0`, `total_pnl_percent = null`, `total_pnl_percent_reason = "capital_history_missing"`.
  - All positions with same ROI → still `null` (never sum ROIs).
- **Local-only exclusion:** the `total_pnl_percent` field name stays in the response model for backward compatibility but is always `null`; no frontend code reads it as a valid number.

**AC-0.3: Rename/qualify drawdown and Sharpe**
- **Backend/API name:** `GET /api/v1/analytics/{exchange}/performance`
- **Drawdown:** rename `max_drawdown` → `realised_pnl_drawdown_usd`, `max_drawdown_percent` → `realised_pnl_drawdown_pct`. Add `drawdown_basis: "cumulative_closed_pnl"` label.
- **Sharpe:** rename `sharpe_ratio` → `trade_quality_score` (or `pnl_dispersion_score`). Add `trade_quality_basis: "per_trade_pnl_dispersion"` label. Never present as conventional portfolio Sharpe.
- **Unavailable behavior:** `realised_pnl_drawdown_pct = null` when peak cumulative PnL is zero/negative (same as current). `trade_quality_score = null` when `< 2 trades` or when `stdev(pnls) == 0` (all trades identical PnL).
- **Backward compatibility:** the old field names (`max_drawdown`, `max_drawdown_percent`, `sharpe_ratio`) are kept as `Optional` aliases returning the same values as their replacements. Frontend is updated to the new names; old names are removed in a later phase.
- **Synthetic tests:**
  - Break-even account: 49 trades all PnL = 0 → drawdown = 0.0, drawdown_pct = 0.0, trade_quality_score = null (stdev = 0).
  - Single trade: trade_quality_score = null (stdev requires ≥ 2).
  - Monotonically increasing cumulative PnL → drawdown = 0.0, drawdown_pct = 0.0.

**AC-0.4: Separate spot allocation from futures risk**
- **Backend/API name:** `GET /api/v1/analytics/{exchange}/allocation`
- **Change:** add `account_type: "spot" | "futures"` to each `AllocationItem`. The endpoint accepts an optional `?account_type=spot|futures` filter; defaults to `spot` for backward compatibility.
- **Source:** `PortfolioBalance` table for spot, `FuturesAccountSnapshot` (Phase 2) for futures. Phase 0: spot allocation is unchanged; `account_type` label is added to existing items.
- `GET /api/v1/analytics/{exchange}/risk` denominator is futures wallet equity only (not spot assets). When `FuturesAccountSnapshot` is unavailable, `margin_usage_pct = null` with `unavailable_reason: "futures_equity_not_available"`.
- **Synthetic tests:**
  - Spot/futures separation: spot balances exist but no futures snapshot → allocation returns spot items with `account_type: "spot"`, risk returns `margin_usage_pct = null`.
  - Empty spot → `{"items": [], "account_type": "spot"}`.
- **Local-only exclusion:** existing `PortfolioBalance` data is read-only; no new `FuturesAccountSnapshot` rows are written in Phase 0.

**AC-0.5: Fix flat-account health state**
- **Backend/API name:** `GET /api/v1/analytics/{exchange}/health`
- **Change:** when `open_positions == 0`, return `health_score = null`, `grade = null`, `health_reason = "no_open_positions"`. Remove the synthetic grade B/65.
- **Source:** `PortfolioSnapshot.open_positions` (most recent snapshot).
- **Synthetic tests:**
  - Flat account: 0 open positions → `health_score = null`, `grade = null`, `health_reason = "no_open_positions"`.
  - Active account: 3 open positions → existing health score logic unchanged.
  - No snapshot at all → `health_score = null`, `health_reason = "no_snapshot_data"`.
- **Local-only exclusion:** health score calculation for active accounts is unchanged.

**AC-0.6: Timezone and period parameters**
- **Backend/API name:** `GET /api/v1/analytics/{exchange}/daily-pnl` (and all new Phase 1+ endpoints)
- **Change:** accept `?timezone=UTC|Asia/Karachi|...` (IANA tz) and `?from=&to=` (ISO 8601) parameters. Default `timezone=UTC`. Store timestamps in UTC; convert to target timezone for grouping.
- **Source:** `PositionHistory.close_time` (UTC). Grouping uses the target timezone's date boundaries.
- **Unavailable behavior:** invalid timezone → `400` with `{"detail": "Invalid timezone: ..."}`. Empty period → zero-length arrays.
- **Synthetic tests:**
  - Timezone rollover: position closes at 2026-07-23 23:30 UTC. Grouped by UTC → 2026-07-23. Grouped by `Asia/Karachi` (UTC+5) → 2026-07-24.
  - Partial history: `from=` and `to=` filter to a range with no trades → `{"days": [], "exchange": "mexc"}`.
  - Week/month rollover: positions on 2026-12-31 and 2027-01-01 → correct weekly grouping across year boundary.
- **Local-only exclusion:** no frontend timezone selector is built in Phase 0; the API parameter is added and tested but the UI defaults to UTC.

**Phase 0 exit criteria:**
Every existing widget is verified to not make a false account-equity, account-return, or futures-collateral claim. All synthetic tests pass. The fixture is committed. The `total_pnl_percent` field is nulled with a reason. The equity curve no longer falls back to unrealised PnL. The health endpoint returns `null` for flat accounts. Drawdown and Sharpe are renamed with basis labels. The allocation endpoint labels account types.

### Phase 1 — Enriched closed-position analytics
1. Build one filtered calculator layer and period/breakdown endpoints.
2. Add actual day/week/month totals, active/calendar averages, expectancy, payoff, streaks, concentration, symbol/side/duration/leverage breakdowns.
3. Add Overview KPIs, weekly/monthly chart, pair/direction contribution, and upgraded PnL calendar.
4. Add server-side Trade Explorer pagination and filters.

Exit criteria: the UI can reproduce the 49-position sample’s $49.23 net PnL and explain where it came from without exporting data manually.

### Phase 2 — Complete MEXC synchronization
1. Capture redacted fixtures and verify supported private API fields.
2. Add stable IDs, incremental full-history pagination, stream-specific sync state, and idempotent upserts.
3. Ingest futures account assets and truthful equity/available/margin snapshots.
4. Add funding and transfer/deposit/withdrawal streams where MEXC supports them.
5. Expose coverage and partial-history states in every affected view.

Exit criteria: no silent 200-row truncation; current account values and history coverage are visible and auditable.

### Phase 3 — Account equity and cash-flow intelligence
1. Build the ledger and Cash Flow view.
2. Calculate starting/ending equity and net deposits only when coverage is complete.
3. Add cash-flow-adjusted account returns, true equity drawdown, and conventional risk-adjusted metrics.
4. Add account-equity curve with transfer markers and resolution controls.

Exit criteria: account return reconciles as `ending equity - opening equity - net external flows`, within defined rounding tolerance.

### Phase 4 — Strategy insight and journal loop
1. Link positions to orders/fills, Miraj scans, and journal records.
2. Add strategy/tag scorecards and scan-outcome attribution.
3. Add data-driven insight cards such as concentration warnings and repeatable-edge candidates.
4. Keep insights descriptive and evidence-based; do not turn the read-only dashboard into an execution engine.

Exit criteria: each insight links to the filtered trades that support it.

## Testing plan

### Backend
Add:
- `backend/tests/test_portfolio_analytics.py`
- `backend/tests/test_portfolio_period_grouping.py`
- `backend/tests/test_mexc_history_normalization.py`
- `backend/tests/test_mexc_sync_pagination.py`
- `backend/tests/test_portfolio_ledger.py`
- `backend/tests/test_portfolio_equity_reconciliation.py`

Cover:
- wins/losses/break-even, profit factor with zero losses, expectancy, streaks, concentration;
- timezone boundaries, week/month rollover, empty periods, and partial history;
- duplicate/partial-close source IDs and idempotent refreshes;
- spot versus futures separation;
- account return and drawdown with deposits/withdrawals;
- unsupported/null MEXC fields and stale/error states;
- authentication and strict user isolation.

### Frontend
Add focused Jest/Testing Library tests for:
- overview values and unavailable reason labels;
- period changes and endpoint parameters;
- chart/table empty, loading, stale, and partial states;
- flat-account risk state;
- Trade Explorer filtering, pagination, drawer, and export;
- mobile tab/filter usability and accessible chart summaries.

### Verification commands
- `JWT_SECRET_KEY=test-key-not-for-production python -m pytest backend/tests/test_portfolio_analytics.py backend/tests/test_mexc_history_normalization.py backend/tests/test_mexc_sync_pagination.py -v`
- `npm test -- --runInBand` from `frontend/`
- `npx tsc --noEmit` from `frontend/`
- `npm run build` from `frontend/`
- Run the broader backend suite before release.

### End-to-end acceptance
Using an authenticated MEXC read-only account:
1. Refresh reports per-stream success/failure and a timestamp.
2. Closed-position totals reconcile exactly to MEXC reported values for the same filters.
3. Day/week/month groups sum back to selected-period total.
4. Spot holdings never appear as futures available margin.
5. Equity, realised-PnL, and unrealised-PnL charts are visibly distinct and numerically reconciled.
6. Starting capital and account return remain unavailable until capital-flow coverage is sufficient.
7. History beyond 200 records is reachable through pagination and included in all-history analytics.
8. Refreshing twice creates no duplicate history, ledger, order, or fill records.
9. No private key, secret, or unredacted private payload appears in logs, API responses, HTML, or client state.
10. User-visible production checks confirm the dashboard, not only unit tests and build output.

## Recommended implementation order
Do Phase 0 first. The app already has many visual components, but adding more charts before fixing equity, return, collateral, and coverage semantics would amplify misleading data. Then deliver Phase 1 as the first visible upgrade, followed by complete MEXC synchronization and the ledger required for truthful starting-capital and account-return analytics.
