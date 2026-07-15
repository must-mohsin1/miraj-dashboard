import Foundation

public enum PositionCacheError: Error, Equatable, LocalizedError {
    case unsupportedSchemaVersion(Int)
    case invalidSnapshotLocation

    public var errorDescription: String? {
        switch self {
        case .unsupportedSchemaVersion(let version): return "Unsupported cached position schema_version \(version)"
        case .invalidSnapshotLocation: return "Unable to create local position cache location"
        }
    }
}

public enum PositionOfflineState: Equatable {
    case offlineWithCache(PositionIntelligenceResponse)
    case offlineWithoutCache
}

public final class PositionCache {
    public static let snapshotFileName = "display-snapshot-v1.json"

    private let fileURL: URL
    private let fileManager: FileManager
    private let decoder: JSONDecoder
    private let encoder: JSONEncoder

    public init(
        fileURL: URL,
        fileManager: FileManager = .default,
        decoder: JSONDecoder = .positionIntelligenceDecoder,
        encoder: JSONEncoder = .positionIntelligenceEncoder
    ) {
        self.fileURL = fileURL
        self.fileManager = fileManager
        self.decoder = decoder
        self.encoder = encoder
    }

    public convenience init(directoryURL: URL, fileManager: FileManager = .default) throws {
        try fileManager.createDirectory(at: directoryURL, withIntermediateDirectories: true)
        self.init(fileURL: directoryURL.appendingPathComponent(PositionCache.snapshotFileName), fileManager: fileManager)
    }

    public convenience init(applicationSupportSubdirectory: String = "MirajPosition", fileManager: FileManager = .default) throws {
        guard let baseURL = fileManager.urls(for: .applicationSupportDirectory, in: .userDomainMask).first else {
            throw PositionCacheError.invalidSnapshotLocation
        }
        try self.init(directoryURL: baseURL.appendingPathComponent(applicationSupportSubdirectory, isDirectory: true), fileManager: fileManager)
    }

    public func save(_ response: PositionIntelligenceResponse) throws {
        guard response.schemaVersion == 1 else {
            throw PositionCacheError.unsupportedSchemaVersion(response.schemaVersion)
        }
        let data = try encoder.encode(response)
        try fileManager.createDirectory(at: fileURL.deletingLastPathComponent(), withIntermediateDirectories: true)
        try data.write(to: fileURL, options: [.atomic, .completeFileProtection])
    }

    public func load() throws -> PositionIntelligenceResponse? {
        guard fileManager.fileExists(atPath: fileURL.path) else { return nil }
        let data = try Data(contentsOf: fileURL)
        let response = try decoder.decode(PositionIntelligenceResponse.self, from: data)
        guard response.schemaVersion == 1 else {
            throw PositionCacheError.unsupportedSchemaVersion(response.schemaVersion)
        }
        return response
    }

    public func clear() throws {
        guard fileManager.fileExists(atPath: fileURL.path) else { return }
        try fileManager.removeItem(at: fileURL)
    }

    public func offlineState() -> PositionOfflineState {
        if let cached = try? load() {
            return .offlineWithCache(cached)
        }
        return .offlineWithoutCache
    }
}

public extension JSONDecoder {
    static var positionIntelligenceDecoder: JSONDecoder {
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        return decoder
    }
}

public extension JSONEncoder {
    static var positionIntelligenceEncoder: JSONEncoder {
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        encoder.outputFormatting = [.sortedKeys]
        return encoder
    }
}
