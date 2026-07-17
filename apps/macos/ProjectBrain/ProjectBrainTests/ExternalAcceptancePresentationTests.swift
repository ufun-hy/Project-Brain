import Foundation
import XCTest
@testable import ProjectBrainKit

final class ExternalAcceptancePresentationTests: XCTestCase {
    func testChallengeReadyMapsToCopyCancelAndAutomaticWaiting() {
        let presentation = ExternalAcceptancePresentation.make(
            connection: readyConnection(),
            acceptance: status(current: run(status: .challengeReady)),
            appVersion: "0.7.0",
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
            appVersion: "0.7.0",
            challengeAvailable: false
        )
        XCTAssertEqual(presentation.state, .pending)
        XCTAssertTrue(presentation.canGenerateChallenge)
        XCTAssertFalse(presentation.canCopyPrompt)
        XCTAssertTrue(presentation.nextAction.contains("restarted"))
    }

    func testHistoricalTransportProbeRemainsPendingWhenTunnelIsUnhealthy() {
        var connection = readyConnection()
        connection.tunnelReady = false
        let probe = run(
            status: .mcpTransportProbePassed,
            verifiedAt: "2026-07-17T02:00:00Z"
        )
        let presentation = ExternalAcceptancePresentation.make(
            connection: connection,
            acceptance: status(current: nil, lastTransportProbe: probe),
            appVersion: "0.7.0",
            challengeAvailable: false
        )
        XCTAssertEqual(presentation.state, .pending)
        XCTAssertTrue(presentation.historicalTransportProbePassed)
        XCTAssertFalse(presentation.applicableCurrentTransportProbe)
        XCTAssertFalse(presentation.currentConnectionHealthy)
        XCTAssertTrue(presentation.title.contains("Historical"))
    }

    func testApplicableTransportProbeNeverSetsExternalAuthority() throws {
        var connection = readyConnection()
        let probe = run(
            status: .mcpTransportProbePassed,
            verifiedAt: "2026-07-17T02:00:00Z"
        )
        let authority = status(current: probe, lastTransportProbe: probe)
        connection.applyExternalAuthority(authority)
        XCTAssertEqual(connection.externalVerification, .notVerified)

        let presentation = ExternalAcceptancePresentation.make(
            connection: connection,
            acceptance: authority,
            appVersion: "0.7.0",
            challengeAvailable: false
        )
        XCTAssertEqual(presentation.state, .pending)
        XCTAssertTrue(presentation.applicableCurrentTransportProbe)
        XCTAssertTrue(presentation.title.contains("ChatGPT acceptance pending"))

        let restored = try JSONDecoder().decode(
            ConnectionSnapshot.self,
            from: JSONEncoder().encode(connection)
        )
        XCTAssertEqual(restored.externalVerification, .notVerified)

        var failedTransport = readyConnection()
        failedTransport.applyExternalAuthority(status(current: run(status: .failed)))
        XCTAssertEqual(failedTransport.externalVerification, .notVerified)
    }

    func testTransportApplicabilityRequiresEntireCanonicalBindingSet() {
        let connection = readyConnection()
        let canonical = run(
            status: .mcpTransportProbePassed,
            verifiedAt: "2026-07-17T02:00:00Z"
        )
        XCTAssertTrue(presentation(connection, status(lastTransportProbe: canonical)).applicableCurrentTransportProbe)

        let mismatches = [
            run(status: .mcpTransportProbePassed, verifiedAt: "2026-07-17T02:00:00Z", installation: "other-install"),
            run(status: .mcpTransportProbePassed, verifiedAt: "2026-07-17T02:00:00Z", appVersion: "0.7.1"),
            run(status: .mcpTransportProbePassed, verifiedAt: "2026-07-17T02:00:00Z", coreVersion: "0.7.1"),
            run(status: .mcpTransportProbePassed, verifiedAt: "2026-07-17T02:00:00Z", tunnelFingerprint: "f".padding(toLength: 64, withPad: "f", startingAt: 0)),
            run(status: .mcpTransportProbePassed, verifiedAt: "2026-07-17T02:00:00Z", contractVersion: 1),
        ]
        for mismatch in mismatches {
            let value = presentation(connection, status(lastTransportProbe: mismatch))
            XCTAssertFalse(value.applicableCurrentTransportProbe)
            XCTAssertEqual(value.state, .pending)
            XCTAssertTrue(value.title.contains("current environment differs"))
        }
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

    private func presentation(
        _ connection: ConnectionSnapshot,
        _ acceptance: ExternalAcceptanceStatusResponse
    ) -> ExternalAcceptancePresentation {
        .make(
            connection: connection,
            acceptance: acceptance,
            appVersion: "0.7.0",
            challengeAvailable: false
        )
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
        current: ExternalAcceptanceRun? = nil,
        lastTransportProbe: ExternalAcceptanceRun? = nil
    ) -> ExternalAcceptanceStatusResponse {
        ExternalAcceptanceStatusResponse(
            status: "ok",
            current: current,
            lastTransportProbe: lastTransportProbe,
            coreVersion: "0.7.0",
            acceptanceContractVersion: 2,
            installationFingerprint: "installation-fingerprint"
        )
    }

    private func run(
        status: ExternalAcceptanceRunStatus,
        verifiedAt: String? = nil,
        installation: String = "installation-fingerprint",
        appVersion: String = "0.7.0",
        coreVersion: String = "0.7.0",
        tunnelFingerprint: String? = nil,
        contractVersion: Int = 2
    ) -> ExternalAcceptanceRun {
        let tunnel = tunnelFingerprint ?? TunnelClient.fingerprint(
            "tunnel_0123456789abcdef0123456789abcdef"
        )
        return ExternalAcceptanceRun(
            runID: "run-1",
            status: status,
            coreVersion: coreVersion,
            appVersion: appVersion,
            acceptanceContractVersion: contractVersion,
            installationFingerprint: installation,
            tunnelFingerprint: tunnel,
            createdAt: "2026-07-17T01:50:00Z",
            expiresAt: "2026-07-17T02:00:00Z",
            waitingAt: status == .waitingForChatGPT ? "2026-07-17T01:51:00Z" : nil,
            verifiedAt: verifiedAt,
            failureCode: nil,
            ingress: verifiedAt == nil ? nil : "local_or_tunneled_mcp_unattributed",
            probeCount: verifiedAt == nil ? 0 : 1
        )
    }
}
