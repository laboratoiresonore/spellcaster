# Antenna — Source-of-Truth Inventory

Generated 2026-06-06. Dense reference for future Claude sessions.

## 1. Canonical install path

**`C:\Users\legui\spellcaster\antenna\`** — a sub-package inside the Spellcaster monorepo (origin `github.com/laboratoiresonore/spellcaster`).

Stale-copy triage:
- `C:\Users\legui\spellcaster-antenna-src\antenna` — STALE clone of the spellcaster repo. `main` has diverged **295 ahead / 1101 behind origin**, last touch 2026-04-25, dirty working tree with stomped sibling files (`comfyui-spellcaster/`, GIMP connector). Do not edit; do not pull from. The `-antenna-src` directory name is misleading — it is not a separate antenna repo, it is just an aging full-spellcaster clone.
- `C:\Users\legui\spellcaster_NSFW\antenna` — DOWNSTREAM auto-patched mirror. Last antenna touch 2026-05-01 commit `e175e9b` "NSFW build: auto-patched from public repo". `heartbeat.py` already drifted from canonical (canonical updated 2026-05-03 / NSFW mirror still on the older copy). Edits here will be clobbered by the next NSFW auto-patch run from spellcaster main.

Canonical confirmation: only `spellcaster/antenna` has `origin → laboratoiresonore/spellcaster` AND fast-forward parity with origin/main on antenna paths; latest antenna commit on main is `52d3932 2026-05-03 chore(privacy): scrub host-name leaks` and on any branch `1c97f6f 2026-06-04 feat(antenna): add LM Studio connector` (branch `fix/gimp_batch-3.0.4-pdb-signature`, no diff vs main for antenna/ — branch is gimp-focused).

## 2. Mission

Antenna is **Spellcaster's distributed-LAN control-plane agent**. A single stdlib-only Python process (`python -m antenna`) running on every box that hosts an AI service (ComfyUI / KoboldCpp / Ollama / LM Studio / DaVinci Resolve / SillyTavern / Signal bridge / Darktable / GIMP). Clients (GIMP plugin, Wizard Guild web UI, installer) POST to `https://<box>:7334` to install nodes, download models, start/stop services, self-update — so a non-SSH user with one beefy AI box + thin laptops never has to log into the server. See `DEEP_DIVE.md:866` ("📡 Antenna — 15+ endpoints, tray menu, self-update").

Place in fleet: **Spellcaster-only**. It is not used by Voodoomancer, Whimweaver, or Laborantin. It is the load-bearing piece that turns Spellcaster from a single-machine app into a federated LAN topology. Cousin of (but distinct from) Prometheus's fleet-ssh path — antenna is a per-app HTTPS service controller, Prometheus is the SSH/secrets hub.

Version: **`__version__ = "2.3"`** (`antenna/__init__.py:6`).

## 3. Surface

Top-level structure (all under `antenna/`, 6,282 lines core + 3,624 endpoints):

- `__main__.py` (394) — tray-vs-console picker, crash trap, first-run Tk shortcut/firewall dialog.
- `agent.py` (697) — `ThreadingHTTPServer` + TLS + routing table + rate limit + audit log. Entrypoint `serve()`.
- `auth.py` (198) — bearer-token compare (`hmac.compare_digest`) + self-signed TLS cert generation.
- `config.py` (529) — load/save `~/.spellcaster/antenna_config.json`, services-list-vs-dict migration, atomic writes.
- `tray.py` (743) — Windows pystray system tray + dynamic menu + toast notifications.
- `pairing.py` (198) — 6-digit pair-code handshake (Guild ↔ antenna token exchange, 5-min TTL).
- `heartbeat.py` (309) — 10-second post to Guild `/api/interfaces/heartbeat`.
- `service_detector.py` (983) + `detect.py` (353) + `service_launcher.py` (493) — per-service auto-detection (registry / Program Files / PortableApps) + subprocess spawn.
- `firewall.py` (307) — netsh inbound rule for port 7334 (UAC-elevated).
- `port_cleanup.py` (193) — pre-bind reap of orphan processes squatting on 7334.
- `install_shortcuts.py` (266) — Windows desktop/Start-Menu/run-at-login `.lnk` via WScript.Shell.
- `splash.py` (263) — first-launch animated splash.
- `telemetry.py` (237) + `bus_client.py` (112) — VRAM/CPU/disk/queue metrics + Guild event-bus client.
- `assets/antenna_logo.png` — tray icon.
- `endpoints/` (11 files): `status.py`, `comfyui.py`, `llm.py`, `resolve.py`, `resolve_plugin.py`, `darktable_plugin.py`, `sillytavern_plugin.py`, `self_update.py`, `services.py`, `telemetry_ep.py`.

Entry points:
- `python -m antenna` → tray (Windows + pystray) or console.
- `python -m antenna.agent` → console-forced.
- `installer/build_antenna_exe.py` → standalone `.exe` bundle.
- `installer/install_antenna.bat` + `.sh` → user-facing remote-box bootstrap.

Config: `~/.spellcaster/antenna_config.json`, token at `~/.spellcaster/antenna_token`, cert at `~/.spellcaster/antenna.crt/.key`, crash log at `~/.spellcaster/antenna-crash.log`, shortcut-done sentinel at `~/.spellcaster/antenna_shortcuts_done`.

Default port: **7334** (HTTPS, self-signed, bearer-token, 30 rpm rate limit per IP).

## 4. Recent activity theme

Last 30 commits touching `antenna/` (Apr 18 → Jun 04 2026):

- **Apr 18-19 — scaffold + multi-service expansion**: initial `feat(antenna): scaffold` (29dcd57, Apr 18) → per-service rich detection → `/llm/install` → ComfyUI URL auto-probe → R55 project picker.
- **Apr 19 — pair-code + tray ship**: 6-digit handshake, Connect-an-app chip integration, Kobold RP/TTS split, Signal bridge, walkie-talkie.
- **Apr 19-20 — Resolve bridge endpoints**: `/resolve/*`, auto-deploy Resolve plugin on `/self-update`, Darktable plugin auto-deploy.
- **Apr 19 — Windows polish**: shortcut installer, first-launch dialog, antenna-exe pystray+Tcl/Tk bundling, firewall auto-rule + Tk theme.
- **May 01-03 — privacy + redaction sweep**: host-name leak scrub (`c2ecc71`, `d116451`, `52d3932`).
- **Jun 04 (current branch only)** — `1c97f6f feat(antenna): add LM Studio connector + service registry entry` (touches `config.py`, `endpoints/llm.py`, `installer/remote_services.json`).

Theme: **April was build-out, May was privacy hardening, June restarted with the LM Studio integration**. Most modules untouched since mid-April; antenna is largely complete.

## 5. Integrations

**Callers of antenna (clients):**
- `tavern/server.py` + `tavern/static/app.js` — Wizard Guild web UI proxies user clicks to antenna endpoints.
- `tavern/guild_tray.py` — Guild's own tray menu uses antenna `/service/*`.
- `installer/install.py`, `installer/installer_gui.py`, `installer/antenna_setup.py`, `installer/build_antenna_exe.py` — installer pipeline.
- `installer/remote_services.json` + `installer/remote_services.py` — service registry consumed by antenna's `_autopopulate_services()` (`agent.py:124`).
- `scaffold/studio_scaffold.py`, `scaffold/video_bridge.py`, `scaffold/cue_seeder.py` — scaffold state machines route remote calls through antenna.
- `plugins/resolve/scripts/_spellcaster_common.py` — Resolve plugin calls antenna's `/resolve/*` when Resolve lives on a different machine.
- `tools/build_builders_manifest.py` — manifest consumer (light reference).
- `tavern/static/video_panel.jsx` — video panel telemetry chips read antenna `/telemetry`.

**Antenna calls outward to**: Guild's `/api/interfaces/heartbeat`, `/api/spellcaster/*` (via `bus_client.py`), GitHub raw `manifest.json`, local ComfyUI on `127.0.0.1:8188`, KoboldCpp 5001/5002, Ollama 11434, LM Studio (port discovered).

**NOT a caller**: Voodoomancer, Whimweaver, Laborantin — antenna is Spellcaster-only.

## 6. Forbidden / load-bearing files

- `antenna/__init__.py:6` — `__version__ = "2.3"` — every bump goes here; the installer reads it.
- `antenna/agent.py` — `_UNAUTHENTICATED_PATHS = {"/", "/pair/claim", "/pair/state"}` (line 70) is security-critical; never add a new path here without 2-factor reasoning.
- `antenna/auth.py` — TLS cert gen + `hmac.compare_digest` token check; do not "simplify" the constant-time compare to `==`.
- `antenna/pairing.py` — 5-min TTL + single-use code lifecycle; do not loosen.
- `~/.spellcaster/antenna_token`, `antenna.key` — user secrets on disk; never log, never include in crash reports.
- `installer/build_antenna_exe.py` — PyInstaller recipe; the Tcl/Tk + pystray bundling here is load-bearing (see commits `a3bb68f` / `b344ecd` / `019b941`). Last 4 fix commits hard-won.
- `installer/remote_services.json` — service registry, single source of truth for auto-detection + LM Studio addition (Jun 04).
- Atomic-write contract: `antenna_config.json` uses tempfile→fsync→`os.replace` (per `DEEP_DIVE.md:907`). Never write directly.

## 7. Open work

- **No `TODO`/`FIXME`/`XXX`/`HACK` markers** anywhere in `antenna/` (grep is empty).
- **No `CHANGELOG.md`, `TODO.md`, `VIBECODER.md`, or `CLAUDE.md` inside `antenna/`** — only `README.md`. The parent repo's `VIBECODER.md` does not enumerate antenna scope either. **Finding: antenna lacks its own Claude/vibe-coder runbook**; sessions touching antenna depend on `DEEP_DIVE.md:866-882` for context.
- **Un-merged active branches** that touch antenna (only):
  - `feat/nsfw-source-annotations-2026-05-15` — checked-out on `spellcaster_NSFW/antenna`; antenna delta is `heartbeat.py` only.
  - `fix/gimp_batch-3.0.4-pdb-signature` (current branch) — no antenna diff vs main.
  - The Jun 04 commit `1c97f6f` (LM Studio connector) appears on local checkout but its branch attribution from `git log --all` suggests it's pre-merge on main; verify before any antenna PR.
- README phase-2 stubs `POST /install-node` and `POST /install-model` still return **501 `not_yet_implemented`** (per `README.md:88-92`). This is the longest-standing open item.

## 8. Quick reference

| Path | What |
|---|---|
| `C:\Users\legui\spellcaster\antenna\` | canonical source |
| `C:\Users\legui\spellcaster\antenna\README.md` | architecture, security, endpoints, config |
| `C:\Users\legui\spellcaster\DEEP_DIVE.md:866` | parent-repo's antenna section |
| `C:\Users\legui\spellcaster\antenna\__init__.py:6` | version |
| `C:\Users\legui\spellcaster\antenna\__main__.py:362` | `main()` — tray/console picker |
| `C:\Users\legui\spellcaster\antenna\agent.py:70` | `_UNAUTHENTICATED_PATHS` |
| `C:\Users\legui\spellcaster\antenna\agent.py:124` | `_autopopulate_services` |
| `C:\Users\legui\spellcaster\antenna\agent.py:207` | `_build_routes` (routing table) |
| `C:\Users\legui\spellcaster\installer\antenna_setup.py` | installer's per-service local/remote prompt |
| `C:\Users\legui\spellcaster\installer\build_antenna_exe.py` | PyInstaller recipe |
| `C:\Users\legui\spellcaster\installer\install_antenna.bat/.sh` | end-user bootstrap |
| `C:\Users\legui\spellcaster\installer\remote_services.json` | service registry (LM Studio just added 2026-06-04) |
| `~/.spellcaster/antenna_config.json` | runtime config |
| `~/.spellcaster/antenna_token` | bearer (sensitive) |
| `~/.spellcaster/antenna-crash.log` | "windowless .exe did nothing" debug log |
| Port 7334 (HTTPS) | bind |
| Default rate limit | 30 rpm per IP |
