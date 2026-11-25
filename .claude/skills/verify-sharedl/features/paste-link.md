# Paste a link

In the ShareDL app, the user pastes or types a video URL and taps `Download to Photos`. The same progress, success and error card as the share extension appears inline under the button.

## Sub-features

- `paste-enable`: `Download to Photos` is disabled until the field contains an http(s) link, including a link inside surrounding text.
- `paste-save`: the video downloads and saves, and `Saved to Photos` shows the video title.
- `paste-submit`: pressing Go on the keyboard starts the download and dismisses the keyboard.
- `paste-error`: a failure shows `Couldn't save video` with the server message.

## How to get to it (user POV)

- Open ShareDL, go to the `Paste a link` section and use the `https://…` field.

## Driving it with agent-device + sharedl-verify

Preconditions:

- Baseline preconditions are met, and the app shows `Connected · yt-dlp …`.

- **Baseline.** Run `$V photos <udid> paste-before`.
- **Open the app.** Run `$AD open dev.sharedl.verify.sharedl --relaunch`. `snapshot -i` shows `[button] "Download to Photos" [disabled]`.
- **Enter the link.** Run `$AD fill <ref of [text-field] "https://…"> "https://www.youtube.com/shorts/tPEE9ZwTmy0" --settle`. The button is no longer `[disabled]`.
- **Download.** Press the `Download to Photos` ref. Within about 10s `snapshot -i` shows `[cell] "Saved to Photos"`. Screenshot to `evidence/paste-saved.png`.
- **Side effect.** Run `$V photos <udid> paste-after`. The diff shows one new MP4, and `ffprobe` shows `h264` + `aac`.
- **Error path.** Fill `https://example.com` and press Download. A `Couldn't save video` cell appears.

## Gotchas

- Granting the Photos permission kills the running app. Relaunch before driving, and take a fresh snapshot, because refs expire.
- The keyboard covers the status card. Screenshots may need `$AD swipe` down, or rely on `snapshot -i`.
