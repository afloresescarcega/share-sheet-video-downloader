# ShareDL verification map

This directory is the maintained source for verifying the user-facing behavior of ShareDL. Read the index before driving the app, then use the matching feature file as the recipe.

## Baseline preconditions

- `$V up`, `$V build-sim` and `$V install-sim <udid>` are done, and `$V doctor` prints `DOCTOR OK`.
  - `V=.claude/skills/verify-sharedl/scripts/sharedl-verify`.
- An iOS Simulator is open via `device_open`, and `$AD` is the `agent-device` path that call returned.
- `dev.sharedl.verify.sharedl` has Photos permission: `$AD settings permission grant photos`, then relaunch.
- The Mac has internet access. Every download hits the real site.
- Never drive the user's launchd server on `:8787` or the user's own installed build (bundle id from their `Local.xcconfig`).

## Driving conventions

- UI actions go through `$AD`. Prefer accessible names (`text="Download to Photos"`). Use coordinates only inside the share sheet, whose snapshot rects are wrong.
- Server-only checks go through `$V api <url> <name>`.
- Reference URLs that are known to work:
  - YouTube Short: `https://www.youtube.com/shorts/tPEE9ZwTmy0`
  - YouTube: `https://www.youtube.com/watch?v=jNQXAC9IVRw`
  - TikTok: `https://www.tiktok.com/@scout2015/video/6718335390845095173`

## Proof and skip reporting

- Capture the user action and the resulting state: screenshots of the sheet, the progress card and the final state.
- Prove the side effect: a `$V photos` before/after diff shows a new `DCIM` file, and `ffprobe` on it shows h264/hevc + aac.
- Pair every UI proof with the `queued`/`done` lines from the instance `server.log`.
- Record the feature ID and entry point with every artifact name.
- If a site refuses (bot check, login wall), report the URL and yt-dlp's error from `status.json`. Do not swap in a different site and call the feature verified.

## Feature entry contract

Each feature file starts with an H1 and one paragraph, then exactly four H2s, in this order:
1. `Sub-features`
2. `How to get to it (user POV)`
3. `Driving it with agent-device + sharedl-verify`
4. `Gotchas`

## Features

- [Share extension](./share-extension.md): share a link from another app, and the video lands in Photos. The primary feature.
- [Paste a link](./paste-link.md): the in-app fallback for links that aren't shared directly.
- [Server connection status](./server-status.md): the app shows whether the Mac is reachable.
- [Server download and conversion](./server-download.md): per-site yt-dlp download and Photos-safe MP4 output.
- [yt-dlp auto-update](./ytdlp-auto-update.md): the daily launchd job that keeps yt-dlp current.
