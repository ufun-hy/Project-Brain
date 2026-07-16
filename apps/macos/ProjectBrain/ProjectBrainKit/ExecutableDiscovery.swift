import Foundation

public enum ExecutableDiscovery {
    public static func find(_ name: String, fileManager: FileManager = .default) -> URL? {
        let home = fileManager.homeDirectoryForCurrentUser
        let candidates = [
            URL(filePath: "/opt/homebrew/bin/\(name)"),
            URL(filePath: "/usr/local/bin/\(name)"),
            URL(filePath: "/usr/bin/\(name)"),
            home.appending(path: ".local/bin/\(name)"),
        ] + (ProcessInfo.processInfo.environment["PATH"] ?? "")
            .split(separator: ":")
            .map { URL(filePath: String($0)).appending(path: name) }
        return candidates.first { candidate in
            var isDirectory: ObjCBool = false
            return fileManager.fileExists(atPath: candidate.path, isDirectory: &isDirectory)
                && !isDirectory.boolValue
                && fileManager.isExecutableFile(atPath: candidate.path)
        }?.standardizedFileURL
    }
}
