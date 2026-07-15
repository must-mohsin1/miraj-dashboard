import Foundation

public final class MockFixturePositionProvider: PositionRefreshing {
    public static let fixtureNames = [
        "position_fresh_long.json",
        "position_stale_short_contract_size.json",
        "no_open_positions.json",
        "not_connected.json",
        "offline_with_cache.json",
        "critical_stale.json"
    ]

    private let fixtureName: String
    private let fixtureDirectory: URL?
    private let decoder: JSONDecoder

    public init(
        fixtureName: String = MockFixturePositionProvider.defaultFixtureName,
        fixtureDirectory: URL? = nil,
        decoder: JSONDecoder = .positionIntelligenceDecoder
    ) {
        self.fixtureName = Self.normalizedFixtureName(fixtureName) ?? Self.defaultFixtureName
        self.fixtureDirectory = fixtureDirectory
        self.decoder = decoder
    }

    public func refresh(trigger: PositionRefreshTrigger, symbol: String?) async -> Result<PositionLoadResult, PositionClientError> {
        do {
            let response = try loadFixture(named: symbol.flatMap(Self.normalizedFixtureName) ?? fixtureName)
            return .success(.loaded(response))
        } catch let error as PositionContractError {
            if case .unsupportedSchemaVersion(let version) = error {
                return .success(.offlineWithoutCache(.unsupportedSchemaVersion(version)))
            }
            return .success(.offlineWithoutCache(.invalidResponse))
        } catch {
            return .success(.offlineWithoutCache(.invalidResponse))
        }
    }

    public static var defaultFixtureName: String { "position_fresh_long.json" }

    public static func fixtureName(from processInfo: ProcessInfo = .processInfo) -> String {
        if let fixture = processInfo.environment["MIRAJ_POSITION_FIXTURE"], let normalized = normalizedFixtureName(fixture) {
            return normalized
        }

        for argument in processInfo.arguments {
            if argument.hasPrefix("--miraj-position-fixture="),
               let normalized = normalizedFixtureName(String(argument.dropFirst("--miraj-position-fixture=".count))) {
                return normalized
            }
        }

        return defaultFixtureName
    }

    public static func fixtureDirectory(from processInfo: ProcessInfo = .processInfo) -> URL? {
        guard let path = processInfo.environment["MIRAJ_POSITION_FIXTURE_DIR"], !path.isEmpty else { return nil }
        return URL(fileURLWithPath: path, isDirectory: true)
    }

    public static func normalizedFixtureName(_ value: String) -> String? {
        let candidate = value.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !candidate.isEmpty else { return nil }
        let fileName = candidate.hasSuffix(".json") ? candidate : "\(candidate).json"
        return fixtureNames.contains(fileName) ? fileName : nil
    }

    private func loadFixture(named name: String) throws -> PositionIntelligenceResponse {
        let data = try Data(contentsOf: fixtureURL(named: name))
        return try decoder.decode(PositionIntelligenceResponse.self, from: data)
    }

    private func fixtureURL(named name: String) throws -> URL {
        var directories = [URL]()
        if let fixtureDirectory { directories.append(fixtureDirectory) }
        if let envDirectory = Self.fixtureDirectory() { directories.append(envDirectory) }

        #if SWIFT_PACKAGE
        directories.append(Bundle.module.resourceURL?.appendingPathComponent("MockFixtures", isDirectory: true) ?? Bundle.module.bundleURL.appendingPathComponent("MockFixtures", isDirectory: true))
        #endif

        if let resourceURL = Bundle.main.resourceURL {
            directories.append(resourceURL.appendingPathComponent("MockFixtures", isDirectory: true))
            directories.append(resourceURL)
        }

        directories.append(URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .appendingPathComponent("MockFixtures", isDirectory: true))

        for directory in directories {
            let url = directory.appendingPathComponent(name)
            if FileManager.default.fileExists(atPath: url.path) {
                return url
            }
        }

        throw PositionClientError.invalidResponse
    }
}
