#!/usr/bin/env bash
# Local image service for Atom (Z-Image-Turbo 4-bit on MLX). Listens on 127.0.0.1:8090.
# Weights: data/models/z-image-turbo-4bit (see ops/imagegen/README.md for the download command).
set -euo pipefail
cd "$(dirname "$0")"
exec uv run python server.py
