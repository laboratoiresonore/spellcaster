# Cross-App Deep Audit — Option C readiness for video direct-to-ComfyUI

**Prior pass:** [AUDIT_CROSS_APP_ARCHITECTURE.md](AUDIT_CROSS_APP_ARCHITECTURE.md) — identified that ST + Darktable currently depend on the Guild only for **video generation** (and cross-app messaging, which is the Guild's correct role). Recommended Option C: expose the Python canon (`build_wan_video`, `build_ltx_video`) to JS/Lua clients without the Guild hop.

This deep audit digs into Option C and finds a **sub-option worth picking**.

---

## 1. Critical discovery: the Guild is NOT just a workflow builder

Reading `scaffold/video_bridge.py` plus `scaffold/video_workflow_dispatch.py` revealed the Guild's video path is richer than the prior audit assumed. When a client POSTs to `/api/video/shots`, it hands off to a `VideoBridge` that routes between **two entirely different runtimes**:

| Backend | What it is | Relevance to Option C |
|--|--|--|
| `comfyui` | Calls `spellcaster_core.workflows.build_wan_video` → queues to ComfyUI | THIS is the path the Option C bypass is about |
| `wangp`   | A separate gradio server at `localhost:7860` running Kijai's WanGP | Cannot be bypassed; not a ComfyUI workflow |
| `hybrid`  | Mixed | Minor |

The Guild also owns **durable shot state** (`shotboard.json`), **queue + concurrency + pause/resume** (`VideoBridge._render_sem`, `render_next`, `queue_status`), and **cross-render orchestration** (variation groups, continuity snapshots, activity log).

**Consequence for Option C:** removing the Guild hop for the `comfyui` backend is straightforward. Removing it for `wangp` is not (WanGP is a completely separate server the Guild federates). And the shotboard/queue state is a legitimate piece of Guild-resident functionality that ST + Darktable callers don't care about but the Guild UI does.

So Option C becomes: **let ST + Darktable bypass the Guild for the `comfyui` backend specifically**, while Guild remains authoritative for `wangp` and for anything that wants the shotboard UX.

---

## 2. The four sub-options of Option C, evaluated

### C.1 — Monolithic ComfyUI custom node
Write `SpellcasterWanI2V` + `SpellcasterLtxI2V` that do the whole pipeline internally (load models, inject LoRAs, run both samplers, decode).

**Verdict: rejected.** `build_wan_video` is 3,406 lines. Replicating its logic inside a node means maintaining TWO copies of the canon that won't stay in sync. The phase-1 audit already deleted a 488-line JS re-implementation that had drifted. This sub-option recreates that problem in Python-to-Python form.

### C.2 — ComfyUI custom HTTP route
Register `POST /spellcaster/animate` on ComfyUI's own web server (via `PromptServer.instance.routes`). The route:
1. Takes `{image_filename, prompt, negative, length, turbo, preset_override?}`
2. Calls `spellcaster_core.workflows.build_wan_video(...)` → workflow dict
3. Queues the workflow via `PromptServer.instance.prompt_queue.put_async(...)`
4. Returns `{prompt_id}` — same shape as ComfyUI's own `/prompt` endpoint
5. Client polls `/history/<prompt_id>` as usual

**Verdict: recommended.** Details in §3 below.

### C.3 — ComfyUI custom route that returns a workflow JSON (no dispatch)
Register `POST /spellcaster/build_wan_workflow` that just returns `build_wan_video(...)` as JSON. Client then submits to `/prompt` itself.

**Verdict: marginally worse than C.2.** Adds a roundtrip and duplicates the submit logic in every client. C.2 gives the simpler contract.

### C.4 — Keep the Guild in the loop; just reduce its role
Continue routing video through Guild's `/api/video/shots`. ST/Darktable stay as-is.

**Verdict: rejected.** The user's stated goal is that the Guild be a failsafe, not a dependency.

---

## 3. C.2 — full design

### 3.1 Route registration in ComfyUI-Spellcaster `__init__.py`

```python
from server import PromptServer  # ComfyUI's singleton
from aiohttp import web
import uuid as _uuid

# Imports from the already-bundled spellcaster_core (arrives with this pack).
from spellcaster_core.workflows import build_wan_video, build_ltx_video
from spellcaster_core.video_presets import (
    detect_wan_preset, wan_turbo_kwargs,
    detect_ltx_preset, ltx_mode_kwargs,
)

def _queue_workflow(workflow: dict, client_id: str | None = None) -> str:
    """Queue a workflow on ComfyUI's prompt queue; return prompt_id.
    Mirrors ComfyUI's own /prompt handler internally so ST/Darktable
    clients see the same contract they already use for /prompt."""
    prompt_id = str(_uuid.uuid4())
    client_id = client_id or "spellcaster"
    # (1, prompt_id, workflow, extra_data, outputs_to_execute)
    PromptServer.instance.prompt_queue.put((
        1,            # priority (0 = system; 1 = user)
        prompt_id,
        workflow,
        {"client_id": client_id},
        ["9"],        # SaveImage node id (see build_wan_video output)
    ))
    return prompt_id


@PromptServer.instance.routes.post("/spellcaster/animate/wan")
async def _animate_wan(request: web.Request):
    body = await request.json()
    image_filename = body.get("image_filename", "").strip()
    if not image_filename:
        return web.json_response({"error": "image_filename required"}, status=400)
    prompt = (body.get("prompt") or "").strip()
    negative = body.get("negative") or ""
    length = int(body.get("length") or 33)
    turbo = bool(body.get("turbo", True))
    seed = int(body.get("seed") or 0)

    # Canonical preset detection. comfy_url=None uses folder_paths
    # directly (no HTTP) — the preset helper supports both modes.
    preset = detect_wan_preset(None)
    if preset is None:
        return web.json_response({"error": "no WAN I2V model installed"}, status=503)

    workflow = build_wan_video(
        image_filename=image_filename,
        preset=preset,
        prompt_text=prompt,
        negative_text=negative,
        seed=seed,
        length=length,
        **wan_turbo_kwargs(turbo),
    )
    prompt_id = _queue_workflow(workflow, client_id=body.get("client_id"))
    return web.json_response({
        "prompt_id": prompt_id,
        "preset": preset["high_model"],
        "turbo": turbo,
    })


@PromptServer.instance.routes.post("/spellcaster/animate/ltx")
async def _animate_ltx(request: web.Request):
    # Same shape; delegates to build_ltx_video + ltx_mode_kwargs.
    ...
```

**Size: ~80 lines** for WAN + LTX + LOAD_IMAGE upload proxy. No logic duplication; every line is a thin shim.

### 3.2 Client-side contract

ST's `server-plugin.js` today POSTs to `GUILD_URL/api/video/shots` (create → attach → render → poll → fetch). After C.2, the whole flow collapses to:

```javascript
// 1. Upload reference (ST already has this path via /upload/image)
await uploadToComfyUI(imageBuf, 'ref.png');

// 2. Kick off the WAN animation (one HTTP call, no Guild involved)
const { prompt_id } = await fetchJSON(
    `${COMFYUI_URL}/spellcaster/animate/wan`,
    { method: 'POST',
      body: JSON.stringify({ image_filename: 'ref.png', prompt, length, turbo }) });

// 3. Poll /history/<id> — the existing dispatchWorkflow helper already does this
const result = await waitForHistory(prompt_id, 600_000);
```

Net diff for `server-plugin.js`:
- Delete `_animateViaGuild()` (~100 lines)
- Add `_animateViaComfy()` (~40 lines) using existing `dispatchWorkflow` primitive
- `/animate` endpoint routes to `_animateViaComfy` first; falls through to Guild `/api/video/shots` only when the ComfyUI route returns 404 (Spellcaster node pack not installed)

### 3.3 Guild becomes the failsafe, as the user wanted

After C.2, the Guild's `/api/video/shots` serves three residual purposes:
1. **WanGP backend users** — who don't want ComfyUI at all. Still needs Guild.
2. **Shotboard UX** — durable named shots, scenes, variation groups. Guild-resident state, has its own UI.
3. **Failsafe** — when `/spellcaster/animate/*` returns 404 (pack not installed or too old), clients can fall back to Guild.

ST + Darktable callers who just want "generate one video from a prompt" never need the Guild.

---

## 4. Blockers, risks, and open questions

### 4.1 ComfyUI route API stability
`PromptServer.instance.routes.post(...)` has been the standard custom-node HTTP-route API since ComfyUI added aiohttp-based routing (~2023). Widely used by ComfyUI-Manager, rgthree-comfy, was-node-suite, and dozens of other packs. **Stable in practice.**

The `prompt_queue.put(...)` tuple shape has shifted once before (added `outputs_to_execute` around 2024). Low risk of further change; worth a version gate if it does.

### 4.2 No auth on ComfyUI
ComfyUI doesn't authenticate `/prompt` today; by extension our `/spellcaster/animate/*` is also unauthenticated. Same as status quo — anyone who can reach ComfyUI can already submit workflows. Not a new exposure.

### 4.3 `detect_wan_preset(None)` — need to verify
The preset detector currently takes `comfy_url: str` and probes over HTTP. Inside a ComfyUI route we're in-process; we'd want to pass `None` and have it switch to `folder_paths.get_filename_list(...)` instead. **Requires a small tweak** to `detect_wan_preset` + `probe_object_info_choices` to accept a `None` url and use local paths. Maybe 10 lines.

### 4.4 Queue concurrency + progress reporting
ComfyUI's built-in queue already handles concurrency, progress (`/ws` progress events), and cancellation (`/interrupt`). The C.2 route inherits all of this for free. The cancel endpoint I added in phase-8 (`POST /animate/cancel`) can be replaced with a ComfyUI-native `/interrupt` call when the prompt is current.

### 4.5 The `image_filename` must already be on ComfyUI
ComfyUI's `LoadImage` node references files in its `input/` dir. Clients upload via `POST /upload/image` before POSTing to our route. Already how GIMP + the current ST server plugin do it; no change.

### 4.6 Shotboard / durable state
If a user invoked `/animate` through C.2, the shotboard won't see it. That's a **feature, not a bug**: shotboard is the Guild UI's state; clients that want shotboard integration keep calling Guild's `/api/video/shots`. Clients that just want "one video now" go direct.

### 4.7 WanGP users
Unaffected. Their workflow still goes Guild → WanGP. Option C.2 just adds a new fast-path for ComfyUI backend users.

---

## 5. Migration checklist (if approved)

| # | Change | Where | Size |
|--|--|--|--|
| 1 | Add `/spellcaster/animate/wan` + `/spellcaster/animate/ltx` routes | `ComfyUI-Spellcaster/__init__.py` | ~80 LOC |
| 2 | Same in NSFW variant | `ComfyUI-Spellcaster-NSFW/__init__.py` | ~80 LOC (copy) |
| 3 | Teach `detect_wan_preset` + `detect_ltx_preset` to read from `folder_paths` when `comfy_url is None` | `spellcaster_core/video_presets.py` | ~10 LOC |
| 4 | Sync core change across the four `spellcaster_core/` copies | CLAUDE.md §3 | mechanical |
| 5 | Add `_animateViaComfy()` to ST server plugin; prefer it; fall back to Guild on 404 | `plugins/sillytavern/spellcaster-st/server-plugin.js` | ~40 LOC replace ~100 LOC |
| 6 | Same for Darktable — swap `guild_create_shot` path for direct ComfyUI POST | `plugins/darktable/comfyui_connector.lua` | ~30 LOC replace ~60 LOC |
| 7 | Update tests to cover both paths (ComfyUI route preferred, Guild fallback on 404) | `plugins/sillytavern/spellcaster-st/test/` | ~20 LOC |
| 8 | Document in each plugin's README | READMEs | small |

**Net LOC delta: smaller codebase.** Deleting more client code than we add server-side.

---

## 6. Out of scope for Option C (good reasons to keep Guild)

Do NOT try to direct-to-ComfyUI these:

- **Cross-app send / receive** (`/cross/send`, `/sc-inbox`, SSE). Fundamentally cross-process. Guild is the right broker.
- **Shotboard** (named shots, scenes, variations, continuity). Guild UI state.
- **WanGP backend**. Separate runtime, not ComfyUI.
- **Calibration / wizard flows** that span multiple generations and need state between them.
- **Resolve bridge**. Architectural reason — embedded Python host.

---

## 7. Remaining deep-audit candidates (not yet done)

The original cross-app architecture review listed four candidates. One is fully covered here (Option C readiness). The other three remain:

1. ✅ **Option C implementation readiness** — this document. Recommended: C.2 (custom HTTP route).
2. ⏳ **Concrete migration diff for ST + Darktable** — waiting on approval of C.2 before I write actual code.
3. ⏳ **End-to-end cross-app trace** (GIMP→ST asset path with durability / dedup / ordering under reconnect).
4. ⏳ **Sentinel-based menu gating port** (shared `feature_sentinels.json` + JS/Lua readers replicating GIMP's pattern).

Each would be 1–3 hours of focused work. Say **"approve C.2 and do the migration"** to jump to (2), or **"go deep on 3"** / **"go deep on 4"** to pick a different thread.

---

## 8. Executive one-liner

**Recommendation: Option C.2 — register two thin HTTP routes on ComfyUI (`/spellcaster/animate/wan` + `/spellcaster/animate/ltx`) that call the existing Python canon directly. No new code duplication; Guild becomes a failsafe; ST + Darktable get GIMP-style autonomy for video.** ~80 LOC of new Python in `ComfyUI-Spellcaster`; ~130 LOC removed from ST + Darktable; everything else unchanged.
