# Miraj Decision Desk Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Turn the existing scanner and realtime worker into a clear manual MEXC decision desk that separates tradable realtime pairs from research-only assets and exposes operational signal status.

**Architecture:** Keep the current `watchlist_pairs` model as the user’s general research list. Add a shared pure classification helper which identifies MEXC-realtime eligibility without inventing markets. The first release adds explicit UI classification and a focused “Now” page derived from persisted realtime state; it does not add auto-trading or private exchange credentials.

**Tech Stack:** FastAPI, SQLAlchemy/SQLite, Next.js/TypeScript, Tailwind, pytest.

---

### Task 1: Add one source of truth for market eligibility

**Objective:** Classify symbols as `mexc_realtime` or `research_only` using the same rules as the MEXC worker.

**Files:**
- Modify: `backend/realtime/worker.py`
- Modify: `backend/routes/watchlist.py`
- Test: `backend/tests/test_realtime_worker.py`

**Step 1: Write failing tests** for compatible `BTC-USD` and unsupported `SNDK-USD` classifications.

**Step 2: Run** `python3 -m pytest backend/tests/test_realtime_worker.py -q` and verify RED.

**Step 3: Implement** a pure reusable helper returning canonical MEXC symbol or `None`; do not map unsupported assets.

**Step 4: Return** `market_scope` and, where applicable, `mexc_symbol` in watchlist responses.

**Step 5: Run** focused backend tests and commit.

### Task 2: Make the Watchlist UI explain its market scope

**Objective:** Show a clear `MEXC Realtime` or `Research only` status for every row and explain why a research-only asset is not monitored.

**Files:**
- Modify: `frontend/lib/types.ts`
- Modify: `frontend/components/watchlist-table.tsx`
- Test: frontend test location consistent with existing project tooling, or add minimal component test if present.

**Step 1: Write a failing type/component test or build assertion for the new response field.

**Step 2: Implement** compact status badges and an explanatory caption on the add form.

**Step 3: Run** frontend lint/type/build validation and commit.

### Task 3: Add a focused Decision Desk / Now endpoint

**Objective:** Return current general watchlist classification plus persisted realtime lifecycle records for the signed-in user.

**Files:**
- Create: `backend/routes/decision_desk.py`
- Modify: `backend/main.py`
- Modify: `backend/schemas.py`
- Test: `backend/tests/test_decision_desk.py`

**Step 1: Write a failing authenticated API test for an owned realtime signal and a research-only watchlist pair.

**Step 2: Implement** a read-only `/api/v1/decision-desk/now` endpoint with explicit freshness/timestamps and no exchange mutations.

**Step 3: Run** focused tests and commit.

### Task 4: Add the Decision Desk page

**Objective:** Provide one daily-use page with market-scope counts, actionable/watch/invalidation lifecycle cards, timestamps, and links back to Scanner/Settings.

**Files:**
- Create: `frontend/app/now/page.tsx`
- Create: `frontend/components/decision-desk.tsx`
- Modify: `frontend/components/sidebar.tsx`
- Modify: `frontend/lib/types.ts`

**Step 1: Write a failing render/type test where feasible.

**Step 2: Implement** the page without suggesting automatic execution; lifecycle labels must be advisory only.

**Step 3: Run** frontend validation and commit.

### Task 5: Operational notification clarity

**Objective:** State accurately in Settings which channel types can be configured now and show channel delivery state where the existing API provides it.

**Files:**
- Modify: `frontend/components/settings/alert-preferences-form.tsx`
- Test: relevant frontend validation.

**Step 1: Write a failing assertion for the configured-channel capability message.

**Step 2: Implement** a truthful Telegram-current / Discord-email-coming-soon message; do not represent unavailable configuration as working.

**Step 3: Run** validation, complete final backend/frontend tests, review, and commit.

## Release gates

- No auto-trading, order placement, or stored exchange credentials.
- `SNDK-USD` and other unsupported symbols stay visible as research-only and never enter MEXC subscriptions.
- Existing MEXC compatible `BASE-USD` pairs preserve their `BASE_USDT` mapping.
- Backend focused tests, frontend build/type validation, and an independent spec + quality review pass before deployment.
