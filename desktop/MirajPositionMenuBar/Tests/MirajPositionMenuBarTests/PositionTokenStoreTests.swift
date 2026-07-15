import Foundation

#if canImport(MirajPositionMenuBar)
@testable import MirajPositionMenuBar
#endif

@main
struct PositionTokenStoreTestRunner {
    static func main() throws {
        let tests = PositionTokenStoreTests()
        try tests.testPreferencesPersistOnlyNonSecretValues()
        try tests.testPreferencesRejectInvalidURLsAndNormalizeSelectedSymbol()
        try tests.testSessionTokenIsSavedOnlyThroughTokenStoreNotUserDefaults()
        try tests.testKeychainTokenStoreSourceUsesSecurityAPIsOnly()
        try tests.testScopedPreferenceAndTokenFilesDoNotContainForbiddenCredentialExamples()
        print("PositionTokenStoreTests: 5 passed")
    }
}

final class PositionTokenStoreTests {
    func testPreferencesPersistOnlyNonSecretValues() throws {
        let defaults = try isolatedDefaults()
        defer { defaults.removePersistentDomain(forName: defaultsSuiteName) }
        let store = PositionPreferencesStore(defaults: defaults)

        store.save(PositionPreferences(
            selectedSymbol: " btc/usdt:usdt ",
            hideAmounts: true,
            redactMenuBar: true,
            debugAPIBaseURL: URL(string: "https://ta.munafaplus.pk/")!,
            refreshPreference: .manualOnly
        ))

        try assertEqual(store.selectedSymbol, "BTC/USDT:USDT")
        try assertEqual(store.hideAmounts, true)
        try assertEqual(store.redactMenuBar, true)
        try assertEqual(store.debugAPIBaseURL.absoluteString, "https://ta.munafaplus.pk")
        try assertEqual(store.refreshPreference, .manualOnly)

        let persisted = defaults.dictionaryRepresentation()
        try assertEqual(persisted[PositionPreferencesStore.selectedSymbolKey] as? String, "BTC/USDT:USDT")
        try assertEqual(persisted[PositionPreferencesStore.hideAmountsKey] as? Bool, true)
        try assertEqual(persisted[PositionPreferencesStore.redactMenuBarKey] as? Bool, true)
        try assertEqual(persisted[PositionPreferencesStore.refreshPreferenceKey] as? String, "manualOnly")
        try assert(!persisted.keys.contains { $0.localizedCaseInsensitiveContains("token") })
        try assert(!persisted.keys.contains { $0.localizedCaseInsensitiveContains("jwt") })
        try assert(!persisted.keys.contains { $0.localizedCaseInsensitiveContains("cookie") })
        try assert(!persisted.keys.contains { $0.localizedCaseInsensitiveContains("secret") })
    }

    func testPreferencesRejectInvalidURLsAndNormalizeSelectedSymbol() throws {
        let defaults = try isolatedDefaults()
        defer { defaults.removePersistentDomain(forName: defaultsSuiteName) }
        let store = PositionPreferencesStore(defaults: defaults)

        store.debugAPIBaseURL = URL(string: "http://example.invalid")!
        try assertEqual(store.debugAPIBaseURL, PositionPreferencesStore.defaultAPIBaseURL)
        try assert(defaults.string(forKey: PositionPreferencesStore.debugAPIBaseURLKey) == nil, "HTTP backend URL must not be persisted")

        defaults.set("file:///tmp/private", forKey: PositionPreferencesStore.debugAPIBaseURLKey)
        try assertEqual(store.debugAPIBaseURL, PositionPreferencesStore.defaultAPIBaseURL)

        store.selectedSymbol = "  eth/usdt:usdt  "
        try assertEqual(store.selectedSymbol, "ETH/USDT:USDT")
        store.selectedSymbol = "   "
        try assert(store.selectedSymbol == nil)
    }

    func testSessionTokenIsSavedOnlyThroughTokenStoreNotUserDefaults() throws {
        let defaults = try isolatedDefaults()
        defer { defaults.removePersistentDomain(forName: defaultsSuiteName) }
        let preferences = PositionPreferencesStore(defaults: defaults)
        let tokenStore = MemoryTokenStore()
        let token = "session-token-never-defaults"

        try tokenStore.saveToken(token)
        preferences.save(PositionPreferences(
            selectedSymbol: "SOLUSDT",
            hideAmounts: false,
            redactMenuBar: false,
            debugAPIBaseURL: URL(string: "https://ta.munafaplus.pk")!,
            refreshPreference: .automatic
        ))

        try assertEqual(try tokenStore.readToken(), token)
        let persistedText = defaults.dictionaryRepresentation().description
        try assert(!persistedText.contains(token), "session token must not be stored in UserDefaults")
        try assert(!persistedText.localizedCaseInsensitiveContains("authorization"))
        try assert(!persistedText.localizedCaseInsensitiveContains("cookie"))
    }

    func testKeychainTokenStoreSourceUsesSecurityAPIsOnly() throws {
        let source = try sourceText("desktop/MirajPositionMenuBar/Sources/MirajPositionMenuBar/PositionTokenStore.swift")
        try assert(source.contains("import Security"))
        try assert(source.contains("SecItemCopyMatching"))
        try assert(source.contains("SecItemAdd"))
        try assert(source.contains("SecItemUpdate"))
        try assert(source.contains("SecItemDelete"))
        try assert(source.contains("kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly"))
        try assert(!source.contains("UserDefaults"))
        try assert(!source.contains("FileManager.default"))
        try assert(!source.contains("write(to:"))
    }

    func testScopedPreferenceAndTokenFilesDoNotContainForbiddenCredentialExamples() throws {
        let files = [
            "desktop/MirajPositionMenuBar/Sources/MirajPositionMenuBar/PositionTokenStore.swift",
            "desktop/MirajPositionMenuBar/Sources/MirajPositionMenuBar/PositionPreferences.swift",
            "desktop/MirajPositionMenuBar/Tests/MirajPositionMenuBarTests/PositionTokenStoreTests.swift"
        ]
        let forbiddenPatterns = [
            #"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"#,
            #"(?i)mexc[_ -]?(api|secret)\s*[:=]\s*[\"'][^\"']+[\"']"#,
            #"(?i)exchange[_ -]?key\s*[:=]\s*[\"'][^\"']+[\"']"#,
            #"(?i)(cookie|set-cookie)\s*[:=]"#,
            #"-----BEGIN [A-Z ]*PRIVATE KEY-----"#
        ]

        for file in files {
            let text = try sourceText(file)
            for pattern in forbiddenPatterns {
                try assert(text.range(of: pattern, options: [.regularExpression]) == nil, "\(file) matched forbidden pattern \(pattern)")
            }
        }
    }

    private var defaultsSuiteName: String { "PositionTokenStoreTests" }

    private func isolatedDefaults() throws -> UserDefaults {
        guard let defaults = UserDefaults(suiteName: defaultsSuiteName) else {
            throw TestFailure.failed("could not create isolated defaults suite")
        }
        defaults.removePersistentDomain(forName: defaultsSuiteName)
        return defaults
    }

    private func sourceText(_ relativePath: String) throws -> String {
        try String(contentsOf: URL(fileURLWithPath: FileManager.default.currentDirectoryPath).appendingPathComponent(relativePath), encoding: .utf8)
    }
}

private final class MemoryTokenStore: PositionTokenStoring {
    private var token: String?

    func readToken() throws -> String? { token }
    func saveToken(_ token: String) throws { self.token = token }
    func clearToken() throws { token = nil }
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
