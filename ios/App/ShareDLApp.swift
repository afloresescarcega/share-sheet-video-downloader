import SwiftUI

@main
struct ShareDLApp: App {
    var body: some Scene {
        WindowGroup { ContentView() }
    }
}

struct ContentView: View {
    @State private var serverStatus: String = "Checking…"
    @State private var serverOK: Bool?
    @State private var link = ""
    @State private var phase: VideoDownloader.Phase = .idle
    private let downloader = VideoDownloader()

    private var statusColor: Color {
        switch serverOK {
        case nil: .gray
        case true?: .green
        case false?: .red
        }
    }

    var body: some View {
        NavigationStack {
            Form {
                Section("Your Mac") {
                    HStack {
                        Circle().fill(statusColor).frame(width: 10)
                        Text(serverStatus).font(.subheadline)
                        Spacer()
                        Button("Retry") { Task { await checkServer() } }
                    }
                    Text(downloader.baseURL.absoluteString).font(.footnote).foregroundStyle(.secondary)
                }

                Section("Paste a link") {
                    TextField("Link to a video", text: $link)
                        .keyboardType(.URL).textInputAutocapitalization(.never).autocorrectionDisabled()
                        .submitLabel(.go).onSubmit(startDownload)
                    Button("Download to Photos") { startDownload() }
                        .disabled(VideoDownloader.firstURL(in: link) == nil || isWorking)
                    if phase != .idle { DownloadStatusView(phase: phase).padding(.vertical, 8) }
                }

                Section("How to use") {
                    Label("In YouTube, TikTok, X, etc. tap Share", systemImage: "square.and.arrow.up")
                    Label("Pick ShareDL (under More the first time)", systemImage: "arrow.down.circle")
                    Label("It lands in your camera roll", systemImage: "photo.on.rectangle")
                }
            }
            .scrollDismissesKeyboard(.interactively)
            .navigationTitle("ShareDL")
            .task { await checkServer() }
        }
    }

    private var isWorking: Bool {
        if case .working = phase { true } else { false }
    }

    private func checkServer() async {
        serverOK = nil
        serverStatus = "Checking…"
        do {
            let version = try await downloader.health()
            serverOK = true
            serverStatus = "Connected · yt-dlp \(version)"
        } catch {
            serverOK = false
            serverStatus = "Can't reach server"
        }
    }

    private func startDownload() {
        guard let url = VideoDownloader.firstURL(in: link), !isWorking else { return }
        UIApplication.shared.sendAction(#selector(UIResponder.resignFirstResponder), to: nil, from: nil, for: nil)
        Task { await downloader.download(url) { phase = $0 } }
    }
}
