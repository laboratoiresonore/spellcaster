# Cross-App Discovery + Coordination — Review

**User question:** if every plugin can update itself based on what's in ComfyUI, can they also detect each other and coordinate multi-app workflows? Example flow:

> Photo → Darktable (basic edits) → GIMP (advanced edits) → Wizard Guild / Resolve (I2V) → extract last frame → back to GIMP

This review audits what's already built, traces the example workflow against it, and identifies what's missing.

---

## 1. Discovery primitives that already exist

A lot of the plumbing is there. Summary of the data model, from code:

### 1.1 `InterfaceRegistry` (`spellcaster_core/interface_registry.py`)
Seven registered interfaces, each with a `ui_label`, `icon`, and **capability list**:

| key | label | capabilities |
|--|--|--|
| `guild`       | Wizard Guild   | chat, send_image, receive_image, event_bus |
| `gimp`        | GIMP           | send_image, receive_image, pixel_edit |
| `darktable`   | Darktable      | send_image, raw_edit |
| `resolve`     | Resolve        | receive_image, receive_video, timeline, playhead_capture, gap_fill |
| `sillytavern` | SillyTavern    | chat, send_image, roleplay |
| `signal`      | Signal Bridge  | notify, receive_text, send_text |
| `antenna`     | Remote Antenna | remote_comfyui, remote_llm, remote_resolve |

**This is already a capability-aware registry** — a sender can ask "who can `receive_video`?" and get back `["resolve"]`. None of the plugins query it that way today, but the data is there.

### 1.2 Heartbeat + presence
- `POST /api/interfaces/heartbeat` with `{interface, meta}` — plugins call this periodically.
- `GET /api/interfaces` returns the full state map including `last_heartbeat`, `online` (bool), `online_local`, `online_remote`, `last_meta`.
- `CrossInterfaceClient.active_interfaces()` in Python; implicit in `server-plugin.js` via HTTP.

### 1.3 Asset gallery + mailbox + event bus (cross-app bus)
- `AssetGallery.put(bytes, origin=, kind=, ...)` — content-addressed blob store, returns hash.
- `EventBus.publish(kind="gimp.asset.send", data={image_url, hash, source, ...})` — fan-out to subscribers.
- `Mailbox` — per-interface pull queue; fan-out by event kind prefix (`gimp.*` → `/api/gimp/inbox`).
- `GET /api/events/stream` — SSE.

### 1.4 Plugin-side usage today

| plugin | heartbeats? | has send-to-X? | has receive from inbox? |
|--|--|--|--|
| GIMP      | ✅ (auto every 10 s via `CrossInterfaceClient`) | ✅ 3 menu items (Resolve / Darktable / SillyTavern) | ✅ "Check Inbox" manual menu action |
| Darktable | ✅ (on publish + install) | ✅ 5+ "Send to X" buttons + cross-app send | ⚠ polls inbox occasionally |
| Resolve   | ✅ (every 10 s in bridge) | ✅ 7 scripts (`send_clip_to_*`, `send_frame_to_*`) | ✅ SSE auto-import via `MediaPoolSync` |
| SillyTavern | ❌ **missing** | ✅ 3 slash commands (`/sc-send-to-*`) | ✅ `/sc-inbox` manual + auto-poll (phase-6) + SSE (phase-8) |

**One real gap already here: ST doesn't heartbeat.** Everyone sees ST as offline in `/api/interfaces` even when it's running; so GIMP's "Send to SillyTavern" chip probably never lights up, or it does but fails.

### 1.5 Asset metadata today

```python
@dataclass
class AssetRecord:
    hash: str; ext: str; mime: str; size: int; ts: float
    origin: str = "unknown"       # "gimp" | "darktable" | ...
    kind: str = "generation"       # "avatar" | "background" | "shot" | "upscale" | ...
    title: str = ""
    prompt: str = ""
    model: str = ""
    seed: Optional[int] = None
    tags: list[str] = []
    meta: dict = {}                # free-form
```

`kind` describes **what the asset IS**. There is no field describing **what the receiver should DO with it** (open as new layer? replace? use as I2V reference? overlay?).

---

## 2. The example workflow, hop-by-hop, against current reality

### Hop 1: Photo → Darktable
User opens a RAW in Darktable as usual. No cross-app involved.
**Status: ✓ works**

### Hop 2: Darktable → GIMP
Darktable user clicks "Send to GIMP" button. Today:

- Darktable exports current image to PNG → uploads to ComfyUI's input dir (via `curl_upload`) OR to the Guild's `/api/assets` (via `guild_emit_event` + `gimp.asset.send`).
- Guild fans event to GIMP's mailbox at `/api/gimp/inbox`.
- GIMP user must **manually click** `<Image>/Filters/Spellcaster/Cross-App/💎 Check Inbox` to pull the asset.
- On pull, GIMP creates a NEW image document with the asset's PNG bytes.

**Gaps:**
- Darktable has no presence check — it doesn't know if GIMP is running. It sends blindly.
- GIMP requires a manual pull. If the user is in GIMP they have no in-UI signal that a new asset is waiting.
- The asset arrives as a brand-new image. There's no way to say "I want this as a new LAYER on my currently-open document", or "use this as a reference, not the main image."

### Hop 3: GIMP → Guild/Resolve (start I2V)
User finishes GIMP editing, wants to start an I2V film using the image as reference.

**For Resolve (starting a video edit with the still):**
- GIMP has `💎 Send to DaVinci Resolve` menu action → uploads to AssetGallery → publishes `resolve.asset.send`.
- Resolve's bridge subscribes to SSE; `MediaPoolSync._handle_event` auto-downloads the image and imports it into Resolve's Media Pool under `Spellcaster/From Guild`.
- **This actually works today end-to-end.** ✓

**For Guild/Video (starting I2V generation with this as first-frame):**
- GIMP has no menu action called "Start I2V film with this image." The user would have to:
  1. Copy the image filename
  2. Open the Guild's web UI in a browser
  3. Create a shot manually
  4. Attach the image manually
  5. Render
- There ARE GIMP plugin procedures for WAN I2V generation (the plugin has its own "animate this" menu via the `wan_i2v` feature sentinel), but those produce video INSIDE GIMP, not inside the shotboard.

**Gap:** no "Send to Wizard Guild as I2V start-frame" action that creates a shot + attaches ref + queues render + shows status in GIMP.

### Hop 4: Video renders
Guild's `VideoBridge` renders the shot. ~30–180 s on WAN 2.2 turbo.

- `/api/events/stream` emits `shot.status` / `shot.ready` events.
- Resolve's bridge auto-imports finished videos. ✓
- GIMP has no subscriber for shot-ready events. The plugin that started the shot (if we added that) wouldn't know when it's done.

**Gap:** no per-plugin subscription to "my" shot's ready event. No way for GIMP to say "tell me when shot XYZ is done."

### Hop 5: Extract last frame back into GIMP
User wants the last frame of the rendered video for a compositing pass.

- **Nothing in any plugin does this today.** There's no "extract last frame" action anywhere. The shotboard doesn't offer it. GIMP can't import from a shot ID.
- Manual workflow: open rendered mp4 in GIMP's "File → Open" (GIMP can import video-as-layers if ffmpeg is available) OR save last frame in Resolve and re-send.

**Gap:** no frame-extract action; no shot→image return path; no workflow-run-id linkage so the plugin knows "this is the last frame OF the shot that started FROM my image."

---

## 3. The real missing pieces

Synthesised from §2, ranked by leverage:

### G1 — Presence UI in every plugin's send-chip menu
Each plugin that can send assets should (a) poll `/api/interfaces` on menu open, (b) grey out dead targets, (c) show a live dot next to alive ones. Small code, big UX improvement. GIMP already has this data in `/api/interfaces` but doesn't use it to gate the menu.

### G2 — ST must heartbeat
The ST extension + server plugin don't call `/api/interfaces/heartbeat`. Fix: server plugin should heartbeat on every incoming request (most generous: on module load + every 10 s). One-line fix in `server-plugin.js` + bridge call to Guild's endpoint.

### G3 — Asset-level "intent" semantics
Extend `AssetRecord` with a small vocabulary of receiver hints:

```
meta.intent = "new_document"      # default — open as fresh doc
             | "new_layer_on_current"  # add as layer to active doc (GIMP)
             | "i2v_ref"          # first frame of a WAN I2V run
             | "i2v_end_ref"      # last frame (for first-last-frame I2V)
             | "v2v_ref"          # style reference for video-to-video
             | "style_ref"        # IPAdapter-style reference
             | "face_ref"         # face swap reference
             | "return_edit"      # "edit this and send back" — triggers reply flow
meta.workflow_run_id = "abc123"   # groups hops in one user workflow
meta.reply_to = "gimp"            # plugin key to offer as return target
```

Plugins that receive an asset with `meta.intent="new_layer_on_current"` behave differently from one with `new_document`. Plugins that see `meta.reply_to` offer a "Send the edit back to GIMP" button when the user saves.

Cost: small — asset_gallery.py + mailbox fan-out already carry arbitrary `meta`; only the RECEIVERS need to grow handlers.

### G4 — Workflow-run-id
A shared id stamped by the originating plugin and carried through every subsequent asset in the same workflow. Enables:
- "Continue workflow" UI — receiver knows which hop it is; offers the next sensible action.
- Workflow history in the Guild UI.
- "Open timeline view for this workflow" — shows the asset chain end-to-end.

Cost: small — just a uuid + propagation convention. Harder part is the UX to use it.

### G5 — "Send to Guild-Video / I2V" action in every image-producing plugin
Right now GIMP, Darktable, and ST have "Send to Resolve" chips. None have "Send as I2V start-frame → Guild video queue → wait → deliver result back to me." That's the workflow the user described.

Cost: per plugin, ~50 LOC (upload → POST `/api/video/shots` with `reply_to` set → subscribe to that shot's `ready` event).

### G6 — Shot → frame extraction action
In the Guild's shotboard UI (and also in each sending plugin), expose:
- "Extract last frame" → crops final frame → publishes back to `reply_to` plugin as a fresh asset with `intent="new_document"`.
- "Extract any frame at time T" — same.

Cost: ffmpeg one-liner + a UI button. Already have ffmpeg available (Guild uses it for thumbnails at server.py:12248).

### G7 — Receiver-side subscription to "my originated" events
When plugin A publishes a shot-creation event with `reply_to=A`, the Guild's event bus already delivers `shot.ready` globally. Plugins need a lightweight filter: "show me events where `meta.reply_to == my_key`". Could be done client-side in each plugin's SSE handler.

Cost: small — each plugin's SSE consumer adds a filter.

### G8 — Unified cross-app action vocabulary
Rather than each plugin implementing its own "Send to X" chip, standardize on one set:

```
send_to(target="gimp",    asset=bytes, intent="new_layer")
send_to(target="resolve", asset=bytes, intent="append_timeline")
start_workflow(target="guild_video",  asset=bytes, preset="wan22_i2v_lightning",
               reply_to="gimp", intent="i2v_ref")
```

Backed by one helper in each language (`cross_interface.send_to()` in Python; equivalent in Lua/JS).

### G9 — `capabilities`-aware menu generation
Right now "Send to X" menus are hand-written per plugin. Instead, each plugin could generate them dynamically by querying `/api/interfaces` for peers with `send_image` or `receive_image` capability and rendering chips for each. That way when a NEW plugin joins the family it auto-appears in everyone's menus.

---

## 4. What "maximum communication benefit" looks like end-to-end

A concrete reimagining of the user's example flow once G1–G9 land:

```
User in Darktable:
  [Send to ▾] — shows live chips: GIMP ● Resolve ● Guild-Video ● ST ○ (greyed)
  Picks "GIMP (new layer)"
    → publishes asset with intent="new_layer_on_current",
      workflow_run_id=wf_abc, reply_to=darktable

GIMP:
  Receives SSE event for its inbox, auto-opens a notification toast:
    "Darktable sent you an image — add as layer?"
  User clicks Accept → active document gains a new layer.
  Status bar shows "Workflow: wf_abc (2/?)"

User continues editing in GIMP, clicks [Continue ▾]:
  Chips offered: "Guild-Video (I2V)" | "Resolve (as still)" | "Send back to Darktable"
  Picks "Guild-Video (I2V)" → wan22_i2v_lightning preset, reply_to=gimp

Guild:
  Creates shot, attaches ref, renders. Emits shot.ready when done.
  Per G7, GIMP's SSE handler filters for meta.reply_to==gimp
  GIMP shows toast: "Your I2V video is ready — view / extract last frame?"

User clicks "Extract last frame":
  Per G6, Guild extracts final frame via ffmpeg → publishes back to GIMP
  with intent="new_document", workflow_run_id=wf_abc, reply_to=gimp

GIMP opens the frame as a new doc; status bar shows "Workflow: wf_abc (5/?)"
User edits, clicks [Continue ▾]: chips include "Send back to Resolve as last-frame
for this shot" — because workflow_run_id links them back.
```

Everything in that flow is buildable on primitives that already exist (AssetGallery, EventBus, Mailbox, SSE, /api/interfaces). No new infrastructure. Just:
- Pick up presence data each plugin already has access to (G1, G2)
- Grow `meta` to carry intent + workflow_run_id (G3, G4)
- Add per-plugin "Send to Guild-Video" action (G5)
- Add frame-extraction (G6)
- Filter SSE per plugin (G7)
- Shared helper + dynamic menus (G8, G9)

---

## 5. Does this change the "reduce Guild dependency" story?

**Yes — it strengthens it.** Cross-app discovery + coordination is the one thing the Guild is genuinely needed for. This is NOT something that can move to ComfyUI (custom ComfyUI nodes can't broker presence across desktop apps). It's NOT something plugins can do peer-to-peer without a broker (mDNS/port-scan is fragile).

Combined with the deep-audit finding (Option C moves video off the Guild), the clean architectural split becomes:

| Concern | Owner | Why |
|--|--|--|
| Generation (image, video) | **ComfyUI** (+ Spellcaster custom routes post-Option C) | Hardware-local compute; already Python-capable |
| Canon / workflow builders | **`spellcaster_core`** (single source, mirrored across Python hosts) | Must be Python for ComfyUI integration |
| Cross-app discovery + coordination | **Guild** | Presence needs a broker; legitimately long-lived process |
| Durable state (shotboard, variations) | **Guild** | User-session-persistent; UI-backed |
| Each plugin's UI / local workflows | **plugin itself** | Native feel matters |

The Guild stops being a "generation middleware" and becomes an **orchestration + coordination service** — a much cleaner role. Option C frees it from the former; G1–G9 strengthen the latter.

---

## 6. Recommended sequencing (ranked by leverage / cost ratio)

| # | Item | Size | User-visible impact |
|--|--|--|--|
| 1 | **G2 — ST heartbeat** | ~20 LOC | Closes a real gap; ST appears online |
| 2 | **G1 — presence UI per plugin** | ~50 LOC × 3 plugins | "Send to" chips light up/grey out live |
| 3 | **G3 — asset intent field** | ~30 LOC schema + 3 receiver handlers | Unlocks new-layer / i2v-ref / etc. semantics |
| 4 | **G9 — capabilities-driven menus** | ~40 LOC × 3 plugins | Adding a new plugin propagates automatically |
| 5 | **G4 — workflow-run-id** | ~10 LOC + UI in Guild | Enables chaining UX |
| 6 | **G5 — "Send to Guild-Video" action in each plugin** | ~50 LOC × 3 plugins | Completes the user's example flow |
| 7 | **G6 — shot frame extraction** | ~20 LOC + ffmpeg | Enables "return last frame" |
| 8 | **G7 — per-plugin SSE filter** | ~20 LOC × 3 plugins | Toast-on-ready for the sender |
| 9 | **G8 — unified cross-app helper** | refactor | Long-term maintenance win |

Items 1–4 alone deliver most of the UX win. Items 5–7 complete the Darktable-to-GIMP-via-I2V flow. Item 8/9 are hygiene — do after the above is stable.

---

## 6.5 Seamless zero-config detection — move presence to ComfyUI

The prior sections assume presence lives in the Guild's `/api/interfaces`. That means a user who runs GIMP + Darktable but NOT the Guild gets no cross-app discovery at all, and installing a new plugin doesn't magically light up peers' menus.

**Cleanest fix: make ComfyUI-Spellcaster the presence broker.** Every Spellcaster-using plugin already talks to ComfyUI — it's the one hard dependency. Add three routes to the `ComfyUI-Spellcaster` pack:

```
POST /spellcaster/presence/register   body: {key, label, icon, capabilities, version}
POST /spellcaster/presence/heartbeat  body: {key, meta?}                 # every ~20 s
GET  /spellcaster/presence/list       → [{key, label, capabilities, age_s}, ...]
```

Custom-node process holds `{key: {registered_at, last_heartbeat, meta}}` in memory. Stale entries (>30 s) auto-drop.

### Zero-config walkthrough

1. User installs GIMP plugin. On load, `_get_cross_interface_client()` — or a new `_register_with_comfyui()` — POSTs `/spellcaster/presence/register`. No peers yet → GIMP's cross-app menu shows nothing beyond its own actions.
2. User later installs Darktable plugin. Darktable's first boot registers against the same ComfyUI. Darktable's menu render (or a 30 s poll) fetches `/presence/list` → sees `[gimp]` → renders a "Send to GIMP" chip with GIMP's declared capabilities.
3. GIMP's next cross-app-menu open fetches the list → sees `[darktable]` → renders "Send to Darktable".
4. No reconfiguration, no Guild. Pure discovery via the ComfyUI both plugins already talk to.

### Why this beats the current Guild-hosted registry

- Every Spellcaster user runs ComfyUI; not everyone runs the Guild.
- Plugin↔ComfyUI is already a mandatory connection — presence calls are effectively free.
- Guild remains **optional**: install it to gain shotboard, chat, rich cross-app messaging — but discovery works without it.
- Lines up with Option C (AUDIT_CROSS_APP_DEEP.md): ComfyUI becomes the authoritative HTTP home for plugin-facing services; Guild is orchestration + cross-app bus when installed.

### What Guild still adds when installed (and why it stays relevant)

- **Durable asset delivery** (AssetGallery content-hash store + Mailbox + SSE fan-out) — plugins can receive assets while they were offline.
- **Shotboard, chat, variation groups, calibration** — UI-resident state that has no analog in ComfyUI.
- **Richer presence metadata** — `online_local` vs `online_remote` distinction (antenna-relayed hosts) that ComfyUI has no native concept of.

### Fallback chain (robust to any installation permutation)

Every plugin's presence query does this in order:

```
peers = []
# 1. Ask ComfyUI-Spellcaster — the baseline, always present if Spellcaster is installed.
try:  peers += comfyui_spellcaster.GET("/spellcaster/presence/list")
except: pass
# 2. Ask Guild — richer data (online_local/remote, last_meta) when running.
try:  peers += guild.GET("/api/interfaces")["interfaces"]
except: pass
# 3. Dedup by key; prefer Guild's richer record where both exist.
return dedup_prefer_guild(peers)
```

Works when:
- Guild off, ComfyUI-Spellcaster pack installed → presence via ComfyUI only ✓
- Guild on, pack not yet registered → presence via Guild only ✓
- Both → union, richer record wins ✓
- Neither → single-plugin mode, no cross-app chips rendered (correct) ✓

### Size

~40 LOC of Python for the ComfyUI-Spellcaster route file (mirrored to NSFW variant by existing build). ~20 LOC per plugin for (register + heartbeat + list-consumer). Net cost is small; the hard part is the per-plugin UI wiring (which is G1 in the table below).

### Sequencing notes

This gets added to §3 as a PREREQUISITE for G1 (presence UI) rather than a separate item — because the point of G1 is to *consume* presence data, and by moving the source to ComfyUI we make G1 work without Guild.

So the updated table becomes:

| # | Item | Cost | Depends on |
|--|--|--|--|
| 0  | ComfyUI-hosted presence (/spellcaster/presence/*) | ~40 LOC in pack | — |
| 1a | Each plugin registers + heartbeats against ComfyUI | ~10 LOC × 4 plugins | 0 |
| 1b | Each plugin queries /presence/list → dedup with Guild's /api/interfaces | ~15 LOC × 4 plugins | 0, 1a |
| 1c | Each plugin renders chips dynamically from the merged peer list | ~30 LOC × 3 plugins | 1b |
| 2  | Asset-level `intent` field + receiver handlers (G3) | ~100 LOC | 1c |
| 3  | Workflow-run-id propagation + chaining UX (G4) | ~50 LOC + UI | 2 |
| ...| | | |

Items 0 + 1a + 1b are the minimum to deliver the user's stated feature: **install a new plugin, the others discover it without any config, without the Guild running**.

---

## 7. What I recommend as the next concrete step

**Say "go" and I'll implement the seamless-detection minimum:**
1. Add ComfyUI-hosted presence routes (§6.5 item 0) — ~40 LOC in `ComfyUI-Spellcaster`, mirrored to NSFW variant.
2. Wire every plugin to register + heartbeat + query (§6.5 items 1a + 1b) — ~25 LOC per plugin.
3. Close the ST heartbeat gap (G2) as a drive-by — another ~10 LOC.

That delivers the user's target outcome: **install a new plugin, the others see it and offer new menu options, no Guild required**.

Phase-9 extras we can pick up after the minimum lands:
- G3 asset `intent` field (unlocks new-layer / i2v-ref / return-edit semantics)
- G4 workflow-run-id (enables chained workflow UX)
- G1c dynamic chip rendering (replace hand-written chips with capability-driven ones)
- G5 "Send to Guild-Video (I2V)" action per plugin — completes the user's example flow

Or we go back to Option C / sentinel menu gating / end-to-end asset trace. All open tracks; pick one.
