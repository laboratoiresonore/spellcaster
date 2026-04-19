# Dependencies

Spellcaster itself is a GIMP plugin + Python server. The AI capabilities come from [ComfyUI](https://github.com/comfyanonymous/ComfyUI) and a set of ComfyUI custom node packs. GitHub's dependency graph only tracks PyPI packages, so this document exists to list the ComfyUI-side dependencies explicitly.

**This file is generated from [`installer/manifest.json`](installer/manifest.json)**. Do not edit by hand — run `python scripts/generate_dependencies_md.py` after editing the manifest.

## How dependencies are installed

The Spellcaster installer (`spellcaster-installer.exe` or `python installer/install.py`) clones each required node pack into `ComfyUI/custom_nodes/` automatically. If you prefer to install manually, clone each repo from the **Repo** column below into your `custom_nodes` directory and restart ComfyUI.

Total node packs: **24** (20 required, 4 optional).

## Required ComfyUI node packs

These packs must be present for the listed features to work. Missing packs cause a clear error at workflow-build time, not a silent fallback.

| Pack | Repo | Used by | Notes |
|------|------|---------|-------|
| `ComfyUI-Flux2Klein-Enhancer` | [ComfyUI-Flux2Klein-Enhancer](https://github.com/capitan01R/ComfyUI-Flux2Klein-Enhancer) | Flux 2 Klein — recommended engine (fastest, best quality) | Optional quality upgrade for Klein pipelines — reference strength control, text/ref balance, and color drift correction. Auto-detected by Spellcaster; if not installed, standard pipelines run unchanged. |
| `ComfyUI-GGUF` | [ComfyUI-GGUF](https://github.com/city96/ComfyUI-GGUF) | Video Generation (Wan 2.2, 2-5 second clips) |  |
| `ComfyUI-IC-Light` | [ComfyUI-IC-Light](https://github.com/kijai/ComfyUI-IC-Light-Wrapper) | Relighting (change lighting direction, 10 presets) |  |
| `ComfyUI-Impact-Pack` | [ComfyUI-Impact-Pack](https://github.com/ltdrdata/ComfyUI-Impact-Pack) | Flux 2 Klein — recommended engine (fastest, best quality) | Face/hand detailer — auto-detect and re-generate faces at high detail. Used by build_klein_face_detail. |
| `ComfyUI-LaMa` | [ComfyUI-LaMa](https://github.com/mlinmg/ComfyUI-LaMA-Preprocessor) | Object Removal & AI Eraser (LaMa, no model needed) |  |
| `ComfyUI-QwenVL-Mod` | [ComfyUI-QwenVL-Mod](https://github.com/1038lab/ComfyUI-QwenVL) | AI Prompt Enhancement (local LLM, auto-rewrites prompts) | Local GGUF LLM for prompt enhancement. Alt: install via ComfyUI Manager, search QwenVL-Mod. |
| `ComfyUI-REMBG` | [ComfyUI-REMBG](https://github.com/Jcd1230/rembg-comfyui-node) | Remove Background (3 engines: rembg, BiRefNet, BiRefNet Portrait) | The isnet-general-use model is downloaded automatically on first use |
| `ComfyUI-RIFE` | [ComfyUI-RIFE](https://github.com/dajes/frame-interpolation-pytorch) | Video Generation (Wan 2.2, 2-5 second clips) |  |
| `ComfyUI-RTX-Remix` | [ComfyUI-RTX-Remix](https://github.com/NVlabs/ComfyUI-RTXVideoSuperResolution) | Video Generation (Wan 2.2, 2-5 second clips) | Install via ComfyUI Manager. Search: Nvidia RTX Nodes. Requires RTX GPU with Tensor cores. |
| `ComfyUI-SUPIR` | [ComfyUI-SUPIR](https://github.com/kijai/ComfyUI-SUPIR) | SUPIR AI Restoration (heavy, 10GB+ VRAM, 5GB download) |  |
| `ComfyUI-Spellcaster` | [ComfyUI-Spellcaster](https://github.com/laboratoiresonore/ComfyUI-Spellcaster) | Image Generation (SDXL/SD1.5/Flux), Text to Image (uses same models as above), Inpaint & Fix (44 expert presets) | Spellcaster nodes — auto-arch model loading, LLM prompt enhance, and smart sampling. Auto-updates via git pull. |
| `ComfyUI-VideoHelperSuite` | [ComfyUI-VideoHelperSuite](https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite) | Video Generation (Wan 2.2, 2-5 second clips) |  |
| `ComfyUI-WD14-Tagger` | [ComfyUI-WD14-Tagger](https://github.com/pythongosssss/ComfyUI-WD14-Tagger) | Image Generation (SDXL/SD1.5/Flux) |  |
| `ComfyUI-essentials` | [ComfyUI-essentials](https://github.com/cubiq/ComfyUI_essentials) | Color Grading (cinematic LUTs, no download needed) |  |
| `ComfyUI_GetImageSize` | [ComfyUI_GetImageSize](https://github.com/cubiq/ComfyUI_essentials) | Image Generation (SDXL/SD1.5/Flux), Inpaint & Fix (44 expert presets), Face Swap — recommended (ReActor), Face Swap — alternative (MTB, lighter) | GetImageSize+ is provided by ComfyUI_essentials. Install that instead. |
| `ComfyUI_IPAdapter_plus` | [ComfyUI_IPAdapter_plus](https://github.com/cubiq/ComfyUI_IPAdapter_plus) | Face Identity — alternative (IPAdapter FaceID) |  |
| `PuLID_ComfyUI` | [PuLID_ComfyUI](https://github.com/cubiq/PuLID_ComfyUI) | Face Identity — premium (PuLID + Flux, 30GB download) |  |
| `comfyui-controlnet-aux` | [comfyui-controlnet-aux](https://github.com/Fannovel16/comfyui_controlnet_aux) | ControlNet (6 structure guides — needed for SDXL, not for Klein), Colorize B&W (DDColor instant or ControlNet guided) |  |
| `comfyui-mtb` | [comfyui-mtb](https://github.com/melMass/comfyui-mtb) | Face Swap — alternative (MTB, lighter) | Install via ComfyUI Manager (repo melMass/comfy-mtb may be archived). Search: comfy-mtb |
| `comfyui-reactor-node` | [comfyui-reactor-node](https://github.com/Gourieff/comfyui-reactor-node) | Face Swap — recommended (ReActor) |  |

## Optional ComfyUI node packs

These packs unlock higher-quality or alternative pipelines when present. Spellcaster auto-detects them and substitutes them into workflows via the preflight validator.

| Pack | Repo | Notes |
|------|------|-------|
| `ComfyUI-DDColor` | [ComfyUI-DDColor](https://github.com/kijai/ComfyUI-DDColor) | DDColor instant B&W colorization — fast, no diffusion model needed. Optional upgrade for Colorize tool. |
| `ComfyUI-DepthAnythingV3` | [ComfyUI-DepthAnythingV3](https://github.com/PozzettiAndrea/ComfyUI-DepthAnythingV3) | DepthAnythingV3 — 35% better depth estimation than V2. Optional upgrade for ControlNet depth. |
| `ComfyUI-NormalCrafter` | [ComfyUI-NormalCrafter](https://github.com/AIWarper/ComfyUI-NormalCrafterWrapper) | NormalCrafter wrapper. Install via ComfyUI Manager if this repo is unavailable. |
| `ComfyUI-RMBG` | [ComfyUI-RMBG](https://github.com/1038lab/ComfyUI-RMBG) | BiRefNet/RMBG-2.0 background removal — better hair and fine detail than standard rembg. |

## Python dependencies

The GIMP plugin runs inside GIMP's bundled Python 3.12 and uses only the Python standard library — there is no `requirements.txt` to install. The Wizard Guild server (`tavern/`) and the installer (`installer/`) likewise depend only on the standard library for their core paths. Any heavier Python packages (torch, transformers, accelerate, insightface, etc.) are pulled in by ComfyUI and its custom nodes, not by Spellcaster directly.

## Related repositories

Spellcaster is split across four repos. Only two are public:

- [`laboratoiresonore/spellcaster`](https://github.com/laboratoiresonore/spellcaster) — this repo (main app, installer, GIMP plugin, Guild server)
- [`laboratoiresonore/ComfyUI-Spellcaster`](https://github.com/laboratoiresonore/ComfyUI-Spellcaster) — the 4 custom Spellcaster ComfyUI nodes (auto-arch loader, prompt enhancer, sampler, output)

