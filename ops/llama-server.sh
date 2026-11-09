#!/usr/bin/env bash
# Start llama-server for Atom. Three slots: 0 = agent loop (kept warm), 1 = extraction / escalated thinking,
# 2 = dashboard chat. Separate slots mean one workload never evicts another's cached prefix.
set -euo pipefail

# Usage: ops/llama-server.sh [qwen|arete]   (default qwen; arete = NousResearch Arete-27B Q4_K_M on :8081)
PROFILE="${1:-${ATOM_PROFILE:-qwen}}"
case "$PROFILE" in
  qwen)  DEF_GGUF="$(ls "$HOME"/.cache/huggingface/hub/models--unsloth--Qwen3.8-27B-GGUF/snapshots/*/Qwen3.8-27B-UD-Q4_K_M.gguf | head -1)"
         DEF_PORT=8080; ALIAS=qwen3.8-27b ;;
  arete) DEF_GGUF="$(ls "$HOME"/.cache/huggingface/hub/models--bartowski--NousResearch_Arete-27B-GGUF/snapshots/*/NousResearch_Arete-27B-Q4_K_M.gguf | head -1)"
         DEF_PORT=8081; ALIAS=arete-27b ;;
  *) echo "unknown profile: $PROFILE (qwen|arete)" >&2; exit 2 ;;
esac
MODEL="${ATOM_GGUF:-$DEF_GGUF}"
# Vision projector (OCR / image understanding). Defaults to the mmproj next to the model; set ATOM_MMPROJ=none to disable.
MMPROJ="${ATOM_MMPROJ:-$(dirname "$MODEL")/mmproj-F16.gguf}"
[ -f "$MMPROJ" ] || MMPROJ="$(dirname "$MODEL")/mmproj-NousResearch_Arete-27B-f16.gguf"
MMPROJ_ARGS=()
if [ "$MMPROJ" != "none" ] && [ -f "$MMPROJ" ]; then MMPROJ_ARGS=(--mmproj "$MMPROJ"); fi
PORT="${ATOM_LLM_PORT:-$DEF_PORT}"
CTX_TOTAL="${ATOM_CTX_TOTAL:-98304}"   # divided across slots -> 32768 each

exec llama-server -m "$MODEL" --jinja \
  -c "$CTX_TOTAL" -np 3 -ngl 99 ${MMPROJ_ARGS[@]+"${MMPROJ_ARGS[@]}"} \
  --host 127.0.0.1 --port "$PORT" \
  --alias "$ALIAS"
