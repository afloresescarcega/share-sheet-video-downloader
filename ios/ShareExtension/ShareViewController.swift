import SwiftUI
import UIKit
import UniformTypeIdentifiers

/// Entry point for "Save Video" in the share sheet.
final class ShareViewController: UIViewController {
    private let model = ShareModel()

    override func viewDidLoad() {
        super.viewDidLoad()
        model.close = { [weak self] in self?.extensionContext?.completeRequest(returningItems: nil) }

        let host = UIHostingController(rootView: ShareView(model: model))
        addChild(host)
        host.view.frame = view.bounds
        host.view.autoresizingMask = [.flexibleWidth, .flexibleHeight]
        view.addSubview(host.view)
        host.didMove(toParent: self)

        let providers = (extensionContext?.inputItems as? [NSExtensionItem] ?? [])
            .flatMap { $0.attachments ?? [] }
        Task { await model.start(with: providers) }
    }
}

@MainActor
final class ShareModel: ObservableObject {
    @Published var phase: VideoDownloader.Phase = .working("Reading link…", 0)
    var close: () -> Void = {}
    private var task: Task<Void, Never>?

    func start(with providers: [NSItemProvider]) async {
        guard let url = await Self.extractURL(from: providers) else {
            phase = .failed("No link found in what was shared.")
            return
        }
        task = Task {
            await VideoDownloader().download(url) { [weak self] in self?.phase = $0 }
            if case .saved = phase {
                try? await Task.sleep(for: .seconds(1.2))
                close()
            }
        }
    }

    func cancel() {
        task?.cancel()
        close()
    }

    private static func extractURL(from providers: [NSItemProvider]) async -> URL? {
        for provider in providers where provider.hasItemConformingToTypeIdentifier(UTType.url.identifier) {
            if let url = try? await provider.loadItem(forTypeIdentifier: UTType.url.identifier) as? URL,
               url.scheme?.hasPrefix("http") == true {
                return url
            }
        }
        for provider in providers where provider.hasItemConformingToTypeIdentifier(UTType.plainText.identifier) {
            if let text = try? await provider.loadItem(forTypeIdentifier: UTType.plainText.identifier) as? String,
               let url = VideoDownloader.firstURL(in: text) {
                return url
            }
        }
        return nil
    }
}

struct ShareView: View {
    @ObservedObject var model: ShareModel

    var body: some View {
        ZStack {
            Color.black.opacity(0.25).ignoresSafeArea()
            VStack(spacing: 18) {
                HStack {
                    Label("Save Video", systemImage: "arrow.down.circle.fill")
                        .font(.headline).foregroundStyle(.pink)
                    Spacer()
                    Button(isFinished ? "Done" : "Cancel") { model.cancel() }
                }
                DownloadStatusView(phase: model.phase)
            }
            .padding(20)
            .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 22))
            .padding(.horizontal, 20)
        }
    }

    private var isFinished: Bool {
        switch model.phase {
        case .saved, .failed: true
        default: false
        }
    }
}
