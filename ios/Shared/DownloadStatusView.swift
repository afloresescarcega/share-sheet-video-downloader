import SwiftUI

/// Progress / success / error card shared by the app and the share extension.
struct DownloadStatusView: View {
    let phase: VideoDownloader.Phase

    var body: some View {
        VStack(spacing: 14) {
            switch phase {
            case .idle:
                EmptyView()
            case let .working(message, progress):
                ProgressView(value: max(progress, 0.02))
                    .progressViewStyle(.linear)
                    .tint(.pink)
                Text(message).font(.subheadline).foregroundStyle(.secondary)
            case let .saved(title):
                Image(systemName: "checkmark.circle.fill")
                    .font(.system(size: 44)).foregroundStyle(.green)
                Text("Saved to Photos").font(.headline)
                if let title { Text(title).font(.footnote).foregroundStyle(.secondary).lineLimit(2).multilineTextAlignment(.center) }
            case let .failed(message):
                Image(systemName: "exclamationmark.triangle.fill")
                    .font(.system(size: 40)).foregroundStyle(.orange)
                Text("Couldn't save video").font(.headline)
                Text(message).font(.footnote).foregroundStyle(.secondary).multilineTextAlignment(.center).textSelection(.enabled)
            }
        }
        .frame(maxWidth: .infinity)
        .animation(.default, value: phase)
    }
}
