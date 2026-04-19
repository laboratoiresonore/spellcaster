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
  ASSESS        → check GPU/VRAM/ComfyUI/antennas
  INTENT        → "what do you mainly want to do?"
  RECOMMEND     → suggest 3-6 features based on intent + VRAM
  QUOTE         → "installing X will take Y GB and unlock Z methods — OK?"
  INSTALL_LOOP  → install one at a time, testing after each
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

  Done for now (flip setup_mode off; user returns to normal Guild):
    <ACTION>{{"type": "finish"}}</ACTION>

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
    if atype == "finish":
        return ("POST", "/api/setup/finish", {})
    return None


# ── Public wizard class ──────────────────────────────────────────────────

class SpellcasterWizardScaffold:
    """Stateless Spellcaster-wizard scaffold. Call respond() per user turn.

    All persistent state (what's installed, setup_mode, antennas, calibration
    results) lives in the Guild server — this module only produces prompts
    and parses actions.
    """

    def __init__(self, llm_client=None):
        """llm_client: callable(system_prompt, user_msg) -> str.
        If None, callers must invoke their own LLM and pass the response to
        parse_action() directly.
        """
        self.llm_client = llm_client

    def system_prompt(self, state: dict[str, Any]) -> str:
        return build_system_prompt(state)

    def respond(self, user_message: str, state: dict[str, Any]) -> dict[str, Any]:
        """One conversational turn.

        Returns:
            {"text": str, "action": dict | None,
             "endpoint": (method, path, body) | None}
        """
        if not self.llm_client:
            raise RuntimeError("SpellcasterWizardScaffold requires an llm_client")
        system = self.system_prompt(state)
        reply = self.llm_client(system, user_message)
        text, action = parse_action(reply)
        endpoint = action_to_endpoint(action) if action else None
        return {"text": text, "action": action, "endpoint": endpoint}


__all__ = [
    "FEATURE_METHODS",
    "USAGE_BUNDLES",
    "PLUGIN_DESCRIPTIONS",
    "BUILD_TARGETS",
    "calc_install_quote",
    "build_system_prompt",
    "parse_action",
    "action_to_endpoint",
    "SpellcasterWizardScaffold",
]
