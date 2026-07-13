# DCA Shadow-Mode Validation — Integration Report

**Date**: 2026-07-13
**Integrator**: devcrew-integrator (task t_a18b2556)
**Branch**: `dca-shadow/integrator`
**Worktree**: `/.worktrees/t_a18b2556`

## Changed files

### New files (copied from implementation worktrees + fix card worktrees)

| File | Source | Purpose |
|------|--------|---------|
| `backend/routes/dca_validation.py` | t_2ada0b90 (fix card) | `GET /api/v1/dca-validation/{exchange}` route with timeout, split-ratio validation, cache |
| `backend/services/dca_validation_reconstruction.py` | t_2ada0b90 (fix card) | Scan-to-scan reconstruction engine with fill assumptions |
| `backend/services/dca_validation_metrics.py` | t_61269e85 | Per-symbol/portfolio metrics (win rate, Sharpe, drawdown, etc.) |
| `backend/services/dca_shadow_service.py` | t_1aea2b97 | Shadow-mode safety gates and decision history |
| `backend/tests/test_dca_validation_api.py` | t_2ada0b90 (fix card) | API route tests (7 tests) |
| `backend/tests/test_dca_validation_reconstruction.py` | t_3528a329 | Reconstruction engine tests (9 tests) |
| `backend/tests/test_dca_validation_metrics.py` | t_61269e85 | Metrics computation tests (4 tests) |
| `backend/tests/test_dca_shadow_service.py` | t_1aea2b97 | Shadow service tests (4 tests) |
| `backend/tests/test_dca_validation_models.py` | t_f4dacbfa | Model/cascade/audit tests (4 tests) |
| `backend/tests/fixtures/dca_validation_scans.json` | t_3528a329 | Deterministic scan fixture for reconstruction |
| `backend/tests/fixtures/dca_validation_expected.json` | t_07116ef0 | Expected metrics for QA verification |
| `frontend/app/portfolio/dca-validation/page.tsx` | t_128e11ec (fix card) | Validation page composing panels |
| `frontend/app/portfolio/dca-validation/page.test.tsx` | t_128e11ec (fix card) | Page tests (6 tests) |
| `frontend/components/portfolio/dca-validation-entry.tsx` | t_128e11ec (fix card) | Entry link component for portfolio panel |
| `frontend/components/portfolio/dca-validation-summary.tsx` | t_128e11ec (fix card) | Summary card with headline metrics |
| `frontend/components/portfolio/dca-validation-events.tsx` | t_128e11ec (fix card) | Reconstructed events table |
| `frontend/components/portfolio/dca-validation-symbol-table.tsx` | t_128e11ec (fix card) | Per-symbol metrics table |
| `frontend/components/portfolio/dca-shadow-history-table.tsx` | t_128e11ec (fix card) | Shadow decision history table |
| `frontend/components/portfolio/dca-validation-panels.test.tsx` | t_128e11ec (fix card) | Panel component tests (6 tests) |
| `frontend/lib/dca-validation-api.ts` | t_128e11ec (fix card) | API client for validation endpoints |
| `frontend/lib/dca-validation-api.test.ts` | t_128e11ec (fix card) | API client tests (5 tests) |
| `frontend/lib/dca-validation-types.ts` | t_128e11ec (fix card) | Shared TypeScript types for validation |
| `scripts/seed_dca_validation_fixture.py` | t_bb7ef857 | Deterministic fixture seed script |
| `docs/qa/dca-validation-fixture.md` | t_bb7ef857 | QA fixture documentation |
| `docs/dca-validation-domain-contract.md` | t_07116ef0 | Domain contract documentation |
| `docs/dca-validation-ux-spec.md` | t_2be6da83 | UX spec documentation |

### Modified files for integration wiring

| File | Change | Purpose |
|------|--------|---------|
| `backend/models.py` | Added `Boolean` import; added `DcaShadowGlobalKillSwitch`, `DcaShadowUserKillSwitch`, `DcaShadowSymbolKillSwitch`, `DcaShadowDecisionHistory` model classes; added User relationship backrefs | New persistence models for shadow safety gates and audit history |
| `backend/main.py` | Imported `DcaShadow*` models for table creation; imported `dca_validation_router`; added `app.include_router(dca_validation_router)` | Registers the validation route in the shared FastAPI app |
| `frontend/components/portfolio/dca-panel.tsx` | Added `DcaValidationEntry` import and rendered the component in the panel header | Provides the validation entry point in the Portfolio DCA panel |

## Test results

### Backend tests (223 passed, 5 pre-existing failures)

| Test suite | Tests | Result |
|------------|-------|--------|
| `test_dca_validation_api.py` | 7 | **7 passed** |
| `test_dca_validation_reconstruction.py` | 9 | **9 passed** |
| `test_dca_validation_metrics.py` | 4 | **4 passed** |
| `test_dca_shadow_service.py` | 4 | **4 passed** |
| `test_dca_validation_models.py` | 4 | **4 passed** |
| **Total DCA validation tests** | **28** | **28 passed** |
| `test_portfolio_models.py` (existing) | 23 | **23 passed** (backward compatible) |
| Full backend suite | 228 | 223 passed, 5 failed (pre-existing: 4x DXY/yfinance network, 1x email mock) |

**Pre-existing failures** (not caused by this integration):
- `test_macro_service.py::test_fetch_dxy_*` (4 tests) — yfinance DNS resolution fails in this environment; unrelated to DCA validation
- `test_alerts.py::TestEmailSend::test_send_success` — email mock assertion; unrelated to DCA validation

### Frontend tests (23 passed)

| Test suite | Tests | Result |
|------------|-------|--------|
| `dca-validation-panels.test.tsx` | 6 | **6 passed** |
| `dca-validation/page.test.tsx` | 6 | **6 passed** |
| `dca-validation-api.test.ts` | 5 | **5 passed** |
| `app/page.test.tsx` (existing) | 5 | **5 passed** (backward compatible) |
| **Total frontend tests** | **23** | **23 passed** |

## Integration wiring performed

### Backend route registration
- `backend/routes/dca_validation.py` routes registered via `app.include_router(dca_validation_router)` in `backend/main.py`
- Route: `GET /api/v1/dca-validation/{exchange}` with query params (symbol, outcome, start_date, end_date, split_ratio, limit, timeout_ms)
- All routes require JWT auth (Depends(get_current_user))

### Backend model bootstrap
- 4 new SQLAlchemy model classes added to `backend/models.py`:
  - `DcaShadowGlobalKillSwitch` — global shadow ADD kill switch
  - `DcaShadowUserKillSwitch` — per-user shadow ADD kill switch
  - `DcaShadowSymbolKillSwitch` — per-user/symbol shadow ADD kill switch
  - `DcaShadowDecisionHistory` — audited shadow decision history
- Models imported in `backend/main.py` for `Base.metadata.create_all()` table creation
- Note: SQLite `create_all()` creates new tables on fresh installs. Existing databases need `alembic upgrade head` or a manual migration for the new tables.

### Frontend navigation
- `DcaValidationEntry` component added to the Portfolio DCA panel (`dca-panel.tsx`)
- Entry point visible below the action summary when the panel is expanded
- Validation page at `/portfolio/dca-validation` renders full validation UI

### Fix card resolution
- **t_2ada0b90** (backend contract fix): Route uses `reconstruct_scan_history` with `start_date`/`end_date` kwargs; `outcome` query param wired through to `list_shadow_history`; split-ratio validation rejects invalid values
- **t_128e11ec** (frontend composition fix): Page uses shared `dca-validation-api` helper and `dca-validation-types`; panels compose shared components; latest reconstructed events rendered; page tests cover all required states
- **t_e9f74049** (QA artifacts absent): All required implementation artifacts now exist in the integration worktree; QA can re-run against this branch

## Known limitations

1. **No Alembic migration for shadow tables.** The new DCA shadow models will be auto-created on fresh installs via `Base.metadata.create_all()`. Existing databases need a manual migration or `alembic revision --autogenerate -m "add dca shadow tables"`.

2. **No live exchange order is created, submitted, signed, queued, or simulated as a live order.** Shadow mode returns only `would_allow`, `would_block`, `would_reduce`, `would_close`, or `no_action` outcomes. The shadow service explicitly verifies no exchange order-placement path is called (test `test_no_action_for_hold_and_no_exchange_order_placement_paths_are_called` confirms this).

3. **Scan-to-scan reconstruction.** The reconstruction method is labeled "scan-to-scan" and is explicitly not candle-level historical replay. Results are labeled as simulated/reconstructed, not realized trading performance.

4. **Deprecation warning.** `HTTP_422_UNPROCESSABLE_ENTITY` is deprecated in the installed FastAPI version. This is a harmless warning that can be updated to `HTTP_422_UNPROCESSABLE_CONTENT` in a future release.

5. **Route registration bypasses routes/__init__.py.** The dca_validation route is imported directly in main.py rather than through the shared `routes/__init__.py` barrel. This is intentional per the route file's docstring ("integration card owns shared route wiring").

## Test commands

```bash
# Backend (from project root)
export JWT_SECRET_KEY="test-key"
python3 -m pytest backend/tests/test_dca_validation_api.py -v
python3 -m pytest backend/tests/test_dca_validation_reconstruction.py -v
python3 -m pytest backend/tests/test_dca_validation_metrics.py -v
python3 -m pytest backend/tests/test_dca_shadow_service.py -v
python3 -m pytest backend/tests/test_dca_validation_models.py -v
python3 -m pytest backend/tests/test_portfolio_models.py -v  # backward compat

# Frontend
cd frontend
npm install
npx jest --runInBand --verbose

# Full backend
python3 -m pytest backend/tests/ -v
```

## Safety statement

**No live exchange orders are created, submitted, signed, queued, or simulated as live orders in this release.** All DCA validation operations are read-only: they reconstruct historical scan events, compute metrics from persisted data, and evaluate shadow safety gates. The shadow mode explicitly returns only non-live outcomes (`would_allow`, `would_block`, `would_reduce`, `would_close`, `no_action`) and the test suite includes a dedicated test (`test_no_action_for_hold_and_no_exchange_order_placement_paths_are_called`) that confirms no exchange order-placement path is called.