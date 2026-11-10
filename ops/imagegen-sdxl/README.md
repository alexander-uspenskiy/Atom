# Atom SDXL image service

Second image backend next to [ops/imagegen](../imagegen/README.md) (Z-Image). It serves three SDXL checkpoints with
[diffusers](https://github.com/huggingface/diffusers) on Apple Silicon (MPS), in its own environment so torch stays out
of Atom. No safety checker and no content filter are applied.

| `model` | for | prompt style |
|---|---|---|
| `lustify` (default) | photoreal, including adult content (LUSTIFY! SDXL, from Civitai) | English |
| `cyberrealistic` | photoreal, Pony-based, widest content range ([CyberRealistic Pony](https://huggingface.co/cyberdelia/CyberRealisticPony)) | tags |
| `illustrious` | anime, illustration ([Illustrious XL v1.0](https://huggingface.co/OnomaAIResearch/Illustrious-XL-v1.0)) | tags |

**Memory model:** checkpoints sit on disk and use no RAM. The one named in the request is loaded on demand; asking for a
different one unloads the current one first (10-30 s from SSD); the loaded one is freed after `IMAGEGEN_SDXL_IDLE_S`
seconds idle (default 300). One image at a time, other callers queue. Expect about 7-9 GB while loaded.

## Setup

```bash
cd ops/imagegen-sdxl && uv sync
mkdir -p ../../data/models/sdxl
```

Put single-file `.safetensors` checkpoints into `data/models/sdxl/`, named as in [models.json](models.json)
(`lustify-sdxl`, `cyberrealistic-pony`, `illustrious-xl`, each `.safetensors`). Get them from the model's own page
and check each model's license: CyberRealistic Pony and Illustrious have official Hugging Face repos; LUSTIFY is
distributed on Civitai. Using a different file (a NoobAI-XL finetune, another LUSTIFY
version) just means editing its `file` in models.json; you can also add more entries. The first load of any checkpoint
needs network once, so diffusers can fetch the small SDXL config files into the Hugging Face cache.

```bash
./run.sh                      # http://127.0.0.1:8091
curl -s localhost:8091/v1/models      # which checkpoints are present
```

Then switch on **Settings → Image generation → Enable SDXL models** in the dashboard. `generate_image` gets a `model`
argument (and `negative_prompt`); leave it out to use Z-Image. `ops/start.sh` starts this service by itself when a
checkpoint is present.

## Images page (no chat model)

The dashboard's **Images** page talks to this service (and Z-Image) directly, with no assistant in between, so the chat
model's refusals and rewrites never apply. Pick a model, type a prompt (tags for `cyberrealistic` and `illustrious`),
and optionally open **Settings** for steps, CFG, sampler, seed and a negative prompt; each field shows the model's
default as a placeholder. Finished PNGs are saved to **Settings → Image generation → Images page output folder**
(default `~/Projects/AtomImages`), and every result shows its full path as a link that opens the image. The page works
whether or not "Enable image generation" / "Enable SDXL models" are on; those switches only control the assistant's
`generate_image` tool.

## API

`POST /v1/images/generations` takes the Z-Image fields plus `model`, `cfg`, `steps` and `negative_prompt`, and returns the
same shape with an added `model`. `GET /v1/models` lists the registry; `GET /health` shows what is loaded.

Per model, models.json sets default steps, CFG, sampler (`euler_a` or `dpmpp_2m_karras`), a quality prefix and a
negative prompt. The service adds the prefix only for tags the caller has not written, and appends the caller's
`negative_prompt` to the default one. Prompts longer than CLIP's 77 tokens are encoded in chunks split between tags, so
long tag lists are not truncated.

## Tag prompts

Cyberrealistic and Illustrious need comma-separated booru tags. The skill [image-tag-prompts](skills/image-tag-prompts/SKILL.md)
tells the assistant and agents how to write them (order, rating and source tags, sizes, the retry loop). `ops/start.sh`
copies it into `~/.atom/skills` without overwriting an edited copy; to install it by hand:

```bash
mkdir -p ~/.atom/skills && cp -Rn skills/* ~/.atom/skills/
```

Env: `IMAGEGEN_SDXL_DIR`, `IMAGEGEN_SDXL_REGISTRY`, `IMAGEGEN_SDXL_OUT`, `IMAGEGEN_SDXL_IDLE_S`, `IMAGEGEN_SDXL_HOST`,
`IMAGEGEN_SDXL_PORT`.

Timings on an M1 Max have not been measured yet; they depend on checkpoint, steps and size.
