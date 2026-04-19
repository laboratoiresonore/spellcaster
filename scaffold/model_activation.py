"""Model activation + arch-level propagation.

Every detected checkpoint / UNET starts DISABLED until the user walks it
through the Spellcaster's activation flow. The flow produces a per-model
record:

    {
      "model":            "juggernautXL_v9Rundiffusionphoto2.safetensors",
      "arch":             "sdxl",
      "activated":        True,
      "activated_ts":     <unix>,
      "samples":          [list of sampler / cfg / turbo / prompt-scaffold
                           outcomes the user rated during setup],
      "settings":         {"cfg": 6.5, "steps": 30, "sampler": "dpmpp_2m",
                           "scheduler": "karras", "turbo": False,
                           "prompt_scaffold": "sdxl_booru_tags"},
      "notes":            "user note",
    }

When the user activates ONE SDXL model, the same settings propagate to
every other *unactivated* SDXL model — so they are pre-filled with
known-good defaults but stay disabled (the user still has to click
"activate" on each to flip the flag). This avoids calibrating the same
thing 10,000 times while keeping the user in the driver's seat on which
models they actually want exposed.

Two layers of memory:

  1. Per-MODEL registry (this module) — tracks activation status,
     per-model overrides, and user notes. Lives in `model_activation.json`.
  2. Per-ARCH profile (piggybacks on spellcaster_core.preference_calibration's
     CalibrationProfile) — stores the "good defaults" that apply to every
     model of that arch. When a model is activated, the arch profile is
     written once; every subsequent same-arch activation inherits it.
"""
from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass, field, asdict
from typing import Callable, Optional


# ── Persistent registry ──────────────────────────────────────────────────

_REGISTRY_LOCK = threading.Lock()
_REGISTRY_PATH_CACHE = None  # resolved once, cached


def _default_registry_path() -> str:
    """Resolve the registry path — next to server.py's state dir if
    available, else alongside this file (for test runs)."""
    global _REGISTRY_PATH_CACHE
    if _REGISTRY_PATH_CACHE:
        return _REGISTRY_PATH_CACHE
    # Prefer tavern/.guild_state/model_activation.json when the Guild is
    # the caller. Fall back to the scaffold dir for unit tests.
    candidates = []
    try:
        import tavern.server as _gs  # type: ignore
        state_dir = getattr(_gs, "_STATE_DIR", None)
        if state_dir:
            candidates.append(os.path.join(state_dir, "model_activation.json"))
    except Exception:
        pass
    candidates.append(os.path.join(os.path.dirname(__file__), "model_activation.json"))
    _REGISTRY_PATH_CACHE = candidates[0]
    return _REGISTRY_PATH_CACHE


def _load_registry(path: Optional[str] = None) -> dict:
    path = path or _default_registry_path()
    if not os.path.isfile(path):
        return {"models": {}, "arch_profiles": {}, "version": 1}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {"models": {}, "arch_profiles": {}, "version": 1}
        data.setdefault("models", {})
        data.setdefault("arch_profiles", {})
        data.setdefault("version", 1)
        return data
    except Exception:
        return {"models": {}, "arch_profiles": {}, "version": 1}


def _save_registry(data: dict, path: Optional[str] = None) -> None:
    path = path or _default_registry_path()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


# ── Public API ───────────────────────────────────────────────────────────

def get_status(model_name: str, arch: str = "") -> dict:
    """Return the activation record for a model. Creates a stub on first
    call — the record is only persisted when something meaningful (user
    approval, test outcome) attaches to it.
    """
    with _REGISTRY_LOCK:
        reg = _load_registry()
    entry = reg.get("models", {}).get(model_name)
    if entry:
        return entry
    # Synthesize a stub. Not saved — caller writes when there's real data.
    return {
        "model":      model_name,
        "arch":       arch,
        "activated":  False,
        "samples":    [],
        "settings":   {},
        "notes":      "",
        "presettings_from": None,
    }


def is_activated(model_name: str) -> bool:
    with _REGISTRY_LOCK:
        reg = _load_registry()
    entry = reg.get("models", {}).get(model_name, {})
    return bool(entry.get("activated"))


def all_activation_statuses(detected_models: list[dict]) -> dict[str, dict]:
    """Bulk status lookup for a list of discovered models.

    Args:
        detected_models: `preference_calibration.discover_models(server)`
                          output — each dict has at least `name` + `arch`.

    Returns:
        {model_name: {activated, has_presettings, arch, settings, ...}}
    """
    with _REGISTRY_LOCK:
        reg = _load_registry()
    models = reg.get("models", {})
    archs = reg.get("arch_profiles", {})

    out: dict[str, dict] = {}
    for m in detected_models:
        name = m.get("name")
        if not name:
            continue
        entry = models.get(name)
        arch = m.get("arch") or (entry or {}).get("arch", "")
        if entry:
            out[name] = {
                "activated":       bool(entry.get("activated")),
                "arch":            arch,
                "settings":        entry.get("settings", {}),
                "has_presettings": bool(entry.get("settings")),
                "activated_ts":    entry.get("activated_ts"),
                "notes":           entry.get("notes", ""),
            }
        else:
            # No record yet. If an arch profile exists for this model's arch,
            # the model INHERITS presettings (so the user sees "pre-configured,
            # awaiting your OK" rather than "totally cold start").
            arch_profile = archs.get(arch)
            out[name] = {
                "activated":       False,
                "arch":            arch,
                "settings":        dict(arch_profile or {}),
                "has_presettings": bool(arch_profile),
                "activated_ts":    None,
                "notes":           "",
            }
    return out


def activate_model(
    model_name: str,
    arch: str,
    settings: Optional[dict] = None,
    samples: Optional[list] = None,
    notes: str = "",
    propagate_to_arch: bool = True,
) -> dict:
    """Mark `model_name` as activated and optionally promote its settings
    to the arch-level profile so every other same-arch model inherits.

    Args:
        model_name:         e.g. "juggernautXL_v9Rundiffusionphoto2.safetensors"
        arch:               architecture key ("sdxl", "illustrious", ...)
        settings:           {cfg, steps, sampler, scheduler, turbo, prompt_scaffold}
        samples:            list of {scenario, seed, rating, notes} dicts
                            capturing the user's per-test-gen verdicts.
        notes:              free-form user note.
        propagate_to_arch:  if True (default), writes `settings` into the
                            arch_profile so subsequent same-arch models are
                            pre-configured.

    Returns:
        the updated activation record.
    """
    if not model_name:
        raise ValueError("model_name required")
    settings = dict(settings or {})
    now = time.time()

    with _REGISTRY_LOCK:
        reg = _load_registry()
        models = reg.setdefault("models", {})
        archs = reg.setdefault("arch_profiles", {})

        entry = models.get(model_name, {
            "model": model_name, "arch": arch,
            "activated": False, "samples": [],
            "settings": {}, "notes": "",
        })
        entry["arch"] = arch or entry.get("arch", "")
        entry["activated"] = True
        entry["activated_ts"] = now
        if settings:
            entry["settings"] = settings
        if samples:
            entry["samples"] = samples
        if notes:
            entry["notes"] = notes[:500]
        models[model_name] = entry

        if propagate_to_arch and arch and settings:
            archs[arch] = dict(settings)

        _save_registry(reg)
    return entry


def deactivate_model(model_name: str) -> bool:
    """Flip a model back to disabled. Keeps the sample history and any
    per-model settings so re-activation is cheap.
    """
    with _REGISTRY_LOCK:
        reg = _load_registry()
        models = reg.get("models", {})
        entry = models.get(model_name)
        if not entry or not entry.get("activated"):
            return False
        entry["activated"] = False
        entry["deactivated_ts"] = time.time()
        _save_registry(reg)
    return True


def get_arch_profile(arch: str) -> dict:
    """Return the propagated default settings for an arch (or {} if the
    user hasn't activated any model of that arch yet).
    """
    with _REGISTRY_LOCK:
        reg = _load_registry()
    return dict(reg.get("arch_profiles", {}).get(arch) or {})


def set_arch_profile(arch: str, settings: dict) -> None:
    """Directly set arch-level defaults without activating a specific model.

    Useful when the user says "I already know SDXL should be CFG 6.5 with
    dpmpp_2m/karras — just apply that everywhere" and skips the test-gen
    ceremony for the arch.
    """
    if not arch:
        return
    with _REGISTRY_LOCK:
        reg = _load_registry()
        reg.setdefault("arch_profiles", {})[arch] = dict(settings or {})
        _save_registry(reg)


def propagation_summary() -> dict:
    """Return {arch: [model names activated of that arch]} — used by the
    Spellcaster to tell the user "you've activated 3 SDXL models; the next
    SDXL checkpoint you click is already pre-configured from them.".
    """
    with _REGISTRY_LOCK:
        reg = _load_registry()
    out: dict[str, list[str]] = {}
    for name, entry in reg.get("models", {}).items():
        if entry.get("activated"):
            out.setdefault(entry.get("arch", "unknown"), []).append(name)
    return out


__all__ = [
    "get_status",
    "is_activated",
    "all_activation_statuses",
    "activate_model",
    "deactivate_model",
    "get_arch_profile",
    "set_arch_profile",
    "propagation_summary",
]
