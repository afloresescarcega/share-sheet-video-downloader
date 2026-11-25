<img src="assets/icon.svg" width="64" height="64" alt="">

# ShareDL

Save videos from YouTube (including Shorts), TikTok, X/Twitter, Instagram, Reddit and [many more sites](https://github.com/yt-dlp/yt-dlp/blob/master/supportedsites.md) straight to your iPhone's camera roll from the share sheet.

```
Share sheet → ShareDL extension → your Mac (yt-dlp + ffmpeg) → MP4 → Photos
```

ShareDL is two small pieces:

- **`server/`**: a FastAPI service that runs on your Mac. It downloads with [yt-dlp](https://github.com/yt-dlp/yt-dlp) and uses ffmpeg to make sure the result is an MP4 Photos accepts (H.264/HEVC + AAC).
- **`ios/`**: a SwiftUI app with a share extension. It sends the link to your Mac, shows progress, downloads the finished file and saves it to Photos.

yt-dlp runs on the Mac rather than on the phone for three reasons:
- Sites break yt-dlp often, and the server updates itself daily.
- A home IP is far less likely to hit YouTube's bot checks than a cloud server.
- iOS share extensions are too constrained to run ffmpeg reliably.

## Requirements

- A Mac that stays on, with [Homebrew](https://brew.sh) and Python 3.10+.
- Xcode 15+ and [XcodeGen](https://github.com/yonaskolb/XcodeGen) (`brew install xcodegen`).
- An Apple ID signed into Xcode. A free account works, but apps signed with it expire after 7 days. A paid developer account lasts a year.
- iOS 17+.

## Setup

### 1. Server (Mac)

```sh
brew install ffmpeg deno     # deno: yt-dlp needs a JS runtime for YouTube
server/scripts/install.sh
```

`install.sh` creates a virtualenv, generates a random API token in `server/.env`, and installs two launchd agents that start automatically when you log in:

| Agent | What it does |
| --- | --- |
| `com.sharedl.server` | Runs the server on port 8787 and restarts it if it crashes |
| `com.sharedl.update` | Upgrades yt-dlp daily at 4am and restarts the server if the version changed |

The script prints the token at the end; you'll need it for the app. Check that the server is up with `curl localhost:8787/health`.

### 2. iOS app

```sh
cp ios/Config/Local.example.xcconfig ios/Config/Local.xcconfig
# edit Local.xcconfig: BUNDLE_PREFIX, DEVELOPMENT_TEAM, SERVER_HOST, API_TOKEN
cd ios && xcodegen && open ShareDL.xcodeproj
```

Select your iPhone and press **Run**. Open ShareDL once: it should show **Connected**, and it will ask for Local Network access. Then, in any app's share sheet, tap **More** and enable or favorite **ShareDL**.

### Using it away from home

`SERVER_HOST = YourMac.local` only works on the same Wi-Fi. For anywhere access, install [Tailscale](https://tailscale.com) on the Mac and the iPhone. Then set `SERVER_HOST` to the Mac's Tailscale name (e.g. `my-mac.tailnet-name.ts.net`) and rebuild. Traffic stays inside your tailnet; don't expose port 8787 to the internet.

## Operating it

| Task | Command |
| --- | --- |
| Server logs | `tail -f server/logs/server.log` |
| Update yt-dlp now | `server/scripts/update-ytdlp.sh` |
| Restart server | `launchctl kickstart -k gui/$(id -u)/com.sharedl.server` |
| Uninstall agents | `launchctl bootout gui/$(id -u)/com.sharedl.server; launchctl bootout gui/$(id -u)/com.sharedl.update; rm ~/Library/LaunchAgents/com.sharedl.*.plist` |

- **Login-only content.** For some Instagram and X posts, export your browser cookies (Netscape format) to `server/cookies.txt` and uncomment `SHAREDL_COOKIES` in `server/.env`.
- **Moving the repo.** If you move the repo folder, re-run `install.sh`; the launchd agents point at its absolute path.
- **Disk use.** Downloaded files are deleted from the Mac after an hour.

## Security

The server is meant for your private network only. It has these protections:

- **Token on everything.** Every request needs the random 192-bit token. The server refuses to start without one. `/health` reveals nothing but `{"ok":true}` without it, and the API docs (`/docs`, `/openapi.json`) are turned off.
- **No access to your own network.** Every outbound connection the server makes is checked against the IP address it actually connects to. Private, loopback, link-local and CGNAT/Tailscale addresses (your router, `localhost`, cloud metadata) are refused. The check covers redirects, URLs embedded in pages, manifests and DNS rebinding, so a leaked token can't be used to probe your home network.
  - yt-dlp's rare ffmpeg-based stream downloads are disabled, since ffmpeg opens its own connections. A few exotic stream types (RTMP, some live formats) won't download.
  - ffmpeg is limited to local files when converting.
- **Resource limits.** Playlist and channel links download only the first video. Live streams, videos over 3 hours and files over 2 GB are skipped, at most 6 downloads run at once, and ffmpeg has a timeout. You can tune these in `server/.env` with `SHAREDL_MAX_DURATION_MIN`, `SHAREDL_MAX_FILESIZE_MB` and `SHAREDL_MAX_ACTIVE_JOBS`.
- **Updates.** yt-dlp updates itself daily. Keep ffmpeg current with `brew upgrade ffmpeg`, since it parses untrusted video files.

Two important caveats:

- **Use Tailscale on a laptop.** By default the server listens on every network the Mac joins, over plain HTTP, so on a café or office Wi-Fi others can reach it and could sniff the token. Use Tailscale (traffic is WireGuard-encrypted) and set `SHAREDL_HOST=<the Mac's Tailscale IP>` in `server/.env`, so the server is only reachable over your tailnet.
- **Never port-forward 8787** on your router or expose it with a tunnel. If you think your token has leaked, delete the `SHAREDL_TOKEN` line from `server/.env` and re-run `install.sh`. It generates a new token, restarts the server and prints the token. Put it in `API_TOKEN` in `ios/Config/Local.xcconfig` and rebuild the app.

## API

All `/jobs` routes need `Authorization: Bearer <SHAREDL_TOKEN>`.

| Route | Description |
| --- | --- |
| `GET /health` | `{"ok": true, "yt_dlp": "<version>"}` |
| `POST /jobs` `{"url": "..."}` | Queue a download → `{"id": "..."}` |
| `GET /jobs/{id}` | `status` (`queued`/`downloading`/`processing`/`done`/`error`), `progress`, `title`, `error` |
| `GET /jobs/{id}/file` | The finished MP4 |

## Verification

`.claude/skills/verify-sharedl/` is an agent-runnable verification harness. It starts an isolated server instance and a separate "ShareDL Verify" app build, drives the share sheet in the iOS Simulator, and collects evidence (screenshots, the saved MP4, ffprobe output) under `.verify/`. See its `SKILL.md`.

```sh
V=.claude/skills/verify-sharedl/scripts/sharedl-verify
$V up && $V doctor
$V api https://www.youtube.com/shorts/tPEE9ZwTmy0 shorts
$V down
```

## Disclaimer

ShareDL is for personal use. Downloading content may violate the terms of service of the sites involved; respect copyright and only save videos you have the right to keep. This project is not affiliated with YouTube, TikTok, X or any other platform.

## License

[MIT](LICENSE)
