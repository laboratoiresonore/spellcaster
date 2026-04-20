# Spellcaster — Deep Dive

Everything the [README](README.md) intentionally left out. Architecture, subsystems, every tool enumerated, cross-app flows, all 9 model families, the scaffold state machines, the antenna, the prompt enhancement chain. If you read ingredient lists on cereal boxes, this is for you.

---

## Contents

- [All 69 Tools](#all-69-tools)
- [Under the Hood](#under-the-hood)
- [Calibration Wizard](#calibration-wizard)
- [The Wizard Guild (chat interface)](#the-wizard-guild-chat-interface)
- [Video Shotboard](#video-shotboard)
- [SillyTavern integration](#sillytavern-integration)
- [Cross-App Functions](#cross-app-functions)
- [🔀 Cross-interface backbone](#-cross-interface-backbone--every-surface-is-the-same-surface)
- [🧠 Prompt enhancement](#-prompt-enhancement--per-architecture-per-method-per-model)
- [🎯 LLM primary picker](#-llm-primary-picker--comfyui-reroute-ollama--kobold-auto-start)
- [🛠 Scaffold system](#-scaffold-system--state-machine-wizards-for-7b-models)
- [⚡ Global preset cycle](#-global-preset-cycle--turbo--standard--quality)
- [📡 Antenna](#-antenna--15-endpoints-tray-menu-self-update)
- [🎙 Voice](#-voice--walkie-talkie-stt--tts-playback)
- [🧩 Connect-an-app](#-connect-an-app--register-launchers-windows-shortcuts-auto-start)
- [🔐 Privacy, boot safety, auto-update risk](#-privacy-boot-safety-auto-update-risk)
- [🎬 Resolve Bridge](#-resolve-bridge--timeline-aware-shot-generation)
- [🖼️ Everything else worth mentioning](#%EF%B8%8F-everything-else-worth-mentioning)
- [For developers](#for-developers)

---

## All 69 Tools

Yes, we counted. Yes, we noticed. No, we will not be adding a 70th (officially).

<details open>
<summary><h3>Generate (7)</h3></summary>

| Tool | What It Does |
|---|---|
| **Text to Image** | Type what you want. 25 scene presets across 6 model families. |
| **Image to Image** | Transform any photo — change styles, add detail, reimagine. |
| **Inpaint Selection** | Paint over any area to regenerate it. 44 expert presets. |
| **Outpaint / Extend** | Extend your image beyond its borders in any direction. |
| **Batch Variations** | Generate 2-8 versions with one click. |
| **Edit by Instruction** | Type "make the sky orange" in plain English. Powered by Kontext. |
| **Generate Anything** | Create a transparent object (sword, hat, dragon) on its own layer. |

</details>

<details>
<summary><h3>Flux 2 Klein (9) — the fancy one</h3></summary>

Klein is what happens when you tell a diffusion model "no, I said *good*." It's 4-20 steps where every other architecture needs 30. It doesn't use a sampler — it uses a *guider*. It doesn't have a CFG scale — it has a *TextRefBalance*. It is, objectively, better than you. Here are its tools:

| Tool | What It Does |
|---|---|
| **AI Editor** | Best-quality img2img with Flux 2 Klein (4-20 steps). |
| **Editor + Reference** | Edit guided by a reference image for structure/style. |
| **Outpaint** | Highest-quality canvas extension. |
| **Inpaint** | Context-aware selection fill. 29 task presets. |
| **Layer Blender** | AI-powered layer harmonization. |
| **Re-poser** | Change poses and camera angles. 26 poses + 11 cameras. |
| **Headswap** | Hybrid: ReActor swap + Klein refinement. |
| **Detail Enhancer** | Targeted detail: face, eyes, hands, skin, hair, custom. |
| **Generate Object** | Transparent object with scene-matched lighting. |

</details>

<details>
<summary><h3>Enhance (9) — because your photo deserves better than what your camera gave it</h3></summary>

| Tool | What It Does |
|---|---|
| **Upscale** | 9 models: WaveSpeed SeedVR2 AI (2K/4K), UltraSharp, RealESRGAN, Remacri, NMKD, Anime. |
| **Photo Restoration** | One-click: upscale + face fix + sharpen. |
| **Detail Hallucination** | Add texture that wasn't there — upscale + low-denoise img2img. |
| **SUPIR AI Restoration** | State-of-the-art repair for damaged/compressed photos. |
| **SeedV2R Upscale** | Controllable hallucination: none/light/high. |
| **Colorize B&W** | 3 engines: DDColor instant (artistic/natural) or ControlNet+diffusion. |
| **Object Removal** | LaMa inpainting — paint over anything, it disappears. |
| **3D Normal Map** | NormalCrafter surface normals for relighting and 3D. |
| **AI Eraser** | Select + `Ctrl+Alt+X` = gone. AI fills the gap. |

</details>

<details>
<summary><h3>Face (7) — the identity crisis suite</h3></summary>

Seven different ways to put your face where it doesn't belong. We built them for "creative portrait work." You will use them to put your boss's face on a medieval knight. We know. It's fine. We've made our peace with it.

| Tool | What It Does |
|---|---|
| **Face Swap (ReActor)** | Paste a face from one photo onto another. |
| **Face Swap (Saved Model)** | Swap using a saved face model library. |
| **Face Swap (mtb)** | Alternative engine with multi-face indexing. |
| **Face Identity Transfer** | Generate images that look like a specific person. FaceID. |
| **Face Identity (Flux)** | Flux-native identity via PuLID. |
| **Face Restore** | 7 models: GPEN-2048, CodeFormer, GFPGAN, RestoreFormer++. |
| **Flux 2 Headswap** | ReActor + Klein refinement for seamless blending. |

</details>

<details>
<summary><h3>Style (4) &bull; Select (3) &bull; Video (7) — the "wait, it can do THAT?" section</h3></summary>

**Style:**

| Tool | What It Does |
|---|---|
| **Style Transfer** | Copy any reference image's visual style via IPAdapter. |
| **Color Grading** | Cinematic LUT application with strength control. |
| **IC-Light Relighting** | Change lighting direction. 10 presets. |
| **AI Color Match** | Transfer color palette from a reference. 3 methods. |

**Select:**

| Tool | What It Does |
|---|---|
| **AI Select (SAM3)** | Type "hair" or "shirt" to select it. |
| **AI Extract Subject** | One-click subject extraction with transparent background. |
| **Remove Background** | 3 engines: rembg, BiRefNet (best hair), BiRefNet Portrait. |

**Video:**

| Tool | What It Does |
|---|---|
| **LTX 2.3 Text to Video** | Generate video from text. VRAM-aware resolution. |
| **LTX 2.3 Image to Video** | Animate any photo. Preserves aspect ratio. |
| **Wan 2.2 Image to Video** | 2-5 second clips. 26 motion presets, dual-pass. |
| **Wan 2.2 First+Last Frame** | Video transition between two images. |
| **Video Upscale** | AI video upscaling with SeedVR2. |
| **Video Face Swap** | ReActor across every video frame + upscale. |
| **SeedVR2 Video Upscale** | Dedicated SeedVR2 video upscaler. |

</details>

<details>
<summary><h3>Studios (7) &bull; Quick (7) &bull; Tools (8) — for when you've gone full method actor</h3></summary>

**Studios** — full character production pipeline. You're not "using an AI tool" anymore. You're *running a one-person visual effects studio from inside a free image editor.* Your parents still think you're "playing on the computer."

| Tool | Pipeline step |
|---|---|
| **Casting Polaroids** | Create reusable face model from any photo. |
| **Body Double** | Full-body transparent cutout with face swap. |
| **Wardrobe Department** | AI outfit replacement. 40 presets. |
| **Set Design** | Generate background + composite characters. |
| **Director's Chair** (Solo/Duo/Trio) | Animated video with face re-injection. |

**Quick** — zero-dialog, instant (`Ctrl+Alt`):

| Action | Shortcut |
|---|---|
| Enhance | `Ctrl+Alt+E` |
| Inpaint | `Ctrl+Alt+P` |
| Upscale | `Ctrl+Alt+U` |
| Face Restore | `Ctrl+Alt+F` |
| Remove BG | `Ctrl+Alt+B` |
| AI Eraser | `Ctrl+Alt+X` |
| Re-run Last | `Ctrl+Alt+R` |

**Tools** — Layer Blend, Upscaler Blend, GIF Stitcher, Watermark Embed/Read, Upload to Server, Settings, Workflow Library.

</details>

---

## Under the Hood

<details>
<summary><strong>What makes it fast</strong></summary>

- **TeaCache auto-acceleration** — every image generation is automatically 1.4x faster. Zero config, zero quality loss. The optimizer injects it into all workflows.
- **Architecture-aware everything** — CFG, denoise, prompts, and ControlNet models are auto-configured per architecture. 9 supported: SD 1.5, SDXL, Illustrious/Pony, ZIT, Flux Dev, Flux 2 Klein, Flux Kontext, Chroma, and WAN/LTX for video.
- **AI Prompt Enhancement** — a local 4B LLM runs inside ComfyUI, rewrites your simple prompts into architecture-optimized descriptions. SDXL gets booru tags, Flux gets natural language, Klein gets concise descriptions. Multi-character prompts use BREAK separation with attention weights.
- **VRAM management** — LLM auto-unloads during image generation. LTX resolution auto-scales to fit your GPU. Video frame counts auto-cap on low VRAM.
- **Privacy cleanup** — all temporary files on ComfyUI are atomically overwritten with 1x1 pixel PNGs after use. Your images don't linger on the server.

</details>

## Calibration Wizard

<details>
<summary><strong>Optometrist for your GPU</strong></summary>

First time using Spellcaster? The Calibration Wizard tests every installed model and tunes all settings to your taste — no technical knowledge required. It is, to our knowledge, the only software that treats your artistic preferences like a medical condition that needs diagnosing.

1. **Model Taste Test** — generates the same scene with every installed model. You rate each one: Love / OK / Dislike.
2. **Settings Calibration** — for your favorite models, shows A/B/C comparisons (CFG, steps, sampler). You pick the image you prefer. That's it.
3. **Apply** — your preferences become the default everywhere. Every dialog reads from your calibrated profile.

It's an eye exam, but for art. "Which is better — A or B?" Repeat until your defaults are perfect.

Access: `Spellcaster > Tools > Calibration Wizard`

</details>

## The Wizard Guild (chat interface)

Don't want to learn GIMP? GIMP has 847 menu items and a learning curve that doubles as a cliff face. The Wizard Guild is a standalone web UI where AI wizard characters handle everything conversationally — tech support, except the support agent is a wizard and instead of restarting your computer it generates a photorealistic dragon.

<p align="center">
  <img src="assets/wizardguild.png" alt="The Wizard Guild" width="80%"/>
</p>

Each wizard specialises in one tool family. The backend chip row at the top shows which local LLMs are live (Ollama / KoboldCpp / ComfyUI-hosted), and every wizard's own chip row exposes the three or four actions it can do — no menus, no modes.

**Scaffolding a local LLM is a drag-and-drop affair.** The Travelling Wizard below is the editor:

<p align="center">
  <img src="assets/wizardguild2.png" alt="The Travelling Wizard — visual scaffold editor" width="80%"/>
</p>

Pick a flow from the left column (*Text-to-Image*, *Inpainting*, *Klein Image Editor*, *Photo Restoration*, *SUPIR Restoration* …), reorder its steps in the middle — **Greeting → Mode → Parameters → Review → Generate** — and tune the system prompt + rule checklist on the right. No JSON, no LangChain, no prompt engineering. Hit **Export** and the scaffold runs on any 3B–14B chat model: Ollama, KoboldCpp, LM Studio, SillyTavern, or the ComfyUI-hosted LLM node. The Meta Wizard and every plugin surface (GIMP / Darktable / Resolve / Signal bridge) consume the same format, so one tuning round travels everywhere.

A **Workflow Library** tab sits next to the scaffold editor and lists every ComfyUI workflow on your server — parsed with `scaffold.workflow_parser.discover_workflows`, auto-classified, with each workflow's tunable parameters surfaced — so a scaffold step can drive a real ComfyUI render without writing a single node. One author, every LLM plays.

Launch: `start_guild.bat` (Windows) or `python tavern/guild_launcher.py`

## Video Shotboard

The Shotboard is a persistent video production system for multi-shot sequences. At some point during development we stopped making a GIMP plugin and accidentally built a pre-production suite. We don't know when it happened. We're not apologizing. Each shot tracks its own motion trajectory, prompt, model, and status (draft → queued → running → ready). Shots link together for continuity — the last frame of shot 1 feeds into shot 2.

Build a full storyboard in the Guild UI, queue all shots, and let them render overnight. The assembly pipeline stitches them together with frame interpolation (RIFE/GIMM-VFI) for smooth transitions.

## SillyTavern integration

Drop these characters into any SillyTavern group chat. They work silently in the background — generating scene backgrounds, character portraits, and dramatic illustrations as your story unfolds. Yes, we gave each one a name, a backstory, and a portrait. Yes, we are aware this is unhinged. Imaginus is our favorite and we will not be taking questions.

<table>
<tr>
<td align="center" width="25%"><img src="tavern/characters/Imaginus.png" alt="Imaginus" width="120"/><br/><strong>Imaginus</strong><br/><sub>Text-to-image generation.<br/>Creates images from descriptions.</sub></td>
<td align="center" width="25%"><img src="tavern/characters/Transmutex.png" alt="Transmutex" width="120"/><br/><strong>Transmutex</strong><br/><sub>Image transformation.<br/>Changes styles, moods, details.</sub></td>
<td align="center" width="25%"><img src="tavern/characters/Masquerade.png" alt="Masquerade" width="120"/><br/><strong>Masquerade</strong><br/><sub>Face swap & identity.<br/>ReActor, FaceID, PuLID, Headswap.</sub></td>
<td align="center" width="25%"><img src="tavern/characters/Restorix.png" alt="Restorix" width="120"/><br/><strong>Restorix</strong><br/><sub>Upscale & restore.<br/>SUPIR, SeedV2R, CodeFormer, GPEN.</sub></td>
</tr>
<tr>
<td align="center" width="25%"><img src="tavern/characters/Erasure.png" alt="Erasure" width="120"/><br/><strong>Erasure</strong><br/><sub>Inpaint & remove.<br/>LaMa, AI Eraser, background gen.</sub></td>
<td align="center" width="25%"><img src="tavern/characters/Videomancer.png" alt="Videomancer" width="120"/><br/><strong>Videomancer</strong><br/><sub>Video generation.<br/>Wan 2.2 I2V, LTX 2.3 T2V.</sub></td>
<td align="center" width="25%"><img src="tavern/characters/Cinematic.png" alt="Cinematic" width="120"/><br/><strong>Cinematic</strong><br/><sub>Director's Chair.<br/>Multi-step video with face re-injection.</sub></td>
<td align="center" width="25%"><img src="tavern/characters/Studiocraft.png" alt="Studiocraft" width="120"/><br/><strong>Studiocraft</strong><br/><sub>Production manager.<br/>Full Studios pipeline orchestration.</sub></td>
</tr>
<tr>
<td align="center" width="25%"><img src="tavern/characters/Sceneshifter.png" alt="Sceneshifter" width="120"/><br/><strong>Sceneshifter</strong><br/><sub>Living scenes.<br/>Auto-generates backgrounds as story moves.</sub></td>
<td align="center" width="25%"><img src="tavern/characters/Portraitist.png" alt="Portraitist" width="120"/><br/><strong>Portraitist</strong><br/><sub>Expression portraits.<br/>Generates mood-matched character art.</sub></td>
<td align="center" width="25%"><img src="tavern/characters/Autonoma.png" alt="Autonoma" width="120"/><br/><strong>Autonoma</strong><br/><sub>Autonomous generation.<br/>AI decides when scenes need illustration.</sub></td>
<td align="center" width="25%"><img src="tavern/characters/Restyler.png" alt="Restyler" width="120"/><br/><strong>Restyler</strong><br/><sub>Avatar restyle.<br/>Transform all avatars to any art style.</sub></td>
</tr>
<tr>
<td align="center" width="25%"><img src="tavern/characters/Animancer.png" alt="Animancer" width="120"/><br/><strong>Animancer</strong><br/><sub>Animation.<br/>Brings still images to life as video.</sub></td>
<td align="center" width="25%"></td>
<td align="center" width="25%"></td>
<td align="center" width="25%"></td>
</tr>
</table>

**How to use:** Launch the Wizard Guild — it auto-downloads SillyTavern, installs the plugin, and imports all 13 characters. Add any character to a group chat alongside your RP characters. Sceneshifter and Autonoma work silently without interrupting conversation.

---

## Cross-App Functions

Spellcaster is the connective tissue. Every generated asset lives in one canonical store, every surface sees every other surface, and every action in one app can finish in another. Drop an image in GIMP, drop it into the Guild chat, drop it onto the Resolve timeline — same bytes, one hash, zero copies.

<p align="center">
  <a href="https://www.gimp.org/" title="GIMP — image editor"><img src="https://img.shields.io/badge/GIMP-5C5543?style=for-the-badge&logo=gimp&logoColor=white" height="48" alt="GIMP"/></a>
  &nbsp;
  <a href="README.md#three-ways-to-use-it" title="The Wizard Guild — chat UI"><img src="https://img.shields.io/badge/Wizard%20Guild-6A1B9A?style=for-the-badge&logo=data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAyNCAyNCIgZmlsbD0iI0ZGRDcwMCI+PHBhdGggZD0iTTE4LjUgMUw5IDE4bC0yLjUtNUwxIDE4LjUgMyAyM2wxNS01IDYgMi41TDIxIDExbC0yLjUtMTB6Ii8%2BPC9zdmc%2B&logoColor=FFD700" height="48" alt="Wizard Guild"/></a>
  &nbsp;
  <a href="https://www.blackmagicdesign.com/products/davinciresolve" title="DaVinci Resolve — video editor"><img src="https://img.shields.io/badge/DaVinci%20Resolve-222222?style=for-the-badge&logo=davinciresolve&logoColor=E74E3C" height="48" alt="Resolve"/></a>
  &nbsp;
  <a href="https://github.com/LostRuins/koboldcpp" title="KoboldCpp — local LLM server"><img src="https://img.shields.io/badge/KoboldCpp-FF6B00?style=for-the-badge&logo=openai&logoColor=white" height="48" alt="KoboldCpp"/></a>
  &nbsp;
  <a href="https://github.com/SillyTavern/SillyTavern" title="SillyTavern — roleplay chat"><img src="https://img.shields.io/badge/SillyTavern-6B7FD7?style=for-the-badge&logo=data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAyNCAyNCIgZmlsbD0iI0ZGRkZGRiI+PHBhdGggZD0iTTEyIDJMMSAyMWgyMkwxMiAyem0wIDRsNy41IDEzaC0xNUwxMiA2eiIvPjwvc3ZnPg==&logoColor=white" height="48" alt="SillyTavern"/></a>
  &nbsp;
  <a href="https://www.darktable.org/" title="Darktable — RAW editor"><img src="https://img.shields.io/badge/Darktable-1F1F1F?style=for-the-badge&logo=darktable&logoColor=FF7A21" height="48" alt="Darktable"/></a>
</p>

<p align="center"><sub>All six talk through one event bus + one blob store + one registry. Add a plugin, get every capability for free.</sub></p>

<table>
<tr>
<th width="15%" align="center">From</th>
<th width="15%" align="center">To</th>
<th>What it does</th>
<th width="20%" align="center">Example — Resolve Plugin</th>
</tr>

<tr>
<td align="center"><img src="https://img.shields.io/badge/GIMP-5C5543?style=flat-square&logo=gimp&logoColor=white" height="28" alt="GIMP"/><br/><strong>GIMP</strong></td>
<td align="center"><img src="https://img.shields.io/badge/Wizard%20Guild-6A1B9A?style=flat-square&logoColor=FFD700" height="28" alt="Guild"/><br/><strong>Wizard Guild</strong></td>
<td>Save any layer to the Guild gallery. It appears instantly under "Recent across apps" in the sidebar and drops into the active wizard's chat as a reference image on click. No upload step.</td>
<td rowspan="8" align="center" valign="top">
  <img src="assets/ResolvePlugin.png" alt="DaVinci Resolve plugin — 💎 Spellcaster scripts menu (30 entries: capture, generate, send-to, queue control)" width="220"/>
  <br/><sub><em>Resolve plugin's script menu — 30 💎 Spellcaster entries. Every cross-app send/capture on the left is a one-click script here.</em></sub>
</td>
</tr>

<tr>
<td align="center"><img src="https://img.shields.io/badge/GIMP-5C5543?style=flat-square&logo=gimp&logoColor=white" height="28" alt="GIMP"/><br/><strong>GIMP</strong></td>
<td align="center"><img src="https://img.shields.io/badge/Resolve-222222?style=flat-square&logo=davinciresolve&logoColor=E74E3C" height="28" alt="Resolve"/><br/><strong>Resolve</strong></td>
<td>Right-click a layer → <em>Send to Resolve Media Pool</em>. The Resolve Bridge picks up the <code>gimp.asset.created</code> event and imports the file at its canonical path. Works even when Resolve runs on a different machine (via the Antenna).</td>
</tr>

<tr>
<td align="center"><img src="https://img.shields.io/badge/Wizard%20Guild-6A1B9A?style=flat-square&logoColor=FFD700" height="28" alt="Guild"/><br/><strong>Wizard Guild</strong></td>
<td align="center"><img src="https://img.shields.io/badge/Resolve-222222?style=flat-square&logo=davinciresolve&logoColor=E74E3C" height="28" alt="Resolve"/><br/><strong>Resolve</strong></td>
<td>Build a Shotboard in the Guild, click <em>Send to Resolve</em>. Every queued shot renders + auto-imports into the timeline in the correct order. Gap-fill between two clips with LTX first-last-frame.</td>
</tr>

<tr>
<td align="center"><img src="https://img.shields.io/badge/Resolve-222222?style=flat-square&logo=davinciresolve&logoColor=E74E3C" height="28" alt="Resolve"/><br/><strong>Resolve</strong></td>
<td align="center"><img src="https://img.shields.io/badge/Wizard%20Guild-6A1B9A?style=flat-square&logoColor=FFD700" height="28" alt="Guild"/><br/><strong>Wizard Guild</strong></td>
<td>Drop the playhead on the timeline, type a prompt, get an 81-frame LTX-2 clip back in the Media Pool snapped to the playhead. Markers map to render profiles (red = high-effort, blue = turbo).</td>
</tr>

<tr>
<td align="center"><img src="https://img.shields.io/badge/Wizard%20Guild-6A1B9A?style=flat-square&logoColor=FFD700" height="28" alt="Guild"/><br/><strong>Wizard Guild</strong></td>
<td align="center"><img src="https://img.shields.io/badge/SillyTavern-6B7FD7?style=flat-square&logoColor=white" height="28" alt="SillyTavern"/><br/><strong>SillyTavern</strong></td>
<td>13 built-in Spellcaster wizard cards install themselves into SillyTavern on first launch. Sceneshifter generates backgrounds as your RP unfolds. Autonoma decides when a scene deserves an illustration. Portraitist paints mood-matched character art. All silent, all background.</td>
</tr>

<tr>
<td align="center"><img src="https://img.shields.io/badge/KoboldCpp-FF6B00?style=flat-square&logoColor=white" height="28" alt="Kobold"/><br/><strong>KoboldCpp</strong></td>
<td align="center"><img src="https://img.shields.io/badge/Wizard%20Guild-6A1B9A?style=flat-square&logoColor=FFD700" height="28" alt="Guild"/><br/><strong>Wizard Guild</strong></td>
<td>Pair one Kobold in RP mode (<code>kobold_rp</code> on :5001) and another in Whisper/TTS mode (<code>kobold_tts</code> on :5002). The Guild's 🎙 walkie-talkie uses the TTS/STT one; SillyTavern keeps chatting through the RP one. No conflict.</td>
</tr>

<tr>
<td align="center"><img src="https://img.shields.io/badge/Darktable-1F1F1F?style=flat-square&logo=darktable&logoColor=FF7A21" height="28" alt="Darktable"/><br/><strong>Darktable</strong></td>
<td align="center"><img src="https://img.shields.io/badge/Wizard%20Guild-6A1B9A?style=flat-square&logoColor=FFD700" height="28" alt="Guild"/><br/><strong>Wizard Guild</strong></td>
<td>Darktable's export filter pushes the developed RAW into the Guild gallery with its full develop history preserved. Send it to the next wizard for upscaling, face restoration, or a cinematic colour pass — no manual export-import dance.</td>
</tr>

<tr>
<td align="center"><img src="https://img.shields.io/badge/Resolve-222222?style=flat-square&logo=davinciresolve&logoColor=E74E3C" height="28" alt="Resolve"/><br/><strong>Resolve</strong></td>
<td align="center"><img src="https://img.shields.io/badge/GIMP-5C5543?style=flat-square&logo=gimp&logoColor=white" height="28" alt="GIMP"/><br/><strong>GIMP</strong></td>
<td>Grab a frame out of Resolve, drop it into GIMP. The Cinematographer wizard reads the timeline context (surrounding clips, markers, grade) so the returned edit matches the cut it came from.</td>
</tr>

</table>

Everything above rides the same three primitives under [`comfyui-spellcaster/spellcaster_core/`](comfyui-spellcaster/spellcaster_core/) — the **event bus** (`event_bus.py`), the **asset gallery** (`asset_gallery.py`), and the **interface registry** (`interface_registry.py`). Adding a new plugin means declaring its capabilities once; every cross-app flow listed above works for it immediately without per-plugin glue code.

---

## 🔀 Cross-interface backbone — every surface is the same surface

Six user-visible interfaces (GIMP, Darktable, Resolve Bridge, SillyTavern, the Wizard Guild web UI, the remote Antenna) all speak the same backbone. When a shot renders in one, every other surface sees it.

Four components in [comfyui-spellcaster/spellcaster_core/](comfyui-spellcaster/spellcaster_core/):

- **`asset_gallery.py` — canonical blob store.** Every generated image or video is stored by content-hash under `tavern/creations/gallery/blobs/<xx>/<hash>.png` with a metadata row (prompt, seed, model, arch, kind, tags, origin, timestamps) written atomically to `index.json`. No matter which surface generates, the bytes land here once and exactly once. Deduplication is free — two identical generations share one blob.
- **`event_bus.py` — publish/subscribe.** Every generation publishes `<origin>.asset.created` with the asset hash. The Resolve Bridge listens for `gimp.asset.created` and auto-imports into the Media Pool. The Guild gallery listens for `resolve.asset.created` and surfaces the new clip under "Recent across apps". Signal Bridge subscribes to any origin and pushes notifications to the user's phone. No polling.
- **`interface_registry.py` — presence + capabilities.** Each surface heartbeats every 10s with `{enabled, online, last_meta, capabilities, origin}`. The sidebar "Connected apps" chip row reads this registry — local chips render green, remote (antenna-backed) chips render in a teal-green gradient with a 📡 prefix + purple dot halo. Disconnected services just stop appearing as chips; no sad-dot spam.
- **`mailbox.py` + `cross_interface.py` — directed delivery.** A wizard in the Guild can say "send this portrait to GIMP" and the image lands as a new GIMP layer the next time the plugin polls its inbox (HTTP long-poll, < 2s typical latency).

All of this travels through **one** canonical URL shape: `/api/assets/<hash>`. Plugins that stored flat paths against pre-refactor ComfyUI `/view?filename=…` URLs still work via the `/api/cached_asset/<name>` compat shim, but every new path produces only the canonical shape.

## 🧠 Prompt enhancement — per-architecture, per-method, per-model

Every "Enhance prompt" click (automatic on most tools, manual on others) routes through a three-layer LLM rewrite so the raw prompt the user typed becomes the exact flavour the target model was trained on.

- **Per-architecture profile** (`_ARCH_ENHANCE_PROFILES` in [prompt_enhance.py](comfyui-spellcaster/spellcaster_core/prompt_enhance.py)) — 9 architectures each with their own `max_tokens`, target `length`, `style`, and guidance notes. SDXL gets booru-style comma-separated tags (≤256 tokens). Flux 1 Dev and LTX Video get verbose natural-language paragraphs (512–768 tokens). Klein gets concise bullet-style descriptions with subject preservation. Illustrious gets a "SUBJECT PRESERVATION" block that stops it from inventing extra characters when the user asks for a single subject.
- **Per-method profile** (`_METHOD_PROFILES`) — 41+ method-level overrides. `refine`, `detailed_visual`, `colorize`, `iclight`, `face_detail`, etc. Each method extends the arch baseline with `extra_notes`, `length_override`, or `max_tokens`. A `skip` flag suppresses enhancement for methods where the raw prompt is already optimal (edit-by-instruction, ZIT). Methods inherit from parents up to 5 levels deep so groups stay DRY.
- **Per-family VRAM management** (`_PER_FAMILY_LLM_CONFIG` in [comfyui_llm.py](comfyui-spellcaster/spellcaster_core/comfyui_llm.py)) — `keep_model_loaded`, `keep_last_prompt`, `max_quant_bits`, `max_model_size_b`, `poll_timeout_s` all tuned per diffusion family. SD 1.5 runs with `keep_last_prompt=False` after the cross-prompt cache-bleed incident (iclight was returning colorize output); Flux 2 Klein keeps the LLM loaded between calls because its sampler is slow enough to mask the reload cost.
- **Per-model overrides** — `~/.spellcaster/llm_prompt_settings.json` stores optimal settings per checkpoint as the user fine-tunes them. Atomic writes via `tempfile + os.replace` so a crash mid-save can't corrupt the file.
- **Per-method AILab preset** (`_METHOD_PRESET` in [comfyui_llm.py](comfyui-spellcaster/spellcaster_core/comfyui_llm.py)) — KoboldCpp's AILab QwenVL GGUF enhancer node has a `preset_system_prompt` dropdown (*Refine*, *Detailed Visual*, *Enhance*, etc.). Each enhance method picks the right one so the node's internal system prompt matches the arch's guidance.

The chain routing is dynamic: `purpose='chat'` prefers Ollama → ComfyUI → Kobold (Ollama speaks conversation natively), `purpose='enhance'` prefers ComfyUI → Ollama → Kobold (ComfyUI's AILab is purpose-built for image prompts). A sidebar pill picker pins the primary backend; the others stay as live fallbacks.

## 🎯 LLM primary picker — ComfyUI reroute, Ollama / Kobold auto-start

Three pills under the Guild title. Clicking one pins that backend as the first hop in `guild_llm.chat()`'s chain and, if necessary, spins up the matching service via `/api/app_control/start`. The other backends stay alive.

- **🎨 ComfyUI** — pure reroute. No service starts; ComfyUI's embedded LLM is reachable whenever ComfyUI is online.
- **🦙 Ollama** — auto-starts the local Ollama daemon if it isn't running. Auto-detects the best installed model (`qwen3:4b` > `gemma3:4b` > `llama3.2:3b` > … in [guild_llm.py](comfyui-spellcaster/spellcaster_core/guild_llm.py)'s `_OLLAMA_MODEL_PREFERENCE`).
- **📜 Kobold (RP)** — auto-starts the dedicated `kobold_rp` service on port 5001.

Running three LLMs at once is fine and useful — SillyTavern keeps talking to Kobold-RP while the Guild uses ComfyUI for image prompts and Ollama for install scaffolding. The picker just decides who answers **chat()** first. The active pill lights up in a purple→gold gradient; state is stored server-side in `guild_config.user_settings.preferred_llm` so it survives browser clears, private-window sessions, and cross-device sync.

## 🛠 Scaffold system — state-machine wizards for 7B models

[scaffold/](scaffold/) contains every conversational flow the Wizard Guild exposes. These are explicit state machines — not free-form LLM chat — because a 4–7B model running locally can't reliably plan multi-step installs, calibration sweeps, or video pipelines on its own.

- **`spellcaster_wizard.py`** — the install manager. Owns `/api/spellcaster/*` endpoints: feature install/uninstall quotes (GB cost + # of unlocked methods), antenna setup, per-feature smoke tests, plugin install/uninstall (GIMP / Darktable / Resolve), custom build flows. Emits `<ACTION>{...}</ACTION>` JSON blocks that the Guild's frontend parses and dispatches.
- **`meta_wizard.py`** — interprets plain-English intent and routes to the right sub-wizard. "Make it cinematic" → cinematographer. "Fix the hands" → hand-fix LoRA suggestion. "Turn this into a video" → video wizard.
- **`video_wizard.py`** + **`shotboard.py`** — persistent multi-shot video production. Each shot tracks its own motion trajectory, prompt, model, status (draft → queued → running → ready). Shots chain for continuity (last frame of shot 1 seeds shot 2); batch queue renders overnight and RIFE/GIMM-VFI stitches them.
- **`scaffold_calibration.py`** — optometrist-style A/B sweeps. Shows two outputs with different samplers/CFG/denoise, asks "A or B?", repeats; the winning settings propagate to every other checkpoint of the same arch.
- **`lora_calibration.py`** — real-test LoRA verification. For each LoRA: load it onto one checkpoint per installed arch, actually render a sample, record where it works vs where it errors. Trigger words come from the safetensors metadata directly, not the LLM. No more "Wan video LoRA showing up on SDXL wizards".
- **`lora_grouping.py`** — purpose-aware LoRA shootout. Classifies LoRAs into 20+ purpose groups (`skin_detail`, `style_photoreal`, etc.), runs a multi-sample render with subject-specific prompts (portrait / fullbody / macro / animal), lets the user approve many LoRAs with user-supplied keywords so the Guild auto-proposes the right one when the keyword appears in a chat prompt. Auto-fallback tries up to 3 different checkpoints of the same arch on generation failure — a single broken NoobAI-anime SDXL doesn't kill the row anymore.
- **`cue_seeder.py`**, **`issue_cue.py`**, **`frame_extract.py`**, **`network_survey.py`** — cue-sheet pipeline for storyboarded work, install-plan survey, and the lead-question "where does each service live on your network?" flow the Spellcaster runs on first launch.

Every scaffold is a Python state class that writes to `tavern/.guild_state/` (atomic tempfile + `os.replace` + `fsync` on every write) so interrupted flows resume cleanly.

## ⚡ Global preset cycle — Turbo / Standard / Quality

A small pill above the chat input cycles through three generation presets on each click:

- **⚡ Turbo** — fastest. Architecture-specific turbo LoRAs auto-injected (Hyper-FLUX.1-dev-8steps at 0.125 strength, LightX2V on video). Step counts cut by 2–3×. CFG stays honest. Expect ~30% quality dip in exchange for 3–5× speedup.
- **⚖️ Standard** — the calibrated defaults. What the Calibration Wizard landed on. Balanced.
- **💎 Quality** — max-effort path. Klein enhancer chain, higher step counts, no turbo LoRAs, full CFG.

The label + colour shifts with the state. Value persists to both `localStorage.guild_preset` AND `guild_config.user_settings.guild_preset` (via `/api/user_settings`), then gets published on `window.generationPreset` + a `guildpresetchange` CustomEvent so downstream action builders can opt in with a single listener.

## 📡 Antenna — 15+ endpoints, tray menu, self-update

The [antenna/](antenna/) module is a single-process stdlib HTTPS server that wraps one remote box with the following capabilities:

- **`/service/start` + `/service/stop` + `/service/register`** — orchestrate ComfyUI, KoboldCpp, Ollama on this box. `/service/register` persists launcher paths so future starts don't need one-shot overrides. Generic over: ComfyUI, Kobold (RP / TTS-STT), Ollama, plus path registration for GIMP, Darktable, Resolve, SillyTavern, Signal.
- **`/llm/install` + `/llm/status`** — Guild-driven install of a local LLM on a remote ComfyUI host the user can't SSH into.
- **`/comfyui/node-catalog`** — scans installed custom-node packs + returns a capability map.
- **`/resolve/luts`** — enumerates DaVinci Resolve LUTs on this box for the cross-app LUT picker.
- **`/self-update`** — `git pull` + rebuild + restart. POST with `{"force": true}` to restart even when there's no code change (useful after config edits).
- **`/pair/claim` + `/pair/state` + `/pair/start`** — 6-digit pair-code handshake. The antenna tray shows a code, the user types it into the Guild sidebar, the Guild exchanges the code for a 43-char bearer token. Constant-time comparison, single-use, 5-minute TTL.
- **`/telemetry`** — VRAM, CPU, disk, rate-limiter state. Fed into chip tooltips.
- **Heartbeats** — posts to Guild `/api/interfaces/heartbeat` every 10s so the sidebar chip stays green / stale / idle.

The **system-tray icon** (pystray + PIL, Windows only) exposes the same operations as a native right-click menu: per-service Start/Stop, View recent log, Pair with Guild (live countdown on the code), Check for antenna update, Setup Signal bridge, Reinstall Desktop + Start Menu icons, Enable/Disable run-at-Windows-startup, Open antenna folder, Quit antenna. Console-mode fallback when pystray isn't installed.

The tray installer lives at [`antenna/install_shortcuts.py`](antenna/install_shortcuts.py) — stdlib-only, shells out to PowerShell's `WScript.Shell` COM object to create `.lnk` files. The generated antenna.bat runs it once on first launch gated by a sentinel at `%USERPROFILE%\.spellcaster\antenna_shortcuts_done`.

## 🎙 Voice — walkie-talkie STT + TTS playback

A mic-button between the chat textarea and the summon-wand. Press-and-hold starts MediaRecorder capture (webm/opus); release uploads the base64 blob to `/api/stt`, which forwards to a registered **Kobold · TTS** backend running KoboldCpp in Whisper mode (`/api/extra/transcribe`). The transcript lands in the chat textarea so the user can edit before sending. Pointer-events cover both mouse and touch; the button pulses red while recording.

Symmetric `/api/tts` forwards text → audio via `/api/extra/generate_audio` so the Guild can read wizard replies aloud. Backend discovery via `_resolve_stt_backend_url()`: checks `guild_config.app_control.kobold_tts` (local) first, then falls back to any paired antenna advertising `kobold_tts`. Kobold in TTS/STT mode runs on port 5002 by convention; RP mode stays on 5001. Both modes coexist on the same box as separate services.

Registering a Kobold TTS backend: right-click any antenna chip → *Connect an app* → **Kobold**, type the launcher path + add `--whisper <model.gguf>` args. Guild tray → *Connect an app* for the local flow.

## 🧩 Connect-an-app — register launchers, Windows shortcuts, auto-start

Right-click any antenna chip (or open the Guild tray → *Connect an app…*) to pick one of eight app types — ComfyUI, Ollama, KoboldCpp, GIMP, Darktable, Resolve, SillyTavern, Signal Bridge — and type the launcher path on that machine. The Guild proxies the registration to the antenna's `/service/register` endpoint; the antenna persists it into `~/.spellcaster/antenna_config.json` (atomic tempfile + replace) under both the nested `services` map and the flat `<name>_launcher` keys so `service_launcher`'s override chain finds it either way.

Each chip also carries two tiny toggles on the left:
- **⚡ Start** — launches the app now on its configured target (local subprocess or remote via the antenna).
- **🔁 Auto-start** — persists "launch on Guild boot / auto-close on Guild exit" to `guild_config.app_control`. Toggled apps auto-start via the boot auto-launch loop in [guild_launcher.py](tavern/guild_launcher.py); `/api/guild/exit` iterates the same matrix on shutdown so nothing orphans.

The **Restart Server** button in Settings does a graceful restart: stops every `auto_start` app on its target, spawns a detached relauncher that sleeps 1.2s then re-execs the current argv, then `os._exit(0)`s the old process. The client polls `/api/comfy_status` until the new process responds, then reloads the page — so a full cycle takes about 3s.

## 🔐 Privacy, boot safety, auto-update risk

- **Privacy cleanup** ([privacy.py](comfyui-spellcaster/spellcaster_core/privacy.py)) — every temporary file on the ComfyUI server is atomically overwritten with a 1×1 pixel PNG then deleted after use. Your images don't linger. Configurable TTL.
- **Crash-safe boot shim** — the GIMP plugin is split into a 228-line immutable loader ([comfyui-connector.py](plugins/gimp/comfyui-connector/comfyui-connector.py)) + the 22K-line main plugin. The shim has 3-tier recovery: local backup → GitHub download → visible "CRASHED" menu entry. The auto-updater has the shim in its protected set — it will never overwrite or delete the loader.
- **Auto-update risk** — three separate auto-updaters run on launch (Wizard Guild, GIMP plugin, installer bootstrap). They download from GitHub and prune local files that aren't in the remote. CLAUDE.md rule 13 documents what each one clobbers and the safe-restart order (commit + push → restart is always safe).
- **Preflight validation** ([preflight.py](comfyui-spellcaster/spellcaster_core/preflight.py)) — every workflow is checked and patched before submission. Missing nodes get substituted, unsupported architectures get fallbacks. A user with a stale ComfyUI custom-node set still gets a working generation instead of a red error.
- **Atomic persistence, everywhere** — `guild_config.json`, `network_survey.json`, `generated_assets.json`, `wizard_identities.json`, `lora_registry.json`, `llm_prompt_settings.json`, `antenna_config.json`. All write via `tempfile` → `fsync` → `os.replace` so a power-cut mid-save leaves you with either the old version or the new, never half.

## 🎬 Resolve Bridge — timeline-aware shot generation

The Resolve plugin in [plugins/resolve/](plugins/resolve/) adds a Spellcaster menu to DaVinci Resolve 20+:

- **Generate from playhead** — drop the cursor on the timeline, type a prompt, get an 81-frame LTX-2 clip back in the Media Pool snapped to the playhead.
- **Smart gap fill** — place two clips with a gap between them; Spellcaster reads the last frame of clip A + the first frame of clip B and renders an LTX-2 "first-last frame" transition that fills the gap.
- **Markers to shots** — Resolve marker colours map to Spellcaster render profiles (red = high-effort, blue = turbo, etc.); batch-render every marker at once.
- **Send to Resolve** — any image anywhere (GIMP, Guild gallery, Darktable) can be pushed into the Resolve Media Pool with one click via the event bus.

The actual Resolve automation runs in a Python script in Resolve's scripting engine; the Guild-side trigger reaches it via the antenna's `/resolve/*` endpoints when Resolve lives on a different box.

## 🖼️ Everything else worth mentioning

- **9-architecture `ArchConfig` registry** ([architectures.py](comfyui-spellcaster/spellcaster_core/architectures.py)) — every arch declares its loader (checkpoint / unet_clip_vae / etc.), sampler, CFG, denoise, resolution, supports-negative flag, prompt style, LoRA prefixes, ControlNet model, turbo config, CLIP+VAE filenames, quality positive/negative tails, autoset LoRA lists per method. One object drives every builder.
- **`NodeFactory` DSL** ([node_factory.py](comfyui-spellcaster/spellcaster_core/node_factory.py)) — every ComfyUI node type is a typed Python method call. Zero raw dicts. Refactors ripple through every workflow without string-editing JSON.
- **Composites** ([composites.py](comfyui-spellcaster/spellcaster_core/composites.py)) — multi-node helpers that compose into a canonical shape: `load_model_stack`, `inject_lora_chain`, `encode_prompts`, `build_klein_enhancer_chain`, etc. Every builder that wants these behaviours gets them by calling the composite; there is no parallel implementation anywhere.
- **Model detect** ([model_detect.py](comfyui-spellcaster/spellcaster_core/model_detect.py)) — maps filename → architecture + family. Handles SD1.5 vs SDXL vs Illustrious vs Pony vs Flux Dev vs Klein vs Kontext vs Chroma vs LTX vs Wan. Extensive test matrix for adversarial filenames (`wan_mixl` shouldn't match "xl" before "wan").
- **Network survey** ([network_survey.py](scaffold/network_survey.py)) — first-time install asks "where does ComfyUI live? Local / LAN / skip / not installed?" for every tracked service. Persists to `.guild_state/network_survey.json` and drives the chip renderer's local vs remote origin hint.
- **Character-hover portrait** — 220px circular preview near the cursor whenever you mouse over a chat avatar. Pointer-events:none so it never steals a click. Delegated listener on `#chat-stream` so dynamically-added avatars pick up the behaviour with zero per-message wiring.
- **Recent-across-apps strip** — sidebar row showing the last N generated assets from **every** origin (GIMP / Resolve / Guild / …). Click a thumbnail → the image drops into the active wizard's chat as a reference. Scrollbar aligns with the character-list scrollbar exactly (both 4px purple thumb on transparent track).

---

## For developers

If you're reading this section voluntarily, you're either evaluating this for a pull request or you're the kind of person who reads disassembly for fun. Either way: welcome. You will find no clean abstractions here. Only 22,000 lines of Python that somehow work, a node factory that generates ComfyUI workflows like a possessed printer, and a boot shim so paranoid it has three backup plans for its backup plan. Godspeed.

- **9 model architectures**: SD 1.5, SDXL, Illustrious/Pony, ZIT, Flux Dev, Flux 2 Klein (4B/9B), Flux Kontext, Chroma, LTX, Wan — each with full `ArchConfig` (loader, sampler, CFG, denoise, resolution, prompt style, LoRA prefixes, ControlNet support, turbo config)
- **NodeFactory DSL** — every ComfyUI node type is a typed method call. No raw dicts.
- **Crash-safe boot shim** — 228-line immutable loader + 3-tier recovery (backup → GitHub → visible error). GIMP never bricks.
- **Scaffold system** — LLM state machines (`scaffold/`) that guide users conversationally. Meta Wizard → sub-wizards → build functions. Designed for 7B models.
- **Calibration engine** — headless A/B comparison generator + compatibility matrix. UI-agnostic (works in GIMP dialogs and Guild chat).
- **Preflight validation** — every workflow is checked and patched before submission. Missing nodes get substituted, unsupported architectures get fallbacks.
- **Privacy module** — atomic temp file cleanup on ComfyUI server (1x1 pixel overwrite + delete).
- **PDB procedures** — every tool callable from Script-Fu or Python-Fu
- **Workflow Library** — import any ComfyUI workflow JSON and run it from GIMP
- **`spellcaster_core/`** — single source of truth, shared across 4 repos. Auto-updater downloads from canonical source.
- **Cross-interface backbone** — event bus, mailbox, asset gallery, and dynamic presence. Every surface (GIMP / Resolve / Darktable / SillyTavern / Guild) can publish and consume events: a shot rendered in the Guild auto-imports into Resolve's Media Pool; an image saved from GIMP auto-appears in the Guild gallery. The **Antenna** (remote HTTPS agent) extends the same presence/auth model across machines.
- **7 plugin surfaces** in `plugins/`: `gimp` (mature, 61 files), `resolve`, `darktable`, `sillytavern` (real integrations), `blender`, `krita`, `photoshop` (minimal / experimental).

---

Back to the [main README](README.md).
