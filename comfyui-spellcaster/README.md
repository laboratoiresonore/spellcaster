# ComfyUI-Spellcaster-NSFW

Architecture-aware nodes for AI image generation **+ NSFW LoRA presets and management**. Extends [ComfyUI-Spellcaster](https://github.com/laboratoiresonore/ComfyUI-Spellcaster) with curated adult LoRA categories per architecture.

Part of the [Spellcaster NSFW](https://github.com/laboratoiresonore/spellcaster_NSFW) ecosystem.

> **Important:** Install this **instead of** the SFW version, not alongside it. This pack includes all 4 base nodes plus 2 NSFW-specific nodes.

## Nodes

### Base Nodes (inherited from SFW)

All 4 nodes from [ComfyUI-Spellcaster](https://github.com/laboratoiresonore/ComfyUI-Spellcaster) are included:

- **Spellcaster Loader (Auto-Arch)** — Auto-detect architecture, load MODEL + CLIP + VAE
- **Spellcaster Prompt Enhance (LLM)** — LLM-powered prompt rewriting per architecture
- **Spellcaster Sampler (Auto-Config)** — Auto-select KSampler vs CustomAdvanced
- **Spellcaster Output (Privacy)** — VAE decode + privacy-aware save

### NSFW Additions

#### Spellcaster NSFW LoRA (Presets)

Architecture-aware NSFW LoRA loader with curated categories. Connect the `arch_key` output from Spellcaster Loader to auto-filter presets.

**Three modes:**

- **preset** — Pick a single LoRA from an NSFW category (use `preset_index` to cycle through options)
- **manual** — Select any LoRA from your full loras/ folder
- **stack** — Apply ALL LoRAs in a category at once (with shared strength)

**Inputs:** MODEL, CLIP, mode, strength_model, strength_clip, arch_key, category, preset_index

**Outputs:** MODEL, CLIP, applied_loras (string listing what was loaded)

#### Spellcaster NSFW LoRA (Model Only)

Same as above but applies to MODEL only (no CLIP modification). Designed for video pipelines (WAN I2V) where CLIP is handled separately.

## NSFW LoRA Categories

| Architecture | Categories |
|---|---|
| Flux 1 Dev | nsfw_unlock, body_type, anatomy_detail, klein_nsfw |
| Flux 2 Klein | acts, effects |
| SDXL | anatomy_detail |
| Illustrious | anatomy_detail |
| WAN I2V | effects, acts, anatomy_detail, general_nsfw, motion |

The node auto-discovers which LoRAs are installed. Missing LoRAs are silently skipped.

## Install

### Manual (git clone)

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/laboratoiresonore/ComfyUI-Spellcaster-NSFW.git
```

Restart ComfyUI. No pip dependencies required.

### Via Spellcaster NSFW Installer

If you're using the [Spellcaster NSFW installer](https://github.com/laboratoiresonore/spellcaster_NSFW), the node pack is installed automatically.

## Workflow Templates

Drag these into ComfyUI to get started:

- `example_workflows/spellcaster_txt2img.json` — text-to-image (base nodes)
- `example_workflows/spellcaster_img2img.json` — image-to-image (base nodes)
- `example_workflows/spellcaster_nsfw_lora.json` — NSFW LoRA stacking workflow

## Updating

All core updates come from the SFW version. NSFW LoRA presets are maintained separately. `git pull` updates both.

## License

MIT
