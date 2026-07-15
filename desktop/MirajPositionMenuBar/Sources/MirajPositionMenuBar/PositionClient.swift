import Foundation

public enum PositionClientError: Error, Equatable, LocalizedError {
    case notConnected
    case invalidBaseURL
    case invalidResponse
    case unauthorized
    case nonSuccessStatus(Int)
    case unsupportedSchemaVersion(Int)
    case transportUnavailable
    case refreshInFlight
    case automaticRefreshThrottled(remainingSeconds: TimeInterval)

    public var errorDescription: String? {
        switch self {
        case .notConnected: return "Connect to Miraj before loading position intelligence"
        case .invalidBaseURL: return "Miraj backend URL must be HTTPS"
        case .invalidResponse: return "Miraj backend returned an invalid response"
        case .unauthorized: return "Miraj session is unauthorized"
        case .nonSuccessStatus(let status): return "Miraj backend returned HTTP \(status)"
        case .unsupportedSchemaVersion(let version): return "Unsupported position schema_version \(version)"
        case .transportUnavailable: return "Miraj backend is unavailable"
        case .refreshInFlight: return "A refresh is already in flight"
        case .automaticRefreshThrottled(let remainingSeconds): return "Automatic refresh throttled for \(Int(ceil(remainingSeconds))) seconds"
        }
    }
}

public enum PositionLoadResult: Equatable {
    case loaded(PositionIntelligenceResponse)
    case offlineWithCache(PositionIntelligenceResponse, PositionClientError)
    case offlineWithoutCache(PositionClientError)
}

public enum PositionRefreshTrigger: Equatable {
    case automatic
    case manual
}

public final class PositionClient {
    public static let endpointPath = "/api/v1/desktop/position-intelligence"

    private let baseURL: URL
    private let session: URLSession
    private let tokenStore: PositionTokenStoring
    private let cache: PositionCache?
    private let decoder: JSONDecoder

    public init(
        baseURL: URL,
        session: URLSession = .shared,
        tokenStore: PositionTokenStoring,
        cache: PositionCache? = nil,
        decoder: JSONDecoder = .positionIntelligenceDecoder
    ) {
        self.baseURL = baseURL
        self.session = session
        self.tokenStore = tokenStore
        self.cache = cache
        self.decoder = decoder
    }

    public static func urlSession(timeout: TimeInterval = 8) -> URLSession {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.timeoutIntervalForRequest = timeout
        configuration.timeoutIntervalForResource = timeout
        configuration.waitsForConnectivity = false
        configuration.requestCachePolicy = .reloadIgnoringLocalCacheData
        return URLSession(configuration: configuration)
    }

    public func loadPosition(symbol: String? = nil) async -> PositionLoadResult {
        do {
            let response = try await fetchPosition(symbol: symbol)
            try? cache?.save(response)
            return .loaded(response)
        } catch let error as PositionClientError {
            return offlineResult(for: error)
        } catch let error as PositionContractError {
            if case .unsupportedSchemaVersion(let version) = error {
                return offlineResult(for: .unsupportedSchemaVersion(version))
            }
            return offlineResult(for: .invalidResponse)
        } catch {
            return offlineResult(for: .transportUnavailable)
        }
    }

    public func fetchPosition(symbol: String? = nil) async throws -> PositionIntelligenceResponse {
        guard let token = try tokenStore.readToken(), !token.isEmpty else {
            throw PositionClientError.notConnected
        }

        var request = try makeRequest(symbol: symbol)
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        request.setValue("application/json", forHTTPHeaderField: "Accept")

        let (data, response): (Data, URLResponse)
        do {
            (data, response) = try await session.data(for: request)
        } catch {
            throw PositionClientError.transportUnavailable
        }

        guard let httpResponse = response as? HTTPURLResponse else {
            throw PositionClientError.invalidResponse
        }

        guard httpResponse.statusCode == 200 else {
            if httpResponse.statusCode == 401 || httpResponse.statusCode == 403 {
                throw PositionClientError.unauthorized
            }
            throw PositionClientError.nonSuccessStatus(httpResponse.statusCode)
        }

        do {
            return try decoder.decode(PositionIntelligenceResponse.self, from: data)
        } catch let error as PositionContractError {
            if case .unsupportedSchemaVersion(let version) = error {
                throw PositionClientError.unsupportedSchemaVersion(version)
            }
            throw PositionClientError.invalidResponse
        } catch {
            throw PositionClientError.invalidResponse
        }
    }

    public func makeRequest(symbol: String? = nil) throws -> URLRequest {
        guard Self.isHTTPSBaseURL(baseURL) else {
            throw PositionClientError.invalidBaseURL
        }
        guard var components = URLComponents(url: baseURL.appendingPathComponent(Self.endpointPath), resolvingAgainstBaseURL: false) else {
            throw PositionClientError.invalidBaseURL
        }

        var queryItems = [URLQueryItem(name: "exchange", value: "mexc")]
        if let normalized = PositionPreferences.normalizedSymbol(symbol) {
            queryItems.append(URLQueryItem(name: "symbol", value: normalized))
        }
        components.queryItems = queryItems

        guard let url = components.url else {
            throw PositionClientError.invalidBaseURL
        }
        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        request.timeoutInterval = 8
        request.cachePolicy = .reloadIgnoringLocalCacheData
        return request
    }

    private static func isHTTPSBaseURL(_ url: URL) -> Bool {
        url.scheme?.lowercased() == "https" && url.host?.isEmpty == false
    }

    private func offlineResult(for error: PositionClientError) -> PositionLoadResult {
        switch cache?.offlineState() {
        case .offlineWithCache(let cached):
            return .offlineWithCache(cached, error)
        case .offlineWithoutCache, .none:
            return .offlineWithoutCache(error)
        }
    }
}

public protocol PositionRefreshing {
    func refresh(trigger: PositionRefreshTrigger, symbol: String?) async -> Result<PositionLoadResult, PositionClientError>
}

public actor PositionRefreshCoordinator: PositionRefreshing {
    public static let minimumAutomaticRefreshInterval: TimeInterval = 60

    private let client: PositionClient
    private let minimumAutomaticRefreshInterval: TimeInterval
    private let now: () -> Date
    private var lastAutomaticFetchAt: Date?
    private var refreshInFlight = false

    public init(
        client: PositionClient,
        minimumAutomaticRefreshInterval: TimeInterval = PositionRefreshCoordinator.minimumAutomaticRefreshInterval,
        now: @escaping () -> Date = Date.init
    ) {
        self.client = client
        self.minimumAutomaticRefreshInterval = minimumAutomaticRefreshInterval
        self.now = now
    }

    public var isInFlight: Bool { refreshInFlight }

    public func refresh(trigger: PositionRefreshTrigger, symbol: String? = nil) async -> Result<PositionLoadResult, PositionClientError> {
        if refreshInFlight { return .failure(.refreshInFlight) }

        if trigger == .automatic, let lastAutomaticFetchAt {
            let elapsed = now().timeIntervalSince(lastAutomaticFetchAt)
            if elapsed < minimumAutomaticRefreshInterval {
                return .failure(.automaticRefreshThrottled(remainingSeconds: minimumAutomaticRefreshInterval - elapsed))
            }
        }

        refreshInFlight = true
        defer { refreshInFlight = false }
        let result = await client.loadPosition(symbol: symbol)
        if trigger == .automatic {
            lastAutomaticFetchAt = now()
        }
        return .success(result)
    }
}
