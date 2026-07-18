import Foundation
import XCTest
@testable import ProjectBrainKit

final class UserProcessLockTests: XCTestCase {
    func testOnlyOneProcessLockOwnerAndReleaseAllowsReacquisition() throws {
        let root = FileManager.default.temporaryDirectory
            .appending(path: UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: root) }
        let url = root.appending(path: "Project Brain/app-instance.lock")

        var first: UserProcessLock? = try UserProcessLock.acquire(at: url)
        XCTAssertNotNil(first)
        XCTAssertNil(try UserProcessLock.acquire(at: url))
        let attributes = try FileManager.default.attributesOfItem(atPath: url.path)
        XCTAssertEqual((attributes[.posixPermissions] as? NSNumber)?.intValue, 0o600)

        first = nil
        XCTAssertNotNil(try UserProcessLock.acquire(at: url))
    }

    func testRejectsRelativeLockPath() {
        XCTAssertThrowsError(try UserProcessLock.acquire(at: URL(string: "relative")!))
    }
}
