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


# ── Canonical-builder detection helpers ──────────────────────────────

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


def _classify_method(handler_body: str) -> tuple[str, str]:
    """Return (ssot_status, notes) for one method's handler body."""
    if not handler_body:
        return ("unknown", "")
    for name in _CANONICAL_BUILDER_NAMES:
        if name in handler_body:
            return ("canonical", f"routes through {name}()")
    # Heuristic: a handler that constructs a raw `"class_type":` dict
    # is likely building its own workflow instead of delegating.
    if '"class_type"' in handler_body or "'class_type'" in handler_body:
        return ("duplicate", "constructs its own workflow JSON (SSoT "
                               "violation — should route through a "
                               "spellcaster_core.workflows build_* "
                               "helper)")
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
        out.append({
            "id": proc_id,
            "name": label,
            "description": doc,
            "handler": handler,
            "feature_gate": pf_map.get(proc_id, "None"),
            "ssot_status": ssot,
            "ssot_notes": notes,
        })
    return out


def _darktable_scaffolds(repo_root: str) -> list[dict]:
    """Extract Darktable button registrations."""
    path = os.path.join(repo_root, "plugins", "darktable",
                         "comfyui_connector.lua")
    src = _read(path)
    if not src:
        return []
    out: list[dict] = []
    # Match `local <name>_btn = dt.new_widget("button") { ... }` blocks.
    pat = re.compile(
        r'local\s+(?P<name>[a-z_]+)\s*=\s*dt\.new_widget\("button"\)\s*'
        r'\{(?P<body>[^}]*?)\}',
        re.DOTALL)
    for m in pat.finditer(src):
        name = m.group("name")
        body = m.group("body")
        label_m = re.search(r'label\s*=\s*["\']([^"\']+)["\']', body)
        tooltip_m = re.search(r'tooltip\s*=\s*["\']([^"\']+)["\']', body)
        # Darktable label often set right AFTER the widget block via
        # `btn.label = "..."` — fall back to the surrounding text.
        if not label_m:
            lbl_assign = re.search(
                rf'{re.escape(name)}\.label\s*=\s*["\']([^"\']+)["\']', src)
            if lbl_assign:
                label_m = lbl_assign
        # For SSoT we look at the `clicked_callback` body — the button
        # body contains it inline.
        cb_m = re.search(r'clicked_callback\s*=\s*function\s*\([^)]*\)\s*'
                          r'(.*?)end\s*,?', body, re.DOTALL)
        cb_body = cb_m.group(1) if cb_m else ""
        # Lua plugin constructs workflow JSON inline (R132's known
        # SSoT violation); flag when we see '"class_type"' in the
        # callback or in a function it immediately calls.
        ssot, notes = _classify_method(cb_body)
        if ssot == "unknown" and "build_wan_i2v_json" in cb_body:
            ssot = "duplicate"
            notes = ("Lua-side workflow builder — parallel to "
                      "spellcaster_core.workflows.build_wan_video. "
                      "Scheduled refactor: route through Guild API.")
        out.append({
            "id": f"darktable-{name}",
            "name": (label_m.group(1) if label_m else name),
            "description": (tooltip_m.group(1) if tooltip_m else ""),
            "handler": name,
            "ssot_status": ssot,
            "ssot_notes": notes,
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
        ssot, notes = _classify_method(src)
        out.append({
            "id": f"resolve-{fn[:-3]}",
            "name": fn[:-3].replace("_", " ").title(),
            "description": doc,
            "handler": fn,
            "ssot_status": ssot,
            "ssot_notes": notes,
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
        ssot, notes = _classify_method(body)
        out.append({
            "id": f"sillytavern-{name_m.group(1)}",
            "name": f"/{name_m.group(1)}",
            "description": (help_m.group(1) if help_m else ""),
            "handler": name_m.group(1),
            "ssot_status": ssot,
            "ssot_notes": notes,
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
        summary = {
            "total": len(scaffolds),
            "canonical": sum(1 for s in scaffolds
                             if s.get("ssot_status") == "canonical"),
            "duplicate": sum(1 for s in scaffolds
                             if s.get("ssot_status") == "duplicate"),
            "unknown":   sum(1 for s in scaffolds
                             if s.get("ssot_status") == "unknown"),
        }
        groups.append({
            "id":          plugin_id,
            "label":       label,
            "icon":        icon,
            "description": blurb,
            "scaffolds":   scaffolds,
            "summary":     summary,
        })
    return groups


def invalidate_cache():
    """Called by the plugin auto-updater after a git pull so freshly-
    added methods appear in the manifest without waiting the full
    5-minute TTL."""
    _CACHE.clear()
