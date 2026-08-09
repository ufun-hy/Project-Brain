import Foundation
import XCTest
@testable import ProjectBrainKit

func repositoryCLIContractDocument(filePath: String = #filePath) throws
    -> CoreCLIContractDocument
{
    var root = URL(filePath: filePath)
    for _ in 0..<5 {
        root.deleteLastPathComponent()
    }
    return try CoreCLIContractDocument(
        contentsOf: root.appending(path: "src/project_brain/cli_contract.json")
    )
}

func encodedContractResponse(_ document: CoreCLIContractDocument) throws -> String {
    struct Response: Encodable {
        let status: String
        let contract: CoreCLIContract
        let documentSHA256: String

        enum CodingKeys: String, CodingKey {
            case status, contract
            case documentSHA256 = "document_sha256"
        }
    }
    return String(decoding: try JSONEncoder().encode(Response(
        status: "ok",
        contract: document.contract,
        documentSHA256: document.sha256
    )), as: UTF8.self)
}

final class CoreCLIContractTests: XCTestCase {
    func testRepositoryContractIsValidAndVersioned() throws {
        let document = try repositoryCLIContractDocument()
        XCTAssertEqual(document.contract.schemaVersion, 1)
        XCTAssertEqual(document.contract.contractVersion, "1.2.0")
        XCTAssertEqual(document.contract.coreVersion, "0.8.0")
        XCTAssertEqual(document.sha256.count, 64)
    }

    func testNativeOnboardingArgvComesFromSharedContract() throws {
        let document = try repositoryCLIContractDocument()
        let operation = document.contract.operations.nativeOnboarding
        XCTAssertEqual(operation.commandPath, ["projects", "add"])
        XCTAssertEqual(operation.options.resolveExisting, "--resolve-existing")
    }

    func testLocalTaskContractUsesFixedCommandsAndStdinJSON() throws {
        let operation = try repositoryCLIContractDocument().contract.operations.localTask
        XCTAssertEqual(operation.requestSchemaVersion, 1)
        XCTAssertEqual(operation.confirmationSchemaVersion, 1)
        XCTAssertEqual(operation.transport, "stdin_json")
        XCTAssertEqual(operation.planCommandPath, ["tasks", "local-plan"])
        XCTAssertEqual(operation.createCommandPath, ["tasks", "local-create"])
    }

    func testAppRejectsStaleCoreAndCLIContractVersions() throws {
        let current = try String(
            decoding: JSONEncoder().encode(repositoryCLIContractDocument().contract),
            as: UTF8.self
        )
        XCTAssertThrowsError(try CoreCLIContractDocument(
            data: Data(current.replacingOccurrences(of: "1.2.0", with: "1.1.0").utf8)
        ))
        XCTAssertThrowsError(try CoreCLIContractDocument(
            data: Data(current.replacingOccurrences(of: "0.8.0", with: "0.7.0").utf8)
        ))
    }
}
