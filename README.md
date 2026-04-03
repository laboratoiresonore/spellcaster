<p align="center">
  <img src="assets/wizard_banner.gif" alt="Spellcaster" width="600" />
</p>

<h1 align="center">Spellcaster</h1>

<p align="center">
  <strong>From zero to generative-AI mastery in one click.</strong><br/>
  Every model, every preset, every parameter — expertly tuned by AI professionals<br/>
  so you get studio-quality results from your very first generation.
</p>

<p align="center">
  <a href="https://github.com/laboratoiresonore/spellcaster/releases"><img alt="Releases" src="https://img.shields.io/github/v/release/laboratoiresonore/spellcaster?color=7c3aed&label=latest&style=flat-square"/></a>
  <a href="LICENSE"><img alt="License" src="https://img.shields.io/badge/license-GPL--2.0-7c3aed?style=flat-square"/></a>
  <img alt="Platform" src="https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-7c3aed?style=flat-square"/>
  <img alt="ComfyUI" src="https://img.shields.io/badge/requires-ComfyUI%20v0.2%2B-5b21b6?style=flat-square"/>
  <img alt="GIMP" src="https://img.shields.io/badge/GIMP-3.0-5b21b6?style=flat-square"/>
  <img alt="Darktable" src="https://img.shields.io/badge/Darktable-4.x-5b21b6?style=flat-square"/>
</p>

<p align="center">
  <a href="#-quick-start">Quick Start</a> &bull;
  <a href="#-why-spellcaster">Why Spellcaster</a> &bull;
  <a href="#-features">Features</a> &bull;
  <a href="#-supported-models">Models</a> &bull;
  <a href="#-architecture">Architecture</a> &bull;
  <a href="#-contributing">Contributing</a>
</p>

---

## Why Spellcaster?

**You don't need to be an AI expert to get expert-level results.**

Other tools hand you a blank canvas of nodes, samplers, and CFG scales and say "good luck." Spellcaster does the opposite: every single model ships with **hand-tuned presets** — the exact steps, CFG, sampler, scheduler, denoise, prompt structure, and negative prompt that professionals use after hundreds of hours of experimentation. You inherit all of that expertise the moment you install.

It works like any other filter in your editing software. Select an area, pick a preset, click a button. Behind the scenes, [ComfyUI](https://github.com/comfyanonymous/ComfyUI) handles the heavy lifting — but you never have to touch it directly.

### What Makes It Different

- **Instant mastery.** 25 scene presets, 44 inpaint refinements, 26 video motion presets — all expertly calibrated. Pick "Portrait Headshot" and the system auto-fills the optimal prompt, sampler, steps, CFG, LoRAs, and resolution. The output is indistinguishable from what an expert would produce after 30 minutes of manual tuning.
- **Stays inside your editor.** Paint a selection in [GIMP](https://www.gimp.org/), hit "Inpaint", get the result as a new layer. Process a batch in [Darktable](https://www.darktable.org/) and results land straight back in your library. No export/import dance.
- **Works like Photoshop's AI tools — but free and open-source.** Generative fill, style transfer, relighting, restoration, upscaling, and video generation — all running locally on your own GPU. No subscriptions, no cloud uploads, your images stay private.
- **VRAM-aware installer.** Detects your GPU, auto-selects only features your hardware can run, downloads the right model variants (Q4 GGUF for 8 GB, fp8 for 12 GB, full precision for 24 GB+), and configures everything. No GPU? It tells you upfront.
- **24 features, 100+ presets, 6 model families.** From photorealistic portraits to anime, from photo restoration to video generation — pick a style and go.
- **Save & recall your settings.** Save your favorite prompt/settings combos as named presets. Dialogs remember your last-used settings within a session.
- **Queue multiple runs.** Every dialog has a "Runs" input (1-99) — generate 10 variations with one click, each with a fresh seed. Requests are serialized so ComfyUI never gets overloaded.
- **Self-updating plugins.** Both plugins check GitHub on launch and silently update themselves — new features appear automatically, no manual downloads needed.

---

## The Expert-Tuned Difference

> *"I spent weeks learning about samplers, schedulers, and CFG values. With Spellcaster, someone already did that work — better than I ever could."*

Every model preset in Spellcaster is the product of extensive testing across hundreds of generations. Here's what you get out of the box that would take weeks to figure out on your own:

| What Spellcaster handles for you | What you'd have to learn without it |
|---|---|
| Optimal sampler + scheduler per model | Trial and error across 20+ sampler/scheduler combos |
| Correct CFG range per architecture | SD1.5 wants 7.0, SDXL wants 5-6, ZIT wants 1-3, Flux wants 3.5 |
| Architecture-specific prompt structure | SD uses quality tags, SDXL uses detailed descriptions, Flux uses natural language |
| Negative prompt engineering | 50+ negative prompt patterns tuned per model family |
| Resolution constraints | SD1.5=512px, SDXL=1024px, Flux=mod-16, Wan=mod-16 832x480 |
| LoRA selection + strength per task | Which LoRA to use, at what strength, for which model |
| Inpaint denoise by body part | Hands need 0.78, eyes need 0.65, skin texture needs 0.45 |
| Video motion preset tuning | Camera speed, subject movement, loop timing — 26 motion presets |

**The result: your first generation looks like your hundredth.** There is no learning curve.

---

## Sample Output

<p align="center"><em>Every image below was generated using Spellcaster's built-in presets — zero manual configuration, zero prompt engineering.</em></p>

### Generation

<p align="center">
  <img src="assets/showcase_fantasy.png" alt="Fantasy Landscape — IlustReal v5" width="80%"/><br/>
  <sub><strong>Fantasy Landscape</strong> &mdash; IlustReal v5 &bull; Illustrious architecture &bull; 25 scene presets across 6 model families</sub>
</p>

<details>
<summary><strong>More generation examples (7 models)</strong></summary>
<table>
  <tr>
    <td align="center" width="25%"><img src="assets/showcase_portrait.png" alt="Photorealistic Portrait" width="100%"/><br/><sub><strong>Photorealistic Portrait</strong><br/>Juggernaut XL v9 &bull; SDXL</sub></td>
    <td align="center" width="25%"><img src="assets/showcase_anime.png" alt="Anime Illustration" width="100%"/><br/><sub><strong>Anime Illustration</strong><br/>NoobAI-XL v1.1 &bull; SDXL</sub></td>
    <td align="center" width="25%"><img src="assets/showcase_disney.png" alt="Disney/Pixar 3D" width="100%"/><br/><sub><strong>Disney / Pixar 3D</strong><br/>Modern Disney XL v3 &bull; SDXL</sub></td>
    <td align="center" width="25%"><img src="assets/showcase_klein_flux2.png" alt="Klein Flux 2" width="100%"/><br/><sub><strong>Klein Flux 2 9B</strong><br/>Next-gen detail &bull; Flux 2</sub></td>
  </tr>
  <tr>
    <td align="center" width="25%"><img src="assets/showcase_zit_photo.png" alt="ZIT Turbo" width="100%"/><br/><sub><strong>Turbo Photo (6-step)</strong><br/>ZIT Zpop v3 &bull; instant</sub></td>
    <td align="center" width="25%"><img src="assets/showcase_zit_cinematic.png" alt="ZIT Cinematic" width="100%"/><br/><sub><strong>Cinematic Still</strong><br/>ZIT &bull; 8 steps</sub></td>
    <td align="center" width="25%"><img src="assets/showcase_sd15_realistic.png" alt="SD1.5" width="100%"/><br/><sub><strong>SD1.5 Realistic</strong><br/>Juggernaut Reborn &bull; 6 GB</sub></td>
    <td align="center" width="25%"><img src="assets/showcase_painterly.png" alt="Painterly Art" width="100%"/><br/><sub><strong>Painterly Art</strong><br/>Sloppy Messy Mix &bull; Illustrious</sub></td>
  </tr>
</table>
</details>

### Inpainting

<p align="center">
  <img src="assets/showcase_inpaint_eyes.png" alt="Fix Eyes / Iris Detail" width="80%"/><br/>
  <sub><strong>Fix Eyes / Iris Detail</strong> &mdash; denoise 0.65, Eyes HD LoRA &bull; 44 expert-tuned refinement presets</sub>
</p>

<details>
<summary><strong>More inpainting examples (4 presets)</strong></summary>
<table>
  <tr>
    <td align="center" width="25%"><img src="assets/showcase_inpaint_hands.png" alt="Fix Hands" width="100%"/><br/><sub><strong>Fix Hands</strong><br/>denoise 0.78, HandFineTuning LoRA</sub></td>
    <td align="center" width="25%"><img src="assets/showcase_inpaint_face.png" alt="Refine Face" width="100%"/><br/><sub><strong>Refine Face</strong><br/>denoise 0.62, RealSkin LoRA</sub></td>
    <td align="center" width="25%"><img src="assets/showcase_inpaint_chrome.png" alt="Chrome Skin" width="100%"/><br/><sub><strong>Chrome / Metallic</strong><br/>denoise 0.75, creative effect</sub></td>
    <td align="center" width="25%"><img src="assets/showcase_inpaint_ghibli.png" alt="Ghibli Style" width="100%"/><br/><sub><strong>Studio Ghibli</strong><br/>denoise 0.72, style transfer</sub></td>
  </tr>
</table>
</details>

### Restoration & Enhancement

<p align="center">
  <img src="assets/showcase_rembg.png" alt="Remove Background" width="80%"/><br/>
  <sub><strong>Remove Background</strong> &mdash; One-click AI background removal to transparent PNG</sub>
</p>

<details>
<summary><strong>More restoration examples (7 tools)</strong></summary>
<table>
  <tr>
    <td align="center" width="25%"><img src="assets/showcase_upscale_before_after.png" alt="AI Upscale 4x" width="100%"/><br/><sub><strong>AI Upscale 4x</strong><br/>UltraSharp &bull; before/after</sub></td>
    <td align="center" width="25%"><img src="assets/showcase_face_restore.png" alt="Face Restore" width="100%"/><br/><sub><strong>Face Restore</strong><br/>CodeFormer v0.1.0</sub></td>
    <td align="center" width="25%"><img src="assets/showcase_colorize.png" alt="Colorize B&W" width="100%"/><br/><sub><strong>Colorize B&W</strong><br/>ControlNet lineart</sub></td>
    <td align="center" width="25%"><img src="assets/showcase_lama_remove.png" alt="Object Removal" width="100%"/><br/><sub><strong>Object Removal</strong><br/>LaMa &bull; paint & erase</sub></td>
  </tr>
  <tr>
    <td align="center" width="25%"><img src="assets/showcase_supir.png" alt="SUPIR" width="100%"/><br/><sub><strong>SUPIR Restoration</strong><br/>State-of-the-art AI repair</sub></td>
    <td align="center" width="25%"><img src="assets/showcase_detail_hallucinate.png" alt="Detail Hallucination" width="100%"/><br/><sub><strong>Detail Hallucination</strong><br/>Upscale + AI detail</sub></td>
    <td align="center" width="25%"><img src="assets/showcase_seedv2r.png" alt="SeedV2R" width="100%"/><br/><sub><strong>SeedV2R Upscale</strong><br/>5 levels &bull; 1x-4x</sub></td>
    <td align="center" width="25%"><img src="assets/showcase_photo_restore.png" alt="Photo Restore" width="100%"/><br/><sub><strong>Photo Restore</strong><br/>4x UltraSharp &bull; full pipeline</sub></td>
  </tr>
</table>
</details>

### Style & Relighting

<p align="center">
  <img src="assets/showcase_iclight_neon.png" alt="IC-Light Neon Cyberpunk" width="80%"/><br/>
  <sub><strong>IC-Light Neon</strong> &mdash; Cyberpunk relighting &bull; 10 lighting presets + style transfer + LUT color grading</sub>
</p>

<details>
<summary><strong>More style examples (3 tools)</strong></summary>
<table>
  <tr>
    <td align="center" width="33%"><img src="assets/showcase_style_transfer.png" alt="Style Transfer" width="100%"/><br/><sub><strong>Style Transfer</strong><br/>IPAdapter &bull; any reference style</sub></td>
    <td align="center" width="33%"><img src="assets/showcase_lut_kodak.png" alt="LUT Color Grading" width="100%"/><br/><sub><strong>Color Grading (LUT)</strong><br/>Kodak film stock &bull; 5 LUTs</sub></td>
    <td align="center" width="33%"><img src="assets/showcase_iclight_golden.png" alt="IC-Light Golden Hour" width="100%"/><br/><sub><strong>IC-Light Golden Hour</strong><br/>Natural warm lighting</sub></td>
  </tr>
</table>
</details>

### Video — Wan 2.2 Image-to-Video

<table>
  <tr>
    <td align="center" width="25%"><img src="assets/showcase_wan_breathing.gif" alt="Living Portrait" width="100%"/><br/><sub><strong>Living Portrait</strong><br/>Breathing &bull; hair sway</sub></td>
    <td align="center" width="25%"><img src="assets/showcase_wan_zoom.gif" alt="Camera Zoom" width="100%"/><br/><sub><strong>Camera Slow Zoom</strong><br/>Cinematic push-in</sub></td>
    <td align="center" width="25%"><img src="assets/showcase_wan_water.gif" alt="Flowing Water" width="100%"/><br/><sub><strong>Flowing Water</strong><br/>Nature motion</sub></td>
    <td align="center" width="25%"><img src="assets/showcase_wan_turntable.gif" alt="Product Turntable" width="100%"/><br/><sub><strong>360 Turntable</strong><br/>Product spin</sub></td>
  </tr>
</table>

### ControlNet — Structure-Guided Generation

<details>
<summary><strong>5 ControlNet modes</strong></summary>
<table>
  <tr>
    <td align="center" width="20%"><img src="assets/showcase_cn_canny.png" alt="Canny Edge" width="100%"/><br/><sub><strong>Canny Edge</strong></sub></td>
    <td align="center" width="20%"><img src="assets/showcase_cn_depth.png" alt="Depth Map" width="100%"/><br/><sub><strong>Depth Map</strong></sub></td>
    <td align="center" width="20%"><img src="assets/showcase_cn_pose.png" alt="OpenPose" width="100%"/><br/><sub><strong>OpenPose</strong></sub></td>
    <td align="center" width="20%"><img src="assets/showcase_cn_lineart.png" alt="Lineart" width="100%"/><br/><sub><strong>Lineart</strong></sub></td>
    <td align="center" width="20%"><img src="assets/showcase_cn_tile.png" alt="Tile Upscale" width="100%"/><br/><sub><strong>Tile Upscale</strong></sub></td>
  </tr>
</table>
</details>

---

## Who Is This For?

| You are... | Spellcaster gives you... |
|---|---|
| **A complete beginner** who's never touched AI | Instant professional-grade results with zero learning curve — every preset is expertly tuned |
| **A photographer** who wants AI retouching without leaving Darktable | One-click skin smoothing, face restore, color grading, upscaling, and style transfer on your RAW workflow |
| **A digital retoucher** tired of Photoshop's subscription fees | Free, open-source generative fill, inpainting, object removal, relighting, and restoration — running locally |
| **A Photoshop user** curious about GIMP but missing AI features | All the AI tools you're used to (and more), right in GIMP's Filters menu |
| **An illustrator** who wants to explore AI-assisted art | 25 scene presets from photorealism to anime to Disney 3D — pick one and paint |
| **Someone with old/damaged photos** | One-click photo restoration: upscale + face restore + sharpen + B&W colorization |
| **A video creator** who needs image-to-video generation | Wan 2.2 video generation with 26 motion presets, RTX upscale, and RIFE interpolation |
| **A privacy-conscious creative** | Everything runs locally on your GPU — no cloud, no subscriptions, your images never leave your machine |

**You don't need to know what a "checkpoint", "sampler", "LoRA", or "CFG scale" is.** Spellcaster handles all of that behind the scenes with settings that professionals have spent hundreds of hours refining. If you can use a Photoshop filter, you can use Spellcaster — and get results that rival or exceed what most experts produce.

---

## Quick Start

> **Prerequisite:** A running [ComfyUI](https://github.com/comfyanonymous/ComfyUI) backend (v0.2.0+).

<p align="center">
  <a href="https://github.com/laboratoiresonore/spellcaster/releases/latest/download/spellcaster-installer.exe">
    <img src="https://img.shields.io/badge/Windows-spellcaster--installer.exe-7c3aed?style=for-the-badge&logo=windows&logoColor=white" alt="Download for Windows"/>
  </a>
  &nbsp;
  <a href="https://github.com/laboratoiresonore/spellcaster/releases/latest/download/spellcaster-installer-macos.zip">
    <img src="https://img.shields.io/badge/macOS-Spellcaster%20Installer.app-7c3aed?style=for-the-badge&logo=apple&logoColor=white" alt="Download for macOS"/>
  </a>
  &nbsp;
  <a href="https://github.com/laboratoiresonore/spellcaster/releases/latest/download/spellcaster-installer-linux">
    <img src="https://img.shields.io/badge/Linux-spellcaster--installer-7c3aed?style=for-the-badge&logo=linux&logoColor=white" alt="Download for Linux"/>
  </a>
</p>

### Standalone Installer (Recommended)

*No Python, no terminal, no dependencies. Just run it.*

1. **Download** the installer for your OS above (or from the [Releases page](https://github.com/laboratoiresonore/spellcaster/releases)).
2. **Run it.** The wizard auto-detects your GPU and VRAM, pre-selects only features your hardware can handle, and downloads the right model variants. Just hit "Use recommended selections" and go.
3. **Launch GIMP or Darktable.** Open `Filters > Spellcaster` in GIMP, or find the Spellcaster panel in Darktable's lighttable module.
4. **Pick any preset and generate.** Every preset is expertly tuned — your first result will look professional.

> **No `git` required** — the installer falls back to ZIP downloads automatically.
>
> **API keys (optional):** A [CivitAI API token](https://civitai.com/user/account) and/or [HuggingFace access token](https://huggingface.co/settings/tokens) unlock authenticated downloads for gated models. Keys are used only during install and **never stored**.
>
> **Plugin not showing up?** Download the [**Manual Update & Repair tool**](https://github.com/laboratoiresonore/spellcaster/releases/latest/download/spellcaster-manual-update.exe) — it auto-detects broken installations, fixes misnamed folders, and updates to the latest version.

---

### Developer Install (Git + Python)

```bash
git clone https://github.com/laboratoiresonore/spellcaster
cd spellcaster
python install.py          # Interactive GUI wizard
python install.py --cli    # Force terminal mode
```

<details>
<summary><strong>CLI flags for scripted & headless installs</strong></summary>

```bash
# Accept all defaults non-interactively
python install.py --yes

# Authenticate downloads
python install.py --civitai-key YOUR_TOKEN --hf-token YOUR_TOKEN

# Remote ComfyUI on another machine
python install.py --server-url http://192.168.1.50:8188

# Cherry-pick features (25 available)
python install.py --features img2img,inpaint,upscale,face_restore,controlnet,ltx_i2v

# Explicit paths (skip auto-detection)
python install.py --comfyui ~/ComfyUI --gimp ~/.config/GIMP/3.0/plug-ins

# Plugins + nodes only, no model downloads
python install.py --skip-models

# Plugins + models only, no custom nodes
python install.py --skip-nodes

# Preview without making any changes
python install.py --dry-run
```

</details>

---

### ComfyUI Server Configuration

| Setup | URL |
|---|---|
| Same machine (default) | `http://127.0.0.1:8188` |
| Another PC on your LAN | `http://192.168.x.x:8188` |
| Custom port | `http://127.0.0.1:YOUR_PORT` |

The installer patches the plugins with your chosen URL. You can also change it at any time from inside the plugin dialogs.

---

## Features

**24 features, 100+ presets, 6 model families** — generation, inpainting, restoration, style transfer, video, and more.

<details>
<summary><strong>Full feature list</strong></summary>

#### Generation

| Feature | GIMP | DT | Description |
|---|:---:|:---:|---|
| **Image-to-Image** | Yes | Yes | SD 1.5, SDXL, ZIT (6-step turbo), Illustrious, Flux 1 Dev, Klein Flux 2, Flux Kontext |
| **Text-to-Image** | Yes | -- | 25 scene presets with architecture-specific prompt optimization |
| **Inpainting** | Yes | Yes | 44 refinement presets — denoise, LoRA, prompt per body part or effect |
| **Outpaint / Extend** | Yes | Yes | AI canvas extension in any direction |
| **Batch Variations** | Yes | Yes | 2-8 variations from one prompt in a single batch |
| **ControlNet** | Yes | Yes | Canny, Depth, Lineart, OpenPose, Scribble, Tile |

#### Restoration & Enhancement

| Feature | GIMP | DT | Description |
|---|:---:|:---:|---|
| **AI Upscale 4x/8x** | Yes | Yes | 6 models: UltraSharp, RealESRGAN, Remacri, NMKD, Anime, 8x Faces |
| **Face Restore** | Yes | Yes | 6 models: CodeFormer, GFPGAN v1.3/v1.4, GPEN 512/1024, RestoreFormer++ |
| **Photo Restoration** | Yes | Yes | Upscale + Face Restore + Sharpen in one click |
| **Detail Hallucination** | Yes | Yes | Upscale + img2img at low denoise — 4 intensity levels |
| **SUPIR Restoration** | Yes | Yes | State-of-the-art AI restoration |
| **SeedV2R Upscale** | Yes | Yes | 5 hallucination levels (Faithful to Extreme), 1x-4x scale |
| **Object Removal (LaMa)** | Yes | Yes | Paint over anything, LaMa erases it — no prompt needed |
| **Colorize B&W** | Yes | Yes | ControlNet lineart auto-colorization |

#### Style, Face & Video

| Feature | GIMP | DT | Description |
|---|:---:|:---:|---|
| **Style Transfer** | Yes | Yes | IPAdapter — apply any reference image's style |
| **Color Grading (LUT)** | Yes | Yes | 5 film LUTs + import your own .cube/.3dl |
| **IC-Light Relighting** | Yes | Yes | 10 lighting presets (golden hour, neon, directional, etc.) |
| **Face Swap (ReActor)** | Yes | Yes | CodeFormer/GFPGAN restore + save/overwrite face models |
| **Face Swap (MTB)** | Yes | Yes | Lightweight alternative engine |
| **FaceID** | Yes | -- | IPAdapter identity preservation |
| **PuLID Flux** | Yes | -- | Advanced identity on Flux 1 Dev |
| **Wan 2.2 I2V** | Yes | Yes | 26 motion presets, RTX upscale, RIFE interpolation, turbo LoRAs |
| **Remove Background** | Yes | Yes | One-click transparent PNG |
| **Invisible Watermark** | Yes | Yes | LSB steganography — embed/read encrypted metadata |

#### UX & Workflow

| Feature | Description |
|---|---|
| **Runs (1-99)** | Queue multiple generations — each with a fresh seed |
| **User Presets** | Save/load/delete prompt+settings combos across sessions |
| **Session Recall** | Dialogs pre-fill with last-used settings |
| **Self-Updating Plugins** | GitHub Tree API auto-discovery on every launch |
| **VRAM-Aware Installer** | Auto-selects features + model variants for your GPU |
| **LUT Import** | Import .cube/.3dl libraries from Davinci Resolve |
| **Spellcaster Theme** | Optional AI-generated splash art for GIMP/Darktable |

</details>

<details>
<summary><strong>Scene presets (25) &bull; Inpainting presets (44) &bull; Video presets (26)</strong></summary>

#### Scene Presets (25)

| Category | Presets |
|---|---|
| **Photo / Realistic** | Portrait Headshot, Full Body, Product Photo, Landscape, Food, Architecture, Fashion, Fantasy Art, Cinematic, Street Photography, Macro |
| **Anime** | Character Portrait, Action Scene, Slice of Life, Fantasy/Isekai, Chibi/Cute, Wallpaper/Key Visual |
| **Cartoon / 3D** | Character Design, Scene/Environment, Cute Animal/Mascot |
| **Flux Kontext** | Change Outfit, Change Background, Age/Appearance Edit, Add Object |

#### Inpainting Presets (44)

| Category | Count | Examples |
|---|---|---|
| **Body Parts** | 10 | Hands, eyes, face, teeth, skin, feet, full body, ears, nose, neck |
| **Style Effects** | 10 | Gothic, epic photo, raw camera, Ghibli, fantasy, realism, amateur |
| **Advanced Styles** | 10 | WAM, poly 3D, dramatic lighting, robot, glitch, aliens, metallic gold |
| **Illustrious-Pony** | 4 | Chiaroscuro, cinematic, hyperdetailed realism, detail slider |
| **Klein** | 4+5 | Sharp details, realism, anatomy slider, glow, 3D Hi-Poly, color tone |

#### Video Presets (26 Wan motions)

| Category | Presets |
|---|---|
| **Living Portrait** | Breathing, hair sway, smile shift |
| **Camera** | Slow zoom, orbit, pan, tilt |
| **Nature** | Water, clouds, trees, candle |
| **Atmosphere** | Rain, snow, particles, fog |
| **Action** | Walking, head turn, dancing |
| **Cinemagraph** | Ocean loop, city lights loop |
| **Product** | 360 turntable, hero sparkle |

</details>

---

<details>
<summary><h2>Supported Models</h2></summary>

The installer detects your GPU VRAM and recommends the right model tier. Models are downloaded automatically during installation.

### VRAM Tiers

| Tier | VRAM | What gets installed |
|---|---|---|
| **Low** | < 8 GB | Q4/Q5 GGUF quantized models — lightweight but capable |
| **Medium** | 8 -- 12 GB | fp8 or Q8 models — great quality/performance balance |
| **High** | 12 -- 20 GB | fp8 or standard precision — full feature access |
| **Ultra** | 20+ GB | Full bf16 precision — maximum quality, all features |

### Checkpoints

<details>
<summary><strong>SD 1.5</strong> (3 models -- 6 GB VRAM)</summary>

| Model | Source | Notes |
|---|---|---|
| Juggernaut Reborn | [CivitAI](https://civitai.com/models/46422) | Versatile realistic |
| Realistic Vision v5.1 | [CivitAI](https://civitai.com/models/4201) | Photography focus |
| SD 1.5 Base | [HuggingFace](https://huggingface.co/stable-diffusion-v1-5/stable-diffusion-v1-5) | Official base model |

</details>

<details>
<summary><strong>SDXL Realistic</strong> (7 models -- 8 GB VRAM)</summary>

| Model | Source | Notes |
|---|---|---|
| Juggernaut XL v9 | [CivitAI](https://civitai.com/models/133005) | Recommended starter |
| Juggernaut XL Ragnarok | [CivitAI](https://civitai.com/models/133005) | Latest Juggernaut |
| JibMix Realistic XL v1.8 | [CivitAI](https://civitai.com/models/194768) | Excellent skin rendering |
| ZavyChroma XL v10 | [CivitAI](https://civitai.com/models/119229) | Vivid colors |
| CyberRealistic Pony v1.6 | [CivitAI](https://civitai.com/models/443821) | Pony architecture |
| AlbedoBase XL | [CivitAI](https://civitai.com/models/140737) | Clean versatile base |
| SDXL Base 1.0 | [HuggingFace](https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0) | Official reference |

</details>

<details>
<summary><strong>SDXL Anime & Illustrious</strong> (5 models -- 8 GB VRAM)</summary>

| Model | Source | Notes |
|---|---|---|
| NoobAI-XL v1.1 | [CivitAI](https://civitai.com/models/833294) | Top-tier anime |
| Nova Anime XL v1.70 | [CivitAI](https://civitai.com/models/376130) | Vivid illustration |
| Wai Illustrious SDXL v1.6 | [CivitAI](https://civitai.com/models/827184) | Aesthetic anime |
| IlustReal v5 | [CivitAI](https://civitai.com/models/1046064) | Semi-realistic |
| Sloppy Messy Mix v1 | [CivitAI search](https://civitai.com/search/models?query=sloppy+messy+mix+illustrious) | Painterly artistic |

</details>

<details>
<summary><strong>SDXL Cartoon / 3D</strong> (2 models -- 8 GB VRAM)</summary>

| Model | Source | Notes |
|---|---|---|
| Modern Disney XL v3 | [CivitAI](https://civitai.com/models/138857) | Disney/Pixar style |
| Nova Cartoon XL v6 | [CivitAI](https://civitai.com/models/1570391) | Cartoon illustration |

</details>

<details>
<summary><strong>Z-Image-Turbo (ZIT)</strong> (1 model -- 8 GB VRAM)</summary>

| Model | Source | Notes |
|---|---|---|
| GonzaloMo Zpop v3 AIO | [CivitAI](https://civitai.com/models/gonzalomo-zpop) | Turbo distilled SDXL -- 6-12 steps, near-instant results |

5 presets: Photo (6-step), Portrait (8-step), Cinematic (8-step), Anime (6-step), Quality (12-step). Has its own union ControlNet and 15 dedicated LoRAs (styles, effects, characters).

</details>

<details>
<summary><strong>Flux 1 Dev</strong> (6 models -- 12+ GB VRAM)</summary>

| Model | Source | Notes |
|---|---|---|
| Flux 1 Dev fp8 | [HuggingFace](https://huggingface.co/Comfy-Org/flux1-dev) | Required for PuLID |
| Flux Kontext Dev fp8 | [HuggingFace](https://huggingface.co/black-forest-labs/FLUX.1-Kontext-dev) | Instruction-based editing |
| CLIP-L text encoder | [HuggingFace](https://huggingface.co/comfyanonymous/flux_text_encoders) | Auto-downloaded |
| T5-XXL fp8 encoder | [HuggingFace](https://huggingface.co/comfyanonymous/flux_text_encoders) | Auto-downloaded |
| Flux VAE | [HuggingFace](https://huggingface.co/black-forest-labs/FLUX.1-schnell) | Auto-downloaded |
| PuLID v0.9.1 | [HuggingFace](https://huggingface.co/guozinan/PuLID) | Auto-downloaded |

</details>

<details>
<summary><strong>Flux 2 Klein</strong> (5 models -- 6-20+ GB VRAM)</summary>

| Model | Source | VRAM | Notes |
|---|---|---|---|
| Klein 9B | [HuggingFace](https://huggingface.co/black-forest-labs/FLUX.2-klein-9B) | 20+ GB | Highest quality |
| Klein 4B fp8 | [CivitAI](https://civitai.com/models/2322332) | 8 GB | Mid-range |
| Klein Base 4B fp8 | [CivitAI](https://civitai.com/models/2322332) | 6 GB | Lowest VRAM |
| Qwen 3 8B fp8 encoder | [HuggingFace](https://huggingface.co/Comfy-Org/vae-text-encorder-for-flux-klein-9b) | -- | For Klein 9B |
| Qwen 3 4B encoder | [HuggingFace](https://huggingface.co/Comfy-Org/vae-text-encorder-for-flux-klein-9b) | -- | For Klein 4B |

</details>

<details>
<summary><strong>Wan 2.2 Image-to-Video</strong> (6 models)</summary>

| Model | Source | VRAM | Notes |
|---|---|---|---|
| Wan 2.2 I2V High-Noise Q4 GGUF | [HuggingFace](https://huggingface.co/city96/Wan2.2-I2V-A14B-480p-gguf) | 8 GB | **Recommended** |
| Wan 2.2 I2V Low-Noise Q4 GGUF | [HuggingFace](https://huggingface.co/city96/Wan2.2-I2V-A14B-480p-gguf) | 8 GB | **Recommended** |
| Wan 2.2 I2V High-Noise fp8 | [HuggingFace](https://huggingface.co/Comfy-Org/Wan_2.2_ComfyUI_repackaged) | 16 GB | Higher quality |
| Wan 2.2 I2V Low-Noise fp8 | [HuggingFace](https://huggingface.co/Comfy-Org/Wan_2.2_ComfyUI_repackaged) | 16 GB | Higher quality |
| Wan Enhanced NSFW SVI fp8 High | CivitAI | 16 GB | Enhanced SVI Camera |
| Wan Enhanced NSFW SVI fp8 Low | CivitAI | 16 GB | Enhanced SVI Camera |
| UMT5-XXL Q8 encoder | [HuggingFace](https://huggingface.co/city96/umt5-xxl-encoder-gguf) | -- | Auto-downloaded |
| Wan 2.1 VAE | [HuggingFace](https://huggingface.co/Comfy-Org/Wan_2.2_ComfyUI_repackaged) | -- | Auto-downloaded |

</details>

<details>
<summary><strong>Upscale Models</strong> (6 models)</summary>

| Model | Notes |
|---|---|
| 4x-UltraSharp | Best general-purpose |
| RealESRGAN x4plus | Good for photos |
| 4x Remacri | Great for restoration |
| 4x NMKD Superscale | Sharp results |
| RealESRGAN x4plus Anime | Anime/illustration |
| 8x NMKD Faces | Portrait focus |

</details>

<details>
<summary><strong>ControlNet Models</strong> (8 models)</summary>

| Model | Architecture | Type |
|---|---|---|
| SD1.5 Lineart | SD 1.5 | Edges, drawing, colorization |
| SD1.5 Depth | SD 1.5 | Spatial layout |
| SD1.5 OpenPose | SD 1.5 | Body pose |
| SD1.5 Tile | SD 1.5 | Detail upscale |
| SDXL Canny | SDXL | Edges |
| SDXL OpenPose | SDXL | Body pose |
| SDXL Tile | SDXL | Detail upscale |
| **ZIT Union** | ZIT | All types in one model (canny, depth, pose, lineart, scribble, tile) |

</details>

<details>
<summary><strong>Specialty Models</strong></summary>

| Model | Feature | Notes |
|---|---|---|
| IC-Light SD1.5 | Relighting | Change lighting direction on any photo |
| SUPIR v0Q fp16 | Restoration | State-of-the-art AI restoration (uses SDXL backbone) |
| CodeFormer v0.1.0 | Face Restore | Best face restoration quality |
| GFPGAN v1.3 / v1.4 | Face Restore | Fast face restoration |
| LaMa | Object Removal | Auto-downloaded by node |

</details>

### LoRAs

<details>
<summary><strong>90+ LoRAs across all architectures</strong></summary>

#### SDXL Body & Detail (7)
HandFineTuning XL, Hand v5.5, Eyes High Definition, RealSkin xxXL, Teefs mouth fix, Skin Texture Style v4, Wonderful Details XL

#### SDXL Style (9)
EpiCPhoto XL, Epic New Photo, RawCam 250, Studio Ghibli, FaeTastic Fantasy, EpiCRealness, Amateur Style, SDXL Offset, Dramatic Lighting Slider

#### Flux 1 Dev (3)
Face Detail, Add Detail, Realism

#### Flux 2 Klein (9)
Sharp Details, Realism, Anatomy Slider, Glow Slider, Color Tone, 3D Hi-Poly, Tentacle v2, AnythingToRealCharacters, Upscale Portrait

#### Z-Image-Turbo (15)
Style: 600mm Telephoto, Sony Alpha, Professional Photographer, 35mm Film, Detailed Anime, Illustria, Cinematic Shot
Effect: Chrome Skin, Oiled Skin, Water Droplets, Cyborg, Tentacles, Special FX
Character: 2B Nier Automata. General: Feet Fix

#### Illustrious-Pony (6)
Metallic Gold/Silver, Gothic, Chiaroscuro, Cinematic Photography, Hyperdetailed Realism, Detail Slider

#### Wan 2.2 Accelerators (4)
LightX2V High/Low Noise (~4x speed-up), SVI v2 Pro High/Low Noise

</details>

</details>

---

<details>
<summary><h2>Custom Nodes</h2></summary>

These ComfyUI custom nodes are installed automatically based on your feature selection:

| Node | Purpose | Required By |
|---|---|---|
| [ComfyUI-GGUF](https://github.com/city96/ComfyUI-GGUF) | Load quantized GGUF models for low VRAM | Wan I2V |
| [ComfyUI-VideoHelperSuite](https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite) | Video composition & VHS utilities | Wan I2V |
| [ComfyUI-Frame-Interpolation](https://github.com/Fannovel16/ComfyUI-Frame-Interpolation) | RIFE frame interpolation for smooth video | Wan I2V |
| [comfyui-reactor-node](https://github.com/Gourieff/comfyui-reactor-node) | ReActor face swap + face restore models | Face Swap, Face Restore |
| [comfyui-mtb](https://github.com/melMass/comfyui-mtb) | MTB face swap & utility nodes | Face Swap (MTB) |
| [ComfyUI_IPAdapter_plus](https://github.com/cubiq/ComfyUI_IPAdapter_plus) | IPAdapter for FaceID + style transfer | FaceID, Style Transfer |
| [PuLID_ComfyUI](https://github.com/cubiq/PuLID_ComfyUI) | PuLID identity preservation | PuLID Flux |
| [ComfyUI-KJNodes](https://github.com/kijai/ComfyUI-KJNodes) | Image size utilities (GetImageSize) | img2img, inpaint, face swap |
| [ComfyUI-RTXVideoSuperResolution](https://github.com/NVlabs/ComfyUI-RTXVideoSuperResolution) | NVIDIA RTX video upscaling | Wan I2V (RTX only) |
| [ComfyUI-REMBG](https://github.com/Jcd1230/rembg-comfyui-node) | AI background removal | Remove Background |
| [ComfyUI-LaMa](https://github.com/mlinmg/ComfyUI-LaMA-Preprocessor) | LaMa inpainting for object removal | Object Removal |
| [ComfyUI_essentials](https://github.com/cubiq/ComfyUI_essentials) | LUT color grading (ImageApplyLUT+) | Color Grading |
| [comfyui_controlnet_aux](https://github.com/Fannovel16/comfyui_controlnet_aux) | ControlNet preprocessors (Canny, Depth, Pose, etc.) | ControlNet, Colorize |
| [ComfyUI-IC-Light](https://github.com/kijai/ComfyUI-IC-Light-Wrapper) | IC-Light relighting | IC-Light |
| [ComfyUI-SUPIR](https://github.com/kijai/ComfyUI-SUPIR) | SUPIR AI restoration | SUPIR Restoration |

</details>

---

<details>
<summary><h2>Architecture</h2></summary>

```
spellcaster/
+-- install.py                  # CLI installer — 24-feature interactive wizard with GPU detection
+-- installer_gui.py            # GUI installer — customtkinter 4-step wizard with VRAM-aware preselection
+-- manual_update.py            # Repair & update tool — dynamic file discovery via GitHub Tree API
+-- build_installer.py          # PyInstaller build script (Windows/macOS/Linux)
+-- generate_showcase.py        # ComfyUI batch job runner — README showcase + splash graphics
+-- manifest.json               # Master config — 24 features, 15 custom nodes, all model URLs
|
+-- plugins/
|   +-- gimp/
|   |   +-- comfyui-connector/
|   |   |   +-- comfyui-connector.py   # GIMP 3 plugin (~11,000 lines) — self-updating
|   |   +-- gimp_banner.png            # Spellcaster banner for GIMP plugin UI + system splash
|   +-- darktable/
|       +-- comfyui_connector.lua      # Darktable Lua plugin (~8,000 lines) — self-updating
|       +-- splash.py                  # Processing splash screen (Tkinter)
|       +-- darktable_splash.jpg       # Spellcaster overlay for Darktable processing + system splash
|
+-- assets/
    +-- wizard_banner.gif
    +-- spellcaster_hero.png
    +-- installer_background.png
    +-- showcase_*.png / *.gif
```

### How It Works

<p align="center">
  <img src="assets/workflow-pipeline.svg" alt="Spellcaster Workflow Pipeline" width="100%"/>
</p>

You pick a preset and click a button. Spellcaster handles everything else:

1. **Select** -- Paint a selection or pick an image in your editor
2. **Export** -- Image exported as a temporary PNG (automatic)
3. **Upload** -- Sent to ComfyUI server via HTTP (local or network)
4. **AI Process** -- ComfyUI runs the workflow with expertly-tuned parameters on your GPU
5. **Download** -- Result fetched back from the server
6. **Import** -- Appears as a new layer (GIMP) or in your library (Darktable)

### Plugin Design

**[GIMP](https://www.gimp.org/) Plugin** (~11,000 lines Python) -- Full GTK integration with GIMP 3's GObject API. Async image uploads, architecture-aware LoRA filtering, ControlNet guides integrated into img2img/inpaint, 25 scene presets, 44 inpaint refinements, 52 video presets. Session recall remembers last-used settings per dialog. User presets save/load across sessions. Runs spinner (1-99) queues multiple generations. Workflow lock serializes requests to prevent ComfyUI overload. Self-updates from GitHub via Tree API with subdirectory support.

**[Darktable](https://www.darktable.org/) Plugin** (~8,000 lines Lua) -- Pure Lua using Darktable's script_manager framework. HTTP via system `curl` with `shell_esc()` injection protection. Widgets persist state within sessions. User presets stored as Lua tables. Runs slider on every non-deterministic section. Processing lock prevents double-click stacking. Batch processing over selected images. Results auto-imported into library. Self-updates from GitHub via dynamic file discovery.

### Installer & Update Pipeline

**Installation** (GUI or CLI):

1. **System Detection** -- GPU name + VRAM via nvidia-smi / rocm-smi / WMIC. Classifies into tiers (Low/Medium/High/Ultra). No-GPU users get a clear warning with remote server guidance.
2. **Smart Feature Selection** -- 24 features shown with VRAM compatibility badges. One-click "Use recommended" for beginners, per-feature toggle for power users. Every feature pre-configured for optimal results.
3. **Node Installation** -- `git clone --depth 1` (or ZIP fallback) + `pip install -r requirements.txt` with alt-repo fallback
4. **VRAM-Aware Model Download** -- Skips model variants that exceed your VRAM. Streaming with progress bar, auth headers, automatic retry on failure.
5. **Plugin Deploy** — Copy plugin files, write `config.json` with server URL, set permissions
6. **LUT Import** — Optionally copy `.cube`/`.3dl` files from any source folder into `ComfyUI/models/luts/`
7. **Spellcaster Theme** — Optionally replace GIMP/Darktable system splash with AI-generated Spellcaster artwork

**Self-Updating Plugins:**

Both plugins check GitHub on each launch using the GitHub Tree API to dynamically discover all files in their respective directories. This means:
- New files are automatically downloaded
- Renamed files are handled (old removed, new added)
- Deleted files are cleaned up
- No hardcoded file lists to maintain
- Atomic file replacement via `.tmp` -> rename prevents corruption

**Manual Repair Tool** (`manual_update.py`):
- Aggressive multi-strategy search finds GIMP/Darktable installs even in non-standard locations
- Fixes misnamed plugin folders (GIMP requires exact folder name match)
- Repairs broken gimprc configuration
- Downloads fresh files via dynamic GitHub Tree API discovery
- Preserves user configuration across updates

</details>

---

<details>
<summary><h2>Model Presets</h2></summary>

Every checkpoint ships with hand-tuned generation settings that produce optimal results out of the box:

| Preset | Architecture | Resolution | Steps | CFG | Denoise | Sampler |
|---|---|---|---|---|---|---|
| Juggernaut Reborn | SD 1.5 | 512x512 | 25 | 7.0 | 0.62 | dpmpp_2m / karras |
| Juggernaut XL v9 | SDXL | 1024x1024 | 30 | 6.5 | 0.58 | dpmpp_2m_sde / karras |
| ZIT Photo (turbo) | ZIT | 1024x1024 | 6 | 2.0 | 0.60 | euler / simple |
| ZIT Quality | ZIT | 1024x1024 | 12 | 3.0 | 0.60 | dpmpp_2m / karras |
| Klein 4B Photo | Flux 2 | 1024x1024 | 4 | 1.0 | 0.70 | euler / simple |
| Klein 9B Photo | Flux 2 | 1024x1024 | 20 | 3.5 | 0.65 | euler / simple |
| Flux 1 Dev Photo | Flux 1 | 1024x1024 | 25 | 3.5 | 0.65 | euler / simple |
| Kontext Edit | Flux 1 | 1024x1024 | 25 | 3.5 | 0.80 | euler / simple |
| Wan 2.2 Q4 | Wan Video | 832x480 | 30 | 5.0 | -- | euler_a / simple |

</details>

---

<details>
<summary><h2>Contributing</h2></summary>

Pull requests, bug reports, and feature suggestions are welcome.

### How to Contribute

- **New model presets** -- Add entries to `manifest.json` with `url`, `page_url`, `size_mb`, and `note` fields. Mirror the preset in both the GIMP and Darktable plugins.
- **Workflow bugs** -- Open an issue with your ComfyUI version, installed nodes, and the error message from GIMP/Darktable.
- **Platform fixes** -- PRs for macOS/Linux path detection are especially appreciated.
- **New features** -- Propose in an issue first so we can discuss architecture.

### Building the Installer

```bash
# Auto-detect current OS and build
python build_installer.py

# Also build the repair/update tool
python build_installer.py --update-tool

# Target a specific platform
python build_installer.py --platform windows
python build_installer.py --platform macos --onedir   # Creates .app bundle
python build_installer.py --platform linux

# Build requires PyInstaller (auto-installed if missing)
```

### Spellmaker (Experimental)

**Spellmaker** is a standalone customization tool for power users who want to create their own presets, link custom LoRAs, import ComfyUI workflows, and modify every aspect of Spellcaster's behavior.

```bash
python spellmaker.py
```

- Edit all preset types: model, inpaint, scene, video, Wan I2V, Klein, IC-Light, custom workflows
- LoRA picker that connects to your ComfyUI server and lists all available LoRAs
- Import any ComfyUI workflow JSON — auto-detects type and extracts all parameters
- Clone, edit, delete presets with a visual editor
- Export to `spellbook.json` or inject directly into the GIMP/Darktable plugins

> **Status: Experimental.** Spellmaker works but is not yet bundled into the installer. Run it from the source tree.

### Project Guidelines

- **manifest.json** is the single source of truth for models, nodes, and features. Both plugins and both installers read from it.
- **Plugins are self-contained.** Each plugin file works independently once installed -- no runtime dependency on the installer or manifest.
- **Security matters.** All shell commands in the Darktable plugin use `shell_esc()` sanitization. The GIMP plugin uses Python's `urllib` directly (no shell).
- **Expert tuning is paramount.** Every preset, every parameter, every default value should be the product of extensive testing. The goal is that a complete beginner's first generation looks professional.

</details>

---

<details>
<summary><h2>Troubleshooting</h2></summary>

| Problem | Solution |
|---|---|
| Plugin not visible in GIMP | Run the **[Manual Update & Repair tool](https://github.com/laboratoiresonore/spellcaster/releases/latest/download/spellcaster-manual-update.exe)** -- it auto-detects and fixes broken installs |
| "Node not found" error | Install the missing custom node into `ComfyUI/custom_nodes/` (or re-run the installer) |
| "Cannot connect to server" | Verify ComfyUI is running and the URL is correct in the plugin dialog |
| Model not loading | Check the model file exists in the correct `ComfyUI/models/` subdirectory |
| GIMP plugin not appearing | Verify the plugin is in your GIMP 3 plug-ins directory and has execute permission |
| Darktable plugin not loading | Add `require "contrib/comfyui_connector"` to your `luarc` file |
| Download fails (403/401) | Add your CivitAI API token or HuggingFace token in the installer |
| Out of VRAM | Switch to a lower VRAM tier model (Q4 GGUF or fp8 variants) |
| ControlNet not working | Install `comfyui_controlnet_aux` node and download the ControlNet models for your architecture |
| Generations queue but never start | Check if ComfyUI has free VRAM. Spellcaster serializes requests -- the next starts when the previous finishes |
| All runs produce same result | Set seed to -1 (random). When Runs > 1, each run auto-randomizes |
| ZIT results look blurry | ZIT needs low CFG (1-3) and low steps (4-12). Using high CFG or many steps produces artifacts |
| SUPIR out of memory | SUPIR requires ~12 GB VRAM. Enable tiled encoding/decoding or use a smaller model |

</details>

---

## License

[GPL-2.0](LICENSE) -- Free software. Use it, modify it, share it.

---

<p align="center">
  <img src="plugins/darktable/darktable_splash.jpg " alt="Spellcaster" width="400" />
  <br/><br/>
  <strong>From noob to master in one install.</strong><br/>
  <sub>Made with love by <a href="https://github.com/laboratoiresonore">laboratoiresonore</a></sub>
</p>
