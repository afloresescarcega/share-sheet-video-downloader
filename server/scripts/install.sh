#!/bin/zsh
# One-time setup: venv, auth token, and two launchd agents
#   com.sharedl.server  - keeps the server running (starts at login, restarts on crash)
#   com.sharedl.update  - upgrades yt-dlp every day at 4am
set -euo pipefail
cd "$(dirname "$0")/.."
SERVER_DIR="$PWD"
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

for bin in ffmpeg ffprobe deno; do
  command -v $bin >/dev/null || { echo "Missing $bin: brew install ${bin/ffprobe/ffmpeg}"; exit 1; }
done

[[ -d .venv ]] || python3 -m venv .venv
./.venv/bin/pip install --quiet --upgrade pip
./.venv/bin/pip install --quiet -r requirements.txt

if [[ ! -f .env ]]; then
  echo "SHAREDL_TOKEN=$(openssl rand -hex 24)" > .env
  echo "SHAREDL_PORT=8787" >> .env
  echo "# SHAREDL_HOST=100.x.y.z   # bind to your Tailscale IP only (see README > Security)" >> .env
  echo "# SHAREDL_COOKIES=$SERVER_DIR/cookies.txt" >> .env
  chmod 600 .env
fi

mkdir -p logs ~/Library/LaunchAgents
chmod +x scripts/*.sh

cat > ~/Library/LaunchAgents/com.sharedl.server.plist <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.sharedl.server</string>
  <key>ProgramArguments</key><array><string>$SERVER_DIR/scripts/run.sh</string></array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$SERVER_DIR/logs/server.log</string>
  <key>StandardErrorPath</key><string>$SERVER_DIR/logs/server.log</string>
</dict></plist>
PLIST

cat > ~/Library/LaunchAgents/com.sharedl.update.plist <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.sharedl.update</string>
  <key>ProgramArguments</key><array><string>$SERVER_DIR/scripts/update-ytdlp.sh</string></array>
  <key>StartCalendarInterval</key><dict><key>Hour</key><integer>4</integer><key>Minute</key><integer>0</integer></dict>
  <key>StandardOutPath</key><string>$SERVER_DIR/logs/update.log</string>
  <key>StandardErrorPath</key><string>$SERVER_DIR/logs/update.log</string>
</dict></plist>
PLIST

for label in com.sharedl.server com.sharedl.update; do
  launchctl bootout "gui/$(id -u)/$label" 2>/dev/null || true
  launchctl bootstrap "gui/$(id -u)" ~/Library/LaunchAgents/$label.plist
done

source ./.env
echo
echo "Server running on port $SHAREDL_PORT. Logs: $SERVER_DIR/logs/server.log"
echo "Token (put this in ios/Config/Local.xcconfig): $SHAREDL_TOKEN"
