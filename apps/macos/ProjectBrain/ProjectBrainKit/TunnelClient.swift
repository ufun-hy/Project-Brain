import CryptoKit
import Foundation

public struct TunnelProcessResult: Equatable, Sendable {
    public let exitCode: Int32
    public let stdout: Data
    public let stderr: Data

    public init(exitCode: Int32, stdout: Data, stderr: Data) {
        self.exitCode = exitCode
        self.stdout = stdout
        self.stderr = stderr
    }
}

public protocol TunnelProcessRunning: Sendable {
    func run(
        executable: URL,
        arguments: [String],
        environment: [String: String]
    ) throws -> TunnelProcessResult
}

public struct FoundationTunnelProcessRunner: TunnelProcessRunning {
    public init() {}

    public func run(
        executable: URL,
        arguments: [String],
        environment: [String: String]
    ) throws -> TunnelProcessResult {
        let process = Process()
        let output = Pipe()
        let error = Pipe()
        process.executableURL = executable
        process.arguments = arguments
        process.environment = environment
        process.standardOutput = output
        process.standardError = error
        try process.run()

        let group = DispatchGroup()
        let lock = NSLock()
        var stdout = Data()
        var stderr = Data()
        group.enter()
        DispatchQueue.global(qos: .userInitiated).async {
            let data = output.fileHandleForReading.readDataToEndOfFile()
            lock.withLock { stdout = data }
            group.leave()
        }
        group.enter()
        DispatchQueue.global(qos: .userInitiated).async {
            let data = error.fileHandleForReading.readDataToEndOfFile()
            lock.withLock { stderr = data }
            group.leave()
        }
        process.waitUntilExit()
        group.wait()
        return TunnelProcessResult(
            exitCode: process.terminationStatus,
            stdout: stdout,
            stderr: stderr
        )
    }
}

public enum TunnelClientError: LocalizedError, Equatable, Sendable {
    case unavailable
    case invalidTunnelID
    case missingToken
    case process(String)
    case invalidResponse

    public var errorDescription: String? {
        switch self {
        case .unavailable:
            "Install the official OpenAI tunnel-client in a supported system location."
        case .invalidTunnelID:
            "Tunnel ID must be tunnel_ followed by 32 lowercase hexadecimal characters."
        case .missingToken:
            "A Runtime API key with Tunnels Read and Use permissions is required."
        case .process(let detail):
            detail
        case .invalidResponse:
            "tunnel-client returned an invalid status response."
        }
    }
}

public struct TunnelConfiguration: Equatable, Sendable {
    public let tunnelID: String
    public let runtimeToken: String

    public init(tunnelID: String, runtimeToken: String) {
        self.tunnelID = tunnelID
        self.runtimeToken = runtimeToken
    }
}

public struct TunnelRuntimeStatus: Equatable, Sendable {
    public let tunnelID: String?
    public let processRunning: Bool
    public let healthy: Bool
    public let ready: Bool
    public let runtimeState: String
    public let uiURL: URL?
    public let detail: String?

    public init(
        tunnelID: String? = nil,
        processRunning: Bool = false,
        healthy: Bool = false,
        ready: Bool = false,
        runtimeState: String = "stopped",
        uiURL: URL? = nil,
        detail: String? = nil
    ) {
        self.tunnelID = tunnelID
        self.processRunning = processRunning
        self.healthy = healthy
        self.ready = ready
        self.runtimeState = runtimeState
        self.uiURL = uiURL
        self.detail = detail.map(SecretRedactor.redact)
    }
}

public struct TunnelStopResult: Equatable, Sendable {
    public let status: TunnelRuntimeStatus
    public let alreadyStopped: Bool

    public init(status: TunnelRuntimeStatus, alreadyStopped: Bool) {
        self.status = status
        self.alreadyStopped = alreadyStopped
    }
}

private struct TunnelPayload: Decodable {
    struct Tunnel: Decodable { let id: String? }

    let tunnelID: String?
    let tunnel: Tunnel?
    let processRunning: Bool?
    let healthy: Bool?
    let ready: Bool?
    let runtimeState: String?
    let uiURL: String?
    let error: String?
    let remoteError: String?

    enum CodingKeys: String, CodingKey {
        case tunnel
        case tunnelID = "tunnel_id"
        case processRunning = "process_running"
        case healthy, ready
        case runtimeState = "runtime_state"
        case uiURL = "ui_url"
        case error
        case remoteError = "remote_error"
    }
}

private struct TunnelStopPayload: Decodable {
    let stopped: Bool?
    let alreadyStopped: Bool?
    let stopError: String?

    enum CodingKeys: String, CodingKey {
        case stopped
        case alreadyStopped = "already_stopped"
        case stopError = "stop_error"
    }
}

public final class TunnelClient: @unchecked Sendable {
    public static let alias = "project-brain"
    public static let profile = "project-brain"
    public static let localMCPURL = URL(string: "http://127.0.0.1:7677/mcp")!
    public static let fixedPATH = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"

    public let executable: URL
    public let profileDirectory: URL
    private let runner: any TunnelProcessRunning
    private let decoder = JSONDecoder()

    public init(
        executable: URL,
        profileDirectory: URL,
        runner: any TunnelProcessRunning = FoundationTunnelProcessRunner()
    ) throws {
        let allowed = Self.allowedExecutableURLs().map(\.standardizedFileURL)
        guard allowed.contains(executable.standardizedFileURL) else {
            throw TunnelClientError.unavailable
        }
        guard profileDirectory.path.hasPrefix("/") else {
            throw TunnelClientError.unavailable
        }
        self.executable = executable.standardizedFileURL
        self.profileDirectory = profileDirectory.standardizedFileURL
        self.runner = runner
    }

    public static func allowedExecutableURLs(
        home: URL = FileManager.default.homeDirectoryForCurrentUser,
        applicationSupportDirectory: URL? = nil
    ) -> [URL] {
        let support = applicationSupportDirectory
            ?? FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        return [
            support.appending(path: TunnelClientInstaller.relativeDestination),
            URL(filePath: "/opt/homebrew/bin/tunnel-client"),
            URL(filePath: "/usr/local/bin/tunnel-client"),
            home.appending(path: ".local/bin/tunnel-client"),
        ]
    }

    public static func discover() -> URL? {
        allowedExecutableURLs().first {
            FileManager.default.isExecutableFile(atPath: $0.path)
        }
    }

    public static func isValidTunnelID(_ value: String) -> Bool {
        value.range(of: #"^tunnel_[0-9a-f]{32}$"#, options: .regularExpression) != nil
    }

    public static func fingerprint(_ tunnelID: String) -> String {
        SHA256.hash(data: Data(tunnelID.utf8))
            .map { String(format: "%02x", $0) }
            .joined()
    }

    public func connect(_ configuration: TunnelConfiguration) throws -> TunnelRuntimeStatus {
        try validate(configuration)
        let arguments = [
            "runtimes", "connect",
            "--alias", Self.alias,
            "--tunnel-id", configuration.tunnelID,
            "--profile", Self.profile,
            "--profile-dir", profileDirectory.path,
            "--mcp-server-url", Self.localMCPURL.absoluteString,
            "--runtime-api-key", "env:CONTROL_PLANE_API_KEY",
            "--json",
        ]
        let result = try run(arguments, token: configuration.runtimeToken)
        guard result.exitCode == 0 else { throw processError(result) }
        return try decodeStatus(result.stdout, fallbackTunnelID: configuration.tunnelID)
    }

    public func status(runtimeToken: String?) throws -> TunnelRuntimeStatus {
        let result = try run(
            ["runtimes", "status", Self.alias, "--json"],
            token: runtimeToken
        )
        if let status = try? decodeStatus(result.stdout, fallbackTunnelID: nil) {
            return status
        }
        guard result.exitCode == 0 else { throw processError(result) }
        throw TunnelClientError.invalidResponse
    }

    public func stop(runtimeToken: String?) throws -> TunnelStopResult {
        let result = try run(
            ["runtimes", "stop", Self.alias, "--json"],
            token: runtimeToken
        )
        guard result.exitCode == 0 else { throw processError(result) }
        guard !result.stdout.isEmpty,
              let payload = try? decoder.decode(TunnelStopPayload.self, from: result.stdout),
              let stopped = payload.stopped else {
            throw TunnelClientError.invalidResponse
        }
        guard stopped else {
            let detail = SecretRedactor.redact(
                payload.stopError ?? "tunnel-client did not confirm that the runtime stopped."
            )
            throw TunnelClientError.process(detail)
        }
        return TunnelStopResult(
            status: TunnelRuntimeStatus(runtimeState: "stopped"),
            alreadyStopped: payload.alreadyStopped ?? false
        )
    }

    public func reconnect(_ configuration: TunnelConfiguration) throws -> TunnelRuntimeStatus {
        _ = try? stop(runtimeToken: configuration.runtimeToken)
        return try connect(configuration)
    }

    private func validate(_ configuration: TunnelConfiguration) throws {
        guard Self.isValidTunnelID(configuration.tunnelID) else {
            throw TunnelClientError.invalidTunnelID
        }
        guard !configuration.runtimeToken.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            throw TunnelClientError.missingToken
        }
    }

    private func run(_ arguments: [String], token: String?) throws -> TunnelProcessResult {
        var environment = [
            "HOME": FileManager.default.homeDirectoryForCurrentUser.path,
            "PATH": Self.fixedPATH,
        ]
        if let temporary = ProcessInfo.processInfo.environment["TMPDIR"] {
            environment["TMPDIR"] = temporary
        }
        if let token, !token.isEmpty { environment["CONTROL_PLANE_API_KEY"] = token }
        do {
            return try runner.run(
                executable: executable,
                arguments: arguments,
                environment: environment
            )
        } catch {
            throw TunnelClientError.process(SecretRedactor.redact(error.localizedDescription))
        }
    }

    private func decodeStatus(
        _ data: Data,
        fallbackTunnelID: String?
    ) throws -> TunnelRuntimeStatus {
        guard !data.isEmpty, let payload = try? decoder.decode(TunnelPayload.self, from: data) else {
            throw TunnelClientError.invalidResponse
        }
        return TunnelRuntimeStatus(
            tunnelID: payload.tunnelID ?? payload.tunnel?.id ?? fallbackTunnelID,
            processRunning: payload.processRunning ?? false,
            healthy: payload.healthy ?? false,
            ready: payload.ready ?? false,
            runtimeState: payload.runtimeState ?? "unknown",
            uiURL: payload.uiURL.flatMap(URL.init(string:)),
            detail: payload.error ?? payload.remoteError
        )
    }

    private func processError(_ result: TunnelProcessResult) -> TunnelClientError {
        let bounded = Data((result.stderr.isEmpty ? result.stdout : result.stderr).prefix(8_192))
        let detail = SecretRedactor.redact(String(decoding: bounded, as: UTF8.self))
        return .process(detail.isEmpty ? "tunnel-client operation failed." : detail)
    }
}
