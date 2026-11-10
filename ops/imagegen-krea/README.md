# Atom LUSTIFY service (Krea 2 Turbo on MLX)

Third image backend, next to [ops/imagegen](../imagegen/README.md) (Z-Image) and [ops/imagegen-sdxl](../imagegen-sdxl/README.md).
It serves model id `lustify`: **LUSTIFY V10**, a finetune of Krea 2 Turbo (a 12.9B-parameter diffusion transformer with a
Qwen3-VL text encoder), on Apple Silicon through [mflux](https://pypi.org/project/mflux/). It is not an SDXL model, so it
cannot run in the SDXL service. No content filter is applied by this service.

- **Prompts:** plain descriptive English. No tags, no negative prompt, no CFG or sampler (Turbo is distilled for about
  8 steps at guidance 1).
- **Memory model:** same as the other services: loaded on the first request, freed after `IMAGEGEN_KREA_IDLE_S` seconds
  idle (default 300), one image at a time. Expect about 15 GB while loaded with the 4-bit weights (about 21 GB with 8-bit): the transformer plus the bf16 text encoder.

## Setup

LUSTIFY V10 ships as one FP8 file. MLX cannot compute in FP8, so a one-time conversion dequantizes it, adds Krea's text
encoder, VAE and tokenizer, quantizes (4 or 8 bits) and saves an mflux folder. The conversion needs about 30 GB of free memory.

1. Save the LUSTIFY V10 Krea file (named `lustify-v10-krea-turbo-fp8.safetensors`) anywhere, for example in
   `data/models/sdxl/`.
2. Accept the license for [krea/Krea-2-Turbo](https://huggingface.co/krea/Krea-2-Turbo) on Hugging Face while logged in
   (Krea 2 Community License; read its terms), then fetch only the shared parts, not the 26 GB transformer:

   ```bash
   cd ops/imagegen-krea && uv sync
   uv run hf download krea/Krea-2-Turbo --local-dir ../../data/models/krea2-base \
     --include "vae/*" --include "text_encoder/*" --include "tokenizer/*" --include "*.json"
   ```
3. Convert:

   ```bash
   uv run python convert.py --fp8 ../../data/models/sdxl/lustify-v10-krea-turbo-fp8.safetensors \
     --base ../../data/models/krea2-base --out ../../data/models/lustify-v10-q4 --bits 4
   ```
4. Run it and turn on **Settings → Image generation → Enable LUSTIFY (Krea 2)**:

   ```bash
   ./run.sh                      # http://127.0.0.1:8092
   curl -s localhost:8092/v1/models
   ```

The Images page lists `lustify` as soon as the service is up; `ops/start.sh` starts the service when
`data/models/lustify-v10-q4` (or `-q8`) exists; the service prefers q4 when both exist. To use another Krea 2 Turbo finetune, convert it the same way into another folder
and point `IMAGEGEN_KREA_MODEL` at it.

## Speed and memory (measured on an M1 Max 64 GB)

Generation time scales with the number of pixels and is the same for 4-bit and 8-bit (the limit is GPU compute, not
memory bandwidth): 8 steps took about 4.5 minutes at 832x1216 (1.0 MP, 33 s per step) and about 2 minutes at 576x832
(0.5 MP, 16 s per step). 4-bit and 8-bit gave the same composition and similar quality for the same seed, so 4-bit is the
default because it leaves about 6 GB more free. Heavy swapping (other models loaded, a large chat-model context) makes
it slower still, so let the SDXL service idle-unload before long runs. For faster drafts use about 0.5 MP sizes
(`576x832`, `704x704`) and keep 1 MP for keepers. Atom's image timeout default is 900 s for this reason.

## API

`POST /v1/images/generations` with `{"prompt", "model": "lustify", "size", "seed", "steps"}` returns the same shape as the
other services. `GET /v1/models`, `GET /health`. Env: `IMAGEGEN_KREA_MODEL`, `IMAGEGEN_KREA_OUT`, `IMAGEGEN_KREA_IDLE_S`,
`IMAGEGEN_KREA_HOST`, `IMAGEGEN_KREA_PORT`.
