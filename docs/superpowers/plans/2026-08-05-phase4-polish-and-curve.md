# Phase 4 polish + equity curve polish

**Status:** Ready for implementation  
**Date:** 2026-08-05  
**Base:** `origin/main` (`f1d2fed` — Phase 4 strategy loop #22)  
**Branch:** `feat/phase4-polish-and-curve`

## Context

Phases 2B–4 first slices are live. Remaining product work:

1. Close the Strategy → evidence → closed-trades loop  
2. Auto-suggest journal tags from linked closed position side  
3. Equity curve usability (downsample, marker tooltips, as-of stamp)

## Global Constraints

- **Futures-only** product rule unchanged: never use spot as equity/return base  
- **Fail closed** / honest unavailable reasons; no invented metrics  
- Insights stay **descriptive** (not execution advice)  
- Prefer INK & OXIDE tokens for new UI (`#161411`, `#2A2620`, `#EDE7DB`, `#8E8778`, `#C2A36B`) — avoid new `slate-*` / `rounded-xl` in portfolio components that gate design-system tests  
- Tests required for backend behavior; frontend focused Jest where components already have patterns  
- Commit after each task with a clear message  
- Do not force-push; do not land/deploy in this plan (controller ships later)

## Tasks

### Task 1: Evidence → closed positions (Strategy panel)

**Goal:** When an insight has `evidence_symbol` (or journal evidence rows have symbols), Strategy evidence panel offers a path into **closed positions** analytics filtered by that symbol — not only journal rows.

**Requirements:**

1. Extend Strategy evidence UI to show:
   - Existing journal evidence list  
   - Secondary action: **View closed positions** linking to portfolio analytics closed-positions context with symbol filter when possible  
2. Prefer deep-link query params the portfolio already understands. Inspect `ClosedPositionFilters` / analytics dashboard for supported filters (`symbol`, etc.). If closed-position filters only support period/side/etc., add a **symbol** filter end-to-end:
   - Backend closed-position analytics / trade explorer if needed  
   - Frontend filter state + URL or tab deep-link  
3. For concentration insights (`symbol_pnl_concentration`), primary CTA should reach closed trades for that symbol.  
4. Tests: unit/integration for any new backend filter; Jest or smoke assertion for link construction if UI-tested elsewhere.

**Files (expected):**  
`frontend/components/portfolio/strategy-insight-panel.tsx`, possibly `closed-position-filters.tsx`, `analytics-dashboard.tsx`, analytics service/routes, types.

### Task 2: Auto-suggest journal tags from closed position side

**Goal:** When creating a journal entry that will auto-link (or explicitly links) a closed position, suggest tags from position **side** (`long`/`short`) so scorecards start useful without manual tagging.

**Requirements:**

1. Backend `POST /api/v1/journal` create path: after resolving position (explicit or auto-link), if `tags` is empty/null, suggest default tags including side: e.g. `long` or `short` (lowercase).  
2. Do **not** overwrite user-supplied tags.  
3. Optionally include `exchange` slug is **not** required as a tag.  
4. Document in create handler docstring.  
5. Tests in `test_phase4_strategy_loop.py` or new test: create without tags → response tags contain side; create with tags → unchanged.

**Files:** `backend/routes/journal.py`, tests.

### Task 3: Equity curve polish (downsample + markers + as-of)

**Goal:** Make the futures equity curve readable under dense snapshots.

**Requirements:**

1. **Downsample** backend `get_equity_curve` points when series is large (e.g. > 200 points): keep first/last and at most one point per calendar day (prefer last snapshot of day) OR max ~200 evenly spaced points. Preserve markers unchanged.  
2. Response includes `as_of` (ISO timestamp of last raw snapshot source_ts) and optionally `point_count_raw` / `point_count_returned`.  
3. Frontend: show **As of …** under the chart title; improve marker **tooltips** (or legend rows already present) to show entry type + signed amount on hover if ReferenceDot supports tooltip — otherwise ensure marker list rows already show amount/type (already partly done) and add title attribute.  
4. Tests: downsample keeps endpoints; as_of set; markers still returned.

**Files:** `backend/services/analytics_service.py`, `backend/routes/analytics.py`, `frontend/components/portfolio/equity-curve.tsx`, types, `test_portfolio_analytics.py`.

### Task 4: Wire-up polish + regression tests

**Goal:** Integration glue and regression suite green.

**Requirements:**

1. Ensure Strategy concentration insight uses closed-position deep link from Task 1.  
2. Ensure journal page still filters by tag/symbol.  
3. Run:  
   - `python3 -m pytest backend/tests/test_phase4_strategy_loop.py backend/tests/test_journal_strategy_insights.py backend/tests/test_portfolio_analytics.py -q`  
   - `cd frontend && npm test -- --testPathPattern="portfolio-analytics-correctness" --no-coverage`  
4. Fix any breakage introduced by Tasks 1–3.  
5. Final commit only if fixes needed; otherwise confirm suite green.

## Out of scope

- Spot-mixed equity  
- Manual opening equity override  
- Conventional Sharpe  
- Deploy / land-and-deploy (separate step)
