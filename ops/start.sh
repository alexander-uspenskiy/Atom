#!/usr/bin/env bash
# Start the whole Atom stack: llama-server (model) + dashboard backend. Ctrl+C stops both.
# Dashboard: http://127.0.0.1:8787   Model API: http://127.0.0.1:8080
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p logs

cleanup() { echo; echo "stopping..."; kill "${LLM_PID:-}" "${API_PID:-}" 2>/dev/null || true; wait 2>/dev/null || true; }
trap cleanup EXIT INT TERM

if curl -sf http://127.0.0.1:8080/health >/dev/null 2>&1; then
  echo "model server already running on :8080"
else
  echo "starting model server (log: logs/llama-server.log) ..."
  ops/llama-server.sh > logs/llama-server.log 2>&1 &
  LLM_PID=$!
fi

if [ ! -d web/dist ]; then
  echo "frontend not built: run 'cd web && pnpm install && pnpm build' (API still works)"
fi

echo "starting dashboard backend (log: logs/atom-serve.log) ..."
uv run python -m atom serve > logs/atom-serve.log 2>&1 &
API_PID=$!

echo "ready when the model has loaded (about a minute). Open http://127.0.0.1:8787"
wait
