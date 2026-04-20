<p align="center">
  <img src="assets/wizard_banner.gif" alt="Spellcaster" width="58%"/>
</p>

<h1 align="center">Spellcaster</h1>

<p align="center">
  <strong>Type "hair" in GIMP. It selects the hair. Perfectly. In one second.</strong><br/>
  <em>69 AI tools, one menu. GIMP · DaVinci Resolve · Darktable · chat UI · 100% local · zero config.</em>
</p>

<p align="center">
  <sub><em>Spellcaster auto-detects your installed checkpoints and routes each generation to the right architecture. You never pick a sampler.</em></sub>
</p>

<p align="center">
  <a href="https://github.com/laboratoiresonore/spellcaster/releases/latest/download/spellcaster-installer.exe"><img src="https://img.shields.io/badge/Windows-Download-7c3aed?style=for-the-badge&logo=windows&logoColor=white" alt="Windows"/></a>
  &nbsp;
  <a href="https://github.com/laboratoiresonore/spellcaster/releases/latest/download/spellcaster-installer-macos.zip"><img src="https://img.shields.io/badge/macOS-Download-7c3aed?style=for-the-badge&logo=apple&logoColor=white" alt="macOS"/></a>
  &nbsp;
  <a href="https://github.com/laboratoiresonore/spellcaster/releases/latest/download/spellcaster-installer"><img src="https://img.shields.io/badge/Linux-Download-7c3aed?style=for-the-badge&logo=linux&logoColor=white" alt="Linux"/></a>
</p>

<p align="center">
  <a href="https://github.com/laboratoiresonore/spellcaster/releases"><img alt="Releases" src="https://img.shields.io/github/v/release/laboratoiresonore/spellcaster?color=7c3aed&label=latest&style=flat"/></a>
  <a href="LICENSE"><img alt="License" src="https://img.shields.io/badge/license-GPL--2.0-7c3aed?style=flat"/></a>
  <a href="https://github.com/laboratoiresonore/spellcaster/stargazers"><img alt="Stars" src="https://img.shields.io/github/stars/laboratoiresonore/spellcaster?style=flat&color=7c3aed"/></a>
  <a href="https://github.com/laboratoiresonore/spellcaster/releases/latest"><img alt="Downloads" src="https://img.shields.io/github/downloads/laboratoiresonore/spellcaster/total?color=7c3aed"/></a>
  <a href="https://patreon.com/LeLaboratoireSonore"><img alt="Support on Patreon" src="https://img.shields.io/badge/Patreon-Tip_the_lab-F96854?style=flat&logo=patreon&logoColor=white"/></a>
</p>

<p align="center">
  <a href="#save-a-day-of-work-right-now">Save a day of work</a> &bull;
  <a href="#i-want-to">I want to…</a> &bull;
  <a href="#five-clicks-start-to-finish">5-click showcase</a> &bull;
  <a href="#install">Install</a> &bull;
  <a href="#three-ways-to-use-it">Three UIs</a> &bull;
  <a href="#faq">FAQ</a> &bull;
  <a href="DEEP_DIVE.md">Deep dive</a>
</p>

---

<div align="center">

<strong>📣 Status — April 2026</strong>

<table>
<tr><td><strong>🆕 News</strong></td><td>DaVinci Resolve plugin is out — test it and report all bugs!</td></tr>
<tr><td><strong>✅ What works</strong></td><td>GIMP plugin is a powerhouse and a far better interface than ComfyUI for anything related to images</td></tr>
<tr><td><strong>🔧 Current focus</strong></td><td>Global debugging and optimizing</td></tr>
<tr><td><strong>⏭ Next</strong></td><td>Signal bridge &nbsp;·&nbsp; Moar plugins / frontends (<a href="https://github.com/laboratoiresonore/spellcaster/issues/new">make a request</a>)</td></tr>
</table>

</div>

---

## Save a day of work, right now

Three things Spellcaster does in one click that most people spend an afternoon (or a whole day) on.

<h3 align="center">🎨 Image models</h3>
<p align="center">
  <a href="DEEP_DIVE.md#all-69-tools" title="Flux 2 Klein — 4-step, ref-aware, SOTA photoreal"><img src="https://img.shields.io/badge/Flux%202%20Klein-ffd700?style=flat-square&labelColor=1a1422" alt="Flux 2 Klein"/></a>
  <a href="DEEP_DIVE.md#all-69-tools" title="Flux 1 Dev — 12B rectified-flow, ControlNet Union Pro"><img src="https://img.shields.io/badge/Flux%201%20Dev-58e0ff?style=flat-square&labelColor=1a1422" alt="Flux 1 Dev"/></a>
  <a href="DEEP_DIVE.md#all-69-tools" title="Flux Kontext — edit-by-instruction"><img src="https://img.shields.io/badge/Flux%20Kontext-7ad7ff?style=flat-square&labelColor=1a1422" alt="Flux Kontext"/></a>
  <a href="DEEP_DIVE.md#all-69-tools" title="Chroma — 8B open-weights DiT"><img src="https://img.shields.io/badge/Chroma-ff7ad7?style=flat-square&labelColor=1a1422" alt="Chroma"/></a>
  <a href="DEEP_DIVE.md#all-69-tools" title="SDXL — the workhorse, every ControlNet works"><img src="https://img.shields.io/badge/SDXL-b470ff?style=flat-square&labelColor=1a1422" alt="SDXL"/></a>
  <a href="DEEP_DIVE.md#all-69-tools" title="Illustrious — booru-tagged anime/illustration"><img src="https://img.shields.io/badge/Illustrious-ff8fd1?style=flat-square&labelColor=1a1422" alt="Illustrious"/></a>
  <a href="DEEP_DIVE.md#all-69-tools" title="Pony — score-cascade SDXL finetune"><img src="https://img.shields.io/badge/Pony-ffa8d4?style=flat-square&labelColor=1a1422" alt="Pony"/></a>
  <a href="DEEP_DIVE.md#all-69-tools" title="Playground — aesthetic SDXL finetune"><img src="https://img.shields.io/badge/Playground-c09bff?style=flat-square&labelColor=1a1422" alt="Playground"/></a>
  <a href="DEEP_DIVE.md#all-69-tools" title="SD 1.5 — classic, universal LoRA compatibility"><img src="https://img.shields.io/badge/SD%201.5-8aa9ff?style=flat-square&labelColor=1a1422" alt="SD 1.5"/></a>
  <a href="DEEP_DIVE.md#all-69-tools" title="SDXL Turbo — 6-step distilled"><img src="https://img.shields.io/badge/SDXL%20Turbo-ffb864?style=flat-square&labelColor=1a1422" alt="SDXL Turbo"/></a>
  <a href="DEEP_DIVE.md#all-69-tools" title="Z-Image Turbo — 6-step, 2B, sharpest distill"><img src="https://img.shields.io/badge/Z%E2%80%91Image%20Turbo-ffef4a?style=flat-square&labelColor=1a1422" alt="Z-Image Turbo"/></a>
</p>

<h3 align="center">🎬 Video models</h3>
<p align="center">
  <a href="DEEP_DIVE.md#all-69-tools" title="Wan 2.2 I2V — 14B image-to-video"><img src="https://img.shields.io/badge/Wan%202.2-10b981?style=flat-square&labelColor=1a1422" alt="Wan 2.2"/></a>
  <a href="DEEP_DIVE.md#all-69-tools" title="LTX 2.3 — 22B cinematic T2V + I2V"><img src="https://img.shields.io/badge/LTX%202.3-5eead4?style=flat-square&labelColor=1a1422" alt="LTX 2.3"/></a>
  <a href="DEEP_DIVE.md#all-69-tools" title="SeedVR — temporally consistent video upscale"><img src="https://img.shields.io/badge/SeedVR-34d399?style=flat-square&labelColor=1a1422" alt="SeedVR"/></a>
</p>

<h3 align="center">🧠 Brains & helpers</h3>
<p align="center">
  <a href="DEEP_DIVE.md#all-69-tools" title="SAM 3 — type 'earring' to select the earring"><img src="https://img.shields.io/badge/SAM%203-ff6b9d?style=flat-square&labelColor=1a1422" alt="SAM 3"/></a>
  <a href="DEEP_DIVE.md#all-69-tools" title="NormalCrafter — 3D normal maps from 2D"><img src="https://img.shields.io/badge/NormalCrafter-9f7aea?style=flat-square&labelColor=1a1422" alt="NormalCrafter"/></a>
  <a href="DEEP_DIVE.md#all-69-tools" title="IC-Light — surface-aware relighting"><img src="https://img.shields.io/badge/IC%E2%80%91Light-fbbf24?style=flat-square&labelColor=1a1422" alt="IC-Light"/></a>
  <a href="DEEP_DIVE.md#all-69-tools" title="ReActor + InsightFace — face swap / restore"><img src="https://img.shields.io/badge/ReActor-f472b6?style=flat-square&labelColor=1a1422" alt="ReActor"/></a>
  <a href="DEEP_DIVE.md#all-69-tools" title="Ollama — local LLM for prompt enhance + scoring"><img src="https://img.shields.io/badge/Ollama-64748b?style=flat-square&labelColor=1a1422&logo=ollama&logoColor=white" alt="Ollama"/></a>
</p>

<table>
<tr>
<td width="33%" align="center" valign="top">
  <img src="assets/sam3demo.png" alt="AI Select with SAM3 — earring mask" width="100%"/>
  <br/><br/>
  <strong>Type what to select</strong><br/>
  <sub>Open the AI Select tool. Type <code>earring</code> (or <code>hair</code>, or <code>left shoe</code>). SAM3 gives you a perfect mask. No lasso, no quick-mask, no endless zooming. The thing graphics people said saves a day of work.</sub>
</td>
<td width="33%" align="center" valign="top">
  <img src="assets/showcase_supir.png" alt="SUPIR Restoration" width="100%"/>
  <img src="assets/_px.gif" width="1" height="208" alt=""/>
  <br/><br/>
  <strong>Resurrect a blurry photo</strong><br/>
  <sub>SUPIR state-of-the-art restoration. One click. Damaged, compressed, low-res — it reconstructs faces, skin, texture. Works on grandma's scanned photos and on JPEGs you downloaded in 2006.</sub>
</td>
<td width="33%" align="center" valign="top">
  <img src="assets/showcase_wan_breathing.gif" alt="Wan 2.2 Image-to-Video" width="100%"/>
  <img src="assets/_px.gif" width="1" height="323" alt=""/>
  <br/><br/>
  <strong>Animate a still</strong><br/>
  <sub>Wan 2.2 Image-to-Video. Pick your motion preset (zoom, turntable, parallax, 26 of them), click. 81 frames, 720p, 2-5 seconds. The image breathes. Render it overnight, post it tomorrow.</sub>
</td>
</tr>
</table>

---

## I want to…

Pick the thing you want. One tool per row. The **Best in** column tells you the fastest interface to launch it from — 🖌️ **GIMP** for pixel-accurate work, 📷 **Darktable** for RAW-first batching, 🧙 **Wizard Guild** for conversational prompts, 🎬 **Resolve** for timeline-aware video, 🎭 **SillyTavern** for in-chat renders.

<table>
<tr>
<td width="16%" align="center"><img src="assets/showcase_lama_remove.png" alt="AI Eraser" width="100%"/></td>
<td><strong>Remove something from a photo</strong><br/><sub>LaMa inpainting erases anything — tourists, power lines, ex-boyfriends — and fills the gap cleanly.</sub></td>
<td width="18%"><sub>🖌️ <strong>GIMP</strong> — select + <code>Ctrl+Alt+X</code> ·<br/>📷 <strong>Darktable</strong> — Send to GIMP first</sub></td>
</tr>
<tr>
<td width="16%" align="center"><img src="assets/showcase_rembg.png" alt="Remove Background" width="100%"/></td>
<td><strong>Cut out the subject</strong><br/><sub>Three engines — rembg, BiRefNet (best for hair), BiRefNet Portrait. You get transparency. No cleanup needed.</sub></td>
<td width="18%"><sub>🖌️ <strong>GIMP</strong> — <code>Ctrl+Alt+B</code> ·<br/>🧙 <strong>Guild</strong> — "remove the background"</sub></td>
</tr>
<tr>
<td width="16%" align="center"><img src="assets/showcase_colorize.png" alt="Colorize" width="100%"/></td>
<td><strong>Colorize a B&W photo</strong><br/><sub>Three engines — DDColor artistic/natural, or ControlNet + diffusion for the "restored family portrait" look.</sub></td>
<td width="18%"><sub>🖌️ <strong>GIMP</strong> — one dialog ·<br/>📷 <strong>Darktable</strong> — batch across shoots</sub></td>
</tr>
<tr>
<td width="16%" align="center"><img src="assets/showcase_iclight_golden.png" alt="IC-Light" width="100%"/></td>
<td><strong>Change the lighting</strong><br/><sub>IC-Light relighting. Pick "Golden Hour", "Neon", "Studio", 10 presets — the subject stays, the light changes.</sub></td>
<td width="18%"><sub>🖌️ <strong>GIMP</strong> — Style menu, one preset click ·<br/>🧙 <strong>Guild</strong> — "relight as sunset"</sub></td>
</tr>
<tr>
<td width="16%" align="center"><img src="assets/showcase_face_restore.png" alt="Face Restore" width="100%"/></td>
<td><strong>Fix a face</strong><br/><sub>Seven models — GPEN-2048, CodeFormer, GFPGAN, RestoreFormer++. Sharp eyes and skin back.</sub></td>
<td width="18%"><sub>🖌️ <strong>GIMP</strong> — <code>Ctrl+Alt+F</code> ·<br/>📷 <strong>Darktable</strong> — restore a whole folder</sub></td>
</tr>
<tr>
<td width="16%" align="center"><img src="assets/showcase_faceid.png" alt="Face Identity" width="100%"/></td>
<td><strong>Put your face on a character</strong><br/><sub>ReActor, FaceID, PuLID, Flux 2 Headswap. Upload a reference, generate a new scene, the subject has your face.</sub></td>
<td width="18%"><sub>🖌️ <strong>GIMP</strong> — upload + preset ·<br/>🎭 <strong>ST</strong> — <code>/portrait</code> in roleplay</sub></td>
</tr>
<tr>
<td width="16%" align="center"><img src="assets/showcase_style_transfer.png" alt="Style Transfer" width="100%"/></td>
<td><strong>Copy a style</strong><br/><sub>IPAdapter style transfer. Point at any reference image — painting, photograph, illustration — and your image gets rewritten in that style.</sub></td>
<td width="18%"><sub>🖌️ <strong>GIMP</strong> — reference image picker ·<br/>🧙 <strong>Guild</strong> — drop a ref, chat it</sub></td>
</tr>
<tr>
<td width="16%" align="center"><img src="assets/showcase_seedv2r.png" alt="SeedV2R Upscale" width="100%"/></td>
<td><strong>Upscale with hallucinated detail</strong><br/><sub>Nine upscalers: WaveSpeed SeedVR2 (best, 2K/4K), UltraSharp, RealESRGAN, Remacri, NMKD, Anime. Controllable hallucination.</sub></td>
<td width="18%"><sub>🖌️ <strong>GIMP</strong> — <code>Ctrl+Alt+U</code> ·<br/>📷 <strong>Darktable</strong> — Hybrid Blend panel</sub></td>
</tr>
<tr>
<td width="16%" align="center"><img src="assets/showcase_normal_map.png" alt="3D Normal Map" width="100%"/></td>
<td><strong>Extract 3D surface geometry</strong><br/><sub>NormalCrafter generates a 3D normal map from any 2D image. Use it in Blender, in game engines, or feed it back into Spellcaster to relight the scene.</sub></td>
<td width="18%"><sub>🖌️ <strong>GIMP</strong> — Enhance ▸ 3D Normal Map ·<br/>📷 <strong>Darktable</strong> — 3D / Relighting panel</sub></td>
</tr>
<tr>
<td width="16%" align="center"><img src="assets/showcase_klein_flux2.png" alt="Flux 2 Klein" width="100%"/></td>
<td><strong>Edit with Flux 2 Klein</strong><br/><sub>4-20 steps, photorealistic, best-in-class img2img and inpaint. Klein is the one people notice. 9 Klein-specific tools, all pre-tuned.</sub></td>
<td width="18%"><sub>🖌️ <strong>GIMP</strong> — Flux 2 submenu, 9 tools ·<br/>🧙 <strong>Guild</strong> — auto-routes via Portraitist wizard</sub></td>
</tr>
<tr>
<td width="16%" align="center"><img src="assets/showcase_spellcaster_cat.gif" alt="Spellcaster — the mascot cat wizard" width="100%"/></td>
<td><strong>Have fun and generate whatever the hell I want</strong><br/><sub>Text to Image across 9 model families. Type "a cat wizard reading a spellbook." Get a cat wizard reading a spellbook. 25 scene presets.</sub></td>
<td width="18%"><sub>🧙 <strong>Wizard Guild</strong> — just type it, the wizards route it ·<br/>🖌️ <strong>GIMP</strong> — Text to Image dialog</sub></td>
</tr>
<tr>
<td width="16%" align="center"><img src="assets/showcase_wan_breathing.gif" alt="Animate a still" width="100%"/></td>
<td><strong>Animate a still into a clip</strong><br/><sub>Wan 2.2 I2V (81 frames, 720p) or LTX 2.3. 26 motion presets — zoom, turntable, parallax, breathing portrait, falling petals.</sub></td>
<td width="18%"><sub>🎬 <strong>Resolve</strong> — drop playhead, render to timeline ·<br/>🖌️ <strong>GIMP</strong> — Image ▸ WAN I2V ·<br/>🎭 <strong>ST</strong> — <code>/animate</code></sub></td>
</tr>
</table>

<sub><strong>Icon key</strong> · 🖌️ GIMP plugin · 📷 Darktable plugin · 🧙 Wizard Guild chat · 🎬 DaVinci Resolve plugin · 🎭 SillyTavern extension — all four talk to the same ComfyUI backend and share a gallery, so any result shows up everywhere.</sub>

**Too many to list here.** [All 69 tools →](DEEP_DIVE.md#all-69-tools)

---

## Five clicks, start to finish

A real pipeline, all built into the GIMP menu. Generate a scene → AI-select the subject → extract its 3D geometry → enhance the detail surgically → blend back in. Five menu items. Zero configuration. Takes longer to microwave a Hot Pocket — and unlike the Hot Pocket, the result doesn't make you question your life choices.

<table>
<tr>
<td width="20%"><img src="assets/showcase_3d_step1_generate.png" alt="Step 1: Generate" width="100%"/><br/><sub><strong>1. Generate</strong> — SDXL creates the scene</sub></td>
<td width="20%"><img src="assets/showcase_3d_step2_sam3.png" alt="Step 2: AI Select" width="100%"/><br/><sub><strong>2. AI Select</strong> — SAM3 isolates the statue</sub></td>
<td width="20%"><img src="assets/showcase_3d_step3_normalmap.png" alt="Step 3: Normal Map" width="100%"/><br/><sub><strong>3. 3D Normal Map</strong> — surface geometry extracted</sub></td>
<td width="20%"><img src="assets/showcase_3d_step4_enhance.png" alt="Step 4: Enhance" width="100%"/><br/><sub><strong>4. Detail Enhance</strong> — surgical texture refinement on the isolated layer</sub></td>
<td width="20%"><img src="assets/showcase_3d_step5_blend.png" alt="Step 5: Blend Layers" width="100%"/><br/><sub><strong>5. Blend Layers</strong> — reintegrated into the original scene</sub></td>
</tr>
</table>

---

## Install

### What you need

| You need | What it is | Where to get it |
|---|---|---|
| **ComfyUI** | The AI engine (runs in background, you never open it) | [github.com/comfyanonymous/ComfyUI](https://github.com/comfyanonymous/ComfyUI) |
| **GIMP 3** | Free image editor (the free Photoshop) | [gimp.org](https://www.gimp.org/downloads/) |
| **A GPU with 4+ GB VRAM** | Runs the AI models | You probably have one |

> **No GPU?** Use the **Antenna** to connect to ComfyUI on another machine on your network. Gaming PC in the closet, laptop on the couch — they get along.

### Get the installer

<p align="center">
  <a href="https://github.com/laboratoiresonore/spellcaster/releases/latest/download/spellcaster-installer.exe"><img src="https://img.shields.io/badge/Windows-spellcaster--installer.exe-7c3aed?style=for-the-badge&logo=windows&logoColor=white" alt="Windows"/></a>
  &nbsp;
  <a href="https://github.com/laboratoiresonore/spellcaster/releases/latest/download/spellcaster-installer-macos.zip"><img src="https://img.shields.io/badge/macOS-Spellcaster%20Installer.app-7c3aed?style=for-the-badge&logo=apple&logoColor=white" alt="macOS"/></a>
  &nbsp;
  <a href="https://github.com/laboratoiresonore/spellcaster/releases/latest/download/spellcaster-installer"><img src="https://img.shields.io/badge/Linux-spellcaster--installer-7c3aed?style=for-the-badge&logo=linux&logoColor=white" alt="Linux"/></a>
</p>

1. **Download** and run the installer. It detects your GPU, downloads models, installs plugins, creates shortcuts.
2. **Open GIMP.** `Filters > Spellcaster` — all 69 AI tools are there.
3. **Pick any tool. Click Generate.** Every preset is already optimized. The AI does the rest. You take the credit.

> **From source:** `git clone https://github.com/laboratoiresonore/spellcaster && cd spellcaster && python installer/install.py`

### The Antenna — remote ComfyUI in one click

The **Antenna** is a small always-on bridge that lets Spellcaster on your laptop drive ComfyUI, KoboldCpp, Ollama, Resolve, Darktable, GIMP, or SillyTavern on **another PC** on your LAN. Pair once, forget forever.

<p align="center">
  <a href="https://github.com/laboratoiresonore/spellcaster/releases/latest/download/spellcaster-antenna-windows.exe"><img src="https://img.shields.io/badge/Windows-spellcaster--antenna.exe-2ed573?style=for-the-badge&logo=windows&logoColor=white" alt="Antenna Windows"/></a>
  &nbsp;
  <a href="https://raw.githubusercontent.com/laboratoiresonore/spellcaster/main/installer/install_antenna.sh"><img src="https://img.shields.io/badge/macOS%20%2F%20Linux-install__antenna.sh-2ed573?style=for-the-badge&logo=apple&logoColor=white" alt="Antenna shell"/></a>
</p>

**Windows:** download the ~140 MB binary, double-click. First launch asks about desktop icon / Start Menu entry / run-at-login. Tray icon appears; right-click → *Pair with Guild…* → type the 6-digit code into your Guild sidebar.

**macOS / Linux:** `curl -LO <link>` → `chmod +x install_antenna.sh && ./install_antenna.sh`. Tray works on macOS; Linux falls back to console mode.

---

## Three ways to use it

<table>
<tr>
<td width="33%" align="center" valign="top">
  <img src="assets/demo_step1_inpaint.png" alt="GIMP plugin — select what to fix" width="100%"/>
  <img src="assets/demo_step2_inpaint.png" alt="GIMP plugin — pick a preset" width="100%"/>
  <img src="assets/demo_step4_inpaint.png" alt="GIMP plugin — result on a new layer" width="100%"/>
  <br/><br/>
  <strong>🖌️ GIMP plugin</strong><br/>
  <sub>The menu. 69 tools across <code>Filters > Spellcaster</code>. Select layers, paint masks, click a tool. Keyboard shortcuts (<code>Ctrl+Alt+E/U/F/B/X</code>) for the quick ones. Every output lands as a new layer. Non-destructive, reversible, composable.</sub>
</td>
<td width="33%" align="center" valign="top">
  <img src="assets/wizardguild.png" alt="Wizard Guild — chat UI" width="100%"/>
  <img src="assets/t1.png" alt="Wizard Guild — second view" width="100%"/>
  <img src="assets/t3.png" alt="Wizard Guild — third view" width="100%"/>
  <img src="assets/_px.gif" width="1" height="38" alt=""/>
  <br/><br/>
  <strong>🧙 Wizard Guild</strong><br/>
  <sub>The chat UI. AI wizard characters walk you through every tool conversationally. "Restore this photo." "Make the sky orange." "Turn this into a video." No menus, no modes. <a href="DEEP_DIVE.md#the-wizard-guild-chat-interface">How it works →</a></sub>
</td>
<td width="33%" align="center" valign="top">
  <img src="assets/ResolvePlugin.png" alt="DaVinci Resolve plugin" width="100%"/>
  <br/><br/>
  <strong>🎬 DaVinci Resolve plugin</strong><br/>
  <sub>The timeline. Drop the playhead, type a prompt, get an LTX-2 clip back in the Media Pool. Gap-fill between clips with reference-aware rendering. Markers map to render profiles. <a href="DEEP_DIVE.md#-resolve-bridge--timeline-aware-shot-generation">How it works →</a></sub>
</td>
</tr>
</table>

All three talk to the same ComfyUI backend. Every generated asset is visible from every interface. [The mechanics →](DEEP_DIVE.md#-cross-interface-backbone--every-surface-is-the-same-surface)

---

<details>
<summary><strong>💎 SillyTavern integration</strong></summary>

<p align="center">
  <img src="assets/ST.png" alt="SillyTavern — roleplay interface with Spellcaster" width="100%"/>
</p>

Spellcaster's [SillyTavern plugin](plugins/sillytavern/) turns the roleplay surface into a fourth interface. Slash commands (`/scene`, `/portrait`, `/animate`) render Klein-2 stills and LTX-2 clips in-chat. A round-trip-safe **Character Card Editor** in GIMP lets you paint card art, edit the V2 metadata with LLM-scaffolded best-practice auto-optimization, and save spec-compliant `chara` PNGs without damaging the embedded data. [SillyTavern upstream →](https://github.com/SillyTavern/SillyTavern) · [How it works →](DEEP_DIVE.md#-cross-interface-backbone--every-surface-is-the-same-surface)

</details>

---

## For people who can't computer

If you can order food on your phone, you can use this. If you once successfully connected a printer on the first try, you're overqualified.

- **Installation?** Automated. The installer sniffs your GPU, figures out what AI models your hardware can run, downloads them, installs everything, creates shortcuts. You click "Next" a few times.
- **Settings?** Automated. Every tool has expert-tuned presets. Or run the **Calibration Wizard** — it shows you real images and asks "A or B?" Like an eye exam. [Details →](DEEP_DIVE.md#calibration-wizard)
- **Prompts?** Automated. Type "a cat" — a local AI rewrites it into the flavour your model was trained on. SDXL wants tags. Flux wants paragraphs. Klein wants bullets. It does this for you. [Details →](DEEP_DIVE.md#-prompt-enhancement--per-architecture-per-method-per-model)
- **Model selection?** Automated. The plugin detects what models are installed and picks the best one.
- **VRAM management?** Automated. Video resolution auto-scales to fit your GPU. The LLM politely unloads itself during image generation. TeaCache acceleration silently injected.
- **Remote ComfyUI?** Automated. The **Antenna** makes a ComfyUI on another machine feel local.
- **Updates?** Automated. The plugin checks GitHub on launch and silently patches itself.
- **Recovery?** Automated. If an update corrupts the plugin, a 3-tier recovery system restores from backup, re-downloads from GitHub, or shows a visible error. GIMP never bricks.

**Open GIMP. Go to the Spellcaster menu. Pick a tool. Click Generate. That's it.**

Too intimidated by GIMP? The [Wizard Guild](DEEP_DIVE.md#the-wizard-guild-chat-interface) is a chat interface where you just tell an AI wizard what you want. In English.

---

## FAQ

<details>
<summary><strong>What GPU do I need?</strong></summary>

Any NVIDIA GPU with 4+ GB VRAM. AMD works too (ROCm/DirectML). The installer looks at your GPU and says "here's what you can run" — no guesswork. 4GB gets you the basics. 8GB is the sweet spot. 16GB unlocks the good stuff. 24GB and you're basically a wizard yourself.

</details>

<details>
<summary><strong>Do I need to understand ComfyUI?</strong></summary>

No. God no. That's the whole point. Every tool has expert-tuned presets. You never need to open ComfyUI, pick a sampler, write a negative prompt, or learn what "Euler ancestral CFG++ with Karras scheduling at 0.85 denoise" means. That sentence just gave you a headache. See? We saved you from that.

If you *want* to go deeper — every parameter is exposed, you can save custom presets, import raw ComfyUI workflows, and inject LoRAs. The power is there when you're ready for it.

</details>

<details>
<summary><strong>Does anything leave my computer?</strong></summary>

No. Nothing. Nada. Zero bytes. Your GPU does all the work, your images stay on your hard drive. The only network traffic is between GIMP and your own ComfyUI server, which can literally be `localhost`.

</details>

<details>
<summary><strong>Can I use my own ComfyUI workflows?</strong></summary>

Yes. `Filters > Spellcaster Tools > Workflow Library` runs any workflow JSON from GIMP.

</details>

<details>
<summary><strong>ComfyUI on another machine?</strong></summary>

Yes. The Antenna auto-detects ComfyUI servers on your network, or set the URL in Settings. Gaming PC in the closet, laptop on the couch — we have enabled laziness at an architectural level and we're proud of it. [Antenna details →](#the-antenna--remote-comfyui-in-one-click)

</details>

<details>
<summary><strong>Can I have more than one LLM running at once?</strong></summary>

Yes. ComfyUI's embedded LLM, Ollama, and a dedicated RP Kobold can all stay online together — SillyTavern keeps chatting with Kobold, the Guild uses ComfyUI for image prompts, Ollama handles install scaffolding. The pill picker decides who answers first; nobody gets stopped. [Details →](DEEP_DIVE.md#-llm-primary-picker--comfyui-reroute-ollama--kobold-auto-start)

</details>

<details>
<summary><strong>How does the LoRA Shootout work?</strong></summary>

Purpose-aware multi-sample renders. The LoRA registry is grouped into 20+ purpose buckets (`skin_detail`, `style_photoreal`, …), each with a subject-specific prompt (portrait / fullbody / macro / animal). You approve **many** LoRAs — not one winner — with keywords that the Guild auto-proposes when the keyword appears in a chat prompt. Auto-fallback tries up to 3 checkpoints of the same arch on failure. [Scaffold details →](DEEP_DIVE.md#-scaffold-system--state-machine-wizards-for-7b-models)

</details>

<details>
<summary><strong>Can I talk to the Guild instead of typing?</strong></summary>

Yes. Register a KoboldCpp in TTS/STT mode, then press-and-hold the 🎙️ button. Walkie-talkie — release to transcribe. [Voice details →](DEEP_DIVE.md#-voice--walkie-talkie-stt--tts-playback)

</details>

<details>
<summary><strong>Why "Spellcaster"?</strong></summary>

Because every tool is a spell, every workflow is an incantation, your GPU is a familiar, and the entire project radiates the energy of someone who played too much D&D and then learned Python. Also "ComfyUI-GIMP-Middleware-With-69-Tools-And-A-Chat-UI-Full-Of-Wizards" didn't fit in the GitHub repo name.

</details>

---

## Dig deeper

- [**Full technical reference →** `DEEP_DIVE.md`](DEEP_DIVE.md) — all 69 tools enumerated, the 9-architecture registry, scaffold state machines, antenna endpoints, cross-interface backbone, prompt enhancement chain, privacy + boot safety details, every subsystem explained.
- [**ComfyUI dependencies** → `DEPENDENCIES.md`](DEPENDENCIES.md) — 24 custom node packs Spellcaster uses, linked to upstream.

---

## Love it? Share it.

Spellcaster is 100% free, 100% open-source, and 0% funded. If it saves you a day of clicking, the best way to pay it forward is to **tell someone**:

- 🌟 **Star the repo** so more GIMP / Darktable / Resolve users find it
- 📣 **Post a screenshot** of your first 5-click result with `#Spellcaster` on your favourite network
- 🧙 **Show a friend** who spends too long on ComfyUI noodle graphs — 30 seconds to install, they'll thank you
- 🐛 **Open an issue** if it broke, a PR if you fixed it, or a [discussion](https://github.com/laboratoiresonore/spellcaster/discussions) if you just want to show off what you made
- ☕ **Tip the lab** on [Patreon](https://patreon.com/LeLaboratoireSonore) if Spellcaster earned you an afternoon of sanity — it funds the next GPU and the next 5 a.m. debugging session

Word of mouth is the entire marketing budget. Make us famous.

<p align="center">
  <a href="https://patreon.com/LeLaboratoireSonore">
    <img alt="Become a Patron" src="https://img.shields.io/badge/Patreon-Become_a_Patron-F96854?style=for-the-badge&logo=patreon&logoColor=white"/>
  </a>
</p>

---

<details>
<summary><strong>Credits & acknowledgements</strong></summary>

*Proudly vibe-coded as a pure pineapple-pen innovation.* 🍍🖊️

Spellcaster doesn't reinvent the wheel — it duct-tapes together the best wheels the open-source AI community has ever built, then hides the duct tape behind a nice menu:

**Core engine:** [ComfyUI](https://github.com/comfyanonymous/ComfyUI) by comfyanonymous — the node-based powerhouse that actually does everything

**Models & architectures:** [Stability AI](https://stability.ai/) (SD 1.5, SDXL, SD3), [Black Forest Labs](https://blackforestlabs.ai/) (Flux), [Flux 2 Klein](https://civitai.com/), [Wan 2.2](https://github.com/Wan-Video/Wan2.2), [LTX Video](https://ltx.io/), [SeedVR2](https://seedvr2.net/)

**Workflow pipelines:** [Elusarca's Klein 6-in-1](https://civitai.com/models/2543188) (Klein refiner, auto-inpaint, color match — used with permission), [xb1n0ry's Comfy-Workflows](https://github.com/xb1n0ry/Comfy-Workflows) (Wan 2.2 NAG + SLG, Klein 4-image-grid, Wan 2.2 block-swap low-VRAM, Qwen Image Edit 2509)

**Face & identity:** [ReActor](https://github.com/Gourieff/comfyui-reactor-node), [IPAdapter](https://github.com/cubiq/ComfyUI_IPAdapter_plus), [PuLID](https://github.com/cubiq/PuLID_ComfyUI), [ACE++](https://github.com/ali-vilab/ACE_plus), [InsightFace](https://github.com/deepinsight/insightface), [CodeFormer](https://github.com/sczhou/CodeFormer), [GFPGAN](https://github.com/TencentARC/GFPGAN), [GPEN](https://github.com/yangxy/GPEN)

**Enhancement:** [Real-ESRGAN](https://github.com/xinntao/Real-ESRGAN), [SUPIR](https://github.com/Fanghua-Yu/SUPIR), [IC-Light](https://github.com/lllyasviel/IC-Light), [DDColor](https://github.com/piddnad/DDColor), [LaMa](https://github.com/advimman/lama), [NormalCrafter](https://github.com/AIWarper/ComfyUI-NormalCrafterWrapper)

**Segmentation:** [SAM 2/3](https://github.com/facebookresearch/sam2) (Meta), [BiRefNet/RMBG](https://github.com/1038lab/ComfyUI-RMBG), [DepthAnything V3](https://depth-anything-3.github.io/), [Florence 2](https://huggingface.co/microsoft/Florence-2-base)

**ControlNet:** [ControlNet](https://github.com/lllyasviel/ControlNet) by lllyasviel, [comfyui-controlnet-aux](https://github.com/Fannovel16/comfyui_controlnet_aux)

**Video:** [RIFE](https://github.com/hzwer/ECCV2022-RIFE), [GIMM-VFI](https://github.com/GSeanCDAT/GIMM-VFI), [VHS](https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite), [AnimateDiff](https://github.com/guoyww/AnimateDiff)

**Acceleration:** [TeaCache](https://github.com/welltop-cn/ComfyUI-TeaCache), [WaveSpeed/FBCache](https://github.com/chengzeyi/Comfy-WaveSpeed), [LightX2V](https://github.com/ModelTC/LightX2V)

**LLM:** [Qwen3](https://huggingface.co/Qwen) (Alibaba), [ComfyUI-QwenVL-Mod](https://github.com/1038lab/ComfyUI-QwenVL)

**Klein Enhancer:** [Flux2Klein-Enhancer](https://github.com/capitan01R/ComfyUI-Flux2Klein-Enhancer) — RefLatentController, TextRefBalance, ColorAnchor

**Node packs:** [Impact Pack](https://github.com/ltdrdata/ComfyUI-Impact-Pack), [ComfyUI-essentials](https://github.com/cubiq/ComfyUI_essentials), [ComfyUI-GGUF](https://github.com/city96/ComfyUI-GGUF), [KJNodes](https://github.com/kijai/ComfyUI-KJNodes), and dozens more — full list in [DEPENDENCIES.md](DEPENDENCIES.md)

**Host apps:** [GIMP 3](https://www.gimp.org/), [Darktable](https://www.darktable.org/), [SillyTavern](https://github.com/SillyTavern/SillyTavern)

**Vibe coding assistant:** [Claude](https://claude.ai/) by Anthropic — wrote most of this while being yelled at

</details>

---

<p align="center">
  <sub>
    Made with unhealthy amounts of coffee, mass delusion, and a GPU that sounds like a jet engine.<br/>
    If you've read this far, you're either installing it or writing a hate comment. Either way, we appreciate the engagement.<br/><br/>
    <strong>Love it? Share it.</strong> Star the repo. Fork it if you hate it. Either way, pass it on.
  </sub>
</p>
