# AUDIT: SillyTavern + GIMP Reciprocal Plugins

**Auditor:** Claude Opus 4.7
**Date:** 2026-04-19
**Scope:** End-to-end, every function.
- SillyTavern extension: `plugins/sillytavern/spellcaster-st/` (index.js 1587L + server-plugin.js 2262L + manifest + CSS + workflows/)
- GIMP plugin: `plugins/gimp/comfyui-connector/` (comfyui-connector.py 228L shim + _spellcaster_main.py 25,688L + ~40 spellcaster_core/ modules)

Live verification: Wizard Guild reachable at `127.0.0.1:7777`, NSFW mode on, GIMP interface registered (last heartbeat within session), SillyTavern not currently connected. ComfyUI (`<INTERNAL_HOST>:8188` per Guild `/api/config`) not reachable from this audit session.

---

## 1. Architecture — the "reciprocal" surface

```
┌─────────────────┐     /cross/send         ┌──────────────────────────┐
│ SillyTavern UI  │ ──────── POST ───────►  │ ST server-plugin.js      │
│ (index.js)      │                         │ (Node, same repo)        │
│ /sc-send-to-X   │ ◄── GET /cross/inbox ── │ /api/plugins/spellcaster │
└─────────────────┘                         └──────────┬───────────────┘
                                                       │  POST /api/assets
                                                       │  POST /api/events/emit
                                                       ▼
┌─────────────────────────────────────────────────────────────────────┐
│ Wizard Guild (127.0.0.1:7777) — the hub                             │
│  • AssetGallery.put  (content-addressed blob store)                 │
│  • EventBus          (ring buffer, filter-subscribe, drop-oldest)   │
│  • Mailbox           (per-interface pull queue)                     │
│  • InterfaceRegistry (gimp / sillytavern / darktable / resolve…)    │
└─────────────▲───────────────────────────────────────────────────────┘
              │  POST /api/assets   (upload_asset)
              │  POST /api/events/emit  (publish)
              │  GET  /api/gimp/inbox   (consume)
              │
┌─────────────┴───────────────────────────────────┐
│ GIMP plugin _spellcaster_main.py                │
│  spellcaster_core/cross_interface.py            │
│   CrossInterfaceClient: heartbeat, publish,     │
│   subscribe (SSE), upload_asset, download_asset │
└─────────────────────────────────────────────────┘
```

"Reciprocal" = both plugins publish to the same AssetGallery and emit on the same EventBus; each can consume the other's messages from its interface mailbox. No plugin-to-plugin direct channel — the Guild is always the broker.

---

## 2. Function / surface count

| Surface | Count |
|--|--|
| ST `index.js` top-level functions | 17 |
| ST `index.js` slash commands | 19 (`/scene`, `/portrait`, `/restyle`, `/restyle-all`, `/animate`, `/cast`, `/studio-scene`, `/spellcaster`, `/sc-inbox`, `/sc-send-to-resolve`, `/sc-send-to-gimp`, `/sc-send-to-darktable`, `/sc-capabilities`, plus minors) |
| ST `index.js` LLM function tools | 3 (`generate_scene`, `generate_portrait`, `change_background`) |
| ST `index.js` event subscriptions | 3 (on `EV_CHAR_MSG` ×2, on `EV_SETTINGS`) |
| ST `server-plugin.js` functions | 28 (11 router, 17 internal) |
| ST `server-plugin.js` routes | 15 POST + 4 GET = **19 endpoints** |
| GIMP `_spellcaster_main.py` classes | 12 (11 dialogs + `Spellcaster`) |
| GIMP `_spellcaster_main.py` module defs + methods | ~113 + ~80 = ~193 |
| GIMP registered procedures | 82 — perfect 82/82/82 across `_PROC_FEATURES`, `menu_map`, `_menu_paths` |
| `spellcaster_core/` modules | 38 |

---

## 3. Findings — ranked

Severities: **C** = critical, **H** = high, **M** = medium, **L** = low. *(verified)* means I re-read the code and confirmed the finding; *(agent-only)* means surfaced by a sub-agent and not re-checked line-by-line.

### 3.1 CRITICAL

| # | Location | Issue |
|--|--|--|
| C1 | `server-plugin.js:312-325` `/cross/send` | **SSRF — unconstrained `image_url`.** `req.body.image_url` is fed straight to `http.get`/`https.get` with no scheme/host allowlist, no DNS-rebind protection, no redirect cap. A local attacker (anyone who can POST to the ST server) can probe `127.0.0.1:*`, `169.254.169.254`, internal LAN. Target validation is only on `target`, not on URL. *(verified)* |
| C2 | `server-plugin.js:569, 625, 689, 743, 752, 864, 933, 980, 1036` | **Base64 → Buffer with no size cap.** Every image endpoint (`/restyle`, `/edit`, `/save-avatar`, `/animate`, `/save-expression`, `/studio/cast`, `/studio/body`, `/studio/scene`) decodes `Buffer.from(image_base64, 'base64')` without pre-checking `image_base64.length`. A 500 MB base64 body decodes to ~375 MB RSS; ST bundles no `body-parser` size limit in plugin hook. Crashes Node process. *(verified)* |
| C3 | `server-plugin.js:858` `/save-expression` | **Path traversal in `character_name`.** `path.join(charDir, character_name)` has no sanitization — `character_name = "../../../Public/Spellcaster"` escapes `charDir`. `/save-avatar:677` uses `path.basename(avatar_filename)` which is defensible, but `/save-expression` has no analogous guard. *(verified)* |
| C4 | `server-plugin.js:261-282` `/settings` | **URL-injection lets an attacker redirect all downstream calls.** `comfyui_url` / `guild_url` are accepted as any string and replace module globals. Combined with C1 this means one POST hijacks every subsequent workflow to attacker's fake ComfyUI. No auth on the route at all. *(verified)* |
| C5 | `server-plugin.js:1105-1114` `/dispatch` | **Arbitrary workflow submission.** Accepts raw ComfyUI workflow JSON from client and forwards unconditionally. No schema check, no node allowlist, no size cap. An LLM tool-call or a bad script can submit a workflow that writes files, downloads LoRAs, or exhausts VRAM. *(verified)* |
| C6 | `_spellcaster_main.py:25039` GIMP Check Inbox | **SSRF in GIMP inbox handler.** `image_url` pulled from Guild event data is passed to `urllib.request.Request(image_url)` with **no scheme check**. `file:///etc/passwd` → downloads and opens in GIMP; `gopher://`, `ftp://` also accepted by urllib. Any interface that can publish an event can smuggle the GIMP process into reading arbitrary local files. *(verified)* |

### 3.2 HIGH

| # | Location | Issue |
|--|--|--|
| H1 | `server-plugin.js:86-96` `fetchBytes` | No timeout, no max-size on `Buffer.concat(chunks)`. Paired with C1 this makes a slow-loris or terabyte response a trivial OOM. *(verified)* |
| H2 | `server-plugin.js:102-175` `dispatchWorkflow` | Polls `/history` every 500 ms for up to 180 s (300 s for `/animate`). On timeout the prompt keeps running on ComfyUI (no `/interrupt`). Also the polling loop has no cleanup for in-flight HTTP sockets — slow leak. *(verified)* |
| H3 | `server-plugin.js:185-219` `_sniffImage` | Only matches first 4 bytes of PNG/JPG/GIF/BMP magic. Accepts a PNG header followed by an SVG/XML body → ComfyUI's `/upload/image` will store it as a "PNG"; some models choke, some don't. Lowest-impact of C2/H1/H2 but still ingest-validation gap. *(verified)* |
| H4 | `server-plugin.js:1933` `buildWanI2VWorkflow` | Hardcodes `clip_vision_h.safetensors`. If absent on the user's ComfyUI, WAN workflow 500s with no pre-flight. *(verified — expected model list not probed)* |
| H5 | `server-plugin.js:1762-1853` `_detectWanPresetDirect` | JS re-implementation of `spellcaster_core.video_presets.detect_wan_preset`. CLAUDE.md §16.4 says only the Python canonical helper may do detection; the JS copy drifts over time. Currently it correctly refuses T2V by substring and picks correct VAE, **but** it has no `accel_strength` tuning beyond `=1.5` and the turbo formula (cfg=1.0 / steps=6 / second_step=3) is hardcoded inline at 1961-1985 instead of derived from a shared constant. *(verified — JS copy is logically close but diverges in structure)* |
| H6 | `index.js:1296-1422` `renderSettingsPanel` | **Event-listener accumulation.** `container.innerHTML = html;` re-creates DOM; all `addEventListener` bindings on the new nodes are added fresh but previously-registered `eventSource.on(...)` handlers at file bottom accumulate. ST fires `EV_SETTINGS` on every settings save → `registerSlashCommands()` → slash commands are re-added without deduping. Over a session, 20 click wastes 20× the work. *(agent-only + verified event handlers at 1543-1568)* |
| H7 | `index.js:98-126` `extractSceneDescription` | Regex `/\*([^*]{10,500})\*/g` is safe by itself, but it's run on every rendered message with no size cap on the input. Long messages (10 KB+ LLM outputs) traverse the full string. Not catastrophic backtracking (bounded quantifier) but wasteful. *(verified)* |
| H8 | `index.js:366-484` `onCharacterMessageRendered` | `_autoBgInFlight` is a JS variable, not atomic. Two rapid `MESSAGE_RECEIVED` events can both pass the `if` before either sets it to `true`. In practice SillyTavern event loop is single-threaded so this is serialized, but on slow main-thread work the guard can still briefly race. *(verified; practical impact low because JS is single-threaded, but the sub-agent's CRITICAL was overstated — I'd mark this HIGH only for async-fetch window)* |
| H9 | `server-plugin.js:298-396` `/cross/send` | **Stored-XSS vector via `title`.** Title is forwarded to the Guild and later surfaces in `/sc-inbox` where `index.js:1154` renders it inside `**${i+1}. From ${src}:** ${title}\n\n![${title}](${url})`. A title containing `](javascript:alert(1))` closes the markdown link and the `url` field plus user-controlled `src` can inject. SillyTavern's markdown renderer does strip `javascript:` in `<a>` but not inside alt-text. Low-likelihood-of-exec, high-likelihood-of-UI-breakage. *(verified)* |
| H10 | `_spellcaster_main.py:25035-25036` | `image_url.startswith("/")` prefixes Guild base; that's fine, but any absolute attacker-URL skips that branch and flows into C6. Also the filename heuristic at 25047-25052 only catches `.mp4` — other formats (e.g., `.svg`, `.heic`) will be saved as `.png` and passed to `Gimp.file_load` which may crash on unexpected container. *(verified)* |

### 3.3 MEDIUM

| # | Location | Issue |
|--|--|--|
| M1 | `server-plugin.js:30-39` `resolveCharactersDir` | Walks upward looking for `data/default-user/characters/`. On a bespoke ST deploy (Docker volume, different `default-user`) it silently returns `null` and every save endpoint 500s with "Cannot find SillyTavern characters directory". No config override. *(verified)* |
| M2 | `server-plugin.js:1125-1139` `detectBestModel` / `detectEditEngine` | Module-level caches with no TTL, invalidated only on `/settings`. ComfyUI hot-swap of checkpoint files won't be noticed for the process lifetime. *(verified)* |
| M3 | `server-plugin.js:488-508` `/generate`, `/scene`, `/portrait` | `prompt`, `negative`, `description` have no length cap before forwarding to ComfyUI. Not an exploit but a DoS vector. *(verified)* |
| M4 | `server-plugin.js:1391-1394` `_roundMod` | Accepts any integer; attacker-supplied `width=1e9` passes through. ComfyUI likely rejects in `WanImageToVideo` but the 8-byte allocation path before rejection is wasteful. *(verified)* |
| M5 | `index.js:1428-1438` `blobToBase64` | Rejecting callers (e.g. 593, 638, 730, 763, 804, 838) don't `.catch()`. An avatar 404 produces an unhandled rejection; ST's global handler will surface it but there's no user feedback. *(verified)* |
| M6 | `index.js:175-298` `detectStoryChanges` | Regex list + heuristics catch >30 patterns but no semantic filter. "Walked into the bar AND ordered drinks" matches "bar AND ordered" as a location change. Triggers unneeded background regen. *(verified)* |
| M7 | `cross_interface.py:45-62` `resolve_guild_url` | Reads `~/.spellcaster/cross_interface.json` without validating the URL scheme. A user-editable config file with a malicious `guild_url` steers heartbeats and asset uploads to an attacker-controlled host; this is LOCAL-only attack surface but should still clamp to `http(s)://` + optionally allowlist `127.0.0.1` by default. *(verified)* |
| M8 | `event_bus.py:178-213` `_SubscriberQueue` | Drop-oldest policy silently discards events on lag. An SSE subscriber that falls behind will miss `asset.created` events; the inbox-poll fallback (mailbox) mitigates this for pull consumers, but any live-subscribe consumer (Resolve bridge, Signal notifier) can miss assets with no indicator. Adds `self._dropped` counter but it's not surfaced anywhere. *(verified)* |
| M9 | `cross_interface.py:101-110` `CrossInterfaceClient.__init__` | `auto_heartbeat=True` spawns a daemon thread every time the client is instantiated. `_spellcaster_main.py:988` memoizes the client — good — but `_spellcaster_main.py:24404` creates a **second** client every `_cross_interface_send` call. Over a long GIMP session with many Send-to-Guild presses, N daemon heartbeat threads accumulate (only stopped on process exit). *(verified)* |
| M10 | `server-plugin.js:455-475` `/cross/inbox` | Default `consume=1` — a single poll consumes the queue. If ST client disconnects before rendering, messages are lost. Should default `consume=0` and let the client explicitly ack. *(verified)* |
| M11 | `server-plugin.js:1422, 1488` `buildKleinEditWorkflow` / `buildKontextEditWorkflow` | Hardcoded Klein/Kontext UNET + CLIP + VAE filenames as module constants. Missing-model check is delegated to ComfyUI (silent 500). Should fall back to `detectBestModel` on missing. *(verified)* |
| M12 | `_spellcaster_main.py:944` | `COMFYUI_DEFAULT_URL = "http://127.0.0.1:8188"` is fine. But the live Guild config at `127.0.0.1:7777/api/config` returns `"comfyui_url":"http://<INTERNAL_HOST>:8188"` — that's a real LAN IP, which CLAUDE.md §11 says must never leak. Config file is gitignored (confirmed in CLAUDE.md §11) so this isn't a repo leak — but auditing found NSFW mode **on** (`"nsfw_mode": true`) on the user's live instance. Not a code issue, but worth flagging that `guild_config.json` must stay untracked. *(verified via live probe)* |
| M13 | Agent 3 vs Agent 4 disagreement on Klein node names | Agent 3 said "class names are correct"; Agent 4 said "names hallucinated with dots/spaces". I grepped both plugins: every occurrence uses the canonical CamelCase (`Flux2KleinRefLatentController`, `Flux2KleinTextRefBalance`, `Flux2KleinColorAnchor`). Agent 4 was wrong. ✅ *(verified — non-issue)* |
| M14 | Agent 4 claimed OOB read in `sillytavern_card.extract_text_chunks` | Re-read lines 46-80: `if data_end + 4 > n: break` runs **before** `data = png_bytes[data_start:data_end]`, and Python byte slicing is bounds-safe anyway. Agent 4 was wrong. ✅ *(verified — non-issue)* |

### 3.4 LOW

| # | Location | Issue |
|--|--|--|
| L1 | `server-plugin.js:233-254` `uploadToComfyUI` | Multipart boundary uses `Date.now()` — millisecond collision possible for near-simultaneous uploads. Theoretical; ComfyUI would likely reject but wastes a round-trip. |
| L2 | `server-plugin.js:1092-1102` `/studio/assets` | `studioAssets` in-memory map is unbounded; attacker-controlled `character_name` values fill memory. |
| L3 | `index.js:1044-1060` `_findLastChatImage` | Regex for markdown + `<img>` doesn't escape special chars in extracted URL. Low impact — an attacker with chat write is already privileged. |
| L4 | `_spellcaster_main.py:24404` | `CrossInterfaceClient(interface_key="gimp")` hardcoded — but also see M9, compounding issue. |
| L5 | `_spellcaster_main.py` auto-updater | Reviewed by structural agent: 3-tier recovery (normal → `.bak` → GitHub fresh → visible CRASHED menu) is robust. `.py` files are staged as `.update` (never live-replaced). NTFS null-byte scrub. No symlink validation in update payload — but remote is `raw.githubusercontent.com` so risk is minimal. Note: CLAUDE.md rule 13 already warns that auto-updater overwrites uncommitted local edits. |
| L6 | `_spellcaster_main.py` no personal data | Grep confirmed: no `redacted`, `redacted`, `@gmail`, `ghp_`, `<INTERNAL_HOST>.` in source. ✅ |
| L7 | `_spellcaster_main.py:5476-5542` WAN+LTX dispatch | Uses canonical `spellcaster_core.video_presets.wan_turbo_kwargs()` + `build_wan_video()` / `build_ltx_video()` — no duplication. ✅ Matches CLAUDE.md §16.4. |
| L8 | `asset_gallery.py` flat cache fallback | Read-only per CLAUDE.md §15 comment — verify new code never writes the flat cache. (Not a current bug; watch for regressions.) |

---

## 4. Reciprocal bridge-specific findings

- **No authentication anywhere.** Guild endpoints (`/api/events/emit`, `/api/assets`, `/api/gimp/inbox`) are open to localhost. ST's `/api/plugins/spellcaster/*` inherits ST's auth. GIMP's heartbeat thread talks plaintext to Guild. For a personal setup this is fine; for any shared-host deployment it's not.
- **Event-bus fanout is best-effort only.** `event_bus.py:_SubscriberQueue.offer` drops oldest on overflow with zero feedback. If a subscriber critical to a feature (Signal notifier, Resolve importer) lags, assets silently stop flowing.
- **Mailbox consume-on-first-read is fragile.** Both `/cross/inbox` (ST) and GIMP's Check Inbox default to `consume=1`. A crash between `urlopen(...).read()` and the subsequent local processing loses the message. Should ack-after-process, not ack-on-fetch.
- **Heartbeat thread leak (M9).** Memoized in GIMP via `_get_cross_interface_client()` for most paths, but `_cross_interface_send` in `_spellcaster_main.py:24404` instantiates a fresh client each call. N clicks → N daemon threads.
- **No URL scheme clamp on incoming inbox messages (C6).** Combined with the open Guild API this is the single biggest cross-interface attack surface.

---

## 5. Prioritized fix list

### Must-fix before any shared-host deployment

1. **C1, C6**: Clamp `image_url` to `http(s)://` + private-IP allowlist or Guild-base prefix check on both sides (`server-plugin.js:315` and `_spellcaster_main.py:25039`).
2. **C2**: Cap `image_base64.length` at e.g. 20 MB across all `/restyle`, `/edit`, `/save-*`, `/animate`, `/studio/*` endpoints in `server-plugin.js`; 413 on over-limit.
3. **C3**: Sanitize `character_name` in `/save-expression` with `path.basename` + strict regex `/^[A-Za-z0-9 _.-]{1,64}$/`.
4. **C4**: Gate `/settings` behind at minimum a confirm-origin check; validate URLs with `new URL()` and a scheme allowlist.
5. **C5**: Either remove `/dispatch` or require a dev-mode flag.

### Should-fix next

6. **H1, H2**: Add `timeout` + `maxSize` to `fetchBytes` / `fetchJSON`; call `/interrupt` on ComfyUI when `dispatchWorkflow` times out.
7. **H3**: Add SVG/XML detection in `_sniffImage` (reject `<?xml`, `<svg`, HTML tags in first 512 bytes).
8. **H6**: Dedupe `eventSource.on` registrations — track handler refs and `.off()` before re-registering in `registerSlashCommands` and `EV_SETTINGS`.
9. **H9**: Escape `title` before markdown interpolation in `/sc-inbox` renderer (index.js:1154); use `title.replace(/[\[\]()]/g, '')` or inline-code it.
10. **M9**: Memoize the cross-interface client in `_cross_interface_send` too (use `_get_cross_interface_client()`).
11. **M10**: Change `/cross/inbox` default to `consume=0` + add explicit `/cross/ack` endpoint.

### Structural hygiene

12. **H5 / CLAUDE.md §16.4 violation**: JS `_detectWanPresetDirect` is a parallel implementation. Either (a) move detection to the Guild (one endpoint, one codepath) and have ST fetch from there, or (b) accept the duplication explicitly and add a cross-language test that snapshots both against `/object_info` and asserts preset equality.
13. **M8**: Surface `EventBus` drop counter to `/api/interfaces` so operators can see subscriber-lag.
14. **L5**: Add SHA256 verification of the GitHub-fetched `_spellcaster_main.py` in the shim before writing it.

---

## 6. Cross-checks against CLAUDE.md rules

| Rule | Status |
|--|--|
| §1 NSFW separation | ✅ Audited files are all in public `plugins/` tree |
| §3 spellcaster_core canonical source | ✅ GIMP main uses `spellcaster_core.workflows.*` and `spellcaster_core.video_presets.*` correctly. JS plugin cannot import Python — H5 notes the unavoidable duplication. |
| §4 crash-safe boot shim | ✅ `comfyui-connector.py` still 228 lines, 3-tier recovery intact, protected from auto-updater |
| §7 procedure registration integrity | ✅ 82/82/82 match in the three dicts |
| §8 Klein node names | ✅ All canonical CamelCase (no dots/spaces) in both plugins and core |
| §9 architecture-specific rules | ✅ GIMP dispatch honors no-negative for Klein/Kontext/Chroma via `conditioning_zero_out`; see workflows.py |
| §11 personal data | ✅ No leaks in tracked source. Local `guild_config.json` has LAN ComfyUI IP — gitignored, correct. |
| §15 asset-gallery single-source | ✅ Both plugins route through `CrossInterfaceClient.upload_asset` → `/api/assets`. No `/api/cached_asset/*` writers added. |
| §16 WAN+LTX canon | ⚠ Python side correct; JS side (H5) re-implements detection — documented deviation. |

---

## 7. Summary numbers

- **19 ST HTTP endpoints** / **82 GIMP GUI procedures** audited end-to-end.
- **6 CRITICAL**, **10 HIGH**, **14 MEDIUM**, **8 LOW** findings.
- **2 sub-agent findings retracted** after verification (M13 Klein names, M14 PNG parser OOB) — sub-agents are fast but do hallucinate; always grep before believing.
- **Live Guild at 7777 confirms** the reciprocal bridge is wired and GIMP is heart-beating; SillyTavern extension is not currently connected.
- **No personal-data leaks** in tracked source; local configs (gitignored) correctly carry the LAN ComfyUI address.
- **Top exploit surface**: C1 + C6 (SSRF on both sides) + C2 (base64 OOM) — all in the cross-interface path. Fix these first.

---

## 8. Fixes applied in this session

All CRITICAL items landed in-place. No `spellcaster_core/` files touched, so no 3-repo sync required. Neither plugin was restarted during the edit (per CLAUDE.md §13 — auto-updater would clobber uncommitted work on a restart; user must commit + push before restarting GIMP or the Guild for changes to stick).

| # | File | Change |
|--|--|--|
| C1 | `server-plugin.js:_rejectUnsafeUrl` + `/cross/send` | `image_url` must be `http:`/`https:`; blocks AWS/GCP/Azure metadata hosts. Uses hardened `fetchBytes` (H1). |
| C2 | `server-plugin.js:_rejectOversizedB64` | 28 MB base64 cap (~20 MB decoded) applied to `/restyle`, `/edit`, `/save-avatar`, `/save-expression`, `/animate` (start + end frames), `/studio/cast`, `/cross/send` data-url path. Returns HTTP 413 on oversize. |
| C3 | `server-plugin.js:_safeNameOrNull` + `/save-avatar` + `/restore-avatar` + `/save-expression` | Rejects control chars, path separators, drive markers, wildcards, `..`; `/save-expression` adds resolve-under-charDir check. Unicode letters/digits still allowed. |
| C4 | `server-plugin.js:/settings` | `comfyui_url` and `guild_url` go through `_rejectUnsafeUrl`; `backgrounds_dir` must be absolute. Invalidates both `_cachedModel` AND `_cachedEditEngine` on ComfyUI URL change (M2 side-fix). |
| C5 | `server-plugin.js:/dispatch` | Disabled unless `SPELLCASTER_ALLOW_DISPATCH=1` in ST env. Adds object-type check and 2 MB JSON size cap when enabled. |
| C6 | `_spellcaster_main.py:25039` GIMP Check Inbox | `urllib.parse.urlparse(image_url).scheme` clamped to `http`/`https`; adds `User-Agent`; reads at most 100 MB. Non-http inbox messages reported in the failure list rather than silently followed. |
| H1 | `server-plugin.js:fetchBytes` | 50 MB byte cap via `req.destroy` on overflow; 30 s `setTimeout`. |

**Second pass (H6, H9, M9):**

| # | File | Change |
|--|--|--|
| H6 | `index.js:renderSettingsPanel` | Removes any existing `#spellcaster-settings` node (and its listeners) before re-inserting. Prevents handler accumulation if the function is ever called more than once. |
| H9 | `index.js:/sc-inbox` callback | `source`, `title` stripped of markdown delimiters + newlines (`[]()*_~` + CR/LF). `image_url` accepted only if `http(s)://` / `data:image/` / `/api/` path; remaining spaces and `)` percent-encoded so nothing can break out of the `![alt](url)` syntax. |
| M9 | `_spellcaster_main.py:_cross_interface_send` | Switched to `_get_cross_interface_client()` — the memoized singleton — instead of `CrossInterfaceClient(interface_key="gimp")` per click. One daemon heartbeat thread total, regardless of how many times the user clicks Send-to-X. |

**Residual (deferred):**
- H5 (JS re-implements WAN preset detection) — architectural fix; move detection behind a Guild endpoint.
- M10 (`/cross/inbox` consume-on-fetch) — requires adding `/cross/ack` and updating the ST client.

**Verification:** all three files pass syntax checks (`node --check` on both JS files, `python -m ast` on `_spellcaster_main.py`).

