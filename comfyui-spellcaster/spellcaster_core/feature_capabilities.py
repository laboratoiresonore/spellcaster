"""Feature ↔ capability resolver — only surface features that actually work.

Every wizard, workflow, menu, or "Send to X" button can declare the
capabilities it needs. At render time the Guild asks this module:
"Given the current /api/capabilities snapshot, can this feature run?"
If yes, show it. If no, hide it.

Capability string grammar (flat, easy to grep in manifests):

    service:<svc>                     — antenna declares the service
    service:<svc>:online              — AND the antenna is online
    comfyui:node:<class_type>         — a ComfyUI node class_type exists
    comfyui:pack:<pack_name>          — a specific custom-node pack installed
    resolve:running                   — Resolve is actively scripting
    resolve:lut:<category>:<name>     — a LUT exists (case-insensitive match)
    resolve:lut:<name>                — any LUT named <name>, any category
    resolve:preset:<name>             — a render preset with that name

Resolution rules:
  - Capabilities are evaluated against a Guild-wide pool that unions
    every online antenna's report. "Any antenna provides X" → satisfied.
    Use `resolve_service_host(cap, snap)` if you need to know WHICH
    antenna will actually serve the request.
  - Unknown capability strings resolve to False (unsatisfied) — safer to
    hide an unparseable feature than to surface a broken one.

Usage:
    from .feature_capabilities import (
        resolve_capability, resolve_feature)

    ok, reason = resolve_capability("comfyui:pack:ComfyUI-Spellcaster", snap)
    feature = {"name": "klein-refine", "capabilities": [...]}
    ok, missing = resolve_feature(feature, snap)
    if ok:
        surface_feature(feature)
"""
from __future__ import annotations

from typing import Any, Optional


def _iter_online_antennas(snap: dict[str, Any]):
    """Yield each online-antenna row from /api/capabilities output.

    The /api/capabilities shape is:
        {"antennas": {"<hostname>": {...}}, "cached_at": ...}
    and every row carries "online": True by construction (the Guild
    only scans online ones). We still double-check for safety.
    """
    antennas = (snap or {}).get("antennas") or {}
    for hostname, row in antennas.items():
        if not isinstance(row, dict):
            continue
        if row.get("online") is False:
            continue
        yield hostname, row


def _lut_matches(luts_by_cat: dict[str, list[dict[str, Any]]],
                 category: str | None, name: str) -> bool:
    """Case-insensitive match on a LUT {category}/{name}. Category None
    = match any category. Name matches on stem (case-insensitive,
    spaces and hyphens interchangeable)."""
    def _norm(s: str) -> str:
        return (s or "").lower().replace("-", " ").replace("_", " ").strip()
    name_norm = _norm(name)
    for cat_key, entries in (luts_by_cat or {}).items():
        if category is not None and _norm(cat_key) != _norm(category):
            continue
        for entry in entries or []:
            if _norm(entry.get("name", "")) == name_norm:
                return True
    return False


def resolve_capability(cap: str, snap: dict[str, Any]
                        ) -> tuple[bool, Optional[str]]:
    """Evaluate a capability string against a /api/capabilities snapshot.

    Returns (satisfied, reason). When satisfied is False, `reason` is a
    human-readable explanation suitable for surfacing in tooltips or
    diagnostic panels.
    """
    if not cap or not isinstance(cap, str):
        return False, "empty capability"
    parts = cap.split(":")
    head = parts[0]

    if head == "service":
        # service:<svc>[:online]
        if len(parts) < 2:
            return False, "service:<name> required"
        svc = parts[1]
        need_online = (len(parts) > 2 and parts[2] == "online")
        for _, row in _iter_online_antennas(snap):
            services = row.get("services") or []
            if svc in services:
                if need_online and not row.get("online"):
                    continue
                return True, None
        return False, f"no antenna declares service {svc!r}"

    if head == "comfyui" and len(parts) >= 3 and parts[1] == "node":
        target = ":".join(parts[2:])  # node names can contain ':'
        for _, row in _iter_online_antennas(snap):
            cu = row.get("comfyui") or {}
            if not cu.get("reachable"):
                continue
            for _, nodes in (cu.get("custom_node_packs") or {}).items():
                if target in (nodes or []):
                    return True, None
        return False, f"node class_type {target!r} not found in any antenna's ComfyUI"

    if head == "comfyui" and len(parts) >= 3 and parts[1] == "pack":
        pack = ":".join(parts[2:])
        for _, row in _iter_online_antennas(snap):
            cu = row.get("comfyui") or {}
            if pack in (cu.get("custom_node_packs") or {}):
                return True, None
        return False, f"custom-node pack {pack!r} not installed anywhere"

    if head == "resolve" and len(parts) == 2 and parts[1] == "running":
        # For "running" we need services_detail.resolve.reachable to be True,
        # which the live probe in heartbeat would populate — but the
        # capabilities snapshot doesn't carry it. Fall back to: any antenna
        # that declares resolve AND has resolve.reachable in the capabilities
        # row (which is populated by /resolve/luts responding — proves
        # scripting is at minimum importable).
        for _, row in _iter_online_antennas(snap):
            rv = row.get("resolve") or {}
            if rv.get("reachable"):
                return True, None
        return False, "no antenna reports Resolve reachable"

    if head == "resolve" and len(parts) >= 3 and parts[1] == "lut":
        # Two shapes: resolve:lut:<name>  OR  resolve:lut:<category>:<name>
        if len(parts) == 3:
            cat, name = None, parts[2]
        else:
            cat, name = parts[2], ":".join(parts[3:])
        for _, row in _iter_online_antennas(snap):
            rv = row.get("resolve") or {}
            if not rv.get("reachable"):
                continue
            by_cat = rv.get("luts_by_category") or {}
            if _lut_matches(by_cat, cat, name):
                return True, None
        cat_str = f" in category {cat!r}" if cat else ""
        return False, f"LUT {name!r}{cat_str} not found on any antenna"

    if head == "resolve" and len(parts) >= 3 and parts[1] == "preset":
        # Guild's /api/capabilities doesn't carry presets by default (adds
        # latency). We approximate: if resolve is reachable on any antenna,
        # consider "preset" a soft match. Callers that need to confirm a
        # specific preset exists should call /resolve/render-presets.
        preset = ":".join(parts[2:])
        for _, row in _iter_online_antennas(snap):
            rv = row.get("resolve") or {}
            if rv.get("reachable"):
                return True, None
        return False, f"Resolve not reachable (cannot verify preset {preset!r})"

    return False, f"unknown capability {cap!r}"


def resolve_feature(feature: dict[str, Any], snap: dict[str, Any]
                     ) -> tuple[bool, list[str]]:
    """Check every required capability of a feature. Returns
    (satisfied, missing_reasons). Features with NO capabilities always
    satisfy (equivalent to an empty AND).
    """
    caps = feature.get("capabilities") or []
    if not caps:
        return True, []
    missing: list[str] = []
    for cap in caps:
        ok, reason = resolve_capability(cap, snap)
        if not ok:
            missing.append(f"{cap}: {reason}")
    return (len(missing) == 0), missing


def resolve_service_host(service: str, snap: dict[str, Any]
                          ) -> Optional[str]:
    """Return the hostname of the antenna best-suited to serve `service`,
    or None if none qualify. Simple heuristic: first reachable host in
    lexicographic order. The production router in
    `antenna_registry.choose_antenna_for` has smarter ranking (vram
    for comfyui, etc.) — use that when actually dispatching traffic.
    This helper is for UI-side "which box would this run on?" hints.
    """
    hits = []
    for hostname, row in _iter_online_antennas(snap):
        if service == "comfyui":
            cu = row.get("comfyui") or {}
            if cu.get("reachable"):
                hits.append(hostname)
        elif service == "resolve":
            rv = row.get("resolve") or {}
            if rv.get("reachable"):
                hits.append(hostname)
        else:
            if service in (row.get("services") or []):
                hits.append(hostname)
    hits.sort(key=lambda h: h.lower())
    return hits[0] if hits else None


# ── Built-in manifest for Spellcaster's own feature set ──────────────

# Keep tight and accurate: each entry is a feature the Guild surfaces
# somewhere that ONLY works when its capabilities resolve. Additions
# here propagate to the Guild automatically via /api/feature-manifest.
SPELLCASTER_FEATURES: list[dict[str, Any]] = [
    {
        "key": "video.send_to_resolve",
        "label": "Send timeline to Resolve",
        "capabilities": ["resolve:running"],
        "ui_hint": "header-button:→ Resolve",
    },
    {
        "key": "video.render_in_resolve",
        "label": "Render current timeline in Resolve",
        "capabilities": ["resolve:running"],
        "ui_hint": "header-button:Render",
    },
    {
        "key": "comfyui.klein.refine",
        "label": "Klein/Flux 2 refine workflow",
        "capabilities": [
            "service:comfyui",
            "comfyui:node:Flux2KleinRefLatentController",
            "comfyui:node:Flux2KleinTextRefBalance",
        ],
        "ui_hint": "klein-enhancer",
    },
    {
        "key": "comfyui.sam3_extract",
        "label": "SAM3 object extraction",
        "capabilities": [
            "service:comfyui",
            "comfyui:pack:ComfyUI-Spellcaster",
        ],
        "ui_hint": "sam3-wizard",
    },
    {
        "key": "resolve.lut.kodak_2383",
        "label": "Kodak 2383 film-emulation grade",
        "capabilities": [
            "resolve:running",
            "resolve:lut:Kodak 2383",
        ],
        "ui_hint": "color-grade-preset",
    },
]
