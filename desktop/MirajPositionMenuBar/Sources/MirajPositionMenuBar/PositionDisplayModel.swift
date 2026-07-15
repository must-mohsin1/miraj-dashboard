import Foundation

public enum PositionContractError: Error, Equatable, LocalizedError {
    case unsupportedSchemaVersion(Int)

    public var errorDescription: String? {
        switch self {
        case .unsupportedSchemaVersion(let version):
            return "Unsupported position schema_version \(version)"
        }
    }
}

public struct PositionIntelligenceResponse: Codable, Equatable {
    public let schemaVersion: Int
    public let exchange: String
    public let selectionReason: SelectionReason
    public let generatedAt: Date
    public let source: PositionSource
    public let position: PositionContract?
    public let privacy: PrivacyContract
    public let errors: [PositionError]

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case exchange
        case selectionReason = "selection_reason"
        case generatedAt = "generated_at"
        case source
        case position
        case privacy
        case errors
    }

    public init(
        schemaVersion: Int,
        exchange: String,
        selectionReason: SelectionReason,
        generatedAt: Date,
        source: PositionSource,
        position: PositionContract?,
        privacy: PrivacyContract,
        errors: [PositionError]
    ) throws {
        guard schemaVersion == 1 else { throw PositionContractError.unsupportedSchemaVersion(schemaVersion) }
        self.schemaVersion = schemaVersion
        self.exchange = exchange
        self.selectionReason = selectionReason
        self.generatedAt = generatedAt
        self.source = source
        self.position = position
        self.privacy = privacy
        self.errors = errors
    }

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        let schemaVersion = try container.decode(Int.self, forKey: .schemaVersion)
        guard schemaVersion == 1 else { throw PositionContractError.unsupportedSchemaVersion(schemaVersion) }
        self.schemaVersion = schemaVersion
        self.exchange = try container.decode(String.self, forKey: .exchange)
        self.selectionReason = try container.decode(SelectionReason.self, forKey: .selectionReason)
        self.generatedAt = try container.decode(Date.self, forKey: .generatedAt)
        self.source = try container.decode(PositionSource.self, forKey: .source)
        self.position = try container.decodeIfPresent(PositionContract.self, forKey: .position)
        self.privacy = try container.decode(PrivacyContract.self, forKey: .privacy)
        self.errors = try container.decode([PositionError].self, forKey: .errors)
    }

    public func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(schemaVersion, forKey: .schemaVersion)
        try container.encode(exchange, forKey: .exchange)
        try container.encode(selectionReason, forKey: .selectionReason)
        try container.encode(generatedAt, forKey: .generatedAt)
        try container.encode(source, forKey: .source)
        try container.encodeIfPresent(position, forKey: .position)
        try container.encode(privacy, forKey: .privacy)
        try container.encode(errors, forKey: .errors)
    }
}

public enum SelectionReason: String, Codable, Equatable {
    case userSelected = "user_selected"
    case selectedPositionClosedDefaulted = "selected_position_closed_defaulted"
    case noUserSelectionDefaulted = "no_user_selection_defaulted"
    case noOpenPositions = "no_open_positions"
}

public struct PositionSource: Codable, Equatable {
    public let portfolioLastRefreshed: Date?
    public let markPriceSource: String
    public let markPriceLastRefreshed: Date?
    public let pnlAgeSeconds: Double?
    public let staleStatus: StaleStatus

    enum CodingKeys: String, CodingKey {
        case portfolioLastRefreshed = "portfolio_last_refreshed"
        case markPriceSource = "mark_price_source"
        case markPriceLastRefreshed = "mark_price_last_refreshed"
        case pnlAgeSeconds = "pnl_age_seconds"
        case staleStatus = "stale_status"
    }
}

public enum StaleStatus: String, Codable, Equatable {
    case fresh
    case stale
    case criticalStale = "critical_stale"
    case offline
}

public struct PrivacyContract: Codable, Equatable {
    public let hideAmountsAvailable: Bool
    public let redactionSupported: Bool

    enum CodingKeys: String, CodingKey {
        case hideAmountsAvailable = "hide_amounts_available"
        case redactionSupported = "redaction_supported"
    }
}

public struct PositionError: Codable, Equatable {
    public let code: String
    public let message: String?
}

public struct PositionContract: Codable, Equatable {
    public let symbol: String
    public let side: PositionSide
    public let sizeContracts: Double
    public let contractSize: Double
    public let entryPrice: Double
    public let markPrice: Double
    public let pnl: Double
    public let pnlPercent: Double
    public let pnlFormula: PnLFormula
    public let margin: Double?
    public let leverage: Double
    public let liquidationPrice: Double?
    public let liquidationDistancePct: Double?
    public let htfSR: SupportResistanceBlock
    public let ltfSR: SupportResistanceBlock
    public let advisory: PositionAdvisory
    public let dashboardDeeplink: String

    enum CodingKeys: String, CodingKey {
        case symbol
        case side
        case sizeContracts = "size_contracts"
        case contractSize = "contract_size"
        case entryPrice = "entry_price"
        case markPrice = "mark_price"
        case pnl
        case pnlPercent = "pnl_percent"
        case pnlFormula = "pnl_formula"
        case margin
        case leverage
        case liquidationPrice = "liquidation_price"
        case liquidationDistancePct = "liquidation_distance_pct"
        case htfSR = "htf_sr"
        case ltfSR = "ltf_sr"
        case advisory
        case dashboardDeeplink = "dashboard_deeplink"
    }
}

public enum PositionSide: String, Codable, Equatable {
    case long = "LONG"
    case short = "SHORT"
}

public enum PnLFormula: String, Codable, Equatable {
    case exchangeUnrealizedPnL = "exchange_unrealized_pnl"
    case computedContractsContractSize = "computed_contracts_contract_size"
}

public struct SupportResistanceBlock: Codable, Equatable {
    public let timeframes: [String]
    public let support: SupportResistanceLevel?
    public let resistance: SupportResistanceLevel?
    public let structureLabel: String
    public let confidence: SupportResistanceConfidence

    enum CodingKeys: String, CodingKey {
        case timeframes
        case support
        case resistance
        case structureLabel = "structure_label"
        case confidence
    }
}

public enum SupportResistanceConfidence: String, Codable, Equatable {
    case high = "HIGH"
    case low = "LOW"
    case unavailable = "UNAVAILABLE"
}

public struct SupportResistanceLevel: Codable, Equatable {
    public let price: Double
    public let distancePct: Double
    public let timeframe: String
    public let swingType: String
    public let swingIndex: Int
    public let method: String

    enum CodingKeys: String, CodingKey {
        case price
        case distancePct = "distance_pct"
        case timeframe
        case swingType = "swing_type"
        case swingIndex = "swing_index"
        case method
    }
}

public struct PositionAdvisory: Codable, Equatable {
    public let action: AdvisoryAction
    public let severity: AdvisorySeverity
    public let reason: String
    public let source: AdvisorySource
    public let actionItemsCount: Int

    enum CodingKeys: String, CodingKey {
        case action
        case severity
        case reason
        case source
        case actionItemsCount = "action_items_count"
    }
}

public enum AdvisoryAction: String, Codable, Equatable {
    case hold = "HOLD"
    case reduce = "REDUCE"
    case close = "CLOSE"
    case wait = "WAIT"
}

public enum AdvisorySeverity: String, Codable, Equatable {
    case info = "INFO"
    case warning = "WARNING"
    case danger = "DANGER"
}

public enum AdvisorySource: String, Codable, Equatable {
    case dca
    case positionAlert = "position_alert"
    case combined
    case fallback
}

public enum PnLSemanticState: String, Equatable {
    case positiveGreen
    case negativeRed
    case neutral
}

public enum PositionDisplayState: String, Equatable {
    case fresh
    case stale
    case criticalStale
    case offlineWithCache
    case offlineWithoutCache
    case noOpenPositions
    case notConnected
    case unsupportedSchema
}

public struct PositionDisplayOptions: Equatable {
    public let hideAmounts: Bool
    public let redactMenuBar: Bool
    public let fullPopoverRedaction: Bool

    public init(hideAmounts: Bool = false, redactMenuBar: Bool = false, fullPopoverRedaction: Bool = false) {
        self.hideAmounts = hideAmounts
        self.redactMenuBar = redactMenuBar
        self.fullPopoverRedaction = fullPopoverRedaction
    }
}

public struct PositionDisplayModel: Equatable {
    public static let mask = "•••"

    public let state: PositionDisplayState
    public let menuBarLabel: String
    public let title: String
    public let subtitle: String?
    public let badge: String
    public let body: String?
    public let detail: String?
    public let rows: [String]
    public let advisoryLine: String?
    public let timestampLine: String?
    public let warningLine: String?
    public let footerActions: [String]
    public let pnlSemanticState: PnLSemanticState

    public init(response: PositionIntelligenceResponse, options: PositionDisplayOptions = PositionDisplayOptions()) {
        let hasAuthError = response.errors.contains { $0.code == "auth_required" || $0.code == "not_connected" || $0.code == "unauthorized" }
        if hasAuthError {
            self = PositionDisplayModel.notConnected(redactMenuBar: options.redactMenuBar)
            return
        }

        guard let position = response.position else {
            self.state = .noOpenPositions
            self.menuBarLabel = options.redactMenuBar ? "Miraj" : "Miraj"
            self.title = "Miraj Position"
            self.subtitle = nil
            self.badge = response.source.staleStatus == .fresh ? "Fresh" : "Stale"
            self.body = "No open positions"
            self.detail = response.source.portfolioLastRefreshed.map { "Last checked \(Self.relativeTime(for: $0, now: response.generatedAt))" }
            self.rows = []
            self.advisoryLine = nil
            self.timestampLine = nil
            self.warningLine = nil
            self.footerActions = ["Open Miraj", "Refresh"]
            self.pnlSemanticState = .neutral
            return
        }

        let age = response.source.pnlAgeSeconds ?? 0
        let critical = age > 900 || response.source.staleStatus == .criticalStale
        let offline = response.source.staleStatus == .offline || response.errors.contains { $0.code == "offline_cached_response" }
        let stale = critical || offline || age > 120 || response.source.staleStatus == .stale
        let displayState: PositionDisplayState = offline ? .offlineWithCache : (critical ? .criticalStale : (stale ? .stale : .fresh))
        let pnlSemantic = Self.semanticState(for: position.pnl)

        self.state = displayState
        self.menuBarLabel = Self.menuBarLabel(for: position, state: displayState, redact: options.redactMenuBar)
        self.title = position.symbol
        self.subtitle = "\(response.exchange) · \(position.side.rawValue)"
        self.badge = offline ? "Offline" : (stale ? "Stale" : "Fresh")
        self.body = options.fullPopoverRedaction ? "Open Miraj to view position details" : nil
        self.detail = nil
        self.rows = options.fullPopoverRedaction ? [] : Self.rows(for: position, hideAmounts: options.hideAmounts)
        self.advisoryLine = Self.advisoryLine(for: position.advisory, state: displayState, hideAmounts: options.hideAmounts, fullPopoverRedaction: options.fullPopoverRedaction)
        self.timestampLine = Self.timestampLine(for: displayState, response: response)
        self.warningLine = Self.warningLine(for: displayState)
        self.footerActions = ["Open Miraj", "Refresh"]
        self.pnlSemanticState = pnlSemantic
    }

    public static func notConnected(redactMenuBar: Bool = false) -> PositionDisplayModel {
        PositionDisplayModel(
            state: .notConnected,
            menuBarLabel: redactMenuBar ? "Miraj" : "Miraj · Connect",
            title: "Miraj Position",
            subtitle: nil,
            badge: "Not connected",
            body: "Connect to Miraj to view your position.",
            detail: nil,
            rows: [],
            advisoryLine: nil,
            timestampLine: nil,
            warningLine: nil,
            footerActions: ["Connect"],
            pnlSemanticState: .neutral
        )
    }

    public static func offlineWithoutCache(redactMenuBar: Bool = false) -> PositionDisplayModel {
        PositionDisplayModel(
            state: .offlineWithoutCache,
            menuBarLabel: redactMenuBar ? "Miraj" : "Miraj · Offline",
            title: "Miraj Position",
            subtitle: nil,
            badge: "Offline",
            body: "Unable to load position",
            detail: "Check your connection, then refresh.",
            rows: [],
            advisoryLine: nil,
            timestampLine: nil,
            warningLine: nil,
            footerActions: ["Refresh"],
            pnlSemanticState: .neutral
        )
    }

    private init(
        state: PositionDisplayState,
        menuBarLabel: String,
        title: String,
        subtitle: String?,
        badge: String,
        body: String?,
        detail: String?,
        rows: [String],
        advisoryLine: String?,
        timestampLine: String?,
        warningLine: String?,
        footerActions: [String],
        pnlSemanticState: PnLSemanticState
    ) {
        self.state = state
        self.menuBarLabel = menuBarLabel
        self.title = title
        self.subtitle = subtitle
        self.badge = badge
        self.body = body
        self.detail = detail
        self.rows = rows
        self.advisoryLine = advisoryLine
        self.timestampLine = timestampLine
        self.warningLine = warningLine
        self.footerActions = footerActions
        self.pnlSemanticState = pnlSemanticState
    }

    public var allDisplayStrings: [String] {
        [menuBarLabel, title, subtitle, badge, body, detail, warningLine, advisoryLine, timestampLine].compactMap { $0 } + rows + footerActions
    }

    public static func decodeResponse(from data: Data) throws -> PositionIntelligenceResponse {
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        return try decoder.decode(PositionIntelligenceResponse.self, from: data)
    }

    private static func menuBarLabel(for position: PositionContract, state: PositionDisplayState, redact: Bool) -> String {
        if redact { return "Miraj" }
        switch state {
        case .fresh:
            return "Miraj \(formatPercent(position.pnlPercent, signed: true))"
        case .stale, .criticalStale:
            return "Miraj · Stale"
        case .offlineWithCache, .offlineWithoutCache:
            return "Miraj · Offline"
        case .notConnected:
            return "Miraj · Connect"
        case .noOpenPositions, .unsupportedSchema:
            return "Miraj"
        }
    }

    private static func rows(for position: PositionContract, hideAmounts: Bool) -> [String] {
        let mask = PositionDisplayModel.mask
        let size = hideAmounts ? mask : formatNumber(position.sizeContracts)
        let entry = hideAmounts ? mask : formatPrice(position.entryPrice)
        let mark = hideAmounts ? mask : formatPrice(position.markPrice)
        let pnl = hideAmounts ? mask : formatCurrency(position.pnl)
        let risk: String
        if position.liquidationDistancePct == nil {
            risk = "Liq: n/a"
        } else {
            risk = "Liq distance \(hideAmounts ? mask : formatPercent(position.liquidationDistancePct ?? 0, signed: false))"
        }

        return [
            "Size \(size) contracts · \(formatNumber(position.leverage))x",
            "Entry \(entry) · Mark \(mark)",
            "PnL \(pnl) (\(formatPercent(position.pnlPercent, signed: true)))",
            risk,
            supportResistanceLine(prefix: "HTF", block: position.htfSR, hideAmounts: hideAmounts),
            supportResistanceLine(prefix: "LTF", block: position.ltfSR, hideAmounts: hideAmounts)
        ]
    }

    private static func supportResistanceLine(prefix: String, block: SupportResistanceBlock, hideAmounts: Bool) -> String {
        guard block.confidence != .unavailable else { return "\(prefix): insufficient swings" }
        guard block.support != nil || block.resistance != nil else { return "\(prefix): insufficient swings" }
        if hideAmounts { return "\(prefix): support/resistance hidden" }
        let support = block.support.map { formatPrice($0.price) } ?? "n/a"
        let resistance = block.resistance.map { formatPrice($0.price) } ?? "n/a"
        return "\(prefix): S \(support) · R \(resistance)"
    }

    private static func advisoryLine(for advisory: PositionAdvisory, state: PositionDisplayState, hideAmounts: Bool, fullPopoverRedaction: Bool) -> String {
        switch state {
        case .criticalStale:
            return "Advisory: WAIT — Open Miraj to refresh before acting"
        case .offlineWithCache:
            return "Advisory: WAIT — Reconnect before changing the position"
        default:
            if fullPopoverRedaction || hideAmounts {
                return "Advisory: \(advisory.action.rawValue)"
            }
            return "Advisory: \(advisory.action.rawValue) — \(advisory.reason)"
        }
    }

    private static func timestampLine(for state: PositionDisplayState, response: PositionIntelligenceResponse) -> String? {
        let timestamp = response.source.markPriceLastRefreshed ?? response.source.portfolioLastRefreshed ?? response.generatedAt
        let relative = relativeTime(for: timestamp, now: response.generatedAt)
        switch state {
        case .fresh:
            return "Updated \(relative)"
        case .stale, .criticalStale:
            return "Stale: \(relative)"
        case .offlineWithCache:
            return "Offline — last known \(relative)"
        default:
            return nil
        }
    }

    private static func warningLine(for state: PositionDisplayState) -> String? {
        switch state {
        case .stale:
            return "Data may be out of date. Open Miraj before acting."
        case .criticalStale:
            return "Open Miraj to refresh before acting"
        case .offlineWithCache:
            return "Offline — showing last known position."
        default:
            return nil
        }
    }

    private static func semanticState(for pnl: Double) -> PnLSemanticState {
        if pnl > 0 { return .positiveGreen }
        if pnl < 0 { return .negativeRed }
        return .neutral
    }

    private static func relativeTime(for timestamp: Date, now: Date) -> String {
        let seconds = max(0, Int(now.timeIntervalSince(timestamp).rounded()))
        if seconds < 60 { return seconds == 1 ? "1 second ago" : "\(seconds) seconds ago" }
        let minutes = seconds / 60
        if minutes < 60 { return minutes == 1 ? "1 minute ago" : "\(minutes) minutes ago" }
        let hours = minutes / 60
        if hours < 24 { return hours == 1 ? "1 hour ago" : "\(hours) hours ago" }
        let days = hours / 24
        return days == 1 ? "1 day ago" : "\(days) days ago"
    }

    private static func formatCurrency(_ value: Double) -> String {
        let sign = value > 0 ? "+" : ""
        return "\(sign)$\(formatNumber(value))"
    }

    private static func formatPercent(_ value: Double, signed: Bool) -> String {
        let sign = signed && value > 0 ? "+" : ""
        return "\(sign)\(formatNumber(value))%"
    }

    private static func formatPrice(_ value: Double) -> String {
        "$\(formatNumber(value))"
    }

    private static func formatNumber(_ value: Double) -> String {
        if value.rounded() == value {
            return String(format: "%.0f", value)
        }
        return String(format: "%.2f", value)
    }
}
