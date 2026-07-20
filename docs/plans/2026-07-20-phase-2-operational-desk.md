# Phase 2 — Operational Decision Desk

## Goal
Turn Phase 1's read-only signal desk into an operationally trustworthy, still manual-only workflow:

```text
verified MEXC market → confirmed closed candle → durable Discord lifecycle alert
→ manual trade → authenticated account reconciliation → linked journal review
```

## Non-negotiable boundaries
- No order creation, cancellation, leverage mutation, transfer, or any other write-capable exchange operation.
- Contract-catalogue failure remains fail-closed; no realtime subscription is retained from syntax-only conversion.
- Discord configuration and an enabled DB channel are not delivery proof. A sent outbox record must have `status=sent`, non-null `sent_at`, and null `last_error`.
- Account data remains unavailable/stale unless authenticated exchange refresh succeeded. Public market data never becomes account truth.
- API secrets stay in protected server configuration/DB encryption paths, never source control or rendered UI.

## Workstreams
1. **Live evidence**: add authenticated Decision Desk lifecycle/outbox evidence scoped to the current user and explicitly distinguish configured, pending, sent, failed, and unavailable.
2. **Watchlist refresh**: reload Contract-catalogue-verified watchlist membership on a bounded interval; on refresh failure retain no new unverified subscriptions and reconnect only when membership changes.
3. **Account reconciliation**: use the existing encrypted-key, read-only `fetch_portfolio` path to refresh balances, open positions, fills/history and expose a timestamped account-truth section in Decision Desk. No private WebSocket or credential ingestion is introduced without a valid existing MEXC key record.
4. **Journal loop**: expose a prefilled manual journal action from a reconciled position / Decision Desk setup, while retaining user ownership and no automatic journal generation.
5. **Verification/release**: focused backend + frontend tests; typecheck and diff checks; review before push/merge/deploy. Production verification uses the public route plus DB-backed status evidence. An actual Discord message requires a genuine transition or explicit user-approved non-trading test event.

## Acceptance criteria
- A user sees only their own latest signal and notification statuses.
- A notification failure is visible as failed/pending and never called delivered.
- Removing a pair from a watchlist removes it from subsequent subscription sets within the refresh bound.
- An unsupported / catalogue-unavailable pair is never newly subscribed.
- Account summary is visibly `unavailable` or `stale` until successful authenticated reconciliation.
- Journal prefill does not place trades or mutate exchange state.
