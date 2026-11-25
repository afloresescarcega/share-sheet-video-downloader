import Foundation
import Photos

/// Talks to the yt-dlp server on the Mac and saves the result to Photos.
struct VideoDownloader {
    enum Phase: Equatable {
        case idle
        case working(String, Double)   // message, progress 0...1
        case saved(String?)            // title
        case failed(String)
    }

    struct ServerError: LocalizedError {
        let message: String
        var errorDescription: String? { message }
    }

    private struct JobStatus: Decodable {
        let status: String
        let progress: Double
        let title: String?
        let error: String?
    }

    let baseURL: URL
    let token: String

    init(bundle: Bundle = .main) {
        let host = bundle.object(forInfoDictionaryKey: "ServerHost") as? String ?? "localhost"
        let port = bundle.object(forInfoDictionaryKey: "ServerPort") as? String ?? "8787"
        baseURL = URL(string: "http://\(host):\(port)")!
        token = bundle.object(forInfoDictionaryKey: "APIToken") as? String ?? ""
    }

    private static let session: URLSession = {
        let config = URLSessionConfiguration.default
        config.timeoutIntervalForRequest = 30
        config.timeoutIntervalForResource = 600
        config.waitsForConnectivity = false
        return URLSession(configuration: config)
    }()

    private func request(_ path: String, method: String = "GET", body: Data? = nil) -> URLRequest {
        var req = URLRequest(url: baseURL.appending(path: path))
        req.httpMethod = method
        req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        if let body {
            req.httpBody = body
            req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        }
        return req
    }

    private func check(_ response: URLResponse, _ data: Data?) throws {
        guard let http = response as? HTTPURLResponse else { return }
        guard (200..<300).contains(http.statusCode) else {
            if http.statusCode == 401 { throw ServerError(message: "Server rejected the token. Check API_TOKEN in Local.xcconfig.") }
            let detail = data.flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] }?["detail"] as? String
            throw ServerError(message: detail ?? "Server error \(http.statusCode)")
        }
    }

    /// Returns the server's yt-dlp version, or throws if unreachable.
    func health() async throws -> String {
        let (data, response) = try await Self.session.data(for: request("health"))
        try check(response, data)
        let json = try JSONSerialization.jsonObject(with: data) as? [String: Any]
        return json?["yt_dlp"] as? String ?? "?"
    }

    /// Full pipeline: queue on server → poll → download MP4 → save to camera roll.
    func download(_ videoURL: URL, update: @MainActor (Phase) -> Void) async {
        do {
            await update(.working("Asking your Mac…", 0))
            let body = try JSONEncoder().encode(["url": videoURL.absoluteString])
            let (data, response) = try await Self.session.data(for: request("jobs", method: "POST", body: body))
            try check(response, data)
            guard let id = (try JSONSerialization.jsonObject(with: data) as? [String: Any])?["id"] as? String else {
                throw ServerError(message: "Unexpected server response")
            }

            var title: String?
            while true {
                try await Task.sleep(for: .milliseconds(700))
                let (data, response) = try await Self.session.data(for: request("jobs/\(id)"))
                try check(response, data)
                let job = try JSONDecoder().decode(JobStatus.self, from: data)
                title = job.title
                switch job.status {
                case "done": break
                case "error": throw ServerError(message: job.error ?? "Download failed")
                case "processing": await update(.working("Converting for Photos…", job.progress * 0.8)); continue
                case "queued": await update(.working("Waiting in line…", 0)); continue
                default: await update(.working("Downloading on your Mac…", job.progress * 0.8)); continue
                }
                break
            }

            await update(.working("Sending to your phone…", 0.85))
            let (tmp, fileResponse) = try await Self.session.download(for: request("jobs/\(id)/file"))
            try check(fileResponse, nil)
            let file = FileManager.default.temporaryDirectory.appending(path: "\(id).mp4")
            try? FileManager.default.removeItem(at: file)
            try FileManager.default.moveItem(at: tmp, to: file)
            defer { try? FileManager.default.removeItem(at: file) }

            await update(.working("Saving to camera roll…", 0.95))
            try await saveToPhotos(file)
            await update(.saved(title))
        } catch is CancellationError {
            return
        } catch {
            await update(.failed(error.localizedDescription))
        }
    }

    private func saveToPhotos(_ file: URL) async throws {
        let status = await PHPhotoLibrary.requestAuthorization(for: .addOnly)
        guard status == .authorized || status == .limited else {
            throw ServerError(message: "Allow ShareDL to add to Photos in Settings → Privacy → Photos.")
        }
        try await PHPhotoLibrary.shared().performChanges {
            let options = PHAssetResourceCreationOptions()
            options.shouldMoveFile = false
            PHAssetCreationRequest.forAsset().addResource(with: .video, fileURL: file, options: options)
        }
    }

    /// Pulls the first http(s) link out of shared text (TikTok/X sometimes share "caption + link").
    static func firstURL(in text: String) -> URL? {
        let detector = try? NSDataDetector(types: NSTextCheckingResult.CheckingType.link.rawValue)
        let range = NSRange(text.startIndex..., in: text)
        return detector?.matches(in: text, range: range)
            .compactMap(\.url)
            .first { $0.scheme == "http" || $0.scheme == "https" }
    }
}
