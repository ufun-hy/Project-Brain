import Foundation
import XCTest
@testable import ProjectBrainKit

final class FirstTaskGuideTests: XCTestCase {
    func testGuideIsOfferedOnceOnlyWhenNoTaskExists() throws {
        let suite = "FirstTaskGuideTests.\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let store = FirstTaskGuideStore(defaults: defaults, key: "guide")

        XCTAssertTrue(store.shouldPresent(taskCount: 0))
        store.markPresented()
        XCTAssertFalse(store.shouldPresent(taskCount: 0))

        let afterRestart = FirstTaskGuideStore(defaults: defaults, key: "guide")
        XCTAssertFalse(afterRestart.shouldPresent(taskCount: 0))
    }

    func testGuideIsNotOfferedWhenAnAuthoritativeTaskAlreadyExists() throws {
        let suite = "FirstTaskGuideTests.\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        XCTAssertFalse(
            FirstTaskGuideStore(defaults: defaults, key: "guide")
                .shouldPresent(taskCount: 1)
        )
    }
}
