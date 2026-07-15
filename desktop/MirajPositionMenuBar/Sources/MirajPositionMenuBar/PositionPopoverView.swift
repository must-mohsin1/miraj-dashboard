import SwiftUI

public struct PositionPopoverView: View {
    private let model: PositionDisplayModel
    private let isRefreshing: Bool
    private let openMiraj: () -> Void
    private let refresh: () -> Void
    private let connect: () -> Void

    public init(
        model: PositionDisplayModel,
        isRefreshing: Bool = false,
        openMiraj: @escaping () -> Void = {},
        refresh: @escaping () -> Void = {},
        connect: @escaping () -> Void = {}
    ) {
        self.model = model
        self.isRefreshing = isRefreshing
        self.openMiraj = openMiraj
        self.refresh = refresh
        self.connect = connect
    }

    public var body: some View {
        VStack(alignment: .leading, spacing: MirajPositionTokens.spacingMedium) {
            header
            bodyCopy
            positionRows
            advisory
            timestamp
            footer
        }
        .padding(MirajPositionTokens.spacingLarge)
        .frame(width: 340, alignment: .leading)
        .background(MirajPositionTokens.background)
        .foregroundStyle(MirajPositionTokens.textPrimary)
        .accessibilityElement(children: .contain)
    }

    private var header: some View {
        HStack(alignment: .firstTextBaseline, spacing: MirajPositionTokens.spacingSmall) {
            VStack(alignment: .leading, spacing: MirajPositionTokens.spacingXSmall) {
                Text(model.title)
                    .font(.system(size: 15, weight: .bold, design: .default))
                    .foregroundStyle(MirajPositionTokens.textPrimary)
                    .lineLimit(1)
                    .truncationMode(.middle)

                if let subtitle = model.subtitle {
                    Text(subtitle)
                        .font(.system(size: 11, weight: .medium, design: .default))
                        .foregroundStyle(MirajPositionTokens.textSecondary)
                        .lineLimit(1)
                }
            }

            Spacer(minLength: MirajPositionTokens.spacingSmall)

            Text(model.badge)
                .font(.system(size: 11, weight: .semibold, design: .default))
                .foregroundStyle(badgeForeground)
                .padding(.horizontal, MirajPositionTokens.spacingSmall)
                .padding(.vertical, MirajPositionTokens.spacingXSmall)
                .background(badgeBackground, in: Capsule())
                .accessibilityLabel("State: \(model.badge)")
        }
    }

    @ViewBuilder
    private var bodyCopy: some View {
        if let body = model.body {
            Text(body)
                .font(.system(size: 13, weight: .regular, design: .default))
                .foregroundStyle(MirajPositionTokens.textPrimary)
                .fixedSize(horizontal: false, vertical: true)
        }

        if let detail = model.detail {
            Text(detail)
                .font(.system(size: 11, weight: .medium, design: .default))
                .foregroundStyle(MirajPositionTokens.textSecondary)
                .fixedSize(horizontal: false, vertical: true)
        }

        if let warning = model.warningLine {
            Text(warning)
                .font(.system(size: 12, weight: .semibold, design: .default))
                .foregroundStyle(warningForeground)
                .padding(MirajPositionTokens.spacingSmall)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(warningBackground, in: RoundedRectangle(cornerRadius: MirajPositionTokens.radiusMedium, style: .continuous))
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    @ViewBuilder
    private var positionRows: some View {
        if !model.rows.isEmpty {
            VStack(alignment: .leading, spacing: MirajPositionTokens.spacingSmall) {
                ForEach(Array(model.rows.enumerated()), id: \.offset) { _, row in
                    Text(row)
                        .font(.system(size: 12, weight: .medium, design: row.hasPrefix("Entry") || row.hasPrefix("PnL") ? .monospaced : .default))
                        .foregroundStyle(rowForeground(row))
                        .lineLimit(2)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            .padding(MirajPositionTokens.spacingMedium)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(MirajPositionTokens.surface, in: RoundedRectangle(cornerRadius: MirajPositionTokens.radiusLarge, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: MirajPositionTokens.radiusLarge, style: .continuous)
                    .stroke(MirajPositionTokens.border, lineWidth: 1)
            )
        }
    }

    @ViewBuilder
    private var advisory: some View {
        if let advisoryLine = model.advisoryLine {
            Text(advisoryLine)
                .font(.system(size: 13, weight: .semibold, design: .default))
                .foregroundStyle(advisoryForeground)
                .fixedSize(horizontal: false, vertical: true)
                .accessibilityLabel(advisoryLine.replacingOccurrences(of: "—", with: ","))
        }
    }

    @ViewBuilder
    private var timestamp: some View {
        if let timestampLine = model.timestampLine {
            Text(timestampLine)
                .font(.system(size: 11, weight: .medium, design: .default))
                .foregroundStyle(MirajPositionTokens.textMuted)
                .accessibilityLabel("Miraj Position, \(model.badge.lowercased()), \(timestampLine.lowercased())")
        }
    }

    private var footer: some View {
        HStack(spacing: MirajPositionTokens.spacingSmall) {
            ForEach(model.footerActions, id: \.self) { action in
                Button(actionTitle(for: action), action: handler(for: action))
                    .buttonStyle(MirajPositionFooterButtonStyle(primary: action == "Open Miraj" || action == "Connect"))
                    .disabled(action == "Refresh" && isRefreshing)
            }
        }
        .padding(.top, MirajPositionTokens.spacingXSmall)
        .accessibilityElement(children: .contain)
    }

    private var badgeForeground: Color {
        switch model.state {
        case .fresh, .noOpenPositions:
            return MirajPositionTokens.positive
        case .stale, .criticalStale:
            return MirajPositionTokens.warning
        case .offlineWithCache, .offlineWithoutCache:
            return MirajPositionTokens.negative
        case .notConnected, .unsupportedSchema:
            return MirajPositionTokens.info
        }
    }

    private var badgeBackground: Color { badgeForeground.opacity(0.16) }

    private var warningForeground: Color {
        model.state == .criticalStale || model.state == .offlineWithCache ? MirajPositionTokens.warning : MirajPositionTokens.textSecondary
    }

    private var warningBackground: Color {
        model.state == .offlineWithCache ? MirajPositionTokens.warning.opacity(0.14) : MirajPositionTokens.surfaceElevated
    }

    private var advisoryForeground: Color {
        guard let advisoryLine = model.advisoryLine else { return MirajPositionTokens.textPrimary }
        if advisoryLine.contains("CLOSE") { return MirajPositionTokens.negative }
        if advisoryLine.contains("REDUCE") || advisoryLine.contains("WAIT") { return MirajPositionTokens.warning }
        return MirajPositionTokens.positive
    }

    private func rowForeground(_ row: String) -> Color {
        guard row.hasPrefix("PnL") else { return MirajPositionTokens.textSecondary }
        switch model.pnlSemanticState {
        case .positiveGreen:
            return MirajPositionTokens.positive
        case .negativeRed:
            return MirajPositionTokens.negative
        case .neutral:
            return MirajPositionTokens.textSecondary
        }
    }

    private func actionTitle(for action: String) -> String {
        action == "Refresh" && isRefreshing ? "Refreshing…" : action
    }

    private func handler(for action: String) -> () -> Void {
        switch action {
        case "Open Miraj": return openMiraj
        case "Refresh": return refresh
        case "Connect": return connect
        default: return {}
        }
    }
}

public struct PositionPopoverSnapshot: Equatable {
    public let menuBarLabel: String
    public let title: String
    public let subtitle: String?
    public let badge: String
    public let body: String?
    public let detail: String?
    public let warningLine: String?
    public let rows: [String]
    public let advisoryLine: String?
    public let timestampLine: String?
    public let footerActions: [String]
    public let isRefreshing: Bool

    public var displayStrings: [String] {
        [menuBarLabel, title, subtitle, badge, body, detail, warningLine, advisoryLine, timestampLine].compactMap { $0 } + rows + renderedFooterActions
    }

    public var renderedFooterActions: [String] {
        footerActions.map { $0 == "Refresh" && isRefreshing ? "Refreshing…" : $0 }
    }

    public init(model: PositionDisplayModel, isRefreshing: Bool = false) {
        self.menuBarLabel = model.menuBarLabel
        self.title = model.title
        self.subtitle = model.subtitle
        self.badge = model.badge
        self.body = model.body
        self.detail = model.detail
        self.warningLine = model.warningLine
        self.rows = model.rows
        self.advisoryLine = model.advisoryLine
        self.timestampLine = model.timestampLine
        self.footerActions = model.footerActions
        self.isRefreshing = isRefreshing
    }
}

enum MirajPositionTokens {
    static let background = Color(red: 0.043, green: 0.059, blue: 0.078)
    static let surface = Color(red: 0.071, green: 0.094, blue: 0.129)
    static let surfaceElevated = Color(red: 0.094, green: 0.129, blue: 0.176)
    static let textPrimary = Color(red: 0.957, green: 0.969, blue: 0.984)
    static let textSecondary = Color(red: 0.655, green: 0.690, blue: 0.745)
    static let textMuted = Color(red: 0.435, green: 0.478, blue: 0.537)
    static let positive = Color(red: 0.192, green: 0.784, blue: 0.553)
    static let negative = Color(red: 0.941, green: 0.322, blue: 0.322)
    static let warning = Color(red: 0.961, green: 0.620, blue: 0.043)
    static let info = Color(red: 0.376, green: 0.647, blue: 0.980)
    static let border = Color(red: 0.169, green: 0.208, blue: 0.263)

    static let spacingXSmall: CGFloat = 4
    static let spacingSmall: CGFloat = 8
    static let spacingMedium: CGFloat = 12
    static let spacingLarge: CGFloat = 16
    static let radiusMedium: CGFloat = 10
    static let radiusLarge: CGFloat = 14
}

struct MirajPositionFooterButtonStyle: ButtonStyle {
    let primary: Bool

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.system(size: 13, weight: .semibold, design: .default))
            .foregroundStyle(primary ? Color(red: 0.031, green: 0.067, blue: 0.122) : MirajPositionTokens.textPrimary)
            .frame(maxWidth: .infinity)
            .padding(.vertical, MirajPositionTokens.spacingSmall)
            .background(primary ? MirajPositionTokens.info : MirajPositionTokens.surfaceElevated, in: RoundedRectangle(cornerRadius: 6, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: 6, style: .continuous)
                    .stroke(configuration.isPressed ? MirajPositionTokens.info : MirajPositionTokens.border, lineWidth: 1)
            )
            .opacity(configuration.isPressed ? 0.82 : 1)
    }
}
