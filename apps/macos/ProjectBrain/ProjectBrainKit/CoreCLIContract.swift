import CryptoKit
import Foundation

public struct CoreCLIContract: Codable, Equatable, Sendable {
    public struct Operations: Codable, Equatable, Sendable {
        public let nativeOnboarding: NativeOnboarding

        enum CodingKeys: String, CodingKey {
            case nativeOnboarding = "native_onboarding"
        }
    }

    public struct NativeOnboarding: Codable, Equatable, Sendable {
        public struct Options: Codable, Equatable, Sendable {
            public let resolveExisting: String
            public let projectID: String
            public let name: String
            public let defaultBranch: String
            public let codexPath: String
            public let verificationFile: String
            public let autoPushEnabled: String
            public let autoPushDisabled: String
            public let autoPREnabled: String
            public let autoPRDisabled: String
            public let plan: String
            public let nonInteractive: String
            public let planToken: String
            public let json: String

            enum CodingKeys: String, CodingKey {
                case resolveExisting = "resolve_existing"
                case projectID = "project_id"
                case name
                case defaultBranch = "default_branch"
                case codexPath = "codex_path"
                case verificationFile = "verification_file"
                case autoPushEnabled = "auto_push_enabled"
                case autoPushDisabled = "auto_push_disabled"
                case autoPREnabled = "auto_pr_enabled"
                case autoPRDisabled = "auto_pr_disabled"
                case plan
                case nonInteractive = "non_interactive"
                case planToken = "plan_token"
                case json
            }

            var all: [String] {
                [
                    resolveExisting, projectID, name, defaultBranch, codexPath,
                    verificationFile, autoPushEnabled, autoPushDisabled,
                    autoPREnabled, autoPRDisabled, plan, nonInteractive,
                    planToken, json,
                ]
            }
        }

        public let commandPath: [String]
        public let options: Options

        enum CodingKeys: String, CodingKey {
            case commandPath = "command_path"
            case options
        }
    }

    public let schemaVersion: Int
    public let contractVersion: String
    public let coreVersion: String
    public let operations: Operations

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case contractVersion = "contract_version"
        case coreVersion = "core_version"
        case operations
    }

    public func validate() throws {
        guard schemaVersion == 1 else {
            throw CoreCLIContractError.invalid("Unsupported Core CLI contract schema")
        }
        guard contractVersion.range(
            of: #"^[0-9]+\.[0-9]+\.[0-9]+$"#,
            options: .regularExpression
        ) != nil else {
            throw CoreCLIContractError.invalid("Invalid Core CLI contract version")
        }
        guard coreVersion.range(
            of: #"^[0-9]+\.[0-9]+\.[0-9]+$"#,
            options: .regularExpression
        ) != nil else {
            throw CoreCLIContractError.invalid("Invalid Core version in CLI contract")
        }
        let onboarding = operations.nativeOnboarding
        guard !onboarding.commandPath.isEmpty,
              onboarding.commandPath.allSatisfy({ !$0.isEmpty && !$0.hasPrefix("-") }),
              onboarding.options.all.allSatisfy({ $0.hasPrefix("--") }) else {
            throw CoreCLIContractError.invalid("Invalid native onboarding CLI contract")
        }
    }
}

public struct CoreCLIContractDocument: Equatable, Sendable {
    public let contract: CoreCLIContract
    public let sha256: String

    public init(data: Data) throws {
        do {
            contract = try JSONDecoder().decode(CoreCLIContract.self, from: data)
        } catch {
            throw CoreCLIContractError.invalid("Core CLI contract is not valid JSON")
        }
        try contract.validate()
        sha256 = SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
    }

    public init(contentsOf url: URL) throws {
        try self.init(data: Data(contentsOf: url, options: [.mappedIfSafe]))
    }
}

public struct CoreCLIContractResponse: Decodable, Equatable, Sendable {
    public let status: String
    public let contract: CoreCLIContract
    public let documentSHA256: String

    enum CodingKeys: String, CodingKey {
        case status, contract
        case documentSHA256 = "document_sha256"
    }
}

public enum CoreCLIContractError: LocalizedError, Equatable {
    case invalid(String)

    public var errorDescription: String? {
        switch self {
        case .invalid(let message): message
        }
    }
}
