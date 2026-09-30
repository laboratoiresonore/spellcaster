# _DEV_HYGIENE.md — ecosystem-wide hygiene rules (H1–H7)

This file is the **cross-repo floor**. Vendor it byte-identical (per **H7**) into every consumer repo: spellcaster, spellcaster_NSFW, Voodoomancer, the ComfyUI-Spellcaster custom nodes, and any future fork. Repo-local rules ride on top via each repo's `CLAUDE.md`.

> **Scaffold note (2026-05-13):** This file was scaffolded by the orientation
> Claude session after finding it referenced by `spellcaster/CLAUDE.md` but
> absent from the tree. Rules **H3**, **H4**, **H7** are concrete and
> verified against existing CLAUDE.md mentions. Rules **H1**, **H2**, **H5**,
> **H6** are placeholders with proposed scope — the user/owner should
> finalize them. Until finalized, treat the placeholders as best-guess
> defaults, not as authoritative law.

---

## H1 — Single source of truth (TBD: confirm scope with user)

**Proposed rule:** Every concept the ecosystem reasons about (a config key, a model path, a workflow node name, a feature flag) lives in exactly one canonical location. If you need to mirror it elsewhere, the mirror is mechanical (script-driven, byte-identical) and one-directional.

**Failsafe pattern:** A `mirror_drift.py`-style test that md5s the canonical against every mirror surface; CI fails on drift. Existing instance: `tests/mirror_drift.py` (the 6-surface `spellcaster_core/` mirror — see `MIRROR_TARGETS.md`).

**Why this matters:** PR #20 (2026-05-13) caught a 4-week-old SaveImageWebsocket fix that landed on surface 1 but never propagated to canonical C — a near-miss for live inpaint recovery.

> ⚠ Status: confirm with user whether H1 is "the SSoT rule (broad)" or
> something narrower.

---

## H2 — Continuous verification (TBD: confirm scope with user)

**Proposed rule:** Before reasoning about a running system's state, run the audit. Don't reconstruct state from memory or assumptions.

**Failsafe pattern:** A `night_maintenance.py`-style composite that runs every audit + writes a dated report under `~/.voodoomaster/` so the next operator (human or Claude) reads the report instead of re-probing. Existing instance: `tests/night_maintenance.py`.

**Cadence:** nightly cron on Theo (per Laborantin practice, §3 of `spellcaster/CLAUDE.md`); on-demand whenever Claude joins a session that touches the live system.

> ⚠ Status: confirm with user whether H2 is "always audit first" or
> something more specific.

---

## H3 — Datetime hygiene (CONFIRMED — see `installer_audit.py`)

**Rule:** Never construct a `datetime` without an explicit timezone. All wall-clock comparisons must be against `datetime.now(timezone.utc)` (or another explicit tz). Naïve `datetime.now()` is forbidden in source.

**Why this matters:** This codebase runs on Theo (Pacific) but the user is on the road across timezones; manifests + report files use ISO-8601 with `Z`. A naïve `datetime` on a daylight-savings boundary silently misorders nightly reports.

**Failsafe:** `tests/installer_audit.py` includes an `H3 datetime hygiene` check that greps the codebase for naïve `datetime.now()` / `datetime.utcnow()` / `datetime(year, month, day)` constructors.

**How to comply:**

```python
# WRONG
from datetime import datetime
ts = datetime.now()

# RIGHT
from datetime import datetime, timezone
ts = datetime.now(timezone.utc)
```

---

## H4 — ComfyUI node-name verification (CONFIRMED — see `spellcaster/CLAUDE.md` §3)

**Rule:** Never hard-code a ComfyUI node class name without first verifying it via the live server's `/object_info` endpoint. One wrong name = the workflow silently runs without the node, often producing apparently-correct but subtly-degraded output (no upscale, no refiner, no face-detail).

**Why this matters:** Custom nodes get renamed across upstream releases. `IPAdapterApply` became `IPAdapter` in one cycle; nodes from `was-node-suite-comfyui` rename themselves between minor versions. A workflow that worked yesterday silently fails today.

**Failsafe:**

```python
import urllib.request, json
oi = json.loads(urllib.request.urlopen("http://192.168.86.28:8190/object_info").read())
assert "MyNodeName" in oi, f"node MyNodeName not on server (have {len(oi)} nodes)"
```

`tests/capabilities.py` (called by `night_maintenance.py`) probes the server's full `/object_info` and surfaces a count + drift report so changes are caught the next morning.

---

## H5 — Local-LLM delegation safety boundary (TBD: confirm scope with user)

**Proposed rule:** Tasks that don't require Claude-level reasoning should be delegated to local LLMs (LM Studio on Theo, Ollama). But there is a **hard never-delegate list**: mirror sync, security-sensitive code, ComfyUI node selection (covered by H4), architecture changes, and ANY client-config edit (covered by H6).

**Failsafe pattern:** `tools/llm_delegate.py` — caller reviews diff before applying. Local LLM never writes to disk directly; it emits a proposal.

**Models on Theo:**
- `qwen2.5-coder-7b` — code tasks
- `qwen3-30b` — nuanced summarization (needs the 16 GB VRAM headroom)
- `deepseek-r1` — reasoning sketches
- `nemotron-3-nano-4b` — fast triage

> ⚠ Status: confirm with user whether H5 is "the delegation safety rule"
> or something else.

---

## H6 — Client-edit ban (TBD: confirm scope with user)

**Proposed rule:** Do not modify any Claude/VSCode/Antigravity/IDE client config to add scope-shared rules. Multiple sessions share the same clients; per-session edits create silent drift across sessions.

**Where to put rules instead:**

| Scope | Home |
|---|---|
| Repo-local rule | `<repo>/CLAUDE.md` |
| Cross-repo invariant | `_DEV_HYGIENE.md` (this file, vendored byte-identical per H7) |
| Surface enumeration | `MIRROR_TARGETS.md` |
| Per-repo dispatch hint | `<repo>/VIBECODER.md` |
| Per-machine user preference | `~/.claude/projects/<dir>/memory/` (persistent for this machine, no repo leakage) |

**Specific forbidden paths:**
- `~/.claude/CLAUDE.md`
- `~/.claude/settings.json`
- `~/.claude/keybindings.json`
- `**/.vscode/settings.json`
- `**/antigravity*`

> ⚠ Status: confirm with user whether H6 is "client-edit ban" — this seems
> like the strongest fit given §4 of `spellcaster/CLAUDE.md` is essentially
> the same rule.

---

## H7 — Byte-identical vendoring (CONFIRMED — see `spellcaster/CLAUDE.md` final line)

**Rule:** Cross-repo files like THIS file (`_DEV_HYGIENE.md`) are **vendored byte-identical** across every consumer repo. Don't fork. If a rule needs to change, change it in the canonical home (spellcaster) and the auto-patch bot propagates to:

- `spellcaster_NSFW`
- `ComfyUI-Spellcaster`
- `ComfyUI-Spellcaster-NSFW`
- `Voodoomancer`
- (any future consumer)

**Failsafe:** the same `mirror_drift.py` style check from H1, applied across repos. A repo whose `_DEV_HYGIENE.md` md5 doesn't match canonical is flagged on next CI run.

**One-direction rule:** spellcaster is canonical. Never edit a vendored copy directly — edit in spellcaster, run the propagator, commit each consumer separately with a `chore(vendor): sync _DEV_HYGIENE.md from spellcaster@<sha>` message.

---

## Quick reference

| Rule | One-liner | Failsafe |
|---|---|---|
| H1 | Single source of truth for every concept | `mirror_drift.py` |
| H2 | Audit before reasoning about state | `night_maintenance.py` |
| H3 | All datetimes tz-aware, UTC default | `installer_audit.py` H3 check |
| H4 | Verify ComfyUI node names via `/object_info` | `capabilities.py` probe |
| H5 | Delegate to local LLM only when safe; hard never-list | `llm_delegate.py` review-before-apply |
| H6 | No client-config edits (~/.claude/, VSCode, Antigravity) | convention; coordinator session list |
| H7 | Vendor cross-repo files byte-identical | per-repo `mirror_drift.py` |

---

*Canonical home: `spellcaster/_DEV_HYGIENE.md`. All other copies are vendored by the auto-patch bot. If you find a discrepancy, fix it here first, then sync.*
