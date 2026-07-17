import Foundation
import XCTest
@testable import ProjectBrainKit

private final class InstallerRunner: TunnelInstallerProcessRunning, @unchecked Sendable {
    var versionResult: TunnelInstallerProcessResult?
    var contractResult: TunnelInstallerProcessResult?
    var version = "0.0.10"
    private(set) var calls: [(URL, [String], TimeInterval, Int, [String: String])] = []

    func run(
        executable: URL,
        arguments: [String],
        timeout: TimeInterval,
        outputLimit: Int,
        environment: [String: String]
    ) throws -> TunnelInstallerProcessResult {
        calls.append((executable, arguments, timeout, outputLimit, environment))
        if arguments == ["runtimes", "list", "--json"] {
            if let contractResult { return contractResult }
            let home = environment["HOME"] ?? "/invalid"
            return .init(
                exitCode: 0,
                stdout: Data(
                    "{\"aliases\":[],\"admin_profile\":\"default\","
                        .appending("\"admin_profile_path\":\"")
                        .appending(home)
                        .appending("/.openai-tunnel/admin.json\",\"state_root\":\"")
                        .appending(home)
                        .appending("/.openai-tunnel\"}").utf8
                ),
                stderr: Data()
            )
        }
        return versionResult ?? .init(
            exitCode: 0,
            stdout: Data("\(version)\n".utf8),
            stderr: Data()
        )
    }
}

final class TunnelClientInstallerTests: XCTestCase {
    private var temporary: URL!
    private var source: URL!
    private var runner: InstallerRunner!
    private var installer: TunnelClientInstaller!

    override func setUpWithError() throws {
        temporary = FileManager.default.temporaryDirectory
            .appending(path: "TunnelClientInstallerTests-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: temporary, withIntermediateDirectories: true)
        source = temporary.appending(path: "tunnel-client")
        try writeMachO(source, architecture: .arm64, marker: 1)
        runner = InstallerRunner()
        installer = try TunnelClientInstaller(
            manifest: manifest(),
            applicationSupportDirectory: temporary.appending(path: "Application Support"),
            requiredArchitecture: .arm64,
            runner: runner
        )
    }

    override func tearDownWithError() throws {
        if let temporary { try? FileManager.default.removeItem(at: temporary) }
    }

    func testSelectionPerformsStaticPreflightWithoutExecutingCandidate() throws {
        XCTAssertThrowsError(try installer.prepareImport(selectedURLs: [])) {
            XCTAssertEqual($0 as? TunnelClientInstallerError, .invalidSelection)
        }
        XCTAssertThrowsError(try installer.prepareImport(selectedURLs: [source, source])) {
            XCTAssertEqual($0 as? TunnelClientInstallerError, .invalidSelection)
        }
        let preview = try installer.prepareImport(selectedURLs: [source])
        XCTAssertEqual(preview.architecture, .arm64)
        XCTAssertEqual(preview.sha256.count, 64)
        XCTAssertGreaterThan(preview.fileSize, 0)
        XCTAssertTrue(preview.sourceAttestation.contains("official OpenAI Platform Tunnels"))
        XCTAssertTrue(runner.calls.isEmpty)
    }

    func testExplicitAuthorizationRunsOnlyFixedVersionCommand() throws {
        let preview = try installer.prepareImport(selectedURLs: [source])
        let plan = try installer.authorize(preview)
        XCTAssertEqual(plan.version, "0.0.10")
        XCTAssertEqual(plan.manifestSchemaVersion, 1)
        XCTAssertEqual(plan.runtimesContract, 1)
        XCTAssertEqual(runner.calls.count, 1)
        XCTAssertEqual(runner.calls.first?.1, ["--version"])
        XCTAssertEqual(runner.calls.first?.2, TunnelClientInstaller.versionTimeout)
        XCTAssertEqual(runner.calls.first?.3, TunnelClientInstaller.outputLimit)
    }

    func testRejectsSymbolicLinkDirectoryAndWrongArchitecture() throws {
        let link = temporary.appending(path: "linked-client")
        try FileManager.default.createSymbolicLink(at: link, withDestinationURL: source)
        XCTAssertThrowsError(try installer.validate(link))

        let directory = temporary.appending(path: "directory")
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: false)
        try FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: directory.path)
        XCTAssertThrowsError(try installer.validate(directory))

        let wrong = temporary.appending(path: "x86-client")
        try writeMachO(wrong, architecture: .x86_64, marker: 2)
        XCTAssertThrowsError(try installer.validate(wrong)) {
            XCTAssertEqual($0 as? TunnelClientInstallerError, .unsupportedArchitecture)
        }
    }

    func testRejectsUnsupportedVersion() throws {
        runner.version = "0.0.11"
        XCTAssertThrowsError(try installer.validate(source)) {
            XCTAssertEqual($0 as? TunnelClientInstallerError, .unsupportedVersion)
        }
    }

    func testVersionTimeoutOversizedAndMaliciousOutputFailClosed() throws {
        runner.versionResult = .init(
            exitCode: -1,
            stdout: Data(),
            stderr: Data(),
            timedOut: true
        )
        XCTAssertThrowsError(try installer.validate(source)) {
            XCTAssertEqual($0 as? TunnelClientInstallerError, .versionTimeout)
        }

        runner.versionResult = .init(
            exitCode: 0,
            stdout: Data(repeating: 65, count: TunnelClientInstaller.outputLimit),
            stderr: Data(),
            stdoutExceededLimit: true
        )
        XCTAssertThrowsError(try installer.validate(source)) {
            XCTAssertEqual($0 as? TunnelClientInstallerError, .versionOutputExceeded)
        }

        runner.versionResult = .init(
            exitCode: 0,
            stdout: Data("0.0.10\nmalicious command output\n".utf8),
            stderr: Data()
        )
        XCTAssertThrowsError(try installer.validate(source)) {
            XCTAssertEqual($0 as? TunnelClientInstallerError, .versionCheckFailed)
            XCTAssertFalse($0.localizedDescription.contains("malicious"))
        }
    }

    func testOfficialVersionWithBuildMetadataIsAccepted() throws {
        runner.versionResult = .init(
            exitCode: 0,
            stdout: Data("0.0.10+abcdef0 (git sha: abcdef0)\n".utf8),
            stderr: Data()
        )
        XCTAssertEqual(try installer.validate(source).version, "0.0.10")
    }

    func testAtomicInstallValidateAgainAndPermissions() throws {
        let plan = try installer.validate(source)
        let result = try installer.install(plan)
        XCTAssertEqual(result.action, .installed)
        XCTAssertEqual(result.destination, installer.destination)
        XCTAssertEqual(try installer.validateInstalled()?.sha256, plan.sha256)
        let binaryMode = try FileManager.default.attributesOfItem(
            atPath: result.destination.path
        )[.posixPermissions] as? NSNumber
        let directoryMode = try FileManager.default.attributesOfItem(
            atPath: result.destination.deletingLastPathComponent().path
        )[.posixPermissions] as? NSNumber
        XCTAssertEqual(binaryMode?.intValue, 0o755)
        XCTAssertEqual(directoryMode?.intValue, 0o700)
        XCTAssertFalse(FileManager.default.fileExists(
            atPath: result.destination.deletingLastPathComponent()
                .appending(path: ".tunnel-client.rollback").path
        ))
        let contractCall = try XCTUnwrap(
            runner.calls.first(where: { $0.1 == ["runtimes", "list", "--json"] })
        )
        XCTAssertNotEqual(
            contractCall.4["HOME"],
            FileManager.default.homeDirectoryForCurrentUser.path
        )
        XCTAssertTrue(contractCall.4["HOME"]?.contains(".contract-probe-") == true)
        XCTAssertFalse(FileManager.default.fileExists(atPath: contractCall.4["HOME"] ?? ""))
    }

    func testCandidateChangeAfterPlanIsRejected() throws {
        let plan = try installer.validate(source)
        try writeMachO(source, architecture: .arm64, marker: 9)
        XCTAssertThrowsError(try installer.install(plan)) {
            XCTAssertEqual($0 as? TunnelClientInstallerError, .candidateChanged)
        }
        XCTAssertFalse(FileManager.default.fileExists(atPath: installer.destination.path))
    }

    func testInstallRejectsManagedDirectorySymlink() throws {
        let support = temporary.appending(path: "Linked Support")
        let redirect = temporary.appending(path: "redirect")
        try FileManager.default.createDirectory(at: redirect, withIntermediateDirectories: true)
        try FileManager.default.createSymbolicLink(at: support, withDestinationURL: redirect)
        let linkedInstaller = try TunnelClientInstaller(
            manifest: manifest(),
            applicationSupportDirectory: support,
            requiredArchitecture: .arm64,
            runner: runner
        )
        let plan = try linkedInstaller.validate(source)
        XCTAssertThrowsError(try linkedInstaller.install(plan))
        XCTAssertFalse(FileManager.default.fileExists(
            atPath: redirect.appending(path: TunnelClientInstaller.relativeDestination).path
        ))
    }

    func testUpgradeActivationFailureRestoresPreviousBinary() throws {
        let firstPlan = try installer.validate(source)
        _ = try installer.install(firstPlan)
        let original = try Data(contentsOf: installer.destination)
        try writeMachO(source, architecture: .arm64, marker: 7)
        let upgrade = try installer.validate(source)
        XCTAssertNotEqual(firstPlan.sha256, upgrade.sha256)
        XCTAssertThrowsError(try installer.install(upgrade) { _, action in
            if action == .upgraded { throw TunnelClientInstallerError.filesystem("activation failed") }
        })
        XCTAssertEqual(try Data(contentsOf: installer.destination), original)
        XCTAssertEqual(try installer.validateInstalled()?.sha256, firstPlan.sha256)
    }

    func testInvalidRuntimeContractRemovesFreshInstall() throws {
        let plan = try installer.validate(source)
        runner.contractResult = .init(
            exitCode: 0,
            stdout: Data("{\"aliases\":[]}".utf8),
            stderr: Data("candidate supplied text must not leak".utf8)
        )
        XCTAssertThrowsError(try installer.install(plan)) {
            XCTAssertEqual(
                $0 as? TunnelClientInstallerError,
                .activationFailedFreshInstallRemoved
            )
            XCTAssertFalse($0.localizedDescription.contains("candidate supplied"))
        }
        XCTAssertFalse(FileManager.default.fileExists(atPath: installer.destination.path))
    }

    func testInvalidRuntimeContractRestoresPreviousSHAOnUpgrade() throws {
        let firstPlan = try installer.validate(source)
        _ = try installer.install(firstPlan)
        let original = try Data(contentsOf: installer.destination)
        try writeMachO(source, architecture: .arm64, marker: 8)
        let upgrade = try installer.validate(source)
        runner.contractResult = .init(
            exitCode: 2,
            stdout: Data(),
            stderr: Data("unknown runtimes contract".utf8)
        )
        XCTAssertThrowsError(try installer.install(upgrade)) {
            XCTAssertEqual(
                $0 as? TunnelClientInstallerError,
                .activationFailedPreviousVersionRestored
            )
        }
        XCTAssertEqual(try Data(contentsOf: installer.destination), original)
        XCTAssertEqual(try installer.validateInstalled()?.sha256, firstPlan.sha256)
    }

    func testRemoveBinaryRequiresConfirmedStopAndPreservesConfigurationBoundary() throws {
        _ = try installer.install(try installer.validate(source))
        let unconfirmed = TunnelStopResult(
            status: TunnelRuntimeStatus(
                processRunning: true,
                runtimeState: "running"
            ),
            alreadyStopped: false
        )
        XCTAssertThrowsError(try installer.removeManagedBinary(confirmedStop: unconfirmed)) {
            XCTAssertEqual($0 as? TunnelClientInstallerError, .stopNotConfirmed)
        }
        XCTAssertTrue(FileManager.default.fileExists(atPath: installer.destination.path))

        let confirmed = TunnelStopResult(
            status: TunnelRuntimeStatus(runtimeState: "stopped"),
            alreadyStopped: true
        )
        try installer.removeManagedBinary(confirmedStop: confirmed)
        XCTAssertFalse(FileManager.default.fileExists(atPath: installer.destination.path))
    }

    func testManagedPathIsFirstDiscoveryCandidate() {
        let support = temporary.appending(path: "Support")
        let urls = TunnelClient.allowedExecutableURLs(
            home: temporary.appending(path: "Home"),
            applicationSupportDirectory: support
        )
        XCTAssertEqual(
            urls.first,
            support.appending(path: TunnelClientInstaller.relativeDestination)
        )
    }

    private func manifest() -> TunnelCompatibilityManifest {
        TunnelCompatibilityManifest(
            schemaVersion: 1,
            supported: [
                .init(
                    version: "0.0.10",
                    platform: "macos",
                    architectures: ["arm64"],
                    runtimesContract: 1
                )
            ]
        )
    }

    private func writeMachO(
        _ url: URL,
        architecture: TunnelBinaryArchitecture,
        marker: UInt8
    ) throws {
        let cpu: [UInt8]
        switch architecture {
        case .arm64: cpu = [0x0c, 0x00, 0x00, 0x01]
        case .x86_64: cpu = [0x07, 0x00, 0x00, 0x01]
        case .unknown: cpu = [0, 0, 0, 0]
        }
        var data = Data([0xcf, 0xfa, 0xed, 0xfe] + cpu)
        data.append(Data(repeating: 0, count: 24))
        data.append(marker)
        try data.write(to: url, options: .atomic)
        try FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: url.path)
    }
}
