import Foundation
import SwiftUI

#if canImport(MirajPositionMenuBar)
@testable import MirajPositionMenuBar
#endif

@main
struct MirajPositionMenuBarViewModelTestRunner {
    static func main() async {
        do {
            let tests = MirajPositionMenuBarViewModelTests()
            try await tests.testManualRefreshLoadsPositionFromReadOnlyDesktopEndpoint()
            try await tests.testUnauthorizedAndNotConnectedMapToNotConnectedState()
            try await tests.testOfflineWithCacheMapsCachedSnapshotToOfflineDisplayState()
            try await tests.testOfflineWithoutCacheMapsToOfflineDisplayState()
            try await tests.testAutomaticRefreshUsesPreferenceAndCoordinatorThrottle()
            try await tests.testMockFixtureRuntimeLoadsAllFixturesWithoutURLRequestOrToken()
            print("MirajPositionMenuBarViewModelTests: 6 tests passed")
        } catch {
            fputs("MirajPositionMenuBarViewModelTests failed: \(error)\n", stderr)
            exit(1)
        }
    }
}

@MainActor
final class MirajPositionMenuBarViewModelTests {
    func testManualRefreshLoadsPositionFromReadOnlyDesktopEndpoint() async throws {
        MenuBarRecordingURLProtocol.reset()
        MenuBarRecordingURLProtocol.requestHandler = { request in
            Thread.sleep(forTimeInterval: 0.05)
            try menuBarAssertEqual(request.httpMethod, "GET", "manual refresh method")
            try menuBarAssertEqual(request.url?.path, PositionClient.endpointPath, "manual refresh path")
            try menuBarAssertEqual(Self.queryValue("exchange", in: request.url), "mexc", "manual refresh exchange")
            try menuBarAssertEqual(Self.queryValue("symbol", in: request.url), "ETHUSDT", "manual refresh selected symbol")
            try Self.assertNoForbiddenEndpoint(request)
            return (HTTPURLResponse(url: request.url!, statusCode: 200, httpVersion: nil, headerFields: nil)!, try JSONEncoder.positionIntelligenceEncoder.encode(Self.response(symbol: "ETHUSDT")))
        }

        let viewModel = makeViewModel(
            token: "session-token",
            preferences: PositionPreferences(selectedSymbol: " ethusdt ", refreshPreference: .manualOnly),
            cache: try PositionCache(directoryURL: temporaryDirectory())
        )

        viewModel.refresh()
        try await waitUntilRefreshing(viewModel)
        try menuBarAssertEqual(viewModel.isRefreshing, true, "manual refresh shows in-flight state")
        try await waitForRefreshCycle(viewModel)

        try menuBarAssertEqual(viewModel.displayModel.state, .fresh, "manual refresh display state")
        try menuBarAssertEqual(viewModel.displayModel.title, "ETHUSDT", "manual refresh symbol")
        try menuBarAssertEqual(viewModel.isRefreshing, false, "manual refresh clears in-flight state")
        try menuBarAssertEqual(MenuBarRecordingURLProtocol.requests.count, 1, "manual refresh request count")
    }

    func testUnauthorizedAndNotConnectedMapToNotConnectedState() async throws {
        MenuBarRecordingURLProtocol.reset()
        MenuBarRecordingURLProtocol.requestHandler = { request in
            try Self.assertNoForbiddenEndpoint(request)
            return (HTTPURLResponse(url: request.url!, statusCode: 401, httpVersion: nil, headerFields: nil)!, Data("ignored private body".utf8))
        }
        let unauthorized = makeViewModel(token: "expired", cache: try PositionCache(directoryURL: temporaryDirectory()))
        unauthorized.refresh()
        try await waitForRefreshCycle(unauthorized)
        try menuBarAssertEqual(unauthorized.displayModel.state, .notConnected, "unauthorized maps to not connected")
        try menuBarAssertEqual(MenuBarRecordingURLProtocol.requests.count, 1, "unauthorized performs one read-only request")

        MenuBarRecordingURLProtocol.reset()
        MenuBarRecordingURLProtocol.requestHandler = { request in
            throw MenuBarViewModelTestFailure.failed("not-connected refresh must not hit network: \(request)")
        }
        let cachedWhileSignedOut = try PositionCache(directoryURL: temporaryDirectory())
        try cachedWhileSignedOut.save(Self.response(symbol: "XRPUSDT", staleStatus: .offline, pnlAgeSeconds: 720, errors: [PositionError(code: "offline_cached_response", message: "cached")]))
        let notConnected = makeViewModel(token: nil, cache: cachedWhileSignedOut)
        notConnected.refresh()
        try await waitForRefreshCycle(notConnected)
        try menuBarAssertEqual(notConnected.displayModel.state, .notConnected, "missing token maps to not connected")
        try menuBarAssertEqual(MenuBarRecordingURLProtocol.requests.count, 0, "missing token does not call endpoint")
    }

    func testOfflineWithCacheMapsCachedSnapshotToOfflineDisplayState() async throws {
        let cache = try PositionCache(directoryURL: temporaryDirectory())
        try cache.save(Self.response(symbol: "SOLUSDT", staleStatus: .offline, pnlAgeSeconds: 720, errors: [PositionError(code: "offline_cached_response", message: "cached")]))
        MenuBarRecordingURLProtocol.reset()
        MenuBarRecordingURLProtocol.requestHandler = { request in
            try Self.assertNoForbiddenEndpoint(request)
            throw URLError(.notConnectedToInternet)
        }

        let viewModel = makeViewModel(token: "session-token", cache: cache)
        viewModel.refresh()
        try await waitForRefreshCycle(viewModel)

        try menuBarAssertEqual(viewModel.displayModel.state, .offlineWithCache, "offline cached display state")
        try menuBarAssertEqual(viewModel.displayModel.title, "SOLUSDT", "offline cached symbol")
        try menuBarAssertEqual(viewModel.displayModel.badge, "Offline", "offline cached badge")
        try menuBarAssertEqual(MenuBarRecordingURLProtocol.requests.count, 1, "offline with cache still attempted read-only refresh")
    }

    func testOfflineWithoutCacheMapsToOfflineDisplayState() async throws {
        MenuBarRecordingURLProtocol.reset()
        MenuBarRecordingURLProtocol.requestHandler = { request in
            try Self.assertNoForbiddenEndpoint(request)
            throw URLError(.timedOut)
        }

        let viewModel = makeViewModel(token: "session-token", cache: try PositionCache(directoryURL: temporaryDirectory()))
        viewModel.refresh()
        try await waitForRefreshCycle(viewModel)

        try menuBarAssertEqual(viewModel.displayModel.state, .offlineWithoutCache, "offline without cache display state")
        try menuBarAssertEqual(viewModel.displayModel.footerActions, ["Refresh"], "offline without cache action")
        try menuBarAssertEqual(MenuBarRecordingURLProtocol.requests.count, 1, "offline without cache read-only request count")
    }

    func testAutomaticRefreshUsesPreferenceAndCoordinatorThrottle() async throws {
        var now = Date(timeIntervalSince1970: 100)
        MenuBarRecordingURLProtocol.reset()
        MenuBarRecordingURLProtocol.requestHandler = { request in
            try menuBarAssertEqual(request.httpMethod, "GET", "automatic refresh method")
            try menuBarAssertEqual(request.url?.path, PositionClient.endpointPath, "automatic refresh path")
            try Self.assertNoForbiddenEndpoint(request)
            return (HTTPURLResponse(url: request.url!, statusCode: 200, httpVersion: nil, headerFields: nil)!, try JSONEncoder.positionIntelligenceEncoder.encode(Self.response(symbol: "BTCUSDT")))
        }

        let client = PositionClient(
            baseURL: PositionPreferencesStore.defaultAPIBaseURL,
            session: Self.mockedSession(),
            tokenStore: MenuBarMemoryTokenStore(token: "session-token"),
            cache: try PositionCache(directoryURL: temporaryDirectory())
        )
        let coordinator = PositionRefreshCoordinator(client: client, now: { now })
        let viewModel = MirajPositionMenuBarViewModel(
            preferencesStore: MenuBarPreferencesStore(PositionPreferences(refreshPreference: .automatic)),
            refreshCoordinator: coordinator
        )

        viewModel.refreshAutomaticallyIfEnabled()
        try await waitForRefreshCycle(viewModel)
        try menuBarAssertEqual(MenuBarRecordingURLProtocol.requests.count, 1, "first automatic refresh request count")

        viewModel.refreshAutomaticallyIfEnabled()
        try await waitForRefreshCycle(viewModel)
        try menuBarAssertEqual(MenuBarRecordingURLProtocol.requests.count, 1, "second automatic refresh is throttled before network")
        try menuBarAssertEqual(viewModel.displayModel.state, .fresh, "throttled automatic refresh preserves current display")

        now = Date(timeIntervalSince1970: 161)
        viewModel.refreshAutomaticallyIfEnabled()
        try await waitForRefreshCycle(viewModel)
        try menuBarAssertEqual(MenuBarRecordingURLProtocol.requests.count, 2, "automatic refresh after 60s reaches endpoint")
    }

    func testMockFixtureRuntimeLoadsAllFixturesWithoutURLRequestOrToken() async throws {
        MenuBarRecordingURLProtocol.reset()
        MenuBarRecordingURLProtocol.requestHandler = { request in
            throw MenuBarViewModelTestFailure.failed("mock fixture runtime must not create URLRequest: \(request)")
        }

        let preferences = PositionPreferences(refreshPreference: .automatic, runtimeMode: .mockFixtures)
        let viewModel = MirajPositionMenuBarViewModel(
            preferencesStore: MenuBarPreferencesStore(preferences),
            refreshCoordinator: MirajPositionMenuBarViewModel.makeRuntimeCoordinator(preferences: preferences),
            automaticallyRefreshOnLaunch: true
        )
        try await waitForRefreshCycle(viewModel)

        try menuBarAssertEqual(MenuBarRecordingURLProtocol.requests.count, 0, "mock runtime must not create URLRequest")
        try menuBarAssertEqual(viewModel.displayModel.state, .fresh, "default mock runtime renders fresh fixture")
        try menuBarAssertEqual(viewModel.displayModel.title, "BTCUSDT", "default mock runtime renders fixture symbol")

        let provider = MockFixturePositionProvider()
        for fixtureName in MockFixturePositionProvider.fixtureNames {
            let result = await provider.refresh(trigger: .manual, symbol: fixtureName)
            if case .success(.loaded(let response)) = result {
                try menuBarAssertEqual(response.schemaVersion, 1, "mock fixture schema version for \(fixtureName)")
            } else {
                throw MenuBarViewModelTestFailure.failed("expected mock fixture \(fixtureName) to load locally, got \(result)")
            }
        }
    }

    private func makeViewModel(
        token: String?,
        preferences: PositionPreferences = PositionPreferences(refreshPreference: .manualOnly),
        cache: PositionCache
    ) -> MirajPositionMenuBarViewModel {
        let client = PositionClient(
            baseURL: preferences.debugAPIBaseURL,
            session: Self.mockedSession(),
            tokenStore: MenuBarMemoryTokenStore(token: token),
            cache: cache
        )
        return MirajPositionMenuBarViewModel(
            preferencesStore: MenuBarPreferencesStore(preferences),
            refreshCoordinator: PositionRefreshCoordinator(client: client)
        )
    }

    private static func mockedSession() -> URLSession {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [MenuBarRecordingURLProtocol.self]
        configuration.timeoutIntervalForRequest = 1
        configuration.timeoutIntervalForResource = 1
        return URLSession(configuration: configuration)
    }

    private func waitForRefreshCycle(_ viewModel: MirajPositionMenuBarViewModel) async throws {
        try await Task.sleep(nanoseconds: 20_000_000)
        for _ in 0..<200 {
            if !viewModel.isRefreshing { return }
            try await Task.sleep(nanoseconds: 5_000_000)
        }
        throw MenuBarViewModelTestFailure.failed("refresh cycle did not complete; isRefreshing=\(viewModel.isRefreshing)")
    }

    private func waitUntilRefreshing(_ viewModel: MirajPositionMenuBarViewModel) async throws {
        for _ in 0..<200 {
            if viewModel.isRefreshing { return }
            try await Task.sleep(nanoseconds: 5_000_000)
        }
        throw MenuBarViewModelTestFailure.failed("refresh cycle did not expose in-flight state")
    }

    private func temporaryDirectory() throws -> URL {
        let url = FileManager.default.temporaryDirectory.appendingPathComponent("menubar-viewmodel-tests-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: url, withIntermediateDirectories: true)
        return url
    }

    private static func response(
        symbol: String = "BTCUSDT",
        staleStatus: StaleStatus = .fresh,
        pnlAgeSeconds: Double? = 30,
        errors: [PositionError] = []
    ) -> PositionIntelligenceResponse {
        try! PositionIntelligenceResponse(
            schemaVersion: 1,
            exchange: "mexc",
            selectionReason: .userSelected,
            generatedAt: ISO8601DateFormatter().date(from: "2026-07-15T10:00:00Z")!,
            source: PositionSource(
                portfolioLastRefreshed: ISO8601DateFormatter().date(from: "2026-07-15T09:59:00Z")!,
                markPriceSource: "backend_cache",
                markPriceLastRefreshed: ISO8601DateFormatter().date(from: "2026-07-15T09:59:30Z")!,
                pnlAgeSeconds: pnlAgeSeconds,
                staleStatus: staleStatus
            ),
            position: PositionContract(
                symbol: symbol,
                side: .long,
                sizeContracts: 3,
                contractSize: 0.5,
                entryPrice: 100,
                markPrice: 110,
                pnl: 15,
                pnlPercent: 15,
                pnlFormula: .computedContractsContractSize,
                margin: 100,
                leverage: 2,
                liquidationPrice: 80,
                liquidationDistancePct: 20,
                htfSR: Self.supportResistanceBlock(),
                ltfSR: Self.supportResistanceBlock(),
                advisory: PositionAdvisory(action: .hold, severity: .info, reason: "Hold current position and review Miraj before changes.", source: .fallback, actionItemsCount: 0),
                dashboardDeeplink: "/portfolio?symbol=\(symbol)"
            ),
            privacy: PrivacyContract(hideAmountsAvailable: true, redactionSupported: true),
            errors: errors
        )
    }

    private static func supportResistanceBlock() -> SupportResistanceBlock {
        SupportResistanceBlock(
            timeframes: ["1H", "4H"],
            support: SupportResistanceLevel(price: 95, distancePct: 13.64, timeframe: "1H", swingType: "low", swingIndex: 10, method: "smc_swing"),
            resistance: SupportResistanceLevel(price: 120, distancePct: 9.09, timeframe: "4H", swingType: "high", swingIndex: 4, method: "smc_swing"),
            structureLabel: "bullish",
            confidence: .high
        )
    }

    private static func queryValue(_ name: String, in url: URL?) -> String? {
        guard let url, let components = URLComponents(url: url, resolvingAgainstBaseURL: false) else { return nil }
        return components.queryItems?.first(where: { $0.name == name })?.value
    }

    private static func assertNoForbiddenEndpoint(_ request: URLRequest) throws {
        let text = "\(request.httpMethod ?? "") \(request.url?.absoluteString ?? "")"
        let forbidden = ["/tr" + "ade", "/ord" + "ers", "/lev" + "erage", "/dca/exec" + "ute", "cc" + "xt"]
        for term in forbidden {
            try menuBarAssert(!text.localizedCaseInsensitiveContains(term), "request must not target forbidden endpoint \(term): \(text)")
        }
        try menuBarAssertEqual(request.httpMethod, "GET", "request remains GET-only")
        try menuBarAssertEqual(request.url?.path, PositionClient.endpointPath, "request path remains desktop position intelligence")
    }
}

private struct MenuBarPreferencesStore: PositionPreferencesLoading {
    let preferences: PositionPreferences

    init(_ preferences: PositionPreferences) {
        self.preferences = preferences
    }

    func load() -> PositionPreferences { preferences }
}

private final class MenuBarMemoryTokenStore: PositionTokenStoring {
    private var token: String?

    init(token: String?) {
        self.token = token
    }

    func readToken() throws -> String? { token }
    func saveToken(_ token: String) throws { self.token = token }
    func clearToken() throws { token = nil }
}

private final class MenuBarRecordingURLProtocol: URLProtocol {
    static var requests: [URLRequest] = []
    static var requestHandler: ((URLRequest) throws -> (HTTPURLResponse, Data))?

    static func reset() {
        requests = []
        requestHandler = nil
    }

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        Self.requests.append(request)
        guard let handler = Self.requestHandler else {
            client?.urlProtocol(self, didFailWithError: URLError(.badServerResponse))
            return
        }
        do {
            let (response, data) = try handler(request)
            client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
            client?.urlProtocol(self, didLoad: data)
            client?.urlProtocolDidFinishLoading(self)
        } catch {
            client?.urlProtocol(self, didFailWithError: error)
        }
    }

    override func stopLoading() {}
}

private enum MenuBarViewModelTestFailure: Error, CustomStringConvertible {
    case failed(String)

    var description: String {
        switch self {
        case .failed(let message): return message
        }
    }
}

private func menuBarAssert(_ condition: Bool, _ message: String) throws {
    if !condition { throw MenuBarViewModelTestFailure.failed(message) }
}

private func menuBarAssertEqual<T: Equatable>(_ actual: T, _ expected: T, _ message: String) throws {
    if actual != expected { throw MenuBarViewModelTestFailure.failed("\(message): expected \(expected), got \(actual)") }
}
