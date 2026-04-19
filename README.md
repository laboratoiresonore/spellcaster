<p align="center">
  <img src="assets/wizard_banner.gif" alt="Spellcaster" width="600" />
</p>

<h1 align="center">Spellcaster</h1>

<p align="center">
  <strong>Dynamic middleware between ComfyUI and everything else,<br/>hellbent on removing every bit of difficulty out of AI generation.</strong><br/>
  <em>69 AI tools (nice) &bull; GIMP &bull; DaVinci Resolve &bull; Darktable &bull; Chat UI &bull; 100% Local &bull; Zero Config</em>
</p>

<p align="center">
  <a href="https://github.com/laboratoiresonore/spellcaster/releases"><img alt="Releases" src="https://img.shields.io/github/v/release/laboratoiresonore/spellcaster?color=7c3aed&label=latest&style=for-the-badge"/></a>
  &nbsp;
  <a href="LICENSE"><img alt="License" src="https://img.shields.io/badge/license-GPL--2.0-7c3aed?style=for-the-badge"/></a>
  &nbsp;
  <img alt="Platform" src="https://img.shields.io/badge/Windows%20%7C%20macOS%20%7C%20Linux-7c3aed?style=for-the-badge&logo=windows&logoColor=white"/>
</p>

<p align="center">
  <a href="https://github.com/laboratoiresonore/spellcaster/stargazers"><img alt="Stars" src="https://img.shields.io/github/stars/laboratoiresonore/spellcaster?style=flat&color=7c3aed"/></a>
  <a href="https://github.com/laboratoiresonore/spellcaster/issues"><img alt="Issues" src="https://img.shields.io/github/issues/laboratoiresonore/spellcaster?color=7c3aed"/></a>
  <a href="https://github.com/laboratoiresonore/spellcaster/commits/main"><img alt="Last commit" src="https://img.shields.io/github/last-commit/laboratoiresonore/spellcaster?color=7c3aed"/></a>
  <a href="https://github.com/laboratoiresonore/spellcaster/releases/latest"><img alt="Downloads" src="https://img.shields.io/github/downloads/laboratoiresonore/spellcaster/total?color=7c3aed"/></a>
  <a href="DEPENDENCIES.md"><img alt="ComfyUI deps" src="https://img.shields.io/badge/ComfyUI%20node%20packs-24-5b8def"/></a>
</p>

<p align="center">
  <a href="#the-problem">The Problem</a> &bull;
  <a href="#the-solution">The Solution</a> &bull;
  <a href="#see-it-in-action-generate--select--map--enhance">See It</a> &bull;
  <a href="#install">Install</a> &bull;
  <a href="#the-antenna--your-other-machines-one-click-away">Antenna</a> &bull;
  <a href="#all-69-tools">All Tools</a> &bull;
  <a href="#deep-dives--every-system-all-the-details">Deep Dives</a> &bull;
  <a href="DEPENDENCIES.md">Dependencies</a> &bull;
  <a href="#faq">FAQ</a> &bull;
  <a href="https://www.reddit.com/r/Spellcaster_Studio/">Reddit</a>
</p>

<p align="center"><em>"Everyone with even a minor self respect would hate on this."</em> — u/chris020891, r/GIMP</p>

---

## The Problem

Experimenting with AI image generation locally is a huge pain in the ass, even for people who are good with computers.

[ComfyUI](https://github.com/comfyanonymous/ComfyUI) is a phenomenal tool — it can do anything — but it takes weeks to wrap your mind around nodes, workflows, model architectures, samplers, schedulers, LoRAs, VAEs, ControlNets, and the dozens of custom node packs you need for each task. You end up spending more time wiring nodes than creating images.

Meanwhile, GIMP is already an ultra-capable image editor with an intuitive interface, a canvas, layers, masks, selections, and transparency. It's the free Photoshop. But it has zero AI capabilities.

<p align="center"><em>"No, I use GIMP because I don't want to make AI slop."</em> — u/Ill_Morning_4282, r/GIMP (130 upvotes)</p>

<p align="center">Cool. This is for everyone else.</p>

## The Solution

**Spellcaster is dynamic middleware that sits between ComfyUI and any interface you want to use.** It absorbs all the complexity — models, nodes, samplers, schedulers, LoRAs, VAEs, ControlNets — and exposes it as simple menu items and one-click tools. Its entire purpose is to make ComfyUI's power accessible to people who have no interest in learning ComfyUI.

- **GIMP / Darktable** — 69 AI tools appear in your menus. Generate, edit, upscale, swap faces, remove backgrounds, create videos — all from the same editor you already know.
- **DaVinci Resolve** — Bridge plugin + shot-generation scripts. Drop a playhead, type a prompt, get a clip back in your Media Pool. Gap-fill between two clips with reference-aware rendering.
- **The Wizard Guild** — a standalone chat UI where AI wizard characters walk you through every tool conversationally. No GIMP needed.
- **SillyTavern** — 13 character cards that generate live visuals during roleplay.
- **Blender / Krita / Photoshop** — experimental minimal plugins; full parity planned.

You never touch ComfyUI. Spellcaster talks to it behind the scenes. Think of it like an engine under the hood — you just press the gas. With your eyes closed. Going 140 in a school zone. Spellcaster is the responsible adult in this relationship.

Every tool starts with expert-tuned presets that just work. But as you get comfortable, you can fine-tune every parameter, save your own presets, build custom workflows, and inject LoRAs — the training wheels come off whenever you're ready.

<table>
<tr>
<td width="25%"><img src="assets/demo_step1_inpaint.png" alt="Step 1" width="100%"/><br/><sub>1. Select what to fix</sub></td>
<td width="25%"><img src="assets/demo_step2_inpaint.png" alt="Step 2" width="100%"/><br/><sub>2. Pick a preset</sub></td>
<td width="25%"><img src="assets/demo_step3_inpaint.png" alt="Step 3" width="100%"/><br/><sub>3. Click Generate</sub></td>
<td width="25%"><img src="assets/demo_step4_inpaint.png" alt="Step 4" width="100%"/><br/><sub>4. Result on a new layer</sub></td>
</tr>
</table>

---

## State of the Art AI Generation, Fingers (Way) Up Your Nose

<table>
<tr>
<th align="left" width="40%">🔬 What's Actually Happening</th>
<th align="left" width="60%">👆👃 What You Actually Do</th>
</tr>
<tr><td>Flow-matching diffusion across 9 model architectures with architecture-aware CFG, denoise, sampler, and scheduler selection</td><td>Pick a preset. Click Generate.</td></tr>
<tr><td>SAM3 zero-shot segmentation with Florence 2 grounding + DepthAnything V3 compositing</td><td>Type "hair." It selects the hair.</td></tr>
<tr><td>NormalCrafter 3D surface normal estimation for physically-based relighting</td><td>Click "3D Normal Map." Get a 3D map.</td></tr>
<tr><td>Multi-LoRA injection chains with per-architecture prefix routing and strength calibration</td><td>Pick a style from a dropdown.</td></tr>
<tr><td>CFGGuider + BasicScheduler pipeline with Flux 2 Klein Enhancer (RefLatentController, TextRefBalance, ColorAnchor)</td><td>Click "AI Editor."</td></tr>
<tr><td>IC-Light relighting with directional conditioning and HDR multiplier control</td><td>Pick "Golden Hour." Click Generate.</td></tr>
<tr><td>TeaCache acceleration + FBCache + WaveSpeed inference optimization (auto-injected)</td><td>You don't even know this is happening.</td></tr>
<tr><td>Local 4B LLM prompt enhancement with architecture-specific rewriting (booru tags vs natural language vs minimal)</td><td>Type "a cat."</td></tr>
<tr><td>ReActor face embedding + Klein refinement + face segmentation compositing pipeline</td><td>Upload a selfie. Click Swap.</td></tr>
<tr><td>Optometrist-style A/B preference calibration across 54 models with per-model parameter sweeps</td><td>"Which picture do you like better, A or B?"</td></tr>
</table>

---

## See It in Action: Generate → Select → Map → Enhance → Blend

A real pipeline — 5 clicks, zero configuration, every step is one menu item. We timed it. It takes longer to microwave a Hot Pocket. And unlike a Hot Pocket, the result doesn't make you question your life choices:

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

## For People Who Can't Computer

Listen. If you can order food on your phone, you can use this. If you once successfully connected a printer on the first try, you're overqualified. The entire thing is automated to a degree that borders on suspicious:

- **Installation?** Automated. The installer sniffs your GPU like a sommelier sniffs wine, figures out what AI models your hardware can swallow, downloads them, installs everything, creates shortcuts, and tucks you into bed. You click "Next" a few times. That's your contribution.
- **Settings?** Automated. Every tool has expert-tuned presets crafted by someone who spent way too long tweaking denoise values at 3 AM so you don't have to. Or run the **Calibration Wizard** — it shows you real images side by side and asks "which do you prefer?" Like an eye exam. Your preferences become the new defaults everywhere. You never configure a sampler, pick a scheduler, set a CFG scale, or write a negative prompt. You don't even know what those words mean. *Good.* Keep it that way.
- **Prompts?** Automated. Type "a cat" and a local AI rewrites it into a paragraph of optimized gibberish that the image model actually understands. It knows that SDXL wants tags, Flux wants poetry, and Klein wants bullet points. You just type "a cat."
- **Model selection?** Automated. The plugin detects what models are installed and picks the best one. You didn't even know you had models. You thought you just had a computer.
- **VRAM management?** Automated. Video resolution auto-scales to fit your GPU. The LLM politely unloads itself during image generation. TeaCache acceleration is silently injected into every workflow. If you don't know what any of that means — congratulations, that's the point.
- **Running ComfyUI on another machine?** Automated. The **Antenna** is a small HTTPS agent you install on the box that hosts ComfyUI. From then on, your laptop's GIMP plugin can install missing custom nodes, download new models, and self-update the stack on the remote machine — without you ever SSHing into it. Gaming PC in the closet, laptop on the couch, and they get along.
- **Updates?** Automated. The plugin checks GitHub on launch and silently patches itself. You will never be asked to "pull the latest commit." You don't know what a commit is and we respect that.
- **Recovery?** Automated. If an update corrupts the plugin, a 3-tier recovery system restores from backup, re-downloads from GitHub, or shows a visible error. GIMP never bricks. Your relationship with technology remains intact.

**You open GIMP. You go to the Spellcaster menu. You pick a tool. You click Generate. That's it. The AI does the rest. You take the credit.**

Too intimidated by GIMP? The [Wizard Guild](#under-the-hood) is a chat interface where you literally just tell an AI wizard what you want. In English. Like ordering at a restaurant, except the waiter is a magical entity running on your GPU and the food is photorealistic art.

---

## 69 Finely Tuned AI Tools, Each One Click Away

Yes, we counted. Yes, we noticed. No, we will not be adding a 70th (officially).

<table>
<tr>
<td align="center" width="25%"><img src="assets/showcase_seedv2r.png" alt="SeedV2R" width="100%"/><br/><sub><strong>SeedV2R Upscale</strong> — AI hallucinated detail</sub></td>
<td align="center" width="25%"><img src="assets/showcase_lama_remove.png" alt="Object Removal" width="100%"/><br/><sub><strong>AI Eraser</strong> — select & delete</sub></td>
<td align="center" width="25%"><img src="assets/showcase_rembg.png" alt="Remove BG" width="100%"/><br/><sub><strong>Remove Background</strong> — one click</sub></td>
<td align="center" width="25%"><img src="assets/showcase_colorize.png" alt="Colorize" width="100%"/><br/><sub><strong>Colorize</strong> — B&W to color (instant)</sub></td>
</tr>
<tr>
<td align="center" width="25%"><img src="assets/showcase_iclight_golden.png" alt="Relight" width="100%"/><br/><sub><strong>Relight</strong> — change lighting direction</sub></td>
<td align="center" width="25%"><img src="assets/showcase_style_transfer.png" alt="Style Transfer" width="100%"/><br/><sub><strong>Style Transfer</strong> — copy any style</sub></td>
<td align="center" width="25%"><img src="assets/sam3demo.png" alt="AI Select" width="100%"/><br/><sub><strong>AI Select</strong> — type what to select</sub></td>
<td align="center" width="25%"><img src="assets/showcase_wan_breathing.gif" alt="Video Gen" width="100%"/><br/><sub><strong>Video Generation</strong> — Wan 2.2 I2V</sub></td>
</tr>
<tr>
<td align="center" width="25%"><img src="assets/showcase_inpaint_chrome.png" alt="Inpaint" width="100%"/><br/><sub><strong>Txt 2 Img</strong> — generate new images</sub></td>
<td align="center" width="25%"><img src="assets/showcase_supir.png" alt="SUPIR" width="100%"/><br/><sub><strong>AI Restoration</strong> — fix old photos</sub></td>
<td align="center" width="25%"><img src="assets/showcase_detail_hallucinate.png" alt="Detail" width="100%"/><br/><sub><strong>Detail Hallucination</strong> — add texture</sub></td>
<td align="center" width="25%"><img src="assets/showcase_normal_map.png" alt="3D Normal Map" width="100%"/><br/><sub><strong>3D Normal Map</strong> — surface geometry</sub></td>
</tr>
</table>


---

## Install

### What You Need

| You need | What it is | Where to get it |
|---|---|---|
| **ComfyUI** | The AI engine (runs in background) | [github.com/comfyanonymous/ComfyUI](https://github.com/comfyanonymous/ComfyUI) |
| **GIMP 3** | Free image editor (like Photoshop) | [gimp.org](https://www.gimp.org/downloads/) |
| **A GPU with 4+ GB VRAM** | Runs the AI models | You probably already have one |

> **Never heard of ComfyUI?** That's fine. You'll never need to open it. Spellcaster talks to it behind the scenes.
>
> **Don't have a GPU?** The installer's **Antenna mode** connects to a ComfyUI server on another computer on your network.

<p align="center"><em>"No one fucking uses GIMP to make AI slop"</em> — u/Capable_Basket1661, r/GIMP (50 upvotes)</p>

<p align="center">Tell that to the 69 tools in the menu, bestie.</p>

### Download & Run

<p align="center">
  <a href="https://github.com/laboratoiresonore/spellcaster/releases/latest/download/spellcaster-installer.exe">
    <img src="https://img.shields.io/badge/Windows-spellcaster--installer.exe-7c3aed?style=for-the-badge&logo=windows&logoColor=white" alt="Download for Windows"/>
  </a>
  &nbsp;
  <a href="https://github.com/laboratoiresonore/spellcaster/releases/latest/download/spellcaster-installer-macos.zip">
    <img src="https://img.shields.io/badge/macOS-Spellcaster%20Installer.app-7c3aed?style=for-the-badge&logo=apple&logoColor=white" alt="Download for macOS"/>
  </a>
  &nbsp;
  <a href="https://github.com/laboratoiresonore/spellcaster/releases/latest/download/spellcaster-installer">
    <img src="https://img.shields.io/badge/Linux-spellcaster--installer-7c3aed?style=for-the-badge&logo=linux&logoColor=white" alt="Download for Linux"/>
  </a>
</p>

1. **Download** the installer for your system
2. **Run it.** It walks you through everything — detects your GPU, downloads models, installs plugins
3. **Open GIMP.** Go to `Filters > Spellcaster` — all 69 AI tools are there
4. **Pick any tool and click Generate.** Every preset is already optimized

> **From source:** `git clone https://github.com/laboratoiresonore/spellcaster && cd spellcaster && python installer/install.py`

### The Antenna — your other machines, one click away

The **Antenna** is the small always-on bridge that lets a Spellcaster running on your laptop drive ComfyUI, KoboldCpp, Ollama, DaVinci Resolve, Darktable, GIMP, or SillyTavern on **another PC** on your LAN. Gaming tower in the closet does the work; the laptop on the couch sends the prompts. Pair once, forget forever.

<p align="center">
  <a href="https://github.com/laboratoiresonore/spellcaster/releases/latest/download/spellcaster-antenna-windows.exe">
    <img src="https://img.shields.io/badge/Windows-spellcaster--antenna.exe-2ed573?style=for-the-badge&logo=windows&logoColor=white" alt="Download compiled antenna (Windows)"/>
  </a>
  &nbsp;
  <a href="https://raw.githubusercontent.com/laboratoiresonore/spellcaster/main/installer/install_antenna.sh">
    <img src="https://img.shields.io/badge/macOS-install__antenna.sh-2ed573?style=for-the-badge&logo=apple&logoColor=white" alt="Antenna installer (macOS)"/>
  </a>
  &nbsp;
  <a href="https://raw.githubusercontent.com/laboratoiresonore/spellcaster/main/installer/install_antenna.sh">
    <img src="https://img.shields.io/badge/GNU%2FLinux-install__antenna.sh-2ed573?style=for-the-badge&logo=linux&logoColor=white" alt="Antenna installer (Linux)"/>
  </a>
</p>

**Windows:** download the ~140&nbsp;MB compiled binary from the latest release, double-click. No Python required. First launch offers to create a desktop icon, a Start Menu entry, and / or launch at login. Tray icon appears; right-click → *Pair with Guild…* → type the 6-digit code into your Guild sidebar.

**macOS / GNU/Linux:** `curl -LO <link>` and `chmod +x install_antenna.sh && ./install_antenna.sh`. The shell installer checks for Python 3.10+, clones the repo, installs tray deps, and runs the antenna. Tray works on macOS out of the box; Linux falls back to console mode without AppIndicator.

> Prefer the source path on Windows too? The Python installer ([install_antenna.bat](https://raw.githubusercontent.com/laboratoiresonore/spellcaster/main/installer/install_antenna.bat)) still works — double-click it, same first-run shortcut flow as the .exe.

Under the hood the bootstrap clones this repo into `~/.spellcaster/repo`, best-effort `pip install`s `pystray` + `Pillow`, and runs `python -m antenna`. Everything is re-runnable — the installer is also the updater.

---

<p align="center"><em>"Ew, AI slop... and you didn't even code it yourself? lmao how ridiculous can you get"</em> — u/FentonTheIIV, r/GIMP</p>

<p align="center">Correct! 22,000 lines of Python, vibe-coded at 3 AM while arguing with an AI that kept setting Klein's CFG to 3.5. The <em>horror</em>.</p>

## All 69 Tools <!-- nice -->

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

<p align="center"><em>"No. Go away, sloperator!"</em> — u/chris020891, r/GIMP</p>

<p align="center">We can't leave. We live here now. We have 69 tools and a chat UI full of wizards. This is our home.</p>

---

## Under the Hood

This section is for people who read ingredients on cereal boxes. If you don't care how the sausage is made — and honestly, you shouldn't, it's horrifying in there — skip to the [FAQ](#faq).

<details>
<summary><strong>What makes it fast</strong></summary>

- **TeaCache auto-acceleration** — every image generation is automatically 1.4x faster. Zero config, zero quality loss. The optimizer injects it into all workflows.
- **Architecture-aware everything** — CFG, denoise, prompts, and ControlNet models are auto-configured per architecture. 9 supported: SD 1.5, SDXL, Illustrious/Pony, ZIT, Flux Dev, Flux 2 Klein, Flux Kontext, Chroma, and WAN/LTX for video.
- **AI Prompt Enhancement** — a local 4B LLM runs inside ComfyUI, rewrites your simple prompts into architecture-optimized descriptions. SDXL gets booru tags, Flux gets natural language, Klein gets concise descriptions. Multi-character prompts use BREAK separation with attention weights.
- **VRAM management** — LLM auto-unloads during image generation. LTX resolution auto-scales to fit your GPU. Video frame counts auto-cap on low VRAM.
- **Privacy cleanup** — all temporary files on ComfyUI are atomically overwritten with 1x1 pixel PNGs after use. Your images don't linger on the server.

</details>

<details>
<summary><strong>Calibration Wizard — optometrist for your GPU</strong></summary>

First time using Spellcaster? The Calibration Wizard tests every installed model and tunes all settings to your taste — no technical knowledge required. It is, to our knowledge, the only software that treats your artistic preferences like a medical condition that needs diagnosing.

1. **Model Taste Test** — generates the same scene with every installed model. You rate each one: Love / OK / Dislike.
2. **Settings Calibration** — for your favorite models, shows A/B/C comparisons (CFG, steps, sampler). You pick the image you prefer. That's it.
3. **Apply** — your preferences become the default everywhere. Every dialog reads from your calibrated profile.

It's an eye exam, but for art. "Which is better — A or B?" Repeat until your defaults are perfect.

Access: `Spellcaster > Tools > Calibration Wizard`

</details>

<details>
<summary><strong>The Wizard Guild (chat interface)</strong></summary>

Don't want to learn GIMP? Look, we get it. GIMP has 847 menu items and a learning curve that doubles as a cliff face. The Wizard Guild is a standalone web UI where AI wizard characters handle everything conversationally. It's like tech support, except the tech support is a wizard, and instead of telling you to restart your computer, it generates a photorealistic dragon.

<img src="assets/wizardguild.png" alt="The Wizard Guild" width="80%"/>

Each wizard specializes in different tools. A local LLM runs natively inside ComfyUI — no separate server needed. Click action buttons to generate directly, or chat for guidance.

The **Travelling Wizard** bridges Spellcaster with external LLM apps — SillyTavern, OpenWebUI, LM Studio — through a scaffold system that routes your intent to the right tool. A **Meta Wizard** interprets what you want ("make it cinematic," "fix the hands," "turn this into a video") and dispatches to specialized sub-wizards for enhancement, generation, video, or pipeline orchestration.

Launch: `start_guild.bat` (Windows) or `python tavern/guild_launcher.py`

</details>

<details>
<summary><strong>Video Shotboard — you are now a film director, apparently</strong></summary>

The Shotboard is a persistent video production system for multi-shot sequences. At some point during development we stopped making a GIMP plugin and accidentally built a pre-production suite. We don't know when it happened. We're not apologizing. Each shot tracks its own motion trajectory, prompt, model, and status (draft → queued → running → ready). Shots link together for continuity — the last frame of shot 1 feeds into shot 2.

Build a full storyboard in the Guild UI, queue all shots, and let them render overnight. The assembly pipeline stitches them together with frame interpolation (RIFE/GIMM-VFI) for smooth transitions.

</details>

<details>
<summary><strong>SillyTavern integration — 13 AI wizard characters who live in your group chat and won't shut up</strong></summary>

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

</details>

<details>
<summary><strong>For developers — abandon hope, all ye who peek behind the curtain</strong></summary>

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

</details>

---

## Cross-App Functions

Spellcaster is the connective tissue. Every generated asset lives in one canonical store, every surface sees every other surface, and every action in one app can finish in another. Drop an image in GIMP, drop it into the Guild chat, drop it onto the Resolve timeline — same bytes, one hash, zero copies.

<p align="center">
  <a href="https://www.gimp.org/" title="GIMP — image editor"><img src="https://img.shields.io/badge/GIMP-5C5543?style=for-the-badge&logo=gimp&logoColor=white" height="48" alt="GIMP"/></a>
  &nbsp;
  <a href="#the-wizard-guild-chat-interface" title="The Wizard Guild — chat UI"><img src="https://img.shields.io/badge/Wizard%20Guild-6A1B9A?style=for-the-badge&logo=data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAyNCAyNCIgZmlsbD0iI0ZGRDcwMCI+PHBhdGggZD0iTTE4LjUgMUw5IDE4bC0yLjUtNUwxIDE4LjUgMyAyM2wxNS01IDYgMi41TDIxIDExbC0yLjUtMTB6Ii8%2BPC9zdmc%2B&logoColor=FFD700" height="48" alt="Wizard Guild"/></a>
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
<th width="18%" align="center">From</th>
<th width="18%" align="center">To</th>
<th>What it does</th>
</tr>

<tr>
<td align="center"><img src="https://img.shields.io/badge/GIMP-5C5543?style=flat-square&logo=gimp&logoColor=white" height="28" alt="GIMP"/><br/><strong>GIMP</strong></td>
<td align="center"><img src="https://img.shields.io/badge/Wizard%20Guild-6A1B9A?style=flat-square&logoColor=FFD700" height="28" alt="Guild"/><br/><strong>Wizard Guild</strong></td>
<td>Save any layer to the Guild gallery. It appears instantly under "Recent across apps" in the sidebar and drops into the active wizard's chat as a reference image on click. No upload step.</td>
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
<td>Pair one Kobold in RP mode (<code>kobold_rp</code> on :5001) and another in Whisper/TTS mode (<code>kobold_tts</code> on :5002). The Guild's 🎙️ walkie-talkie uses the TTS/STT one; SillyTavern keeps chatting through the RP one. No conflict.</td>
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

Everything above rides the same three primitives under [`comfyui-spellcaster/spellcaster_core/`](comfyui-spellcaster/spellcaster_core/) — the **event bus** (`event_bus.py`), the **asset gallery** (`asset_gallery.py`), and the **interface registry** (`interface_registry.py`). Adding a new plugin means declaring its capabilities once; every cross-app flow listed above works for it immediately without per-plugin glue code. See [🔀 Cross-interface backbone](#-cross-interface-backbone--every-surface-is-the-same-surface) for the mechanics.

---

## Deep Dives — every system, all the details

The sections below document the non-obvious subsystems that make Spellcaster more than a menu of ComfyUI shortcuts. Each one is opt-in reading — open the `<details>` you care about.

<details>
<summary><strong>🔀 Cross-interface backbone — every surface is the same surface</strong></summary>

Six user-visible interfaces (GIMP, Darktable, Resolve Bridge, SillyTavern, the Wizard Guild web UI, the remote Antenna) all speak the same backbone. When a shot renders in one, every other surface sees it.

Four components in [comfyui-spellcaster/spellcaster_core/](comfyui-spellcaster/spellcaster_core/):

- **`asset_gallery.py` — canonical blob store.** Every generated image or video is stored by content-hash under `tavern/creations/gallery/blobs/<xx>/<hash>.png` with a metadata row (prompt, seed, model, arch, kind, tags, origin, timestamps) written atomically to `index.json`. No matter which surface generates, the bytes land here once and exactly once. Deduplication is free — two identical generations share one blob.
- **`event_bus.py` — publish/subscribe.** Every generation publishes `<origin>.asset.created` with the asset hash. The Resolve Bridge listens for `gimp.asset.created` and auto-imports into the Media Pool. The Guild gallery listens for `resolve.asset.created` and surfaces the new clip under "Recent across apps". Signal Bridge subscribes to any origin and pushes notifications to the user's phone. No polling.
- **`interface_registry.py` — presence + capabilities.** Each surface heartbeats every 10s with `{enabled, online, last_meta, capabilities, origin}`. The sidebar "Connected apps" chip row reads this registry — local chips render green, remote (antenna-backed) chips render in a teal-green gradient with a 📡 prefix + purple dot halo. Disconnected services just stop appearing as chips; no sad-dot spam.
- **`mailbox.py` + `cross_interface.py` — directed delivery.** A wizard in the Guild can say "send this portrait to GIMP" and the image lands as a new GIMP layer the next time the plugin polls its inbox (HTTP long-poll, < 2s typical latency).

All of this travels through **one** canonical URL shape: `/api/assets/<hash>`. Plugins that stored flat paths against pre-refactor ComfyUI `/view?filename=…` URLs still work via the `/api/cached_asset/<name>` compat shim, but every new path produces only the canonical shape.

</details>

<details>
<summary><strong>🧠 Prompt enhancement — per-architecture, per-method, per-model</strong></summary>

Every "Enhance prompt" click (automatic on most tools, manual on others) routes through a three-layer LLM rewrite so the raw prompt the user typed becomes the exact flavour the target model was trained on.

- **Per-architecture profile** (`_ARCH_ENHANCE_PROFILES` in [prompt_enhance.py](comfyui-spellcaster/spellcaster_core/prompt_enhance.py)) — 9 architectures each with their own `max_tokens`, target `length`, `style`, and guidance notes. SDXL gets booru-style comma-separated tags (≤256 tokens). Flux 1 Dev and LTX Video get verbose natural-language paragraphs (512–768 tokens). Klein gets concise bullet-style descriptions with subject preservation. Illustrious gets a "SUBJECT PRESERVATION" block that stops it from inventing extra characters when the user asks for a single subject.
- **Per-method profile** (`_METHOD_PROFILES`) — 41+ method-level overrides. `refine`, `detailed_visual`, `colorize`, `iclight`, `face_detail`, etc. Each method extends the arch baseline with `extra_notes`, `length_override`, or `max_tokens`. A `skip` flag suppresses enhancement for methods where the raw prompt is already optimal (edit-by-instruction, ZIT). Methods inherit from parents up to 5 levels deep so groups stay DRY.
- **Per-family VRAM management** (`_PER_FAMILY_LLM_CONFIG` in [comfyui_llm.py](comfyui-spellcaster/spellcaster_core/comfyui_llm.py)) — `keep_model_loaded`, `keep_last_prompt`, `max_quant_bits`, `max_model_size_b`, `poll_timeout_s` all tuned per diffusion family. SD 1.5 runs with `keep_last_prompt=False` after the cross-prompt cache-bleed incident (iclight was returning colorize output); Flux 2 Klein keeps the LLM loaded between calls because its sampler is slow enough to mask the reload cost.
- **Per-model overrides** — `~/.spellcaster/llm_prompt_settings.json` stores optimal settings per checkpoint as the user fine-tunes them. Atomic writes via `tempfile + os.replace` so a crash mid-save can't corrupt the file.
- **Per-method AILab preset** (`_METHOD_PRESET` in [comfyui_llm.py](comfyui-spellcaster/spellcaster_core/comfyui_llm.py)) — KoboldCpp's AILab QwenVL GGUF enhancer node has a `preset_system_prompt` dropdown (*Refine*, *Detailed Visual*, *Enhance*, etc.). Each enhance method picks the right one so the node's internal system prompt matches the arch's guidance.

The chain routing is dynamic: `purpose='chat'` prefers Ollama → ComfyUI → Kobold (Ollama speaks conversation natively), `purpose='enhance'` prefers ComfyUI → Ollama → Kobold (ComfyUI's AILab is purpose-built for image prompts). A sidebar pill picker pins the primary backend; the others stay as live fallbacks.

</details>

<details>
<summary><strong>🎯 LLM primary picker — ComfyUI reroute, Ollama / Kobold auto-start</strong></summary>

Three pills under the Guild title. Clicking one pins that backend as the first hop in `guild_llm.chat()`'s chain and, if necessary, spins up the matching service via `/api/app_control/start`. The other backends stay alive.

- **🎨 ComfyUI** — pure reroute. No service starts; ComfyUI's embedded LLM is reachable whenever ComfyUI is online.
- **🦙 Ollama** — auto-starts the local Ollama daemon if it isn't running. Auto-detects the best installed model (`qwen3:4b` > `gemma3:4b` > `llama3.2:3b` > … in [guild_llm.py](comfyui-spellcaster/spellcaster_core/guild_llm.py)'s `_OLLAMA_MODEL_PREFERENCE`).
- **📜 Kobold (RP)** — auto-starts the dedicated `kobold_rp` service on port 5001.

Running three LLMs at once is fine and useful — SillyTavern keeps talking to Kobold-RP while the Guild uses ComfyUI for image prompts and Ollama for install scaffolding. The picker just decides who answers **chat()** first. The active pill lights up in a purple→gold gradient; state is stored server-side in `guild_config.user_settings.preferred_llm` so it survives browser clears, private-window sessions, and cross-device sync.

</details>

<details>
<summary><strong>🛠 Scaffold system — state-machine wizards for 7B models</strong></summary>

[scaffold/](scaffold/) contains every conversational flow the Wizard Guild exposes. These are explicit state machines — not free-form LLM chat — because a 4–7B model running locally can't reliably plan multi-step installs, calibration sweeps, or video pipelines on its own.

- **`spellcaster_wizard.py`** — the install manager. Owns `/api/spellcaster/*` endpoints: feature install/uninstall quotes (GB cost + # of unlocked methods), antenna setup, per-feature smoke tests, plugin install/uninstall (GIMP / Darktable / Resolve), custom build flows. Emits `<ACTION>{...}</ACTION>` JSON blocks that the Guild's frontend parses and dispatches.
- **`meta_wizard.py`** — interprets plain-English intent and routes to the right sub-wizard. "Make it cinematic" → cinematographer. "Fix the hands" → hand-fix LoRA suggestion. "Turn this into a video" → video wizard.
- **`video_wizard.py`** + **`shotboard.py`** — persistent multi-shot video production. Each shot tracks its own motion trajectory, prompt, model, status (draft → queued → running → ready). Shots chain for continuity (last frame of shot 1 seeds shot 2); batch queue renders overnight and RIFE/GIMM-VFI stitches them.
- **`scaffold_calibration.py`** — optometrist-style A/B sweeps. Shows two outputs with different samplers/CFG/denoise, asks "A or B?", repeats; the winning settings propagate to every other checkpoint of the same arch.
- **`lora_calibration.py`** — real-test LoRA verification. For each LoRA: load it onto one checkpoint per installed arch, actually render a sample, record where it works vs where it errors. Trigger words come from the safetensors metadata directly, not the LLM. No more "Wan video LoRA showing up on SDXL wizards".
- **`lora_grouping.py`** — purpose-aware LoRA shootout. Classifies LoRAs into 20+ purpose groups (`skin_detail`, `style_photoreal`, etc.), runs a multi-sample render with subject-specific prompts (portrait / fullbody / macro / animal), lets the user approve many LoRAs with user-supplied keywords so the Guild auto-proposes the right one when the keyword appears in a chat prompt. Auto-fallback tries up to 3 different checkpoints of the same arch on generation failure — a single broken NoobAI-anime SDXL doesn't kill the row anymore.
- **`cue_seeder.py`**, **`issue_cue.py`**, **`frame_extract.py`**, **`network_survey.py`** — cue-sheet pipeline for storyboarded work, install-plan survey, and the lead-question "where does each service live on your network?" flow the Spellcaster runs on first launch.

Every scaffold is a Python state class that writes to `tavern/.guild_state/` (atomic tempfile + `os.replace` + `fsync` on every write) so interrupted flows resume cleanly.

</details>

<details>
<summary><strong>⚡ Global preset cycle — Turbo / Standard / Quality</strong></summary>

A small pill above the chat input cycles through three generation presets on each click:

- **⚡ Turbo** — fastest. Architecture-specific turbo LoRAs auto-injected (Hyper-FLUX.1-dev-8steps at 0.125 strength, LightX2V on video). Step counts cut by 2–3×. CFG stays honest. Expect ~30% quality dip in exchange for 3–5× speedup.
- **⚖️ Standard** — the calibrated defaults. What the Calibration Wizard landed on. Balanced.
- **💎 Quality** — max-effort path. Klein enhancer chain, higher step counts, no turbo LoRAs, full CFG.

The label + colour shifts with the state. Value persists to both `localStorage.guild_preset` AND `guild_config.user_settings.guild_preset` (via `/api/user_settings`), then gets published on `window.generationPreset` + a `guildpresetchange` CustomEvent so downstream action builders can opt in with a single listener.

</details>

<details>
<summary><strong>📡 Antenna — 15+ endpoints, tray menu, self-update</strong></summary>

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

</details>

<details>
<summary><strong>🎙️ Voice — walkie-talkie STT + TTS playback</strong></summary>

A mic-button between the chat textarea and the summon-wand. Press-and-hold starts MediaRecorder capture (webm/opus); release uploads the base64 blob to `/api/stt`, which forwards to a registered **Kobold · TTS** backend running KoboldCpp in Whisper mode (`/api/extra/transcribe`). The transcript lands in the chat textarea so the user can edit before sending. Pointer-events cover both mouse and touch; the button pulses red while recording.

Symmetric `/api/tts` forwards text → audio via `/api/extra/generate_audio` so the Guild can read wizard replies aloud. Backend discovery via `_resolve_stt_backend_url()`: checks `guild_config.app_control.kobold_tts` (local) first, then falls back to any paired antenna advertising `kobold_tts`. Kobold in TTS/STT mode runs on port 5002 by convention; RP mode stays on 5001. Both modes coexist on the same box as separate services.

Registering a Kobold TTS backend: right-click any antenna chip → *Connect an app* → **Kobold**, type the launcher path + add `--whisper <model.gguf>` args. Guild tray → *Connect an app* for the local flow.

</details>

<details>
<summary><strong>🧩 Connect-an-app — register launchers, Windows shortcuts, auto-start</strong></summary>

Right-click any antenna chip (or open the Guild tray → *Connect an app…*) to pick one of eight app types — ComfyUI, Ollama, KoboldCpp, GIMP, Darktable, Resolve, SillyTavern, Signal Bridge — and type the launcher path on that machine. The Guild proxies the registration to the antenna's `/service/register` endpoint; the antenna persists it into `~/.spellcaster/antenna_config.json` (atomic tempfile + replace) under both the nested `services` map and the flat `<name>_launcher` keys so `service_launcher`'s override chain finds it either way.

Each chip also carries two tiny toggles on the left:
- **⚡ Start** — launches the app now on its configured target (local subprocess or remote via the antenna).
- **🔁 Auto-start** — persists "launch on Guild boot / auto-close on Guild exit" to `guild_config.app_control`. Toggled apps auto-start via the boot auto-launch loop in [guild_launcher.py](tavern/guild_launcher.py); `/api/guild/exit` iterates the same matrix on shutdown so nothing orphans.

The **Restart Server** button in Settings does a graceful restart: stops every `auto_start` app on its target, spawns a detached relauncher that sleeps 1.2s then re-execs the current argv, then `os._exit(0)`s the old process. The client polls `/api/comfy_status` until the new process responds, then reloads the page — so a full cycle takes about 3s.

</details>

<details>
<summary><strong>🔐 Privacy, boot safety, auto-update risk</strong></summary>

- **Privacy cleanup** ([privacy.py](comfyui-spellcaster/spellcaster_core/privacy.py)) — every temporary file on the ComfyUI server is atomically overwritten with a 1×1 pixel PNG then deleted after use. Your images don't linger. Configurable TTL.
- **Crash-safe boot shim** — the GIMP plugin is split into a 228-line immutable loader ([comfyui-connector.py](plugins/gimp/comfyui-connector/comfyui-connector.py)) + the 22K-line main plugin. The shim has 3-tier recovery: local backup → GitHub download → visible "CRASHED" menu entry. The auto-updater has the shim in its protected set — it will never overwrite or delete the loader.
- **Auto-update risk** — three separate auto-updaters run on launch (Wizard Guild, GIMP plugin, installer bootstrap). They download from GitHub and prune local files that aren't in the remote. CLAUDE.md rule 13 documents what each one clobbers and the safe-restart order (commit + push → restart is always safe).
- **Preflight validation** ([preflight.py](comfyui-spellcaster/spellcaster_core/preflight.py)) — every workflow is checked and patched before submission. Missing nodes get substituted, unsupported architectures get fallbacks. A user with a stale ComfyUI custom-node set still gets a working generation instead of a red error.
- **Atomic persistence, everywhere** — `guild_config.json`, `network_survey.json`, `generated_assets.json`, `wizard_identities.json`, `lora_registry.json`, `llm_prompt_settings.json`, `antenna_config.json`. All write via `tempfile` → `fsync` → `os.replace` so a power-cut mid-save leaves you with either the old version or the new, never half.

</details>

<details>
<summary><strong>🎬 Resolve Bridge — timeline-aware shot generation</strong></summary>

The Resolve plugin in [plugins/resolve/](plugins/resolve/) adds a Spellcaster menu to DaVinci Resolve 20+:

- **Generate from playhead** — drop the cursor on the timeline, type a prompt, get an 81-frame LTX-2 clip back in the Media Pool snapped to the playhead.
- **Smart gap fill** — place two clips with a gap between them; Spellcaster reads the last frame of clip A + the first frame of clip B and renders an LTX-2 "first-last frame" transition that fills the gap.
- **Markers to shots** — Resolve marker colours map to Spellcaster render profiles (red = high-effort, blue = turbo, etc.); batch-render every marker at once.
- **Send to Resolve** — any image anywhere (GIMP, Guild gallery, Darktable) can be pushed into the Resolve Media Pool with one click via the event bus.

The actual Resolve automation runs in a Python script in Resolve's scripting engine; the Guild-side trigger reaches it via the antenna's `/resolve/*` endpoints when Resolve lives on a different box.

</details>

<details>
<summary><strong>🖼️ Everything else worth mentioning</strong></summary>

- **9-architecture `ArchConfig` registry** ([architectures.py](comfyui-spellcaster/spellcaster_core/architectures.py)) — every arch declares its loader (checkpoint / unet_clip_vae / etc.), sampler, CFG, denoise, resolution, supports-negative flag, prompt style, LoRA prefixes, ControlNet model, turbo config, CLIP+VAE filenames, quality positive/negative tails, autoset LoRA lists per method. One object drives every builder.
- **`NodeFactory` DSL** ([node_factory.py](comfyui-spellcaster/spellcaster_core/node_factory.py)) — every ComfyUI node type is a typed Python method call. Zero raw dicts. Refactors ripple through every workflow without string-editing JSON.
- **Composites** ([composites.py](comfyui-spellcaster/spellcaster_core/composites.py)) — multi-node helpers that compose into a canonical shape: `load_model_stack`, `inject_lora_chain`, `encode_prompts`, `build_klein_enhancer_chain`, etc. Every builder that wants these behaviours gets them by calling the composite; there is no parallel implementation anywhere.
- **Model detect** ([model_detect.py](comfyui-spellcaster/spellcaster_core/model_detect.py)) — maps filename → architecture + family. Handles SD1.5 vs SDXL vs Illustrious vs Pony vs Flux Dev vs Klein vs Kontext vs Chroma vs LTX vs Wan. Extensive test matrix for adversarial filenames (`wan_mixl` shouldn't match "xl" before "wan").
- **Network survey** ([network_survey.py](scaffold/network_survey.py)) — first-time install asks "where does ComfyUI live? Local / LAN / skip / not installed?" for every tracked service. Persists to `.guild_state/network_survey.json` and drives the chip renderer's local vs remote origin hint.
- **Character-hover portrait** — 220px circular preview near the cursor whenever you mouse over a chat avatar. Pointer-events:none so it never steals a click. Delegated listener on `#chat-stream` so dynamically-added avatars pick up the behaviour with zero per-message wiring.
- **Recent-across-apps strip** — sidebar row showing the last N generated assets from **every** origin (GIMP / Resolve / Guild / …). Click a thumbnail → the image drops into the active wizard's chat as a reference. Scrollbar aligns with the character-list scrollbar exactly (both 4px purple thumb on transparent track).

</details>

---

<p align="center"><em>"the smugness radiates 'I'm better than everyone' it kills the interest"</em> — u/kanatakkun, r/GIMP</p>

<p align="center">You know I am, baby. Xoxo</p>

## FAQ

The questions below are "frequently asked" in the sense that we asked them to ourselves in the shower and decided the answers were important enough to write down.

<details>
<summary><strong>What GPU do I need?</strong></summary>

Any NVIDIA GPU with 4+ GB VRAM. AMD works too (ROCm/DirectML). The installer looks at your GPU and says "here's what you can run" — no guesswork. 4GB gets you the basics. 8GB is the sweet spot. 16GB unlocks the good stuff. 24GB and you're basically a wizard yourself, at which point you should be the one writing this README.

</details>

<details>
<summary><strong>Do I need to understand ComfyUI?</strong></summary>

No. God no. The whole point of this project is that you don't. Every tool has expert-tuned presets. You never need to open ComfyUI, pick a sampler, write a negative prompt, or learn what "Euler ancestral CFG++ with Karras scheduling at 0.85 denoise" means. That sentence just gave you a headache. See? We saved you from that.

(But if you *want* to go deeper — every parameter is exposed, you can save custom presets, import raw ComfyUI workflows, and inject LoRAs. The power is there when you're ready for it.)

</details>

<details>
<summary><strong>Does anything leave my computer?</strong></summary>

No. Nothing. Nada. Zero bytes. Your GPU does all the work, your images stay on your hard drive, and absolutely no one — not us, not OpenAI, not the ghost of Steve Jobs — ever sees what you generate. The only network traffic is between GIMP and your own ComfyUI server, which can literally be `localhost`. Generate whatever you want. We're not watching. We don't *want* to watch.

</details>

<details>
<summary><strong>Can I use my own ComfyUI workflows?</strong></summary>

Yes. `Filters > Spellcaster Tools > Workflow Library` runs any workflow JSON from GIMP.

</details>

<details>
<summary><strong>ComfyUI on another machine?</strong></summary>

Yes. The Antenna Installer auto-detects ComfyUI servers on your network. Or set the URL in Settings. One of our beta testers runs ComfyUI on a gaming PC in their closet and generates images from a laptop on their couch. We have enabled laziness at an architectural level and we're proud of it.

**Direct antenna downloads:** [Windows .bat](https://raw.githubusercontent.com/laboratoiresonore/spellcaster/main/installer/install_antenna.bat) &bull; [macOS / Linux .sh](https://raw.githubusercontent.com/laboratoiresonore/spellcaster/main/installer/install_antenna.sh). See [The Antenna](#the-antenna--your-other-machines-one-click-away) for pairing instructions.

</details>

<details>
<summary><strong>Can I have more than one LLM running at once?</strong></summary>

Yes. That's the whole point of the LLM pill picker under the Guild title. ComfyUI's embedded LLM, Ollama, and a dedicated RP Kobold can all stay online together — SillyTavern keeps chatting with Kobold, the Guild uses ComfyUI for image prompts, Ollama handles install scaffolding. The pill just decides who answers **chat()** first; nobody gets stopped. See [🎯 LLM primary picker](#-llm-primary-picker--comfyui-reroute-ollama--kobold-auto-start).

</details>

<details>
<summary><strong>How does the LoRA Shootout actually work?</strong></summary>

Purpose-aware multi-sample renders: the LoRA registry is grouped into 20+ purpose buckets (`skin_detail`, `style_photoreal`, …), each with a subject-specific prompt (portrait / fullbody / macro / animal). You approve **many** LoRAs — not pick one winner — with user-supplied keywords that the Guild auto-proposes when the keyword appears in a chat prompt. Auto-fallback tries up to 3 checkpoints of the same arch on generation failure. See [🛠 Scaffold system](#-scaffold-system--state-machine-wizards-for-7b-models) → `lora_grouping.py`.

</details>

<details>
<summary><strong>Can I talk to the Guild instead of typing?</strong></summary>

Yes — register a KoboldCpp in TTS/STT mode (right-click any antenna chip → *Connect an app* → *Kobold* with `--whisper <model.gguf>`), then press-and-hold the 🎙️ button next to the chat input. Walkie-talkie — release to transcribe. See [🎙️ Voice](#%EF%B8%8F-voice--walkie-talkie-stt--tts-playback).

</details>

<details>
<summary><strong>Why "Spellcaster"?</strong></summary>

Because every tool is a spell, every workflow is an incantation, your GPU is a familiar, and the entire project radiates the energy of someone who played too much D&D and then learned Python. Also "ComfyUI-GIMP-Middleware-With-69-Tools-And-A-Chat-UI-Full-Of-Wizards" didn't fit in the GitHub repo name.

</details>

<details>

---

<p align="center"><em>"Man this is the kind of phrasing you can use in your incel-fueled, ragebaiting and redpilled nutjobed clanckers spaces"</em> — u/MrSumNemo, r/GIMP</p>

<p align="center">No you.</p>

<details>
<summary><strong>Wall of Love from r/GIMP</strong></summary>

We posted Spellcaster to r/GIMP. They were... *thrilled.*

> *"No, I use GIMP because I don't want to make AI slop."*
> — u/Ill_Morning_4282 (130 upvotes, community hero)

> *"No one fucking uses GIMP to make AI slop"*
> — u/Capable_Basket1661 (50 upvotes, keeper of the sacred flame)

> *"Ew, AI slop... and you didn't even code it yourself? lmao how ridiculous can you get"*
> — u/FentonTheIIV (correct! 22,000 lines of Python, vibe-coded at 3 AM while arguing with an AI that kept setting Klein's CFG to 3.5. We are not ashamed. We are tired.)

> *"No. Go away, sloperator!"*
> — u/chris020891 (coined a new word though, we respect that)

> *"the smugness radiates 'I'm better than everyone' it kills the interest"*
> — u/kanatakkun (fair point honestly, we were kind of a dick about it)

> *"Man this is the kind of phrasing you can use in your incel-fueled, ragebaiting and redpilled nutjobed clanckers spaces"*
> — u/MrSumNemo (we had to look up "clanckers" and we're still not sure what it means)

> *"Nice persecution complex, some of us don't need to steal others' artwork in order to pretend to be creative."*
> — u/Ill_Morning_4282 (back for round two, still swinging)

> *"Everyone with even a minor self respect would hate on this."*
> — u/chris020891 (our self-respect was already in critical condition, but thanks for checking)

Meanwhile, u/stilgarpl said *"Background removal has been the worst and most tedious task for me for years... I can finally focus on actual creative work"* and got buried by downvotes. u/darkhalfkz said *"thank you"* and survived. Barely.

We love you, r/GIMP. Never change. The tool is still free. The source is still open. The LICENSE still lets you print it and shove it wherever you want. We'll be here when you're ready. ❤️

</details>

<details>
<summary><strong>Credits & Acknowledgements</strong></summary>

*Proudly vibe-coded as a pure pineapple-pen innovation.* 🍍🖊️ *I have a pen. I have ComfyUI. Ugh — Spellcaster.*

Spellcaster doesn't reinvent the wheel — it duct-tapes together the best wheels the open-source AI community has ever built, then hides the duct tape behind a nice menu:

**Core engine:** [ComfyUI](https://github.com/comfyanonymous/ComfyUI) by comfyanonymous — the node-based powerhouse that actually does everything

**AI models & architectures:** [Stability AI](https://stability.ai/) (SD 1.5, SDXL, SD3), [Black Forest Labs](https://blackforestlabs.ai/) (Flux), [Flux 2 Klein](https://civitai.com/), [Wan 2.2](https://github.com/Wan-Video/Wan2.2), [LTX Video](https://ltx.io/), [SeedVR2](https://seedvr2.net/)

**Workflow pipelines:** [Elusarca's Klein 6-in-1](https://civitai.com/models/2543188) (Klein refiner, auto-inpaint, color match — used with permission), [xb1n0ry's Comfy-Workflows](https://github.com/xb1n0ry/Comfy-Workflows) (Wan 2.2 NAG + Skip-Layer-Guidance, Klein 4-image-grid batch variations, Wan 2.2 block-swap low-VRAM pipeline, Qwen Image Edit 2509 — all adapted into Spellcaster builders)

**Face & identity:** [ReActor](https://github.com/Gourieff/comfyui-reactor-node), [IPAdapter](https://github.com/cubiq/ComfyUI_IPAdapter_plus), [PuLID](https://github.com/cubiq/PuLID_ComfyUI), [ACE++](https://github.com/ali-vilab/ACE_plus), [InsightFace](https://github.com/deepinsight/insightface), [CodeFormer](https://github.com/sczhou/CodeFormer), [GFPGAN](https://github.com/TencentARC/GFPGAN), [GPEN](https://github.com/yangxy/GPEN)

**Enhancement:** [Real-ESRGAN](https://github.com/xinntao/Real-ESRGAN), [SUPIR](https://github.com/Fanghua-Yu/SUPIR), [IC-Light](https://github.com/lllyasviel/IC-Light), [DDColor](https://github.com/piddnad/DDColor), [LaMa](https://github.com/advimman/lama), [NormalCrafter](https://github.com/AIWarper/ComfyUI-NormalCrafterWrapper)

**Segmentation:** [SAM 2/3](https://github.com/facebookresearch/sam2) (Meta), [BiRefNet/RMBG](https://github.com/1038lab/ComfyUI-RMBG), [DepthAnything V3](https://depth-anything-3.github.io/), [Florence 2](https://huggingface.co/microsoft/Florence-2-base)

**ControlNet:** [ControlNet](https://github.com/lllyasviel/ControlNet) by lllyasviel, [comfyui-controlnet-aux](https://github.com/Fannovel16/comfyui_controlnet_aux)

**Video:** [RIFE](https://github.com/hzwer/ECCV2022-RIFE), [GIMM-VFI](https://github.com/JihyongOh/GIMM-VFI), [VHS](https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite), [AnimateDiff](https://github.com/guoyww/AnimateDiff)

**Acceleration:** [TeaCache](https://github.com/welltop-cn/ComfyUI-TeaCache), [WaveSpeed/FBCache](https://github.com/chengzeyi/Comfy-WaveSpeed), [LightX2V](https://github.com/modelscope/lightx2v)

**LLM:** [Qwen3](https://huggingface.co/Qwen) (Alibaba), [ComfyUI-QwenVL-Mod](https://github.com/1038lab/ComfyUI-QwenVL)

**Klein Enhancer:** [Flux2Klein-Enhancer](https://github.com/Flux2Klein) — RefLatentController, TextRefBalance, ColorAnchor

**Node packs:** [Impact Pack](https://github.com/ltdrdata/ComfyUI-Impact-Pack), [ComfyUI-essentials](https://github.com/cubiq/ComfyUI_essentials), [ComfyUI-GGUF](https://github.com/city96/ComfyUI-GGUF), [KJNodes](https://github.com/kijai/ComfyUI-KJNodes), and dozens more

**Host apps:** [GIMP 3](https://www.gimp.org/), [Darktable](https://www.darktable.org/), [SillyTavern](https://github.com/SillyTavern/SillyTavern)

**Vibe coding assistant:** [Claude](https://claude.ai/) by Anthropic — wrote most of this while being yelled at

**Moral support:** r/GIMP — for keeping us humble, grounded, and deeply motivated by spite

</details>

---

<p align="center">
  <sub>
    Made with unhealthy amounts of coffee, mass delusion, and a GPU that sounds like a jet engine.<br/>
    If you've read this far, you're either installing it or writing a hate comment. Either way, we appreciate the engagement.<br/><br/>
    <strong>Star the repo if you like it. Fork it if you hate it. Ignore it if you're u/Ill_Morning_4282.</strong>
  </sub>
</p>
