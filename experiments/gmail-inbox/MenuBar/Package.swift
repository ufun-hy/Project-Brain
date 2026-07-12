// swift-tools-version: 6.0
import PackageDescription
let package = Package(name:"ProjectBrainMenuBar",platforms:[.macOS(.v13)],products:[.executable(name:"ProjectBrainMenuBar",targets:["ProjectBrainMenuBar"])],targets:[.executableTarget(name:"ProjectBrainMenuBar"),.testTarget(name:"ProjectBrainMenuBarTests",dependencies:["ProjectBrainMenuBar"])])
