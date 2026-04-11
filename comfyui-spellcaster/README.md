# ComfyUI-Spellcaster

Architecture-aware nodes for AI image generation. Auto-detects your model architecture (SD 1.5, SDXL, Illustrious, ZIT, Flux Dev, Flux 2 Klein, Chroma), loads the correct CLIP and VAE, enhances prompts via local LLM, and samples with optimal settings — all automatically.

Part of the [Spellcaster](https://github.com/laboratoiresonore/spellcaster) ecosystem. ONE SOURCE OF TRUTH: the same architecture definitions power the GIMP plugin, Darktable plugin, and Wizard Guild.

## Nodes

### Spellcaster Loader (Auto-Arch)

Drop in any model and it figures out the rest. Detects architecture from the filename, loads the right CLIP encoder(s) and VAE automatically.

- **Checkpoint models** (SD 1.5, SDXL, Illustrious, ZIT): single-file load
- **Separate loaders** (Flux Dev, Klein, Chroma): auto-selects UNET + correct CLIP type + correct VAE
- **Klein CLIP auto-detect**: picks `qwen_3_8b` for 9B models, `qwen_3_4b` for 4B models
- **Flux dual CLIP**: loads both `clip_l` and `t5xxl` with correct type
- **Override inputs**: force architecture, CLIP, or VAE if auto-detect gets it wrong

**Outputs:** `MODEL`, `CLIP`, `VAE`, `arch_key` (string for downstream nodes)

### Spellcaster Prompt Enhance (LLM)

Sends your prompt to a local LLM (KoboldCpp, Ollama, or any OpenAI-compatible server) for rewriting, tuned per architecture.

- **Booru tag style** for SD 1.5 / SDXL / Illustrious: comma-separated tags with quality boosters
- **Natural language** for Flux / Klein / Chroma: descriptive sentences, no tag spam
- **Architecture guidance**: the LLM receives expert rules specific to each model
- **Graceful fallback**: if the LLM is offline, returns your original prompt unchanged

**Inputs:** prompt text, `arch_key` from Loader, LLM URL, enable/disable toggle

### Spellcaster Sampler (Auto-Config)

One sampler node that works for every architecture. Auto-selects the correct sampling pipeline and fills in optimal defaults.

- **Standard KSampler** for SD 1.5, SDXL, Illustrious, ZIT, Flux Dev
- **SamplerCustomAdvanced + CFGGuider** for Flux 2 Klein (automatic)
- **Auto-defaults**: steps, CFG, sampler algorithm, scheduler all populated from architecture config
- **Override anything**: steps, CFG, sampler, scheduler, denoise all accept manual overrides (0 = use default)

### Spellcaster Output (Privacy)

VAE decode + save with metadata stripping enabled by default.

- Decodes latent to image
- Strips generation parameters from PNG metadata (no prompt leaks)
- Clean timestamped filenames
- Toggle metadata stripping on/off

## Install

### ComfyUI Manager (recommended)

Search for **"Spellcaster"** in ComfyUI Manager and click Install.

### Manual (git clone)

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/laboratoiresonore/ComfyUI-Spellcaster.git
```

Restart ComfyUI. No pip dependencies required.

### Via Spellcaster Installer

If you're using the [Spellcaster installer](https://github.com/laboratoiresonore/spellcaster), the node pack is installed automatically.

## Workflow Templates

Drag these into ComfyUI to get started:

- `example_workflows/spellcaster_txt2img.json` — text-to-image with all 4 nodes
- `example_workflows/spellcaster_img2img.json` — image-to-image with prompt enhancement

## Supported Architectures

| Architecture | Loader | Sampler | Negative Prompt | Default Steps | Default CFG |
|---|---|---|---|---|---|
| SD 1.5 | checkpoint | KSampler | Yes | 25 | 7.0 |
| SDXL | checkpoint | KSampler | Yes | 30 | 6.5 |
| Illustrious | checkpoint | KSampler | Yes | 28 | 5.5 |
| ZIT (turbo) | checkpoint | KSampler | Yes | 6 | 2.0 |
| Flux 1 Dev | unet+clip+vae | KSampler | No | 25 | 3.5 |
| Chroma | unet+clip+vae | KSampler | No | 25 | 3.0 |
| Flux 2 Klein | unet+clip+vae | CustomAdvanced | No | 4 | 1.0 |
| Flux Kontext | unet+clip+vae | KSampler | No | 25 | 3.5 |

## License

MIT
