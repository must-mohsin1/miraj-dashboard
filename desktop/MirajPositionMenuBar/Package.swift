// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "MirajPositionMenuBar",
    platforms: [
        .macOS(.v14)
    ],
    products: [
        .executable(
            name: "MirajPositionMenuBar",
            targets: ["MirajPositionMenuBar"]
        )
    ],
    targets: [
        .executableTarget(
            name: "MirajPositionMenuBar",
            path: ".",
            exclude: [
                "README.md",
                "Tests"
            ],
            sources: [
                "Sources/MirajPositionMenuBar/MirajPositionMenuBarApp.swift",
                "Sources/MirajPositionMenuBar/MockFixturePositionProvider.swift",
                "Sources/MirajPositionMenuBar/PositionCache.swift",
                "Sources/MirajPositionMenuBar/PositionClient.swift",
                "Sources/MirajPositionMenuBar/PositionDisplayModel.swift",
                "Sources/MirajPositionMenuBar/PositionPopoverView.swift",
                "Sources/MirajPositionMenuBar/PositionPreferences.swift",
                "Sources/MirajPositionMenuBar/PositionTokenStore.swift"
            ],
            resources: [
                .copy("MockFixtures")
            ]
        )
    ]
)
