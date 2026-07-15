import Foundation
import SwiftUI

#if canImport(MirajPositionMenuBar)
@testable import MirajPositionMenuBar
#endif

enum PositionPopoverViewTestFailure: Error, CustomStringConvertible {
    case failed(String)

    var description: String {
        switch self {
        case .failed(let message): return message
        }
    }
}

func popoverExpect(_ condition: @autoclosure () -> Bool, _ message: String) throws {
    if !condition() { throw PositionPopoverViewTestFailure.failed(message) }
}

func popoverExpectEqual<T: Equatable>(_ actual: T, _ expected: T, _ message: String) throws {
    if actual != expected { throw PositionPopoverViewTestFailure.failed("\(message): expected \(expected), got \(actual)") }
}

struct PositionPopoverViewTestSuite {
    private let now = ISO8601DateFormatter().date(from: "2026-07-15T10:00:00Z")!

    func runAll() throws {
        try testPopoverRendersAllRequiredStatesFromDisplayModels()
        try testHideAmountsSnapshotMasksPrivateNumbers()
        try testFullPopoverRedactionHidesPrivateRows()
        try testFooterActionsAreLimitedAndRefreshShowsInFlightCopy()
        try testForbiddenTradingCopyNeverAppearsInSnapshots()
    }

    func testPopoverRendersAllRequiredStatesFromDisplayModels() throws {
        let cases: [(PositionDisplayModel, String, String?)] = [
            (.notConnected(), "Not connected", "Connect to Miraj to view your position."),
            (PositionDisplayModel(response: try response(position: nil, staleStatus: .fresh, pnlAgeSeconds: nil, selectionReason: .noOpenPositions)), "Fresh", "No open positions"),
            (PositionDisplayModel(response: try response(position: position(symbol: "BTCUSDT"), staleStatus: .fresh, pnlAgeSeconds: 30)), "Fresh", nil),
            (PositionDisplayModel(response: try response(position: position(symbol: "ETHUSDT", side: .short, pnl: 15, pnlPercent: 15), staleStatus: .stale, pnlAgeSeconds: 360)), "Stale", nil),
            (PositionDisplayModel(response: try response(position: position(symbol: "SOLUSDT", advisory: Self.advisory(.close, reason: "Risk is elevated.")), staleStatus: .criticalStale, pnlAgeSeconds: 1_200)), "Stale", nil),
            (PositionDisplayModel(response: try response(position: position(symbol: "XRPUSDT", pnl: -4, pnlPercent: -2, advisory: Self.advisory(.reduce, reason: "Network failed.")), staleStatus: .offline, pnlAgeSeconds: 720, errors: [PositionError(code: "offline_cached_response", message: "cached")])) , "Offline", nil),
            (.offlineWithoutCache(), "Offline", "Unable to load position")
        ]

        for (model, badge, body) in cases {
            let snapshot = PositionPopoverSnapshot(model: model)
            try popoverExpectEqual(snapshot.badge, badge, "badge for \(model.state.rawValue)")
            if let body { try popoverExpectEqual(snapshot.body, body, "body for \(model.state.rawValue)") }
            try popoverExpect(!snapshot.title.isEmpty, "title exists for \(model.state.rawValue)")
            try assertNoForbiddenTradingCopy(snapshot.displayStrings)
        }
    }

    func testHideAmountsSnapshotMasksPrivateNumbers() throws {
        let model = PositionDisplayModel(
            response: try response(position: position(symbol: "BTCUSDT"), staleStatus: .fresh, pnlAgeSeconds: 30),
            options: PositionDisplayOptions(hideAmounts: true)
        )
        let snapshot = PositionPopoverSnapshot(model: model)
        let joined = snapshot.displayStrings.joined(separator: "\n")

        try popoverExpect(joined.contains("Size ••• contracts · 10x"), "size masked")
        try popoverExpect(joined.contains("Entry ••• · Mark •••"), "entry/mark masked")
        try popoverExpect(joined.contains("PnL ••• (+7.50%)"), "absolute pnl masked with percent preserved")
        try popoverExpect(joined.contains("Liq distance •••"), "liquidation distance masked")
        try popoverExpect(joined.contains("HTF: support/resistance hidden"), "HTF levels masked")
        try popoverExpect(joined.contains("LTF: support/resistance hidden"), "LTF levels masked")
        try popoverExpectEqual(snapshot.advisoryLine, "Advisory: HOLD", "hide amounts advisory enum only")
        try popoverExpect(!joined.contains("25000"), "entry price not exposed")
        try popoverExpect(!joined.contains("25150"), "mark price not exposed")
        try popoverExpect(!joined.contains("24000"), "liquidation/support price not exposed")
        try assertNoForbiddenTradingCopy(snapshot.displayStrings)
    }

    func testFullPopoverRedactionHidesPrivateRows() throws {
        let model = PositionDisplayModel(
            response: try response(position: position(symbol: "BTCUSDT"), staleStatus: .fresh, pnlAgeSeconds: 30),
            options: PositionDisplayOptions(hideAmounts: true, redactMenuBar: true, fullPopoverRedaction: true)
        )
        let snapshot = PositionPopoverSnapshot(model: model)
        let joined = snapshot.displayStrings.joined(separator: "\n")

        try popoverExpectEqual(snapshot.menuBarLabel, "Miraj", "redacted menu bar label")
        try popoverExpectEqual(snapshot.body, "Open Miraj to view position details", "redacted body")
        try popoverExpect(snapshot.rows.isEmpty, "redacted popover rows hidden")
        try popoverExpectEqual(snapshot.advisoryLine, "Advisory: HOLD", "redacted advisory enum only")
        try popoverExpect(!joined.contains("+7.50%"), "redacted menu display strings do not expose pnl percent outside hidden rows")
        try assertNoForbiddenTradingCopy(snapshot.displayStrings)
    }

    func testFooterActionsAreLimitedAndRefreshShowsInFlightCopy() throws {
        let connected = PositionPopoverSnapshot(model: PositionDisplayModel(response: try response(position: position(), staleStatus: .fresh, pnlAgeSeconds: 30)), isRefreshing: true)
        try popoverExpectEqual(connected.footerActions, ["Open Miraj", "Refresh"], "connected footer source actions")
        try popoverExpectEqual(connected.renderedFooterActions, ["Open Miraj", "Refreshing…"], "connected refreshing footer")

        let notConnected = PositionPopoverSnapshot(model: .notConnected())
        try popoverExpectEqual(notConnected.footerActions, ["Connect"], "not-connected footer")

        let offlineNoCache = PositionPopoverSnapshot(model: .offlineWithoutCache(), isRefreshing: true)
        try popoverExpectEqual(offlineNoCache.footerActions, ["Refresh"], "offline no-cache footer")
        try popoverExpectEqual(offlineNoCache.renderedFooterActions, ["Refreshing…"], "offline no-cache refreshing footer")

        for snapshot in [connected, notConnected, offlineNoCache] {
            let allowed = Set(["Open Miraj", "Refresh", "Refreshing…", "Connect"])
            try popoverExpect(Set(snapshot.renderedFooterActions).isSubset(of: allowed), "footer actions limited to safe labels")
            try assertNoForbiddenTradingCopy(snapshot.displayStrings)
        }
    }

    func testForbiddenTradingCopyNeverAppearsInSnapshots() throws {
        let models = [
            PositionDisplayModel.notConnected(),
            PositionDisplayModel.offlineWithoutCache(),
            PositionDisplayModel(response: try response(position: nil, staleStatus: .fresh, pnlAgeSeconds: nil, selectionReason: .noOpenPositions)),
            PositionDisplayModel(response: try response(position: position(advisory: Self.advisory(.hold, reason: "Trend remains constructive.")), staleStatus: .fresh, pnlAgeSeconds: 30)),
            PositionDisplayModel(response: try response(position: position(side: .short, pnl: 15, pnlPercent: 15, advisory: Self.advisory(.reduce, reason: "Risk is elevated.")), staleStatus: .stale, pnlAgeSeconds: 360)),
            PositionDisplayModel(response: try response(position: position(pnl: 0, pnlPercent: 0, advisory: Self.advisory(.close, reason: "Original stale reason must be hidden.")), staleStatus: .criticalStale, pnlAgeSeconds: 1_200)),
            PositionDisplayModel(response: try response(position: position(pnl: -4, pnlPercent: -2, advisory: Self.advisory(.wait, reason: "Network failed.")), staleStatus: .offline, pnlAgeSeconds: 720, errors: [PositionError(code: "offline_cached_response", message: "cached")]))
        ]

        for model in models {
            try assertNoForbiddenTradingCopy(PositionPopoverSnapshot(model: model, isRefreshing: true).displayStrings)
        }
    }

    private func assertNoForbiddenTradingCopy(_ strings: [String]) throws {
        let forbidden = ["B" + "uy", "S" + "ell", "Add" + " now", "Exec" + "ute", "Close" + " now", "Reduce" + " now"]
        let joined = strings.joined(separator: "\n")
        for term in forbidden {
            try popoverExpect(!joined.localizedCaseInsensitiveContains(term), "forbidden string \(term) appeared in: \(joined)")
        }
    }

    private func response(
        position: PositionContract?,
        staleStatus: StaleStatus,
        pnlAgeSeconds: Double?,
        selectionReason: SelectionReason = .userSelected,
        errors: [PositionError] = []
    ) throws -> PositionIntelligenceResponse {
        try PositionIntelligenceResponse(
            schemaVersion: 1,
            exchange: "mexc",
            selectionReason: position == nil ? .noOpenPositions : selectionReason,
            generatedAt: now,
            source: PositionSource(
                portfolioLastRefreshed: now.addingTimeInterval(-60),
                markPriceSource: "cached",
                markPriceLastRefreshed: now.addingTimeInterval(-(pnlAgeSeconds ?? 60)),
                pnlAgeSeconds: pnlAgeSeconds,
                staleStatus: staleStatus
            ),
            position: position,
            privacy: PrivacyContract(hideAmountsAvailable: true, redactionSupported: true),
            errors: errors
        )
    }

    private func position(
        symbol: String = "BTCUSDT",
        side: PositionSide = .long,
        pnl: Double = 15,
        pnlPercent: Double = 7.5,
        advisory: PositionAdvisory = PositionPopoverViewTestSuite.advisory(.hold, reason: "Trend remains constructive.")
    ) -> PositionContract {
        PositionContract(
            symbol: symbol,
            side: side,
            sizeContracts: 3,
            contractSize: 0.5,
            entryPrice: 25_000,
            markPrice: 25_150,
            pnl: pnl,
            pnlPercent: pnlPercent,
            pnlFormula: .computedContractsContractSize,
            margin: 200,
            leverage: 10,
            liquidationPrice: 24_000,
            liquidationDistancePct: 4.4,
            htfSR: supportResistanceBlock(timeframes: ["Daily", "Weekly"], support: 24_250, resistance: 26_000),
            ltfSR: supportResistanceBlock(timeframes: ["1H", "4H"], support: 24_800, resistance: 25_500),
            advisory: advisory,
            dashboardDeeplink: "/portfolio?symbol=BTCUSDT"
        )
    }

    private static func advisory(_ action: AdvisoryAction, reason: String) -> PositionAdvisory {
        PositionAdvisory(action: action, severity: action == .close ? .danger : (action == .hold ? .info : .warning), reason: reason, source: .fallback, actionItemsCount: 0)
    }

    private func supportResistanceBlock(timeframes: [String], support: Double?, resistance: Double?) -> SupportResistanceBlock {
        SupportResistanceBlock(
            timeframes: timeframes,
            support: support.map { level(price: $0, swingType: "low") },
            resistance: resistance.map { level(price: $0, swingType: "high") },
            structureLabel: "bullish",
            confidence: .high
        )
    }

    private func level(price: Double, swingType: String) -> SupportResistanceLevel {
        SupportResistanceLevel(price: price, distancePct: 1.2, timeframe: "Daily", swingType: swingType, swingIndex: 7, method: "smc_swing")
    }
}

@main
struct PositionPopoverViewTestRunner {
    static func main() {
        do {
            try PositionPopoverViewTestSuite().runAll()
            print("PositionPopoverViewTests: 5 tests passed")
        } catch {
            fputs("PositionPopoverViewTests failed: \(error)\n", stderr)
            exit(1)
        }
    }
}
