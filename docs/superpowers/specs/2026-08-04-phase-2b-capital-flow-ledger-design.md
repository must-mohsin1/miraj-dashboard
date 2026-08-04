# Phase 2B — MEXC Capital-Flow Ledger

**Status:** Approved design (brainstorming complete)
**Date:** 2026-08-04
**Branch base:** `main-2` (= `origin/main`)
**Predecessor:** Phase 2A MEXC synchronization (#11), SQLite WAL hardening (#12, #13)

## Summary

Phase 2A synchronized read-only MEXC futures **positions, orders, trades, and
the futures-account snapshot**. Phase 2B ingests the four **capital-flow ledger**
streams that Phase 2A explicitly deferred — funding, futures transfers, deposits,
and withdrawals — with the same idempotency and coverage discipline, and surfaces
them in a read-only view.

The frontend already reserves these four slots in `sync-status-panel.tsx`, where
they render as `not_enabled_phase_2b` placeholders. Phase 2B replaces those
placeholders with real coverage states backed by ingested data.

## Goals

- Ingest funding / futures-transfer / deposit / withdrawal history from MEXC into
  a persistent, idempotent ledger.
- Track per-stream coverage using the existing `ExchangeSyncState` model and
  `_coverage(...)` envelope, so gaps are shown honestly rather than hidden.
- Flip the four `sync-status-panel` slots from `not_enabled_phase_2b` to real
  `fresh` / `partial` / `error` / `unavailable` states.
- Provide a read-only capital-flow view so a user can see the ingested entries.

## Non-Goals (YAGNI)

- **No account-return calculation.** `total_pnl_percent` stays `null` /
  `capital_history_missing`. Turning the ledger into time-weighted account return
  is deferred to Phase 3.
- **No retention probe.** Detecting how far back each endpoint serves data is a
  later concern; Phase 2B reports whatever the endpoint returns and marks the rest
  as `partial` with `unrecoverable_gaps`, exactly as Phase 2A already does.
- **No write operations.** The exchange integration remains strictly read-only.
- **No rebates/bonuses ingestion.** The schema tolerates new `entry_type` values,
  but only the four named streams are ingested now.

## Design

### 1. Data model

New table `capital_flow_ledger`, created by Alembic revision
`20260804_phase2b_capital_flow` (down-revision = `20260725_phase2a_mexc_sync`),
using SQLite batch mode consistent with the Phase 2A migration.

| Column | Type | Purpose |
|---|---|---|
| `id` | Integer PK | |
| `user_id` | Integer, not null, indexed | scoping |
| `exchange` | String(32), not null | scoping |
| `entry_type` | String(32), not null | `funding` \| `futures_transfer` \| `deposit` \| `withdrawal` |
| `exchange_entry_id` | String(128), nullable | source id for idempotency |
| `asset` | String(32), not null | settlement currency |
| `amount` | Float, nullable | magnitude as reported by source |
| `signed_amount` | Float, nullable | **+inflow / −outflow** relative to the futures account |
| `status` | String(32), nullable | source state, redacted |
| `occurred_at` | DateTime, nullable | source event time |
| `source_updated_at` | DateTime, nullable | source's last-update time |
| `synced_at` | DateTime, not null | when Miraj ingested the row |
| `raw_json` | Text, nullable | full redacted source row (stream-specific fields) |

Indexes:

- Partial unique index `uq_capital_flow_user_exchange_type_source_id` on
  `(user_id, exchange, entry_type, exchange_entry_id)` where
  `exchange_entry_id IS NOT NULL` — mirrors Phase 2A's source-id upsert keys.
- Index `ix_capital_flow_user_exchange_occurred` on
  `(user_id, exchange, occurred_at)` for the chronological view.

**Signed-amount convention** (the one piece of normalization math):

| entry_type | sign |
|---|---|
| `deposit` | `+amount` (inflow) |
| `withdrawal` | `−amount` (outflow) |
| `futures_transfer` | `+` into futures account, `−` out |
| `funding` | `+` receipt, `−` payment |

This is what a future Phase 3 return calc needs and makes the view summable. No
return is computed in Phase 2B.

**Idempotency for id-less rows.** Entries lacking a stable `exchange_entry_id`
derive a deterministic synthetic id: a hash of
`(entry_type, asset, amount, occurred_at)`. This prevents duplicate rows on
re-ingest for streams whose source rows carry no stable id.

### 2. Ingestion + coverage

New module `backend/services/phase2b_ledger.py`, structured parallel to
`phase2a_sync.py`:

- Per-stream coerce functions normalizing a raw MEXC row into the common ledger
  dict (including `signed_amount`).
- `persist_capital_flow_payload(session, user_id, exchange, payload, now)` —
  idempotent upsert keyed on the source id (or synthetic hash), plus
  `_upsert_sync_state(...)` for each of the four streams, reusing the existing
  `ExchangeSyncState` model.

Four capability-guarded fetchers in `backend/services/exchange_service.py`,
mirroring the existing `_fetch_*_with_coverage` functions:

- `_fetch_funding_history_with_coverage`
- `_fetch_futures_transfers_with_coverage`
- `_fetch_deposits_with_coverage`
- `_fetch_withdrawals_with_coverage`

Each:

- Guards capability with `hasattr(exchange, "<mexc implicit method>")`. If the
  method is absent, returns `_coverage(stream, rows=[], status="unavailable",
  complete=False, reason="stream_not_supported")`.
- Reuses `_paginate_mexc_history` for the paginated MEXC contract endpoints,
  inheriting its retry/backoff and partial/gap accounting.
- Returns `(rows, _coverage(stream, rows, **paging))`.

**Endpoint resolution (honesty note).** The exact MEXC implicit method names
differ per stream — funding is a futures-contract endpoint, while
deposit/withdrawal/transfer records are account/spot-side endpoints. The concrete
method names and response shapes are resolved against ccxt's mexc implicit API map
during implementation and confirmed against **redacted fixtures**, per the plan
doc's "capability probe with redacted raw fixtures — normalize only fields
observed from the authenticated response." Streams MEXC does not expose to the
authenticated key render as `unavailable`; they are never faked.

**Trigger.** The four fetchers are wired into the existing `fetch_history` / sync
refresh path (the same coverage-bearing path Phase 2A's history streams use), not
the hot balances/price-tick path. A portfolio refresh ingests the ledger with
coverage under the existing rate-limit handling.

### 3. API + read-only view

Backend:

- The existing cached-coverage endpoint in `routes/portfolio.py` stops
  special-casing the four streams as `not_enabled_phase_2b` and returns their real
  `ExchangeSyncState` coverage.
- New `GET /portfolio/{exchange}/capital-flow` — user-scoped, returns ledger
  entries sorted by `occurred_at` (descending) plus a coverage summary. Paginated
  consistent with existing portfolio endpoints.

Frontend:

- New `frontend/components/portfolio/capital-flow-table.tsx` — read-only, styled
  per INK & OXIDE (`DESIGN.md`): columns for date, type badge, asset, signed
  amount, status; a coverage banner when any stream is `partial` / `unavailable` /
  `error`. Added as a portfolio section/tab.
- `sync-status-panel.tsx` — remove the `not_enabled_phase_2b` special-casing for
  these four streams so they reflect real states.
- `frontend/lib/types.ts` — add `CapitalFlowEntry` and the capital-flow response
  type.

### 4. Error handling

Reuse the Phase 2A `_coverage` state machine: `fresh` / `partial` / `error` /
`unavailable`, redacted error messages, and `unrecoverable_gaps`. Partial coverage
drives a banner ("history truncated at exchange boundary"). The system never
invents entries to fill a gap; missing history is shown as a gap.

### 5. Testing (TDD, fixture-driven)

- `backend/tests/fixtures/phase2b_ledger.py` — redacted MEXC rows for each of the
  four streams (including id-less rows to exercise the synthetic-hash path).
- `backend/tests/test_phase2b_ledger.py` — coerce/normalize per stream,
  signed-amount conventions, idempotent double-ingest (no duplicates), coverage
  states (`fresh` / `partial` / `unavailable` / `error`).
- `backend/tests/test_phase2b_migration.py` — table and indexes created; upgrade
  and downgrade.
- `backend/tests/test_phase2b_capital_flow_api.py` — endpoint returns sorted
  entries + coverage; strict user-scope isolation.
- `frontend/components/portfolio/capital-flow-table.test.tsx` — renders entries,
  signed-amount formatting, coverage banner on partial/unavailable.
- Update `frontend/components/portfolio/sync-status-panel.test.tsx` for the four
  streams now returning real states.

## Files touched

New:

- `backend/migrations/versions/20260804_phase2b_capital_flow.py`
- `backend/services/phase2b_ledger.py`
- `backend/tests/fixtures/phase2b_ledger.py`
- `backend/tests/test_phase2b_ledger.py`
- `backend/tests/test_phase2b_migration.py`
- `backend/tests/test_phase2b_capital_flow_api.py`
- `frontend/components/portfolio/capital-flow-table.tsx`
- `frontend/components/portfolio/capital-flow-table.test.tsx`

Modified:

- `backend/models.py` (add `CapitalFlowLedger`)
- `backend/services/exchange_service.py` (four `_fetch_*_with_coverage` fetchers,
  wire into the history/sync path)
- `backend/routes/portfolio.py` (real coverage for the four streams; new
  capital-flow endpoint)
- `frontend/components/portfolio/sync-status-panel.tsx` (drop
  `not_enabled_phase_2b` special-casing for these four streams)
- `frontend/components/portfolio/sync-status-panel.test.tsx`
- `frontend/lib/types.ts` (`CapitalFlowEntry` + response type)
- Service-worker cache bump (`frontend/public/sw.js`), consistent with prior
  phases.

## Open implementation detail (resolved during build, not a spec gap)

The concrete MEXC implicit method names per stream are confirmed against ccxt's
mexc API map and redacted fixtures during implementation. This does not change the
design: capability guards and honest coverage already handle any stream that turns
out to be unavailable to the authenticated key.
