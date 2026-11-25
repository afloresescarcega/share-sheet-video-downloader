#!/bin/zsh
# Upgrades yt-dlp (sites break it often) and restarts the server if it changed.
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
before=$(./.venv/bin/python -c 'import yt_dlp; print(yt_dlp.version.__version__)')
./.venv/bin/pip install --quiet --upgrade "yt-dlp[default]"
after=$(./.venv/bin/python -c 'import yt_dlp; print(yt_dlp.version.__version__)')
echo "$(date '+%F %T') yt-dlp $before -> $after"
if [[ "$before" != "$after" ]]; then
  launchctl kickstart -k "gui/$(id -u)/com.sharedl.server" || true
fi
