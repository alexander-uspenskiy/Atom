# Atom image service

Z-Image-Turbo (4-bit, ~5.9 GB) on Apple Silicon via [mflux](https://pypi.org/project/mflux/). It runs as its own
process in its own environment so MLX stays out of Atom. The model loads on the first request and unloads after
`IMAGEGEN_IDLE_S` seconds idle (default 300).

```bash
# one-time: weights into data/models/z-image-turbo-4bit
cd ops/imagegen && uv sync
HF_HUB_DISABLE_XET=1 uv run python -c "from huggingface_hub import snapshot_download as d; d('filipstrand/Z-Image-Turbo-mflux-4bit', local_dir='../../data/models/z-image-turbo-4bit', ignore_patterns=['.DS_Store'])"

./run.sh                      # http://127.0.0.1:8090
```

`POST /v1/images/generations` with `{"prompt": "...", "size": "1024x1024", "seed": 1}` returns the PNG path (under
`data/images/`) plus a small JPEG preview. Then turn on **Settings → Image generation** in the dashboard: chat and
agents get a `generate_image` tool and are shown each result so they can check it and retry.

**Where images go:** by default `data/images/`. When a chat project or an agent has a working folder, the PNG is moved
into `<folder>/generated-images/<timestamp>-<id>-<prompt-slug>.png` instead (the small preview stays in `data/images/`).

**Measured on an M1 Max 64GB** (Z-Image-Turbo 4-bit, 9 steps): 1024×1024 takes about 96 s warm and 113 s cold (model
load included); the service holds about 5.8 GB while loaded. Smaller sizes are much faster. Looking at a result costs the
vision model roughly 10-40 s (image encoding), so a generate-check-retry loop is a few minutes per round.

Env: `IMAGEGEN_MODEL`, `IMAGEGEN_OUT`, `IMAGEGEN_IDLE_S`, `IMAGEGEN_HOST`, `IMAGEGEN_PORT`.
