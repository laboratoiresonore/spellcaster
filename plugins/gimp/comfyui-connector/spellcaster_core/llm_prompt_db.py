"""Per-model LLM prompt-enhancement settings database.

THE shared store of "what LLM parameters work best for enhancing
prompts destined for THIS specific checkpoint". Every surface — the
Guild, the GIMP plugin, the Darktable plugin, the ComfyUI-Spellcaster
node pack — reads and writes through this one module. Do not duplicate.

WHY per-model (not just per-arch)
──────────────────────────────────
Two checkpoints of the same architecture don't always respond the same
way. `juggernautXL_ragnarok` likes more-aggressive booru tags than
`sd_xl_base_1.0`. A cinematic-trained klein finetune wants camera
vocabulary that vanilla klein-9b ignores. The arch profile
(`_ARCH_ENHANCE_PROFILES` in prompt_enhance) is the baseline; this
database holds per-model overrides learned from actual generations.

Storage
───────
Single JSON file at `~/.spellcaster/llm_prompt_settings.json`, shared
across every surface on this machine. Located in the user's home so
the GIMP plugin and the Guild server both see the same state without
having to agree on a working directory.

Record shape
────────────
    {
      "version": 1,
      "models": {
        "<model_path_as_stored_in_ComfyUI>": {
          "arch":           "flux2klein",
          "llm_settings":   {"temperature": 0.3, "max_tokens": 300,
                             "top_p": 0.9, "repetition_penalty": 1.1},
          "profile_override": null | {...},   // optional per-arch profile tweak
          "hints": [                           // free-form per-model hints
            "prefers 40-60 word prompts",
            "responds poorly to negative conjunctions"
          ],
          "validated": {
            "at":       "2026-04-19T22:05:00Z",
            "llm":      "gemma3:4b",
            "scenes":   {"1p": "pass", "2p": "pass", "3p": "pass"},
            "by":       "user" | "auto"
          },
          "updated_at": "2026-04-19T22:05:00Z"
        }
      }
    }

The DB is loaded lazily on first access and written atomically (via
temp-file + rename) on every save. Concurrent writes from multiple
processes are last-write-wins; that's fine for this data (small, low
churn, hand-curated).

API
───
    from spellcaster_core.llm_prompt_db import (
        get_model_settings, set_model_settings, all_models, forget_model,
        merge_with_profile,
    )

    # Read: returns the per-model record or None.
    rec = get_model_settings("A-Flux/Flux2/flux-2-klein-9b.safetensors")

    # Write: merges into existing record (or creates one).
    set_model_settings(
        "A-Flux/Flux2/flux-2-klein-9b.safetensors",
        arch="flux2klein",
        llm_settings={"temperature": 0.25, "max_tokens": 280},
        hints=["tight prompts outperform verbose ones"],
        validated={"llm": "gemma3:4b", "scenes": {"1p": "pass"}},
    )

    # Merge per-model overrides onto the arch baseline (what enhance_prompt uses):
    eff = merge_with_profile(model_name, arch_profile)
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time

# Public so external tools can locate the file (e.g. for sync).
# User home is the single source across Guild / GIMP / Darktable / etc.
DB_DIR = os.path.join(os.path.expanduser("~"), ".spellcaster")
DB_PATH = os.path.join(DB_DIR, "llm_prompt_settings.json")

_SCHEMA_VERSION = 1
_lock = threading.Lock()
_cache = {"mtime": 0.0, "data": None}


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _default_db() -> dict:
    return {"version": _SCHEMA_VERSION, "models": {}}


def _load() -> dict:
    """Return the DB dict. Creates an empty one on first call or if the
    file is missing / corrupt. Cached until the file's mtime changes.
    """
    try:
        st = os.stat(DB_PATH)
        mtime = st.st_mtime
    except OSError:
        mtime = 0.0
    # Serve from cache if file hasn't changed since last read.
    if _cache["data"] is not None and mtime == _cache["mtime"]:
        return _cache["data"]
    if mtime == 0.0:
        data = _default_db()
    else:
        try:
            with open(DB_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            # If someone saved a different shape, repair in place.
            if not isinstance(data, dict) or data.get("version") != _SCHEMA_VERSION:
                data = _default_db()
            if not isinstance(data.get("models"), dict):
                data["models"] = {}
        except (OSError, json.JSONDecodeError):
            data = _default_db()
    _cache["data"] = data
    _cache["mtime"] = mtime
    return data


def _save(data: dict) -> None:
    """Atomically write the DB. Creates DB_DIR if needed."""
    os.makedirs(DB_DIR, exist_ok=True)
    # Write to a temp file in the same dir, then rename — atomic on POSIX
    # and best-effort on Windows (os.replace handles cross-fs rename).
    fd, tmp = tempfile.mkstemp(prefix=".llm_prompt_settings.", suffix=".json",
                                dir=DB_DIR, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, DB_PATH)
    except Exception:
        try: os.unlink(tmp)
        except OSError: pass
        raise
    # Invalidate cache so the next _load picks up our own write.
    try:
        _cache["mtime"] = os.stat(DB_PATH).st_mtime
        _cache["data"] = data
    except OSError:
        pass


# ── Public API ─────────────────────────────────────────────────────────

def get_model_settings(model_name: str) -> dict | None:
    """Return the per-model record (dict) or None if nothing is stored."""
    if not model_name:
        return None
    with _lock:
        data = _load()
    return data["models"].get(str(model_name))


def set_model_settings(model_name: str, *,
                       arch: str | None = None,
                       llm_settings: dict | None = None,
                       profile_override: dict | None = None,
                       hints: list | None = None,
                       validated: dict | None = None) -> dict:
    """Create or merge-update the record for one model. Returns the
    post-merge record.

    Only the fields you pass get updated; the rest are preserved.
    `validated` gets its timestamp auto-stamped if you don't provide one.
    """
    if not model_name:
        raise ValueError("model_name required")
    key = str(model_name)
    with _lock:
        data = _load()
        rec = dict(data["models"].get(key, {}))
        if arch is not None:
            rec["arch"] = arch
        if llm_settings is not None:
            merged = dict(rec.get("llm_settings") or {})
            merged.update(llm_settings)
            rec["llm_settings"] = merged
        if profile_override is not None:
            rec["profile_override"] = profile_override
        if hints is not None:
            # Preserve uniqueness but keep order stable.
            seen = set()
            combined = list(rec.get("hints") or []) + list(hints)
            rec["hints"] = [h for h in combined
                            if not (h in seen or seen.add(h))]
        if validated is not None:
            vrec = dict(validated)
            vrec.setdefault("at", _now_iso())
            rec["validated"] = vrec
        rec["updated_at"] = _now_iso()
        data["models"][key] = rec
        _save(data)
    return rec


def forget_model(model_name: str) -> bool:
    """Remove a model's record. Returns True if something was deleted."""
    if not model_name:
        return False
    key = str(model_name)
    with _lock:
        data = _load()
        if key in data["models"]:
            del data["models"][key]
            _save(data)
            return True
    return False


def all_models() -> dict:
    """Return a shallow copy of the {model_name: record} map."""
    with _lock:
        data = _load()
    return dict(data["models"])


def merge_with_profile(model_name: str, profile: dict) -> dict:
    """Merge a stored per-model override onto the base arch profile
    (one of `_ARCH_ENHANCE_PROFILES` from prompt_enhance). Missing keys
    fall through to the profile. The caller passes the profile directly
    — this module doesn't import prompt_enhance to avoid a cycle.

    Used by enhance_prompt(): it picks the arch profile, then asks us
    to overlay any model-specific tweaks before building the system
    message.
    """
    base = dict(profile or {})
    rec = get_model_settings(model_name)
    if not rec:
        return base
    override = rec.get("profile_override")
    if isinstance(override, dict):
        base.update(override)
    # Also hoist model-specific hints into `notes` so the LLM sees them.
    hints = rec.get("hints") or []
    if hints and isinstance(base.get("notes"), str):
        suffix = "\n\nPER-MODEL HINTS (learned from prior runs):\n- " + \
                 "\n- ".join(str(h) for h in hints)
        base["notes"] = base["notes"] + suffix
    return base


def get_effective_params(model_name: str,
                          defaults: dict | None = None) -> dict:
    """Return the LLM sampling params to use for a model. Caller passes
    the defaults (temperature, max_tokens, etc.); per-model overrides
    win where they exist.
    """
    out = dict(defaults or {})
    rec = get_model_settings(model_name)
    if rec:
        for k, v in (rec.get("llm_settings") or {}).items():
            out[k] = v
    return out


__all__ = [
    "DB_DIR", "DB_PATH",
    "get_model_settings", "set_model_settings", "forget_model",
    "all_models", "merge_with_profile", "get_effective_params",
]
