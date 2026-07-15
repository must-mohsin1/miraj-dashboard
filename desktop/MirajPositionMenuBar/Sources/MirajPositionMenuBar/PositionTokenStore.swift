import Foundation
import Security

public protocol PositionTokenStoring {
    func readToken() throws -> String?
    func saveToken(_ token: String) throws
    func clearToken() throws
}

public enum PositionTokenStoreError: Error, Equatable, LocalizedError {
    case keychainReadFailed(OSStatus)
    case keychainWriteFailed(OSStatus)
    case keychainDeleteFailed(OSStatus)
    case invalidTokenEncoding

    public var errorDescription: String? {
        switch self {
        case .keychainReadFailed(let status): return "Keychain token read failed with status \(status)"
        case .keychainWriteFailed(let status): return "Keychain token write failed with status \(status)"
        case .keychainDeleteFailed(let status): return "Keychain token delete failed with status \(status)"
        case .invalidTokenEncoding: return "Miraj session token could not be encoded"
        }
    }
}

public final class PositionKeychainTokenStore: PositionTokenStoring {
    public static let defaultService = "pk.miraj.position-menubar.auth"
    public static let defaultAccount = "miraj-session-token"

    private let service: String
    private let account: String
    private let accessGroup: String?

    public init(
        service: String = PositionKeychainTokenStore.defaultService,
        account: String = PositionKeychainTokenStore.defaultAccount,
        accessGroup: String? = nil
    ) {
        self.service = service
        self.account = account
        self.accessGroup = accessGroup
    }

    public func readToken() throws -> String? {
        var query = baseQuery()
        query[kSecReturnData as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitOne

        var result: CFTypeRef?
        let status = SecItemCopyMatching(query as CFDictionary, &result)
        if status == errSecItemNotFound { return nil }
        guard status == errSecSuccess else {
            throw PositionTokenStoreError.keychainReadFailed(status)
        }
        guard let data = result as? Data, let token = String(data: data, encoding: .utf8) else {
            throw PositionTokenStoreError.invalidTokenEncoding
        }
        return token
    }

    public func saveToken(_ token: String) throws {
        guard let data = token.data(using: .utf8) else {
            throw PositionTokenStoreError.invalidTokenEncoding
        }

        let query = baseQuery()
        let updateAttributes: [String: Any] = [kSecValueData as String: data]
        let updateStatus = SecItemUpdate(query as CFDictionary, updateAttributes as CFDictionary)
        if updateStatus == errSecSuccess { return }
        if updateStatus != errSecItemNotFound {
            throw PositionTokenStoreError.keychainWriteFailed(updateStatus)
        }

        var addQuery = query
        addQuery[kSecValueData as String] = data
        addQuery[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        let addStatus = SecItemAdd(addQuery as CFDictionary, nil)
        guard addStatus == errSecSuccess else {
            throw PositionTokenStoreError.keychainWriteFailed(addStatus)
        }
    }

    public func clearToken() throws {
        let status = SecItemDelete(baseQuery() as CFDictionary)
        guard status == errSecSuccess || status == errSecItemNotFound else {
            throw PositionTokenStoreError.keychainDeleteFailed(status)
        }
    }

    private func baseQuery() -> [String: Any] {
        var query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account
        ]
        if let accessGroup, !accessGroup.isEmpty {
            query[kSecAttrAccessGroup as String] = accessGroup
        }
        return query
    }
}
