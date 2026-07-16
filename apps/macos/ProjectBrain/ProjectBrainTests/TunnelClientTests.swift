import Foundation
import XCTest
@testable import ProjectBrainKit

private final class CapturingTunnelRunner: TunnelProcessRunning, @unchecked Sendable {
    var results: [TunnelProcessResult]
    private(set) var calls: [(URL, [String], [String: String])] = []

    init(results: [TunnelProcessResult]) { self.results = results }

    func run(
        executable: URL,
        arguments: [String],
        environment: [String: String]
    ) throws -> TunnelProcessResult {
        calls.append((executable, arguments, environment))
        return results.removeFirst()
    }
}

final class TunnelClientTests: XCTestCase {
    private let tunnelID = "tunnel_0123456789abcdef0123456789abcdef"
    private let token = "sk-runtime-super-secret-value"

    private func payload(
        running: Bool = true,
        healthy: Bool = true,
        ready: Bool = true
    ) -> TunnelProcessResult {
        let value = """
        {"tunnel_id":"\(tunnelID)","process_running":\(running),"healthy":\(healthy),"ready":\(ready),"runtime_state":"\(ready ? "ready" : "degraded")","ui_url":"http://127.0.0.1:4321/ui"}
        """
        return .init(exitCode: 0, stdout: Data(value.utf8), stderr: Data())
    }

    private func client(_ runner: CapturingTunnelRunner) throws -> TunnelClient {
        try TunnelClient(
            executable: URL(filePath: "/opt/homebrew/bin/tunnel-client"),
            profileDirectory: URL(filePath: "/Users/example/.project-brain/tunnel/profiles"),
            runner: runner
        )
    }

    func testConnectUsesClosedOfficialRuntimeArgvAndEnvironmentBackedToken() throws {
        let runner = CapturingTunnelRunner(results: [payload()])
        let status = try client(runner).connect(
            TunnelConfiguration(tunnelID: tunnelID, runtimeToken: token)
        )
        XCTAssertTrue(status.ready)
        let call = try XCTUnwrap(runner.calls.first)
        XCTAssertEqual(call.0.path, "/opt/homebrew/bin/tunnel-client")
        XCTAssertEqual(
            call.1,
            [
                "runtimes", "connect", "--alias", "project-brain",
                "--tunnel-id", tunnelID,
                "--profile", "project-brain",
                "--profile-dir", "/Users/example/.project-brain/tunnel/profiles",
                "--mcp-server-url", "http://127.0.0.1:7677/mcp",
                "--runtime-api-key", "env:CONTROL_PLANE_API_KEY", "--json",
            ]
        )
        XCTAssertEqual(call.2["CONTROL_PLANE_API_KEY"], token)
        XCTAssertFalse(call.1.contains(token))
        XCTAssertEqual(call.2["PATH"], TunnelClient.fixedPATH)
    }

    func testInvalidTunnelIDAndMissingTokenNeverLaunchProcess() throws {
        let runner = CapturingTunnelRunner(results: [])
        let client = try client(runner)
        XCTAssertThrowsError(try client.connect(.init(tunnelID: "tunnel_BAD", runtimeToken: token))) {
            XCTAssertEqual($0 as? TunnelClientError, .invalidTunnelID)
        }
        XCTAssertThrowsError(try client.connect(.init(tunnelID: tunnelID, runtimeToken: ""))) {
            XCTAssertEqual($0 as? TunnelClientError, .missingToken)
        }
        XCTAssertTrue(runner.calls.isEmpty)
    }

    func testInvalidTokenFailureIsRedacted() throws {
        let failure = TunnelProcessResult(
            exitCode: 2,
            stdout: Data(),
            stderr: Data("api_key=\(token) unauthorized".utf8)
        )
        let runner = CapturingTunnelRunner(results: [failure])
        XCTAssertThrowsError(
            try client(runner).connect(.init(tunnelID: tunnelID, runtimeToken: token))
        ) { error in
            XCTAssertFalse(error.localizedDescription.contains(token))
            XCTAssertTrue(error.localizedDescription.contains("<redacted>"))
        }
    }

    func testInterruptedRuntimeIsNotReadyAndReconnectStopsThenConnects() throws {
        let runner = CapturingTunnelRunner(results: [
            payload(running: false, healthy: false, ready: false),
            .init(exitCode: 0, stdout: Data(#"{"stopped":true}"#.utf8), stderr: Data()),
            payload(),
        ])
        let client = try client(runner)
        let interrupted = try client.status(runtimeToken: token)
        XCTAssertFalse(interrupted.ready)
        let recovered = try client.reconnect(.init(tunnelID: tunnelID, runtimeToken: token))
        XCTAssertTrue(recovered.ready)
        XCTAssertEqual(runner.calls.map { Array($0.1.prefix(2)) }, [
            ["runtimes", "status"],
            ["runtimes", "stop"],
            ["runtimes", "connect"],
        ])
    }
}
