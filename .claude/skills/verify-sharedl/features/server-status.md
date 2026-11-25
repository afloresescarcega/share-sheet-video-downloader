# Server connection status

The ShareDL app's `Your Mac` section shows whether the download server is reachable and which yt-dlp version it runs, along with the server URL the build targets. `Retry` re-checks.

## Sub-features

- `status-ok`: a green dot and `Connected · yt-dlp <version>`, matching `/health`.
- `status-down`: a red dot and `Can't reach server` when the Mac server is not running.
- `status-retry`: `Retry` re-checks and recovers once the server is back.
- `status-url`: the footer shows `http://<SERVER_HOST>:<SERVER_PORT>`.

## How to get to it (user POV)

- Open ShareDL. The check runs on launch, and `Retry` sits next to the status.

## Driving it with agent-device + sharedl-verify

Preconditions:

- Baseline preconditions are met.

- **Healthy.** Run `$AD open dev.sharedl.verify.sharedl --relaunch` and `$AD snapshot -i`.
  - A cell reads `Connected · yt-dlp <v>`, where `<v>` equals the `yt_dlp` value printed by `$V doctor`.
  - A cell reads `http://127.0.0.1:<instance port>`.
- **Down.** Stop only your instance's server: `kill $(cat .verify/$(cat .verify/current)/instance/server.pid)`. Press `Retry`. The cell reads `Can't reach server`.
- **Recover.**
  - Running `$V up` again creates a new run on a new port, which would mean rebuilding the app.
  - To recover on the same port instead, restart uvicorn by hand. Use the instance's `env` (PORT, TOKEN) and the same command `cmd_up` in the helper uses.
  - Then press `Retry`. It shows `Connected` again.

## Gotchas

- Killing the server mid-run invalidates `$V doctor` until it is restarted. Do this feature last in a run, or follow it with `$V down`.
- On a physical phone, a `<name>.local` SERVER_HOST needs the same Wi-Fi and the Local Network permission. The simulator uses `127.0.0.1` and needs neither.
