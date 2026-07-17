// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "ProjectBrain",
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
            resources: [.copy("Resources/tunnel-client-compatibility.json")]
        ),
        .testTarget(
            name: "ProjectBrainTests",
            dependencies: ["ProjectBrainKit"],
            path: "ProjectBrainTests"
        ),
    ]
)
