import SwiftUI

#if !MENUBAR_VIEWMODEL_TESTING
@main
struct MirajPositionMenuBarApp: App {
    @StateObject private var viewModel = MirajPositionMenuBarViewModel()

    var body: some Scene {
        MenuBarExtra {
            PositionPopoverView(
                model: viewModel.displayModel,
                isRefreshing: viewModel.isRefreshing,
                openMiraj: viewModel.openMiraj,
                refresh: viewModel.refresh,
                connect: viewModel.connect
            )
        } label: {
            Text(viewModel.displayModel.menuBarLabel)
                .accessibilityLabel(viewModel.menuBarAccessibilityLabel)
        }
        .menuBarExtraStyle(.window)
    }
}
#endif

@MainActor
final class MirajPositionMenuBarViewModel: ObservableObject {
    @Published private(set) var displayModel: PositionDisplayModel
    @Published private(set) var isRefreshing = false

    private let preferencesStore: PositionPreferencesLoading
    private let refreshCoordinator: PositionRefreshing
    private var preferences: PositionPreferences
    private var refreshTask: Task<Void, Never>?

    convenience init() {
        let preferencesStore = PositionPreferencesStore()
        let preferences = preferencesStore.load()
        self.init(
            preferencesStore: preferencesStore,
            refreshCoordinator: Self.makeRuntimeCoordinator(preferences: preferences),
            initialDisplayModel: .notConnected(redactMenuBar: preferences.redactMenuBar),
            automaticallyRefreshOnLaunch: true
        )
    }

    static func makeRuntimeCoordinator(preferences: PositionPreferences) -> PositionRefreshing {
        switch PositionRuntimeConfiguration.runtimeMode(preferences: preferences) {
        case .mockFixtures:
            return MockFixturePositionProvider(
                fixtureName: MockFixturePositionProvider.fixtureName(),
                fixtureDirectory: MockFixturePositionProvider.fixtureDirectory()
            )
        case .connected:
            let cache = try? PositionCache()
            let client = PositionClient(
                baseURL: preferences.debugAPIBaseURL,
                session: PositionClient.urlSession(),
                tokenStore: PositionKeychainTokenStore(),
                cache: cache
            )
            return PositionRefreshCoordinator(client: client)
        }
    }

    init(
        preferencesStore: PositionPreferencesLoading,
        refreshCoordinator: PositionRefreshing,
        initialDisplayModel: PositionDisplayModel? = nil,
        automaticallyRefreshOnLaunch: Bool = false
    ) {
        self.preferencesStore = preferencesStore
        self.refreshCoordinator = refreshCoordinator
        self.preferences = preferencesStore.load()
        self.displayModel = initialDisplayModel ?? .notConnected(redactMenuBar: preferences.redactMenuBar)

        if automaticallyRefreshOnLaunch {
            refreshAutomaticallyIfEnabled()
        }
    }

    var menuBarAccessibilityLabel: String {
        if displayModel.menuBarLabel == "Miraj" {
            return "Miraj Position, privacy mode on"
        }

        let timestamp = displayModel.timestampLine.map { ", \($0.lowercased())" } ?? ""
        return "Miraj Position, \(displayModel.badge.lowercased())\(timestamp)"
    }

    func refresh() {
        startRefresh(trigger: .manual)
    }

    func refreshAutomaticallyIfEnabled() {
        preferences = preferencesStore.load()
        let runtimeMode = PositionRuntimeConfiguration.runtimeMode(preferences: preferences)
        guard runtimeMode == .mockFixtures || preferences.refreshPreference == .automatic else { return }
        startRefresh(trigger: .automatic)
    }

    private func startRefresh(trigger: PositionRefreshTrigger) {
        guard !isRefreshing else { return }
        refreshTask?.cancel()
        refreshTask = Task { [weak self] in
            await self?.performRefresh(trigger: trigger)
        }
    }

    private func performRefresh(trigger: PositionRefreshTrigger) async {
        preferences = preferencesStore.load()
        isRefreshing = true
        defer { isRefreshing = false }

        let result = await refreshCoordinator.refresh(trigger: trigger, symbol: preferences.selectedSymbol)
        guard !Task.isCancelled else { return }
        apply(result)
    }

    private func apply(_ result: Result<PositionLoadResult, PositionClientError>) {
        switch result {
        case .success(let loadResult):
            apply(loadResult)
        case .failure(.automaticRefreshThrottled), .failure(.refreshInFlight):
            return
        case .failure(let error):
            apply(.offlineWithoutCache(error))
        }
    }

    private func apply(_ result: PositionLoadResult) {
        let options = PositionDisplayOptions(
            hideAmounts: preferences.hideAmounts,
            redactMenuBar: preferences.redactMenuBar
        )

        switch result {
        case .loaded(let response):
            displayModel = PositionDisplayModel(response: response, options: options)
        case .offlineWithCache(_, .notConnected), .offlineWithCache(_, .unauthorized):
            displayModel = .notConnected(redactMenuBar: preferences.redactMenuBar)
        case .offlineWithCache(let cached, _):
            displayModel = PositionDisplayModel(response: cached, options: options)
        case .offlineWithoutCache(.notConnected), .offlineWithoutCache(.unauthorized):
            displayModel = .notConnected(redactMenuBar: preferences.redactMenuBar)
        case .offlineWithoutCache:
            displayModel = .offlineWithoutCache(redactMenuBar: preferences.redactMenuBar)
        }
    }

    func openMiraj() {
        guard let url = URL(string: "miraj://portfolio") ?? URL(string: "http://localhost:3000/portfolio") else { return }
        NSWorkspace.shared.open(url)
    }

    func connect() {
        guard let url = URL(string: "miraj://login") ?? URL(string: "http://localhost:3000/login") else { return }
        NSWorkspace.shared.open(url)
    }
}

enum PositionRuntimeConfiguration {
    static func runtimeMode(preferences: PositionPreferences, processInfo: ProcessInfo = .processInfo) -> PositionRuntimeMode {
        if let mode = processInfo.environment["MIRAJ_POSITION_MODE"].flatMap(PositionRuntimeMode.init(rawValue:)) {
            return mode
        }

        if processInfo.arguments.contains("--miraj-position-connected") {
            return .connected
        }

        if processInfo.arguments.contains("--miraj-position-mock") {
            return .mockFixtures
        }

        return preferences.runtimeMode
    }
}
