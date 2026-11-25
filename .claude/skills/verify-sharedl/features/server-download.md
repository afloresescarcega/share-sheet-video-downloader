# Server download and conversion

Given a video URL, the Mac server downloads it with yt-dlp and returns an MP4 that iOS Photos accepts: H.264 or HEVC (tagged `hvc1`) video with AAC audio. Other codecs are re-encoded.

## Sub-features

- `dl-youtube`: a regular YouTube watch URL.
- `dl-shorts`: a YouTube Shorts URL.
- `dl-tiktok`: TikTok, which often serves HEVC; it must come back tagged `hvc1`.
- `dl-x`: X/Twitter status URLs with video.
- `dl-reencode`: a VP9/AV1-only source is re-encoded to H.264 with VideoToolbox.
- `dl-error`: an unsupported or private URL ends `status=error` with yt-dlp's message.
- `dl-auth`: requests without the bearer token get 401. `/health` without the token returns only `{"ok":true}`, with no version.
- `dl-ssrf`: URLs whose host resolves to a private, loopback or link-local address (router, `localhost`, `169.254.169.254`), and non-http(s) schemes, are rejected with 400.
- `dl-limits`: playlist URLs download only the first video. Live streams, videos over `SHAREDL_MAX_DURATION_MIN` (180) and files over `SHAREDL_MAX_FILESIZE_MB` (2048) end in `error` with a "skipped" message. More than `SHAREDL_MAX_ACTIVE_JOBS` (6) concurrent jobs gets 429.
- `dl-nodocs`: `/docs`, `/redoc` and `/openapi.json` return 404.

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
- **SSRF.**
  - Load the instance's env with `source .verify/$(cat .verify/current)/instance/env`.
  - Run `curl -s -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d '{"url":"http://192.168.1.1/"}' http://127.0.0.1:$PORT/jobs`.
  - The response is `{"detail":"private or local addresses are not allowed"}`.
  - Repeat with `http://localhost/` and `http://169.254.169.254/`.
- **Limits.**
  - Start the instance with `SHAREDL_MAX_DURATION_MIN=0 $V up`.
  - Run `$V api 'https://www.youtube.com/watch?v=jNQXAC9IVRw' dl-limit`. It fails with `No video downloaded. Live streams, videos over 0 min ... are skipped.`
  - Quote URLs containing `?`, or zsh treats them as globs.
- **Playlist.**
  - Run `$V api 'https://www.youtube.com/watch?v=jNQXAC9IVRw&list=PL590L5WQmH8fJ54F369BLDSqIwcs-TCfs' dl-playlist`.
  - It prints `PASS`, and the instance's `downloads/` dir holds a single video.
- **No docs.** `curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:$PORT/docs` returns `404`.
- **Evidence.** For each run, `evidence/<name>/` holds `video.mp4`, `ffprobe.json`, `codecs.txt` and `status.json`.

## Gotchas

- There is no stable X reference URL yet. `NASA/status/1856794469347242240` has no video and fails with `No video could be found in this tweet`. That is not a regression.
- `dl-reencode` needs a source with no avc1 stream, and none is pinned yet. Report it as unverified rather than claiming it via another feature.
- YouTube may return "Sign in to confirm you're not a bot". That is a site-side refusal, so report it with the `status.json` text.
- Deno must be on PATH (`/opt/homebrew/bin`), or YouTube extraction fails.
