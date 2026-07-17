import Foundation
import XCTest
@testable import ProjectBrainKit

final class OnboardingDiagnosticsTests: XCTestCase {
    func testOnboardingProgressResumesFromPersistedStage() throws {
        let suite = "ProjectBrainTests.\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let store = OnboardingStore(defaults: defaults, key: "onboarding")
        let progress = OnboardingProgress(
            stage: .services,
            selectedRepository: "/Users/example/repo",
            projectPlanSHA256: "abc123"
        )
        store.save(progress)
        XCTAssertEqual(store.load(), progress)
    }

    func testDiagnosticsRedactPathsAndCredentialsAndContainNoSecretField() throws {
        let check = HealthCheck(
            name: "runtime",
            status: "failed",
            detail: "/Users/example/private token=ghp_abcdefghijklmnopqrstuvwxyz1234567890"
        )
        let report = DiagnosticReport(
            generatedAt: "2026-07-16T00:00:00Z",
            appVersion: "0.6.0",
            aggregateStatus: .needsAttention,
            taskCounts: ["failed": 1],
            services: [],
            checks: [check],
            projects: [],
            connection: ConnectionSnapshot(
                tunnelID: "tunnel_0123456789abcdef0123456789abcdef",
                runtimeTokenConfigured: true
            )
        )
        let rendered = String(decoding: try report.encoded(), as: UTF8.self)
        XCTAssertFalse(rendered.contains("/Users/example"))
        XCTAssertFalse(rendered.contains("ghp_"))
        XCTAssertFalse(rendered.lowercased().contains("token\""))
    }

    func testExternalAcceptanceDefaultsPendingAndIsNotDerivedFromLocalMCP() {
        let connection = ConnectionSnapshot(localMCPStatus: "running")
        XCTAssertEqual(connection.externalAcceptance, .notStarted)
        XCTAssertNotEqual(connection.externalAcceptance, .passed)
    }

    func testTunnelReadyToTestRequiresVerifiedLocalTransportAndRuntimeStatus() {
        let tunnelID = "tunnel_0123456789abcdef0123456789abcdef"
        let tokenOnly = ConnectionSnapshot(
            tunnelID: tunnelID,
            runtimeTokenConfigured: true
        )
        XCTAssertEqual(tokenOnly.externalAcceptance, .notStarted)

        let ready = ConnectionSnapshot(
            localMCPTransportHealthy: true,
            tunnelID: tunnelID,
            runtimeTokenConfigured: true,
            tunnelClientAvailable: true,
            tunnelProcessRunning: true,
            tunnelHealthy: true,
            tunnelReady: true,
            workspaceConfiguration: .operatorDeclared
        )
        XCTAssertEqual(ready.externalAcceptance, .readyToTest)
        XCTAssertEqual(ready.externalVerification, .notVerified)
    }

    func testOperatorDeclarationDoesNotBecomeExternalVerification() {
        let connection = ConnectionSnapshot(workspaceConfiguration: .operatorDeclared)
        XCTAssertTrue(connection.workspaceConfigured)
        XCTAssertEqual(connection.externalVerification, .notVerified)
        XCTAssertNotEqual(connection.externalAcceptance, .passed)
    }

    func testErrorCategoriesProvideUserTitleAndNextAction() {
        let error = CoreClientError.core(category: "service", message: "launchd stopped")
        XCTAssertEqual(error.userTitle, "Background service needs attention")
        XCTAssertTrue(error.nextAction.contains("Connection Center"))
    }
}
