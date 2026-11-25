# Share extension

From any app's share sheet, the user picks ShareDL. A card shows progress while the Mac downloads the video, then the MP4 is saved to the camera roll and the card dismisses itself. Failures stay on screen with yt-dlp's message.

## Sub-features

- `share-url`: a shared web URL (Safari, YouTube, X) is accepted.
- `share-text`: shared text containing a link (TikTok/X "caption + link") has its first http(s) URL extracted.
- `share-progress`: the card steps through `Asking your Mac…` → `Downloading on your Mac…` → `Sending to your phone…` → `Saving to camera roll…`.
- `share-save`: the video lands in Photos and the card auto-dismisses about 1.2s after `Saved to Photos`.
- `share-error`: a server or yt-dlp failure shows `Couldn't save video` with the message, and the button reads `Done`.
- `share-cancel`: `Cancel` closes the card mid-download.

## How to get to it (user POV)

- Safari: `Page Menu` → `Share` → `ShareDL` in the app row. The first time, it may be under `More`.
- The YouTube, TikTok or X app: Share → `ShareDL`. Not available in the simulator; physical device only.
- Any app sharing plain text that contains a link.

## Driving it with agent-device + sharedl-verify

Preconditions:

- Baseline preconditions from the README are met.
- Safari has been opened once and its onboarding dismissed: `$AD press 'text="Continue"'`, repeated until it's gone.

- **Baseline camera roll.** Run `$V photos <udid> share-before`. It prints `N videos in camera roll`.
- **Open a video page.** Run `$AD open com.apple.mobilesafari "https://www.youtube.com/watch?v=jNQXAC9IVRw"`. The `Me at the zoo` page loads.
- **Open the share sheet.**
  - Run `$AD snapshot -i`, press the `Page Menu` button ref, then press the `[cell] "Share"` ref.
  - Screenshot to `evidence/share-1-sheet.png`. The sheet shows `jawed · youtube.com`.
- **Pick ShareDL Verify.**
  - Swipe the app row with `$AD swipe 300 650 120 650` until `ShareDL Verify` is fully visible.
  - Screenshot, then `$AD press <x> <y>` on its icon. On an iPhone 18 Pro after one swipe, that was about `244 642`.
  - Screenshot every ~0.7s into `evidence/share-3-progress-N.png`. A frame shows the `Save Video` card with `Downloading on your Mac…`.
- **Confirm the save.**
  - After about 5s the card is gone and Safari is back.
  - Run `$V photos <udid> share-after` and `diff` it with `share-before`. Exactly one new `DCIM/100APPLE/IMG_*.MP4` appears.
  - Copy that file to `evidence/share-saved-video.mp4`. `ffprobe` shows `h264` and `aac`.
- **Server side.** `.verify/<run>/instance/server.log` (or `evidence/server.log` after `down`) contains `queued https://www.youtube.com/watch?v=jNQXAC9IVRw` and `done ... (Me at the zoo)`.
- **Error path.**
  - Share a page with no video, such as `https://example.com`.
  - The card stays with `Couldn't save video` and a yt-dlp `Unsupported URL` message, and the button reads `Done`.

## Gotchas

- The share sheet is a remote view. Snapshot refs list `ShareDL` cells, but their rects are relative to the sheet, so pressing the ref does nothing. Press by screenshot coordinates instead.
- Two ShareDL icons appear if the user's own build is installed in the same simulator. Only `ShareDL Verify` talks to your instance; tapping `ShareDL` hits the user's live server.
- The first screenshot after tapping can be a blank white sheet while it animates in. Take more frames.
- A fresh simulator's Safari opens onboarding ("Continue" screens) instead of the URL. Dismiss them, then reopen the URL.
- Success is fast for short videos (under 5s), so a progress frame can be missed. The camera roll diff is the authoritative proof.
- Real YouTube, TikTok and X apps aren't installable in the simulator, so the `share-text` path is only proven on a physical device.
