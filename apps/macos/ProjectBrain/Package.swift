// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "ProjectBrain",
    platforms: [.macOS(.v14)],
    products: [
        .library(name: "ProjectBrainKit", targets: ["ProjectBrainKit"]),
    ],
    targets: [
        .target(
            name: "ProjectBrainKit",
            path: "ProjectBrainKit"
        ),
        .testTarget(
            name: "ProjectBrainTests",
            dependencies: ["ProjectBrainKit"],
            path: "ProjectBrainTests"
        ),
    ]
)
