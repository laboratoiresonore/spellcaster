# HF snapshot — 2026-07-02

Trending / recently-modified diffusion repos captured by the every-48h cloud routine for use as the diff baseline in the next digest.

## Flux.2 Klein family — most-recently-modified

| Repo | Task | Last modified |
|---|---|---|
| epfl-vita/flux2-klein-1step-rdm | text-to-image | 2026-07-02 |
| geceff/Flux2Klein9B-comfyui | — | 2026-07-02 |
| Latentiq/Flux2_Klein_4B_3D2AI_LoRA | (LoRA) | 2026-07-01 |
| vladmandic/Flux.2-Klein-9B-KV-Merge-sdnq-hadamard-uint4 | text-to-image (diffusers) | 2026-07-01 |
| vladmandic/Flux.2-Klein-9B-KV-sdnq-hadamard-uint4 | — (diffusers) | 2026-07-01 |
| PontuzWPZ/FLUX.2-klein-9B | — | 2026-07-01 |
| MXKA/FLUX.2-klein-4B-GGUF | image-to-image (ggml/gguf) | 2026-07-01 |

Signal: intense end-of-June activity on Klein 9B KV-quant + 4B GGUF — the community is producing consumer-VRAM-friendly Klein variants in real time.

## Notable base repos (from earlier queries)

- black-forest-labs/FLUX.2-klein-4B
- black-forest-labs/FLUX.2-klein-9B
- black-forest-labs/FLUX.2-klein-9b-fp8
- black-forest-labs/FLUX.2-klein-9b-kv (KV-cache accelerated multi-reference editing)
- black-forest-labs/FLUX.2-klein-4b-fp8
- black-forest-labs/FLUX.2-klein-base-4B
- black-forest-labs/FLUX.2-klein-base-4b-fp8
- black-forest-labs/FLUX.2-dev (32 B, over VRAM ceiling)
- unsloth/FLUX.2-klein-9B-GGUF
- Tongyi-MAI/Z-Image-Turbo (baseline)

## Notes

- `hub_repo_search` with `sort=trendingScore` and query `text-to-image` returns lexical matches, not the true HF "trending" board — the ordering below is treated as approximate. Next run should call the query differently (try `sort=downloads` or narrower tag queries per architecture) to get truer trend deltas.
- `wan-2.2-i2v` query returned zero results — the current WAN line is 2.6 (see digest).
