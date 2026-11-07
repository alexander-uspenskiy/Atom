#!/usr/bin/env bash
# Start llama-server for Atom. Three slots: 0 = agent loop (kept warm), 1 = extraction / escalated thinking,
# 2 = dashboard chat. Separate slots mean one workload never evicts another's cached prefix.
set -euo pipefail

MODEL="${ATOM_GGUF:-$(ls "$HOME"/.cache/huggingface/hub/models--unsloth--Qwen3.8-27B-GGUF/snapshots/*/Qwen3.8-27B-UD-Q4_K_M.gguf | head -1)}"
PORT="${ATOM_LLM_PORT:-8080}"
CTX_TOTAL="${ATOM_CTX_TOTAL:-98304}"   # divided across slots -> 32768 each

exec llama-server -m "$MODEL" --jinja \
  -c "$CTX_TOTAL" -np 3 -ngl 99 \
  --host 127.0.0.1 --port "$PORT" \
  --alias qwen3.8-27b
