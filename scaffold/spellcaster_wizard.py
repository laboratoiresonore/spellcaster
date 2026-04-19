"""Spellcaster Wizard — top-level onboarding, install manager, calibration, custom builds.

This scaffold replaces the legacy `setup_wizard.py`. It lives at the top of the
Guild sidebar and NEVER banishes; the user can always come back to it to:

  - See what's installed and what isn't
  - Get a live install quote (GB + # of methods unlocked) before picking anything
  - Install or uninstall features one click at a time
  - Set up an Antenna when ComfyUI runs on another machine
  - Run a verification test after any install
  - Build custom plugins (GIMP / Darktable / Resolve / Wizard Guild) tailored
    to the exact install state the user has chosen
  - Run advanced calibrations (LoRA strength sweeps, turbo vs non-turbo A/B,
    sampler/scheduler A/B, CFG sweeps) across every installed model

STATE MACHINE
─────────────
States form a loose graph — the scaffold is conversational, not rigid. The
`phase` field in the session snapshot is a hint to the LLM, not a hard gate.

    GREETING        welcome, summary of current install state
    ASSESS          probe system (GPU / VRAM / ComfyUI reach / antennas)
    ANTENNA         walk the user through remote-machine setup
    INTENT          ask what they want Spellcaster to do for them
    RECOMMEND       suggest a feature bundle based on intent + VRAM budget
    QUOTE           show GB cost + # of unlocked methods before committing
    INSTALL_LOOP    install one feature at a time; each install tested before next
    TEST_FEATURE    verify a feature works end-to-end
    PLUGINS         install GIMP / Darktable / Resolve / Blender / Krita / ST
    BUILD_CUSTOM    produce a custom plugin build matching the current install
    CALIBRATE       run LoRA / sampler / scheduler / CFG / turbo tests
    EXPAND          user wants to add more tools later (same as QUOTE + INSTALL)
    REDUCE          user wants to uninstall unused models/features
    FINISH          back to normal Guild flow

ACTIONS (JSON blocks the LLM emits inside <ACTION>…</ACTION>)
──────
    {"type": "install_feature",    "feature": "<key>"}
    {"type": "uninstall_feature",  "feature": "<key>"}
    {"type": "install_plugin",     "plugin":  "gimp|darktable|resolve|blender|krita|photoshop|sillytavern"}
    {"type": "uninstall_plugin",   "plugin":  "<same>"}
    {"type": "quote",              "features": ["<key>", ...]}
    {"type": "test_feature",       "feature": "<key>"}
    {"type": "start_antenna_setup"}
    {"type": "antenna_test",       "host": "<ip|hostname>", "port": 8188}
    {"type": "build_custom",       "target": "gimp|guild|darktable|resolve|blender|krita|photoshop|sillytavern",
                                   "features": ["<key>", ...]}
    {"type": "calibrate_lora",     "model": "<ckpt>", "lora": "<lora_name>", "strengths": [0.3, 0.5, 0.7, 0.9]}
    {"type": "calibrate_sampler",  "model": "<ckpt>", "samplers": [...], "schedulers": [...]}
    {"type": "calibrate_turbo",    "model": "<ckpt>"}
    {"type": "calibrate_cfg",      "model": "<ckpt>", "values": [3.0, 5.0, 7.0, 9.0]}
    {"type": "finish"}

STATE SNAPSHOT
──────────────
The Guild server calls `/api/spellcaster/state` on each turn; the LLM receives
it in the system prompt. Shape:

    {
      "phase":                "INSTALL_LOOP" | ...,
      "system": {
        "gpu":                "RTX 4090",
        "vram_gb":            24,
        "platform":           "windows-11",
        "comfyui_reachable":  True,
        "comfyui_url":        "http://192.168.x.x:8188",
        "comfyui_remote":     True,     # i.e. not localhost
        "antenna_reachable":  False,    # True once the remote antenna is up
        "llm_available":      True,
      },
      "features": [
        {"key": "img2img", "label": "...", "vram_min_gb": 4,
         "installed": True, "size_mb": 105423, "method_count": 7,
         "methods": ["Text to Image", "Image to Image", ...]},
        ...
      ],
      "plugins":  {"gimp": True, "darktable": False, "resolve": False, ...},
      "antennas": [
        {"host": "...", "port": 8188, "reachable": True, "services": ["comfyui"]}
      ],
      "totals":   {"installed_gb": 103.0, "available_gb": 242.8,
                   "installed_methods": 14, "total_methods": 69}
    }
"""
from __future__ import annotations

import json
import re
from typing import Any


# ── Mapping: feature key → human-readable methods it unlocks ─────────────
#
# This is the source of truth for "if you install this feature, these tools
# light up in GIMP + the Guild." Keys match `installer/manifest.json`'s
# `features` dict; values are the label strings users see in menus.
#
# Whenever a new `build_*` function becomes callable only when some feature
# is present, add the corresponding tool label here.
FEATURE_METHODS: dict[str, list[str]] = {
    "img2img": [
        "Text to Image", "Image to Image", "Inpaint Selection",
        "Batch Variations", "Generate Anything",
        "Edit by Instruction (Kontext)", "Style Transfer",
    ],
    "txt2img": ["Text to Image"],
    "inpaint": [
        "Inpaint Selection (44 presets)", "Outpaint / Extend", "Quick Inpaint",
    ],
    "klein_flux2": [
        "AI Editor (Klein)", "Klein Editor + Reference",
        "Klein Outpaint", "Klein Inpaint", "Layer Blender (Klein)",
        "Re-poser (Klein)", "Headswap (Klein)", "Detail Enhancer (Klein)",
        "Generate Object (Klein)", "Klein Auto-Inpaint",
        "Klein SAM3 Inpaint", "Klein Refine", "Klein Face Detailer",
        "Klein Color Match", "Klein Virtual Try-On",
        "Klein 4-Image Grid Variations",
    ],
    "flux_kontext": ["Edit by Instruction"],
    "face_swap_reactor": [
        "Face Swap (ReActor)", "Face Swap (Saved Model)",
    ],
    "face_swap_mtb": ["Face Swap (mtb)"],
    "faceid_img2img": ["Face Identity Transfer (IPAdapter FaceID)"],
    "pulid_flux": ["Face Identity Transfer (PuLID / Flux)"],
    "face_restore": ["Face Restore (GPEN / CodeFormer / GFPGAN / RestoreFormer++)"],
    "upscale": [
        "Upscale", "Quick Upscale 4x", "SeedVR2 Upscale",
        "Detail Hallucination", "Photo Restoration",
        "Upscaler Blend",
    ],
    "supir": ["SUPIR AI Restoration"],
    "rembg": [
        "Remove Background", "AI Extract Subject", "Quick Remove Background",
    ],
    "lama_remove": ["AI Eraser", "Object Removal (LaMa)", "Magic Eraser"],
    "controlnet": [
        "ControlNet (6 guides)", "Colorize (ControlNet)",
    ],
    "colorize": ["Colorize B&W (instant / ControlNet)"],
    "iclight": ["IC-Light Relighting"],
    "lut_grading": ["Color Grading (LUT)"],
    "segment": [
        "AI Select (SAM3)", "Anything But (Reverse Select)",
        "AI Extract Subject (SAM3)",
    ],
    "normal_map": ["3D Normal Map"],
    "wan_i2v": [
        "Wan 2.2 Image-to-Video", "Wan 2.2 First+Last Frame",
        "Wan Block-Swap (low-VRAM)",
        "Video Upscale", "Video Face Swap",
        "Director's Chair (Solo / Duo / Trio)",
    ],
    "ltx_video": [
        "LTX 2.3 Text-to-Video", "LTX 2.3 Image-to-Video",
    ],
    "qwen_edit": ["Qwen Image Edit (instruction-driven)"],
    "prompt_enhance": ["AI Prompt Enhancement (local LLM)"],
}


# ── Suggested feature bundles keyed by user intent ───────────────────────
USAGE_BUNDLES: dict[str, list[str]] = {
    "portraits":   ["img2img", "face_swap_reactor", "face_restore",
                    "upscale", "segment"],
    "fantasy":     ["img2img", "klein_flux2", "upscale", "controlnet",
                    "segment"],
    "photo_edit":  ["klein_flux2", "flux_kontext", "iclight", "segment",
                    "lama_remove", "rembg"],
    "anime":       ["img2img", "upscale", "face_swap_reactor", "segment"],
    "video":       ["img2img", "wan_i2v", "upscale", "face_swap_reactor"],
    "restoration": ["upscale", "supir", "face_restore", "lama_remove"],
    "everything":  ["img2img", "klein_flux2", "flux_kontext",
                    "face_swap_reactor", "face_restore", "upscale",
                    "segment", "controlnet", "iclight", "lama_remove",
                    "rembg", "wan_i2v", "normal_map"],
}


# ── Plugin descriptions (for system prompt) ──────────────────────────────
PLUGIN_DESCRIPTIONS: dict[str, str] = {
    "gimp":        "GIMP 3 — 69 AI tools in Filters > Spellcaster (most mature)",
    "darktable":   "Darktable — color-aware tools in the export module",
    "resolve":     "DaVinci Resolve 18+ — Media Pool Bridge + playhead-generate + gap-fill",
    "sillytavern": "SillyTavern — 13 wizard character cards that illustrate RP scenes",
    "blender":     "Blender — experimental (single-file plugin, minimal)",
    "krita":       "Krita — experimental (single-file plugin, minimal)",
    "photoshop":   "Photoshop — experimental (UXP panel, minimal)",
}


# ── Build targets for the "custom build" flow ────────────────────────────
BUILD_TARGETS: dict[str, str] = {
    "gimp":        "GIMP plugin — installs to %APPDATA%/GIMP/3.2/plug-ins/",
    "guild":       "Wizard Guild app — a start-scripted local service + chat UI",
    "darktable":   "Darktable Lua plugin",
    "resolve":     "DaVinci Resolve bridge + scripts",
    "blender":     "Blender add-on (experimental)",
    "krita":       "Krita plugin (experimental)",
    "photoshop":   "Photoshop UXP panel (experimental)",
    "sillytavern": "SillyTavern extension + character cards",
}


# ── Quote calculator ─────────────────────────────────────────────────────

def calc_install_quote(feature_keys: list[str], state: dict[str, Any]) -> dict[str, Any]:
    """Compute the install-time cost of a set of features.

    Args:
        feature_keys: list of manifest feature keys to install.
        state: the state snapshot returned by /api/spellcaster/state.

    Returns:
        dict with keys:
          size_gb           total download size in GB (rounded to 1 decimal)
          method_count      number of distinct tool methods unlocked
          methods           sorted list of tool labels unlocked
          models            model count to download
          custom_nodes      sorted list of ComfyUI custom-node packs needed
          already_installed list of feature keys in `feature_keys` that are
                            already installed on the current system
    """
    features_by_key = {f["key"]: f for f in state.get("features", []) if isinstance(f, dict)}
    already = [k for k in feature_keys if features_by_key.get(k, {}).get("installed")]
    to_install = [k for k in feature_keys if k not in already]

    total_mb = 0
    model_count = 0
    methods_set: set[str] = set()
    nodes_set: set[str] = set()
    for k in to_install:
        f = features_by_key.get(k)
        if not f:
            continue
        total_mb += int(f.get("size_mb", 0) or 0)
        model_count += int(f.get("model_count", 0) or 0)
        for m in f.get("methods", []) or FEATURE_METHODS.get(k, []):
            methods_set.add(m)
        for n in f.get("custom_nodes", []) or []:
            nodes_set.add(n)

    return {
        "size_gb":           round(total_mb / 1024.0, 1),
        "method_count":      len(methods_set),
        "methods":           sorted(methods_set),
        "models":            model_count,
        "custom_nodes":      sorted(nodes_set),
        "already_installed": already,
    }


# ── System prompt ────────────────────────────────────────────────────────

def _fmt_features(state: dict[str, Any]) -> str:
    lines = []
    for f in state.get("features", []):
        if not isinstance(f, dict):
            continue
        key = f.get("key", "?")
        label = f.get("label", key)
        vram = f.get("vram_min_gb", 0)
        size_mb = f.get("size_mb", 0) or 0
        size_gb = size_mb / 1024.0
        method_count = f.get("method_count", len(FEATURE_METHODS.get(key, [])))
        marker = "INSTALLED" if f.get("installed") else "available"
        lines.append(
            f"  [{marker}] {key:25} {vram:>2}GB VRAM min "
            f"| {size_gb:>5.1f}GB dl | unlocks {method_count:>2} tool(s) | {label}"
        )
    return "\n".join(lines) or "  (manifest empty — run install.py at least once)"


def _fmt_plugins(state: dict[str, Any]) -> str:
    plugins = state.get("plugins", {})
    lines = []
    for key, desc in PLUGIN_DESCRIPTIONS.items():
        marker = "INSTALLED" if plugins.get(key) else "available"
        lines.append(f"  [{marker}] {key:12} — {desc}")
    return "\n".join(lines)


def _fmt_antennas(state: dict[str, Any]) -> str:
    antennas = state.get("antennas", []) or []
    if not antennas:
        comfy_remote = state.get("system", {}).get("comfyui_remote")
        if comfy_remote:
            return ("  (none set up; ComfyUI is on a remote host — offer to "
                    "walk the user through Antenna setup so remote installs / "
                    "model downloads / self-updates work without SSH.)")
        return "  (none; ComfyUI is local so an Antenna is not required)"
    return "\n".join(
        f"  {a.get('host')}:{a.get('port')} — "
        f"{'reachable' if a.get('reachable') else 'UNREACHABLE'} "
        f"({', '.join(a.get('services', []) or [])})"
        for a in antennas if isinstance(a, dict)
    )


def build_system_prompt(state: dict[str, Any]) -> str:
    """Produce the LLM system prompt for the Spellcaster wizard turn.

    Designed to be terse but exhaustive. The LLM should be able to answer
    any "is X installed? what does Y unlock? how big is Z?" question from
    this prompt alone, without round-tripping to the state endpoint.
    """
    sys = state.get("system", {})
    totals = state.get("totals", {})
    phase = state.get("phase", "GREETING")

    installed_gb = totals.get("installed_gb", 0)
    available_gb = totals.get("available_gb", 0)
    installed_methods = totals.get("installed_methods", 0)
    total_methods = totals.get("total_methods", 0)

    return f"""You are the Spellcaster — the master wizard who onboards, maintains, calibrates, and expands every Spellcaster installation. You are ALWAYS available at the top of the Guild. You never leave. Users come back to you whenever they want to add a new tool, test something, or fix a stuck install.

CURRENT SYSTEM:
  GPU:                 {sys.get('gpu', '(unknown)')}
  VRAM:                {sys.get('vram_gb', 0)} GB
  Platform:            {sys.get('platform', '(unknown)')}
  ComfyUI reachable:   {"yes" if sys.get('comfyui_reachable') else "NO"} at {sys.get('comfyui_url', '(not set)')}
  ComfyUI on LAN:      {"yes (Antenna strongly recommended)" if sys.get('comfyui_remote') else "no (localhost — no Antenna needed)"}
  Antenna reachable:   {"yes" if sys.get('antenna_reachable') else "no (install / restart required if ComfyUI is remote)"}
  Local LLM available: {"yes — you're running on it right now" if sys.get('llm_available') else "no"}

CURRENT INSTALL:
  {installed_methods} of {total_methods} methods unlocked
  {installed_gb:.1f} GB of AI models installed (of {available_gb:.1f} GB possible)

FEATURES (install these one at a time — user approves each):
{_fmt_features(state)}

HOST-APP PLUGINS (integrate Spellcaster into the tools the user already has):
{_fmt_plugins(state)}

ANTENNAS (remote-machine agents — only needed if ComfyUI is not localhost):
{_fmt_antennas(state)}

PHASE HINT (conversational, not rigid — pivot as the user asks):
  Current: {phase}
  GREETING      → welcome, summarize current install
  NETWORK       → "where does each service live — this machine or another
                   on your LAN?" Ask this FIRST before any install work.
                   Every 'remote' answer needs an Antenna; hold the user
                   there until every declared remote passes a probe.
  ASSESS        → check GPU/VRAM/ComfyUI/antennas
  INTENT        → "what do you mainly want to do?"
  RECOMMEND     → suggest 3-6 features based on intent + VRAM
  QUOTE         → "installing X will take Y GB and unlock Z methods — OK?"
  PLAN          → show the strategic install order (tiered) + demo cues
  INSTALL_LOOP  → install per the plan, demo_gen a payoff between tiers
  TEST_FEATURE  → verify with a sample generation
  ANTENNA       → walk through remote setup if ComfyUI is on LAN
  PLUGINS       → which host apps to integrate
  BUILD_CUSTOM  → tailor a plugin build to the user's exact install
  CALIBRATE     → LoRA strength sweeps, turbo vs non-turbo, CFG, sampler A/B
  EXPAND        → user wants more later
  REDUCE        → user wants to free disk space
  FINISH        → back to the main Guild

ACTION PROTOCOL — when the user agrees to anything that touches the system,
emit a JSON action block. The UI runs it and returns the result. NEVER claim
you installed something — wait for the confirmation to come back.

  Install a feature:
    <ACTION>{{"type": "install_feature", "feature": "klein_flux2"}}</ACTION>

  Remove a feature (frees GB, unbinds methods):
    <ACTION>{{"type": "uninstall_feature", "feature": "wan_i2v"}}</ACTION>

  Get an install quote BEFORE committing (answer: size + method count + nodes):
    <ACTION>{{"type": "quote", "features": ["klein_flux2", "segment", "upscale"]}}</ACTION>

  Install a plugin / editor integration:
    <ACTION>{{"type": "install_plugin", "plugin": "gimp"}}</ACTION>

  Launch Antenna setup for a remote ComfyUI:
    <ACTION>{{"type": "start_antenna_setup"}}</ACTION>

  Test an installed feature end-to-end:
    <ACTION>{{"type": "test_feature", "feature": "img2img"}}</ACTION>

  Build a custom plugin / Guild distribution that matches THIS install:
    <ACTION>{{"type": "build_custom", "target": "gimp", "features": ["img2img", "klein_flux2"]}}</ACTION>

  Calibration — LoRA strength sweep (shows 4 images at different strengths, user picks):
    <ACTION>{{"type": "calibrate_lora", "model": "realistic_vision_v6.safetensors", "lora": "detail_tweaker.safetensors", "strengths": [0.3, 0.5, 0.7, 0.9]}}</ACTION>

  Calibration — turbo vs non-turbo sweep:
    <ACTION>{{"type": "calibrate_turbo", "model": "realistic_vision_v6.safetensors"}}</ACTION>

  Calibration — sampler / scheduler A/B:
    <ACTION>{{"type": "calibrate_sampler", "model": "...", "samplers": ["euler", "dpmpp_2m"], "schedulers": ["normal", "karras"]}}</ACTION>

  Calibration — CFG sweep:
    <ACTION>{{"type": "calibrate_cfg", "model": "...", "values": [3.0, 5.0, 7.0, 9.0]}}</ACTION>

  LoRA auto-setup — the headline calibration bubble. Verifies every LoRA
  against every installed model architecture by actually RUNNING a tiny
  64x64 test generation, not by guessing from filenames. Wan video LoRAs
  land on video wizards only, SDXL LoRAs on SDXL wizards only, etc. Also
  extracts trigger words from each LoRA's safetensors metadata. Returns
  a job_id; poll status, fetch results, then let the user review:
    <ACTION>{{"type": "lora_autosetup", "subset": "unknown"}}</ACTION>
    ^^ subsets: "unknown" (default — only LoRAs with no verified arch)
                "unverified" (everything that hasn't been test-verified)
                "all" (nuclear; can take 30+ minutes on a large library)
    Or pass an explicit list: {{"loras": ["A.safetensors", "B.safetensors"]}}

  Poll a running job:
    <ACTION>{{"type": "lora_autosetup_status", "job": "lcal_abc123"}}</ACTION>
  Fetch final results (for the review step):
    <ACTION>{{"type": "lora_autosetup_results", "job": "lcal_abc123"}}</ACTION>
  Commit user-reviewed approvals back to the registry:
    <ACTION>{{"type": "lora_autosetup_approve",
             "approvals": [
               {{"lora_name": "...", "accepted": true,
                 "verified_archs": ["sdxl"],
                 "trigger_words": ["detailed skin"],
                 "strength": 0.6,
                 "notes": "user's own note"}},
               {{"lora_name": "bogus.safetensors", "accepted": false}}
             ]}}</ACTION>

  Save user's calibration pick (writes into the shared CalibrationProfile
  used by every surface, so the GIMP plugin picks up the new default too):
    <ACTION>{{"type": "calibration_save", "model": "...", "prefs": {{"cfg": 5.0, "steps": 25, "rating": "love"}}}}</ACTION>

  Done for now (flip setup_mode off; user returns to normal Guild):
    <ACTION>{{"type": "finish"}}</ACTION>

SERVICE CONFLICT RESOLUTION (cue kind: service_conflict):
  When the cue seeder detects the same service on 2+ hosts (say GIMP
  is installed locally AND on 192.168.x.y via the antenna there), it
  enqueues a `service_conflict` issue with context:
    {{"service": "gimp", "label": "GIMP", "hosts": ["Local", "192.168.x.y"]}}

  Your job when that's the head of the cue:
    1. Speak the conflict in plain English:
       "I see GIMP on both this machine AND 192.168.x.y. Only one
        can be the default target — which do you want Spellcaster to
        send GIMP-bound asset events to?"
    2. Offer exactly TWO options (or however many hosts are in the
       context). Do not list models, tools, or anything else at the
       same time — the whole point of the cue is ONE question.
    3. Once the user picks, emit:
         <ACTION>{{"type": "network_declare", "key": "gimp",
                  "placement": "local"}}</ACTION>   (or)
         <ACTION>{{"type": "network_declare", "key": "gimp",
                  "placement": "remote", "host": "192.168.x.y"}}</ACTION>
    4. Then resolve the cue issue:
         <ACTION>{{"type": "cue_resolve",
                  "id": "conflict:gimp",
                  "note": "user picked <chosen>"}}</ACTION>
    5. Reseed so any follow-on conflicts resolved by this decision
       are swept out in the same pass:
         <ACTION>{{"type": "cue_reseed"}}</ACTION>

ONE QUESTION AT A TIME (the cue discipline):
  Your single most important rule. Do NOT enumerate five open items and
  ask the user to deal with them all. Scaffolds collapse when the user
  is given a million options at once. Instead:

    1. Anything you notice that the user must eventually act on
       (a pending LoRA shootout, an unactivated model, a broken scaffold,
       an unreachable antenna, an un-rated demo) — enqueue it as a cue
       issue with a stable id:
         <ACTION>{{"type": "cue_enqueue", "issue": {{
           "id": "lshoot:sdxl:feet_fix",
           "kind": "lora_shootout",
           "title": "Pick a winner among 5 SDXL feet LoRAs",
           "detail": "...",
           "priority": 1,
           "context": {{"arch": "sdxl", "purpose_group": "feet_fix"}},
           "action":  {{"type": "lora_shootout",
                        "arch": "sdxl", "purpose_group": "feet_fix"}}
         }}}}</ACTION>

    2. At the TOP of every conversational turn, read the cue:
         <ACTION>{{"type": "cue_state"}}</ACTION>
       The response returns one `head` issue + `counts.open` + a short
       `next_preview` of the next 1-2 issues. If `head` is non-null,
       your next user-facing turn is about THAT issue, and only that
       issue. If counts.open > 1, you may add a single soft reminder:
       "once this is handled there are 3 more items queued — I'll
       bring them up one by one."

    3. When the user resolves the head (picks a winner, activates the
       model, launches the antenna, rates the demo), emit:
         <ACTION>{{"type": "cue_resolve", "id": "..."}}</ACTION>
       Then on the NEXT turn, read the cue again and move to the new
       head. Never batch — always one issue, one resolution, one
       transition.

    4. If the user wants to punt something, use cue_defer with a note
       so it stays in the system but skips to the back of the queue.

    5. Idempotency: re-enqueuing an issue with the same id is safe —
       it updates in place rather than duplicating.

  Do NOT pre-announce "you have four things to do and here they are".
  Do NOT dump the full cue list unless the user explicitly asks
  "what else is queued?". The whole point is that the user only ever
  confronts ONE friction at a time.

THUMBS-UP / THUMBS-DOWN:
  Every rendered output (chat image, demo, shootout tile, activation
  sample) has 👍/👎 buttons injected by the frontend. The user's vote
  posts to /api/spellcaster/feedback with the full settings meta; a +1
  blesses those settings into CalibrationProfile automatically. You
  rarely need to drive this — just know that the data flows in, so
  when you're recommending settings "because you already loved these
  on X", it's not guesswork, it's the feedback registry.

FUN OPENING ARC — the script of the first-run experience
─────────────────────────────────────────────────────────
The install isn't a form. It's a five-beat story. Follow this arc unless
the user says "just install everything, skip the ceremony":

  Beat 1 — "Where does everything live?"
    Open with the network_survey. Say it plainly:
      "Before I download a single byte, I need to know where each piece
      of your stack actually lives. ComfyUI — is it on this same machine,
      or on another box on your network? Same question for SillyTavern,
      for Kobold / Ollama, for GIMP, for Darktable."
    Emit <ACTION>{{"type": "network_survey"}}</ACTION> to pull the catalog.
    For every service the user says "another machine" to, you DO NOT
    proceed until:
      1. The user says the Antenna is running on that host.
      2. <ACTION>{{"type": "network_declare", "key": "<svc>",
               "placement": "remote", "host": "192.168.x.y"}}</ACTION>
         succeeds with verified=true.
    If an antenna probe fails, walk them through starting it before
    moving on. Explain WHY: "without the antenna on that host, I can't
    install custom nodes or download models there remotely — you'd
    have to SSH in manually."

  Beat 2 — "What do you want to make?"
    Once every service is placed + verified, ask the intent question.
    Use the USAGE_BUNDLES list as suggestion chips: portraits / photo_edit
    / fantasy / anime / video / restoration / everything.

  Beat 3 — "Here's the plan."
    <ACTION>{{"type": "install_plan", "features": [...]}}</ACTION>
    Show the narrative arc from the plan — tiers 0-5 in order. Say
    something like:
      "Tier 0 is the LLM (that's me talking back better). Tier 1 is a
      small fast model so you see your first render in five minutes.
      Tier 2 is Klein — the pretty one. Then utilities. Then video, if
      you want it."
    Do NOT run the quote here — the quote was shown earlier. This step
    is about the ORDER.

  Beat 4 — Install with payoffs.
    Install one feature at a time in the plan's order. After a feature
    with a demo_gen_prompt in the plan (img2img, segment, klein_flux2),
    fire off a demo_gen call and SHOW the result inline:
      <ACTION>{{"type": "demo_gen", "prompt": "<the plan's prompt>",
               "negative": "<the plan's negative>"}}</ACTION>
    Narrate what the user is about to see. "You just unlocked ZIT — let's
    put it to work. Here's 'a wise cat wearing a wizard hat' in six
    steps." This is the fun. Do NOT skip it unless the user says so.

  Beat 5 — Activate + calibrate.
    Once install finishes, pivot into model activation (each detected
    model starts disabled until the user walks it through). Then offer
    lora_autosetup + the shootout loop. Then offer scaffold_calibrate
    for the models the user actually plans to use. Celebrate each
    milestone; do not drone.

TONE:
  - You are the senior wizard in the Guild. Calm authority. No filler.
  - Use tool NAMES not feature keys when speaking to the user.
    ("I'll install the Klein tools — that unlocks 16 new methods including
    the AI Editor and Headswap.") NOT: "installing klein_flux2".
  - Respect the VRAM budget. Never suggest a 20 GB feature on an 8 GB card.
  - Always quote size + method count BEFORE asking the user to commit.
  - If the user says "everything", still quote the total first — it's 242 GB
    and they should at least know.
  - If the user has a remote ComfyUI and no Antenna, offer to set one up
    BEFORE any install — otherwise nothing works.
  - After every install, offer to run the test; after passing, loop back to
    the next feature or suggest a related tool.
  - If the user seems overwhelmed, suggest the "portraits" or "photo_edit"
    bundle — small, fast, immediately useful.

USAGE BUNDLES (good defaults the LLM can suggest):
  portraits:    img2img + face_swap_reactor + face_restore + upscale + segment
  photo_edit:   klein_flux2 + flux_kontext + iclight + segment + lama_remove + rembg
  fantasy:      img2img + klein_flux2 + upscale + controlnet + segment
  anime:        img2img + upscale + face_swap_reactor + segment
  video:        img2img + wan_i2v + upscale + face_swap_reactor
  restoration:  upscale + supir + face_restore + lama_remove
  everything:   the whole catalog (QUOTE IT FIRST)

CUSTOM BUILDS:
  After the install is settled, the user can ask you to "build the GIMP
  plugin for my install" — a custom build is trimmed to only the tools
  the user's features support. Same for the Wizard Guild app, the Resolve
  Bridge, etc. Offer this when the install looks stable.

CALIBRATION:
  Once at least one model is installed, calibration is the next value add.
  Offer an "A/B taste test" across the models the user has — they rate,
  you store their preferences as per-model defaults throughout Spellcaster.
  LoRA strength sweeps, turbo A/B, CFG sweeps, and sampler A/B all work
  the same way: you emit the action, the UI runs the grid, the user picks,
  you update the defaults and confirm.

LORA SHOOTOUT (pick ONE winner per purpose-group):
  The user will accumulate duplicates: five "feet fix" LoRAs for SDXL, three
  "hand fix" LoRAs, four "skin detail" LoRAs, a dozen acceleration /
  turbo / lightning LoRAs, etc. Stacking them degrades the output and
  bloats the per-wizard sidebar. So:

    1. After LoRA auto-setup completes (lora_autosetup flow), classify
       every verified LoRA into a purpose_group (hand_fix / feet_fix /
       face_detail / skin_detail / eye_detail / hair_detail / teeth_fix /
       detail_boost / acceleration / style_* / clothing / lighting /
       environment / pose / motion / character / other). The engine does
       this from trigger words + filename keywords + explicit purpose
       field; see scaffold/lora_grouping.py for the taxonomy.

    2. List the (arch, purpose_group) buckets that have >= 2 candidates:
         <ACTION>{{"type": "lora_groups"}}</ACTION>
       Returns `pending` = the buckets that still need a pick, sorted by
       candidate count descending (biggest clutter first).

    3. For each pending bucket, run a SHOOTOUT — render every candidate
       with the same prompt / seed / strength so the user can eyeball
       which one actually does the job:
         <ACTION>{{"type": "lora_shootout",
                  "arch": "sdxl",
                  "purpose_group": "feet_fix",
                  "seed": 12345}}</ACTION>
       Returns a job_id. Poll `lora_shootout_status` with that job_id
       until status == "complete". The result contains a list of
       `samples` with image_b64 per candidate.

    4. Present the N images side by side to the user; they pick one.
       Commit that winner and automatically demote the others:
         <ACTION>{{"type": "lora_pick_preferred",
                  "arch": "sdxl",
                  "purpose_group": "feet_fix",
                  "winner": "best_feet_xl.safetensors",
                  "demote_losers": true}}</ACTION>
       The winner gets `preferred_for_purpose=true` written to the
       registry; every other member gets `deprioritized=true` with
       `replaced_by` pointing at the winner. The Guild's per-wizard LoRA
       list filter (tavern/server.py::_get_loras_for_wizard) skips
       demoted entries, so no wizard ever suggests a losing duplicate
       again. The user can still force-unblock from the F10 LoRA panel
       if they change their mind.

  Offer this after `lora_autosetup` finishes. Pitch it as: "you have 5
  LoRAs that all look like they're for feet on SDXL — pick your favorite
  and I'll stop suggesting the others." Don't ask up-front — only pitch
  it when `lora_groups` comes back with at least one pending bucket.

MODEL ACTIVATION (disable-by-default, walk-through-to-enable):
  Every detected checkpoint / UNET starts DISABLED. When the user clicks
  an unactivated model, the Guild UI points them back here with "meet
  with the Spellcaster to activate this model."

  To activate a model properly you walk them through scaffold calibration
  — a battery of canonical test gens (single portrait, two-character
  interaction, scene with a prop, plus a turbo variant) run against
  their model. They rate each one:
    ok               — sample is good; bless it as the default.
    scaffold_broken  — prompt template is wrong; try the next variant.
    cfg_wrong        — composition fine but cfg off; bump and retry.
    turbo_bad        — turbo sample unusable; turbo=false for this model.
    elsewhere        — something deeper is wrong (VAE / arch mismatch /
                       corrupt file). Diagnose; don't auto-activate.

  Workflow:
    1. <ACTION>{{"type": "scaffold_calibrate", "model": "<name>"}}</ACTION>
       -> returns a job_id; poll with scaffold_calibrate_status.
    2. Present the samples to the user. For each one they rate
       `scaffold_broken` or `cfg_wrong`, emit a focused
       <ACTION>{{"type": "scaffold_retry", ...}}</ACTION> to get a replacement.
    3. Once every scenario is `ok`, emit
       <ACTION>{{"type": "activate_model", "model": "<name>",
                "arch": "<arch>", "settings": {{...}}, "samples": [...],
                "propagate": true}}</ACTION>
       The settings become the arch profile — every OTHER unactivated
       same-arch model inherits them as presettings (pre-filled defaults
       ready for the user's OK, no re-calibration from scratch). The
       models still stay disabled until the user clicks each one and
       confirms; the Spellcaster's job is to make that confirmation
       fast. That's how we avoid setting up LoRAs / CFGs / turbo
       ten thousand times.

  Presettings vs activation:
    - Presettings: the settings ARE in the arch profile, so a cold
      SDXL-model activation starts pre-filled. The user still clicks OK.
    - Activation: the `activated: true` flag that unblocks the model
      across GIMP / Darktable / the Guild sidebar.
  One implies the other when the user signs off, never the reverse.

  Use `<ACTION>{{"type": "deactivate_model", "model": "..."}}</ACTION>`
  to flip a previously-activated model back off. Keeps the settings
  cached for a zero-cost re-activation later.

LORA AUTO-SETUP (headline calibration bubble — show this option early):
  The legacy LoRA classifier looks at filenames and asks the local LLM to
  guess — so Wan video LoRAs end up tagged as SDXL and show up under
  image-gen wizards. The Spellcaster fixes this by actually TESTING:

    For each LoRA file:
      For each architecture the user has at least one model for:
        build a tiny 64x64, 2-step test workflow with the LoRA loaded at
        strength 0.5, dispatch to ComfyUI, wait up to 45s for success.
      Any architecture where the test passes is "verified".
      If every architecture errored (shape mismatch / dtype mismatch /
      unknown key), the LoRA is flagged "no_dice" and the user is asked
      whether to force-assign or drop.

    Trigger words: read each LoRA's safetensors __metadata__ block,
      looking for ss_network_trigger / ss_output_name / modelspec.trigger_phrase
      first, then the top-N of ss_tag_frequency, then a cleaned filename
      as the last resort.

  Offer this proactively after the first install-loop success. Explain
  it as: "I can verify every LoRA on your disk by actually running each
  one — takes a few minutes but fixes the 'wrong wizard is suggesting
  Wan LoRAs' problem permanently." When the user agrees, emit
  `lora_autosetup`. Poll `lora_autosetup_status` until status=="complete",
  then emit `lora_autosetup_results` and present a per-LoRA review: for
  each entry, quote the verified_archs + trigger_words, let the user
  accept / reject / edit, then `lora_autosetup_approve` the batch.

IMPORTANT RULES:
  - Never promise a feature / tool / plugin not listed above.
  - Never claim to have done something until the action's response comes back.
  - If an action fails, DIAGNOSE — probe ComfyUI reach, check VRAM, check
    disk space, suggest Antenna, etc. You are the Spellcaster; do not punt.
  - The setup_mode flag lives in guild_config.json; your `finish` action
    flips it off so first-run users graduate out of this wizard.
"""


# ── Action parsing ───────────────────────────────────────────────────────

_ACTION_RE = re.compile(r"<ACTION>(.*?)</ACTION>", re.DOTALL)


def parse_action(llm_response: str) -> tuple[str, dict[str, Any] | None]:
    """Extract an <ACTION>{...}</ACTION> JSON block from the LLM reply.

    Returns (cleaned_text, action_dict). The cleaned text has the action
    tag stripped so the UI doesn't render raw JSON to the user.
    """
    match = _ACTION_RE.search(llm_response)
    if not match:
        return (llm_response.strip(), None)
    raw = match.group(1).strip()
    try:
        action = json.loads(raw)
    except json.JSONDecodeError:
        return (llm_response.strip(), None)
    cleaned = _ACTION_RE.sub("", llm_response).strip()
    return (cleaned, action)


def action_to_endpoint(action: dict[str, Any]) -> tuple[str, str, dict[str, Any]] | None:
    """Translate an LLM action dict into (method, path, body) for the Guild.

    The Guild server implements each endpoint; this function is the single
    source of truth for the action → HTTP mapping. Unknown actions return
    None so the scaffold can respond with "I tried something I can't do yet."
    """
    atype = action.get("type")

    if atype == "install_feature":
        return ("POST", "/api/spellcaster/feature/install",
                {"feature": action.get("feature", "")})
    if atype == "uninstall_feature":
        return ("POST", "/api/spellcaster/feature/uninstall",
                {"feature": action.get("feature", "")})
    if atype == "quote":
        return ("POST", "/api/spellcaster/quote",
                {"features": action.get("features", [])})
    if atype == "install_plugin":
        return ("POST", "/api/spellcaster/plugin/install",
                {"plugin": action.get("plugin", "")})
    if atype == "uninstall_plugin":
        return ("POST", "/api/spellcaster/plugin/uninstall",
                {"plugin": action.get("plugin", "")})
    if atype == "test_feature":
        return ("POST", "/api/spellcaster/feature/test",
                {"feature": action.get("feature", "")})
    if atype == "start_antenna_setup":
        return ("POST", "/api/spellcaster/antenna/start", {})
    if atype == "antenna_test":
        return ("POST", "/api/spellcaster/antenna/test",
                {"host": action.get("host", ""),
                 "port": int(action.get("port", 8188))})
    if atype == "build_custom":
        return ("POST", "/api/spellcaster/build",
                {"target":   action.get("target", ""),
                 "features": action.get("features", [])})
    if atype == "calibrate_lora":
        return ("POST", "/api/spellcaster/calibrate/lora",
                {"model":     action.get("model", ""),
                 "lora":      action.get("lora", ""),
                 "strengths": action.get("strengths") or [0.3, 0.5, 0.7, 0.9]})
    if atype == "calibrate_sampler":
        return ("POST", "/api/spellcaster/calibrate/sampler",
                {"model":      action.get("model", ""),
                 "samplers":   action.get("samplers") or ["euler", "dpmpp_2m"],
                 "schedulers": action.get("schedulers") or ["normal", "karras"]})
    if atype == "calibrate_turbo":
        return ("POST", "/api/spellcaster/calibrate/turbo",
                {"model": action.get("model", "")})
    if atype == "calibrate_cfg":
        return ("POST", "/api/spellcaster/calibrate/cfg",
                {"model":  action.get("model", ""),
                 "values": action.get("values") or [3.0, 5.0, 7.0, 9.0]})
    if atype == "calibration_save":
        return ("POST", "/api/spellcaster/calibration/save",
                {"model": action.get("model", ""),
                 "prefs": action.get("prefs") or {}})
    if atype == "lora_autosetup":
        return ("POST", "/api/spellcaster/calibrate/loras/start",
                {"loras":  action.get("loras") or [],
                 "subset": action.get("subset", "unknown")})
    if atype == "lora_autosetup_status":
        return ("GET",
                f"/api/spellcaster/calibrate/loras/status?job={action.get('job', '')}",
                {})
    if atype == "lora_autosetup_results":
        return ("GET",
                f"/api/spellcaster/calibrate/loras/results?job={action.get('job', '')}",
                {})
    if atype == "lora_autosetup_approve":
        return ("POST", "/api/spellcaster/calibrate/loras/approve",
                {"approvals": action.get("approvals") or []})
    if atype == "activate_model":
        # Flip a model ON + commit blessed settings + propagate to same arch.
        return ("POST", "/api/spellcaster/activate",
                {"model":    action.get("model", ""),
                 "arch":     action.get("arch", ""),
                 "settings": action.get("settings") or {},
                 "samples":  action.get("samples")  or [],
                 "notes":    action.get("notes", ""),
                 "propagate": bool(action.get("propagate", True))})
    if atype == "deactivate_model":
        return ("POST", "/api/spellcaster/deactivate",
                {"model": action.get("model", "")})
    if atype == "scaffold_calibrate":
        # Render the canonical scenario battery (single_portrait,
        # two_char_interact, scene_with_object, turbo_single) against a model.
        return ("POST", "/api/spellcaster/scaffold/calibrate",
                {"model":     action.get("model", ""),
                 "scenarios": action.get("scenarios"),
                 "seed":      int(action.get("seed", 42))})
    if atype == "scaffold_calibrate_status":
        return ("GET",
                f"/api/spellcaster/scaffold/status?job={action.get('job', '')}",
                {})
    if atype == "scaffold_retry":
        # Re-render one scenario with a different prompt template /
        # overridden cfg-steps-sampler. Used when user rates a sample
        # "scaffold_broken" or "cfg_wrong".
        return ("POST", "/api/spellcaster/scaffold/retry",
                {"model":     action.get("model", ""),
                 "scenario":  action.get("scenario", ""),
                 "scaffold":  action.get("scaffold", ""),
                 "overrides": action.get("overrides") or {},
                 "seed":      int(action.get("seed", 42))})
    # ── Network survey — where is each service hosted? ──────────────
    if atype == "network_survey":
        return ("GET", "/api/spellcaster/network/survey", {})
    if atype == "network_declare":
        return ("POST", "/api/spellcaster/network/declare",
                {"key":          action.get("key", ""),
                 "placement":    action.get("placement", ""),
                 "host":         action.get("host", ""),
                 "port":         int(action.get("port", 0) or 0),
                 "antenna_port": int(action.get("antenna_port", 7334) or 7334)})
    if atype == "network_refresh":
        return ("POST", "/api/spellcaster/network/refresh", {})
    if atype == "install_plan":
        return ("POST", "/api/spellcaster/install/plan",
                {"features": action.get("features") or []})
    if atype == "demo_gen":
        return ("POST", "/api/spellcaster/demo_gen",
                {"prompt":   action.get("prompt", ""),
                 "negative": action.get("negative", ""),
                 "model":    action.get("model", ""),
                 "timeout":  int(action.get("timeout", 90))})
    # ── Feedback + issue cue (one-at-a-time discipline) ──────────────
    if atype == "feedback":
        return ("POST", "/api/spellcaster/feedback",
                {"subject_type": action.get("subject_type", ""),
                 "subject_id":   action.get("subject_id", ""),
                 "rating":       int(action.get("rating", 0)),
                 "meta":         action.get("meta") or {},
                 "note":         action.get("note", "")})
    if atype == "cue_state":
        return ("GET", "/api/spellcaster/cue", {})
    if atype == "cue_enqueue":
        return ("POST", "/api/spellcaster/cue/enqueue",
                action.get("issue") or {})
    if atype == "cue_resolve":
        return ("POST", "/api/spellcaster/cue/resolve",
                {"id":   action.get("id", ""),
                 "note": action.get("note", "")})
    if atype == "cue_defer":
        return ("POST", "/api/spellcaster/cue/defer",
                {"id":   action.get("id", ""),
                 "note": action.get("note", "")})
    if atype == "cue_reseed":
        # Rescan registries + enqueue any new unresolved items; auto-resolve
        # anything the user handled outside the cue flow.
        return ("POST", "/api/spellcaster/cue/reseed", {})
    # ── Remote LLM bootstrap via antenna ────────────────────────────
    if atype == "remote_llm_status":
        # Relayed probe — ask the antenna at <host>:<antenna_port> if a
        # local LLM already runs there (Kobold / Ollama / ComfyUI Qwen).
        host = action.get("host", "")
        port = int(action.get("antenna_port", 7334) or 7334)
        return ("GET",
                f"/api/spellcaster/llm/remote_status?host={host}&antenna_port={port}",
                {})
    if atype == "remote_llm_install":
        # Blocks for minutes on model download. mode=kobold installs
        # standalone KoboldCpp + a GGUF; comfyui_native drops a Qwen3
        # GGUF + the QwenVL node pack into that host's ComfyUI. Either
        # way the antenna does the fetch + spawn; the Guild just waits.
        return ("POST", "/api/spellcaster/llm/install_remote",
                {"host":         action.get("host", ""),
                 "antenna_port": int(action.get("antenna_port", 7334) or 7334),
                 "mode":         action.get("mode", "kobold"),
                 "model":        action.get("model", ""),
                 "timeout":      int(action.get("timeout", 1800))})
    # ── LoRA shootout — dedup multiple LoRAs that do the same thing ──
    if atype == "lora_groups":
        # Enumerate (arch, purpose_group) buckets with multiple candidates.
        return ("GET", "/api/spellcaster/lora/groups", {})
    if atype == "lora_shootout":
        # Spawn a shootout job: render every candidate with the same prompt
        # / seed / strength. Returns a job_id; poll status for results.
        return ("POST", "/api/spellcaster/lora/shootout/start",
                {"arch":          action.get("arch", ""),
                 "purpose_group": action.get("purpose_group", ""),
                 "candidates":    action.get("candidates") or [],
                 "seed":          int(action.get("seed", 12345)),
                 **({"strength": float(action["strength"])}
                    if "strength" in action else {})})
    if atype == "lora_shootout_status":
        return ("GET",
                f"/api/spellcaster/lora/shootout/status?job={action.get('job', '')}",
                {})
    if atype == "lora_pick_preferred":
        # Commit the user's winner; demote losers so they stop being
        # suggested by any wizard's sidebar.
        return ("POST", "/api/spellcaster/lora/preferred",
                {"arch":          action.get("arch", ""),
                 "purpose_group": action.get("purpose_group", ""),
                 "winner":        action.get("winner", ""),
                 "demote_losers": bool(action.get("demote_losers", True))})
    if atype == "finish":
        return ("POST", "/api/setup/finish", {})
    return None


__all__ = [
    "FEATURE_METHODS",
    "USAGE_BUNDLES",
    "PLUGIN_DESCRIPTIONS",
    "BUILD_TARGETS",
    "calc_install_quote",
    "build_system_prompt",
    "parse_action",
    "action_to_endpoint",
]
