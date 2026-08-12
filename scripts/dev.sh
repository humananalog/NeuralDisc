#!/usr/bin/env bash
# Start backend + frontend for local development.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

export NEURALDISC_LIBRARY_ROOT="${NEURALDISC_LIBRARY_ROOT:-$HOME/NeuralDisc}"

# Backend
source "$ROOT/backend/.venv/bin/activate"
cd "$ROOT/backend"
python -c "from neuraldisc.config import get_settings; from neuraldisc.db.database import init_engine, create_all; s=get_settings(); s.ensure_layout(); init_engine(s); create_all()"
neuraldisc serve --host 127.0.0.1 --port 8020 &
BACKEND_PID=$!

# Frontend
cd "$ROOT/frontend"
# Default 3020 — do not use 3000 (often taken by other apps)
FRONTEND_PORT="${NEURALDISC_FRONTEND_PORT:-3020}"
npm run dev -- --port "$FRONTEND_PORT" --hostname 127.0.0.1 &
FRONTEND_PID=$!

cleanup() {
  kill "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "Backend  → http://127.0.0.1:8020  (docs /docs)"
echo "Frontend → http://127.0.0.1:$FRONTEND_PORT"
echo "Library  → $NEURALDISC_LIBRARY_ROOT"
wait
