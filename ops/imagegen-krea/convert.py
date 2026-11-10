"""One-time conversion: a Krea 2 Turbo finetune stored as one FP8 file (e.g. LUSTIFY V10) -> an mflux model folder.

MLX cannot compute in FP8, so the weights are dequantized to bfloat16 (the file's FP8 precision is the limit anyway),
combined with Krea's text encoder, VAE and tokenizer, then quantized to N bits and saved. The service loads the result.

    uv run python convert.py --fp8 ../../data/models/sdxl/lustify-v10-krea-turbo-fp8.safetensors \
        --base ../../data/models/krea2-base --out ../../data/models/lustify-v10-q8 --bits 8

--base is a folder holding vae/, text_encoder/ and tokenizer/ from krea/Krea-2-Turbo (see README.md). Needs about
30 GB of free memory while it runs; close the heavy apps first.
"""
from __future__ import annotations

import argparse
import gc
import shutil
import sys
from pathlib import Path


def dequantize_fp8_file(src: Path, dst: Path) -> None:
    """Write `src` (all tensors F8_E4M3) as a bfloat16 safetensors file without holding the model in memory.

    The output header is computed up front (bf16 is two bytes per element, FP8 one), then each tensor is dequantized with
    MLX and appended, so the peak is one tensor instead of the 26 GB model."""
    import json
    import struct

    import mlx.core as mx
    import numpy as np

    with open(src, "rb") as f:
        n = struct.unpack("<Q", f.read(8))[0]
        header = json.loads(f.read(n))
        base = 8 + n
        header.pop("__metadata__", None)
        bad = [k for k, v in header.items() if v["dtype"] != "F8_E4M3"]
        if bad:
            sys.exit(f"{len(bad)} tensors are not F8_E4M3 (first: {bad[0]}); this is not a plain FP8 Krea 2 file")
        names = sorted(header, key=lambda k: header[k]["data_offsets"][0])
        out_header, pos = {"__metadata__": {"format": "pt"}}, 0
        for k in names:
            count = header[k]["data_offsets"][1] - header[k]["data_offsets"][0]       # FP8: one byte per element
            out_header[k] = {"dtype": "BF16", "shape": header[k]["shape"], "data_offsets": [pos, pos + 2 * count]}
            pos += 2 * count
        blob = json.dumps(out_header, separators=(",", ":")).encode()
        blob += b" " * (-len(blob) % 8)
        with open(dst, "wb") as out:
            out.write(struct.pack("<Q", len(blob)))
            out.write(blob)
            for i, k in enumerate(names):
                begin, end = header[k]["data_offsets"]
                f.seek(base + begin)
                raw = np.frombuffer(f.read(end - begin), dtype=np.uint8)
                bf = mx.from_fp8(mx.array(raw), dtype=mx.bfloat16)
                out.write(np.array(bf.view(mx.uint16)).tobytes())
                if i % 50 == 0:
                    mx.clear_cache()
            written = out.tell()
    if written != 8 + len(blob) + pos:
        sys.exit("size mismatch while writing the bf16 file")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fp8", required=True, type=Path, help="the finetune's single FP8 .safetensors file")
    ap.add_argument("--base", required=True, type=Path, help="folder with vae/, text_encoder/, tokenizer/")
    ap.add_argument("--out", required=True, type=Path, help="output mflux folder (created)")
    ap.add_argument("--bits", type=int, choices=(4, 8), default=8)
    a = ap.parse_args()

    for part in ("vae", "text_encoder", "tokenizer"):
        if not (a.base / part).is_dir():
            sys.exit(f"missing {a.base / part}: download vae/, text_encoder/ and tokenizer/ from krea/Krea-2-Turbo first")
    if not a.fp8.is_file():
        sys.exit(f"not found: {a.fp8}")
    if a.out.exists():
        sys.exit(f"{a.out} already exists; remove it or choose another --out")

    import mlx.core as mx
    from mflux.models.common.config import ModelConfig
    from mflux.models.krea2.variants.txt2img.krea2 import Krea2

    stage = a.out.with_name(a.out.name + ".staging")
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)
    try:
        for part in ("vae", "text_encoder", "tokenizer"):
            (stage / part).symlink_to((a.base / part).resolve(), target_is_directory=True)
        for extra in a.base.glob("*.json"):
            (stage / extra.name).symlink_to(extra.resolve())
        for extra in ("added_tokens.json", "chat_template.jinja"):
            if (a.base / extra).exists() and not (stage / extra).exists():
                (stage / extra).symlink_to((a.base / extra).resolve())

        print("dequantizing FP8 -> bfloat16 (streamed, one tensor at a time) ...", flush=True)
        dequantize_fp8_file(a.fp8, stage / "turbo.safetensors")
        gc.collect()
        mx.clear_cache()

        print(f"loading with {a.bits}-bit quantization and saving to {a.out} ...", flush=True)
        model = Krea2(model_config=ModelConfig.krea2(), quantize=a.bits, model_path=str(stage))
        model.save_model(str(a.out))
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    print("done:", a.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
