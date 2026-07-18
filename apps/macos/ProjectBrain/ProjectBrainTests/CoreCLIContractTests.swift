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
        XCTAssertEqual(document.contract.contractVersion, "1.0.0")
        XCTAssertEqual(document.contract.coreVersion, "0.7.0")
        XCTAssertEqual(document.sha256.count, 64)
    }

    func testNativeOnboardingArgvComesFromSharedContract() throws {
        let document = try repositoryCLIContractDocument()
        let operation = document.contract.operations.nativeOnboarding
        XCTAssertEqual(operation.commandPath, ["projects", "add"])
        XCTAssertEqual(operation.options.resolveExisting, "--resolve-existing")
    }
}
