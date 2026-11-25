# yt-dlp auto-update

Every day at 4am, a launchd agent upgrades yt-dlp in the server venv. If the version changed, it restarts the server, so site breakages get fixed without the user doing anything.

## Sub-features

- `update-schedule`: `com.sharedl.update` is loaded with `StartCalendarInterval` Hour 4.
- `update-run`: `server/scripts/update-ytdlp.sh` logs `<date> yt-dlp <before> -> <after>`.
- `update-restart`: when the version changes, it runs `launchctl kickstart -k` on `com.sharedl.server`.

## How to get to it (user POV)

- Nothing to click. The user sees `Connected · yt-dlp <newer version>` in the app the next day.

## Driving it with agent-device + sharedl-verify

Preconditions:

- `server/scripts/install.sh` has been run on this Mac.

- **Schedule loaded (read-only).** Run `launchctl print gui/$(id -u)/com.sharedl.update | grep -A3 -i calendar`. It shows `Hour => 4`.
- **Last run (read-only).** Run `tail -5 server/logs/update.log`. Each run is one line, `YYYY-MM-DD HH:MM:SS yt-dlp X -> Y`.
- **Server version (read-only).** Run `curl -s localhost:8787/health`. `yt_dlp` equals the `Y` on the last log line.

## Gotchas

- Running `update-ytdlp.sh` by hand mutates the user's real `server/.venv` and may restart their live server. Do it only when the user asks, and never mid-download.
- The isolated `$V up` instance shares the same venv, so an update also changes the yt-dlp version the verify instance uses after its next restart.
