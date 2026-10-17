# Model Quantization — How Spellcaster Loads LLMs

This document describes how Spellcaster loads quantized LLM models from GGUF files. The quantization is **not** performed at runtime; Spellcaster only **loads pre-quantized** models and selects the right model based on quantisation level, size, and VRAM constraints.

## Core principle

Spellcaster never converts models on-the-fly (no bitsandbytes, GPTQ, or FP16→Q4 conversions). It downloads and loads only **pre-quantized** GGUF files and picks the best model for the current GPU and diffusion family.

The quantisation decision happens at **download time** via the model router and at **runtime** via `_pick_model()` which filters the available GGUF files by bit-width and size.

## Quantisation detection

### `_model_quant_bits(name) -> int`

Defined in `comfyui-spellcaster/spellcaster_core/comfyui_llm.py`:

```python
def _model_quant_bits(name):
    """Parse a GGUF filename for quantisation bit count.
    Qwen3-4B-Instruct-Q4_K_M.gguf → 4, ...Q5_K_M... → 5, ...Q8_0... → 8,
    fp16 / f16 → 16. Unknown → 8 (treat as heavy, so filters err on safe).
    """
    low = (name or "").lower()
    if "f16" in low or "fp16" in low:
        return 16
    if "q8" in low:
        return 8
    if "q6" in low:
        return 6
    if "q5" in low:
        return 5
    if "q4" in low:
        return 4
    if "q3" in low:
        return 3
    if "q2" in low:
        return 2
    return 8  # unknown → default to heavy
```

**Key rules:**

| File pattern | Quant bits | Comments |
|---|---|---|
| `*-Q4_K_M.gguf` | 4 | Preferred for minimal VRAM |
| `*-Q5_K_M.gguf` | 5 | Better accuracy, ~3 GB |
| `*-Q6_K.gguf` | 6 | Medium VRAM, better quality |
| `*-Q8_0.gguf` | 8 | High VRAM, best quality |
| `fp16` / `f16` | 16 | Unquantised, heavy |
| Unknown | 8 | Conservative default |

### `_model_size_b(name) -> int`

Parses parameter count from GGUF filenames:

```python
def _model_size_b(name):
    """Parse a GGUF filename for parameter count in billions.
    Substring match on -4b- / -8b- / -13b- etc. Unknown → 999.
    """
    low = (name or "").lower()
    for n in (1, 2, 3, 4, 6, 7, 8, 13, 14, 20, 30, 34, 70):
        if f"-{n}b-" in low or f"-{n}b." in low or f"_{n}b_" in low \
                or f"_{n}b." in low or f":{n}b" in low:
            return n
    return 999
```

**Supported parameter sizes:** 1B, 2B, 3B, 4B, 6B, 7B, 8B, 13B, 14B, 20B, 30B, 34B, 70B.

## Model selection

### `_pick_model(models, exclude=None, arch_key=None) -> str`

Filters available models and returns the best fit:

```python
def _pick_model(models, exclude=None, arch_key=None):
    """Choose the best model from the available list.

    Skips models in _failed_models (not downloaded) and any in exclude set.
    When arch_key is given, filters models whose quantisation or size
    exceed the family's cap (see _PER_FAMILY_LLM_CONFIG) — so SDXL won't
    try to load a Q8 8B model into a GPU that also has to host the SDXL
    checkpoint.
    """
    # 1. Remove permanently-failed models
    skip = _failed_models | (exclude or set())
    available = [m for m in models if m not in skip]
    if not available:
        available = models  # reset if all failed

    # 2. Apply per-family caps (if arch_key known)
    if arch_key:
        cfg = _family_config(arch_key)
        max_bits = cfg.get("max_quant_bits", 4)
        max_size = cfg.get("max_model_size_b", 4)
        filtered = [m for m in available
                    if _model_quant_bits(m) <= max_bits
                    and _model_size_b(m) <= max_size]
        if filtered:
            available = filtered

    # 3. Preference list (substring match)
    for pref in _MODEL_PREFERENCE:
        for m in available:
            if pref in m.lower():
                return m

    # 4. Heuristic fallback: smallest non-VL model with Q4 quantisation
    for m in available:
        low = m.lower()
        if "instruct" in low and "vl" not in low and "q4" in low:
            return m

    # 5. Last resort: alphabetically first
    return available[0]
```

### Example output

```
Available models (before filtering):
  - Qwen3-4B-Instruct-Q4_K_M.gguf
  - Qwen3-4B-Instruct-Q5_K_M.gguf
  - Qwen3-8B-Instruct-Q8_0.gguf

After filtering for sdxl family (max_quant_bits=4, max_model_size_b=4):
  - Qwen3-4B-Instruct-Q4_K_M.gguf
  - Qwen3-4B-Instruct-Q5_K_M.gguf

picked: Qwen3-4B-Instruct-Q4_K_M.gguf (preference match)
```

## Per-family VRAM management

The `_PER_FAMILY_LLM_CONFIG` table in `comfyui_llm.py` defines VRAM caps per diffusion family:

| Family | `max_quant_bits` | `max_model_size_b` | `keep_model_loaded` | Comments |
|---|---|---|---|---|
| sdxl | 4 | 4 | False | Tight VRAM on 8 GB cards |
| illustrious | 4 | 4 | False | SDXL finetune |
| pony | 4 | 4 | False | SDXL finetune |
| sd15 | 8 | 8 | True | 2 GB diffusion → room for 8B LLM |
| flux1dev | 4 | 4 | False | 12-16 GB diffusion |
| flux2klein | 4 | 4 | False | 11-14 GB diffusion |
| chroma | 4 | 4 | False | Flux 2 engine |
| flux_kontext | 4 | 4 | False | Flux edit instructions |
| wan | 5 | 4 | False | Video generation, Q5_K_M for better vocab |
| ltx | 5 | 4 | False | Long prompts, Q5_K_M acceptable |

## FP8 quantisation in video pipelines

While the LLM layer uses GGUF Q2–Q8 quantisation, the **video generation** paths use FP8:

- **Flux models**: `t5xxl_fp8_e4m3fn.safetensors` (CLIP text encoder)
- **SeedVR2 video upscale**: `seedvr2_ema_3b_fp8_e4m3fn.safetensors`

These are **separate FP8 quantisations** applied by ComfyUI nodes, not GGUF files. The FP8 mode is specified in workflow configs:

```python
quantization="fp8_e4m3fn",
base_precision="bf16",
```

See `comfyui-spellcaster/spellcaster_core/workflows.py` for FP8 usage in:

- `build_flux_video()` (line 3934)
- `_build_seedvr2_video_upscale()` (line 5515)

## Configuration files and naming conventions

### Model naming pattern

Spellcaster expects GGUF files in this format:

```
<model-name>-Q<bit>_<variant>.gguf
```

Examples:
- `Qwen3-4B-Instruct-Q4_K_M.gguf`
- `Qwen3-8B-Instruct-Q8_0.gguf`
- `Llama-3-8B-Q5_K_M.gguf`

### Pre-quantized artifacts

Only **pre-quantized** GGUF files are accepted. The repository does not produce or convert GGUF files — the download script (`spellcaster_core.download_llm`) fetches models from HuggingFace and validates their quantisation level via `_model_quant_bits()`.

## Limitations

| Limit | Details |
|---|---|
| **No runtime quantisation** | No bitsandbytes, GPTQ, or GGML quant conversions. All models are pre-quantized. |
| **No FP16/FP32 loading** | Only quantised GGUF files (Q2–Q8, fp16 as fallback). |
| **Maximum quant bits per family** | Hard-coded cap in `_PER_FAMILY_LLM_CONFIG`. SDXL cannot load Q5 or Q8 models. |
| **Maximum model size** | Families with large diffusion models are capped at 4B parameters. |
| **Vision-language models (VL)** | Not recommended; much larger and slower. The filter prefers text-only instruct models. |

## Summary

| Layer | Quantisation | Format | Source |
|---|---|---|---|
| LLM text generation | Q2–Q8 (bits) | GGUF | Pre-quantized HuggingFace models |
| Video generation | FP8 (e4m3fn) | safetensors | ComfyUI FP8 nodes |
| Diffusion (SDXL, Flux, etc.) | N/A | safetensors | Native model format |

**Rule of thumb:** If you're adding a new model, it must already be quantized to the right level for your family. Spellcaster **selects** among pre-quantized models; it never **creates** them.
