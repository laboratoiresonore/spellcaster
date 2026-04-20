# Cross-Application Architecture — Review

**Scope:** how the five Spellcaster surfaces (GIMP, SillyTavern, Darktable, Resolve, ComfyUI custom nodes) currently talk to ComfyUI and to each other, and what would have to change to make every plugin match the GIMP pattern.

**GIMP pattern (the gold standard, per user):**
- Direct ComfyUI connection — no Guild required for any primary feature
- Dynamic menu build — probes ComfyUI's `/object_info` + installed models, registers only the procedures whose required nodes are present (22 feature sentinels)
- Auto-updater — pulls from GitHub with rollback, staged `.py` files, SHA verification, protected file list
- Crash-safe boot shim — 3-tier recovery (backup → GitHub fresh → visible "CRASHED" menu)
- SFW/NSFW patching via `nsfw/build_nsfw.py`

The rest of this document reviews where each plugin is relative to that standard, then asks the concrete architectural question: **can SillyTavern and Darktable video generation be made direct?**

---

## 1. Plugin inventory (one-paragraph each)

### 1.1 GIMP — gold standard
Python 3 plugin, registered with GIMP 3's GI/GTK via `Gimp.PlugIn`. 22 menu procedures under `<Image>/Filters/Spellcaster/...`. Dynamic menu: each procedure has a feature key (one of 22 in `_FEATURE_SENTINELS`) and only registers when ComfyUI's `/object_info` shows the required node class. Talks to ComfyUI directly via `urllib.request`; bundles `spellcaster_core/` alongside the plugin so every workflow builder is a local Python import. Uses the Guild only for **cross-app send/receive** (Send-to-Resolve / Check Inbox), never for primary generation.

### 1.2 SillyTavern
Two files: a browser-side `index.js` (SillyTavern UI extension) and a Node server plugin (`server-plugin.js`, mounted under `/api/plugins/spellcaster/*`). 23 slash commands + 3 LLM function tools. Image generation (`/scene`, `/portrait`, `/restyle`, `/edit`, `/studio/*`) talks direct to ComfyUI from the Node server. **Video (`/animate`) routes through the Guild's `/api/video/shots` pipeline** because the WAN/LTX canon is Python-only (CLAUDE.md §16.4) and JS can't import `spellcaster_core`. Cross-app via `/cross/send` + `/cross/events` (SSE proxy to Guild) + `/cross/inbox`.

### 1.3 Darktable
Single Lua file (~8.8k lines) loaded as a Darktable script. 66 `process_*` functions driving the lib panel. Talks to ComfyUI by shelling out to `curl`. Same shape as SillyTavern: image ops direct, video via the Guild (`guild_create_shot` → `guild_attach_reference` → `guild_render_shot` → `guild_wait_for_shot_ready` → `guild_download_shot_video`) because Lua can't import Python.

### 1.4 Resolve
A Python bridge (3 modules in `spellcaster_bridge/`) plus 35 standalone scripts in `scripts/`. Runs inside DaVinci Resolve's embedded Python. **Almost every feature routes through the Guild by design**: the bridge subscribes to the Guild's SSE, auto-imports finished shots into the Media Pool, and scripts use `GuildClient` for everything. Unlike ST/Darktable the Resolve environment is a _host_ environment (embedded Python, limited module access, not a fresh process), so direct ComfyUI workflow-building from inside Resolve is genuinely harder — the Guild hop is architectural, not incidental.

### 1.5 ComfyUI custom nodes
Two repos (public + NSFW) bundled with the installer. Expose 4 nodes (`SpellcasterLoader`, `SpellcasterPromptEnhance`, `SpellcasterSampler`, `SpellcasterOutput`) plus 2 NSFW-only in the private variant. These ARE "smart nodes" — they embed `spellcaster_core` knowledge so a ComfyUI workflow can use them without needing to know arch detection, quality profiles, or prompt-enhancement details.

---

## 2. Cross-application primitives

All five surfaces share three layers:

| Layer | Source of truth | Consumers |
|--|--|--|
| **`spellcaster_core/`** (38 Python modules) | `comfyui-spellcaster/spellcaster_core/` (canonical) — mirrored into 3 plugin/node locations per CLAUDE.md §3 | GIMP plugin, Guild server, ComfyUI custom nodes. **NOT importable from JS/Lua/Resolve-embedded-Python.** |
| **Guild cross-interface bus** | `tavern/server.py` + `spellcaster_core/{cross_interface,event_bus,asset_gallery,mailbox,interface_registry}.py` | Any plugin talking to Guild `/api/events/*`, `/api/assets/*`, `/api/<iface>/inbox`. |
| **Guild `/api/video/shots`** | `tavern/server.py:9700` → `scaffold/video_bridge.py` | ST, Darktable video paths. |

Of those three, **only the first two are universally needed**. The Guild `/api/video/shots` layer exists because JS and Lua plugins can't import the Python video canon.

---

## 3. Per-plugin dependency matrix

| Plugin | Image gen | Restyle/edit | Video (WAN/LTX) | Prompt enhance | Cross-app send | Cross-app recv | Auto-update | Dynamic menu | NSFW patch |
|--|--|--|--|--|--|--|--|--|--|
| **GIMP** | direct | direct | direct (Python import) | direct | Guild | Guild | ✅ full | ✅ 22 sentinels | ✅ |
| **SillyTavern** | direct | direct | **Guild** | direct | Guild | Guild | ⚠️ ST auto-update only | ❌ no gating | partial (base file) |
| **Darktable** | direct | direct | **Guild** | direct | Guild | Guild | ⚠️ manual_update.py | ⚠️ hardcoded | ✅ |
| **Resolve** | — | — | Guild | — | Guild | Guild (SSE) | ❌ manual | ❌ — | ❌ (not patched) |
| **ComfyUI nodes** | (provides) | (provides) | (provides — via `/prompt`) | (provides) | — | — | via ComfyUI Manager | n/a | ✅ (NSFW repo) |

**Read this matrix as:** the only "forced Guild" cells for non-Resolve plugins are the **video** column (because the WAN/LTX canon is Python-only) and the **cross-app send/recv** columns (because cross-app is by definition cross-process).

---

## 4. What's "essential" vs "avoidable" Guild usage

Classifying each current Guild dependency:

### Essential (no way around it)
- **Cross-app send/recv** (`/api/assets`, `/api/events/*`, `/api/<iface>/inbox`). Any "send this image from GIMP to Resolve" feature fundamentally needs a broker process because the two clients don't share address space. The Guild *is* the right place for this.
- **Resolve's whole architecture.** Resolve's embedded Python can't easily fork subprocesses, has constrained module access, and would need the user to keep a separate DavinciResolve-Spellcaster window open. The Guild mediating is structurally sound.
- **Guild-owned features** — shotboard, the chat wizards, calibration sessions, cross-app orchestration (mailbox fan-out, heartbeat registry). These live on the Guild by design.

### Avoidable (could be made direct)
- **SillyTavern `/animate`.** Currently POSTs to Guild's `/api/video/shots`. Could be direct if a client had a way to invoke the WAN/LTX canon without importing Python.
- **Darktable `process_wan_i2v` + LTX paths.** Same as above.

Two dependencies, one underlying cause: **JS/Lua can't import `spellcaster_core`**.

---

## 5. Four architectural options for the "avoidable" set

### Option A — Port the canon to JS + Lua
Re-implement `detect_wan_preset`, `build_wan_video`, `build_ltx_video`, `wan_turbo_kwargs` in each language. **Rejected.** I already deleted a 488-line JS re-implementation in phase-7; it had drifted from the Python canon (missing CausVid LoRA detection, missing accel-strength tuning, wrong turbo formula). Multi-language canon duplication is a maintenance disaster.

### Option B — Bundle a Python companion with each plugin
ST's Node server spawns `python3 workflow_helper.py build-wan-i2v ...` on demand. Darktable's Lua shells out similarly. **Rejected for ST; maybe OK for Darktable.** Requires Python on the user's box (already a requirement for the installer, so not new), but spawning a subprocess per generation is slow (~1 s cold-start) and error-prone (which `python`? venv? PATH?). Also duplicates process-management complexity across plugins.

### Option C — Expose the canon as ComfyUI custom nodes
Add two nodes to `ComfyUI-Spellcaster`:

- **`SpellcasterWanI2V`**: inputs `(image, prompt, negative, length, turbo, pingpong, ltx_end_image?)`, outputs `(video, frames)`. Internally calls `spellcaster_core.video_presets.detect_wan_preset` + `workflows.build_wan_video` + dispatches within ComfyUI. One node per video architecture (WAN, LTX).
- **`SpellcasterLtxI2V`**: same shape for LTX.

Any plugin in any language then submits a tiny ~4-node workflow:
```json
{
  "1": { "class_type": "LoadImage", "inputs": { "image": "ref.png" } },
  "2": { "class_type": "SpellcasterWanI2V", "inputs": {
      "image": ["1", 0], "prompt": "...", "length": 33, "turbo": true }},
  "3": { "class_type": "VHS_VideoCombine", "inputs": {
      "images": ["2", 0], "frame_rate": 16, "format": "image/gif" }}
}
```

**Pros:** canon stays Python-only (no duplication); JS and Lua already submit ComfyUI workflows for image gen, so video becomes symmetric; no Guild dependency for video; users get the feature just by installing the ComfyUI node pack (already part of the installer); dynamic menu gating falls out for free (plugin probes `/object_info` and disables the video menu if the node isn't installed).

**Cons:** node has to live in the ComfyUI process (it does — custom nodes run as part of ComfyUI's Python); ComfyUI doesn't natively support long-running-with-progress nodes well (but WAN/LTX work fine because each sampling step is a normal node); new maintenance point (the 2 nodes + their tests).

**This is the option that matches the GIMP pattern.** GIMP uses `spellcaster_core` because it's a Python plugin; JS/Lua plugins would use the ComfyUI nodes as the canon boundary. Same underlying canon; different import mechanism.

### Option D — Keep the Guild, reduce its role
Leave `/api/video/shots` as-is; make the Guild optional by gracefully degrading. ST/Darktable would fall back to SDXL noise-inject when the Guild is down. **Current state, not a change.** Doesn't meet the user's stated goal ("plugins should work exactly like GIMP without needing Guild").

### Recommendation: **Option C**
It's the smallest, cleanest change that actually matches the GIMP pattern. The existing `ComfyUI-Spellcaster` repo already has 4 "smart nodes" that do this for image gen — extending the pattern to video is additive, not architectural.

---

## 6. Auto-update parity gap

GIMP is the only plugin with a real auto-updater. Others:

| Plugin | Today | What GIMP has that this lacks |
|--|--|--|
| GIMP | `_auto_update()` pulls from GitHub, SHA-verified, staged `.py`, crash-safe shim, rollback-on-boot-error. | — |
| SillyTavern | ST's own `enableServerPluginsAutoUpdate` pulls the whole plugin dir on launch. | No rollback on a bad update → a broken plugin silently fails and the only fix is reinstall. No SHA verification (ST's updater uses git pull). |
| Darktable | `installer/manual_update.py` runs on demand. | No automatic pull. No rollback. |
| Resolve | Manual reinstall. | Everything. |

**Bringing all plugins to GIMP parity** would mean each plugin ships a small self-updater (fetch from GitHub, SHA-check, stage, rollback). The shared primitives are already in `spellcaster_core/auto_updater.py` (I hardened it in phase-3). A JS-side port would be small (~100 lines) — same shape, same semantics.

Priority: **low**. ST's native updater is adequate in practice; Darktable's manual_update works. Worth noting in the audit but not urgent.

---

## 7. Dynamic-menu parity gap

GIMP has `_FEATURE_SENTINELS` — 22 feature keys, each mapped to a set of ComfyUI node class names. On menu build, it probes `/object_info`, checks which nodes are present, and only registers procedures for features that can actually run. A user without ReActor installed doesn't see "Face Swap" in the menu.

ST + Darktable register every command unconditionally. A user without WAN installed still sees `/animate` and gets a confusing error when they try it. A user without Klein sees `/edit` fall through to SDXL without explanation.

**Gap:** port the sentinel pattern to ST's slash-command registration and Darktable's lib-panel build. A single shared JSON (`feature_sentinels.json` — synced between the Guild and each plugin) would keep them in lock-step with the GIMP list.

---

## 8. NSFW patching parity gap

`nsfw/build_nsfw.py` has:
- `patch_gimp_plugin` — injects NSFW presets, LoRA metadata, director scripts, outfits, unlock LoRAs. 73 injections total across the GIMP plugin.
- `patch_darktable_plugin` — injects 19 NSFW inpaint presets.
- `patch_klein_nsfw` — injects 26 Klein inpaint, 21 poses, 7 interactions, 12 outpaints, 6 outfits, 3 unlock LoRAs.
- `patch_manifest` — NSFW LoRAs + Wan models.
- **NO SillyTavern-specific patches.** ST only gets the base-file rewrite (no NSFW content injection).
- **NO Resolve-specific patches.**

**Gap:** ST and Resolve don't get NSFW preset injections. They CAN use NSFW content from the shared gallery (assets sent from GIMP are shareable), but they don't have in-plugin NSFW presets like GIMP does. Likely intentional — ST's slash commands are user-typed prompts, so there's nothing to "pre-inject." Resolve's role is editing-suite, not generation, so same story. Not a gap in practice; worth noting.

---

## 9. Cross-app backbone — health check

The cross-app layer itself (the thing that genuinely needs Guild coordination) is in good shape after the earlier audit phases:

| Primitive | Status | Notes |
|--|--|--|
| `AssetGallery` (content-addressed blob store) | ✅ | Content-hash sharded; atomic write via tmpfile+rename; thread-locked |
| `EventBus` | ✅ | Ring buffer + per-subscriber queue with drop-oldest; bounded |
| `Mailbox` | ⚠️ | `consume=1` default makes messages lost-on-first-fetch if the reader crashes mid-render. Deferred from earlier audit (M10). |
| `InterfaceRegistry` | ✅ | Heartbeat TTL works; UI gates on active flag |
| `/api/video/shots` dispatcher | ✅ | Shadow bug fixed in phase-3 (G1-G5 recovered 5 dead POST handlers) |
| Per-plugin client (`CrossInterfaceClient` Python, server-plugin `/cross/*` Node) | ✅ | One memoized client per process after phase-2 M9 fix |

One action item remains: **Mailbox consume-on-fetch** (M10). Low priority; requires adding `/cross/ack` to the Guild and updating every client.

---

## 10. Summary and recommended direction

### Present state in one sentence
GIMP is direct-to-ComfyUI with full autonomy; ST and Darktable are direct for image ops but forced through the Guild for video (because the WAN/LTX canon is Python-only); Resolve is Guild-centric by necessity. Cross-app send/receive legitimately needs the Guild and that subsystem is healthy.

### To match GIMP's pattern across SillyTavern and Darktable
**Do Option C: add `SpellcasterWanI2V` and `SpellcasterLtxI2V` ComfyUI custom nodes** that embed the Python canon. ST and Darktable then submit a tiny direct-to-ComfyUI workflow for video. No Guild dependency for generation. The Guild reverts to its correct role: **the cross-app message bus + a failsafe for legacy paths**.

Remaining parity work (ranked):
1. **Option C nodes** — largest impact, eliminates the "JS/Lua can't import Python" problem for video.
2. **Dynamic-menu gating in ST + Darktable** — small effort, noticeable UX improvement.
3. **Port auto-updater shape to ST + Darktable** — nice-to-have, ST's native updater already works.
4. **Mailbox M10** — `/cross/ack` so consume-on-fetch doesn't lose messages.

### What NOT to touch
- The cross-app bus (AssetGallery + EventBus + Mailbox + InterfaceRegistry). It's the Guild's legitimate purpose and it works.
- Resolve's Guild-centric architecture. Trying to inline the canon there is fighting the host environment.
- The GIMP plugin's autonomy. Leave it exactly as-is.

---

## 11. Ready for a deeper audit on user's signal

Waiting for direction. Candidates for a deeper pass:

| Focus | What a deeper audit would produce |
|--|--|
| **Option C implementation readiness** | Proof-of-concept `SpellcasterWanI2V` node against the current `build_wan_video` — confirms the signature / I/O typing works, measures overhead vs the Guild pipeline, identifies edge cases (e.g. progress reporting, long-running node behaviour). |
| **ST + Darktable Guild-removal path** | Concrete diff that switches `/animate` and `process_wan_i2v` from Guild POSTs to direct ComfyUI workflows using the new node. Includes the fallback chain when the node isn't installed. |
| **Cross-app message guarantee** | End-to-end trace of a GIMP→ST asset: `GIMP.send → AssetGallery.put → EventBus.publish → Mailbox.fanout → /cross/events SSE → ST.render`. Confirm durability + dedup + ordering under reconnect. |
| **Sentinel-based menu gating port** | Draft of a shared `feature_sentinels.json` + JS/Lua readers that duplicate GIMP's 22-feature gating pattern. |

Say "go deep on X" and I'll do X.
