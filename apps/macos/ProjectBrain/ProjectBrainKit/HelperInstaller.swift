import CryptoKit
import Darwin
import Foundation

public struct HelperCommandResult: Equatable, Sendable {
    public let exitCode: Int32
    public let stdout: String
    public let stderr: String

    public init(exitCode: Int32, stdout: String, stderr: String) {
        self.exitCode = exitCode
        self.stdout = stdout
        self.stderr = stderr
    }
}

public protocol HelperCommandRunning: Sendable {
    func run(executable: URL, arguments: [String]) throws -> HelperCommandResult
}

public struct FoundationHelperCommandRunner: HelperCommandRunning {
    public init() {}

    public func run(executable: URL, arguments: [String]) throws -> HelperCommandResult {
        guard executable.path.hasPrefix("/") else {
            throw HelperInstallerError.invalidHelper("Helper executable must be absolute")
        }
        let process = Process()
        let stdout = Pipe()
        let stderr = Pipe()
        process.executableURL = executable
        process.arguments = arguments
        process.standardOutput = stdout
        process.standardError = stderr
        try process.run()
        process.waitUntilExit()
        let outputData = stdout.fileHandleForReading.readDataToEndOfFile().prefix(4096)
        let errorData = stderr.fileHandleForReading.readDataToEndOfFile().prefix(4096)
        return HelperCommandResult(
            exitCode: process.terminationStatus,
            stdout: String(decoding: outputData, as: UTF8.self),
            stderr: String(decoding: errorData, as: UTF8.self)
        )
    }
}

public enum HelperInstallAction: String, Equatable, Sendable {
    case installed
    case upgraded
    case current
}

public struct HelperInstallResult: Equatable, Sendable {
    public let action: HelperInstallAction
    public let version: String
    public let destination: URL
    public let sha256: String
    public let cliContractVersion: String
    public let cliContractSHA256: String

    public init(
        action: HelperInstallAction,
        version: String,
        destination: URL,
        sha256: String,
        cliContractVersion: String,
        cliContractSHA256: String
    ) {
        self.action = action
        self.version = version
        self.destination = destination
        self.sha256 = sha256
        self.cliContractVersion = cliContractVersion
        self.cliContractSHA256 = cliContractSHA256
    }
}

public enum HelperInstallerError: LocalizedError, Equatable {
    case invalidHelper(String)
    case versionCheck(String)
    case filesystem(String)

    public var errorDescription: String? {
        switch self {
        case .invalidHelper(let message), .versionCheck(let message), .filesystem(let message):
            return message
        }
    }
}

public final class HelperInstaller: @unchecked Sendable {
    public static let relativeDestination = "Project Brain/bin/project-brain"

    private let applicationSupportDirectory: URL
    private let fileManager: FileManager
    private let runner: any HelperCommandRunning

    public init(
        applicationSupportDirectory: URL? = nil,
        fileManager: FileManager = .default,
        runner: any HelperCommandRunning = FoundationHelperCommandRunner()
    ) {
        self.fileManager = fileManager
        self.runner = runner
        self.applicationSupportDirectory = applicationSupportDirectory
            ?? fileManager.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
    }

    public var destination: URL {
        applicationSupportDirectory.appending(path: Self.relativeDestination)
    }

    public func install(
        bundledHelper: URL,
        cliContract document: CoreCLIContractDocument,
        onActivated: @Sendable (URL, HelperInstallAction) throws -> Void = { _, _ in }
    ) throws -> HelperInstallResult {
        try validateRegularFile(bundledHelper, requireExecutable: true)
        let bundledVersion = try version(of: bundledHelper)
        guard bundledVersion == "project-brain \(document.contract.coreVersion)" else {
            throw HelperInstallerError.versionCheck(
                "Bundled helper version does not match the Core CLI contract"
            )
        }
        try requireContract(of: bundledHelper, matches: document)
        let bundledSHA256 = try sha256(bundledHelper)
        let destination = destination.standardizedFileURL
        let binDirectory = destination.deletingLastPathComponent()
        try rejectSymbolicLink(binDirectory)
        try fileManager.createDirectory(
            at: binDirectory,
            withIntermediateDirectories: true,
            attributes: [.posixPermissions: 0o700]
        )
        try fileManager.setAttributes([.posixPermissions: 0o700], ofItemAtPath: binDirectory.path)

        if fileManager.fileExists(atPath: destination.path) {
            try validateRegularFile(destination, requireExecutable: true)
            let destinationMatches = (try? version(of: destination)) == bundledVersion
                && (try? sha256(destination)) == bundledSHA256
                && (try? contractMatches(executable: destination, document: document)) == true
            if destinationMatches {
                return HelperInstallResult(
                    action: .current,
                    version: bundledVersion,
                    destination: destination,
                    sha256: bundledSHA256,
                    cliContractVersion: document.contract.contractVersion,
                    cliContractSHA256: document.sha256
                )
            }
        }

        let candidate = binDirectory.appending(
            path: ".project-brain.\(UUID().uuidString).candidate"
        )
        let rollback = binDirectory.appending(path: ".project-brain.rollback")
        var candidateExists = false
        do {
            try fileManager.copyItem(at: bundledHelper, to: candidate)
            candidateExists = true
            try fileManager.setAttributes([.posixPermissions: 0o755], ofItemAtPath: candidate.path)
            try syncFile(candidate)
            guard try version(of: candidate) == bundledVersion else {
                throw HelperInstallerError.versionCheck("Candidate helper version changed")
            }
            try requireContract(of: candidate, matches: document)
            guard try sha256(candidate) == bundledSHA256 else {
                throw HelperInstallerError.versionCheck("Candidate helper SHA-256 changed")
            }

            let upgrading = fileManager.fileExists(atPath: destination.path)
            if upgrading {
                if fileManager.fileExists(atPath: rollback.path) {
                    try fileManager.removeItem(at: rollback)
                }
                try fileManager.copyItem(at: destination, to: rollback)
                try fileManager.setAttributes([.posixPermissions: 0o755], ofItemAtPath: rollback.path)
                try syncFile(rollback)
            }

            try atomicRename(candidate, destination)
            candidateExists = false
            try syncDirectory(binDirectory)
            let action: HelperInstallAction = upgrading ? .upgraded : .installed
            do {
                guard try version(of: destination) == bundledVersion else {
                    throw HelperInstallerError.versionCheck(
                        "Installed helper did not report the bundled version"
                    )
                }
                try requireContract(of: destination, matches: document)
                guard try sha256(destination) == bundledSHA256 else {
                    throw HelperInstallerError.versionCheck(
                        "Installed helper SHA-256 does not match the bundled helper"
                    )
                }
                try onActivated(destination, action)
            } catch {
                if upgrading, fileManager.fileExists(atPath: rollback.path) {
                    try atomicRename(rollback, destination)
                    try syncDirectory(binDirectory)
                    try? onActivated(destination, .current)
                } else if fileManager.fileExists(atPath: destination.path) {
                    try fileManager.removeItem(at: destination)
                    try syncDirectory(binDirectory)
                }
                throw error
            }
            if fileManager.fileExists(atPath: rollback.path) {
                try fileManager.removeItem(at: rollback)
                try syncDirectory(binDirectory)
            }
            return HelperInstallResult(
                action: action,
                version: bundledVersion,
                destination: destination,
                sha256: bundledSHA256,
                cliContractVersion: document.contract.contractVersion,
                cliContractSHA256: document.sha256
            )
        } catch {
            if candidateExists, fileManager.fileExists(atPath: candidate.path) {
                try? fileManager.removeItem(at: candidate)
            }
            if let installerError = error as? HelperInstallerError {
                throw installerError
            }
            throw HelperInstallerError.filesystem(error.localizedDescription)
        }
    }

    private func version(of executable: URL) throws -> String {
        let result = try runner.run(executable: executable, arguments: ["--version"])
        let value = result.stdout.trimmingCharacters(in: .whitespacesAndNewlines)
        guard result.exitCode == 0, value.range(
            of: #"^project-brain [0-9]+\.[0-9]+\.[0-9]+$"#,
            options: .regularExpression
        ) != nil else {
            throw HelperInstallerError.versionCheck("Helper version validation failed")
        }
        return value
    }

    private func requireContract(
        of executable: URL,
        matches document: CoreCLIContractDocument
    ) throws {
        guard try contractMatches(executable: executable, document: document) else {
            throw HelperInstallerError.versionCheck(
                "Helper CLI contract does not match this app"
            )
        }
    }

    private func contractMatches(
        executable: URL,
        document: CoreCLIContractDocument
    ) throws -> Bool {
        let result = try runner.run(
            executable: executable,
            arguments: ["cli-contract", "--json"]
        )
        guard result.exitCode == 0,
              let data = result.stdout.data(using: .utf8),
              let response = try? JSONDecoder().decode(
                  CoreCLIContractResponse.self,
                  from: data
              ) else {
            return false
        }
        return response.status == "ok"
            && response.contract == document.contract
            && response.documentSHA256 == document.sha256
    }

    private func sha256(_ url: URL) throws -> String {
        let handle = try FileHandle(forReadingFrom: url)
        defer { try? handle.close() }
        var hasher = SHA256()
        while true {
            let data = try handle.read(upToCount: 1024 * 1024) ?? Data()
            if data.isEmpty { break }
            hasher.update(data: data)
        }
        return hasher.finalize().map { String(format: "%02x", $0) }.joined()
    }

    private func validateRegularFile(_ url: URL, requireExecutable: Bool) throws {
        try rejectSymbolicLink(url)
        var isDirectory: ObjCBool = false
        guard fileManager.fileExists(atPath: url.path, isDirectory: &isDirectory),
              !isDirectory.boolValue else {
            throw HelperInstallerError.invalidHelper("Helper is not a regular file")
        }
        if requireExecutable && !fileManager.isExecutableFile(atPath: url.path) {
            throw HelperInstallerError.invalidHelper("Helper is not executable")
        }
    }

    private func rejectSymbolicLink(_ url: URL) throws {
        if fileManager.fileExists(atPath: url.path) {
            let values = try url.resourceValues(forKeys: [.isSymbolicLinkKey])
            if values.isSymbolicLink == true {
                throw HelperInstallerError.invalidHelper("Helper path cannot be a symbolic link")
            }
        }
    }

    private func atomicRename(_ source: URL, _ destination: URL) throws {
        let result = source.path.withCString { sourcePointer in
            destination.path.withCString { destinationPointer in
                Darwin.rename(sourcePointer, destinationPointer)
            }
        }
        guard result == 0 else {
            throw HelperInstallerError.filesystem(
                "Atomic helper replacement failed with errno \(errno)"
            )
        }
    }

    private func syncFile(_ url: URL) throws {
        let descriptor = Darwin.open(url.path, O_RDONLY)
        guard descriptor >= 0 else {
            throw HelperInstallerError.filesystem("Unable to open helper for fsync")
        }
        defer { Darwin.close(descriptor) }
        guard Darwin.fsync(descriptor) == 0 else {
            throw HelperInstallerError.filesystem("Unable to fsync helper")
        }
    }

    private func syncDirectory(_ url: URL) throws {
        let descriptor = Darwin.open(url.path, O_RDONLY)
        guard descriptor >= 0 else {
            throw HelperInstallerError.filesystem("Unable to open helper directory")
        }
        defer { Darwin.close(descriptor) }
        guard Darwin.fsync(descriptor) == 0 else {
            throw HelperInstallerError.filesystem("Unable to fsync helper directory")
        }
    }
}
