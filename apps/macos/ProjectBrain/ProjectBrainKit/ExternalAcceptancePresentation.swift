import Foundation

public enum AcceptanceGateState: String, Equatable, Sendable {
    case blocking
    case pending
    case passed
}

public struct ExternalAcceptancePresentation: Equatable, Sendable {
    public let state: AcceptanceGateState
    public let title: String
    public let nextAction: String
    public let canGenerateChallenge: Bool
    public let canCopyPrompt: Bool
    public let canCancel: Bool
    public let shouldAutoRefresh: Bool
    public let historicalTransportProbePassed: Bool
    public let applicableCurrentTransportProbe: Bool
    public let currentConnectionHealthy: Bool

    public static func make(
        connection: ConnectionSnapshot,
        acceptance: ExternalAcceptanceStatusResponse?,
        appVersion: String,
        challengeAvailable: Bool
    ) -> Self {
        let connectionHealthy = connection.tunnelConfigured
            && connection.tunnelClientAvailable
            && connection.localMCPTransportHealthy
            && connection.tunnelProcessRunning
            && connection.tunnelHealthy
            && connection.tunnelReady
        let historicalProbe = acceptance?.lastTransportProbe != nil
        let currentTunnelFingerprint = TunnelClient.isValidTunnelID(connection.tunnelID)
            ? TunnelClient.fingerprint(connection.tunnelID)
            : nil
        let applicableProbe = acceptance.map { status in
            guard let probe = status.lastTransportProbe else { return false }
            return connectionHealthy
                && probe.installationFingerprint == status.installationFingerprint
                && probe.appVersion == appVersion
                && probe.coreVersion == status.coreVersion
                && probe.tunnelFingerprint == currentTunnelFingerprint
                && probe.acceptanceContractVersion == status.acceptanceContractVersion
        } ?? false
        let externallyVerified = acceptance?.applicableExternalChatGPTVerification != nil

        guard connection.localMCPTransportHealthy else {
            return value(
                .blocking,
                "Local MCP is not ready",
                "Start Worker/MCP and resolve the local initialize check.",
                historicalProbe: historicalProbe,
                applicableProbe: false,
                connectionHealthy: false
            )
        }
        guard connection.tunnelClientAvailable, connection.tunnelConfigured else {
            return value(
                .blocking,
                "Tunnel setup is incomplete",
                "Install a compatible Tunnel Client, then configure the Tunnel ID and Runtime key.",
                historicalProbe: historicalProbe,
                applicableProbe: false,
                connectionHealthy: false
            )
        }
        guard connection.tunnelProcessRunning, connection.tunnelHealthy, connection.tunnelReady else {
            return value(
                historicalProbe ? .pending : .blocking,
                historicalProbe
                    ? "Historical MCP transport probe retained; current Tunnel is unhealthy"
                    : "Tunnel is not ready",
                "Restore Tunnel process, health, and control-plane readiness.",
                historicalProbe: historicalProbe,
                applicableProbe: false,
                connectionHealthy: false
            )
        }
        guard connection.workspaceConfigured else {
            return value(
                .blocking,
                "Workspace declaration is pending",
                "Confirm the ChatGPT workspace connector configuration is prepared.",
                historicalProbe: historicalProbe,
                applicableProbe: applicableProbe,
                connectionHealthy: connectionHealthy
            )
        }
        if externallyVerified {
            return value(
                .passed,
                "External ChatGPT acceptance passed",
                "Optionally preview a real-project Draft PR acceptance task.",
                historicalProbe: historicalProbe,
                applicableProbe: applicableProbe,
                connectionHealthy: connectionHealthy
            )
        }
        if applicableProbe {
            return value(
                .pending,
                "MCP transport probe passed; ChatGPT acceptance pending",
                "A trusted ChatGPT control-plane attestation is still required.",
                canGenerate: true,
                historicalProbe: true,
                applicableProbe: true,
                connectionHealthy: connectionHealthy
            )
        }
        if historicalProbe {
            return value(
                .pending,
                "Historical MCP transport probe retained; current environment differs",
                "Generate a new probe for this installation, app, Core, Tunnel, and contract set.",
                canGenerate: true,
                historicalProbe: true,
                applicableProbe: false,
                connectionHealthy: connectionHealthy
            )
        }
        guard let current = acceptance?.current else {
            return value(
                .pending,
                "Ready for an MCP transport probe",
                "Generate a one-time challenge. Its source cannot authenticate ChatGPT.",
                canGenerate: true,
                historicalProbe: false,
                applicableProbe: false,
                connectionHealthy: connectionHealthy
            )
        }
        switch current.status {
        case .challengeReady:
            return value(
                .pending,
                "MCP transport challenge ready",
                challengeAvailable
                    ? "Copy the probe prompt and begin waiting. The resulting source remains unattributed."
                    : "The app restarted without persisting challenge plaintext; generate a new challenge.",
                canGenerate: !challengeAvailable,
                canCopy: challengeAvailable,
                canCancel: true,
                shouldRefresh: true,
                historicalProbe: false,
                applicableProbe: false,
                connectionHealthy: connectionHealthy
            )
        case .waitingForChatGPT:
            return value(
                .pending,
                "Waiting for an unattributed MCP transport probe",
                "The call may be local or tunneled and cannot complete external ChatGPT acceptance.",
                canCancel: true,
                shouldRefresh: true,
                historicalProbe: false,
                applicableProbe: false,
                connectionHealthy: connectionHealthy
            )
        case .mcpTransportProbePassed:
            return value(
                .pending,
                "MCP transport probe passed; ChatGPT acceptance pending",
                "A trusted ChatGPT control-plane attestation is still required.",
                canGenerate: true,
                historicalProbe: true,
                applicableProbe: applicableProbe,
                connectionHealthy: connectionHealthy
            )
        case .failed, .expired, .superseded:
            return value(
                .pending,
                "Transport probe \(current.status.title.lowercased())",
                "Generate a new one-time challenge when ready.",
                canGenerate: true,
                historicalProbe: false,
                applicableProbe: false,
                connectionHealthy: connectionHealthy
            )
        case .notStarted:
            return value(
                .pending,
                "Ready for an MCP transport probe",
                "Generate a one-time challenge.",
                canGenerate: true,
                historicalProbe: false,
                applicableProbe: false,
                connectionHealthy: connectionHealthy
            )
        }
    }

    private static func value(
        _ state: AcceptanceGateState,
        _ title: String,
        _ nextAction: String,
        canGenerate: Bool = false,
        canCopy: Bool = false,
        canCancel: Bool = false,
        shouldRefresh: Bool = false,
        historicalProbe: Bool,
        applicableProbe: Bool,
        connectionHealthy: Bool
    ) -> Self {
        Self(
            state: state,
            title: title,
            nextAction: nextAction,
            canGenerateChallenge: canGenerate,
            canCopyPrompt: canCopy,
            canCancel: canCancel,
            shouldAutoRefresh: shouldRefresh,
            historicalTransportProbePassed: historicalProbe,
            applicableCurrentTransportProbe: applicableProbe,
            currentConnectionHealthy: connectionHealthy
        )
    }
}
