import Foundation
import XCTest
@testable import ProjectBrainKit

private final class VersionRunner: HelperCommandRunning, @unchecked Sendable {
    var versions: [String: Result<String, Error>] = [:]
    var calls: [(String, [String])] = []

    func run(executable: URL, arguments: [String]) throws -> HelperCommandResult {
        calls.append((executable.path, arguments))
        let version = try versions[executable.path]?.get() ?? "project-brain 0.6.0"
        return HelperCommandResult(exitCode: 0, stdout: version + "\n", stderr: "")
    }
}

final class HelperInstallerTests: XCTestCase {
    private var root: URL!
    private var support: URL!
    private var bundled: URL!
    private var runner: VersionRunner!

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
        runner = VersionRunner()
    }

    override func tearDownWithError() throws {
        try FileManager.default.removeItem(at: root)
    }

    func testInstallAndNoOpUseValidatedAbsoluteHelper() throws {
        let installer = HelperInstaller(
            applicationSupportDirectory: support,
            runner: runner
        )
        let installed = try installer.install(bundledHelper: bundled)
        XCTAssertEqual(installed.action, .installed)
        XCTAssertEqual(installed.version, "project-brain 0.6.0")
        XCTAssertTrue(FileManager.default.isExecutableFile(atPath: installed.destination.path))
        XCTAssertTrue(installed.destination.path.hasPrefix("/"))

        runner.versions[installed.destination.path] = .success("project-brain 0.6.0")
        XCTAssertEqual(try installer.install(bundledHelper: bundled).action, .current)
        XCTAssertTrue(runner.calls.allSatisfy { $0.1 == ["--version"] })
    }

    func testUpgradeFailureRestoresPreviouslyRunnableHelper() throws {
        let installer = HelperInstaller(
            applicationSupportDirectory: support,
            runner: runner
        )
        let first = try installer.install(bundledHelper: bundled)
        try Data("old-helper".utf8).write(to: first.destination)
        try FileManager.default.setAttributes(
            [.posixPermissions: 0o755],
            ofItemAtPath: first.destination.path
        )
        runner.versions[bundled.path] = .success("project-brain 0.7.0")
        runner.versions[first.destination.path] = .success("project-brain 0.6.0")

        let failing = FailingDestinationRunner(
            destination: first.destination.path
        )
        let failingInstaller = HelperInstaller(
            applicationSupportDirectory: support,
            runner: failing
        )
        XCTAssertThrowsError(try failingInstaller.install(bundledHelper: bundled))
        XCTAssertEqual(try Data(contentsOf: first.destination), Data("old-helper".utf8))
    }

    func testRejectsNonExecutableAndSymlinkedHelpers() throws {
        let installer = HelperInstaller(applicationSupportDirectory: support, runner: runner)
        try FileManager.default.setAttributes(
            [.posixPermissions: 0o644],
            ofItemAtPath: bundled.path
        )
        XCTAssertThrowsError(try installer.install(bundledHelper: bundled))

        let target = root.appending(path: "target")
        try Data("helper".utf8).write(to: target)
        try FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: target.path)
        let link = root.appending(path: "link")
        try FileManager.default.createSymbolicLink(at: link, withDestinationURL: target)
        XCTAssertThrowsError(try installer.install(bundledHelper: link))
    }

    func testActivationFailureRollsBackUpgradeAndReactivatesOldHelper() throws {
        let installer = HelperInstaller(applicationSupportDirectory: support, runner: runner)
        let first = try installer.install(bundledHelper: bundled)
        try Data("old-helper".utf8).write(to: first.destination)
        try FileManager.default.setAttributes(
            [.posixPermissions: 0o755],
            ofItemAtPath: first.destination.path
        )
        let activationRunner = ActivationRunner(destination: first.destination.path)
        let upgradingInstaller = HelperInstaller(
            applicationSupportDirectory: support,
            runner: activationRunner
        )
        let actions = LockedActions()

        XCTAssertThrowsError(
            try upgradingInstaller.install(bundledHelper: bundled) { _, action in
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
    private let destination: String
    private var destinationChecks = 0

    init(destination: String) { self.destination = destination }

    func run(executable: URL, arguments: [String]) throws -> HelperCommandResult {
        if executable.path == destination {
            destinationChecks += 1
            let version = destinationChecks == 2 ? "project-brain 0.7.0" : "project-brain 0.6.0"
            return HelperCommandResult(exitCode: 0, stdout: version + "\n", stderr: "")
        }
        return HelperCommandResult(exitCode: 0, stdout: "project-brain 0.7.0\n", stderr: "")
    }
}

private final class FailingDestinationRunner: HelperCommandRunning, @unchecked Sendable {
    private let destination: String
    private var checks = 0

    init(destination: String) {
        self.destination = destination
    }

    func run(executable: URL, arguments: [String]) throws -> HelperCommandResult {
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
            stdout: "project-brain 0.7.0\n",
            stderr: ""
        )
    }
}
