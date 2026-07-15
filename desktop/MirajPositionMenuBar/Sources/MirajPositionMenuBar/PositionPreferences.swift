import Foundation

public enum PositionRefreshPreference: String, Codable, Equatable {
    case automatic
    case manualOnly
}

public enum PositionRuntimeMode: String, Codable, Equatable {
    case mockFixtures
    case connected
}

public struct PositionPreferences: Equatable {
    public var selectedSymbol: String?
    public var hideAmounts: Bool
    public var redactMenuBar: Bool
    public var debugAPIBaseURL: URL
    public var refreshPreference: PositionRefreshPreference
    public var runtimeMode: PositionRuntimeMode

    public init(
        selectedSymbol: String? = nil,
        hideAmounts: Bool = false,
        redactMenuBar: Bool = false,
        debugAPIBaseURL: URL = PositionPreferencesStore.defaultAPIBaseURL,
        refreshPreference: PositionRefreshPreference = .manualOnly,
        runtimeMode: PositionRuntimeMode = .mockFixtures
    ) {
        self.selectedSymbol = Self.normalizedSymbol(selectedSymbol)
        self.hideAmounts = hideAmounts
        self.redactMenuBar = redactMenuBar
        self.debugAPIBaseURL = debugAPIBaseURL
        self.refreshPreference = refreshPreference
        self.runtimeMode = runtimeMode
    }

    public static func normalizedSymbol(_ symbol: String?) -> String? {
        guard let symbol else { return nil }
        let trimmed = symbol.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty ? nil : trimmed.uppercased()
    }
}

public final class PositionPreferencesStore {
    public static let defaultAPIBaseURL = URL(string: "https://localhost.invalid")!

    public static let selectedSymbolKey = "miraj.positionMenuBar.selectedSymbol"
    public static let hideAmountsKey = "miraj.positionMenuBar.hideAmounts"
    public static let redactMenuBarKey = "miraj.positionMenuBar.redactMenuBar"
    public static let debugAPIBaseURLKey = "miraj.positionMenuBar.debugAPIBaseURL"
    public static let refreshPreferenceKey = "miraj.positionMenuBar.refreshPreference"
    public static let runtimeModeKey = "miraj.positionMenuBar.runtimeMode"

    private let defaults: UserDefaults

    public init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
    }

    public var selectedSymbol: String? {
        get { PositionPreferences.normalizedSymbol(defaults.string(forKey: Self.selectedSymbolKey)) }
        set {
            if let normalized = PositionPreferences.normalizedSymbol(newValue) {
                defaults.set(normalized, forKey: Self.selectedSymbolKey)
            } else {
                defaults.removeObject(forKey: Self.selectedSymbolKey)
            }
        }
    }

    public var hideAmounts: Bool {
        get { defaults.bool(forKey: Self.hideAmountsKey) }
        set { defaults.set(newValue, forKey: Self.hideAmountsKey) }
    }

    public var redactMenuBar: Bool {
        get { defaults.bool(forKey: Self.redactMenuBarKey) }
        set { defaults.set(newValue, forKey: Self.redactMenuBarKey) }
    }

    public var debugAPIBaseURL: URL {
        get {
            guard
                let stored = defaults.string(forKey: Self.debugAPIBaseURLKey),
                let url = URL(string: stored),
                Self.isHTTPSURL(url)
            else { return Self.defaultAPIBaseURL }
            return url
        }
        set {
            guard Self.isHTTPSURL(newValue) else { return }
            defaults.set(newValue.absoluteString.trimmedTrailingSlash(), forKey: Self.debugAPIBaseURLKey)
        }
    }

    public var refreshPreference: PositionRefreshPreference {
        get {
            guard
                let raw = defaults.string(forKey: Self.refreshPreferenceKey),
                let value = PositionRefreshPreference(rawValue: raw)
            else { return .manualOnly }
            return value
        }
        set { defaults.set(newValue.rawValue, forKey: Self.refreshPreferenceKey) }
    }

    public var runtimeMode: PositionRuntimeMode {
        get {
            guard
                let raw = defaults.string(forKey: Self.runtimeModeKey),
                let value = PositionRuntimeMode(rawValue: raw)
            else { return .mockFixtures }
            return value
        }
        set { defaults.set(newValue.rawValue, forKey: Self.runtimeModeKey) }
    }

    public func load() -> PositionPreferences {
        PositionPreferences(
            selectedSymbol: selectedSymbol,
            hideAmounts: hideAmounts,
            redactMenuBar: redactMenuBar,
            debugAPIBaseURL: debugAPIBaseURL,
            refreshPreference: refreshPreference,
            runtimeMode: runtimeMode
        )
    }

    public func save(_ preferences: PositionPreferences) {
        selectedSymbol = preferences.selectedSymbol
        hideAmounts = preferences.hideAmounts
        redactMenuBar = preferences.redactMenuBar
        debugAPIBaseURL = preferences.debugAPIBaseURL
        refreshPreference = preferences.refreshPreference
        runtimeMode = preferences.runtimeMode
    }

    private static func isHTTPSURL(_ url: URL) -> Bool {
        url.scheme?.lowercased() == "https" && url.host?.isEmpty == false
    }
}

public protocol PositionPreferencesLoading {
    func load() -> PositionPreferences
}

extension PositionPreferencesStore: PositionPreferencesLoading {}

private extension String {
    func trimmedTrailingSlash() -> String {
        guard count > 1, hasSuffix("/") else { return self }
        return String(dropLast())
    }
}
