# Phase 9 — WebSockets + ETN Inline Transport: Spec & Audit

**Date:** 2026-05-01
**Status:** Retrospective audit of `b512255` (landed canonical-only on `main` 2026-05-01 11:07 PT, **not yet pushed**, **not yet mirrored** to surfaces 2–6)
**Scope:** `comfyui-spellcaster/spellcaster_core/{comfy_ws.py, dispatch.py, node_factory.py}`, `tests/test_phase9_ws.py`
**Authoring intent:** Close out `HANDOFF_SPELLCASTER.md:49–52` (the prep-work asks: *protocol shape*, *6-surface audit*, *failure-mode matrix*) — but **as documentation of what shipped**, not as forward design. The implementation already exists; this doc is the spec the code now embodies.

---

## 1. Why Phase 9

Two distinct wins, shipped together (`EVAL_LANGGRAPH_COMFYSCRIPT.md:72-76, 116-118, 132-139`):

| Win | Mechanism | Magnitude |
|-----|-----------|-----------|
| Kill the `/history` poll race | Subscribe to `/ws?clientId=…` *before* posting `/prompt`; listen for `executing` with `node==None` | Eliminates a real failure mode for any workflow that completes in <2 s on a warm cache (every poll loop tick is 500 ms) |
| Eliminate filesystem round-trip on output | `SaveImageWebsocket` (core) / `ETN_SendImageWebSocket` (Acly) emit image bytes as binary ws frames; nothing lands in `output/` | ~50–200 ms saved per image **and** privacy: no on-disk artefact for the privacy-cleanup pass to chase |

A third, paired win — input-side `ETN_LoadImageBase64` — eliminates `POST /upload/image` + `GET /view` for inputs by embedding base64 in the prompt JSON. Together they're "fully filesystem-free I/O" for Spellcaster-authored workflows.

---

## 2. Protocol shape

### 2.1 Endpoint & connection

```
ws://{host}:8188/ws?clientId={client_id}        # http server → ws
wss://{host}:8188/ws?clientId={client_id}       # https server → wss
```

`comfy_ws._build_ws_url` derives scheme + host from the existing `server` argument (`http://` → `ws://`, `https://` → `wss://`, no scheme → `ws://`); strips a trailing `/`. `client_id` is a random `uuid.uuid4().hex` per call — **not** reused across dispatches, so each call gets an isolated message stream.

### 2.2 Race-free order (load-bearing)

```
1. ws.connect(/ws?clientId=ID)            # subscribe FIRST
2. POST /prompt {prompt: …, client_id: ID}
3. listen until executing.node==None && executing.prompt_id==pid
```

Reverse order races: ComfyUI may have already finished the workflow and emitted the done signal between (2) and (1), at which point the listener never sees it. `comfy_ws.py:298-303` makes this explicit in the docstring; `comfy_ws.submit_and_listen` enforces it (connect at line 317, submit at line 338).

### 2.3 `/prompt` body

```json
{
  "prompt":     <workflow JSON>,
  "client_id":  "<uuid hex>",
  "extra_data": {…optional…}
}
```

The `client_id` field is **required for the binary-frame return path**. Without it, ComfyUI emits the binary frame to whatever ws happens to be in its registry (last-connected wins); with it, the frame goes only to the matching socket. `comfy_ws.py:197-208`.

### 2.4 Text messages observed

ComfyUI broadcasts every message to every connected `client_id`. We filter by `data.prompt_id == our_prompt_id` when present (`comfy_ws.py:382-384`).

| `type` | Action | Notes |
|---|---|---|
| `execution_start` | Progress emit `ws.exec_start` | First message after submit |
| `execution_cached` | Stash `data.nodes` into `WSDispatchResult.cached_nodes` | Optional, useful for diag |
| `executing` (`node==None`) | **Done signal — break loop** | Canonical completion when `data.prompt_id == our_pid` |
| `executing` (`node==<id>`) | Progress emit `ws.executing` | Per-node tick |
| `executed` | Pull `output.images` and `output.gifs` into `file_outputs` | Mirrors poll-path behavior. `gifs` covers VHS_VideoCombine. SaveVideo's `videos` key is **NOT** consumed here (poll path covers it; gap if a builder uses ws + SaveVideo together — see §6) |
| `execution_error` | Format via `_format_execution_error`; break loop with `error_detail` | Caller decides whether to raise based on whether outputs exist (partial-success contract) |
| `execution_interrupted` | Set `interrupted=True`; break loop | Caller raises `RuntimeError` |
| `progress` | Progress emit `ws.progress N/M` | Per-step; informational |
| any other | Recorded in `text_messages`; ignored | Forward-compat |

### 2.5 Binary frame format

```python
header = struct.pack(">II", event_type, image_format)
frame  = header + image_bytes        # 8-byte header + raw image bytes
```

Constants (`comfy_ws.py:75-87`):

| `event_type` | Meaning |
|---|---|
| `1` | Preview/output image (only one we consume) |

| `image_format` | `format_name` |
|---|---|
| `1` | `jpg` |
| `2` | `png` |
| `3` | `jpeg` (legacy) |
| `4` | `webp` |

`_decode_binary_frame` returns `None` on:
- frames shorter than 8 bytes,
- non-`event_type==1` frames (newer ComfyUI versions emit progress as binary with a different shape; we ignore unknown shapes rather than abort).

### 2.6 Result shape (`WSDispatchResult` → `DispatchResult`)

`comfy_ws.WSDispatchResult` is the raw collection. `dispatch.dispatch_workflow` adapts it into the public `DispatchResult`:

```
DispatchResult(
    prompt_id:        str,
    outputs:          [(filename, subfolder, type), …]    # filename-based, same as poll path
    elapsed:          float,
    warnings:         [str, …],
    binary_outputs:   [(format_name, image_bytes), …],    # NEW; ws path only
    transport:        "poll" | "websocket",                # NEW; records which path ran
)
```

**Backward compat:** `binary_outputs` defaults to `[]` and `transport` defaults to `"poll"`. Existing callers reading only `outputs` / `elapsed` / `warnings` are unaffected.

---

## 3. Six-surface audit

Per `CLAUDE.md:33-39`, `spellcaster_core/` is mirrored across **six surfaces**. Edits to canonical (#1) must propagate to the other five (`R1`, `CLAUDE.md:65-67`).

| # | Path | Role | Phase 9 status (post-b512255, pre-mirror) |
|---|---|---|---|
| 1 | `comfyui-spellcaster/spellcaster_core/` | **CANONICAL** | ✅ Has `comfy_ws.py` (478 LOC), `dispatch.py` ws branch (+137), `node_factory.py` ETN helpers (+93) |
| 2 | `plugins/gimp/comfyui-connector/spellcaster_core/` | GIMP dev copy (in this repo) | ❌ OUT OF SYNC — does not yet have any Phase 9 files |
| 3 | `../ComfyUI-Spellcaster/spellcaster_core/` | Public node repo (`laboratoiresonore/ComfyUI-Spellcaster`) | ❌ OUT OF SYNC |
| 4 | `../ComfyUI-Spellcaster-NSFW/spellcaster_core/` | Private node repo | ❌ OUT OF SYNC |
| 5 | `%APPDATA%/GIMP/3.2/plug-ins/comfyui-connector/spellcaster_core/` | Installed copy on this dev machine | ❌ OUT OF SYNC — refreshed by auto-updater on next GIMP launch from #1 once #1 is pushed |
| 6 | `private-distro/plugin/comfyui-connector/spellcaster_core/` | Portable bundle (gitignored mirror) | ❌ OUT OF SYNC — refresh via distro build pipeline |

### 3.1 Mirror plan (deferred — out of scope for this branch)

R1 says: edit canonical → mirror to other five → verify byte-identical via `md5sum` → commit + push in each repo → run `python nsfw/build_nsfw.py --patch-only --push`.

**Not done in this branch.** This branch only touches surfaces (1) and the GIMP plugin entry point. Surface #2 in particular is the GIMP **dev copy** (sibling to `_spellcaster_main.py`); since the wire-up at `_spellcaster_main.py:12687` does `from spellcaster_core.dispatch import dispatch_workflow`, surface #2 must mirror surface #1 before the wired plugin will actually pick up the ws path. Mirror is a separate, deliberate step (R1 + status verification across all five sibling surfaces).

### 3.2 Mirror surfaces with synchronous-only assumptions

The handoff (§50) asked: *"audit 6 mirror surfaces for synchronous-only assumptions that break with WS."* Assessment of `dispatch.py` consumers in canonical:

| Caller | File:line | Sync-only assumption? |
|---|---|---|
| GIMP plugin main | `plugins/gimp/comfyui-connector/_spellcaster_main.py:12687-12710` | No new assumption; existing call reads `result.outputs` (filename list) only — already compatible. Adding `use_websocket=True` is safe; the new `binary_outputs` field is ignored unless the caller explicitly consumes it. |
| GIMP plugin error fallback | `_spellcaster_main.py:9213` (inside `_get_output_images`) | Imports `extract_execution_error` / `has_usable_outputs` — these are unchanged by Phase 9. Not a wire-up point. |
| Pipeline | `comfyui-spellcaster/spellcaster_core/pipeline.py` | Not audited in this pass — flagged for follow-up if/when builders adopt `save_image_websocket`. |
| Cross-interface consumers | `cross_interface.py`, `mailbox.py`, `event_bus.py` | The CLAUDE.md note (line 277) flags these as files Phase 9 will rewire; structural refactors deferred. The dispatcher swap in this commit is opt-in per-call, so no cross-interface signature changes were needed. |

**Conclusion:** the Phase 9 implementation as shipped requires zero changes to mirror-surface consumers. The only mandatory follow-up is mirroring the canonical `spellcaster_core/` files to surfaces 2–6.

---

## 4. Failure-mode matrix

Every failure mode the ws path can hit, and the handling. Behavior is parameterised by `ws_fallback_to_poll` (default `True`).

| # | Failure | Where | Detection | `ws_fallback_to_poll=True` | `ws_fallback_to_poll=False` |
|---|---|---|---|---|---|
| F1 | `websockets` package not installed | `comfy_ws._ws_connect` import | `WSDependencyMissing` raised at first connect | Caught by `dispatch.py` at the import-time guard (`dispatch.py:421-434`) → `use_websocket=False`, fall through to poll | `RuntimeError` |
| F2 | `comfy_ws` module itself not importable | `dispatch.py` top of ws branch | `ImportError` | `use_websocket=False`, fall through to poll | `RuntimeError` |
| F3 | TCP connect refused / DNS fail / open timeout | `_ws_connect` → `connect()` | Any exception from `websockets.sync.client.connect` is folded into `WSUnreachable` (`comfy_ws.py:320-324`) | Warn → poll | `RuntimeError("ws dispatch failed: …")` |
| F4 | `POST /prompt` HTTP 4xx/5xx | `_submit_prompt` urlopen | `WSError` carrying first 500 chars of error body (`comfy_ws.py:221-229`) | Warn → poll | `RuntimeError` |
| F5 | `POST /prompt` connection refused / DNS | `_submit_prompt` urlopen | `WSUnreachable` | Warn → poll | `RuntimeError` |
| F6 | `POST /prompt` returns no `prompt_id` | `_submit_prompt` parse | `WSError("did not return a prompt_id")` | Warn → poll | `RuntimeError` |
| F7 | ws receives a binary frame shorter than 8 bytes | `_decode_binary_frame` | Returns `None`; listen loop continues | n/a (silent) | n/a (silent) |
| F8 | ws receives a binary frame with `event_type != 1` | `_decode_binary_frame` | Returns `None`; listen loop continues | n/a (silent) | n/a (silent) |
| F9 | ws receives malformed JSON text frame | listen loop | `json.JSONDecodeError` caught; frame skipped | n/a (silent) | n/a (silent) |
| F10 | Connection drops mid-listen | `ws.recv()` raises | Folded into `WSError("ws connection died mid-listen")` | Warn → poll, **partial state lost** (whatever was already collected on the ws side is discarded; poll path starts over from a fresh `/history` query) | `RuntimeError` |
| F11 | Per-recv timeout (`recv(timeout=…)` returns no message) | listen loop | `TimeoutError` caught; outer deadline checked | continues | continues |
| F12 | Outer deadline (`timeout=300` default) elapsed before done signal | listen loop | `WSTimeout` raised | Warn → poll (poll path then has its own deadline; effectively two timeouts in series for fail-slow case) | `RuntimeError` |
| F13 | `execution_error` and **no** outputs collected | `dispatch.py:453-455` | `RuntimeError("ComfyUI execution failed: …")` | Raise (no fallback — ComfyUI did its job, the workflow itself is bad) | Raise |
| F14 | `execution_error` and **some** outputs collected (partial success) | `dispatch.py:456-460` | Warning appended; result still returned | Returned | Returned |
| F15 | `execution_interrupted` (user clicked cancel in ComfyUI UI) | `dispatch.py:461-464` | `RuntimeError("ComfyUI execution interrupted …")` | Raise | Raise |

### 4.1 Fall-through state model

```
                    ┌────────────────────────────────────────────────┐
                    │ dispatch_workflow(use_websocket=True,          │
                    │                   ws_fallback_to_poll=True)    │
                    └─────┬──────────────────────────────────────────┘
                          │
                          ▼
                  ┌───────────────────┐
                  │ try import ws path│
                  └───┬──────────────┬┘
                      │              │
              ImportError        OK   │
                      │              │
                      ▼              ▼
            ┌──────────────┐  ┌────────────────────┐
            │ fallback     │  │ submit_and_listen  │
            │ → poll path  │  │ (race-free order)  │
            └──────┬───────┘  └─────┬───────────┬──┘
                   │                │           │
                   │       WSError  │           │ WSDispatchResult
                   │                ▼           ▼
                   │      ┌────────────┐   ┌────────────────┐
                   │      │ fallback   │   │ build          │
                   │      │ → poll path│   │ DispatchResult │
                   │      └─────┬──────┘   │ (ws path)      │
                   │            │          └────────────────┘
                   ▼            ▼
              ┌────────────────────┐
              │ historical /history│
              │ poll loop          │
              └────────────────────┘
```

The poll path is **untouched** by Phase 9. Anything that worked before still works the same way.

### 4.2 Privacy cleanup interaction

The historical privacy-cleanup pass (`spellcaster_core/privacy.py:cleanup_server_files`) wipes server-side files after dispatch. Phase 9 honors it for the **filename-based** outputs in mixed-mode workflows, and skips it for binary-only outputs (nothing landed on disk to wipe). `dispatch.py:480-489`.

---

## 5. Adoption — caller opt-in

### 5.1 Minimum change: turn on ws path, no inline transport

Pass two kwargs at the call site:

```python
result = dispatch_workflow(
    server, workflow,
    use_websocket=True,
    ws_fallback_to_poll=True,    # default; explicit for clarity
    # …existing kwargs unchanged…
)
```

Effect: kill the `/history` poll race for any workflow shorter than the poll period. **Zero builder changes required.** `result.outputs` still contains the filename list; `result.binary_outputs` will be empty (no `SaveImageWebsocket` node in the workflow → no binary frame).

### 5.2 Full inline transport: replace SaveImage with ws-output node

Builders in `workflows.py` that today call `node_factory.save_image(...)` can opt into `save_image_websocket(...)` (core, PNG only) or `etn_send_image_websocket(...)` (Acly's pack, PNG/JPEG). The dispatcher then surfaces the bytes via `result.binary_outputs`. The caller is responsible for writing to a temp file or feeding directly to the consumer (e.g. PIL).

### 5.3 First adopter — GIMP plugin

The natural first adopter is the GIMP dispatch call at `plugins/gimp/comfyui-connector/_spellcaster_main.py:12705`:

- Already imports `dispatch_workflow` from canonical (the shipped surface)
- Reads `result.outputs` and feeds into `_precache_results(server, images)` → `_repatriate_outputs(...)` → privacy-cleanup pass
- Currently has nothing reading `result.binary_outputs`

Wiring plan (next commit on this branch):

1. Add `use_websocket=True, ws_fallback_to_poll=True` to the call.
2. After dispatch, fold any `result.binary_outputs` into `_download_cache` by writing the bytes to a temp file and synthesising a `(filename, "", "output")` key — so downstream code paths (precache, repatriate, GIMP-side import) see binary outputs uniformly with file outputs.
3. No builder changes in this commit — builders keep emitting `SaveImage`, so `binary_outputs` is empty in practice. The fold-in is defensive: when (and if) builders adopt `save_image_websocket` later, the GIMP plugin already consumes them correctly.

### 5.4 Surfaces requiring sync before the GIMP plugin sees the new path

`_spellcaster_main.py` does `from spellcaster_core.dispatch import dispatch_workflow`. The Python `sys.path` inside the GIMP plugin runtime resolves this to **surface #2** (`plugins/gimp/comfyui-connector/spellcaster_core/`) — *not* canonical #1. Therefore:

> Until surface #2 is mirrored from canonical (R1 step 1 of 5), the GIMP plugin will resolve the **old** `dispatch_workflow` signature and silently drop the new kwargs (Python: `**kwargs` would catch them, but `dispatch_workflow` does not take `**kwargs`, so `TypeError: unexpected keyword argument 'use_websocket'`).

Mitigation in the wiring commit: pass the kwargs via `**({...} if ws_supported else {})` guard, or feature-detect via `inspect.signature(dispatch_workflow).parameters`. The simplest path is to mirror surface #2 in the same branch, but that's an R1 step requiring its own discipline. Decision: **feature-detect** (graceful degrade if surface #2 hasn't been mirrored) — see §6 open question 1.

---

## 6. Open questions / known gaps

1. **Surface-mirror coupling:** the GIMP wire-up effectively requires surface #2 to be mirrored before it takes effect. The wiring commit will use `inspect.signature` feature detection so that an un-mirrored surface #2 silently keeps the poll path instead of `TypeError`-ing on import. Tracked but not fixed by this branch.
2. **`SaveVideo` (`videos` key) on the ws path:** `_collect_outputs_from_executed` reads `images` and `gifs` but not `videos`. If a builder later combines `use_websocket=True` with `SaveVideo`, the video filename will be missed. Low-priority — no current builder does this.
3. **Partial state on mid-listen drop (F10):** `ws_fallback_to_poll=True` discards the partial ws state and re-runs poll. For a long workflow that has already produced ¾ of its outputs over ws, the poll path then queries `/history` for the same `prompt_id` — which will succeed and return the full set, so this is correct, but it's not optimal (the ws path's collected `binary_frames` are *lost* because they're not in `/history`). If a workflow used `save_image_websocket` and the connection dropped, those frames are gone — the poll path can only recover **filename-based** outputs. Documented for future hardening if it becomes a real failure mode.
4. **`websocket-client` fallback:** the docstring at `comfy_ws.py:55-61` mentions falling back to the older `websocket-client` package if `websockets` is unavailable — but the fallback is "documented but not implemented." Low priority because `websockets` is bundled.
5. **Header-shape drift in newer ComfyUI:** `_decode_binary_frame` returns `None` on unknown event types, which is correct forward-compat behavior. If ComfyUI adds a new event type we want to consume, the listener silently drops it. No alarm; manual update required when that happens.
6. **Per-call new `client_id`:** each dispatch generates a fresh UUID. ComfyUI does not require persistent client IDs (in fact, broadcasting + filtering by `prompt_id` makes per-call IDs cleaner). No issue.

---

## 7. Verification status

- `python tests/test_phase9_ws.py` (with `PYTHONPATH=comfyui-spellcaster`): commit message reports **28/28 passed**. Re-verification deferred to the wiring commit's CI step.
- Sibling test sweep at the time of `b512255`: clean (the only failures — `test_quality_boost` 3/54, `test_video_layer` ImportError — reproduce on the pre-Phase-9 tree).

---

## 8. Refs

- `comfyui-spellcaster/spellcaster_core/comfy_ws.py` — the ws client
- `comfyui-spellcaster/spellcaster_core/dispatch.py:34-58` — `DispatchResult` shape + new `binary_outputs` / `transport` fields
- `comfyui-spellcaster/spellcaster_core/dispatch.py:246` — `dispatch_workflow` signature with `use_websocket` / `ws_fallback_to_poll`
- `comfyui-spellcaster/spellcaster_core/dispatch.py:421-498` — ws branch (import guard, submit_and_listen call, result construction)
- `comfyui-spellcaster/spellcaster_core/node_factory.py:1260-1335` — ETN helpers + `SaveImageWebsocket`
- `tests/test_phase9_ws.py` — 28 tests, custom runner, mocks `websockets.sync.client.connect`
- `_dev_docs/EVAL_LANGGRAPH_COMFYSCRIPT.md:72-76, 116-118, 132-139` — original "ship the lower-risk transport upgrade first" rationale
- `_dev_docs/ARCHITECTURAL_STUDY_2026-04-30.md` — sprint-1 #3, research-doc PARTIAL items
- `HANDOFF_SPELLCASTER.md:49-52, 122` — prep-work asks (this doc closes them out as retrospective audit) and the "DO NOT START Phase 9 yet" advisory (overtaken by `b512255` 3 hours after the handoff was written)
- `INTERNAL_ROADMAP_2026-04-30.md:425-430` — calendar slot Wk 20–21 (delivered Wk 1)
- `CLAUDE.md:33-39, 65-67, 273, 277, 286-291` — six-surface mirror canon, Phase 9 status row (now stale), cross-interface "rewire" note
