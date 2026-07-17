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
    public let historicalPassed: Bool
    public let currentConnectionHealthy: Bool

    public static func make(
        connection: ConnectionSnapshot,
        acceptance: ExternalAcceptanceStatusResponse?,
        challengeAvailable: Bool
    ) -> Self {
        let connectionHealthy = connection.tunnelConfigured
            && connection.tunnelClientAvailable
            && connection.localMCPTransportHealthy
            && connection.tunnelProcessRunning
            && connection.tunnelHealthy
            && connection.tunnelReady
        let historicalPassed = acceptance?.lastPassed != nil
        guard connection.localMCPTransportHealthy else {
            return value(
                .blocking,
                "Local MCP is not ready",
                "Start Worker/MCP and resolve the local initialize check.",
                historicalPassed: historicalPassed,
                connectionHealthy: false
            )
        }
        guard connection.tunnelClientAvailable, connection.tunnelConfigured else {
            return value(
                .blocking,
                "Tunnel setup is incomplete",
                "Install a compatible Tunnel Client, then configure the Tunnel ID and Runtime key.",
                historicalPassed: historicalPassed,
                connectionHealthy: false
            )
        }
        guard connection.tunnelProcessRunning, connection.tunnelHealthy, connection.tunnelReady else {
            return value(
                historicalPassed ? .pending : .blocking,
                historicalPassed
                    ? "Historical acceptance passed; current Tunnel is unhealthy"
                    : "Tunnel is not ready",
                "Restore Tunnel process, health, and control-plane readiness.",
                historicalPassed: historicalPassed,
                connectionHealthy: false
            )
        }
        guard connection.workspaceConfigured else {
            return value(
                .blocking,
                "Workspace declaration is pending",
                "Confirm the ChatGPT workspace connector configuration is prepared.",
                historicalPassed: historicalPassed,
                connectionHealthy: connectionHealthy
            )
        }
        guard let current = acceptance?.current else {
            return value(
                historicalPassed ? .passed : .pending,
                historicalPassed ? "External acceptance passed" : "Ready for external acceptance",
                historicalPassed
                    ? "Optionally run the real-project Draft PR acceptance task."
                    : "Generate a one-time challenge.",
                canGenerate: !historicalPassed,
                historicalPassed: historicalPassed,
                connectionHealthy: connectionHealthy
            )
        }
        switch current.status {
        case .challengeReady:
            return value(
                .pending,
                "Acceptance challenge ready",
                challengeAvailable
                    ? "Copy the generated ChatGPT prompt and begin waiting."
                    : "The app restarted without persisting challenge plaintext; generate a new challenge.",
                canGenerate: !challengeAvailable,
                canCopy: challengeAvailable,
                canCancel: true,
                shouldRefresh: true,
                historicalPassed: historicalPassed,
                connectionHealthy: connectionHealthy
            )
        case .waitingForChatGPT:
            return value(
                .pending,
                "Waiting for a real ChatGPT connector call",
                "Use the Project Brain Connector in ChatGPT; this view refreshes automatically.",
                canCancel: true,
                shouldRefresh: true,
                historicalPassed: historicalPassed,
                connectionHealthy: connectionHealthy
            )
        case .passed:
            return value(
                .passed,
                "External acceptance passed",
                "Optionally preview a real-project Draft PR acceptance task.",
                historicalPassed: true,
                connectionHealthy: connectionHealthy
            )
        case .failed, .expired, .superseded:
            return value(
                historicalPassed ? .passed : .pending,
                historicalPassed
                    ? "Historical acceptance passed"
                    : "Acceptance \(current.status.title.lowercased())",
                "Generate a new one-time challenge when ready.",
                canGenerate: true,
                historicalPassed: historicalPassed,
                connectionHealthy: connectionHealthy
            )
        case .notStarted:
            return value(
                .pending,
                "Ready for external acceptance",
                "Generate a one-time challenge.",
                canGenerate: true,
                historicalPassed: historicalPassed,
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
        historicalPassed: Bool,
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
            historicalPassed: historicalPassed,
            currentConnectionHealthy: connectionHealthy
        )
    }
}
