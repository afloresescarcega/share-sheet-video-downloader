# Server download and conversion

Given a video URL, the Mac server downloads it with yt-dlp and returns an MP4 that iOS Photos accepts: H.264 or HEVC (tagged `hvc1`) video with AAC audio. Other codecs are re-encoded.

## Sub-features

- `dl-youtube`: a regular YouTube watch URL.
- `dl-shorts`: a YouTube Shorts URL.
- `dl-tiktok`: TikTok, which often serves HEVC; it must come back tagged `hvc1`.
- `dl-x`: X/Twitter status URLs with video.
- `dl-reencode`: a VP9/AV1-only source is re-encoded to H.264 with VideoToolbox.
- `dl-error`: an unsupported or private URL ends `status=error` with yt-dlp's message.
- `dl-auth`: requests without the bearer token get 401.

## How to get to it (user POV)

- Indirectly, through the share extension or the paste field. Directly, through the HTTP API.

## Driving it with agent-device + sharedl-verify

Preconditions:

- `$V up` is done and `$V doctor` prints `DOCTOR OK`. No simulator is needed.

- **YouTube / Shorts / TikTok.**
  - Run `$V api https://www.youtube.com/watch?v=jNQXAC9IVRw dl-youtube`.
  - Run `$V api https://www.youtube.com/shorts/tPEE9ZwTmy0 dl-shorts`.
  - Run `$V api https://www.tiktok.com/@scout2015/video/6718335390845095173 dl-tiktok`.
  - Each prints `PASS <name>: video=h264/avc1 audio=aac/mp4a`. TikTok shows `video=hevc/hvc1`.
- **X.** Run `$V api <x.com status URL with a video> dl-x`. It prints `PASS`. Pick a current public tweet that has a video, and record the URL used.
- **Error.** Run `$V api https://example.com dl-error`. It exits non-zero with `FAIL: job ended: {...,"status":"error","error":"...Unsupported URL..."}`.
- **Auth.** `$V doctor` already asserts the 401 vs 404 behavior.
- **Evidence.** For each run, `evidence/<name>/` holds `video.mp4`, `ffprobe.json`, `codecs.txt` and `status.json`.

## Gotchas

- There is no stable X reference URL yet. `NASA/status/1856794469347242240` has no video and fails with `No video could be found in this tweet`. That is not a regression.
- `dl-reencode` needs a source with no avc1 stream, and none is pinned yet. Report it as unverified rather than claiming it via another feature.
- YouTube may return "Sign in to confirm you're not a bot". That is a site-side refusal, so report it with the `status.json` text.
- Deno must be on PATH (`/opt/homebrew/bin`), or YouTube extraction fails.
