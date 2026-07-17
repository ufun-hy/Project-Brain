import Foundation
import XCTest
@testable import ProjectBrainKit

final class ExternalAcceptancePresentationTests: XCTestCase {
    func testChallengeReadyMapsToCopyCancelAndAutomaticWaiting() {
        let presentation = ExternalAcceptancePresentation.make(
            connection: readyConnection(),
            acceptance: status(current: run(status: .challengeReady)),
            challengeAvailable: true
        )
        XCTAssertEqual(presentation.state, .pending)
        XCTAssertTrue(presentation.canCopyPrompt)
        XCTAssertTrue(presentation.canCancel)
        XCTAssertTrue(presentation.shouldAutoRefresh)
        XCTAssertFalse(presentation.canGenerateChallenge)
    }

    func testRestartRecoversCoreRunWithoutPersistingChallengePlaintext() {
        let presentation = ExternalAcceptancePresentation.make(
            connection: readyConnection(),
            acceptance: status(current: run(status: .challengeReady)),
            challengeAvailable: false
        )
        XCTAssertEqual(presentation.state, .pending)
        XCTAssertTrue(presentation.canGenerateChallenge)
        XCTAssertFalse(presentation.canCopyPrompt)
        XCTAssertTrue(presentation.nextAction.contains("restarted"))
    }

    func testHistoricalPassRemainsVisibleWhenCurrentTunnelIsUnhealthy() {
        var connection = readyConnection()
        connection.tunnelReady = false
        let passed = run(status: .passed, verifiedAt: "2026-07-17T02:00:00Z")
        let presentation = ExternalAcceptancePresentation.make(
            connection: connection,
            acceptance: status(current: nil, lastPassed: passed),
            challengeAvailable: false
        )
        XCTAssertEqual(presentation.state, .pending)
        XCTAssertTrue(presentation.historicalPassed)
        XCTAssertFalse(presentation.currentConnectionHealthy)
        XCTAssertTrue(presentation.title.contains("Historical"))
    }

    func testPersistedClientStateCannotRestorePassedWithoutCoreAuthority() throws {
        var connection = readyConnection()
        let passed = run(status: .passed, verifiedAt: "2026-07-17T02:00:00Z")
        connection.applyExternalAuthority(status(current: passed, lastPassed: passed))
        XCTAssertEqual(connection.externalVerification, .passed)

        let restored = try JSONDecoder().decode(
            ConnectionSnapshot.self,
            from: JSONEncoder().encode(connection)
        )
        XCTAssertEqual(restored.externalVerification, .notVerified)
        var authoritative = restored
        authoritative.applyExternalAuthority(status(current: passed, lastPassed: passed))
        XCTAssertEqual(authoritative.externalVerification, .passed)
    }

    func testDiagnosticsContainFingerprintButNoTunnelIDOrChallenge() throws {
        let tunnelID = "tunnel_0123456789abcdef0123456789abcdef"
        var connection = readyConnection()
        connection.tunnelID = tunnelID
        let pending = run(status: .waitingForChatGPT)
        let report = DiagnosticReport(
            generatedAt: "2026-07-17T02:00:00Z",
            appVersion: "0.7.0",
            aggregateStatus: .healthy,
            taskCounts: [:],
            services: [],
            checks: [],
            projects: [],
            connection: connection,
            acceptance: status(current: pending)
        )
        let rendered = String(decoding: try report.encoded(), as: UTF8.self)
        XCTAssertFalse(rendered.contains(tunnelID))
        XCTAssertFalse(rendered.contains("challenge"))
        XCTAssertTrue(rendered.contains(TunnelClient.fingerprint(tunnelID)))
    }

    private func readyConnection() -> ConnectionSnapshot {
        ConnectionSnapshot(
            localMCPStatus: "running",
            localMCPTransportHealthy: true,
            tunnelID: "tunnel_0123456789abcdef0123456789abcdef",
            runtimeTokenConfigured: true,
            tunnelClientAvailable: true,
            tunnelProcessRunning: true,
            tunnelHealthy: true,
            tunnelReady: true,
            tunnelRuntimeState: "ready",
            workspaceConfiguration: .operatorDeclared
        )
    }

    private func status(
        current: ExternalAcceptanceRun?,
        lastPassed: ExternalAcceptanceRun? = nil
    ) -> ExternalAcceptanceStatusResponse {
        ExternalAcceptanceStatusResponse(
            status: "ok",
            current: current,
            lastPassed: lastPassed,
            installationFingerprint: "installation-fingerprint"
        )
    }

    private func run(
        status: ExternalAcceptanceRunStatus,
        verifiedAt: String? = nil
    ) -> ExternalAcceptanceRun {
        ExternalAcceptanceRun(
            runID: "run-1",
            status: status,
            coreVersion: "0.7.0",
            appVersion: "0.7.0",
            installationFingerprint: "installation-fingerprint",
            tunnelFingerprint: "tunnel-fingerprint",
            createdAt: "2026-07-17T01:50:00Z",
            expiresAt: "2026-07-17T02:00:00Z",
            waitingAt: status == .waitingForChatGPT ? "2026-07-17T01:51:00Z" : nil,
            verifiedAt: verifiedAt,
            failureCode: nil,
            ingress: verifiedAt == nil ? nil : "mcp_streamable_http",
            probeCount: verifiedAt == nil ? 0 : 1
        )
    }
}
