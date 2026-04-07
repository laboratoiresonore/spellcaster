# Spellcaster Refactoring Audit

## Executive Summary

The GIMP plugin (`comfyui-connector.py`, 22,459 lines) and Darktable plugin (`comfyui_connector.lua`, 7,400 lines) have grown organically into monolithic files. The Flux2Scheduler breaking change exposed the core problem: **91 unique ComfyUI node types are hardcoded across 39 workflow-building functions**, making any upstream API change a multi-hour search-and-replace operation.

This audit proposes a layered refactoring that introduces a **Node Abstraction Layer**, **Architecture Registry**, and **Workflow Composer** pattern. The goal: when a node like `Flux2Scheduler` changes its API, you fix *one function* instead of nine.

---

## 1. Current Architecture Analysis

### 1.1 What We Have

```
comfyui-connector.py (22,459 lines, single file)
  |
  +-- 86 top-level functions
  +-- 8 classes (7 dialogs + 1 Gimp.PlugIn)
  +-- 118 class methods
  +-- 39 workflow builders (_build_*)
  +-- 25+ data structure dicts/lists
  +-- 91 unique ComfyUI node types referenced
```

Everything lives in one file because GIMP 3's Python plugin loader expects a single entry point. This constraint is real but doesn't prevent internal modularization via logical sections or a bundled package.

### 1.2 The Seven Architectures

| Arch Key       | Loader Pattern                      | Sampler          | CFG  | Steps | Notes                        |
|----------------|-------------------------------------|------------------|------|-------|------------------------------|
| `sd15`         | CheckpointLoaderSimple              | KSampler         | 7.0  | 20-25 | Oldest, simplest             |
| `sdxl`         | CheckpointLoaderSimple              | KSampler         | 5.5  | 25-30 | Most presets (15+)           |
| `illustrious`  | CheckpointLoaderSimple              | KSampler         | 5.5  | 28    | SDXL-based anime             |
| `zit`          | CheckpointLoaderSimple              | KSampler         | 1.0  | 4-12  | Turbo SDXL distill           |
| `flux1dev`     | UNETLoader + CLIPLoader + VAELoader | KSampler         | 3.5  | 20-30 | No negative prompts          |
| `flux2klein`   | UNETLoader + CLIPLoader + VAELoader | SamplerCustomAdv | 1.0  | 4     | ReferenceLatent, Flux2Sched  |
| `flux_kontext` | UNETLoader + CLIPLoader + VAELoader | KSampler         | 3.5  | 20    | Edit instructions, no neg    |

### 1.3 Core Problem: Hardcoded Node Graphs

Every `_build_*()` function constructs a raw dict with string node IDs, class_type strings, and input wiring. Example from `_build_img2img`:

```python
"32": {"class_type": "Flux2Scheduler",
       "inputs": {"steps": 20, "width": ["12", 0], "height": ["12", 1]}},
```

When `Flux2Scheduler` changed its API, we had to find and fix all 9 occurrences manually. The same would happen if `KSampler`, `VAEEncode`, `CLIPTextEncode`, or any of the other 91 node types changed.

### 1.4 Repeated Patterns (Duplication Hotspots)

| Pattern                        | Occurrences | Lines Each | Total Waste |
|--------------------------------|-------------|------------|-------------|
| Model loader + LoRA injection  | 7+          | ~15        | ~105        |
| CLIP pos/neg encoding pair     | 20+         | ~4         | ~80         |
| KSampler with conditioning     | 10+         | ~12        | ~120        |
| VAEEncode/VAEDecode bookends   | 12+         | ~4         | ~48         |
| SaveImage output node          | 25+         | ~2         | ~50         |
| Dialog _collect/_apply presets | 8           | ~30        | ~240        |
| Server fetch callbacks         | 8+          | ~10        | ~80         |
| Turbo toggle logic             | 4+          | ~20        | ~80         |

Conservative estimate: **~800 lines** of pure duplication that can be eliminated.

---

## 2. Proposed Architecture

### 2.1 Layer Diagram

```
Layer 4: GIMP/Darktable UI          (dialogs, callbacks, image I/O)
Layer 3: Workflow Composer           (task recipes: img2img, inpaint, faceswap...)
Layer 2: Node Factory                (node constructors with version awareness)
Layer 1: Architecture Registry       (model configs, arch-specific behaviors)
Layer 0: Transport                   (server comms, upload/download, queue polling)
```

Each layer only talks to the one below it. A node API change is isolated to Layer 2. A new architecture is isolated to Layer 1. A new workflow is isolated to Layer 3.

### 2.2 Layer 1: Architecture Registry

Replace the scattered `_AUTOSET_*` dicts, `MODEL_PRESETS`, `TURBO_CONFIGS`, `ARCH_LORA_PREFIXES`, and inline `if arch == "flux1dev"` checks with a single registry:

```python
ARCHITECTURES = {
    "sd15": ArchConfig(
        loader="checkpoint",        # CheckpointLoaderSimple
        sampler="ksampler",         # KSampler
        clip_mode="single",         # One CLIP encoder
        vae_mode="bundled",         # VAE from checkpoint
        supports_negative=True,
        default_cfg=7.0,
        default_steps=22,
        default_denoise=0.65,
        default_resolution=(512, 512),
        lora_prefixes=[],
        quality_boost_positive="(masterpiece), (best quality), ...",
        quality_boost_negative="(worst quality), ...",
        turbo_lora=("SD1.5\\turbo_sd_v5.safetensors", 0.5),
        controlnet_models={...},
    ),
    "flux1dev": ArchConfig(
        loader="unet_clip_vae",     # Separate loaders
        sampler="ksampler",
        clip_mode="dual",           # DualCLIPLoader or CLIPLoader
        vae_mode="separate",
        supports_negative=False,    # No negative prompts
        default_cfg=3.5,
        default_steps=25,
        default_denoise=0.55,
        default_resolution=(1024, 1024),
        lora_prefixes=["Flux-1-Dev\\"],
        quality_boost_positive="professional photo, ...",
        quality_boost_negative="",
        turbo_lora=("Flux-1-Dev\\Hyper-FLUX-8Steps.safetensors", 0.125),
        controlnet_models={...},
    ),
    "flux2klein": ArchConfig(
        loader="unet_clip_vae",
        sampler="custom_advanced",  # SamplerCustomAdvanced + CFGGuider
        clip_mode="single_gguf",    # CLIPLoaderGGUF with Qwen
        vae_mode="separate",
        supports_negative=False,
        default_cfg=1.0,
        default_steps=4,
        default_denoise=0.65,
        default_resolution=(1024, 1024),
        lora_prefixes=["Flux-2-Klein\\"],
        scheduler="flux2",         # Flux2Scheduler
        reference_latent=True,     # Uses ReferenceLatent
    ),
    # ... etc for sdxl, illustrious, zit, flux_kontext
}
```

**Benefits:**
- Adding a new architecture = adding one dict entry
- Architecture-specific behavior queries become `ARCHITECTURES[arch].supports_negative` instead of `if arch in ("flux1dev", "flux2klein", "flux_kontext")`
- Spellmaker can query the registry to understand what any architecture supports

### 2.3 Layer 2: Node Factory

Replace raw dict construction with factory functions that encapsulate node API knowledge:

```python
class NodeFactory:
    """Centralized ComfyUI node constructors. ONE place to update when APIs change."""

    _next_id = 1

    def __init__(self):
        self._nodes = {}
        self._next_id = 1

    def _add(self, class_type, inputs, node_id=None):
        nid = node_id or str(self._next_id)
        self._next_id = max(self._next_id, int(nid)) + 1
        self._nodes[nid] = {"class_type": class_type, "inputs": inputs}
        return nid

    # ── Model Loading ──────────────────────────────────────────
    def checkpoint_loader(self, ckpt_name, node_id=None):
        return self._add("CheckpointLoaderSimple",
                         {"ckpt_name": ckpt_name}, node_id)

    def unet_loader(self, unet_name, weight_dtype="default", node_id=None):
        return self._add("UNETLoader",
                         {"unet_name": unet_name, "weight_dtype": weight_dtype}, node_id)

    def clip_loader(self, clip_name, clip_type="stable_diffusion", node_id=None):
        return self._add("CLIPLoader",
                         {"clip_name": clip_name, "type": clip_type}, node_id)

    def vae_loader(self, vae_name, node_id=None):
        return self._add("VAELoader", {"vae_name": vae_name}, node_id)

    def lora_loader(self, model_ref, clip_ref, lora_name,
                    strength_model=1.0, strength_clip=1.0, node_id=None):
        return self._add("LoraLoader", {
            "model": model_ref, "clip": clip_ref,
            "lora_name": lora_name,
            "strength_model": strength_model, "strength_clip": strength_clip,
        }, node_id)

    # ── Conditioning ───────────────────────────────────────────
    def clip_encode(self, clip_ref, text, node_id=None):
        return self._add("CLIPTextEncode",
                         {"clip": clip_ref, "text": text}, node_id)

    def conditioning_pair(self, clip_ref, positive, negative):
        """Encode pos/neg prompts. Returns (pos_id, neg_id)."""
        pos_id = self.clip_encode(clip_ref, positive)
        neg_id = self.clip_encode(clip_ref, negative)
        return pos_id, neg_id

    # ── Sampling ───────────────────────────────────────────────
    def ksampler(self, model_ref, positive_ref, negative_ref, latent_ref,
                 seed, steps, cfg, sampler_name, scheduler, denoise, node_id=None):
        return self._add("KSampler", {
            "model": model_ref, "positive": [positive_ref, 0],
            "negative": [negative_ref, 0], "latent_image": [latent_ref, 0],
            "seed": seed, "steps": steps, "cfg": cfg,
            "sampler_name": sampler_name, "scheduler": scheduler,
            "denoise": denoise,
        }, node_id)

    def flux2_scheduler(self, steps, width_ref, height_ref, node_id=None):
        """Flux2Scheduler — NEW API (steps, width, height only)."""
        return self._add("Flux2Scheduler", {
            "steps": steps,
            "width": width_ref,   # e.g. ["12", 0]
            "height": height_ref, # e.g. ["12", 1]
        }, node_id)

    def basic_scheduler(self, model_ref, steps, denoise,
                        scheduler="simple", node_id=None):
        """BasicScheduler — used for img2img when denoise is needed."""
        return self._add("BasicScheduler", {
            "model": model_ref, "scheduler": scheduler,
            "steps": steps, "denoise": denoise,
        }, node_id)

    # ── Image I/O ──────────────────────────────────────────────
    def load_image(self, filename, node_id=None):
        return self._add("LoadImage", {"image": filename}, node_id)

    def save_image(self, images_ref, prefix="gimp_comfy", node_id=None):
        return self._add("SaveImage",
                         {"images": images_ref, "filename_prefix": prefix}, node_id)

    def vae_encode(self, pixels_ref, vae_ref, node_id=None):
        return self._add("VAEEncode",
                         {"pixels": pixels_ref, "vae": vae_ref}, node_id)

    def vae_decode(self, samples_ref, vae_ref, node_id=None):
        return self._add("VAEDecode",
                         {"samples": samples_ref, "vae": vae_ref}, node_id)

    # ── Helpers ────────────────────────────────────────────────
    def image_scale(self, image_ref, width, height,
                    upscale_method="lanczos", crop="disabled", node_id=None):
        return self._add("ImageScale", {
            "image": image_ref, "width": width, "height": height,
            "upscale_method": upscale_method, "crop": crop,
        }, node_id)

    def build(self):
        """Return the completed workflow dict."""
        return dict(self._nodes)
```

**The Flux2Scheduler incident with this pattern:**

Before (scattered across 9 functions):
```python
# Had to find and fix each one manually
"32": {"class_type": "Flux2Scheduler",
       "inputs": {"model": [...], "steps": 20, "denoise": 0.35, ...}}
```

After (single function):
```python
# Fix NodeFactory.flux2_scheduler() once, all 9 workflows are fixed
nf.flux2_scheduler(steps=20, width_ref=["12", 0], height_ref=["12", 1])
```

### 2.4 Layer 2.5: Composite Builders (Architecture-Aware)

Higher-level functions that combine multiple nodes using the registry:

```python
def load_model_stack(nf, arch_config, preset):
    """Load model+clip+vae per architecture. Returns (model_ref, clip_ref, vae_ref)."""
    if arch_config.loader == "checkpoint":
        ckpt_id = nf.checkpoint_loader(preset["checkpoint"])
        return ([ckpt_id, 0], [ckpt_id, 1], [ckpt_id, 2])
    elif arch_config.loader == "unet_clip_vae":
        unet_id = nf.unet_loader(preset["unet"], preset.get("weight_dtype", "default"))
        clip_id = nf.clip_loader(preset["clip"], preset.get("clip_type", "flux"))
        vae_id  = nf.vae_loader(preset["vae"])
        return ([unet_id, 0], [clip_id, 0], [vae_id, 0])

def inject_lora_chain(nf, loras, model_ref, clip_ref):
    """Insert LoRA chain. Returns updated (model_ref, clip_ref)."""
    for lora_name, str_model, str_clip in loras:
        lid = nf.lora_loader(model_ref, clip_ref, lora_name, str_model, str_clip)
        model_ref = [lid, 0]
        clip_ref = [lid, 1]
    return model_ref, clip_ref

def encode_prompts(nf, arch_config, clip_ref, positive, negative):
    """Encode prompts, respecting arch (no negative for Flux)."""
    pos_id = nf.clip_encode(clip_ref, positive)
    if arch_config.supports_negative and negative:
        neg_id = nf.clip_encode(clip_ref, negative)
    else:
        neg_id = nf._add("ConditioningZeroOut", {"conditioning": [pos_id, 0]})
    return pos_id, neg_id

def sample_standard(nf, arch_config, model_ref, pos_ref, neg_ref,
                    latent_ref, seed, preset):
    """Standard sampling path for sd15/sdxl/flux1dev."""
    return nf.ksampler(
        model_ref, pos_ref, neg_ref, latent_ref, seed,
        preset["steps"], preset["cfg"],
        preset.get("sampler", "euler"),
        preset.get("scheduler", "normal"),
        preset.get("denoise", 1.0))

def sample_klein(nf, model_ref, pos_ref, neg_ref, latent_ref,
                 noise_ref, sigmas_ref, seed, preset):
    """Klein sampling path (SamplerCustomAdvanced + CFGGuider)."""
    guider_id = nf._add("CFGGuider", {
        "model": model_ref, "positive": [pos_ref, 0],
        "negative": [neg_ref, 0], "cfg": preset.get("cfg", 1.0)})
    sampler_id = nf._add("KSamplerSelect", {"sampler_name": "euler"})
    return nf._add("SamplerCustomAdvanced", {
        "guider": [guider_id, 0], "sampler": [sampler_id, 0],
        "sigmas": [sigmas_ref, 0], "noise": [noise_ref, 0],
        "latent_image": [latent_ref, 0]})
```

### 2.5 Layer 3: Workflow Composer

The existing `_build_*()` functions become thin orchestrators:

```python
def build_img2img(preset, image_filename, prompt, negative, seed, loras=None):
    arch = ARCHITECTURES[preset["arch"]]
    nf = NodeFactory()

    # Load model stack
    model_ref, clip_ref, vae_ref = load_model_stack(nf, arch, preset)

    # LoRA chain
    if loras:
        model_ref, clip_ref = inject_lora_chain(nf, loras, model_ref, clip_ref)

    # Encode prompts
    pos_id, neg_id = encode_prompts(nf, arch, clip_ref, prompt, negative)

    # Load + encode image
    img_id = nf.load_image(image_filename)
    latent_id = nf.vae_encode([img_id, 0], vae_ref)

    # Sample
    if arch.sampler == "custom_advanced":
        # Klein path
        sample_id = sample_klein(nf, model_ref, pos_id, neg_id, ...)
    else:
        # Standard path
        sample_id = sample_standard(nf, arch, model_ref, pos_id, neg_id,
                                     latent_id, seed, preset)

    # Decode + save
    decode_id = nf.vae_decode([sample_id, 0], vae_ref)
    nf.save_image([decode_id, 0], "gimp_comfy")

    return nf.build()
```

This is ~25 lines vs the current ~120 lines in `_build_img2img`.

---

## 3. Refactoring Roadmap

### Phase 1: Node Factory (Highest Impact, Lowest Risk)

**Effort:** ~2 days
**Risk:** Low (additive, doesn't break existing code)
**Impact:** Eliminates node API change vulnerability

1. Create `NodeFactory` class with constructors for all 91 node types
2. Add it at the top of the file (still single-file, no structural change)
3. Migrate `_build_*` functions one at a time to use NodeFactory
4. Each migration is independently testable: `old_build() == new_build()` for same inputs

**Priority nodes to wrap first** (most-used, most-changed):
- `KSampler` (14 uses)
- `CLIPTextEncode` (38 uses)
- `LoadImage` (56 uses)
- `SaveImage` (44 uses)
- `VAEEncode` / `VAEDecode` (24/22 uses)
- `Flux2Scheduler` / `BasicScheduler` (9 uses — the ones that just broke)
- `CheckpointLoaderSimple` / `UNETLoader` (12+ uses each)

### Phase 2: Architecture Registry (High Impact)

**Effort:** ~1 day
**Risk:** Low (data restructure, no logic change)
**Impact:** Centralizes all arch-specific config, enables Spellmaker queries

1. Define `ArchConfig` dataclass/namedtuple
2. Build `ARCHITECTURES` dict from existing scattered dicts
3. Replace inline `if arch ==` checks with registry lookups
4. Remove `_AUTOSET_PROMPTS`, `_AUTOSET_CFG`, `_AUTOSET_STEPS`, `_AUTOSET_DENOISE`, `_AUTOSET_CN`, `_AUTOSET_LORAS` (fold into `ARCHITECTURES`)

**Dicts that get absorbed:**
| Current Dict | Lines | Destination |
|---|---|---|
| `_AUTOSET_PROMPTS` | 9351 | `ArchConfig.default_prompts` |
| `_AUTOSET_CFG` | 9367 | `ArchConfig.default_cfg` |
| `_AUTOSET_STEPS` | 9372 | `ArchConfig.default_steps` |
| `_AUTOSET_DENOISE` | 9377 | `ArchConfig.default_denoise` |
| `_AUTOSET_CN` | 9397 | `ArchConfig.default_controlnet` |
| `_AUTOSET_LORAS` | 9430 | `ArchConfig.default_loras` |
| `QUALITY_BOOST_POSITIVE` | 487 | `ArchConfig.quality_positive` |
| `QUALITY_BOOST_NEGATIVE` | 501 | `ArchConfig.quality_negative` |
| `ARCH_LORA_PREFIXES` | 1421 | `ArchConfig.lora_prefixes` |
| `TURBO_CONFIGS` | 1449 | `ArchConfig.turbo_config` |

### Phase 3: Composite Builders (Medium Impact)

**Effort:** ~2 days
**Risk:** Medium (changes workflow construction logic)
**Impact:** Eliminates ~800 lines of duplication

1. Implement `load_model_stack()`, `inject_lora_chain()`, `encode_prompts()`, `sample_standard()`, `sample_klein()`
2. Refactor `_build_img2img`, `_build_txt2img`, `_build_inpaint` first (most-used)
3. Gradually migrate remaining 36 workflow builders

### Phase 4: Dialog Consolidation (Lower Priority)

**Effort:** ~2 days
**Risk:** Medium (UI changes)
**Impact:** Reduces dialog boilerplate by ~50%

1. Extract `BasePresetDialog` with shared `_collect_user_preset` / `_apply_user_preset` / `_add_lora_row` / `_add_turbo_toggle`
2. Specialized dialogs inherit and override only unique parts
3. Unify server fetch callback pattern into `_async_fetch_and_populate(combo, fetch_fn)`

### Phase 5: Logical File Splitting (Optional, Long-term)

**Effort:** ~1 day
**Risk:** Low (but requires GIMP plugin loader consideration)
**Impact:** Navigability, parallel development

GIMP 3 requires a single entry-point file, but it can import from sibling modules. Structure:

```
comfyui-connector/
  comfyui-connector.py     # Entry point: imports + Spellcaster class only
  _nodes.py                # NodeFactory
  _architectures.py        # ARCHITECTURES registry + ArchConfig
  _workflows.py            # All _build_* functions
  _dialogs.py              # All dialog classes
  _presets.py              # MODEL_PRESETS, SCENE_PRESETS, etc.
  _transport.py            # Server comms (_api_get, _upload_image, etc.)
  _utils.py                # PNG writers, config, session management
```

This can be done incrementally: move one module at a time, keep backward compat via imports in the main file.

---

## 4. Spellmaker Compatibility

The refactoring directly enables Spellmaker by providing:

1. **Architecture Registry** — Spellmaker can query `ARCHITECTURES["flux2klein"].default_steps` to auto-configure workflows
2. **NodeFactory** — Spellmaker can construct workflows programmatically without knowing raw node APIs
3. **Composite Builders** — Spellmaker can call `load_model_stack()` + `encode_prompts()` + `sample_standard()` to build custom pipelines
4. **Preset Data** — `MODEL_PRESETS`, `SCENE_PRESETS`, `LORA_METADATA` become importable data that Spellmaker can reference

### Spellmaker API Surface

After refactoring, Spellmaker needs only these imports:

```python
from _architectures import ARCHITECTURES, ArchConfig
from _nodes import NodeFactory
from _workflows import load_model_stack, inject_lora_chain, encode_prompts
from _presets import MODEL_PRESETS, SCENE_PRESETS, LORA_METADATA
from _transport import run_comfyui_workflow, upload_image, download_image
```

---

## 5. Darktable Parity

The Darktable plugin has the same patterns in Lua:
- 19 `build_*_json()` functions constructing JSON strings via `string.format`
- 21 `process_*()` functions with identical orchestration patterns
- Same 73 node types hardcoded

**Recommendation:** Refactor GIMP first (Python, easier to test), then port the pattern to Darktable. The Lua version would use tables instead of classes but the same layered structure:

```lua
local arch_registry = { sd15 = {...}, sdxl = {...}, flux1dev = {...} }
local function node(class_type, inputs) ... end
local function load_model_stack(nf, arch, preset) ... end
```

---

## 6. Risk Mitigation

| Risk | Mitigation |
|------|------------|
| Regression in workflows | Golden test: save current `_build_*()` outputs as JSON fixtures, verify new builders produce identical output |
| NSFW addon injection breaks | Injection points stay in same logical locations; NSFW blocks inject into preset data structures, not workflow code |
| GIMP plugin loader incompatibility | Test single-file vs multi-file import on GIMP 3.0.0 before committing to Phase 5 |
| Darktable Lua porting effort | Lua refactoring is optional and independent; can lag behind GIMP |

---

## 7. Priority Order

```
Phase 1: Node Factory             ← Do this first. Biggest protection against API changes.
Phase 2: Architecture Registry    ← Do this second. Enables Spellmaker and simplifies everything.
Phase 3: Composite Builders       ← Do this third. Cleans up the most code.
Phase 4: Dialog Consolidation     ← Nice-to-have. UI code changes less often.
Phase 5: File Splitting           ← Nice-to-have. Do when the file gets unwieldy to navigate.
```

Phases 1-3 are the core refactoring. They reduce the effective complexity from "91 node types x 39 workflows" to "91 factory methods + 7 arch configs + ~10 composite helpers + 39 thin composers."

---

## 8. Metrics (Expected Outcomes)

| Metric | Before | After (Phase 1-3) |
|--------|--------|-------------------|
| Lines to fix a node API change | 10-50+ (grep & replace) | 1 (factory method) |
| Lines to add a new architecture | ~200 (scattered across 10+ dicts) | ~30 (one ArchConfig entry) |
| Average workflow builder size | ~100 lines | ~25 lines |
| Total file size | 22,459 lines | ~18,000 lines (est. -20%) |
| Duplication ratio | ~800 lines duplicated | ~0 |
| Time to understand a workflow | Read 100+ lines of raw node dict | Read 25 lines of named function calls |
