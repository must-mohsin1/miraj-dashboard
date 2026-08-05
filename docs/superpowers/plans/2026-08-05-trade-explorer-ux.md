# Trade Explorer UX slice

**Status:** Implemented — ready to ship  
**Date:** 2026-08-05  
**Base:** `origin/main` (`1794f3c` — Phase 4 depth/curve/ops #24)  
**Branch:** `feat/trade-explorer-ux`

## Context

Closed-position analytics already has filters, server pagination, and Trade Explorer table/cards. Gaps vs the portfolio-intelligence plan:

1. Filter state only deep-links **symbols** (not side/sort/period/pagination).
2. No **CSV export** of explorer rows.
3. No **trade detail drawer** (row click).

## Scope (this PR)

1. **URL filter sync** for closed-position filters used by Trade Explorer  
   - Read: `symbols`, `side`, `sort`, `period`, `limit`, `offset`, `from`, `to`, `close_reason`  
   - Write: client `router.replace` when filters change on the closed-positions tab  
   - Preserve `exchange`, `tab`, `analytics_tab`
2. **CSV export** of the **current page** of explorer items (honest label; no silent full-history dump).
3. **Trade detail drawer** (Sheet) on row/card click with full fields + journal deep-link by symbol.
4. **Clickable column sort** headers → update filter `sort`.
5. Tests for CSV helper, URL parse/serialize, drawer open, export control.

## Out of scope

- Backend CSV endpoint / full-history export  
- Orders/fills/funding inside drawer (not on explorer payload)  
- Conventional Sharpe  
- Authenticated browser e2e (Keychain blocked in this session)

## Constraints

- Futures-only product rules unchanged  
- Fail-closed copy; no invented fee-net PnL  
- Prefer existing INK/card tokens (`border-border`, `bg-card`) in explorer chrome
