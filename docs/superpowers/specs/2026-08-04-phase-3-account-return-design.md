# Phase 3 — Account Return from Capital-Flow Ledger

**Status:** Approved for implementation (milestone after Phase 2B)
**Date:** 2026-08-04
**Predecessor:** Phase 2B capital-flow ledger (#14)

## Summary

Compute cash-flow-adjusted **account return** and **net account profit** when
authenticated futures equity snapshots and complete external capital-flow coverage
exist. Never invent a return when coverage is incomplete.

## Formula (from portfolio intelligence contract)

```
net_external_flows = sum(signed_amount) for deposit | withdrawal | futures_transfer
                     with opening_ts < occurred_at ≤ ending_ts

net_account_profit_usd = ending_equity − opening_equity − net_external_flows

account_return_pct = ((ending_equity − net_external_flows) / opening_equity − 1) × 100
```

- **External flows only:** `deposit`, `withdrawal`, `futures_transfer`.
  Funding is already reflected in equity change and is **not** an external flow.
- **Opening equity:** earliest `FuturesAccountSnapshot` with non-null `equity` for
  user/exchange (by `source_ts`, then `id`).
- **Ending equity:** latest such snapshot with `source_ts` strictly after opening.
- **Percent scale:** percentage points (e.g. `12.5` means +12.5%), matching
  `btc_return_pct` style.

## Coverage gate (honesty)

External capital streams: `deposits`, `withdrawals`, `futures_transfers`.

A stream is **satisfied** when:
- `ExchangeSyncState.complete` is true, **or**
- `status` is `unavailable` (endpoint not supported → treat as empty, complete).

If any of the three is `partial`, `error`, `stale`, or missing with no
unavailable status → do **not** compute return; reason:
`capital_history_incomplete` (or `capital_history_missing` when no sync state).

Additional fail-closed reasons:
- `opening_equity_missing` — no usable futures equity snapshot
- `insufficient_equity_snapshots` — fewer than two distinct snapshot times
- `opening_equity_zero` — cannot divide by zero

## Surfaces

- `compute_performance_metrics` sets `account_return_pct`,
  `account_return_pct_reason`, `net_account_profit_usd`,
  `net_account_profit_usd_reason` (new optional fields), and clears
  `unavailable_reason` only for the return fields when computed.
- `total_pnl_percent` stays **null** (still not a valid account return).
- Sync panel: show account return when available; else keep unavailable copy
  (drop “Phase 2B does not calculate it”).
- Performance metrics UI: show account return when present.

## Non-goals

- Full time-weighted sub-period TWR with daily equity series
- Conventional Sharpe from account returns (still later)
- Benchmark portfolio_return_pct series (can stay null this phase)
- Retention probe / rebates

## Tests

- Formula unit tests with fixtures (opening/ending/flows)
- Incomplete capital stream → null + reason
- Unavailable deposit stream → still computable if other external streams OK
- UI shows return when metrics provide it
