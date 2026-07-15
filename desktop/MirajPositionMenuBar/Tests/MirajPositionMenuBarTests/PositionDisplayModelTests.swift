import Foundation

#if canImport(MirajPositionMenuBar)
@testable import MirajPositionMenuBar
#endif

enum TestFailure: Error, CustomStringConvertible {
    case failed(String)

    var description: String {
        switch self {
        case .failed(let message): return message
        }
    }
}

func expect(_ condition: @autoclosure () -> Bool, _ message: String) throws {
    if !condition() { throw TestFailure.failed(message) }
}

func expectEqual<T: Equatable>(_ actual: T, _ expected: T, _ message: String) throws {
    if actual != expected { throw TestFailure.failed("\(message): expected \(expected), got \(actual)") }
}

func expectNil(_ value: Any?, _ message: String) throws {
    if value != nil { throw TestFailure.failed(message) }
}

func expectApprox(_ actual: Double, _ expected: Double, accuracy: Double, _ message: String) throws {
    if abs(actual - expected) > accuracy { throw TestFailure.failed("\(message): expected \(expected), got \(actual)") }
}

func unwrap<T>(_ value: T?, _ message: String) throws -> T {
    guard let value else { throw TestFailure.failed(message) }
    return value
}

struct PositionDisplayModelTestSuite {
    private var fixturesDirectory: URL {
        URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .appendingPathComponent("MockFixtures")
    }

    private func loadFixture(_ name: String) throws -> PositionIntelligenceResponse {
        let url = fixturesDirectory.appendingPathComponent(name)
        let data = try Data(contentsOf: url)
        return try PositionDisplayModel.decodeResponse(from: data)
    }

    private func assertNoForbiddenCTA(_ strings: [String]) throws {
        let forbidden = ["Buy", "Sell", "Add now", "Execute", "Close now", "Reduce now", "Place order", "Submit order", "Market buy", "Market sell", "Add position", "Reduce position", "Close position", "One-click", "Trade now"]
        let joined = strings.joined(separator: "\n")
        for term in forbidden {
            try expect(!joined.localizedCaseInsensitiveContains(term), "Forbidden CTA \(term) leaked in display strings: \(joined)")
        }
    }

    func runAll() throws {
        try testAllDeterministicFixturesDecodeAsSchemaVersionOne()
        try testUnsupportedSchemaVersionIsRejected()
        try testFreshLongMapsContractAndPositivePnLDisplay()
        try testHideAmountsMasksPrivateAmountsButPreservesAllowedFields()
        try testRedactedMenuBarDoesNotExposePositionData()
        try testStaleShortContractSizeMapsStaleCopyAndPositivePnL()
        try testNoOpenPositionsAndNotConnectedDoNotExposePrivatePositionData()
        try testOfflineWithCacheUsesConservativeCopyAndNegativePnL()
        try testCriticalStaleMasksOriginalAdvisoryReasonAndZeroPnLIsNeutral()
        try testOfflineWithoutCacheStaticDisplayContainsNoPrivateData()
        try testForbiddenCTATextAbsentFromFixtureFilesAndDisplayStrings()
    }

    func testAllDeterministicFixturesDecodeAsSchemaVersionOne() throws {
        let fixtureNames = [
            "position_fresh_long.json",
            "position_stale_short_contract_size.json",
            "no_open_positions.json",
            "not_connected.json",
            "offline_with_cache.json",
            "critical_stale.json"
        ]

        for fixtureName in fixtureNames {
            let response = try loadFixture(fixtureName)
            try expectEqual(response.schemaVersion, 1, "schema version for \(fixtureName)")
            try expectEqual(response.exchange, "mexc", "exchange for \(fixtureName)")
            try expect(response.privacy.hideAmountsAvailable, "hide amounts available for \(fixtureName)")
            try expect(response.privacy.redactionSupported, "redaction supported for \(fixtureName)")
            try expect(!String(describing: response).localizedCaseInsensitiveContains("jwt"), "JWT must not appear in \(fixtureName)")
            try expect(!String(describing: response).localizedCaseInsensitiveContains("mexc_secret"), "MEXC secret must not appear in \(fixtureName)")
        }
    }

    func testUnsupportedSchemaVersionIsRejected() throws {
        let json = """
        {
          "schema_version": 2,
          "exchange": "mexc",
          "selection_reason": "no_open_positions",
          "generated_at": "2026-07-15T10:00:00Z",
          "source": {
            "portfolio_last_refreshed": null,
            "mark_price_source": "unavailable",
            "mark_price_last_refreshed": null,
            "pnl_age_seconds": null,
            "stale_status": "fresh"
          },
          "position": null,
          "privacy": { "hide_amounts_available": true, "redaction_supported": true },
          "errors": []
        }
        """

        do {
            _ = try PositionDisplayModel.decodeResponse(from: Data(json.utf8))
            throw TestFailure.failed("schema_version 2 unexpectedly decoded")
        } catch let error as PositionContractError {
            try expectEqual(error, .unsupportedSchemaVersion(2), "unsupported schema error")
        }
    }

    func testFreshLongMapsContractAndPositivePnLDisplay() throws {
        let response = try loadFixture("position_fresh_long.json")
        let position = try unwrap(response.position, "fresh long position missing")
        try expectEqual(position.side, .long, "fresh side")
        try expectEqual(position.contractSize, 0.5, "fresh contract size")
        try expectApprox(position.pnl, 15, accuracy: 0.0001, "fresh pnl")
        try expectEqual(position.pnlFormula, .computedContractsContractSize, "fresh pnl formula")
        try expectEqual(position.htfSR.support?.method, "smc_swing", "HTF support provenance")
        try expectEqual(position.ltfSR.resistance?.method, "smc_swing", "LTF resistance provenance")

        let model = PositionDisplayModel(response: response)
        try expectEqual(model.state, .fresh, "fresh display state")
        try expectEqual(model.menuBarLabel, "Miraj +7.50%", "fresh menu label")
        try expectEqual(model.badge, "Fresh", "fresh badge")
        try expectEqual(model.pnlSemanticState, .positiveGreen, "fresh pnl semantic")
        try expect(model.rows.contains("PnL +$15 (+7.50%)"), "fresh pnl row")
        try expectEqual(model.timestampLine, "Updated 30 seconds ago", "fresh timestamp")
        try assertNoForbiddenCTA(model.allDisplayStrings)
    }

    func testHideAmountsMasksPrivateAmountsButPreservesAllowedFields() throws {
        let response = try loadFixture("position_fresh_long.json")
        let model = PositionDisplayModel(response: response, options: PositionDisplayOptions(hideAmounts: true))

        try expectEqual(model.title, "BTCUSDT", "masked title")
        try expectEqual(model.subtitle, "mexc · LONG", "masked subtitle")
        try expectEqual(model.menuBarLabel, "Miraj +7.50%", "masked menu label")
        try expect(model.rows.contains("Size ••• contracts · 10x"), "masked size row")
        try expect(model.rows.contains("Entry ••• · Mark •••"), "masked entry row")
        try expect(model.rows.contains("PnL ••• (+7.50%)"), "masked pnl row")
        try expect(model.rows.contains("Liq distance •••"), "masked risk row")
        try expect(model.rows.contains("HTF: support/resistance hidden"), "masked HTF row")
        try expect(model.rows.contains("LTF: support/resistance hidden"), "masked LTF row")
        try expectEqual(model.advisoryLine, "Advisory: HOLD", "masked advisory enum only")
        try assertNoForbiddenCTA(model.allDisplayStrings)
    }

    func testRedactedMenuBarDoesNotExposePositionData() throws {
        let response = try loadFixture("position_fresh_long.json")
        let model = PositionDisplayModel(response: response, options: PositionDisplayOptions(redactMenuBar: true))

        try expectEqual(model.menuBarLabel, "Miraj", "redacted menu label")
        try expect(!model.menuBarLabel.contains("BTC"), "redacted menu leaked symbol")
        try expect(!model.menuBarLabel.contains("+7.50%"), "redacted menu leaked pnl percent")
        try expect(!model.menuBarLabel.contains("LONG"), "redacted menu leaked side")
    }

    func testStaleShortContractSizeMapsStaleCopyAndPositivePnL() throws {
        let response = try loadFixture("position_stale_short_contract_size.json")
        let position = try unwrap(response.position, "stale short position missing")
        try expectEqual(position.side, .short, "stale side")
        try expectEqual(position.contractSize, 0.5, "stale contract size")
        try expectApprox(position.pnl, 15, accuracy: 0.0001, "stale pnl")
        try expectApprox(position.pnlPercent, 15, accuracy: 0.0001, "stale pnl percent")

        let model = PositionDisplayModel(response: response)
        try expectEqual(model.state, .stale, "stale display state")
        try expectEqual(model.menuBarLabel, "Miraj · Stale", "stale menu label")
        try expectEqual(model.badge, "Stale", "stale badge")
        try expectEqual(model.warningLine, "Data may be out of date. Open Miraj before acting.", "stale warning")
        try expectEqual(model.timestampLine, "Stale: 6 minutes ago", "stale timestamp")
        try expectEqual(model.pnlSemanticState, .positiveGreen, "stale pnl semantic")
        try assertNoForbiddenCTA(model.allDisplayStrings)
    }

    func testNoOpenPositionsAndNotConnectedDoNotExposePrivatePositionData() throws {
        let noOpen = PositionDisplayModel(response: try loadFixture("no_open_positions.json"))
        try expectEqual(noOpen.state, .noOpenPositions, "no-open state")
        try expectEqual(noOpen.body, "No open positions", "no-open body")
        try expectEqual(noOpen.footerActions, ["Open Miraj", "Refresh"], "no-open actions")
        try expect(noOpen.rows.isEmpty, "no-open rows empty")
        try expectNil(noOpen.advisoryLine, "no-open advisory hidden")

        let notConnected = PositionDisplayModel(response: try loadFixture("not_connected.json"))
        try expectEqual(notConnected.state, .notConnected, "not-connected state")
        try expectEqual(notConnected.body, "Connect to Miraj to view your position.", "not-connected body")
        try expectEqual(notConnected.footerActions, ["Connect"], "not-connected actions")
        try expect(notConnected.rows.isEmpty, "not-connected rows empty")
        try expectNil(notConnected.advisoryLine, "not-connected advisory hidden")
        try assertNoForbiddenCTA(noOpen.allDisplayStrings + notConnected.allDisplayStrings)
    }

    func testOfflineWithCacheUsesConservativeCopyAndNegativePnL() throws {
        let response = try loadFixture("offline_with_cache.json")
        let model = PositionDisplayModel(response: response)

        try expectEqual(model.state, .offlineWithCache, "offline state")
        try expectEqual(model.menuBarLabel, "Miraj · Offline", "offline menu label")
        try expectEqual(model.badge, "Offline", "offline badge")
        try expectEqual(model.warningLine, "Offline — showing last known position.", "offline warning")
        try expectEqual(model.timestampLine, "Offline — last known 12 minutes ago", "offline timestamp")
        try expectEqual(model.advisoryLine, "Advisory: WAIT — Reconnect before changing the position", "offline advisory")
        try expectEqual(model.pnlSemanticState, .negativeRed, "offline pnl semantic")
        try expect(model.rows.contains("HTF: insufficient swings"), "offline HTF unavailable")
        try assertNoForbiddenCTA(model.allDisplayStrings)
    }

    func testCriticalStaleMasksOriginalAdvisoryReasonAndZeroPnLIsNeutral() throws {
        let response = try loadFixture("critical_stale.json")
        let originalReason = try unwrap(response.position?.advisory.reason, "critical stale original reason missing")
        let model = PositionDisplayModel(response: response)

        try expectEqual(model.state, .criticalStale, "critical stale state")
        try expectEqual(model.menuBarLabel, "Miraj · Stale", "critical stale menu label")
        try expectEqual(model.badge, "Stale", "critical stale badge")
        try expectEqual(model.warningLine, "Open Miraj to refresh before acting", "critical stale warning")
        try expectEqual(model.advisoryLine, "Advisory: WAIT — Open Miraj to refresh before acting", "critical stale advisory")
        try expect(!model.allDisplayStrings.joined(separator: "\n").contains(originalReason), "critical stale leaked original reason")
        try expectEqual(model.timestampLine, "Stale: 20 minutes ago", "critical stale timestamp")
        try expectEqual(model.pnlSemanticState, .neutral, "critical stale pnl semantic")
        try assertNoForbiddenCTA(model.allDisplayStrings)
    }

    func testOfflineWithoutCacheStaticDisplayContainsNoPrivateData() throws {
        let model = PositionDisplayModel.offlineWithoutCache()
        try expectEqual(model.state, .offlineWithoutCache, "offline no-cache state")
        try expectEqual(model.body, "Unable to load position", "offline no-cache body")
        try expectEqual(model.detail, "Check your connection, then refresh.", "offline no-cache detail")
        try expectEqual(model.footerActions, ["Refresh"], "offline no-cache actions")
        try expect(model.rows.isEmpty, "offline no-cache rows empty")
        try expectNil(model.advisoryLine, "offline no-cache advisory hidden")
        try assertNoForbiddenCTA(model.allDisplayStrings)
    }

    func testForbiddenCTATextAbsentFromFixtureFilesAndDisplayStrings() throws {
        let fixtureNames = [
            "position_fresh_long.json",
            "position_stale_short_contract_size.json",
            "no_open_positions.json",
            "not_connected.json",
            "offline_with_cache.json",
            "critical_stale.json"
        ]

        for fixtureName in fixtureNames {
            let fixtureText = try String(contentsOf: fixturesDirectory.appendingPathComponent(fixtureName), encoding: .utf8)
            try assertNoForbiddenCTA([fixtureText])
            let model = PositionDisplayModel(response: try loadFixture(fixtureName), options: PositionDisplayOptions(hideAmounts: true, redactMenuBar: true))
            try assertNoForbiddenCTA(model.allDisplayStrings)
        }
    }
}

@main
struct PositionDisplayModelTestRunner {
    static func main() {
        do {
            try PositionDisplayModelTestSuite().runAll()
            print("PositionDisplayModelTests: 11 tests passed")
        } catch {
            fputs("PositionDisplayModelTests failed: \(error)\n", stderr)
            exit(1)
        }
    }
}
