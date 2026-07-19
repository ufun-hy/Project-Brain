import Foundation
import XCTest
@testable import ProjectBrainKit

private final class VersionRunner: HelperCommandRunning, @unchecked Sendable {
    var versions: [String: Result<String, Error>] = [:]
    var calls: [(String, [String])] = []
    let contractDocument: CoreCLIContractDocument

    init(contractDocument: CoreCLIContractDocument) {
        self.contractDocument = contractDocument
    }

    func run(executable: URL, arguments: [String]) throws -> HelperCommandResult {
        calls.append((executable.path, arguments))
        if arguments == ["cli-contract", "--json"] {
            if (try? Data(contentsOf: executable)) == Data("old-helper".utf8) {
                return HelperCommandResult(
                    exitCode: 2,
                    stdout: "",
                    stderr: "unsupported contract"
                )
            }
            return HelperCommandResult(
                exitCode: 0,
                stdout: try encodedContractResponse(contractDocument) + "\n",
                stderr: ""
            )
        }
        let version = try versions[executable.path]?.get() ?? "project-brain 0.8.0"
        return HelperCommandResult(exitCode: 0, stdout: version + "\n", stderr: "")
    }
}

final class HelperInstallerTests: XCTestCase {
    private var root: URL!
    private var support: URL!
    private var bundled: URL!
    private var runner: VersionRunner!
    private var contractDocument: CoreCLIContractDocument!

    override func setUpWithError() throws {
        root = FileManager.default.temporaryDirectory.appending(path: UUID().uuidString)
        support = root.appending(path: "Application Support")
        bundled = root.appending(path: "bundled-project-brain")
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        try Data("helper".utf8).write(to: bundled)
        try FileManager.default.setAttributes(
            [.posixPermissions: 0o755],
            ofItemAtPath: bundled.path
        )
        contractDocument = try repositoryCLIContractDocument()
        runner = VersionRunner(contractDocument: contractDocument)
    }

    override func tearDownWithError() throws {
        try FileManager.default.removeItem(at: root)
    }

    func testInstallAndNoOpUseValidatedAbsoluteHelper() throws {
        let installer = HelperInstaller(
            applicationSupportDirectory: support,
            runner: runner
        )
        let installed = try installer.install(
            bundledHelper: bundled,
            cliContract: contractDocument
        )
        XCTAssertEqual(installed.action, .installed)
        XCTAssertEqual(installed.version, "project-brain 0.8.0")
        XCTAssertEqual(installed.cliContractVersion, "1.1.0")
        XCTAssertEqual(installed.cliContractSHA256, contractDocument.sha256)
        XCTAssertTrue(FileManager.default.isExecutableFile(atPath: installed.destination.path))
        XCTAssertTrue(installed.destination.path.hasPrefix("/"))

        runner.versions[installed.destination.path] = .success("project-brain 0.8.0")
        XCTAssertEqual(
            try installer.install(
                bundledHelper: bundled,
                cliContract: contractDocument
            ).action,
            .current
        )
        XCTAssertTrue(runner.calls.allSatisfy {
            $0.1 == ["--version"] || $0.1 == ["cli-contract", "--json"]
        })
    }

    func testSameVersionWithDifferentSHAAndMissingContractIsUpgraded() throws {
        let installer = HelperInstaller(
            applicationSupportDirectory: support,
            runner: runner
        )
        let first = try installer.install(
            bundledHelper: bundled,
            cliContract: contractDocument
        )
        try Data("old-helper".utf8).write(to: first.destination)
        try FileManager.default.setAttributes(
            [.posixPermissions: 0o755],
            ofItemAtPath: first.destination.path
        )
        runner.versions[first.destination.path] = .success("project-brain 0.8.0")

        let upgraded = try installer.install(
            bundledHelper: bundled,
            cliContract: contractDocument
        )
        XCTAssertEqual(upgraded.action, .upgraded)
        XCTAssertEqual(try Data(contentsOf: upgraded.destination), Data("helper".utf8))
        XCTAssertEqual(upgraded.sha256.count, 64)
    }

    func testUpgradeFailureRestoresPreviouslyRunnableHelper() throws {
        let installer = HelperInstaller(
            applicationSupportDirectory: support,
            runner: runner
        )
        let first = try installer.install(
            bundledHelper: bundled,
            cliContract: contractDocument
        )
        try Data("old-helper".utf8).write(to: first.destination)
        try FileManager.default.setAttributes(
            [.posixPermissions: 0o755],
            ofItemAtPath: first.destination.path
        )
        runner.versions[bundled.path] = .success("project-brain 0.8.0")
        runner.versions[first.destination.path] = .success("project-brain 0.8.0")

        let failing = FailingDestinationRunner(
            destination: first.destination.path,
            contractDocument: contractDocument
        )
        let failingInstaller = HelperInstaller(
            applicationSupportDirectory: support,
            runner: failing
        )
        XCTAssertThrowsError(try failingInstaller.install(
            bundledHelper: bundled,
            cliContract: contractDocument
        ))
        XCTAssertEqual(try Data(contentsOf: first.destination), Data("old-helper".utf8))
    }

    func testRejectsNonExecutableAndSymlinkedHelpers() throws {
        let installer = HelperInstaller(applicationSupportDirectory: support, runner: runner)
        try FileManager.default.setAttributes(
            [.posixPermissions: 0o644],
            ofItemAtPath: bundled.path
        )
        XCTAssertThrowsError(try installer.install(
            bundledHelper: bundled,
            cliContract: contractDocument
        ))

        let target = root.appending(path: "target")
        try Data("helper".utf8).write(to: target)
        try FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: target.path)
        let link = root.appending(path: "link")
        try FileManager.default.createSymbolicLink(at: link, withDestinationURL: target)
        XCTAssertThrowsError(try installer.install(
            bundledHelper: link,
            cliContract: contractDocument
        ))
    }

    func testActivationFailureRollsBackUpgradeAndReactivatesOldHelper() throws {
        let installer = HelperInstaller(applicationSupportDirectory: support, runner: runner)
        let first = try installer.install(
            bundledHelper: bundled,
            cliContract: contractDocument
        )
        try Data("old-helper".utf8).write(to: first.destination)
        try FileManager.default.setAttributes(
            [.posixPermissions: 0o755],
            ofItemAtPath: first.destination.path
        )
        let activationRunner = ActivationRunner(
            contractDocument: contractDocument
        )
        let upgradingInstaller = HelperInstaller(
            applicationSupportDirectory: support,
            runner: activationRunner
        )
        let actions = LockedActions()

        XCTAssertThrowsError(
            try upgradingInstaller.install(
                bundledHelper: bundled,
                cliContract: contractDocument
            ) { _, action in
                actions.append(action)
                if action == .upgraded {
                    throw HelperInstallerError.versionCheck("simulated service restart failure")
                }
            }
        )
        XCTAssertEqual(try Data(contentsOf: first.destination), Data("old-helper".utf8))
        XCTAssertEqual(actions.values, [.upgraded, .current])
    }
}

private final class LockedActions: @unchecked Sendable {
    private let lock = NSLock()
    private var stored: [HelperInstallAction] = []

    var values: [HelperInstallAction] { lock.withLock { stored } }
    func append(_ action: HelperInstallAction) { lock.withLock { stored.append(action) } }
}

private final class ActivationRunner: HelperCommandRunning, @unchecked Sendable {
    private let contractDocument: CoreCLIContractDocument

    init(contractDocument: CoreCLIContractDocument) {
        self.contractDocument = contractDocument
    }

    func run(executable: URL, arguments: [String]) throws -> HelperCommandResult {
        if arguments == ["cli-contract", "--json"] {
            return HelperCommandResult(
                exitCode: 0,
                stdout: try encodedContractResponse(contractDocument),
                stderr: ""
            )
        }
        return HelperCommandResult(exitCode: 0, stdout: "project-brain 0.8.0\n", stderr: "")
    }
}

private final class FailingDestinationRunner: HelperCommandRunning, @unchecked Sendable {
    private let destination: String
    private let contractDocument: CoreCLIContractDocument
    private var checks = 0

    init(destination: String, contractDocument: CoreCLIContractDocument) {
        self.destination = destination
        self.contractDocument = contractDocument
    }

    func run(executable: URL, arguments: [String]) throws -> HelperCommandResult {
        if arguments == ["cli-contract", "--json"] {
            return HelperCommandResult(
                exitCode: 0,
                stdout: try encodedContractResponse(contractDocument),
                stderr: ""
            )
        }
        if executable.path == destination {
            checks += 1
            if checks > 1 {
                throw HelperInstallerError.versionCheck("simulated installed validation failure")
            }
            return HelperCommandResult(
                exitCode: 0,
                stdout: "project-brain 0.6.0\n",
                stderr: ""
            )
        }
        return HelperCommandResult(
            exitCode: 0,
            stdout: "project-brain 0.8.0\n",
            stderr: ""
        )
    }
}
