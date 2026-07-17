import AppKit
import ProjectBrainKit
import SwiftUI

@main
struct ProductShellScreenshotRenderer {
    @MainActor
    static func main() throws {
        guard CommandLine.arguments.count == 2 else {
            throw CocoaError(.fileWriteInvalidFileName)
        }
        let output = URL(filePath: CommandLine.arguments[1])
        let defaults = UserDefaults(suiteName: "ProjectBrainScreenshot.\(UUID().uuidString)")!
        let model = AppModel(
            onboardingStore: OnboardingStore(defaults: defaults, key: "screenshot")
        )
        let content = ZStack {
            Color(nsColor: .windowBackgroundColor)
            OnboardingView(model: model)
        }
        .frame(width: 700, height: 520)
        .environment(\.colorScheme, .light)

        let renderer = ImageRenderer(content: content)
        renderer.scale = 2
        guard let image = renderer.nsImage,
              let tiff = image.tiffRepresentation,
              let bitmap = NSBitmapImageRep(data: tiff),
              let png = bitmap.representation(using: .png, properties: [:]) else {
            throw CocoaError(.fileWriteUnknown)
        }
        try FileManager.default.createDirectory(
            at: output.deletingLastPathComponent(),
            withIntermediateDirectories: true
        )
        try png.write(to: output, options: .atomic)
    }
}
