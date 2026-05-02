# Research — existing tools to stop reinventing wheels

Parallel research dump (2026-04-20) on libraries / node packs / tooling Spellcaster could adopt to delete custom code. Ordered by expected LOC savings × risk.

**TL;DR adoption matrix:**

| Adopt | Tool | Replaces | LOC deleted | License | Risk |
|-------|------|----------|-------------|---------|------|
| ✅ NOW | `huggingface_hub` | `model_repair.py` download loop + `CN_URL_MAP` resolve-URL dance | ~100 | Apache-2.0 | very low |
| ✅ NOW | `age` / `pyrage` | custom `.scv` scrypt+AES-GCM format in `bundle_passphrase_gate.py` | ~150 + spec | BSD-3 + MIT | low |
| ✅ NOW | `python-websockets` | `/history/<prompt_id>` poll loop in `_run_comfyui_workflow` | ~60 + fewer races | BSD-3 | very low |
| ✅ NOW | `sseclient-py` | manual SSE buffer+reconnect in Resolve bridge + GIMP inbox | ~80 | Apache-2.0 | very low |
| ⚖️ SOON | `comfyui-tooling-nodes` (Acly) | filesystem round-trip `/upload/image` + `/view?filename=...` | ~200 + privacy win | GPL-3.0 | low (invoke as sibling pack, don't vendor) |
| 🔎 EVAL | `ComfyScript` (Chaoses-Ib) | entire `spellcaster_core/node_factory.py` (2262 LOC, 129 methods) | ~2300 | MIT | medium (big migration, some workflows may regress) |
| 🔎 EVAL | `ComfyUI-Manager` HTTP API | custom CN install flow + prerequisite checks | ~100 | GPL-3.0 | low |
| 🔎 EVAL | `zeroconf` | custom presence broker | ~200 | LGPL-2.1 | medium (multi-subnet + TXT-size gotchas) |
| ❌ SKIP | `pynsist` | downstream-distro FirstRun.bat orchestration | ~80 | MIT | **dormant — no release since 2022** |
| ❌ SKIP | `briefcase` | per-OS bundle batch files | ~80 | BSD-3 | **5 GB payload is outside happy path** |

---

## 1. `huggingface_hub.hf_hub_download()` — ADOPT NOW

- **URL**: https://github.com/huggingface/huggingface_hub · Apache-2.0 · active.
- **Replaces**: the hand-rolled `urllib.request` streamer + `.download` → atomic-rename dance + size-verification shim in [model_repair.py](../comfyui-spellcaster/model_repair.py).
- **Gains free**: resume-on-fail, tqdm progress bar, SHA-256 chunk verification (xet backend ≥0.32), `HF_TOKEN` env var for gated repos, content-addressed cache layout.
- **Migration**: convert `CN_URL_MAP` from `filename → url` to `filename → (repo_id, file_in_repo, revision)`. Each entry becomes:
  ```python
  hf_hub_download(
      repo_id="xinsir/controlnet-union-sdxl-1.0",
      filename="diffusion_pytorch_model_promax.safetensors",
      local_dir=controlnet_root,
      local_dir_use_symlinks=False,
      force_download=True,  # repair means always refetch
  )
  ```
  Keep §26 Layer 3 resolver (`_resolve_cn_paths_in_workflow`) untouched — it matches installed filenames, doesn't care how they got there.
- **Ship as**: add `huggingface_hub>=1.10` to the pack's `requirements.txt`; bundle builder installs into `python_embedded/`.

## 2. `age` / `pyrage` — ADOPT NOW (private downstream distribution only)

- **URLs**: `FiloSottile/age` (Go CLI, single 4 MB static binary, per-OS) + `woodruffw/pyrage` (Rust-backed Python bindings via `str4d/rage`). BSD-3 + MIT. Format is a C2SP-specified, independently-reviewed standard.
- **Replaces**: every byte of our custom `.scv` (Spellcaster Encrypted Vault) format — hand-rolled scrypt KDF, header struct, AES-GCM framing in [bundle_passphrase_gate.py](../nsfw/bundle/plugin_tools/bundle_passphrase_gate.py) and the entire [ENCRYPTED_FORMAT_PLAN.md](../nsfw/bundle/docs/ENCRYPTED_FORMAT_PLAN.md) spec.
- **Files are just `.age`.** Ciphertext: ChaCha20-Poly1305 in 64 KiB chunks, ~200 byte header, Poly1305 tag per chunk. Passphrase mode uses scrypt with format-standardised cost.
- **Disaster recovery we currently don't have**: user with a 4 MB age binary + their passphrase can decrypt on any OS — `age -d -o out.xcf bundle.age`. No Spellcaster install required to recover their own data. That's a huge UX+safety win.
- **Minimal recipe**: replace ENCRYPTED_FORMAT_PLAN entirely. `bundle_passphrase_gate.encrypt()` → `pyrage.passphrase.encrypt(payload, passphrase)`. Extension `.scv` → `.age` (or `.xcf.age`).
- **Streaming note**: `pyrage` today is bytes-in/bytes-out. For multi-GB NSFW vaults, shell out to the `age` binary (bundled in `nsfw/bundle/tools/`). For typical LoRA/preset bundles (few MB) the bytes API is fine.

## 3. `python-websockets` — ADOPT NOW

- **URL**: `python-websockets/websockets` · BSD-3 · active · pure-Python + optional C extension.
- **Replaces**: the `/history/<prompt_id>` polling loop in `_run_comfyui_workflow` (GIMP plug-in) + the same pattern in Resolve bridge. Eliminates a race where completion notification arrives before the history endpoint records the output.
- **ComfyUI's WS protocol** is well-documented in the official repo: `script_examples/websockets_api_example.py`. Completion signal = `executing` message with `data['node'] is None and data['prompt_id'] == your_id`.
- **Pairs naturally with `ETN_SendImageWebSocket`** from comfyui-tooling-nodes — same socket carries both the completion event and the image bytes (as binary frames with an 8-byte header).
- **Minimal client**:
  ```python
  from websockets.sync.client import connect
  with connect(f"ws://{host}/ws?clientId={cid}") as ws:
      for msg in ws:
          if isinstance(msg, bytes): continue  # preview / image payload
          m = json.loads(msg)
          if (m["type"] == "executing" and m["data"]["node"] is None
              and m["data"]["prompt_id"] == pid): break
  ```

## 4. `sseclient-py` — ADOPT NOW

- **URL**: `mpetazzoni/sseclient` · Apache-2.0 · active · `pip install sseclient-py`.
- **Replaces**: custom line-buffer + `\n\n` parser + manual reconnect-with-backoff in Resolve bridge and GIMP inbox poller that consume Guild SSE streams.
- **Notes**: accepts `requests.Session` for auth header + custom headers, supports `last_id` (sent as `Last-Event-ID` on reconnect) + `retry` ms backoff. One caveat: reconnect loop is on the caller — library surfaces disconnects as iterator termination. Still ~5 lines of calling code vs the ~80 lines we have today.
- **Snippet**:
  ```python
  import sseclient, requests
  s = requests.Session(); s.headers["Authorization"] = f"Bearer {tok}"
  for evt in sseclient.SSEClient(url, session=s, last_id=saved, retry=3000):
      handle(evt.event, evt.data); saved = evt.id
  ```

## 5. `comfyui-tooling-nodes` (Acly) — ADOPT SOON

- **URL**: `Acly/comfyui-tooling-nodes` · GPL-3.0 · 648 stars · active · used by Krita AI Diffusion in production.
- **Replaces**: every filesystem round-trip for image I/O. Today we `POST /upload/image` then `GET /view?filename=...`. With ETN nodes, bytes go in via base64 embedded in the prompt JSON (`ETN_LoadImageBase64`) and out over the existing `/ws` socket as a binary frame (`ETN_SendImageWebSocket`, format = `struct.pack(">II", 1, 2) + png_bytes`).
- **Massive privacy win**: ComfyUI `input/` + `output/` folders are NEVER TOUCHED for Spellcaster-authored workflows. Supersedes both our custom `SpellcasterLoadImageFromBlob` spec AND the INLINE_IMAGE_TRANSPORT_PLAN (which already mentioned this tool — adopting means we delete the plan and just install the pack).
- **Krita's consumption pattern** (verified from `Acly/krita-ai-diffusion/ai_diffusion/comfy_client.py`):
  ```python
  async for msg in websocket:
      if isinstance(msg, bytes):
          s = struct.calcsize(">II")
          event, format = struct.unpack_from(">II", msg)
          if event == 1 and format == 2:
              png_bytes = msg[s:]
  ```
- **License catch**: GPL-3.0. Safe to use as a sibling `custom_nodes/` install (invoke over JSON, not linked). Do NOT vendor into our own plugin tree or we propagate GPL into Spellcaster's MIT.
- **Migration**: add 2 methods to node_factory (`load_image_base64`, `send_image_websocket`); add ws client path alongside the current HTTP path (gated on `use_inline_transport=True`); bundle builder git-clones tooling-nodes into `custom_nodes/`.

## 6. `ComfyScript` (Chaoses-Ib) — EVALUATE (big deletion, needs careful migration)

- **URL**: `Chaoses-Ib/ComfyScript` · MIT · 664 stars · v0.6.1 Nov 2025 · `pip install comfy-script[default]`.
- **What it is**: Python DSL for ComfyUI workflows. Auto-generates typed node constructors (`.pyi` stubs) from ComfyUI's runtime — same data source as `/object_info`. Transpiler in both directions (Python ↔ workflow JSON).
- **Replaces**: the ENTIRETY of our `node_factory.py` (2262 LOC, 129 hand-maintained methods) + the graph-assembly scaffolding in `workflows.py` / `pipeline.py`.
- **Maturity**: strictly a superset of what we have. Every custom node the user has installed is auto-typed; we don't need to hand-port node signatures every time ComfyUI updates.
- **Migration strategy**: per-workflow. Each `build_*` in workflows.py becomes a `with Workflow():` block. Both paths coexist; we migrate one builder at a time.
- **Why evaluate not adopt-now**: 2300 LOC of battle-tested code doesn't vanish without a 2–3 week migration + regression test sweep. The `test_quality_boost.py` / `test_model_coverage.py` / `test_klein_enhancer.py` suites need to pass on the ComfyScript path before flipping.
- **Decision trigger**: next time we need to add a new ComfyUI node family (happens every few months), adopt then instead of hand-rolling another N NodeFactory methods.

## 7. `ComfyUI-Manager` HTTP API — EVALUATE

- **URL**: `Comfy-Org/ComfyUI-Manager` · GPL-3.0 · 14.3k stars · canonical node/model installer.
- **It exposes a full HTTP API** on the ComfyUI port:
  - `POST /manager/queue/install_model` — queue model download (with hash validation)
  - `POST /manager/queue/install` — install a custom node by ID or git URL
  - `GET /manager/queue/status` — poll progress
  - `GET /externalmodel/getlist` / `GET /customnode/getlist` — catalogs
- **Replaces**: our custom ControlNet download flow in `model_repair.py` + the prerequisite prompts that tell users "go install X via ComfyUI-Manager."
- **Why evaluate**: Manager covers the catalog, our `CN_URL_MAP` covers what Spellcaster specifically needs. Duplicating the catalog is fine for curated files; offloading to Manager works when users already have it installed (most do). Decision: add a "try Manager API first, fall back to our direct download" branch in model_repair.py's redownload action.

## 8. `zeroconf` — EVALUATE with caveats

- **URL**: `python-zeroconf/python-zeroconf` · LGPL-2.1 · active.
- **Replaces**: the register/list/heartbeat/unregister HTTP routes in [presence.py](../comfyui-spellcaster/presence.py) (~200 lines).
- **Gotchas**:
  - mDNS is link-local. Multi-subnet ComfyUI setups (user's workstation on WiFi, GPU box on wired LAN) lose discovery that our HTTP broker gets for free via `X-Forwarded-For`. That's a real use case for our typical deployments.
  - TXT records cap at ~1300 bytes — tighter than our 2 KB `MAX_META_BYTES`. Capability lists would need to shorten or reshape.
  - LGPL is copyleft; dynamic-link-only is fine for a plugin pack.
- **Verdict**: evaluate for the SINGLE-SUBNET case (would be a nice win), keep HTTP broker as the cross-subnet fallback. Probably end up running BOTH.

## 9. `pynsist` — SKIP

- Last release 2.8 was March 2022 — dormant. NSIS toolchain underneath is fine, but the Python wrapper hasn't tracked CPython 3.12+ officially.
- **Better fit**: stick with the official-GIMP-installer orchestration we already have, OR use Inno Setup directly when a proper installer is needed.

## 10. `briefcase` (BeeWare) — SKIP unless cross-platform is a product commitment

- Active, good library, but bundling GIMP (~300 MB) + ComfyUI Portable (3–5 GB with models) is outside its happy path.
- macOS notarisation on a 5 GB .app is painful. AppImage has a practical ~4 GB ceiling on some filesystems.
- If downstream bundles stay Windows-only (current plan), briefcase is overkill for a week of setup.
- Decision trigger: when macOS + Linux downstream bundles become a real release goal, revisit.

---

## Recommended adoption order

**Sprint 1 (days):**
1. ✅ **DONE 2026-04-20** — `huggingface_hub.hf_hub_download` in [model_repair.py](../comfyui-spellcaster/model_repair.py). `CN_REPO_MAP` is now the canonical (repo_id, filename, revision) table; `CN_URL_MAP` kept as legacy fallback. Installer's `step_check_cn_coverage` pulls URLs live from the pack route.
2. ✅ **DONE 2026-04-20** — `sseclient-py` in Resolve bridge via [`_iter_sseclient`](../plugins/resolve/shared/spellcaster_api.py). Gains ``Last-Event-ID`` replay across reconnects (bridge's [`sse_client.py`](../plugins/resolve/spellcaster_bridge/sse_client.py) now tracks `_last_event_id`). Hand-rolled `_iter_sse` kept as graceful fallback when the lib isn't installed (air-gapped / legacy Resolve shipments). GIMP inbox poller uses HTTP polling, not SSE — no change needed there.
3. **DEFERRED** — `python-websockets` for ComfyUI `/history` poll replacement. Full value only comes paired with ETN_SendImageWebSocket binary frames (disk-free image return). Landing both together is a future dedicated session — needs live ComfyUI testing + config flag + gradual rollout.

**Sprint 2 (weeks):**
4. ✅ **DONE (NSFW side) 2026-04-20** — `age` / `pyrage` replaces the `.scv` custom spec entirely. [bundle_passphrase_gate.py](../nsfw/bundle/plugin_tools/bundle_passphrase_gate.py) uses `pyrage.passphrase.encrypt/decrypt` with an `age` binary fallback. [ENCRYPTED_FORMAT_PLAN.md](../nsfw/bundle/docs/ENCRYPTED_FORMAT_PLAN.md) rewritten to spec `.age` format instead of `.scv`. Legacy `.lock` JSON auto-upgrades on first unlock.
5. **PARTIAL** — `Acly/comfyui-tooling-nodes` git-cloned into bundle's `custom_nodes/` by [build_portable_bundle.py::_install_tooling_nodes](../nsfw/bundle/tools/build_portable_bundle.py). Bundle's `python_embedded/` also gets `huggingface_hub + pyrage + websockets + sseclient-py` pre-installed via the new `step_install_pyrequirements` step. STILL TODO: add `use_inline_transport=True` flag on `build_*` and wire ETN_LoadImageBase64 / ETN_SendImageWebSocket in the GIMP dispatcher — lands when the websockets client swap (sprint 1 #3) lands, since ETN's result path is ws-binary-frame-based.

**Sprint 3 (next quarter):**
6. Evaluate `ComfyScript` migration — timed for the next "new ComfyUI node family" need.
7. ✅ **DONE 2026-04-20** — `zeroconf` as additional mDNS broadcast in [`presence.py::_install_zeroconf_broadcast`](../comfyui-spellcaster/presence.py). Advertises `_spellcaster._tcp.local.` alongside the existing HTTP broker; TXT record points at the HTTP broker URL so rich capability metadata stays on the HTTP path. Silent on failure (zeroconf not installed / multicast blocked / port undiscoverable) — HTTP broker remains authoritative. Additive, zero behaviour change for existing clients.
8. Evaluate Manager API offload for ControlNet installs.

**Never:**
- pynsist (dormant). briefcase (payload-size-mismatch).

---

## Net effect if 1-5 adopted

- **Delete**: ~600 LOC of custom downloader / poller / SSE parser / ciphertext framing.
- **Add**: 4–5 `pip install` lines to bundle requirements (`huggingface_hub`, `pyrage`, `websockets`, `sseclient-py`, optionally `zeroconf`).
- **Gains for free**: resume-on-fail, hash verification, formal-spec crypto, binary-framed image streaming, industry-standard disaster recovery.
- **Risk**: low. Each adoption is incremental, testable, behind a config flag where appropriate.
