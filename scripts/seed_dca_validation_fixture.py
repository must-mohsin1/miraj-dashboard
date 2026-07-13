#!/usr/bin/env python3
"""Seed deterministic DCA validation QA data into a local Miraj SQLite DB.

The fixture is intentionally local and offline: it reads the expected-values JSON
contract, writes only application database rows, and never imports exchange
clients or requires exchange API keys.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import bcrypt
from sqlalchemy import delete, select

# Ensure the repo root is importable when the script is executed directly.
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from backend.database import Base, get_engine, get_session_factory, set_db_path  # noqa: E402
from backend.models import (  # noqa: E402
    Analysis,
    PortfolioPosition,
    PortfolioTrade,
    PositionHistory,
    User,
)

DEFAULT_EXPECTED_PATH = REPO_ROOT / "backend" / "tests" / "fixtures" / "dca_validation_expected.json"
FIXTURE_SOURCE = "dca_validation_fixture_seed"
DEFAULT_USERNAME = "qa_dca_validation"
DEFAULT_EMAIL = "qa-dca-validation@example.test"
DEFAULT_PASSWORD = "qa-dca-validation-password"


def parse_utc(value: str) -> datetime:
    """Parse the fixture's ISO timestamps into naive UTC datetimes for SQLite."""
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.astimezone(timezone.utc).replace(tzinfo=None)


def hash_password(password: str) -> str:
    """Return a bcrypt hash without importing backend.auth (which needs JWT_SECRET_KEY)."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def load_expected(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(
            f"Expected-values fixture not found at {path}. "
            "Generate or copy backend/tests/fixtures/dca_validation_expected.json first."
        )
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if data.get("schema_version") != 1:
        raise ValueError(f"Unsupported DCA expected fixture schema_version={data.get('schema_version')!r}")
    if not isinstance(data.get("fixtures"), list) or not isinstance(data.get("edge_cases"), list):
        raise ValueError("Expected fixture must contain fixtures[] and edge_cases[] arrays")
    return data


def symbol_to_pair(symbol: str) -> str:
    """Normalize exchange symbols to the app's scan pair format where useful."""
    base = symbol.upper().split(":", 1)[0].replace("/", "-")
    if base.endswith("-USDT"):
        base = base[:-5] + "-USD"
    return base


def scan_result(
    *,
    source: dict[str, Any],
    fixture_id: str,
    symbol: str,
    direction: str,
    assumptions: dict[str, Any],
    position_budget: float | None,
    shadow_decision: dict[str, Any] | None,
    expected_metrics: dict[str, Any] | None = None,
    edge_expected: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build an Analysis.result JSON shape that validation code and QA can inspect."""
    mark_price = source.get("mark_price")
    rsi = ((source.get("indicators") or {}).get("daily") or {}).get("rsi")
    direction = direction.upper()
    is_long = direction == "LONG"
    entry_zone = None
    if isinstance(mark_price, (int, float)):
        entry_zone = {
            "low": round(float(mark_price) * (0.98 if is_long else 0.99), 6),
            "high": round(float(mark_price) * (1.01 if is_long else 1.02), 6),
        }

    result: dict[str, Any] = {
        "symbol": symbol_to_pair(symbol),
        "fixture_symbol": symbol,
        "fixture_id": fixture_id,
        "fixture_source": FIXTURE_SOURCE,
        "scan_id": source.get("scan_id"),
        "timestamp": source.get("timestamp"),
        "current_price": mark_price,
        "mark_price": mark_price,
        "overall_score": 12 if shadow_decision and shadow_decision.get("final_outcome") == "would_allow" else 8,
        "confluence_score": 12 if shadow_decision and shadow_decision.get("final_outcome") == "would_allow" else 8,
        "indicators": source.get("indicators") or {},
        "trade_plan": {
            "direction": direction,
            "entry_zone": entry_zone,
            "reasoning": f"Deterministic DCA validation fixture {fixture_id} scan {source.get('scan_id')}",
            "take_profit_targets": [
                {"level": round(float(mark_price) * (1.1 if is_long else 0.9), 6)}
            ] if isinstance(mark_price, (int, float)) else [],
        },
        "dca_validation": {
            "method": "scan-to-scan",
            "assumptions": assumptions,
            "position_context": {
                "symbol": symbol,
                "direction": direction,
                "position_budget": position_budget,
            },
            "expected_event": source.get("expected_event"),
            "expected_metrics": expected_metrics,
            "edge_expected": edge_expected,
        },
        "dca_safe": {
            "passes": bool(shadow_decision and shadow_decision.get("final_outcome") == "would_allow"),
            "checks": shadow_decision.get("gates") if shadow_decision else [],
        },
        "shadow_history": [shadow_decision] if shadow_decision else [],
    }
    if rsi is not None:
        result["rsi"] = rsi
    return result


def shadow_decisions_for_fixture(fixture: dict[str, Any]) -> list[dict[str, Any]]:
    """Create deterministic no-live-order shadow examples for each fixture scan."""
    symbol = fixture["symbol"]
    decisions: list[dict[str, Any]] = []
    for index, scan in enumerate(fixture["scan_history"]):
        event = scan.get("expected_event")
        allow = event in {"entry_1", "entry_3"}
        reduce_or_close = event in {"validation_exit", "latest_open_valuation"}
        if allow:
            outcome = "would_allow"
            final_reason = "All deterministic QA ADD gates passed; no live order was placed."
            gates = [
                {"name": "dca_safe_checklist", "passed": True, "reason": "fixture marks DCA SAFE"},
                {"name": "confluence_score_at_least_10", "passed": True, "reason": "score=12"},
                {"name": "user_kill_switch_inactive", "passed": True, "reason": "fixture user kill switch off"},
                {"name": "symbol_kill_switch_inactive", "passed": True, "reason": "fixture symbol kill switch off"},
                {"name": "hourly_add_limit", "passed": True, "reason": "fixture count below 3/hour"},
                {"name": "daily_add_limit", "passed": True, "reason": "fixture count below 10/day"},
                {"name": "cooldown_after_close", "passed": True, "reason": "no 24h close cooldown"},
                {"name": "add_size_cap", "passed": True, "reason": "simulated ADD <= 10% portfolio value"},
                {"name": "exposure_cap", "passed": True, "reason": "simulated exposure below cap"},
            ]
        elif reduce_or_close:
            outcome = "would_close" if event == "validation_exit" else "no_action"
            final_reason = "Risk/valuation outcome is shown only as a shadow decision; no live order was placed."
            gates = [{"name": "live_order_path", "passed": True, "reason": "fixture is offline/read-only"}]
        else:
            outcome = "would_block"
            final_reason = "ADD blocked by deterministic QA gates; no live order was placed."
            gates = [
                {"name": "dca_safe_checklist", "passed": event != "no_fill", "reason": "no qualifying DCA event" if event == "no_fill" else "fixture DCA SAFE"},
                {"name": "confluence_score_at_least_10", "passed": False, "reason": "score=8 for blocked fixture scan"},
                {"name": "live_order_path", "passed": True, "reason": "fixture is offline/read-only"},
            ]
        decisions.append(
            {
                "timestamp": scan.get("timestamp"),
                "symbol": symbol,
                "original_recommendation": "ADD" if event and "entry" in event else "HOLD",
                "final_outcome": outcome,
                "blocked_gates": [gate["name"] for gate in gates if not gate["passed"]],
                "gates": gates,
                "final_reason": final_reason,
                "assumption_set": "dca_validation_expected.schema_v1.defaults",
                "live_order_placed": False,
                "sequence": index,
            }
        )
    return decisions


async def reset_fixture_user(session_factory, username: str) -> int:
    async with session_factory() as session:
        user = (await session.execute(select(User).where(User.username == username))).scalar_one_or_none()
        if user is None:
            return 0
        user_id = user.id
        for model in (Analysis, PortfolioTrade, PortfolioPosition, PositionHistory):
            await session.execute(delete(model).where(model.user_id == user_id))
        await session.delete(user)
        await session.commit()
        return user_id


async def seed_fixture(args: argparse.Namespace) -> dict[str, Any]:
    expected = load_expected(Path(args.expected).resolve())

    if args.dry_run:
        return {
            "dry_run": True,
            "db": args.db,
            "expected": str(Path(args.expected).resolve()),
            "fixtures": len(expected["fixtures"]),
            "edge_cases": len(expected["edge_cases"]),
        }

    set_db_path(args.db)
    engine = get_engine()

    if args.init_schema:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    session_factory = get_session_factory()

    removed_user_id = None
    if args.reset or args.reset_only:
        removed_user_id = await reset_fixture_user(session_factory, args.username)
        if args.reset_only:
            return {"reset_user_id": removed_user_id, "seeded": False}

    async with session_factory() as session:
        existing = (await session.execute(select(User).where(User.username == args.username))).scalar_one_or_none()
        if existing is not None:
            raise RuntimeError(
                f"User {args.username!r} already exists. Re-run with --reset (default) or choose --username."
            )

        user = User(
            username=args.username,
            email=args.email,
            hashed_password=hash_password(args.password),
        )
        session.add(user)
        await session.flush()

        analysis_count = 0
        position_count = 0
        position_history_count = 0
        trade_count = 0
        shadow_count = 0

        for fixture in expected["fixtures"]:
            symbol = fixture["symbol"]
            direction = fixture["direction"].upper()
            side = direction.lower()
            metrics = fixture.get("expected_metrics") or {}
            shadows = shadow_decisions_for_fixture(fixture)
            shadow_count += len(shadows)

            scan_by_id = {
                scan.get("scan_id"): scan
                for scan in fixture.get("scan_history", [])
                if isinstance(scan, dict)
            }

            if fixture.get("expected_status") == "open":
                latest_scan = fixture["scan_history"][-1]
                session.add(
                    PortfolioPosition(
                        user_id=user.id,
                        exchange=args.exchange,
                        symbol=symbol,
                        side=side,
                        size=float(metrics.get("total_quantity") or 0),
                        entry_price=float(metrics.get("average_executed_entry") or metrics.get("average_mark_entry") or 0),
                        mark_price=float(latest_scan.get("mark_price") or 0),
                        pnl=float(metrics.get("net_open_pnl") or metrics.get("net_pnl") or 0),
                        pnl_percent=round((float(metrics.get("net_open_pnl") or 0) / float(fixture.get("position_budget") or 1)) * 100, 6),
                        leverage=1.0,
                        liquidation_price=None,
                        margin=float(fixture.get("position_budget") or 0),
                        contract_size=1.0,
                        updated_at=parse_utc(latest_scan["timestamp"]),
                    )
                )
                position_count += 1
            else:
                first_scan = fixture["scan_history"][0]
                fallback_exit_scan = fixture["scan_history"][-1]
                expected_exit = fixture.get("expected_exit") or {}
                exit_scan = scan_by_id.get(expected_exit.get("scan_id")) or fallback_exit_scan
                session.add(
                    PositionHistory(
                        user_id=user.id,
                        exchange=args.exchange,
                        symbol=symbol,
                        side=side,
                        size=float(metrics.get("total_quantity") or 0),
                        entry_price=float(metrics.get("average_executed_entry") or metrics.get("average_mark_entry") or 0),
                        exit_price=float(expected_exit.get("fill_price") or exit_scan.get("mark_price") or 0),
                        pnl=float(metrics.get("net_pnl") or 0),
                        pnl_percent=round((float(metrics.get("net_pnl") or 0) / float(fixture.get("position_budget") or 1)) * 100, 6),
                        leverage=1.0,
                        open_time=parse_utc(first_scan["timestamp"]),
                        close_time=parse_utc(exit_scan["timestamp"]),
                        close_reason="validation_fixture",
                        contract_size=1.0,
                        updated_at=parse_utc(exit_scan["timestamp"]),
                    )
                )
                position_history_count += 1

            for fill in fixture.get("expected_fills", []):
                scan = scan_by_id.get(fill.get("scan_id"), {})
                is_entry_short = direction == "SHORT"
                session.add(
                    PortfolioTrade(
                        user_id=user.id,
                        exchange=args.exchange,
                        symbol=symbol,
                        side="sell" if is_entry_short else "buy",
                        type="validation_fixture",
                        price=float(fill["fill_price"]),
                        amount=float(fill["quantity"]),
                        cost=float(fill["allocation_notional"]),
                        fee=float(fill["fee_amount"]),
                        fee_currency="USDT",
                        timestamp=parse_utc(scan.get("timestamp", fixture["scan_history"][0]["timestamp"])),
                        exchange_trade_id=f"dca-fixture-{fixture['id']}-{fill['entry_level']}",
                    )
                )
                trade_count += 1

            for scan, shadow in zip(fixture["scan_history"], shadows):
                result = scan_result(
                    source=scan,
                    fixture_id=fixture["id"],
                    symbol=symbol,
                    direction=direction,
                    assumptions=expected["assumptions"],
                    position_budget=fixture.get("position_budget"),
                    shadow_decision=shadow,
                    expected_metrics=metrics,
                )
                session.add(
                    Analysis(
                        user_id=user.id,
                        pair=symbol,
                        analysis_type="dca_validation_fixture_scan",
                        parameters=json.dumps({"fixture_id": fixture["id"], "scan_id": scan.get("scan_id")}),
                        result=json.dumps(result, sort_keys=True),
                        score=float(result.get("overall_score") or 0),
                        created_at=parse_utc(scan["timestamp"]),
                    )
                )
                analysis_count += 1

        for edge in expected["edge_cases"]:
            symbol = edge.get("symbol") or f"EDGE-{edge['id']}"
            direction = (edge.get("direction") or "LONG").upper()
            for index, scan in enumerate(edge.get("scan_history", [])):
                if not isinstance(scan, dict):
                    scan = {
                        "scan_id": f"{edge['id']}-malformed-{index}",
                        "timestamp": edge["scan_history"][0].get("timestamp", "2026-03-01T00:00:00Z"),
                        "malformed_payload": scan,
                    }
                result = scan_result(
                    source=scan,
                    fixture_id=edge["id"],
                    symbol=symbol,
                    direction=direction,
                    assumptions=expected["assumptions"],
                    position_budget=(edge.get("position_context") or {}).get("position_budget") if isinstance(edge.get("position_context"), dict) else None,
                    shadow_decision={
                        "timestamp": scan.get("timestamp"),
                        "symbol": symbol,
                        "original_recommendation": "HOLD",
                        "final_outcome": "would_block",
                        "blocked_gates": [edge["expected"]["skip_reason"]],
                        "gates": [{"name": edge["expected"]["skip_reason"], "passed": False, "reason": "deterministic edge-case skip"}],
                        "final_reason": f"Skipped for QA edge case: {edge['expected']['skip_reason']}",
                        "assumption_set": "dca_validation_expected.schema_v1.defaults",
                        "live_order_placed": False,
                        "sequence": index,
                    },
                    edge_expected=edge.get("expected"),
                )
                session.add(
                    Analysis(
                        user_id=user.id,
                        pair=symbol[:20],
                        analysis_type="dca_validation_fixture_edge_case",
                        parameters=json.dumps({"edge_case_id": edge["id"], "scan_id": scan.get("scan_id")}),
                        result=json.dumps(result, sort_keys=True),
                        score=float(result.get("overall_score") or 0),
                        created_at=parse_utc(scan.get("timestamp", "2026-03-01T00:00:00Z")),
                    )
                )
                analysis_count += 1
                shadow_count += 1

        await session.commit()

        return {
            "seeded": True,
            "reset_user_id": removed_user_id,
            "db": args.db,
            "expected": str(Path(args.expected).resolve()),
            "user_id": user.id,
            "username": args.username,
            "email": args.email,
            "password": args.password,
            "exchange": args.exchange,
            "analyses": analysis_count,
            "open_positions": position_count,
            "position_history": position_history_count,
            "portfolio_trades": trade_count,
            "shadow_decisions": shadow_count,
            "fixtures": [fixture["id"] for fixture in expected["fixtures"]],
            "edge_cases": [edge["id"] for edge in expected["edge_cases"]],
        }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Seed deterministic DCA validation QA fixture data.")
    parser.add_argument("--db", default=os.environ.get("DATABASE_URL", "crypto_analysis.db"), help="SQLite DB path. Defaults to DATABASE_URL or ./crypto_analysis.db")
    parser.add_argument("--expected", default=str(DEFAULT_EXPECTED_PATH), help="Path to backend/tests/fixtures/dca_validation_expected.json")
    parser.add_argument("--exchange", default="binance", help="Exchange slug to attach to seeded portfolio rows")
    parser.add_argument("--username", default=DEFAULT_USERNAME, help="Seeded QA username")
    parser.add_argument("--email", default=DEFAULT_EMAIL, help="Seeded QA email")
    parser.add_argument("--password", default=DEFAULT_PASSWORD, help="Seeded QA password (local test DB only)")
    parser.add_argument("--reset", action=argparse.BooleanOptionalAction, default=True, help="Delete the existing fixture user before seeding (default: true)")
    parser.add_argument("--reset-only", action="store_true", help="Delete the fixture user and exit without reseeding")
    parser.add_argument("--init-schema", action="store_true", help="Create missing tables before seeding, useful for a scratch QA DB")
    parser.add_argument("--dry-run", action="store_true", help="Validate the expected fixture file and print what would be seeded")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    try:
        summary = asyncio.run(seed_fixture(args))
    except Exception as exc:  # pragma: no cover - CLI surface
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
