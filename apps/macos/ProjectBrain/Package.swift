// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "ProjectBrain",
    defaultLocalization: "en",
    platforms: [.macOS(.v14)],
    products: [
        .library(name: "ProjectBrainKit", targets: ["ProjectBrainKit"]),
        .executable(name: "ProjectBrainApp", targets: ["ProjectBrainApp"]),
    ],
    targets: [
        .target(
            name: "ProjectBrainKit",
            path: "ProjectBrainKit",
            linkerSettings: [.linkedFramework("Security")]
        ),
        .executableTarget(
            name: "ProjectBrainApp",
            dependencies: ["ProjectBrainKit"],
            path: "ProjectBrain",
            exclude: ["Info.plist"],
            resources: [.process("Resources")]
        ),
        .testTarget(
            name: "ProjectBrainTests",
            dependencies: ["ProjectBrainKit"],
            path: "ProjectBrainTests"
        ),
    ]
)
