#!/usr/bin/env bash
# Local Krea 2 Turbo image service for Atom (LUSTIFY V10 on MLX). Listens on 127.0.0.1:8092.
# Weights: data/models/lustify-v10-q4 (or -q8), built once with convert.py, see ops/imagegen-krea/README.md.
set -euo pipefail
cd "$(dirname "$0")"
exec uv run python server.py
