# Phase 2B — MEXC Capital-Flow Ledger Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ingest MEXC funding, futures transfers, deposits, and withdrawals into a persistent idempotent ledger with honest per-stream coverage, expose `GET /portfolio/{exchange}/capital-flow`, and replace Phase 2A `not_enabled_phase_2b` placeholders with real sync states plus a read-only capital-flow UI.

**Architecture:** Mirror Phase 2A: capability-guarded fetchers in `exchange_service.py` return `(rows, _coverage(...))`; `phase2b_ledger.py` coerces rows (including `signed_amount` and synthetic ids), upserts into `capital_flow_ledger`, and writes `ExchangeSyncState` per stream; portfolio routes stop special-casing the four streams and serve a paginated capital-flow endpoint; frontend adds an INK & OXIDE capital-flow table/tab and drops Phase 2B placeholder copy in the sync panel.

**Tech Stack:** FastAPI, SQLAlchemy async, Alembic (SQLite batch mode), pytest/anyio, Next.js App Router, TypeScript, Jest/RTL, DESIGN.md INK & OXIDE tokens.

**Spec:** `docs/superpowers/specs/2026-08-04-phase-2b-capital-flow-ledger-design.md`

## Global Constraints

- Read-only exchange integration only — never create deposits/withdrawals/transfers/orders.
- No account-return calculation; `total_pnl_percent` / capital return stay deferred to Phase 3.
- No retention probe; report what the endpoint returns and mark the rest `partial` with `unrecoverable_gaps`.
- Only four streams: `funding`, `futures_transfers`, `deposits`, `withdrawals` (schema may tolerate more `entry_type` later).
- Coverage status machine reuses Phase 2A: `fresh` / `partial` / `error` / `unavailable` (+ existing `stale` for no sync state).
- Error messages redacted (`_redact_error`); never store live secrets in fixtures.
- Idempotent upsert on `(user_id, exchange, entry_type, exchange_entry_id)` with partial unique index where source id is not null; id-less rows get deterministic synthetic id.
- Signed amount: deposit `+amount`, withdrawal `−amount`, futures_transfer into futures `+` / out `−`, funding receipt `+` / payment `−`.
- Stream names in `ExchangeSyncState` must match existing panel keys: `funding`, `futures_transfers`, `deposits`, `withdrawals`.
- Wire fetchers into history/sync refresh path (`fetch_history` and the history portion of `fetch_portfolio`), not hot balances/price ticks.
- MEXC method resolution: prefer contract private methods already on ccxt mexc for funding/transfers (`contract_private_get_position_funding_records`, `contract_private_get_account_transfer_record` + `_paginate_mexc_history`); deposits/withdrawals use `fetch_deposits` / `fetch_withdrawals` when present, else `unavailable` / `stream_not_supported`.
- Frontend capital-flow UI uses INK & OXIDE hex tokens (`#161411`, `#2A2620`, `#EDE7DB`, `#C2A36B`, `#8E8778`, verdigris/rust for signed amounts) — no slate/indigo.
- Bump `frontend/public/sw.js` `CACHE_NAME` (v5 → v6) with this UI surface.
- TDD: write failing tests first for each task; no live MEXC calls in tests.

## File Structure

| Path | Responsibility |
|---|---|
| `backend/migrations/versions/20260804_phase2b_capital_flow.py` | Create `capital_flow_ledger` + indexes; down-revision `20260725_phase2a_mexc_sync` |
| `backend/models.py` | `CapitalFlowLedger` ORM + `User.capital_flow_ledger` relationship |
| `backend/services/phase2b_ledger.py` | Coerce, synthetic id, signed amounts, `persist_capital_flow_payload`, list helpers |
| `backend/services/exchange_service.py` | Four `_fetch_*_with_coverage` fetchers; wire into `fetch_history` / `fetch_portfolio` |
| `backend/routes/portfolio.py` | Drop `not_enabled_phase_2b` defaults; `GET .../capital-flow`; persist capital-flow rows |
| `backend/tests/fixtures/phase2b_ledger.py` | Redacted static MEXC/ccxt-shaped rows for four streams + id-less cases |
| `backend/tests/test_phase2b_migration.py` | Upgrade/downgrade + indexes |
| `backend/tests/test_phase2b_ledger.py` | Coerce, signed amounts, idempotency, coverage persistence |
| `backend/tests/test_phase2b_capital_flow_api.py` | Endpoint sort, coverage, user isolation |
| `backend/tests/test_phase2a_portfolio_api.py` | Update assertions that expected `not_enabled_phase_2b` |
| `frontend/lib/types.ts` | `CapitalFlowEntry`, `CapitalFlowResponse` |
| `frontend/components/portfolio/capital-flow-table.tsx` | Read-only table + coverage banner |
| `frontend/components/portfolio/capital-flow-table.test.tsx` | Render/format/banner tests |
| `frontend/components/portfolio/sync-status-panel.tsx` | Real states; Phase 2B placeholder copy retired for ingested streams |
| `frontend/components/portfolio/sync-status-panel.test.tsx` | Real states for four streams |
| `frontend/components/portfolio/portfolio-dashboard.tsx` | Capital Flow tab; client fetch of capital-flow endpoint |
| `frontend/components/portfolio/portfolio-dashboard-phase2a.test.tsx` | Update Phase 2B placeholder expectations |
| `frontend/public/sw.js` | Cache name bump |

---

### Task 1: Migration + `CapitalFlowLedger` model

**Files:**
- Create: `backend/migrations/versions/20260804_phase2b_capital_flow.py`
- Modify: `backend/models.py` (after `ExchangeSyncState`, ~line 319; also `User` relationships ~line 33)
- Test: `backend/tests/test_phase2b_migration.py`

**Interfaces:**
- Consumes: Alembic head `20260725_phase2a_mexc_sync`
- Produces: table `capital_flow_ledger`; model `CapitalFlowLedger`; partial unique index `uq_capital_flow_user_exchange_type_source_id`; chronological index `ix_capital_flow_user_exchange_occurred`

- [ ] **Step 1: Write the failing migration test**

Create `backend/tests/test_phase2b_migration.py`:

```python
"""Phase 2B capital-flow ledger Alembic migration tests."""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = PROJECT_ROOT / "backend"
ALEMBIC_INI = BACKEND_DIR / "alembic.ini"
PRE_PHASE2B_REVISION = "20260725_phase2a_mexc_sync"
PHASE2B_REVISION = "20260804_phase2b_capital_flow"


def _run_alembic(db_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.setdefault("JWT_SECRET_KEY", "test-key-not-for-production")
    env["DATABASE_URL"] = f"sqlite+aiosqlite:///{db_path}"
    return subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(ALEMBIC_INI), *args],
        cwd=PROJECT_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def _columns(db_path: Path, table: str) -> set[str]:
    with sqlite3.connect(db_path) as conn:
        return {row[1] for row in conn.execute(f"PRAGMA table_info('{table}')")}


def _indexes(db_path: Path, table: str) -> dict[str, str]:
    with sqlite3.connect(db_path) as conn:
        indexes = {}
        for row in conn.execute(f"PRAGMA index_list('{table}')"):
            name = row[1]
            sql = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='index' AND name=?",
                (name,),
            ).fetchone()
            indexes[name] = (sql[0] if sql else "") or ""
        return indexes


def test_phase2b_upgrade_creates_ledger_indexes_and_downgrade_drops_table(tmp_path):
    db_path = tmp_path / "phase2b_migration.db"

    before = _run_alembic(db_path, "upgrade", PRE_PHASE2B_REVISION)
    assert before.returncode == 0, before.stderr + before.stdout
    assert not _columns(db_path, "capital_flow_ledger")

    upgrade = _run_alembic(db_path, "upgrade", PHASE2B_REVISION)
    assert upgrade.returncode == 0, upgrade.stderr + upgrade.stdout

    cols = _columns(db_path, "capital_flow_ledger")
    assert {
        "id",
        "user_id",
        "exchange",
        "entry_type",
        "exchange_entry_id",
        "asset",
        "amount",
        "signed_amount",
        "status",
        "occurred_at",
        "source_updated_at",
        "synced_at",
        "raw_json",
    }.issubset(cols)

    indexes = _indexes(db_path, "capital_flow_ledger")
    assert "uq_capital_flow_user_exchange_type_source_id" in indexes
    assert "WHERE exchange_entry_id IS NOT NULL" in indexes["uq_capital_flow_user_exchange_type_source_id"]
    assert "ix_capital_flow_user_exchange_occurred" in indexes

    downgrade = _run_alembic(db_path, "downgrade", PRE_PHASE2B_REVISION)
    assert downgrade.returncode == 0, downgrade.stderr + downgrade.stdout
    assert not _columns(db_path, "capital_flow_ledger")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/mustcompanymohsin/orca/workspaces/miraj-dashboard/main-2
python -m pytest backend/tests/test_phase2b_migration.py -v
```

Expected: FAIL (revision / table missing).

- [ ] **Step 3: Add model + migration**

Append to `User` relationships in `backend/models.py`:

```python
capital_flow_ledger = relationship("CapitalFlowLedger", back_populates="user", cascade="all, delete-orphan")
```

Add model after `ExchangeSyncState`:

```python
class CapitalFlowLedger(Base):
    """Idempotent capital-flow ledger (funding, transfers, deposits, withdrawals)."""

    __tablename__ = "capital_flow_ledger"
    __table_args__ = (
        Index(
            "uq_capital_flow_user_exchange_type_source_id",
            "user_id",
            "exchange",
            "entry_type",
            "exchange_entry_id",
            unique=True,
            sqlite_where=sa_text("exchange_entry_id IS NOT NULL") if False else None,
        ),
        Index("ix_capital_flow_user_exchange_occurred", "user_id", "exchange", "occurred_at"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    exchange = Column(String(32), nullable=False)
    entry_type = Column(String(32), nullable=False)
    exchange_entry_id = Column(String(128), nullable=True)
    asset = Column(String(32), nullable=False)
    amount = Column(Float, nullable=True)
    signed_amount = Column(Float, nullable=True)
    status = Column(String(32), nullable=True)
    occurred_at = Column(DateTime, nullable=True)
    source_updated_at = Column(DateTime, nullable=True)
    synced_at = Column(DateTime, nullable=False)
    raw_json = Column(Text, nullable=True)

    user = relationship("User", back_populates="capital_flow_ledger")
```

**Important ORM note:** SQLAlchemy partial indexes need `sqlite_where` via dialect kwargs. Prefer this exact pattern (matches Phase 2A migration style for uniqueness, model index for chronological):

```python
from sqlalchemy import text as sa_text

class CapitalFlowLedger(Base):
    __tablename__ = "capital_flow_ledger"
    __table_args__ = (
        Index("ix_capital_flow_user_exchange_occurred", "user_id", "exchange", "occurred_at"),
    )
    # columns as above...
```

Put the **partial unique index only in the Alembic migration** (Phase 2A did the same for position/order source ids). ORM uniqueness is enforced by upsert lookup in `phase2b_ledger.py`.

Create `backend/migrations/versions/20260804_phase2b_capital_flow.py`:

```python
"""phase2b capital flow ledger

Revision ID: 20260804_phase2b_capital_flow
Revises: 20260725_phase2a_mexc_sync
Create Date: 2026-08-04
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260804_phase2b_capital_flow"
down_revision: Union[str, Sequence[str], None] = "20260725_phase2a_mexc_sync"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "capital_flow_ledger",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("exchange", sa.String(length=32), nullable=False),
        sa.Column("entry_type", sa.String(length=32), nullable=False),
        sa.Column("exchange_entry_id", sa.String(length=128), nullable=True),
        sa.Column("asset", sa.String(length=32), nullable=False),
        sa.Column("amount", sa.Float(), nullable=True),
        sa.Column("signed_amount", sa.Float(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=True),
        sa.Column("occurred_at", sa.DateTime(), nullable=True),
        sa.Column("source_updated_at", sa.DateTime(), nullable=True),
        sa.Column("synced_at", sa.DateTime(), nullable=False),
        sa.Column("raw_json", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_capital_flow_ledger_user_id"),
        "capital_flow_ledger",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_capital_flow_user_exchange_occurred",
        "capital_flow_ledger",
        ["user_id", "exchange", "occurred_at"],
        unique=False,
    )
    op.create_index(
        "uq_capital_flow_user_exchange_type_source_id",
        "capital_flow_ledger",
        ["user_id", "exchange", "entry_type", "exchange_entry_id"],
        unique=True,
        sqlite_where=sa.text("exchange_entry_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_capital_flow_user_exchange_type_source_id", table_name="capital_flow_ledger")
    op.drop_index("ix_capital_flow_user_exchange_occurred", table_name="capital_flow_ledger")
    op.drop_index(op.f("ix_capital_flow_ledger_user_id"), table_name="capital_flow_ledger")
    op.drop_table("capital_flow_ledger")
```

- [ ] **Step 4: Run migration test to verify it passes**

```bash
python -m pytest backend/tests/test_phase2b_migration.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/migrations/versions/20260804_phase2b_capital_flow.py backend/models.py backend/tests/test_phase2b_migration.py
git commit -m "$(cat <<'EOF'
feat(phase2b): add capital_flow_ledger migration and model

EOF
)"
```

---

### Task 2: Fixtures + coerce/persist ledger service (TDD)

**Files:**
- Create: `backend/tests/fixtures/phase2b_ledger.py`
- Create: `backend/services/phase2b_ledger.py`
- Create: `backend/tests/test_phase2b_ledger.py`

**Interfaces:**
- Consumes: `CapitalFlowLedger`, `ExchangeSyncState`; reuses `_upsert_sync_state` pattern from `phase2a_sync` (either import private helper by extracting shared util, or duplicate the small upsert block inside `phase2b_ledger` — **prefer importing** by promoting `_upsert_sync_state` to a shared name if needed; simplest: copy the function body into `phase2b_ledger._upsert_sync_state` identically to avoid large refactors).
- Produces:
  - `ENTRY_TYPES = ("funding", "futures_transfer", "deposit", "withdrawal")` (DB `entry_type` values; stream names use plurals for deposits/withdrawals/transfers)
  - Stream keys in coverage: `funding`, `futures_transfers`, `deposits`, `withdrawals`
  - `synthetic_exchange_entry_id(entry_type, asset, amount, occurred_at) -> str`
  - `coerce_funding_row(raw) -> dict`
  - `coerce_futures_transfer_row(raw) -> dict`
  - `coerce_deposit_row(raw) -> dict`
  - `coerce_withdrawal_row(raw) -> dict`
  - `async def persist_capital_flow_payload(session, user_id, exchange, payload, now) -> None`
  - Payload shape:
    ```python
    {
      "funding": [row, ...],
      "futures_transfers": [...],
      "deposits": [...],
      "withdrawals": [...],
      "sync": {
        "funding": coverage_dict,
        "futures_transfers": coverage_dict,
        "deposits": coverage_dict,
        "withdrawals": coverage_dict,
      },
    }
    ```
  - Coerced row dict keys: `entry_type`, `exchange_entry_id`, `asset`, `amount`, `signed_amount`, `status`, `occurred_at`, `source_updated_at`, `raw_json` (JSON string of redacted source fields)

**Signed-amount rules (must match tests):**

| entry_type | signed_amount |
|---|---|
| `funding` | `+abs(amount)` if receipt (MEXC `funding`/`cash` positive or `type` in receipt set); `−abs(amount)` if payment |
| `futures_transfer` | `+abs` into futures (`type` in {`IN`, `1`, `in`, `TRANSFER_IN`}); `−abs` out |
| `deposit` | `+abs(amount)` |
| `withdrawal` | `−abs(amount)` |

- [ ] **Step 1: Write fixtures**

Create `backend/tests/fixtures/phase2b_ledger.py`:

```python
"""Static redacted Phase 2B capital-flow fixtures. Synthetic only — never live keys."""

from __future__ import annotations

BASE_MS = 1_786_100_000_000


def funding_row(
    entry_id: str | None = "redacted-fund-001",
    *,
    funding: str = "-1.25",
    currency: str = "USDT",
    offset: int = 0,
) -> dict:
    ts = BASE_MS + offset * 60_000
    row = {
        "symbol": "BTC_USDT",
        "currency": currency,
        "funding": funding,
        "fundingRate": "0.0001",
        "positionValue": "1000",
        "positionType": "1",
        "settleTime": ts,
        "createTime": ts - 1000,
    }
    if entry_id is not None:
        row["id"] = entry_id
    return row


def futures_transfer_row(
    entry_id: str | None = "redacted-xfer-001",
    *,
    amount: str = "50.0",
    transfer_type: str = "IN",
    currency: str = "USDT",
    offset: int = 0,
) -> dict:
    ts = BASE_MS + offset * 60_000
    row = {
        "currency": currency,
        "amount": amount,
        "type": transfer_type,
        "state": "SUCCESS",
        "createTime": ts,
        "updateTime": ts + 500,
    }
    if entry_id is not None:
        row["id"] = entry_id
        row["tranId"] = entry_id
    return row


def deposit_row(
    entry_id: str | None = "redacted-dep-001",
    *,
    amount: float = 100.0,
    currency: str = "USDT",
    offset: int = 0,
) -> dict:
    """ccxt-unified shaped deposit."""
    ts = BASE_MS + offset * 60_000
    row = {
        "currency": currency,
        "amount": amount,
        "status": "ok",
        "timestamp": ts,
        "datetime": None,
        "txid": f"tx-{entry_id}" if entry_id else None,
        "info": {"coin": currency, "amount": str(amount), "status": "5"},
    }
    if entry_id is not None:
        row["id"] = entry_id
    return row


def withdrawal_row(
    entry_id: str | None = "redacted-wd-001",
    *,
    amount: float = 25.0,
    currency: str = "USDT",
    offset: int = 0,
) -> dict:
    ts = BASE_MS + offset * 60_000
    row = {
        "currency": currency,
        "amount": amount,
        "status": "ok",
        "timestamp": ts,
        "txid": f"tx-{entry_id}" if entry_id else None,
        "info": {"coin": currency, "amount": str(amount), "status": "7"},
    }
    if entry_id is not None:
        row["id"] = entry_id
    return row


FUNDING_WITH_ID = funding_row("redacted-fund-001", funding="-1.25", offset=1)
FUNDING_RECEIPT = funding_row("redacted-fund-002", funding="0.55", offset=2)
FUNDING_IDLESS = funding_row(None, funding="-0.10", offset=3)
TRANSFER_IN = futures_transfer_row("redacted-xfer-in", amount="50.0", transfer_type="IN", offset=4)
TRANSFER_OUT = futures_transfer_row("redacted-xfer-out", amount="20.0", transfer_type="OUT", offset=5)
DEPOSIT = deposit_row("redacted-dep-001", amount=100.0, offset=6)
WITHDRAWAL = withdrawal_row("redacted-wd-001", amount=25.0, offset=7)
DEPOSIT_IDLESS = deposit_row(None, amount=11.0, offset=8)
```

- [ ] **Step 2: Write failing ledger unit tests**

Create `backend/tests/test_phase2b_ledger.py` (session fixture mirrored from `test_phase2a_mexc_sync.py`):

```python
"""Phase 2B capital-flow ledger coerce + persist tests."""

from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime

import pytest
from sqlalchemy import func, select

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

os.environ.setdefault("JWT_SECRET_KEY", "test-key-not-for-production")

from backend import database
from backend.auth import hash_password
from backend.database import Base, set_db_path
from backend.models import CapitalFlowLedger, ExchangeSyncState, User
from backend.tests.fixtures.phase2b_ledger import (
    DEPOSIT,
    DEPOSIT_IDLESS,
    FUNDING_IDLESS,
    FUNDING_RECEIPT,
    FUNDING_WITH_ID,
    TRANSFER_IN,
    TRANSFER_OUT,
    WITHDRAWAL,
)

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def tmp_db_path():
    fd, path = tempfile.mkstemp(suffix=".db", prefix="phase2b_ledger_")
    os.close(fd)
    yield path
    try:
        os.unlink(path)
    except OSError:
        pass


@pytest.fixture
async def session(tmp_db_path: str):
    database._DB_PATH = None
    database._engine = None
    database._session_factory = None
    set_db_path(tmp_db_path)
    engine = database.get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = database.get_session_factory()
    async with factory() as s:
        yield s


async def _user(session, username: str = "phase2bledger") -> User:
    user = User(
        username=username,
        email=f"{username}@test.local",
        hashed_password=hash_password("testpass123"),
    )
    session.add(user)
    await session.flush()
    await session.refresh(user)
    return user


def test_signed_amount_conventions():
    from backend.services.phase2b_ledger import (
        coerce_deposit_row,
        coerce_funding_row,
        coerce_futures_transfer_row,
        coerce_withdrawal_row,
    )

    assert coerce_funding_row(FUNDING_WITH_ID)["signed_amount"] == -1.25
    assert coerce_funding_row(FUNDING_RECEIPT)["signed_amount"] == 0.55
    assert coerce_futures_transfer_row(TRANSFER_IN)["signed_amount"] == 50.0
    assert coerce_futures_transfer_row(TRANSFER_OUT)["signed_amount"] == -20.0
    assert coerce_deposit_row(DEPOSIT)["signed_amount"] == 100.0
    assert coerce_withdrawal_row(WITHDRAWAL)["signed_amount"] == -25.0


def test_idless_rows_get_stable_synthetic_exchange_entry_id():
    from backend.services.phase2b_ledger import coerce_funding_row, synthetic_exchange_entry_id

    a = coerce_funding_row(FUNDING_IDLESS)
    b = coerce_funding_row(dict(FUNDING_IDLESS))
    assert a["exchange_entry_id"]
    assert a["exchange_entry_id"] == b["exchange_entry_id"]
    assert a["exchange_entry_id"].startswith("synth:")
    # deterministic for same inputs
    assert a["exchange_entry_id"] == synthetic_exchange_entry_id(
        a["entry_type"], a["asset"], a["amount"], a["occurred_at"]
    )


async def test_persist_is_idempotent_on_double_ingest(session):
    from backend.services.phase2b_ledger import persist_capital_flow_payload

    user = await _user(session)
    now = datetime(2026, 8, 4, 12, 0, 0)
    payload = {
        "funding": [FUNDING_WITH_ID, FUNDING_IDLESS],
        "futures_transfers": [TRANSFER_IN, TRANSFER_OUT],
        "deposits": [DEPOSIT, DEPOSIT_IDLESS],
        "withdrawals": [WITHDRAWAL],
        "sync": {
            "funding": {"status": "fresh", "complete": True, "rows_fetched_total": 2, "source_total": 2},
            "futures_transfers": {"status": "fresh", "complete": True, "rows_fetched_total": 2, "source_total": 2},
            "deposits": {"status": "partial", "complete": False, "reason": "exchange_boundary_before_source_total", "rows_fetched_total": 2, "source_total": 10, "unrecoverable_gaps": [{"stream": "deposits", "reason": "exchange_boundary_before_source_total"}]},
            "withdrawals": {"status": "fresh", "complete": True, "rows_fetched_total": 1, "source_total": 1},
        },
    }
    await persist_capital_flow_payload(session, user.id, "mexc", payload, now)
    await session.commit()
    await persist_capital_flow_payload(session, user.id, "mexc", payload, now)
    await session.commit()

    count = await session.scalar(select(func.count()).select_from(CapitalFlowLedger))
    assert count == 7

    funding_state = await session.scalar(
        select(ExchangeSyncState).where(ExchangeSyncState.stream == "funding")
    )
    deposits_state = await session.scalar(
        select(ExchangeSyncState).where(ExchangeSyncState.stream == "deposits")
    )
    assert funding_state.status == "fresh"
    assert funding_state.complete is True
    assert deposits_state.status == "partial"
    assert deposits_state.complete is False
    assert deposits_state.partial_reason == "exchange_boundary_before_source_total"


async def test_unavailable_and_error_coverage_states_persist(session):
    from backend.services.phase2b_ledger import persist_capital_flow_payload

    user = await _user(session, "phase2bcov")
    now = datetime(2026, 8, 4, 13, 0, 0)
    await persist_capital_flow_payload(
        session,
        user.id,
        "mexc",
        {
            "funding": [],
            "futures_transfers": [],
            "deposits": [],
            "withdrawals": [],
            "sync": {
                "funding": {"status": "unavailable", "complete": False, "reason": "stream_not_supported", "rows_fetched_total": 0},
                "futures_transfers": {"status": "error", "complete": False, "error_code": "510", "error_message": "rate limited for REDACTED synthetic-key value", "rows_fetched_total": 0},
                "deposits": {"status": "unavailable", "complete": False, "reason": "stream_not_supported", "rows_fetched_total": 0},
                "withdrawals": {"status": "unavailable", "complete": False, "reason": "stream_not_supported", "rows_fetched_total": 0},
            },
        },
        now,
    )
    await session.commit()
    states = {
        row.stream: row
        for row in (
            await session.scalars(select(ExchangeSyncState).where(ExchangeSyncState.user_id == user.id))
        ).all()
    }
    assert states["funding"].status == "unavailable"
    assert states["futures_transfers"].status == "error"
    assert "synthetic-key" not in (states["futures_transfers"].error_message_redacted or "")
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
python -m pytest backend/tests/test_phase2b_ledger.py -v
```

Expected: FAIL (module missing).

- [ ] **Step 4: Implement `backend/services/phase2b_ledger.py`**

```python
"""Phase 2B capital-flow ledger coerce + idempotent persist."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Dict, Iterable, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import CapitalFlowLedger, ExchangeSyncState

STREAM_TO_ENTRY_TYPE = {
    "funding": "funding",
    "futures_transfers": "futures_transfer",
    "deposits": "deposit",
    "withdrawals": "withdrawal",
}
ENTRY_STREAMS = tuple(STREAM_TO_ENTRY_TYPE.keys())


def _mexc_datetime(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.utcfromtimestamp(int(value) / 1000.0)
    except (TypeError, ValueError):
        return None


def _safe_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def synthetic_exchange_entry_id(
    entry_type: str,
    asset: str,
    amount: Optional[float],
    occurred_at: Optional[datetime],
) -> str:
    ts = occurred_at.isoformat() if occurred_at else ""
    amt = "" if amount is None else f"{amount:.12g}"
    digest = hashlib.sha256(f"{entry_type}|{asset}|{amt}|{ts}".encode("utf-8")).hexdigest()
    return f"synth:{digest[:48]}"


def _ensure_source_id(row: Dict[str, Any]) -> Dict[str, Any]:
    if row.get("exchange_entry_id"):
        row["exchange_entry_id"] = str(row["exchange_entry_id"])[:128]
        return row
    row["exchange_entry_id"] = synthetic_exchange_entry_id(
        row["entry_type"], row["asset"], row.get("amount"), row.get("occurred_at")
    )
    return row


def _raw_json(raw: Dict[str, Any]) -> str:
    return json.dumps(raw, default=str, separators=(",", ":"))


def coerce_funding_row(raw: Dict[str, Any]) -> Dict[str, Any]:
    if raw.get("entry_type") == "funding" and "signed_amount" in raw:
        return _ensure_source_id(dict(raw))
    amount = _safe_float(raw.get("funding") if raw.get("funding") is not None else raw.get("amount"))
    occurred = _mexc_datetime(raw.get("settleTime") or raw.get("createTime") or raw.get("timestamp"))
    source_id = raw.get("id") or raw.get("fundingRecordId")
    # signed: preserve exchange sign when present; else treat as payment if negative type flags appear
    signed = amount
    if signed is not None:
        # funding already signed in MEXC samples; keep sign
        pass
    row = {
        "entry_type": "funding",
        "exchange_entry_id": str(source_id) if source_id is not None else None,
        "asset": str(raw.get("currency") or raw.get("asset") or "USDT"),
        "amount": abs(amount) if amount is not None else None,
        "signed_amount": signed,
        "status": str(raw.get("state") or raw.get("status") or "") or None,
        "occurred_at": occurred,
        "source_updated_at": _mexc_datetime(raw.get("updateTime")) or occurred,
        "raw_json": _raw_json(raw),
    }
    return _ensure_source_id(row)


def coerce_futures_transfer_row(raw: Dict[str, Any]) -> Dict[str, Any]:
    if raw.get("entry_type") == "futures_transfer" and "signed_amount" in raw:
        return _ensure_source_id(dict(raw))
    amount = _safe_float(raw.get("amount"))
    t = str(raw.get("type") or raw.get("transferType") or "").upper()
    into_futures = t in {"IN", "1", "TRANSFER_IN", "INCOME", "DEPOSIT"}
    out_futures = t in {"OUT", "2", "TRANSFER_OUT", "OUTCOME", "WITHDRAW"}
    if amount is None:
        signed = None
    elif into_futures:
        signed = abs(amount)
    elif out_futures:
        signed = -abs(amount)
    else:
        # unknown type: preserve numeric sign if any, else +abs
        signed = amount
    occurred = _mexc_datetime(raw.get("createTime") or raw.get("timestamp"))
    source_id = raw.get("id") or raw.get("tranId") or raw.get("transferId")
    row = {
        "entry_type": "futures_transfer",
        "exchange_entry_id": str(source_id) if source_id is not None else None,
        "asset": str(raw.get("currency") or raw.get("asset") or "USDT"),
        "amount": abs(amount) if amount is not None else None,
        "signed_amount": signed,
        "status": str(raw.get("state") or raw.get("status") or "") or None,
        "occurred_at": occurred,
        "source_updated_at": _mexc_datetime(raw.get("updateTime")) or occurred,
        "raw_json": _raw_json(raw),
    }
    return _ensure_source_id(row)


def coerce_deposit_row(raw: Dict[str, Any]) -> Dict[str, Any]:
    if raw.get("entry_type") == "deposit" and "signed_amount" in raw:
        return _ensure_source_id(dict(raw))
    amount = _safe_float(raw.get("amount"))
    occurred = _mexc_datetime(raw.get("timestamp") or raw.get("createTime"))
    source_id = raw.get("id") or raw.get("txid")
    row = {
        "entry_type": "deposit",
        "exchange_entry_id": str(source_id) if source_id is not None else None,
        "asset": str(raw.get("currency") or raw.get("asset") or "USDT"),
        "amount": abs(amount) if amount is not None else None,
        "signed_amount": abs(amount) if amount is not None else None,
        "status": str(raw.get("status") or "") or None,
        "occurred_at": occurred,
        "source_updated_at": occurred,
        "raw_json": _raw_json(raw),
    }
    return _ensure_source_id(row)


def coerce_withdrawal_row(raw: Dict[str, Any]) -> Dict[str, Any]:
    if raw.get("entry_type") == "withdrawal" and "signed_amount" in raw:
        return _ensure_source_id(dict(raw))
    amount = _safe_float(raw.get("amount"))
    occurred = _mexc_datetime(raw.get("timestamp") or raw.get("createTime"))
    source_id = raw.get("id") or raw.get("txid")
    row = {
        "entry_type": "withdrawal",
        "exchange_entry_id": str(source_id) if source_id is not None else None,
        "asset": str(raw.get("currency") or raw.get("asset") or "USDT"),
        "amount": abs(amount) if amount is not None else None,
        "signed_amount": -abs(amount) if amount is not None else None,
        "status": str(raw.get("status") or "") or None,
        "occurred_at": occurred,
        "source_updated_at": occurred,
        "raw_json": _raw_json(raw),
    }
    return _ensure_source_id(row)


_COERCERS = {
    "funding": coerce_funding_row,
    "futures_transfers": coerce_futures_transfer_row,
    "deposits": coerce_deposit_row,
    "withdrawals": coerce_withdrawal_row,
}


async def persist_capital_flow_payload(
    session: AsyncSession,
    user_id: int,
    exchange: str,
    payload: Dict[str, Any],
    now: datetime,
) -> None:
    for stream, coercer in _COERCERS.items():
        rows = payload.get(stream) or []
        await _upsert_entries(session, user_id, exchange, [coercer(r) for r in rows], now)
    for stream, coverage in (payload.get("sync") or {}).items():
        if stream in ENTRY_STREAMS or stream in STREAM_TO_ENTRY_TYPE:
            await _upsert_sync_state(session, user_id, exchange, stream, coverage, now)


async def _upsert_entries(
    session: AsyncSession,
    user_id: int,
    exchange: str,
    rows: Iterable[Dict[str, Any]],
    now: datetime,
) -> None:
    seen: set[str] = set()
    for row in rows:
        source_id = row.get("exchange_entry_id")
        if not source_id:
            continue
        key = f"{row['entry_type']}:{source_id}"
        if key in seen:
            continue
        seen.add(key)
        existing = await session.scalar(
            select(CapitalFlowLedger).where(
                CapitalFlowLedger.user_id == user_id,
                CapitalFlowLedger.exchange == exchange,
                CapitalFlowLedger.entry_type == row["entry_type"],
                CapitalFlowLedger.exchange_entry_id == str(source_id),
            )
        )
        target = existing or CapitalFlowLedger(user_id=user_id, exchange=exchange)
        target.entry_type = row["entry_type"]
        target.exchange_entry_id = str(source_id)
        target.asset = row["asset"]
        target.amount = row.get("amount")
        target.signed_amount = row.get("signed_amount")
        target.status = row.get("status")
        target.occurred_at = row.get("occurred_at")
        target.source_updated_at = row.get("source_updated_at")
        target.synced_at = now
        target.raw_json = row.get("raw_json")
        session.add(target)


async def _upsert_sync_state(
    session: AsyncSession,
    user_id: int,
    exchange: str,
    stream: str,
    coverage: Dict[str, Any],
    now: datetime,
) -> None:
    target = await session.scalar(
        select(ExchangeSyncState).where(
            ExchangeSyncState.user_id == user_id,
            ExchangeSyncState.exchange == exchange,
            ExchangeSyncState.stream == stream,
        )
    )
    target = target or ExchangeSyncState(user_id=user_id, exchange=exchange, stream=stream)
    complete = bool(coverage.get("complete"))
    target.status = coverage.get("status") or ("fresh" if complete else "partial")
    target.cursor_json = coverage.get("cursor")
    target.oldest_source_ts = coverage.get("oldest_source_ts")
    target.newest_source_ts = coverage.get("newest_source_ts")
    target.rows_fetched_total = int(coverage.get("rows_fetched_total") or 0)
    target.source_total = coverage.get("source_total")
    target.complete = complete
    target.partial_reason = coverage.get("reason")
    target.unrecoverable_gaps_json = coverage.get("unrecoverable_gaps") or []
    target.last_attempt_at = now
    if complete:
        target.last_success_at = now
        target.error_code = None
        target.error_message_redacted = None
    else:
        target.error_code = coverage.get("error_code")
        target.error_message_redacted = coverage.get("error_message")
        if coverage.get("status") in {"fresh", "partial"} and complete is False:
            pass
        if coverage.get("status") == "partial" and coverage.get("last_success_at") is None:
            # still record attempt; success only when complete
            pass
    # Mark success timestamp for partial successes that still returned rows
    if coverage.get("status") in {"fresh", "partial"} and int(coverage.get("rows_fetched_total") or 0) > 0:
        target.last_success_at = now
        if coverage.get("status") == "fresh":
            target.error_code = None
            target.error_message_redacted = None
    target.updated_at = now
    session.add(target)
```

Tune `_upsert_sync_state` so it matches Phase 2A behavior exactly if tests demand: prefer copying `phase2a_sync._upsert_sync_state` line-for-line (including only setting `last_success_at` when `complete`). Adjust the double-ingest test if Phase 2A semantics mark partial without last_success — keep identical to Phase 2A.

- [ ] **Step 5: Run tests to verify they pass**

```bash
python -m pytest backend/tests/test_phase2b_ledger.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/services/phase2b_ledger.py backend/tests/fixtures/phase2b_ledger.py backend/tests/test_phase2b_ledger.py
git commit -m "$(cat <<'EOF'
feat(phase2b): coerce and idempotently persist capital-flow ledger

EOF
)"
```

---

### Task 3: Exchange fetchers + history/sync wiring

**Files:**
- Modify: `backend/services/exchange_service.py`
- Modify: `backend/tests/test_phase2b_ledger.py` or create additional cases in `backend/tests/test_phase2a_mexc_sync.py` — prefer new tests in `backend/tests/test_phase2b_ledger.py` for fetcher coverage using a `MockMexcExchange` extension

**Interfaces:**
- Produces:
  - `_fetch_funding_history_with_coverage(exchange, user_id, exchange_name) -> Tuple[List[dict], dict]`
  - `_fetch_futures_transfers_with_coverage(...)`
  - `_fetch_deposits_with_coverage(...)`
  - `_fetch_withdrawals_with_coverage(...)`
- `fetch_history` and `fetch_portfolio` include the four streams in `sync` and raw lists under keys `funding`, `futures_transfers`, `deposits`, `withdrawals`
- Capability guards:
  - funding: `exchange_name == "mexc" and hasattr(exchange, "contract_private_get_position_funding_records")`
  - futures_transfers: `... contract_private_get_account_transfer_record`
  - deposits: `hasattr(exchange, "fetch_deposits")` (or `fetchDeposits`)
  - withdrawals: `hasattr(exchange, "fetch_withdrawals")`
- Contract streams use `_paginate_mexc_history` then coerce via `phase2b_ledger.coerce_*` (or return raw rows and let persist coerce — **return already-coerced rows** so API can reuse them).
- Unified deposits/withdrawals: call with `limit=100` once; if `len(rows) >= 100` mark `partial` with `exchange_boundary_before_source_total`; on exception use `_translate`/`_coverage` error path with redaction.

- [ ] **Step 1: Write failing fetcher tests**

Append to `backend/tests/test_phase2b_ledger.py`:

```python
class MockMexcCapitalExchange:
    id = "mexc"
    markets = {}

    def __init__(self, **streams):
        self._streams = streams
        self.funding_pages_requested = []

    def contract_private_get_position_funding_records(self, params):
        self.funding_pages_requested.append(params["pageNum"])
        pages = self._streams.get("funding_pages", [[]])
        if isinstance(pages, dict):
            return pages
        page = pages[params["pageNum"] - 1] if params["pageNum"] <= len(pages) else []
        return {
            "success": True,
            "data": {
                "list": page,
                "totalPage": max(len(pages), 1),
                "total": sum(len(p) for p in pages),
                "pageNum": params["pageNum"],
                "pageSize": 100,
            },
        }

    def contract_private_get_account_transfer_record(self, params):
        pages = self._streams.get("transfer_pages", [[]])
        page = pages[params["pageNum"] - 1] if params["pageNum"] <= len(pages) else []
        return {
            "success": True,
            "data": {
                "list": page,
                "totalPage": max(len(pages), 1),
                "total": sum(len(p) for p in pages),
            },
        }

    def fetch_deposits(self, code=None, since=None, limit=None, params=None):
        return self._streams.get("deposits", [])

    def fetch_withdrawals(self, code=None, since=None, limit=None, params=None):
        return self._streams.get("withdrawals", [])


async def test_fetch_history_includes_capital_flow_streams_and_coverage():
    from backend.services.exchange_service import fetch_history

    exchange = MockMexcCapitalExchange(
        funding_pages=[[FUNDING_WITH_ID, FUNDING_RECEIPT]],
        transfer_pages=[[TRANSFER_IN]],
        deposits=[DEPOSIT],
        withdrawals=[WITHDRAWAL],
    )
    # attach position/order methods as empty so Phase 2A streams stay available
    exchange.contract_private_get_position_list_history_positions = lambda params: {
        "success": True, "data": {"list": [], "totalPage": 1, "total": 0}
    }
    exchange.contract_private_get_order_list_history_orders = lambda params: {
        "success": True, "data": {"list": [], "totalPage": 1, "total": 0}
    }

    data = await fetch_history(exchange, user_id=9)
    assert "funding" in data["sync"]
    assert data["sync"]["funding"]["status"] == "fresh"
    assert len(data["funding"]) == 2
    assert data["funding"][0]["entry_type"] == "funding"
    assert data["sync"]["deposits"]["rows_fetched_total"] == 1
    assert data["sync"]["withdrawals"]["complete"] is True


async def test_missing_capability_marks_stream_unavailable():
    from backend.services.exchange_service import fetch_history

    class Bare:
        id = "mexc"
        def contract_private_get_position_list_history_positions(self, params):
            return {"success": True, "data": {"list": [], "totalPage": 1, "total": 0}}
        def contract_private_get_order_list_history_orders(self, params):
            return {"success": True, "data": {"list": [], "totalPage": 1, "total": 0}}

    data = await fetch_history(Bare(), user_id=9)
    assert data["sync"]["funding"]["status"] == "unavailable"
    assert data["sync"]["funding"]["reason"] == "stream_not_supported"
    assert data["sync"]["futures_transfers"]["status"] == "unavailable"
    assert data["sync"]["deposits"]["status"] == "unavailable"
    assert data["sync"]["withdrawals"]["status"] == "unavailable"
```

- [ ] **Step 2: Run tests — expect FAIL**

```bash
python -m pytest backend/tests/test_phase2b_ledger.py::test_fetch_history_includes_capital_flow_streams_and_coverage backend/tests/test_phase2b_ledger.py::test_missing_capability_marks_stream_unavailable -v
```

- [ ] **Step 3: Implement fetchers and wire `fetch_history` / `fetch_portfolio`**

In `exchange_service.py`, after Phase 2A helpers, add:

```python
def _fetch_funding_history_with_coverage(exchange, user_id, exchange_name):
    from backend.services.phase2b_ledger import coerce_funding_row
    if not (exchange_name == "mexc" and hasattr(exchange, "contract_private_get_position_funding_records")):
        return [], _coverage("funding", rows=[], status="unavailable", complete=False, reason="stream_not_supported")
    rows, paging = _paginate_mexc_history(exchange.contract_private_get_position_funding_records, "funding")
    normalised = [coerce_funding_row(r) for r in rows]
    return normalised, _coverage("funding", rows=normalised, **paging)


def _fetch_futures_transfers_with_coverage(exchange, user_id, exchange_name):
    from backend.services.phase2b_ledger import coerce_futures_transfer_row
    if not (exchange_name == "mexc" and hasattr(exchange, "contract_private_get_account_transfer_record")):
        return [], _coverage("futures_transfers", rows=[], status="unavailable", complete=False, reason="stream_not_supported")
    rows, paging = _paginate_mexc_history(exchange.contract_private_get_account_transfer_record, "futures_transfers")
    normalised = [coerce_futures_transfer_row(r) for r in rows]
    return normalised, _coverage("futures_transfers", rows=normalised, **paging)


def _fetch_deposits_with_coverage(exchange, user_id, exchange_name):
    from backend.services.phase2b_ledger import coerce_deposit_row
    method = getattr(exchange, "fetch_deposits", None) or getattr(exchange, "fetchDeposits", None)
    if not callable(method):
        return [], _coverage("deposits", rows=[], status="unavailable", complete=False, reason="stream_not_supported")
    try:
        raw = method(limit=100) or []
    except Exception as exc:
        return [], _coverage(
            "deposits", rows=[], status="error", complete=False,
            error_code=str(getattr(exc, "code", "exchange_error")),
            error_message=_redact_error(str(exc)),
        )
    normalised = [coerce_deposit_row(r if isinstance(r, dict) else {"amount": r}) for r in raw]
    complete = len(normalised) < 100
    return normalised, _coverage(
        "deposits",
        rows=normalised,
        status="fresh" if complete else "partial",
        complete=complete,
        reason=None if complete else "exchange_boundary_before_source_total",
        source_total=len(normalised) if complete else None,
        page_num=1,
        page_size=100,
        exhausted=complete,
        unrecoverable_gaps=[] if complete else [{"stream": "deposits", "reason": "exchange_boundary_before_source_total"}],
    )


def _fetch_withdrawals_with_coverage(exchange, user_id, exchange_name):
    # mirror deposits with stream name withdrawals / coerce_withdrawal_row
    ...
```

Update `_coverage` time extraction to also consider `occurred_at`:

```python
times = [row.get("close_time") or row.get("timestamp") or row.get("source_ts") or row.get("occurred_at") for row in rows]
```

Wire into `fetch_history`:

```python
position_history, order_history, funding, transfers, deposits, withdrawals = await asyncio.gather(
    asyncio.to_thread(_fetch_positions_history_with_coverage, ...),
    asyncio.to_thread(_fetch_order_history_with_coverage, ...),
    asyncio.to_thread(_fetch_funding_history_with_coverage, ...),
    asyncio.to_thread(_fetch_futures_transfers_with_coverage, ...),
    asyncio.to_thread(_fetch_deposits_with_coverage, ...),
    asyncio.to_thread(_fetch_withdrawals_with_coverage, ...),
)
sync = {
    "positions_history": position_history[1],
    "orders_history": order_history[1],
    "funding": funding[1],
    "futures_transfers": transfers[1],
    "deposits": deposits[1],
    "withdrawals": withdrawals[1],
}
return {
    "position_history": position_history[0],
    "order_history": order_history[0],
    "funding": funding[0],
    "futures_transfers": transfers[0],
    "deposits": deposits[0],
    "withdrawals": withdrawals[0],
    "sync": sync,
    "partial": any(not c.get("complete", False) for c in sync.values()),
}
```

Same four streams in `fetch_portfolio` gather (in addition to existing futures account), merged into `sync` and top-level lists.

- [ ] **Step 4: Run tests — expect PASS**

```bash
python -m pytest backend/tests/test_phase2b_ledger.py -v
python -m pytest backend/tests/test_phase2a_mexc_sync.py -v
```

Fix any Phase 2A mocks that lack new methods: capability guards return `unavailable` when methods missing — existing `MockMexcExchange` without capital methods should still pass if tests only assert Phase 2A keys; if `fetch_history` now always includes capital keys, update assertions that iterate all sync keys carefully.

- [ ] **Step 5: Commit**

```bash
git add backend/services/exchange_service.py backend/tests/test_phase2b_ledger.py
git commit -m "$(cat <<'EOF'
feat(phase2b): fetch capital-flow streams with coverage guards

EOF
)"
```

---

### Task 4: Portfolio API — real coverage defaults + capital-flow endpoint + persist

**Files:**
- Modify: `backend/routes/portfolio.py`
- Create: `backend/tests/test_phase2b_capital_flow_api.py`
- Modify: `backend/tests/test_phase2a_portfolio_api.py` (replace `not_enabled_phase_2b` expectations)

**Interfaces:**
- `_phase2a_default_coverage`: for `funding` / `futures_transfers` / `deposits` / `withdrawals`, return the same generic **no_sync_state / stale** shape as other streams (remove `not_enabled_phase_2b` and `requires_spot_wallet_endpoint_and_retention_probe_phase_2b` special cases).
- `_persist_history_data` / `_persist_portfolio_data`: after `persist_phase2a_sync_payload`, call `persist_capital_flow_payload` with capital keys from `data`.
- New schemas:
  ```python
  class CapitalFlowEntryItem(BaseModel):
      id: int
      entry_type: str
      exchange_entry_id: Optional[str] = None
      asset: str
      amount: Optional[float] = None
      signed_amount: Optional[float] = None
      status: Optional[str] = None
      occurred_at: Optional[datetime] = None
      source_updated_at: Optional[datetime] = None
      synced_at: datetime

  class CapitalFlowResponse(BaseModel):
      exchange: str
      entries: List[CapitalFlowEntryItem]
      sync: List[SyncCoverageItem]
      partial: bool = False
      limit: int = 200
      offset: int = 0
  ```
- Route: `GET /{exchange}/capital-flow?limit=200&offset=0` (same auth + exchange slug validation as other portfolio routes)
- Query: user-scoped, `order_by(occurred_at.desc().nullslast(), id.desc())`, limit/offset clamped (`limit` default 200, max 500)
- Coverage: `_load_sync_coverage` filtered to the four capital streams **or** return full sync list with all streams — **spec: coverage summary**; return the four capital streams (and only those) in `sync` for this endpoint for a focused UI banner.

- [ ] **Step 1: Write failing API tests**

Create `backend/tests/test_phase2b_capital_flow_api.py` using the same app/client fixtures pattern as `test_phase2a_portfolio_api.py` (copy fixture helpers for tmp DB, user, client).

```python
async def test_capital_flow_endpoint_returns_sorted_entries_and_coverage(...):
    # seed two users; only current user rows returned
    # insert CapitalFlowLedger rows with different occurred_at
    # insert ExchangeSyncState for funding=partial, deposits=fresh
    resp = await client.get("/api/v1/portfolio/mexc/capital-flow", headers=auth)
    assert resp.status_code == 200
    body = resp.json()
    assert body["exchange"] == "mexc"
    times = [e["occurred_at"] for e in body["entries"]]
    assert times == sorted(times, reverse=True)
    streams = {s["stream"]: s for s in body["sync"]}
    assert streams["funding"]["status"] == "partial"
    assert "not_enabled_phase_2b" not in {s["status"] for s in body["sync"]}


async def test_capital_flow_is_user_scoped(...):
    # user A cannot see user B ledger rows
    ...


async def test_cached_portfolio_no_longer_emits_phase2b_placeholder(...):
    # after seed without capital sync state, default is stale/no_sync_state not not_enabled_phase_2b
    ...
```

Update `test_phase2a_portfolio_api.py` lines that assert:

```python
assert streams["funding"]["status"] == "not_enabled_phase_2b"
```

to expect either real coverage from payload or `stale` / `no_sync_state` when absent. When refresh mock does not include capital streams, defaults must not be `not_enabled_phase_2b`.

- [ ] **Step 2: Run tests — expect FAIL**

```bash
python -m pytest backend/tests/test_phase2b_capital_flow_api.py backend/tests/test_phase2a_portfolio_api.py -v
```

- [ ] **Step 3: Implement route changes**

1. Fix `_phase2a_default_coverage` — delete the special branches for funding/transfers/deposits/withdrawals; all unknown/missing streams use the generic `stale` / `no_sync_state` dict.
2. Import `CapitalFlowLedger`, `persist_capital_flow_payload`.
3. In `_persist_history_data` and `_persist_portfolio_data`:

```python
await persist_phase2a_sync_payload(session, user_id, exchange, data, now)
await persist_capital_flow_payload(session, user_id, exchange, data, now)
```

4. Add endpoint:

```python
@router.get("/{exchange}/capital-flow", response_model=CapitalFlowResponse)
async def get_capital_flow(
    exchange: str,
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    exchange_slug = _validate_exchange(exchange)  # use existing helper if present
    result = await session.execute(
        select(CapitalFlowLedger)
        .where(
            CapitalFlowLedger.user_id == current_user.id,
            CapitalFlowLedger.exchange == exchange_slug,
        )
        .order_by(CapitalFlowLedger.occurred_at.desc().nullslast(), CapitalFlowLedger.id.desc())
        .offset(offset)
        .limit(limit)
    )
    rows = list(result.scalars().all())
    sync = await _load_sync_coverage(session, current_user.id, exchange_slug)
    capital_streams = {"funding", "futures_transfers", "deposits", "withdrawals"}
    capital_sync = [s for s in sync if s.stream in capital_streams]
    # ensure all four present via defaults
    present = {s.stream for s in capital_sync}
    for stream in ("funding", "futures_transfers", "deposits", "withdrawals"):
        if stream not in present:
            capital_sync.append(SyncCoverageItem(**_phase2a_default_coverage(stream)))
    partial = any(not s.complete for s in capital_sync)
    return CapitalFlowResponse(
        exchange=exchange_slug,
        entries=[CapitalFlowEntryItem(
            id=r.id,
            entry_type=r.entry_type,
            exchange_entry_id=r.exchange_entry_id,
            asset=r.asset,
            amount=r.amount,
            signed_amount=r.signed_amount,
            status=r.status,
            occurred_at=r.occurred_at,
            source_updated_at=r.source_updated_at,
            synced_at=r.synced_at,
        ) for r in rows],
        sync=capital_sync,
        partial=partial,
        limit=limit,
        offset=offset,
    )
```

Use the same exchange validation helper and dependency injection style already in `portfolio.py` (search for `async def get_history` / `get_portfolio` as template).

- [ ] **Step 4: Run tests — expect PASS**

```bash
python -m pytest backend/tests/test_phase2b_capital_flow_api.py backend/tests/test_phase2a_portfolio_api.py -v
```

- [ ] **Step 5: Commit**

```bash
git add backend/routes/portfolio.py backend/tests/test_phase2b_capital_flow_api.py backend/tests/test_phase2a_portfolio_api.py
git commit -m "$(cat <<'EOF'
feat(phase2b): capital-flow API and real stream coverage defaults

EOF
)"
```

---

### Task 5: Frontend types + capital-flow table + dashboard tab

**Files:**
- Modify: `frontend/lib/types.ts`
- Create: `frontend/components/portfolio/capital-flow-table.tsx`
- Create: `frontend/components/portfolio/capital-flow-table.test.tsx`
- Modify: `frontend/components/portfolio/portfolio-dashboard.tsx`

**Interfaces:**
- Types:
  ```ts
  export type CapitalFlowEntryType =
    | "funding"
    | "futures_transfer"
    | "deposit"
    | "withdrawal"
    | string;

  export interface CapitalFlowEntry {
    id: number;
    entry_type: CapitalFlowEntryType;
    exchange_entry_id?: string | null;
    asset: string;
    amount?: number | null;
    signed_amount?: number | null;
    status?: string | null;
    occurred_at?: string | null;
    source_updated_at?: string | null;
    synced_at: string;
  }

  export interface CapitalFlowResponse {
    exchange: string;
    entries: CapitalFlowEntry[];
    sync: SyncCoverageItem[];
    partial: boolean;
    limit: number;
    offset: number;
  }
  ```
- `CapitalFlowTable` props: `{ entries: CapitalFlowEntry[]; sync: SyncCoverageItem[]; partial?: boolean }`
- Columns: date (`occurred_at`), type badge, asset, signed amount (verdigris `+` / rust `−`), status
- Banner when any of four streams has status in `partial|unavailable|error`: copy like “History truncated at exchange boundary” / stream-specific humanized reason — never invent rows
- Dashboard: new tab `capital-flow` that client-fetches `GET /api/v1/portfolio/${exchange}/capital-flow` with bearer token (same pattern as `TradeAttributionTable` / `PositionDesk`)

- [ ] **Step 1: Write failing component test**

```tsx
import { render, screen } from "@testing-library/react";
import { CapitalFlowTable } from "@/components/portfolio/capital-flow-table";
import type { CapitalFlowEntry, SyncCoverageItem } from "@/lib/types";

const entries: CapitalFlowEntry[] = [
  {
    id: 1,
    entry_type: "deposit",
    asset: "USDT",
    amount: 100,
    signed_amount: 100,
    status: "ok",
    occurred_at: "2026-08-01T12:00:00Z",
    synced_at: "2026-08-04T12:00:00Z",
  },
  {
    id: 2,
    entry_type: "funding",
    asset: "USDT",
    amount: 1.25,
    signed_amount: -1.25,
    status: null,
    occurred_at: "2026-08-02T12:00:00Z",
    synced_at: "2026-08-04T12:00:00Z",
  },
];

const partialSync: SyncCoverageItem[] = [
  {
    stream: "funding",
    status: "partial",
    complete: false,
    reason: "exchange_boundary_before_source_total",
    rows_fetched_total: 2,
    source_total: 10,
  },
];

describe("CapitalFlowTable", () => {
  it("renders entries with signed amount formatting and type badges", () => {
    render(<CapitalFlowTable entries={entries} sync={[]} />);
    expect(screen.getByText("Deposit")).toBeInTheDocument();
    expect(screen.getByText("Funding")).toBeInTheDocument();
    expect(screen.getByText("USDT")).toBeInTheDocument();
    expect(screen.getByText(/\+100/)).toBeInTheDocument();
    expect(screen.getByText(/-1\.25/)).toBeInTheDocument();
  });

  it("shows coverage banner when a stream is partial or unavailable", () => {
    render(<CapitalFlowTable entries={entries} sync={partialSync} partial />);
    expect(screen.getByText(/history truncated at exchange boundary/i)).toBeInTheDocument();
  });

  it("uses INK & OXIDE tokens not slate/indigo", () => {
    const { container } = render(<CapitalFlowTable entries={entries} sync={partialSync} />);
    expect(container.innerHTML).toContain("#161411");
    expect(container.innerHTML).toContain("#2A2620");
    expect(container.innerHTML).not.toMatch(/(?:slate|indigo)-/);
  });
});
```

- [ ] **Step 2: Run test — expect FAIL**

```bash
cd frontend && npm test -- --testPathPattern=capital-flow-table --no-cache 2>&1 | tail -40
```

- [ ] **Step 3: Implement types + table + tab**

Add types to `frontend/lib/types.ts`.

Implement `capital-flow-table.tsx` as a client component with table markup styled like `SyncStatusPanel` (INK & OXIDE), not the older slate portfolio tables:

```tsx
"use client";

import type { CapitalFlowEntry, SyncCoverageItem } from "@/lib/types";
import { formatUtcDateTime } from "@/lib/date-format";

const TYPE_LABELS: Record<string, string> = {
  funding: "Funding",
  futures_transfer: "Futures transfer",
  deposit: "Deposit",
  withdrawal: "Withdrawal",
};

export function CapitalFlowTable({
  entries,
  sync,
  partial = false,
}: {
  entries: CapitalFlowEntry[];
  sync: SyncCoverageItem[];
  partial?: boolean;
}) {
  const showBanner =
    partial ||
    sync.some((s) => ["partial", "unavailable", "error"].includes(s.status));

  return (
    <section className="border border-[#2A2620] bg-[#161411]" aria-labelledby="capital-flow-title">
      <div className="border-b border-[#2A2620] p-4">
        <p className="text-[11px] font-semibold uppercase tracking-[0.24em] text-[#C2A36B]">
          Capital flow
        </p>
        <h2 id="capital-flow-title" className="mt-1 text-lg font-semibold text-[#EDE7DB]">
          Ledger entries
        </h2>
        <p className="mt-2 text-sm text-[#8E8778]">
          Read-only funding, transfers, deposits, and withdrawals ingested from the exchange.
        </p>
      </div>
      {showBanner && (
        <div className="border-b border-[#2A2620] px-4 py-3 text-sm text-[#D19A4A]" role="status">
          History truncated at exchange boundary. Miraj only shows proven ledger coverage.
        </div>
      )}
      {/* table: Date | Type | Asset | Signed amount | Status */}
    </section>
  );
}
```

Format signed amounts with `font-mono tabular-nums`; positive `#6CA98F`, negative `#C96A55`.

In `portfolio-dashboard.tsx`:
- Import `CapitalFlowTable`
- Add state/effect to fetch capital-flow when tab selected or on mount after refresh
- Add `TabsTrigger value="capital-flow"` and `TabsContent` rendering the table
- On successful portfolio refresh, re-fetch capital-flow

- [ ] **Step 4: Run frontend tests**

```bash
cd frontend && npm test -- --testPathPattern='capital-flow-table|portfolio-dashboard-phase2a' --no-cache 2>&1 | tail -50
```

Update `portfolio-dashboard-phase2a.test.tsx` mocks to include `CapitalFlowTable` mock if needed.

- [ ] **Step 5: Commit**

```bash
git add frontend/lib/types.ts frontend/components/portfolio/capital-flow-table.tsx frontend/components/portfolio/capital-flow-table.test.tsx frontend/components/portfolio/portfolio-dashboard.tsx
git commit -m "$(cat <<'EOF'
feat(phase2b): capital-flow table and portfolio tab

EOF
)"
```

---

### Task 6: Sync status panel — drop Phase 2B placeholders + SW bump

**Files:**
- Modify: `frontend/components/portfolio/sync-status-panel.tsx`
- Modify: `frontend/components/portfolio/sync-status-panel.test.tsx`
- Modify: `frontend/components/portfolio/portfolio-dashboard-phase2a.test.tsx` (if still asserting Phase 2A capital-flow copy)
- Modify: `frontend/public/sw.js` (`miraj-dashboard-v5` → `miraj-dashboard-v6`)

**Behavior changes:**
- Keep `not_enabled_phase_2b` label/style for backward compatibility if old cached payloads appear, but primary path uses real states.
- `hasCapitalFlowGap`: treat gap when capital streams are `partial|unavailable|error|stale` (not only Phase 2B placeholder).
- Replace right-rail copy:
  - **Remove** “Funding, transfers, deposits, and withdrawals are not ingested in Phase 2A.”
  - **Remove** “Ledger ingestion and retention validation belong to Phase 2B.”
  - **Keep** “Account return unavailable” (Phase 3 still deferred) with accurate copy: account return needs opening equity and complete capital-flow history; Phase 2B does not calculate it.
  - Capital-flow blurb: if any capital stream incomplete → “Capital-flow history is partial or unavailable for one or more streams.” else if all four `fresh` → “Capital-flow streams are synchronized.” (still no return calc).
- `unavailableDetail`: remove special case for `requires_spot_wallet_endpoint_and_retention_probe_phase_2b` or map it to generic unavailable.
- Update tests to use real statuses for the four streams (e.g. funding `fresh`, futures_transfers `partial`, deposits `unavailable`, withdrawals `error`) and assert new copy.

- [ ] **Step 1: Update tests first (red)**

In `sync-status-panel.test.tsx`, change `ALL_STATES` so `futures_transfers` is `partial` (not `not_enabled_phase_2b`), expect “Partial history” not “Phase 2B”, and rewrite capital-flow copy assertions.

- [ ] **Step 2: Run — expect FAIL on old copy**

```bash
cd frontend && npm test -- --testPathPattern=sync-status-panel --no-cache
```

- [ ] **Step 3: Update panel + SW**

Apply copy/logic changes; bump:

```js
const CACHE_NAME = "miraj-dashboard-v6";
```

- [ ] **Step 4: Run full related suite**

```bash
cd frontend && npm test -- --testPathPattern='sync-status-panel|capital-flow|portfolio-dashboard-phase2a' --no-cache
python -m pytest backend/tests/test_phase2b_migration.py backend/tests/test_phase2b_ledger.py backend/tests/test_phase2b_capital_flow_api.py backend/tests/test_phase2a_portfolio_api.py backend/tests/test_phase2a_mexc_sync.py -v
```

- [ ] **Step 5: Commit**

```bash
git add frontend/components/portfolio/sync-status-panel.tsx frontend/components/portfolio/sync-status-panel.test.tsx frontend/components/portfolio/portfolio-dashboard-phase2a.test.tsx frontend/public/sw.js
git commit -m "$(cat <<'EOF'
feat(phase2b): surface real capital-flow coverage in sync panel

EOF
)"
```

---

## Self-Review (plan vs spec)

| Spec requirement | Task |
|---|---|
| `capital_flow_ledger` table + partial unique + chronological indexes | Task 1 |
| Signed-amount conventions | Task 2 |
| Synthetic id for id-less rows | Task 2 |
| `phase2b_ledger.persist_capital_flow_payload` + sync state | Task 2 |
| Four capability-guarded fetchers + `_paginate_mexc_history` where applicable | Task 3 |
| Wire into history/sync path not hot path | Task 3 |
| Real coverage (drop `not_enabled_phase_2b` defaults) | Task 4 |
| `GET /portfolio/{exchange}/capital-flow` sorted + coverage + user scope | Task 4 |
| Capital-flow table + types | Task 5 |
| Sync panel real states | Task 6 |
| Fixture-driven TDD tests listed in spec | Tasks 1–6 |
| SW cache bump | Task 6 |
| No return calc / no retention probe / no writes / no rebates | Global constraints |

**Placeholder scan:** none intentional; MEXC field names for rare alternate keys are listed with fallbacks in coercers.

**Type consistency:** stream keys `funding|futures_transfers|deposits|withdrawals`; DB `entry_type` singular `funding|futures_transfer|deposit|withdrawal`; API `CapitalFlowEntry.entry_type` matches DB; frontend types align.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-08-04-phase-2b-capital-flow-ledger.md`.

**Two execution options:**

1. **Subagent-Driven (recommended)** — dispatch a fresh subagent per task, review between tasks, fast iteration  
2. **Inline Execution** — execute tasks in this session using executing-plans, batch execution with checkpoints  

Which approach?
