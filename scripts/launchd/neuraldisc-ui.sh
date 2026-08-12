#!/bin/bash
# NeuralDisc UI (LaunchAgent) on :3020 — proxies /api → :8020
set -euo pipefail

ROOT="/Users/alexclaw/Projects/NeuralDisc"
FRONTEND="$ROOT/frontend"
mkdir -p "$HOME/logs/neuraldisc"

export PATH="/opt/homebrew/bin:/usr/local/bin:$FRONTEND/node_modules/.bin:/usr/bin:/bin"
export NEURALDISC_API_URL="${NEURALDISC_API_URL:-http://127.0.0.1:8020}"
export HOSTNAME=127.0.0.1
export PORT=3020

cd "$FRONTEND"
exec /opt/homebrew/bin/node "$FRONTEND/node_modules/next/dist/bin/next" dev --port 3020 --hostname 127.0.0.1
