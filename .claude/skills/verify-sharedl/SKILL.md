---
name: verify-sharedl
description: Drive and prove ShareDL end to end — the iOS share extension and app (in an iOS Simulator) plus the Mac yt-dlp server — using an isolated server instance. Use whenever you change server/app.py, anything under ios/, or need evidence that sharing a YouTube/Shorts/TikTok/X link lands an MP4 in the camera roll.
---

# Verify ShareDL

ShareDL has two halves:
- **iOS app** (`ios/`, SwiftUI, XcodeGen). The primary user surface is the **share extension**: Share → "ShareDL" in any app. Secondary: the app's "Paste a link" form and its "Your Mac" connection status.
- **Mac server** (`server/app.py`, FastAPI + yt-dlp + ffmpeg). Its HTTP API is `POST /jobs`, `GET /jobs/{id}`, `GET /jobs/{id}/file` and `GET /health`, with a bearer token. It is normally run by launchd as `com.sharedl.server` on port **8787**. That is the user's live instance: **never drive, restart or kill it during verification.**

All commands below run from the repo root. The helper is `.claude/skills/verify-sharedl/scripts/sharedl-verify` (call it `$V`):

```sh
V=.claude/skills/verify-sharedl/scripts/sharedl-verify
```

## Launch

```sh
$V up          # starts an isolated server: random free port, random token, own work dir
$V build-sim   # builds the app pointed at that instance, bundle id dev.sharedl.verify.sharedl, name "ShareDL Verify"
```

Each command prints exactly one success line, and that line is the readiness signal:
- `$V up` prints `READY run=<id> port=<port> pid=<pid>`, but only after `/health` returns `ok`.
- `$V build-sim` prints `BUILT <path>.app`.

Prerequisites: `server/.venv` must exist (`server/scripts/install.sh` creates it), and `ffmpeg`, `ffprobe`, `deno`, `xcodegen` and Xcode must be installed. `up` checks the binaries. The run id is remembered in `.verify/current`, so later commands find the instance without needing `RUN_ID`.

Then open a simulator through the T3 device tools:
1. `device_list`, then `device_open` on an iOS Simulator. It returns an `agent-device` path; call it `$AD`.
2. Install the build:
   ```sh
   $V install-sim <udid>
   ```
3. Grant Photos access to the verify app, then relaunch it:
   ```sh
   $AD open dev.sharedl.verify.sharedl
   $AD settings permission grant photos
   $AD open dev.sharedl.verify.sharedl --relaunch
   ```
   Granting the permission kills the app, which is why the relaunch is needed.

## Doctor

```sh
$V doctor
```

This is read-only. It checks:
- The server pid is alive and owns the port.
- `/health` returns ok and reports the yt-dlp version.
- Auth is enforced: no token gives 401, a valid token gives 404 for an unknown job.
- `ffmpeg`, `ffprobe` and `deno` are present.
- The simulator build's `ServerPort` matches the instance port.

It ends with `DOCTOR OK` or fails, naming each `BAD` line. Run it first whenever anything looks off. A port mismatch means rerun `build-sim` and `install-sim`.

## Drive

**Simulator UI.** Drive it only through `$AD`, the path `device_open` returned. Do not use `simctl` for UI actions. `simctl install`/`uninstall` inside the helper is fine. Stable handles:
- **App** (`dev.sharedl.verify.sharedl`):
  - Text field `https://…` (placeholder).
  - Button `Download to Photos`.
  - Cell `Connected · yt-dlp <ver>` or `Can't reach server`.
  - Button `Retry`.
  - Status cells `Saved to Photos` and `Couldn't save video`.
- **Safari** (`com.apple.mobilesafari`):
  - Button `Page Menu`, then cell `Share`.
- **Share sheet:** the app row shows `ShareDL` (the user's build, if installed) and `ShareDL Verify` (yours). **Always pick `ShareDL Verify`.**
  - Snapshot rects for share sheet cells are wrong, because the sheet is a remote view. Take a screenshot, find the icon and press by coordinates (points = screenshot px / 3).
  - Swipe the app row left (`$AD swipe 300 650 120 650`) if the icon is cut off.
- **Extension card:**
  - Title `Save Video`.
  - Button `Cancel`, which becomes `Done` when finished.
  - Messages: `Asking your Mac…`, `Downloading on your Mac…`, `Converting for Photos…`, `Sending to your phone…`, `Saving to camera roll…`.
  - On success it auto-dismisses after about 1.2s.

**Server API (no UI):** `$V api <video-url> <name>` runs the full job round trip. It asserts the output is Photos-safe (video `h264/avc1` or `hevc/hvc1`, audio `aac/mp4a`) and prints `PASS <name>: <codecs>`.

**Camera roll side effect:** run `$V photos <udid> <label>` before and after a UI save. It lists the simulator's `DCIM` video files into the evidence dir; `diff` the two lists to get the new file.

## Evidence

Everything goes under `.verify/<run-id>/evidence/`, which is gitignored and survives `down`:
- `<name>/{url.txt,status.json,video.mp4,ffprobe.json,codecs.txt}` from `$V api`.
- Screenshots from `$AD screenshot .verify/<run-id>/evidence/<step>.png`.
- `*-before.txt` and `*-after.txt` camera roll listings, plus the saved MP4 copied out of `DCIM`.
- `server.log`, which `down` copies there. It shows the `queued <url>` and `done <url> (<title>)` lines.

Proof standards:
- Use the real user path: share sheet or paste field, not `$V api`. The API proves only the server half.
- Capture the action (share sheet with `ShareDL Verify` visible, progress card) and the result (`Saved to Photos` or auto-dismiss).
- Verify the side effects: a new file in `DCIM`, a `done` line in the server log, and `ffprobe` on the saved file.
- Use real network downloads. No mocks: yt-dlp hitting the real sites is exactly what can break.

## Cleanup

```sh
$V down
```

This:
- Kills only the uvicorn pid it started, after checking that the pid's command line matches the port.
- Uninstalls `dev.sharedl.verify.sharedl` from the simulator it installed to.
- Copies the server log into evidence, then deletes `.verify/<run-id>/instance`.

It prints `CLEANED ... evidence kept at <dir>`. Then `device_close` the simulator if you opened it. Never `pkill uvicorn` and never touch `com.sharedl.server`. Videos saved to the simulator's Photos stay there; that is simulator state, not the user's.

## Physical iPhone

Physical-device installs are not part of verification because they need signing. To install the user's real build:

```sh
cd ios && xcodegen && xcodebuild -project ShareDL.xcodeproj -scheme ShareDL \
  -destination 'id=<device udid>' -derivedDataPath build -allowProvisioningUpdates build
xcrun devicectl device install app --device <udid> build/Build/Products/Debug-iphoneos/ShareDL.app
```

This requires an Apple ID signed into Xcode → Settings → Accounts. Free-team builds expire after 7 days.

## Feature map

See `features/README.md`. A proof is incomplete if it skips an entry point the map lists.
