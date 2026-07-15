import Foundation

#if canImport(MirajPositionMenuBar)
@testable import MirajPositionMenuBar
#endif

@main
struct PositionClientCacheTestRunner {
    static func main() async throws {
        let tests = PositionClientCacheTests()
        try tests.testRequestTargetsOnlyDesktopEndpointWithMEXCExchangeAndOptionalSymbol()
        try tests.testRequestRejectsNonHTTPSBackendBeforeAuthorizationCanBeAttached()
        try await tests.testFetchUsesBearerTokenAndStoresSchemaVersionOneSnapshot()
        try await tests.testNetworkFailureMapsToOfflineWithCache()
        try await tests.testNetworkFailureMapsToOfflineWithoutCacheWhenNoSnapshotExists()
        try await tests.testNonSuccessHTTPStatusesAreClassifiedWithoutCachingPrivateErrorBodies()
        try await tests.testAutomaticRefreshThrottleAndManualInFlightState()
        try tests.testCacheRejectsUnsupportedSchemaSnapshotOnLoad()
        try tests.testCacheSnapshotDoesNotPersistTokenOrForbiddenCredentialMaterial()
        try tests.testScopedDataAccessFilesContainNoForbiddenEndpointsOrCredentialExamples()
        print("PositionClientCacheTests: 10 passed")
    }
}

final class PositionClientCacheTests {
    func testRequestTargetsOnlyDesktopEndpointWithMEXCExchangeAndOptionalSymbol() throws {
        let client = PositionClient(baseURL: URL(string: "https://ta.munafaplus.pk")!, tokenStore: MemoryTokenStore(token: "session-token"))

        let unsymbolized = try client.makeRequest()
        try assertEqual(unsymbolized.httpMethod, "GET")
        try assertEqual(unsymbolized.url?.path, "/api/v1/desktop/position-intelligence")
        try assertEqual(queryValue("exchange", in: unsymbolized.url), "mexc")
        try assert(queryValue("symbol", in: unsymbolized.url) == nil)

        let symbolized = try client.makeRequest(symbol: " btc/usdt:usdt ")
        try assertEqual(symbolized.httpMethod, "GET")
        try assertEqual(symbolized.url?.path, "/api/v1/desktop/position-intelligence")
        try assertEqual(queryValue("exchange", in: symbolized.url), "mexc")
        try assertEqual(queryValue("symbol", in: symbolized.url), "BTC/USDT:USDT")
        try assertNotForbiddenEndpoint(symbolized.url?.absoluteString ?? "")
    }

    func testRequestRejectsNonHTTPSBackendBeforeAuthorizationCanBeAttached() throws {
        let rejectedBaseURLs = [
            URL(string: "http://example.invalid")!,
            URL(string: "file:///tmp/private")!,
            URL(string: "miraj://portfolio")!
        ]

        for baseURL in rejectedBaseURLs {
            let client = PositionClient(baseURL: baseURL, tokenStore: MemoryTokenStore(token: "session-token"))
            do {
                _ = try client.makeRequest()
                throw TestFailure.failed("expected \(baseURL.absoluteString) to be rejected")
            } catch PositionClientError.invalidBaseURL {
            }
        }
    }

    func testFetchUsesBearerTokenAndStoresSchemaVersionOneSnapshot() async throws {
        let token = "session-token-not-real"
        MockURLProtocol.requestHandler = { request in
            try assertEqual(request.httpMethod, "GET")
            try assertEqual(request.url?.path, "/api/v1/desktop/position-intelligence")
            try assertEqual(self.queryValue("exchange", in: request.url), "mexc")
            try assertEqual(request.value(forHTTPHeaderField: "Authorization"), "Bearer \(token)")
            try self.assertNotForbiddenEndpoint(request.url?.absoluteString ?? "")
            return (HTTPURLResponse(url: request.url!, statusCode: 200, httpVersion: nil, headerFields: nil)!, Data(Self.freshPositionJSON.utf8))
        }

        let directory = try temporaryDirectory()
        let cache = try PositionCache(directoryURL: directory)
        let client = PositionClient(
            baseURL: URL(string: "https://ta.munafaplus.pk")!,
            session: Self.mockedSession(),
            tokenStore: MemoryTokenStore(token: token),
            cache: cache
        )

        let result = await client.loadPosition(symbol: "BTC/USDT:USDT")
        switch result {
        case .loaded(let response):
            try assertEqual(response.schemaVersion, 1)
            try assertEqual(response.position?.symbol, "BTC/USDT:USDT")
        default:
            throw TestFailure.failed("expected loaded result, got \(result)")
        }

        let cached = try cache.load()
        try assertEqual(cached?.schemaVersion, 1)
        try assertEqual(cached?.position?.symbol, "BTC/USDT:USDT")
        let cacheText = try String(contentsOf: directory.appendingPathComponent(PositionCache.snapshotFileName), encoding: .utf8)
        try assert(!cacheText.contains(token), "cache snapshot must not persist Miraj session token")
    }

    func testNetworkFailureMapsToOfflineWithCache() async throws {
        let cache = try PositionCache(directoryURL: temporaryDirectory())
        try cache.save(try decode(Self.freshPositionJSON))
        MockURLProtocol.requestHandler = { _ in throw URLError(.notConnectedToInternet) }
        let client = PositionClient(
            baseURL: URL(string: "https://ta.munafaplus.pk")!,
            session: Self.mockedSession(),
            tokenStore: MemoryTokenStore(token: "session-token"),
            cache: cache
        )

        let result = await client.loadPosition()
        switch result {
        case .offlineWithCache(let cached, let reason):
            try assertEqual(cached.schemaVersion, 1)
            try assertEqual(cached.position?.symbol, "BTC/USDT:USDT")
            try assertEqual(reason, .transportUnavailable)
        default:
            throw TestFailure.failed("expected offline-with-cache state, got \(result)")
        }
    }

    func testNetworkFailureMapsToOfflineWithoutCacheWhenNoSnapshotExists() async throws {
        MockURLProtocol.requestHandler = { _ in throw URLError(.timedOut) }
        let client = PositionClient(
            baseURL: URL(string: "https://ta.munafaplus.pk")!,
            session: Self.mockedSession(),
            tokenStore: MemoryTokenStore(token: "session-token"),
            cache: try PositionCache(directoryURL: temporaryDirectory())
        )

        let result = await client.loadPosition()
        switch result {
        case .offlineWithoutCache(let reason):
            try assertEqual(reason, .transportUnavailable)
        default:
            throw TestFailure.failed("expected offline-without-cache state, got \(result)")
        }
    }

    func testNonSuccessHTTPStatusesAreClassifiedWithoutCachingPrivateErrorBodies() async throws {
        let statuses = [401, 403, 404, 500]
        for status in statuses {
            MockURLProtocol.requestHandler = { request in
                (HTTPURLResponse(url: request.url!, statusCode: status, httpVersion: nil, headerFields: nil)!, Data("private backend body must be ignored".utf8))
            }
            let client = PositionClient(
                baseURL: URL(string: "https://ta.munafaplus.pk")!,
                session: Self.mockedSession(),
                tokenStore: MemoryTokenStore(token: "session-token"),
                cache: try PositionCache(directoryURL: temporaryDirectory())
            )

            let result = await client.loadPosition()
            switch (status, result) {
            case (401, .offlineWithoutCache(.unauthorized)), (403, .offlineWithoutCache(.unauthorized)):
                continue
            case (404, .offlineWithoutCache(.nonSuccessStatus(404))), (500, .offlineWithoutCache(.nonSuccessStatus(500))):
                continue
            default:
                throw TestFailure.failed("unexpected classification for HTTP \(status): \(result)")
            }
        }
    }

    func testAutomaticRefreshThrottleAndManualInFlightState() async throws {
        final class SlowTokenStore: PositionTokenStoring {
            func readToken() throws -> String? { "session-token" }
            func saveToken(_ token: String) throws {}
            func clearToken() throws {}
        }

        var requestCount = 0
        MockURLProtocol.requestHandler = { request in
            requestCount += 1
            Thread.sleep(forTimeInterval: 0.05)
            return (HTTPURLResponse(url: request.url!, statusCode: 200, httpVersion: nil, headerFields: nil)!, Data(Self.freshPositionJSON.utf8))
        }
        var now = Date(timeIntervalSince1970: 100)
        let client = PositionClient(
            baseURL: URL(string: "https://ta.munafaplus.pk")!,
            session: Self.mockedSession(),
            tokenStore: SlowTokenStore(),
            cache: nil
        )
        let coordinator = PositionRefreshCoordinator(client: client, now: { now })

        let first = await coordinator.refresh(trigger: .automatic)
        if case .success(.loaded) = first {} else { throw TestFailure.failed("expected first automatic refresh to load, got \(first)") }

        let throttled = await coordinator.refresh(trigger: .automatic)
        if case .failure(.automaticRefreshThrottled(let remaining)) = throttled {
            try assert(remaining >= 59 && remaining <= 60, "remaining throttle should be about 60 seconds")
        } else {
            throw TestFailure.failed("expected automatic throttle, got \(throttled)")
        }

        let manualTask = Task { await coordinator.refresh(trigger: .manual) }
        while await coordinator.isInFlight == false {
            try await Task.sleep(nanoseconds: 5_000_000)
        }
        let inFlight = await coordinator.refresh(trigger: .manual)
        if case .failure(.refreshInFlight) = inFlight {} else { throw TestFailure.failed("expected in-flight manual refresh state") }
        _ = await manualTask.value

        now = Date(timeIntervalSince1970: 161)
        let later = await coordinator.refresh(trigger: .automatic)
        if case .success(.loaded) = later {} else { throw TestFailure.failed("expected automatic refresh after 60s, got \(later)") }
        try assert(requestCount >= 3, "manual refresh should remain read-only network GET and count as a request")
    }

    func testCacheRejectsUnsupportedSchemaSnapshotOnLoad() throws {
        let directory = try temporaryDirectory()
        let snapshotURL = directory.appendingPathComponent(PositionCache.snapshotFileName)
        try Self.freshPositionJSON.replacingOccurrences(of: "\"schema_version\": 1", with: "\"schema_version\": 2").data(using: .utf8)!.write(to: snapshotURL)
        let cache = try PositionCache(directoryURL: directory)
        do {
            _ = try cache.load()
            throw TestFailure.failed("expected unsupported schema snapshot to be rejected")
        } catch let error as PositionContractError {
            try assertEqual(error, .unsupportedSchemaVersion(2))
        }
    }

    func testCacheSnapshotDoesNotPersistTokenOrForbiddenCredentialMaterial() throws {
        let directory = try temporaryDirectory()
        let cache = try PositionCache(directoryURL: directory)
        let token = "session-token-redacted-marker"
        try cache.save(try decode(Self.freshPositionJSON))
        let text = try String(contentsOf: directory.appendingPathComponent(PositionCache.snapshotFileName), encoding: .utf8)
        try assert(text.contains("\"schema_version\":1"), "cache stores schema_version=1 display snapshots")
        try assert(!text.contains(token), "cache must not persist token values")
        try assert(!text.localizedCaseInsensitiveContains("authorization"))
        try assert(!text.localizedCaseInsensitiveContains("cookie"))
        try assert(!text.localizedCaseInsensitiveContains("api_key"))
        try assert(!text.localizedCaseInsensitiveContains("secret"))
    }

    func testScopedDataAccessFilesContainNoForbiddenEndpointsOrCredentialExamples() throws {
        let files = [
            "desktop/MirajPositionMenuBar/Sources/MirajPositionMenuBar/PositionClient.swift",
            "desktop/MirajPositionMenuBar/Sources/MirajPositionMenuBar/PositionCache.swift",
            "desktop/MirajPositionMenuBar/Sources/MirajPositionMenuBar/PositionTokenStore.swift",
            "desktop/MirajPositionMenuBar/Sources/MirajPositionMenuBar/PositionPreferences.swift",
            "desktop/MirajPositionMenuBar/Tests/MirajPositionMenuBarTests/PositionClientCacheTests.swift"
        ]
        let commonForbiddenPatterns = [
            #"(?i)mexc[_ -]?(api|secret)\s*[:=]\s*[\"'][^\"']+[\"']"#,
            #"(?i)exchange[_ -]?key\s*[:=]\s*[\"'][^\"']+[\"']"#,
            #"(?i)(cookie|set-cookie)\s*[:=]"#,
            #"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"#
        ]

        for file in files {
            let text = try String(contentsOf: sourceURL(file), encoding: .utf8)
            for pattern in commonForbiddenPatterns {
                try assert(text.range(of: pattern, options: [.regularExpression]) == nil, "\(file) matched forbidden pattern \(pattern)")
            }
        }

        let clientSource = try String(contentsOf: sourceURL("desktop/MirajPositionMenuBar/Sources/MirajPositionMenuBar/PositionClient.swift"), encoding: .utf8)
        try assert(clientSource.range(of: #"/api/v1/(trade|orders|positions/.*/close|portfolio/.*/dca/execute|.*leverage|.*dca/execute)"#, options: [.regularExpression]) == nil, "PositionClient must not target trading or execution endpoints")
        try assert(clientSource.range(of: #"(?i)\b(POST|PUT|PATCH|DELETE)\b"#, options: [.regularExpression]) == nil, "PositionClient must remain GET-only")
    }

    private static func mockedSession() -> URLSession {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [MockURLProtocol.self]
        configuration.timeoutIntervalForRequest = 1
        configuration.timeoutIntervalForResource = 1
        return URLSession(configuration: configuration)
    }

    private func temporaryDirectory() throws -> URL {
        let url = FileManager.default.temporaryDirectory.appendingPathComponent("position-client-cache-tests-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: url, withIntermediateDirectories: true)
        return url
    }

    private func sourceURL(_ relativePath: String) -> URL {
        URL(fileURLWithPath: FileManager.default.currentDirectoryPath).appendingPathComponent(relativePath)
    }

    private func queryValue(_ name: String, in url: URL?) -> String? {
        guard let url, let components = URLComponents(url: url, resolvingAgainstBaseURL: false) else { return nil }
        return components.queryItems?.first(where: { $0.name == name })?.value
    }

    private func assertNotForbiddenEndpoint(_ text: String) throws {
        let forbidden = ["/trade", "/orders", "/leverage", "/dca/execute", "ccxt"]
        for term in forbidden {
            try assert(!text.localizedCaseInsensitiveContains(term), "request must not target forbidden endpoint \(term): \(text)")
        }
    }

    private static let freshPositionJSON = """
    {
      "schema_version": 1,
      "exchange": "mexc",
      "selection_reason": "user_selected",
      "generated_at": "2026-07-15T10:00:00Z",
      "source": {
        "portfolio_last_refreshed": "2026-07-15T09:58:00Z",
        "mark_price_source": "backend_cache",
        "mark_price_last_refreshed": "2026-07-15T09:58:00Z",
        "pnl_age_seconds": 120,
        "stale_status": "fresh"
      },
      "position": {
        "symbol": "BTC/USDT:USDT",
        "side": "LONG",
        "size_contracts": 3,
        "contract_size": 0.5,
        "entry_price": 100,
        "mark_price": 110,
        "margin": 100,
        "pnl": 15,
        "pnl_percent": 15,
        "pnl_formula": "computed_contracts_contract_size",
        "leverage": 2,
        "liquidation_price": 80,
        "liquidation_distance_pct": 20,
        "htf_sr": {
          "timeframes": ["Daily", "Weekly"],
          "support": {"price": 95, "distance_pct": 13.64, "method": "smc_swing", "timeframe": "Daily", "swing_type": "low", "swing_index": 10},
          "resistance": {"price": 120, "distance_pct": 9.09, "method": "smc_swing", "timeframe": "Weekly", "swing_type": "high", "swing_index": 4},
          "structure_label": "bullish",
          "confidence": "HIGH"
        },
        "ltf_sr": {
          "timeframes": ["1H", "4H"],
          "support": {"price": 104, "distance_pct": 5.45, "method": "smc_swing", "timeframe": "1H", "swing_type": "low", "swing_index": 22},
          "resistance": {"price": 112, "distance_pct": 1.82, "method": "smc_swing", "timeframe": "4H", "swing_type": "high", "swing_index": 8},
          "structure_label": "bullish",
          "confidence": "HIGH"
        },
        "advisory": {
          "action": "HOLD",
          "severity": "INFO",
          "reason": "Hold current position and review Miraj before changes.",
          "source": "fallback",
          "action_items_count": 0
        },
        "dashboard_deeplink": "/portfolio?symbol=BTC%2FUSDT%3AUSDT"
      },
      "privacy": {"hide_amounts_available": true, "redaction_supported": true},
      "errors": []
    }
    """
}

private final class MemoryTokenStore: PositionTokenStoring {
    private var token: String?

    init(token: String?) {
        self.token = token
    }

    func readToken() throws -> String? { token }
    func saveToken(_ token: String) throws { self.token = token }
    func clearToken() throws { token = nil }
}

private final class MockURLProtocol: URLProtocol {
    static var requestHandler: ((URLRequest) throws -> (HTTPURLResponse, Data))?

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
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

private func decode(_ text: String) throws -> PositionIntelligenceResponse {
    try JSONDecoder.positionIntelligenceDecoder.decode(PositionIntelligenceResponse.self, from: Data(text.utf8))
}

private enum TestFailure: Error, CustomStringConvertible {
    case failed(String)

    var description: String {
        switch self {
        case .failed(let message): return message
        }
    }
}

private func assert(_ condition: Bool, _ message: String = "assertion failed") throws {
    if !condition { throw TestFailure.failed(message) }
}

private func assertEqual<T: Equatable>(_ actual: T, _ expected: T, _ message: String = "") throws {
    if actual != expected {
        throw TestFailure.failed("expected \(expected), got \(actual)" + (message.isEmpty ? "" : " — \(message)"))
    }
}
