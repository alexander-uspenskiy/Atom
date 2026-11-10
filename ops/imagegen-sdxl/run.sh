#!/usr/bin/env bash
# Local SDXL image service for Atom (diffusers on MPS). Listens on 127.0.0.1:8091.
# Checkpoints: data/models/sdxl/*.safetensors (names set in ops/imagegen-sdxl/models.json, see README.md).
set -euo pipefail
cd "$(dirname "$0")"
export PYTORCH_ENABLE_MPS_FALLBACK=1
exec uv run python server.py
