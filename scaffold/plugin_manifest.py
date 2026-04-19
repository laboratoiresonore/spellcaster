"""Cross-plugin method inventory (R144).

The Travelling Wizard's Scaffolds tab used to show only the Wizard
Guild's own characters from `_STUDIO_BY_ID`, so the user had no
visibility into the 80+ GIMP procedures, 33 DaVinci Resolve scripts,
40+ Darktable buttons, and 16 SillyTavern slash commands that the
rest of the app ships. This module statically extracts each plugin's
method list straight from the source files checked into the repo, so
the Guild serves an honest "what can this installation do" manifest
without having to launch GIMP / Darktable / Resolve to query them.

Design notes:

- Parse the source, don't import it. The GIMP plugin bootstraps a
  GObject ABI that blows up outside a running GIMP process; the
  Darktable plugin is Lua; Resolve scripts rely on a Fusion runtime.
  Regex extraction of the REGISTRATION SHAPE (menu_map tuples, dt.
  new_widget button blocks, SlashCommand.fromProps({name: ...}),
  etc.) is the cheapest honest inventory.

- Cache per-plugin inventories for 5 min. The source files are
  ~24K lines each; a cold re-parse is still under 100ms, but the
  UI calls this often during editing.

- Canonical-builder detection: for each plugin method, grep the
  surrounding function body for calls to
  spellcaster_core.workflows.build_* — flags the method as
  "canonical" (SSoT compliant) when detected, "duplicate" when the
  plugin constructs its own workflow JSON (the Darktable Lua case,
  which violates the zero-duplication rule and is flagged so the
  user can see it in the UI), or "unknown" when no workflow shape
  is visible (cross-plugin sends, utility actions, etc.).
"""
from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional


_CACHE: Dict[str, tuple[float, list[dict]]] = {}
_CACHE_TTL_S = 300.0


def _read(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


# ── Classification helpers ──────────────────────────────────────────

# spellcaster_core/workflows.py ships a catalog of build_* functions
# every plugin SHOULD reach through; a method whose handler body
# references one of these is flagged "canonical" in the UI.
_CANONICAL_BUILDER_NAMES = (
    "build_img2img", "build_txt2img", "build_inpaint", "build_outpaint",
    "build_upscale", "build_wavespeed_upscale", "build_rembg",
    "build_rembg_birefnet", "build_ddcolor", "build_normal_map",
    "build_lama_remove", "build_lut", "build_color_match",
    "build_klein_img2img", "build_klein_img2img_ref",
    "build_klein_headswap",
    "build_faceswap", "build_faceswap_model", "build_faceswap_mtb",
    "build_face_restore", "build_photo_restore",
    "build_detail_hallucinate", "build_colorize",
    "build_controlnet_gen", "build_iclight", "build_supir",
    "build_faceid_img2img", "build_pulid_flux",
    "build_save_face_model",
    "build_video_upscale", "build_video_reactor",
    "build_wan_video", "build_wan_flf",
    "build_wan22_t2v",
    "build_ltx_video", "build_seedvr2_video_upscale",
    "build_generate_anything",
)

# Substring patterns for the CATEGORY axis (what the method DOES) —
# separate from the SSoT-status axis (how it dispatches). Each entry
# maps a set of id / name substrings to a canonical category tag.
# First match wins; more-specific buckets come first.
_CATEGORY_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("send_to_gimp",       ("send-to-gimp", "to_gimp", "send_frame_to_gimp",
                             "sc-send-to-gimp")),
    ("send_to_resolve",    ("send-to-resolve", "to_resolve",
                             "send_frame_to_resolve", "send_clip_to_guild",
                             "sc-send-to-resolve")),
    ("send_to_darktable",  ("send-to-darktable", "send_frame_to_darktable",
                             "sc-send-to-darktable")),
    ("send_to_sillytavern",("send-to-sillytavern", "send_frame_to_sillytavern",
                             "sc-send-to-sillytavern")),
    ("video_generation",   ("wan", "ltx", "i2v", "t2v", "v2v", "video",
                             "animate", "vace")),
    ("image_generation",   ("txt2img", "img2img", "generate", "klein",
                             "faceid", "pulid", "generate_from")),
    ("inpaint_outpaint",   ("inpaint", "outpaint", "erasure", "erase")),
    ("faceswap",           ("faceswap", "face_swap", "face-swap", "reactor",
                             "mtb")),
    ("restore_enhance",    ("detail", "enhance", "restore", "upscale",
                             "supir", "photo_restore", "face_restore")),
    ("color_relight",      ("iclight", "colorize", "ddcolor", "lut",
                             "color-match", "color_match", "relight")),
    ("rembg_mask",         ("rembg", "birefnet", "remove_bg", "mask",
                             "sam3", "lama")),
    ("trajectory",         ("trajectory",)),
    ("pipeline",           ("pipeline", "pipe", "multi-step", "photobooth",
                             "body_factory", "clothing_store", "studio_set")),
    ("queue_render",       ("render_all", "render-all", "render_queue",
                             "cancel", "retry", "pause", "resume",
                             "refresh_ready", "timeline", "edl",
                             "preset_shootout")),
    ("chat_flow",          ("studio_", "model_", "comfyui_", "custom_",
                             "generated")),
    ("capture",            ("capture", "playhead", "markers_to",
                             "import", "grab")),
    ("prompt_enhance",     ("enhance", "prompt_", "variation", "reprompt")),
    ("settings",           ("config", "settings", "theme", "check_inbox",
                             "capabilities", "help", "status", "open_bridge",
                             "open_guild")),
    ("upload_send",        ("send-image", "upload", "attach", "load_", "save_",
                             "delete_")),
]


def _category_for(*probes: str) -> str:
    """Return a category tag based on method id / name / handler / file."""
    haystack = " ".join(str(p or "") for p in probes).lower()
    for tag, needles in _CATEGORY_RULES:
        if any(n in haystack for n in needles):
            return tag
    return "other"


# Labels for the UI, matching _CATEGORY_RULES' tags.
_CATEGORY_LABELS = {
    "send_to_gimp":       "Send → GIMP",
    "send_to_resolve":    "Send → Resolve",
    "send_to_darktable":  "Send → Darktable",
    "send_to_sillytavern":"Send → SillyTavern",
    "video_generation":   "Video generation",
    "image_generation":   "Image generation",
    "inpaint_outpaint":   "Inpaint / outpaint",
    "faceswap":           "Face swap / identity",
    "restore_enhance":    "Restore / enhance",
    "color_relight":      "Color / relight",
    "rembg_mask":         "Background removal / mask",
    "trajectory":         "Trajectory / motion",
    "pipeline":           "Multi-step pipeline",
    "queue_render":       "Queue / render control",
    "chat_flow":          "Chat scaffold",
    "capture":            "Capture / import",
    "prompt_enhance":     "Prompt enhance / variations",
    "settings":           "Settings / diagnostics",
    "upload_send":        "Upload / file ops",
    "other":              "Other",
}


def _pretty_from_var(var_name: str) -> str:
    """Turn a Lua-style button variable like `load_btn` or
    `send_face_model_btn` into a human label ('Load', 'Send Face
    Model'). Used when we can't find an explicit `.label` / `.tooltip`
    assignment in the source."""
    name = str(var_name or "").strip()
    for suf in ("_btn", "_button", "-btn"):
        if name.endswith(suf):
            name = name[: -len(suf)]
            break
    # Split on underscores/dashes, title-case each chunk.
    parts = [p for p in name.replace("-", "_").split("_") if p]
    if not parts:
        return var_name
    return " ".join(p[:1].upper() + p[1:] for p in parts)


def _classify_method(handler_body: str, *, is_thin_client: bool = False) -> tuple[str, str]:
    """Return (ssot_status, notes) for one method's handler body.

    Statuses:
      canonical   — handler body calls a spellcaster_core.workflows
                    build_* helper (single source of truth respected).
      duplicate   — handler body literally constructs a workflow JSON
                    (contains "class_type": dicts). SSoT violation.
      thin_client — handler body POSTs/GETs a Guild HTTP endpoint
                    (Resolve scripts, SillyTavern commands). Correct
                    design for out-of-process clients — no workflow
                    code to duplicate.
      utility     — handler body does local work with no workflow
                    construction (file ops, settings dialogs).
      unknown     — nothing classifiable.
    """
    if not handler_body:
        return ("unknown", "")
    for name in _CANONICAL_BUILDER_NAMES:
        if name in handler_body:
            return ("canonical", f"routes through {name}()")
    if '"class_type"' in handler_body or "'class_type'" in handler_body:
        return ("duplicate", "constructs its own workflow JSON (SSoT "
                               "violation — should route through a "
                               "spellcaster_core.workflows build_* "
                               "helper)")
    if is_thin_client:
        return ("thin_client", "thin client — calls Guild API over HTTP")
    # Heuristics for common Guild-API thin-client idioms.
    if any(k in handler_body for k in (
            "/api/video/shots", "/api/events/emit", "/api/assets",
            "/api/app_control", "/api/stt", "/api/tts",
            "guild._post_json", "guild.create_shot", "guild.queue_shot",
            "guild.render_", "CrossInterfaceClient")):
        return ("thin_client", "thin client — calls Guild API over HTTP")
    # Heuristics for utility / dialog / settings handlers.
    if any(k in handler_body for k in (
            "show_message(", "prompt_text(", "dt.new_widget",
            "Gtk.FileChooser", "set_active(", "get_text(",
            "config.get(", "get_config(", "open_url(", "webbrowser")):
        return ("utility", "local UI / config handler (no workflow)")
    return ("unknown", "")


# ── Per-plugin extractors ────────────────────────────────────────────

def _gimp_scaffolds(repo_root: str) -> list[dict]:
    """Parse plugins/gimp/comfyui-connector/_spellcaster_main.py's
    menu_map + _PROC_FEATURES + _menu_paths so we can return the
    per-procedure label, docstring, feature gate, and SSoT status."""
    path = os.path.join(repo_root, "plugins", "gimp",
                         "comfyui-connector", "_spellcaster_main.py")
    src = _read(path)
    if not src:
        return []
    # Find the menu_map block (the first matching dict after the
    # `menu_map = {` line that sits inside the registration method).
    start = src.find("menu_map = {")
    if start < 0:
        return []
    depth = 0
    i = src.find("{", start)
    j = i
    while j < len(src):
        c = src[j]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                break
        j += 1
    block = src[i:j + 1]
    # Each entry: "proc-id": ("Label", self._handler, "docstring"),
    entry_pat = re.compile(
        r'"(?P<id>spellcaster-[a-z0-9\-_]+)"\s*:\s*'
        r'\(\s*"(?P<label>[^"]+)"\s*,\s*self\.(?P<handler>_[a-zA-Z0-9_]+)\s*,\s*'
        r'"(?P<doc>[^"]+)"',
        re.DOTALL)
    # Pull _PROC_FEATURES so we know which procedure needs a feature
    # gate to actually appear in the GIMP menu.
    pf_start = src.find("_PROC_FEATURES = {")
    pf_map: dict[str, Optional[str]] = {}
    if pf_start > 0:
        depth = 0
        pi = src.find("{", pf_start)
        pj = pi
        while pj < len(src):
            c = src[pj]
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    break
            pj += 1
        pf_block = src[pi:pj + 1]
        for m in re.finditer(r'"(spellcaster-[a-z0-9\-_]+)"\s*:\s*'
                              r'(None|"[a-zA-Z0-9_]+")', pf_block):
            k = m.group(1)
            v = m.group(2)
            pf_map[k] = None if v == "None" else v.strip('"')
    out: list[dict] = []
    for m in entry_pat.finditer(block):
        proc_id = m.group("id")
        label = m.group("label")
        handler = m.group("handler")
        doc = m.group("doc")
        # Pull the handler's body for SSoT classification.
        h_re = re.compile(rf"def {re.escape(handler)}\b")
        h_match = h_re.search(src)
        body = ""
        if h_match:
            # Grab ~200 lines after the def to catch builder calls.
            lines = src[h_match.start():].splitlines()[:200]
            body = "\n".join(lines)
        ssot, notes = _classify_method(body)
        cat = _category_for(proc_id, label, handler)
        out.append({
            "id": proc_id,
            "name": label,
            "description": doc,
            "handler": handler,
            "feature_gate": pf_map.get(proc_id, "None"),
            "ssot_status": ssot,
            "ssot_notes": notes,
            "category": cat,
            "category_label": _CATEGORY_LABELS.get(cat, cat),
        })
    return out


def _darktable_scaffolds(repo_root: str) -> list[dict]:
    """Extract Darktable button registrations.

    Labels and tooltips are set across three Darktable conventions:
      1. Inline in the widget block: ``dt.new_widget("button") {
         label = "Go", tooltip = "..." }``
      2. Assigned after the block: ``my_btn.label = "Go"`` /
         ``my_btn.tooltip = "..."``
      3. Pre-compiled strings assigned via intermediate variables.
    We try all three and fall back to a titlecased variable name so
    the UI never shows the raw ``load_btn`` identifier.

    SSoT detection also follows the clicked_callback into the NAMED
    function it dispatches to (e.g. ``clicked_callback = function()
    process_wan_i2v(images) end``) — looking at just the callback
    body misses the heavy lifting that lives in ``process_wan_i2v``.
    """
    path = os.path.join(repo_root, "plugins", "darktable",
                         "comfyui_connector.lua")
    src = _read(path)
    if not src:
        return []
    out: list[dict] = []
    pat = re.compile(
        r'local\s+(?P<name>[a-z_][a-z0-9_]*)\s*=\s*dt\.new_widget\("button"\)\s*'
        r'\{(?P<body>[^}]*?)\}',
        re.DOTALL)
    seen: set[str] = set()
    for m in pat.finditer(src):
        name = m.group("name")
        if name in seen:
            continue
        seen.add(name)
        body = m.group("body")

        # 1. Inline attributes
        label = None
        tooltip = None
        for key in ("label", "title"):
            lm = re.search(rf'{key}\s*=\s*["\']([^"\']+)["\']', body)
            if lm:
                label = lm.group(1)
                break
        tm = re.search(r'tooltip\s*=\s*["\']([^"\']+)["\']', body)
        if tm:
            tooltip = tm.group(1)

        # 2. Follow-on `.label = "..."` / `.tooltip = "..."` assignments
        # after the widget declaration. Use a *close-by* window so
        # unrelated later assignments don't bleed in.
        tail_start = m.end()
        tail = src[tail_start: tail_start + 600]
        if label is None:
            lm = re.search(rf'{re.escape(name)}\.(?:label|title)\s*=\s*'
                            r'["\']([^"\']+)["\']', tail)
            if lm:
                label = lm.group(1)
        if tooltip is None:
            tm = re.search(rf'{re.escape(name)}\.tooltip\s*=\s*["\']([^"\']+)["\']', tail)
            if tm:
                tooltip = tm.group(1)

        # 3. Pretty-print variable name as last-resort label.
        if not label:
            label = _pretty_from_var(name)

        # Extract the clicked_callback body so we can chase named
        # helper functions from it (Darktable's Lua code dispatches
        # to process_wan_i2v / process_image / send_clip / etc).
        cb_m = re.search(r'clicked_callback\s*=\s*function\s*\([^)]*\)\s*'
                          r'(.*?)end\s*,?', body, re.DOTALL)
        cb_body = cb_m.group(1) if cb_m else ""
        # Chase named helper calls referenced inside the callback.
        # Lua's non-greedy `.*?end` matches the FIRST `end` (usually
        # an inner if/for block's end, not the function's), so the
        # only reliable bound is a fixed-size window after the
        # function's opening signature.
        helper_refs = set(re.findall(r'\b([a-z][a-z0-9_]*)\s*\(', cb_body))
        chased_body = cb_body
        for fn in list(helper_refs)[:8]:  # cap to keep regex cost bounded
            fm = re.search(
                rf'(?:^|\n)\s*(?:local\s+)?function\s+{re.escape(fn)}\s*\(',
                src, re.MULTILINE)
            if fm:
                # Grab a generous 8000-char slice — Darktable's
                # longest workflow builders top out around 5k chars.
                chased_body += "\n" + src[fm.end(): fm.end() + 8000]
        # Darktable-specific: its Lua handlers build workflows via
        # string.format + process_* helpers. Flag them BEFORE the
        # generic classifier so a `dt.gui.selection` call in the
        # callback body doesn't demote a real workflow builder to
        # "utility". Lua can't import spellcaster_core.workflows, so
        # these are SSoT violations by design — the honest fix is to
        # refactor the plugin to POST at the Guild API (thin client).
        DUPLICATE_HINTS = (
            "build_wan_i2v_json", "build_img2img_json",
            "build_faceswap_model_json", "build_faceswap_direct_json",
            "build_save_face_model_json", "build_rembg_json",
            "build_upscale_json", "build_lama_json", "build_lut_json",
            "build_outpaint_json", "build_style_transfer_json",
            "build_face_restore_json", "build_photo_restore_json",
            "build_detail_hallucinate_json", "build_colorize_json",
            '"KSamplerAdvanced"', '"CheckpointLoaderSimple"',
            '"VAELoader"', '"WanImageToVideo"',
            '"UNETLoader"', '"UnetLoaderGGUF"',
        )
        if any(h in chased_body for h in DUPLICATE_HINTS):
            ssot = "duplicate"
            notes = ("Lua-side workflow builder (process_* / "
                     "build_*_json) — parallels the canonical "
                     "spellcaster_core.workflows helpers. Lua can't "
                     "import Python; the honest SSoT fix is to "
                     "route through the Guild API (like Resolve + "
                     "SillyTavern plugins do).")
        else:
            ssot, notes = _classify_method(chased_body)
            # Utility-ish Lua handlers — fetchers, savers, settings
            # dialogs, toggles. Catches the buttons that obviously
            # aren't workflow generators.
            if ssot == "unknown" and any(k in chased_body for k in (
                    "dt.preferences", "fetch_all_loras", "dt.print",
                    "dt.gui.selection", "load_face_model",
                    "save_face_model", "delete_face_model",
                    "set_text", "set_selected_index", "dt.new_widget")):
                ssot = "utility"
                notes = "local Darktable UI / preferences handler"

        cat = _category_for(name, label or "", tooltip or "", chased_body[:800])
        out.append({
            "id": f"darktable-{name}",
            "name": label,
            "description": tooltip or "",
            "handler": name,
            "ssot_status": ssot,
            "ssot_notes": notes,
            "category": cat,
            "category_label": _CATEGORY_LABELS.get(cat, cat),
        })
    return out


def _resolve_scaffolds(repo_root: str) -> list[dict]:
    """Each .py file in plugins/resolve/scripts/ is a menu entry."""
    script_dir = os.path.join(repo_root, "plugins", "resolve", "scripts")
    out: list[dict] = []
    if not os.path.isdir(script_dir):
        return out
    for fn in sorted(os.listdir(script_dir)):
        if not fn.endswith(".py") or fn.startswith("_"):
            continue
        full = os.path.join(script_dir, fn)
        src = _read(full)
        if not src:
            continue
        # Module docstring = first triple-quoted block.
        doc_m = re.search(r'^\s*"""(.+?)"""', src, re.DOTALL)
        doc = ""
        if doc_m:
            lines = doc_m.group(1).strip().splitlines()
            doc = lines[0].strip() if lines else ""
        # Resolve scripts are thin clients by design — they POST to
        # the Guild's /api/video/* endpoints. Mark them as such
        # (default thin_client=True inside the classifier) so they
        # don't land under the generic "unknown" bucket.
        ssot, notes = _classify_method(src, is_thin_client=True)
        cat = _category_for(fn, src[:1500])
        out.append({
            "id": f"resolve-{fn[:-3]}",
            "name": fn[:-3].replace("_", " ").title(),
            "description": doc,
            "handler": fn,
            "ssot_status": ssot,
            "ssot_notes": notes,
            "category": cat,
            "category_label": _CATEGORY_LABELS.get(cat, cat),
        })
    return out


def _sillytavern_scaffolds(repo_root: str) -> list[dict]:
    """SillyTavern plugin registers slash commands via
    SlashCommand.fromProps({name, callback, helpString, ...})."""
    path = os.path.join(repo_root, "plugins", "sillytavern",
                         "spellcaster-st", "index.js")
    src = _read(path)
    if not src:
        return []
    out: list[dict] = []
    # Catch `SlashCommand.fromProps({ name: "x", ... })` blocks.
    pat = re.compile(
        r'SlashCommand\.fromProps\s*\(\s*\{\s*(?P<body>[^}]*?)\}',
        re.DOTALL)
    for m in pat.finditer(src):
        body = m.group("body")
        name_m = re.search(r'name\s*:\s*["\']([^"\']+)["\']', body)
        help_m = re.search(r'helpString\s*:\s*["\']([^"\']+)["\']', body)
        if not name_m:
            continue
        # SillyTavern plugin: all slash commands hit either the local
        # ST server-plugin endpoints (which themselves forward to the
        # Guild) or /api/events/emit directly. Thin-client by design.
        ssot, notes = _classify_method(body, is_thin_client=True)
        cmd_name = name_m.group(1)
        cat = _category_for(cmd_name, body[:500])
        out.append({
            "id": f"sillytavern-{cmd_name}",
            "name": f"/{cmd_name}",
            "description": (help_m.group(1) if help_m else ""),
            "handler": cmd_name,
            "ssot_status": ssot,
            "ssot_notes": notes,
            "category": cat,
            "category_label": _CATEGORY_LABELS.get(cat, cat),
        })
    return out


# ── Public API ───────────────────────────────────────────────────────

_PLUGIN_LABELS = [
    ("wizard_guild", "Wizard Guild", "💬",
     "Chat-based LLM scaffolds served by the local Guild."),
    ("gimp",         "GIMP Plugin", "🖼️",
     "GIMP menu procedures; each routes through "
     "spellcaster_core.workflows."),
    ("darktable",    "Darktable Plugin", "📸",
     "Darktable Lua actions. Lua can't import Python, so workflow "
     "construction is duplicated locally — SSoT violation flagged "
     "per-method."),
    ("resolve",      "DaVinci Resolve Plugin", "🎬",
     "Fusion scripts under plugins/resolve/scripts/. Thin clients — "
     "they POST at the Guild API."),
    ("sillytavern",  "SillyTavern Plugin", "🍺",
     "Slash commands registered by the ST server plugin. Thin "
     "clients — routed through the Guild."),
]


def build_manifest(repo_root: str,
                    wizard_guild_scaffolds: Optional[list[dict]] = None,
                    force: bool = False) -> list[dict]:
    """Return [{id, label, icon, description, scaffolds, summary}, ...]
    one entry per plugin source. `wizard_guild_scaffolds` should be
    the caller's already-built /api/scaffolds payload so we don't
    re-scan _STUDIO_BY_ID here (the Guild owns that state)."""
    now = time.time()
    groups: list[dict] = []
    for plugin_id, label, icon, blurb in _PLUGIN_LABELS:
        cached = _CACHE.get(plugin_id)
        if cached and not force and (now - cached[0]) < _CACHE_TTL_S:
            scaffolds = cached[1]
        else:
            if plugin_id == "wizard_guild":
                scaffolds = wizard_guild_scaffolds or []
            elif plugin_id == "gimp":
                scaffolds = _gimp_scaffolds(repo_root)
            elif plugin_id == "darktable":
                scaffolds = _darktable_scaffolds(repo_root)
            elif plugin_id == "resolve":
                scaffolds = _resolve_scaffolds(repo_root)
            elif plugin_id == "sillytavern":
                scaffolds = _sillytavern_scaffolds(repo_root)
            else:
                scaffolds = []
            # Skip caching the wizard_guild group — it's caller-
            # provided and changes whenever a user banishes/creates
            # a wizard.
            if plugin_id != "wizard_guild":
                _CACHE[plugin_id] = (now, scaffolds)
        # Sort by category label then name so each group reads in a
        # logical order when expanded: every "Send → X" row together,
        # every "Image generation" row together, etc.
        scaffolds = sorted(scaffolds,
                            key=lambda s: (s.get("category_label", "zzz"),
                                             s.get("name", "").lower()))
        summary = {
            "total":       len(scaffolds),
            "canonical":   sum(1 for s in scaffolds if s.get("ssot_status") == "canonical"),
            "duplicate":   sum(1 for s in scaffolds if s.get("ssot_status") == "duplicate"),
            "thin_client": sum(1 for s in scaffolds if s.get("ssot_status") == "thin_client"),
            "utility":     sum(1 for s in scaffolds if s.get("ssot_status") == "utility"),
            "unknown":     sum(1 for s in scaffolds if s.get("ssot_status") == "unknown"),
        }
        # Count by category too so the UI can render a per-group
        # breakdown ("27 Image generation · 14 Face swap · …").
        cat_counts: dict[str, int] = {}
        for s in scaffolds:
            k = s.get("category_label", "Other")
            cat_counts[k] = cat_counts.get(k, 0) + 1
        groups.append({
            "id":            plugin_id,
            "label":         label,
            "icon":          icon,
            "description":   blurb,
            "scaffolds":     scaffolds,
            "summary":       summary,
            "category_counts": cat_counts,
        })
    return groups


def invalidate_cache():
    """Called by the plugin auto-updater after a git pull so freshly-
    added methods appear in the manifest without waiting the full
    5-minute TTL."""
    _CACHE.clear()
