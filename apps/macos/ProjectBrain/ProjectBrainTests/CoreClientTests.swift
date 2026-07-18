import Foundation
import XCTest
@testable import ProjectBrainKit

private final class CapturingCoreRunner: CoreProcessRunning, @unchecked Sendable {
    var result: CoreProcessResult
    private(set) var executable: URL?
    private(set) var arguments: [String] = []

    init(result: CoreProcessResult) { self.result = result }

    func run(executable: URL, arguments: [String]) throws -> CoreProcessResult {
        self.executable = executable
        self.arguments = arguments
        return result
    }
}

final class CoreClientTests: XCTestCase {
    func testTypedAdapterUsesAbsoluteHelperFixedArgvAndNoShell() throws {
        let runner = CapturingCoreRunner(result: .init(
            exitCode: 0,
            stdout: Data(#"{"status":"ok","counts":{},"tasks":[]}"#.utf8),
            stderr: Data()
        ))
        let client = try CoreClient(
            executable: URL(filePath: "/Applications/Project Brain.app/Contents/Resources/project-brain"),
            runtimeRoot: URL(filePath: "/Users/example/.project-brain"),
            runner: runner
        )
        _ = try client.status()
        XCTAssertTrue(runner.executable?.path.hasPrefix("/") == true)
        XCTAssertEqual(
            runner.arguments,
            ["--runtime-root", "/Users/example/.project-brain", "status", "--json"]
        )
        XCTAssertFalse(runner.arguments.contains("-c"))
        XCTAssertFalse(runner.arguments.contains(where: { $0.contains("zsh") || $0.contains("bash") }))
    }

    func testProjectMutationRequiresSeparatePlanAndApplyCommands() {
        let draft = ProjectDraft(
            repository: URL(filePath: "/Users/example/repo"),
            projectID: "example",
            name: "Example",
            codexExecutable: URL(filePath: "/opt/homebrew/bin/codex"),
            autoPush: true,
            autoPR: true
        )
        let runtime = URL(filePath: "/Users/example/.project-brain")
        let plan = CoreCommand.addProject(draft, planToken: nil).arguments(runtimeRoot: runtime)
        let token = "v1:abc123"
        let apply = CoreCommand.addProject(draft, planToken: token).arguments(runtimeRoot: runtime)
        XCTAssertTrue(plan.contains("--plan"))
        XCTAssertTrue(plan.contains("--resolve-existing"))
        XCTAssertFalse(plan.contains("--non-interactive"))
        XCTAssertTrue(apply.contains("--non-interactive"))
        XCTAssertEqual(apply.suffix(3), ["--plan-token", token, "--json"])
        XCTAssertFalse(apply.contains("--plan"))
    }

    func testCoreErrorsAreCategorizedAndSecretRedacted() throws {
        let runner = CapturingCoreRunner(result: .init(
            exitCode: 2,
            stdout: Data(),
            stderr: Data(#"{"status":"error","error_category":"configuration","error":"token=ghp_abcdefghijklmnopqrstuvwxyz1234567890"}"#.utf8)
        ))
        let client = try CoreClient(
            executable: URL(filePath: "/tmp/project-brain"),
            runner: runner
        )
        XCTAssertThrowsError(try client.projects()) { error in
            guard let clientError = error as? CoreClientError,
                  case .core(let category, let message) = clientError else {
                return XCTFail("unexpected error: \(error)")
            }
            XCTAssertEqual(category, "configuration")
            XCTAssertFalse(message.contains("ghp_"))
        }
    }

    func testStructuredProjectConflictIsDecodedForOnboardingRecovery() throws {
        let runner = CapturingCoreRunner(result: .init(
            exitCode: 2,
            stdout: Data(),
            stderr: Data(#"{"status":"error","error_category":"project_conflict","error":"Name is registered","conflict":{"kind":"project_name_conflict","existing_project_id":"project-brain","existing_project_name":"Project-Brain","repository_label":"Project-Brain","recovery_options":["use_existing_project","choose_different_repository","edit_project_name"]}}"#.utf8)
        ))
        let client = try CoreClient(
            executable: URL(filePath: "/tmp/project-brain"),
            runner: runner
        )
        XCTAssertThrowsError(try client.projects()) { error in
            guard let clientError = error as? CoreClientError,
                  case .projectConflict(let message, let conflict) = clientError else {
                return XCTFail("unexpected error: \(error)")
            }
            XCTAssertEqual(message, "Name is registered")
            XCTAssertEqual(conflict.existingProjectID, "project-brain")
            XCTAssertEqual(
                conflict.recoveryOptions,
                [.useExistingProject, .chooseDifferentRepository, .editProjectName]
            )
        }
    }

    func testAllCommandsComeFromClosedTypedAllowlist() {
        let runtime = URL(filePath: "/Users/example/.project-brain")
        let commands: [CoreCommand] = [
            .initialize, .status, .tasks, .task("task-1"), .projects, .health, .readiness,
            .serviceStatus, .service(.restart),
            .useProject("project-1", planToken: nil),
            .projectLifecycle("project-1", .pause, execute: false),
            .acceptanceStatus,
            .acceptanceCreate(appVersion: "0.7.0", tunnelFingerprint: "fingerprint"),
            .acceptanceWaiting("run-1"), .acceptanceReset("run-1"),
            .acceptanceTaskPlan("project-1"),
            .acceptanceTaskCreate("project-1", planToken: "v1:token"),
        ]
        for command in commands {
            let arguments = command.arguments(runtimeRoot: runtime)
            XCTAssertFalse(arguments.contains("-c"))
            XCTAssertFalse(arguments.contains("--cwd"))
            XCTAssertFalse(arguments.contains("--env"))
            XCTAssertFalse(arguments.contains("pass"))
        }
    }

    func testAcceptanceCommandsUseOnlyFixedCoreArgumentsAndExposeNoPassCommand() {
        let runtime = URL(filePath: "/Users/example/.project-brain")
        XCTAssertEqual(
            CoreCommand.acceptanceCreate(
                appVersion: "0.7.0",
                tunnelFingerprint: "sha256-fingerprint"
            ).arguments(runtimeRoot: runtime),
            [
                "--runtime-root", "/Users/example/.project-brain",
                "acceptance", "create", "--app-version", "0.7.0",
                "--tunnel-fingerprint", "sha256-fingerprint", "--json",
            ]
        )
        XCTAssertEqual(
            CoreCommand.acceptanceWaiting("run-1").arguments(runtimeRoot: runtime).suffix(4),
            ["acceptance", "waiting", "run-1", "--json"]
        )
    }
}
