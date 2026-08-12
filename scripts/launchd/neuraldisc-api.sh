#!/bin/bash
# NeuralDisc API (LaunchAgent). Port 8020 — :8000 mineru, :8010 vllm-mlx.
set -euo pipefail

ROOT="/Users/alexclaw/Projects/NeuralDisc"
BACKEND="$ROOT/backend"
VENV="$BACKEND/.venv/bin"
LOG_DIR="$HOME/logs/neuraldisc"
mkdir -p "$LOG_DIR"

export PATH="$VENV:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
export NEURALDISC_LIBRARY_ROOT="${NEURALDISC_LIBRARY_ROOT:-$ROOT/data/NeuralDisc}"
export NEURALDISC_MLX_PEER_ID="${NEURALDISC_MLX_PEER_ID:-neuraldisc}"
export NEURALDISC_API_HOST=127.0.0.1
export NEURALDISC_API_PORT=8020

# Peer MLX lease — pull only needed keys (never `source` whole .env.local)
_envf="/Users/alexclaw/Projects/vinimidas/.env.local"
if [[ -f "$_envf" ]]; then
  while IFS= read -r line || [[ -n "$line" ]]; do
    case "$line" in
      ''|\#*) continue ;;
      VINIMIDAS_MCP_HTTP_SECRET=*|VINIMIDAS_MCP_HTTP_URL=*)
        key="${line%%=*}"
        val="${line#*=}"
        val="${val%$'\r'}"
        # strip surrounding quotes
        if [[ "$val" == \"*\" && "$val" == *\" ]]; then val="${val:1:${#val}-2}"; fi
        if [[ "$val" == \'*\' && "$val" == *\' ]]; then val="${val:1:${#val}-2}"; fi
        export "$key=$val"
        ;;
    esac
  done < "$_envf"
fi
export VINIMIDAS_MCP_HTTP_URL="${VINIMIDAS_MCP_HTTP_URL:-http://127.0.0.1:3100}"

cd "$BACKEND"
exec "$VENV/neuraldisc" serve --host 127.0.0.1 --port 8020
