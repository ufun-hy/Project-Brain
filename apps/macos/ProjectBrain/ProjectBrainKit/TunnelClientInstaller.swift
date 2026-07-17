import CryptoKit
import Darwin
import Foundation

public struct TunnelCompatibilityManifest: Codable, Equatable, Sendable {
    public struct Entry: Codable, Equatable, Sendable {
        public let version: String
        public let platform: String
        public let architectures: [String]
        public let runtimesContract: Int

        public init(
            version: String,
            platform: String,
            architectures: [String],
            runtimesContract: Int
        ) {
            self.version = version
            self.platform = platform
            self.architectures = architectures
            self.runtimesContract = runtimesContract
        }

        enum CodingKeys: String, CodingKey {
            case version, platform, architectures
            case runtimesContract = "runtimes_contract"
        }
    }

    public let schemaVersion: Int
    public let supported: [Entry]

    public init(schemaVersion: Int, supported: [Entry]) {
        self.schemaVersion = schemaVersion
        self.supported = supported
    }

    public static func load(from url: URL) throws -> Self {
        let data = try Data(contentsOf: url, options: [.mappedIfSafe])
        let value = try JSONDecoder().decode(Self.self, from: data)
        guard value.schemaVersion == 1, !value.supported.isEmpty else {
            throw TunnelClientInstallerError.invalidManifest
        }
        return value
    }

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case supported
    }
}

public enum TunnelBinaryArchitecture: String, Codable, Equatable, Sendable {
    case arm64
    case x86_64
    case unknown

    public static var current: Self {
        var system = utsname()
        uname(&system)
        let machine = withUnsafePointer(to: &system.machine) {
            $0.withMemoryRebound(to: CChar.self, capacity: 1) { String(cString: $0) }
        }
        switch machine {
        case "arm64": return .arm64
        case "x86_64": return .x86_64
        default: return .unknown
        }
    }
}

public struct TunnelInstallerProcessResult: Equatable, Sendable {
    public let exitCode: Int32
    public let stdout: Data
    public let stderr: Data
    public let timedOut: Bool
    public let stdoutExceededLimit: Bool
    public let stderrExceededLimit: Bool

    public init(
        exitCode: Int32,
        stdout: Data,
        stderr: Data,
        timedOut: Bool = false,
        stdoutExceededLimit: Bool = false,
        stderrExceededLimit: Bool = false
    ) {
        self.exitCode = exitCode
        self.stdout = stdout
        self.stderr = stderr
        self.timedOut = timedOut
        self.stdoutExceededLimit = stdoutExceededLimit
        self.stderrExceededLimit = stderrExceededLimit
    }
}

public protocol TunnelInstallerProcessRunning: Sendable {
    func run(
        executable: URL,
        arguments: [String],
        timeout: TimeInterval,
        outputLimit: Int
    ) throws -> TunnelInstallerProcessResult
}

private final class BoundedPipeDrain: @unchecked Sendable {
    private let lock = NSLock()
    private var storage = Data()
    private var exceeded = false
    private let limit: Int

    init(limit: Int) { self.limit = limit }

    func append(_ data: Data) {
        lock.withLock {
            let remaining = max(0, limit - storage.count)
            if data.count > remaining { exceeded = true }
            if remaining > 0 { storage.append(data.prefix(remaining)) }
        }
    }

    func result() -> (Data, Bool) { lock.withLock { (storage, exceeded) } }
}

public struct FoundationTunnelInstallerProcessRunner: TunnelInstallerProcessRunning {
    public init() {}

    public func run(
        executable: URL,
        arguments: [String],
        timeout: TimeInterval,
        outputLimit: Int
    ) throws -> TunnelInstallerProcessResult {
        let process = Process()
        let output = Pipe()
        let error = Pipe()
        process.executableURL = executable
        process.arguments = arguments
        process.environment = [
            "HOME": FileManager.default.homeDirectoryForCurrentUser.path,
            "PATH": TunnelClient.fixedPATH,
        ]
        process.standardOutput = output
        process.standardError = error

        let stdout = BoundedPipeDrain(limit: outputLimit)
        let stderr = BoundedPipeDrain(limit: outputLimit)
        let drains = DispatchGroup()
        for (handle, target) in [
            (output.fileHandleForReading, stdout),
            (error.fileHandleForReading, stderr),
        ] {
            drains.enter()
            DispatchQueue.global(qos: .userInitiated).async {
                while true {
                    let data = handle.availableData
                    if data.isEmpty { break }
                    target.append(data)
                }
                drains.leave()
            }
        }
        let terminated = DispatchSemaphore(value: 0)
        process.terminationHandler = { _ in terminated.signal() }
        try process.run()
        let deadline = DispatchTime.now() + timeout
        let timedOut = terminated.wait(timeout: deadline) == .timedOut
        if timedOut {
            process.terminate()
            if terminated.wait(timeout: .now() + 1) == .timedOut {
                Darwin.kill(process.processIdentifier, SIGKILL)
                _ = terminated.wait(timeout: .now() + 1)
            }
        }
        process.waitUntilExit()
        drains.wait()
        let (stdoutData, stdoutExceeded) = stdout.result()
        let (stderrData, stderrExceeded) = stderr.result()
        return TunnelInstallerProcessResult(
            exitCode: process.terminationStatus,
            stdout: stdoutData,
            stderr: stderrData,
            timedOut: timedOut,
            stdoutExceededLimit: stdoutExceeded,
            stderrExceededLimit: stderrExceeded
        )
    }
}

public struct TunnelClientValidation: Equatable, Sendable {
    public let source: URL
    public let resolvedSource: URL
    public let version: String
    public let architecture: TunnelBinaryArchitecture
    public let sha256: String
    public let manifestSchemaVersion: Int
    public let runtimesContract: Int
    public let sourceAttestation: String

    public init(
        source: URL,
        resolvedSource: URL,
        version: String,
        architecture: TunnelBinaryArchitecture,
        sha256: String,
        manifestSchemaVersion: Int,
        runtimesContract: Int,
        sourceAttestation: String = "User must confirm this file came from the official OpenAI Platform Tunnels page."
    ) {
        self.source = source
        self.resolvedSource = resolvedSource
        self.version = version
        self.architecture = architecture
        self.sha256 = sha256
        self.manifestSchemaVersion = manifestSchemaVersion
        self.runtimesContract = runtimesContract
        self.sourceAttestation = sourceAttestation
    }
}

public enum TunnelClientInstallAction: String, Equatable, Sendable {
    case installed
    case upgraded
    case current
}

public struct TunnelClientInstallResult: Equatable, Sendable {
    public let action: TunnelClientInstallAction
    public let validation: TunnelClientValidation
    public let destination: URL

    public init(
        action: TunnelClientInstallAction,
        validation: TunnelClientValidation,
        destination: URL
    ) {
        self.action = action
        self.validation = validation
        self.destination = destination
    }
}

public enum TunnelClientInstallerError: LocalizedError, Equatable, Sendable {
    case invalidSelection
    case invalidManifest
    case invalidFile(String)
    case unsupportedArchitecture
    case unsupportedVersion
    case versionTimeout
    case versionOutputExceeded
    case versionCheckFailed
    case candidateChanged
    case filesystem(String)
    case stopNotConfirmed

    public var errorDescription: String? {
        switch self {
        case .invalidSelection:
            "Select exactly one regular Tunnel Client file."
        case .invalidManifest:
            "The bundled Tunnel Client compatibility manifest is invalid."
        case .invalidFile(let message), .filesystem(let message):
            message
        case .unsupportedArchitecture:
            "This Tunnel Client does not contain the supported Mac architecture."
        case .unsupportedVersion:
            "This Tunnel Client version is not in the reviewed compatibility manifest."
        case .versionTimeout:
            "Tunnel Client version validation timed out."
        case .versionOutputExceeded:
            "Tunnel Client version output exceeded the safety limit."
        case .versionCheckFailed:
            "Tunnel Client version validation returned an invalid response."
        case .candidateChanged:
            "The selected Tunnel Client changed after validation; select it again."
        case .stopNotConfirmed:
            "The managed Tunnel runtime must be confirmed stopped before removing the binary."
        }
    }
}

public final class TunnelClientInstaller: @unchecked Sendable {
    public static let relativeDestination = "Project Brain/bin/tunnel-client"
    public static let versionTimeout: TimeInterval = 5
    public static let outputLimit = 8_192

    private let applicationSupportDirectory: URL
    private let manifest: TunnelCompatibilityManifest
    private let requiredArchitecture: TunnelBinaryArchitecture
    private let fileManager: FileManager
    private let runner: any TunnelInstallerProcessRunning

    public init(
        manifest: TunnelCompatibilityManifest,
        applicationSupportDirectory: URL? = nil,
        requiredArchitecture: TunnelBinaryArchitecture = .current,
        fileManager: FileManager = .default,
        runner: any TunnelInstallerProcessRunning = FoundationTunnelInstallerProcessRunner()
    ) throws {
        guard manifest.schemaVersion == 1, !manifest.supported.isEmpty else {
            throw TunnelClientInstallerError.invalidManifest
        }
        self.manifest = manifest
        self.requiredArchitecture = requiredArchitecture
        self.fileManager = fileManager
        self.runner = runner
        self.applicationSupportDirectory = applicationSupportDirectory
            ?? fileManager.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
    }

    public var destination: URL {
        applicationSupportDirectory.appending(path: Self.relativeDestination)
            .standardizedFileURL
    }

    public func prepareImport(selectedURLs: [URL]) throws -> TunnelClientValidation {
        guard selectedURLs.count == 1 else { throw TunnelClientInstallerError.invalidSelection }
        return try validate(selectedURLs[0])
    }

    public func validateInstalled() throws -> TunnelClientValidation? {
        guard fileManager.fileExists(atPath: destination.path) else { return nil }
        return try validate(destination)
    }

    public func validate(_ source: URL) throws -> TunnelClientValidation {
        let source = source.standardizedFileURL
        try validateRegularExecutable(source)
        let resolved = source.resolvingSymlinksInPath().standardizedFileURL
        try validateRegularExecutable(resolved)
        let architectures = try architectures(of: resolved)
        guard architectures.contains(requiredArchitecture) else {
            throw TunnelClientInstallerError.unsupportedArchitecture
        }
        let version = try version(of: resolved)
        guard let compatibility = manifest.supported.first(where: {
            $0.version == version
                && $0.platform == "macos"
                && $0.architectures.contains(requiredArchitecture.rawValue)
        }) else {
            throw TunnelClientInstallerError.unsupportedVersion
        }
        return TunnelClientValidation(
            source: source,
            resolvedSource: resolved,
            version: version,
            architecture: requiredArchitecture,
            sha256: try sha256(resolved),
            manifestSchemaVersion: manifest.schemaVersion,
            runtimesContract: compatibility.runtimesContract
        )
    }

    public func install(
        _ plan: TunnelClientValidation,
        onActivated: @Sendable (URL, TunnelClientInstallAction) throws -> Void = { _, _ in }
    ) throws -> TunnelClientInstallResult {
        let latest = try validate(plan.source)
        guard latest == plan else { throw TunnelClientInstallerError.candidateChanged }
        let destination = destination
        let bin = destination.deletingLastPathComponent()
        try validateManagedDirectory(applicationSupportDirectory)
        try validateManagedDirectory(
            applicationSupportDirectory.appending(path: "Project Brain")
        )
        try validateManagedDirectory(bin)
        try fileManager.createDirectory(
            at: bin,
            withIntermediateDirectories: true,
            attributes: [.posixPermissions: 0o700]
        )
        try validateManagedDirectory(bin)
        try fileManager.setAttributes([.posixPermissions: 0o700], ofItemAtPath: bin.path)
        let candidate = bin.appending(path: ".tunnel-client.\(UUID().uuidString).candidate")
        let rollback = bin.appending(path: ".tunnel-client.rollback")
        var candidateExists = false
        do {
            try fileManager.copyItem(at: plan.resolvedSource, to: candidate)
            candidateExists = true
            try fileManager.setAttributes([.posixPermissions: 0o755], ofItemAtPath: candidate.path)
            try syncFile(candidate)
            let candidateValidation = try validate(candidate)
            guard candidateValidation.version == plan.version,
                  candidateValidation.architecture == plan.architecture,
                  candidateValidation.sha256 == plan.sha256 else {
                throw TunnelClientInstallerError.candidateChanged
            }

            let upgrading = fileManager.fileExists(atPath: destination.path)
            if upgrading {
                let installed = try validate(destination)
                if installed.sha256 == plan.sha256 {
                    try fileManager.removeItem(at: candidate)
                    candidateExists = false
                    try syncDirectory(bin)
                    return TunnelClientInstallResult(
                        action: .current,
                        validation: installed,
                        destination: destination
                    )
                }
                if fileManager.fileExists(atPath: rollback.path) {
                    try fileManager.removeItem(at: rollback)
                }
                try fileManager.copyItem(at: destination, to: rollback)
                try fileManager.setAttributes([.posixPermissions: 0o755], ofItemAtPath: rollback.path)
                try syncFile(rollback)
            }

            try atomicRename(candidate, destination)
            candidateExists = false
            try syncDirectory(bin)
            let action: TunnelClientInstallAction = upgrading ? .upgraded : .installed
            do {
                let installed = try validate(destination)
                guard installed.sha256 == plan.sha256 else {
                    throw TunnelClientInstallerError.candidateChanged
                }
                try onActivated(destination, action)
            } catch {
                if upgrading, fileManager.fileExists(atPath: rollback.path) {
                    try atomicRename(rollback, destination)
                    try syncDirectory(bin)
                    try? onActivated(destination, .current)
                } else if fileManager.fileExists(atPath: destination.path) {
                    try fileManager.removeItem(at: destination)
                    try syncDirectory(bin)
                }
                throw error
            }
            if fileManager.fileExists(atPath: rollback.path) {
                try fileManager.removeItem(at: rollback)
                try syncDirectory(bin)
            }
            return TunnelClientInstallResult(
                action: action,
                validation: try validate(destination),
                destination: destination
            )
        } catch {
            if candidateExists, fileManager.fileExists(atPath: candidate.path) {
                try? fileManager.removeItem(at: candidate)
            }
            if let known = error as? TunnelClientInstallerError { throw known }
            throw TunnelClientInstallerError.filesystem(
                SecretRedactor.redact(error.localizedDescription)
            )
        }
    }

    public func removeManagedBinary(confirmedStop: TunnelStopResult) throws {
        guard confirmedStop.status.runtimeState == "stopped",
              !confirmedStop.status.processRunning else {
            throw TunnelClientInstallerError.stopNotConfirmed
        }
        guard fileManager.fileExists(atPath: destination.path) else { return }
        try validateRegularExecutable(destination)
        do {
            try fileManager.removeItem(at: destination)
            try syncDirectory(destination.deletingLastPathComponent())
        } catch {
            throw TunnelClientInstallerError.filesystem(
                SecretRedactor.redact(error.localizedDescription)
            )
        }
    }

    private func version(of executable: URL) throws -> String {
        let result = try runner.run(
            executable: executable,
            arguments: ["--version"],
            timeout: Self.versionTimeout,
            outputLimit: Self.outputLimit
        )
        if result.timedOut { throw TunnelClientInstallerError.versionTimeout }
        if result.stdoutExceededLimit || result.stderrExceededLimit {
            throw TunnelClientInstallerError.versionOutputExceeded
        }
        guard result.exitCode == 0,
              let output = String(data: result.stdout, encoding: .utf8) else {
            throw TunnelClientInstallerError.versionCheckFailed
        }
        let trimmed = output.trimmingCharacters(in: .whitespacesAndNewlines)
        let expression = try NSRegularExpression(
            pattern: #"^v?([0-9]+\.[0-9]+\.[0-9]+)(?:\+[0-9A-Za-z.-]+)?(?: \(git sha: [0-9a-fA-F]{7,64}\))?$"#
        )
        let whole = NSRange(trimmed.startIndex..., in: trimmed)
        guard let match = expression.firstMatch(in: trimmed, range: whole),
              match.range == whole,
              let versionRange = Range(match.range(at: 1), in: trimmed) else {
            throw TunnelClientInstallerError.versionCheckFailed
        }
        return String(trimmed[versionRange])
    }

    private func validateRegularExecutable(_ url: URL) throws {
        var info = stat()
        let result = url.path.withCString { Darwin.lstat($0, &info) }
        guard result == 0, (info.st_mode & S_IFMT) == S_IFREG else {
            throw TunnelClientInstallerError.invalidFile(
                "Tunnel Client must be one regular file, not a directory, bundle, device, or link."
            )
        }
        guard fileManager.isExecutableFile(atPath: url.path) else {
            throw TunnelClientInstallerError.invalidFile("Tunnel Client file is not executable.")
        }
    }

    private func validateManagedDirectory(_ url: URL) throws {
        guard fileManager.fileExists(atPath: url.path) else { return }
        var info = stat()
        let result = url.path.withCString { Darwin.lstat($0, &info) }
        guard result == 0, (info.st_mode & S_IFMT) == S_IFDIR else {
            throw TunnelClientInstallerError.invalidFile(
                "The managed Tunnel Client path must contain only regular directories."
            )
        }
    }

    private func architectures(of url: URL) throws -> Set<TunnelBinaryArchitecture> {
        let handle = try FileHandle(forReadingFrom: url)
        defer { try? handle.close() }
        let data = try handle.read(upToCount: 8_192) ?? Data()
        guard data.count >= 12 else { throw TunnelClientInstallerError.unsupportedArchitecture }
        let bytes = [UInt8](data)
        let magic = Array(bytes[0..<4])
        if magic == [0xcf, 0xfa, 0xed, 0xfe] {
            return [architecture(cpuType: read32(bytes, offset: 4, littleEndian: true))]
        }
        let fat: (littleEndian: Bool, entrySize: Int)?
        switch magic {
        case [0xca, 0xfe, 0xba, 0xbe]: fat = (false, 20)
        case [0xbe, 0xba, 0xfe, 0xca]: fat = (true, 20)
        case [0xca, 0xfe, 0xba, 0xbf]: fat = (false, 32)
        case [0xbf, 0xba, 0xfe, 0xca]: fat = (true, 32)
        default: fat = nil
        }
        guard let fat else { throw TunnelClientInstallerError.unsupportedArchitecture }
        let count = Int(read32(bytes, offset: 4, littleEndian: fat.littleEndian))
        guard count > 0, count <= 64, 8 + count * fat.entrySize <= bytes.count else {
            throw TunnelClientInstallerError.unsupportedArchitecture
        }
        return Set((0..<count).map {
            architecture(
                cpuType: read32(
                    bytes,
                    offset: 8 + $0 * fat.entrySize,
                    littleEndian: fat.littleEndian
                )
            )
        })
    }

    private func architecture(cpuType: UInt32) -> TunnelBinaryArchitecture {
        switch cpuType {
        case 0x0100000c: .arm64
        case 0x01000007: .x86_64
        default: .unknown
        }
    }

    private func read32(_ bytes: [UInt8], offset: Int, littleEndian: Bool) -> UInt32 {
        let values = bytes[offset..<(offset + 4)].map(UInt32.init)
        if littleEndian {
            return values[0] | values[1] << 8 | values[2] << 16 | values[3] << 24
        }
        return values[0] << 24 | values[1] << 16 | values[2] << 8 | values[3]
    }

    private func sha256(_ url: URL) throws -> String {
        let handle = try FileHandle(forReadingFrom: url)
        defer { try? handle.close() }
        var hasher = SHA256()
        while let data = try handle.read(upToCount: 64 * 1_024), !data.isEmpty {
            hasher.update(data: data)
        }
        return hasher.finalize().map { String(format: "%02x", $0) }.joined()
    }

    private func atomicRename(_ source: URL, _ destination: URL) throws {
        let result = source.path.withCString { sourcePointer in
            destination.path.withCString { destinationPointer in
                Darwin.rename(sourcePointer, destinationPointer)
            }
        }
        guard result == 0 else {
            throw TunnelClientInstallerError.filesystem(
                "Atomic Tunnel Client replacement failed with errno \(errno)."
            )
        }
    }

    private func syncFile(_ url: URL) throws {
        let descriptor = Darwin.open(url.path, O_RDONLY)
        guard descriptor >= 0 else {
            throw TunnelClientInstallerError.filesystem("Unable to open Tunnel Client for fsync.")
        }
        defer { Darwin.close(descriptor) }
        guard Darwin.fsync(descriptor) == 0 else {
            throw TunnelClientInstallerError.filesystem("Unable to fsync Tunnel Client.")
        }
    }

    private func syncDirectory(_ url: URL) throws {
        let descriptor = Darwin.open(url.path, O_RDONLY)
        guard descriptor >= 0 else {
            throw TunnelClientInstallerError.filesystem(
                "Unable to open the managed Tunnel Client directory."
            )
        }
        defer { Darwin.close(descriptor) }
        guard Darwin.fsync(descriptor) == 0 else {
            throw TunnelClientInstallerError.filesystem(
                "Unable to fsync the managed Tunnel Client directory."
            )
        }
    }
}
