import Darwin
import Foundation

public enum UserProcessLockError: LocalizedError, Equatable {
    case invalidPath
    case filesystem(String)

    public var errorDescription: String? {
        switch self {
        case .invalidPath:
            "The application instance lock path must be absolute."
        case .filesystem(let message):
            message
        }
    }
}

/// A process-scoped, non-blocking advisory lock. The descriptor remains open
/// for the lifetime of this value so another app copy cannot acquire the same
/// user-level lock.
public final class UserProcessLock: @unchecked Sendable {
    private let descriptor: Int32
    public let url: URL

    private init(descriptor: Int32, url: URL) {
        self.descriptor = descriptor
        self.url = url
    }

    deinit {
        _ = flock(descriptor, LOCK_UN)
        _ = Darwin.close(descriptor)
    }

    public static func acquire(
        at url: URL,
        fileManager: FileManager = .default
    ) throws -> UserProcessLock? {
        guard url.isFileURL, url.path.hasPrefix("/") else {
            throw UserProcessLockError.invalidPath
        }
        let directory = url.deletingLastPathComponent()
        do {
            try fileManager.createDirectory(
                at: directory,
                withIntermediateDirectories: true,
                attributes: [.posixPermissions: 0o700]
            )
            try fileManager.setAttributes(
                [.posixPermissions: 0o700],
                ofItemAtPath: directory.path
            )
        } catch {
            throw UserProcessLockError.filesystem(
                "Unable to prepare the application instance lock directory."
            )
        }

        let descriptor = Darwin.open(url.path, O_CREAT | O_RDWR | O_CLOEXEC, 0o600)
        guard descriptor >= 0 else {
            throw UserProcessLockError.filesystem(
                "Unable to open the application instance lock."
            )
        }
        guard flock(descriptor, LOCK_EX | LOCK_NB) == 0 else {
            let lockError = errno
            _ = Darwin.close(descriptor)
            if lockError == EWOULDBLOCK { return nil }
            throw UserProcessLockError.filesystem(
                "Unable to acquire the application instance lock."
            )
        }
        guard Darwin.fchmod(descriptor, 0o600) == 0 else {
            _ = flock(descriptor, LOCK_UN)
            _ = Darwin.close(descriptor)
            throw UserProcessLockError.filesystem(
                "Unable to secure the application instance lock."
            )
        }
        return UserProcessLock(descriptor: descriptor, url: url)
    }
}
