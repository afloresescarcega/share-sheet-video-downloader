#!/bin/zsh
# Starts the server. launchd runs this; you can also run it by hand.
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
set -a; source ./.env; set +a
exec ./.venv/bin/uvicorn app:app --host 0.0.0.0 --port "${SHAREDL_PORT:-8787}"
