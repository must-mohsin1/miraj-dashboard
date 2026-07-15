"""Cross-contract test for backend S/R JSON and the Swift display model."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import textwrap
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.services.desktop_position_service import build_desktop_position_intelligence


def _position() -> dict[str, object]:
    return {
        "symbol": "BTCUSDT",
        "exchange": "mexc",
        "side": "LONG",
        "size": 2.0,
        "contract_size": 1.0,
        "entry_price": 100.0,
        "mark_price": 105.0,
        "pnl": 10.0,
        "margin": 50.0,
        "leverage": 5.0,
        "liquidation_price": 75.0,
    }


def _scan() -> dict[str, object]:
    return {
        "structure": {
            "daily": {
                "label": "HH",
                "swings": [
                    {"type": "low", "price": 101.0, "index": 9},
                    {"type": "high", "price": 111.0, "index": 10},
                ],
            },
            "1h": {
                "label": "HL",
                "swings": [
                    {"type": "low", "price": 103.0, "index": 21},
                    {"type": "high", "price": 107.0, "index": 22},
                ],
            },
        }
    }


def test_backend_service_payload_sr_levels_decode_with_swift_display_model(tmp_path: Path) -> None:
    swiftc = shutil.which("swiftc")
    if swiftc is None:
        pytest.skip("swiftc unavailable; Swift contract decode harness cannot run")

    now = datetime(2026, 7, 15, 10, 30, tzinfo=timezone.utc)
    payload = build_desktop_position_intelligence(
        positions=[_position()],
        exchange="mexc",
        selected_symbol="BTCUSDT",
        scans_by_symbol={"BTCUSDT": _scan()},
        now=now,
        portfolio_last_refreshed=now - timedelta(seconds=30),
        mark_price_last_refreshed=now - timedelta(seconds=30),
    )
    payload_path = tmp_path / "backend_payload.json"
    payload_path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")

    model_path = PROJECT_ROOT / "desktop/MirajPositionMenuBar/Sources/MirajPositionMenuBar/PositionDisplayModel.swift"
    harness_path = tmp_path / "BackendPayloadDecodeHarness.swift"
    binary_path = tmp_path / "BackendPayloadDecodeHarness"
    harness_path.write_text(
        textwrap.dedent(
            """
            import Foundation

            enum HarnessError: Error, CustomStringConvertible {
                case failed(String)

                var description: String {
                    switch self {
                    case .failed(let message): return message
                    }
                }
            }

            func expect(_ condition: @autoclosure () -> Bool, _ message: String) throws {
                if !condition() { throw HarnessError.failed(message) }
            }

            func expectApprox(_ actual: Double, _ expected: Double, _ accuracy: Double, _ message: String) throws {
                if abs(actual - expected) > accuracy {
                    throw HarnessError.failed("\\(message): expected \\(expected), got \\(actual)")
                }
            }

            @main
            struct BackendPayloadDecodeHarness {
                static func main() {
                    do {
                        let path = CommandLine.arguments[1]
                        let data = try Data(contentsOf: URL(fileURLWithPath: path))
                        let response = try PositionDisplayModel.decodeResponse(from: data)
                        let position = try response.position ?? { throw HarnessError.failed("position missing") }()
                        let htfSupport = try position.htfSR.support ?? { throw HarnessError.failed("HTF support missing") }()
                        let htfResistance = try position.htfSR.resistance ?? { throw HarnessError.failed("HTF resistance missing") }()
                        let ltfSupport = try position.ltfSR.support ?? { throw HarnessError.failed("LTF support missing") }()
                        try expect(response.schemaVersion == 1, "schema_version must be 1")
                        try expect(htfSupport.method == "smc_swing", "HTF support method")
                        try expect(htfSupport.timeframe == "Daily", "HTF support timeframe")
                        try expect(htfSupport.swingType == "swing_low", "HTF support swing type")
                        try expect(htfSupport.swingIndex == 9, "HTF support swing index")
                        try expectApprox(htfSupport.distancePct, -3.8095238, 0.0001, "HTF support distance_pct")
                        try expectApprox(htfResistance.distancePct, 5.7142857, 0.0001, "HTF resistance distance_pct")
                        try expect(ltfSupport.method == "smc_swing", "LTF support method")
                        print("Backend payload decoded with Swift PositionDisplayModel")
                    } catch {
                        fputs("BackendPayloadDecodeHarness failed: \\(error)\\n", stderr)
                        exit(3)
                    }
                }
            }
            """
        ),
        encoding="utf-8",
    )

    compile_result = subprocess.run(
        [swiftc, "-parse-as-library", str(model_path), str(harness_path), "-o", str(binary_path)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert compile_result.returncode == 0, compile_result.stderr

    decode_result = subprocess.run(
        [str(binary_path), str(payload_path)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert decode_result.returncode == 0, decode_result.stderr + decode_result.stdout
