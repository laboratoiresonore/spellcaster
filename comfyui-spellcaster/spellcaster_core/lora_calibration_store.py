"""Read/write helpers for the shipped LoRA calibration stores.

The app persists confirmed calibrations to one of two JSON files:

    comfyui-spellcaster/spellcaster_core/lora_calibrations_sfw.json
    comfyui-spellcaster/spellcaster_core/lora_calibrations_nsfw.json

The SFW file travels with the public spellcaster repo and is safe to
commit. The NSFW file is gitignored in the public repo; `build_nsfw.py`
copies `nsfw/lora_calibrations_nsfw.json` into the NSFW staging tree
so the private NSFW build ships it with the package.

A LoRA lands in the NSFW store iff `lora_knowledge.classify_nsfw()`
returns True — the routing decision lives there, not here. This module
just reads and writes JSON files with consistent schema and atomic
replace semantics.
"""
from __future__ import annotations

import json
import os
import threading
import time
from typing import Optional


SCHEMA_VERSION = 1

_WRITE_LOCK = threading.Lock()


def _pkg_dir() -> str:
    return os.path.dirname(os.path.abspath(__file__))


def sfw_path() -> str:
    return os.path.join(_pkg_dir(), "lora_calibrations_sfw.json")


def nsfw_path() -> str:
    return os.path.join(_pkg_dir(), "lora_calibrations_nsfw.json")


def _read_json(path: str) -> dict:
    try:
        if not os.path.exists(path):
            return {}
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def _init_doc() -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "notes": "Auto-maintained by lora_calibration_store.write_calibration.",
        "loras": {},
    }


def _atomic_write(path: str, doc: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")
    os.replace(tmp, path)


def load_sfw() -> dict:
    """{lora_name: calibration_entry}."""
    return _read_json(sfw_path()).get("loras") or {}


def load_nsfw() -> dict:
    """{lora_name: calibration_entry}. Empty dict if the NSFW file
    isn't shipped with this install (i.e. this is a SFW build)."""
    return _read_json(nsfw_path()).get("loras") or {}


def load_merged() -> dict:
    """SFW ∪ NSFW — NSFW wins on collision. Callers that don't care
    about provenance use this to look up any recipe by name."""
    merged = dict(load_sfw())
    merged.update(load_nsfw())
    return merged


def get_calibration(name: str) -> Optional[dict]:
    """Find `name` in either store. Returns None if absent."""
    if not name:
        return None
    sfw = load_sfw()
    if name in sfw:
        return sfw[name]
    nsfw = load_nsfw()
    if name in nsfw:
        return nsfw[name]
    return None


def _build_entry(
    *,
    recommended_weight: Optional[float],
    recommended_sampler: Optional[str],
    recommended_cfg: Optional[float],
    subject_key: Optional[str],
    trigger_words: Optional[list[str]],
    base_model: Optional[str],
    sha256: Optional[str],
    source: str,
    extra: Optional[dict] = None,
) -> dict:
    entry = {
        "updated_at": int(time.time()),
        "source": source,
    }
    if recommended_weight is not None:
        entry["recommended_weight"] = float(recommended_weight)
    if recommended_sampler:
        entry["recommended_sampler"] = str(recommended_sampler)
    if recommended_cfg is not None:
        entry["recommended_cfg"] = float(recommended_cfg)
    if subject_key:
        entry["subject_key"] = str(subject_key)
    if trigger_words:
        entry["trigger_words"] = [str(t) for t in trigger_words if t][:10]
    if base_model:
        entry["base_model"] = str(base_model)
    if sha256:
        entry["sha256"] = str(sha256).lower()
    if isinstance(extra, dict):
        # Caller extras (example_prompts, civitai_url, user notes, etc.)
        for k, v in extra.items():
            if k not in entry and v not in (None, "", [], {}):
                entry[k] = v
    return entry


def write_calibration(
    name: str,
    *,
    nsfw: bool,
    recommended_weight: Optional[float] = None,
    recommended_sampler: Optional[str] = None,
    recommended_cfg: Optional[float] = None,
    subject_key: Optional[str] = None,
    trigger_words: Optional[list[str]] = None,
    base_model: Optional[str] = None,
    sha256: Optional[str] = None,
    source: str = "auto",
    extra: Optional[dict] = None,
    confirmed_by_user: bool = False,
) -> str:
    """Persist a calibration entry to the SFW or NSFW store.

    Returns the path that was written. Atomic: stages to `.tmp` and
    replaces in one `os.replace` call. If the NSFW file doesn't exist
    (SFW-only build), NSFW writes degrade to creating it — the file
    simply isn't tracked by the public repo's .gitignore.

    `confirmed_by_user=True` means a human explicitly said "this
    calibration looks right"; otherwise the entry is a provisional
    auto-pick that future runs may refresh.
    """
    if not name:
        raise ValueError("name is required")
    target = nsfw_path() if nsfw else sfw_path()
    with _WRITE_LOCK:
        doc = _read_json(target) or _init_doc()
        doc.setdefault("schema_version", SCHEMA_VERSION)
        doc.setdefault("loras", {})
        entry = _build_entry(
            recommended_weight=recommended_weight,
            recommended_sampler=recommended_sampler,
            recommended_cfg=recommended_cfg,
            subject_key=subject_key,
            trigger_words=trigger_words,
            base_model=base_model,
            sha256=sha256,
            source=source,
            extra=extra,
        )
        if confirmed_by_user:
            entry["confirmed_by_user"] = True
            entry["confirmed_at"] = int(time.time())
        doc["loras"][name] = entry
        _atomic_write(target, doc)
    return target


def remove_calibration(name: str, *, from_sfw: bool = True, from_nsfw: bool = True) -> int:
    """Delete `name` from both stores (by default). Returns the number
    of files modified."""
    changed = 0
    with _WRITE_LOCK:
        for path, do_it in ((sfw_path(), from_sfw), (nsfw_path(), from_nsfw)):
            if not do_it:
                continue
            doc = _read_json(path)
            if doc and name in (doc.get("loras") or {}):
                del doc["loras"][name]
                _atomic_write(path, doc)
                changed += 1
    return changed


def stats() -> dict:
    sfw = load_sfw()
    nsfw = load_nsfw()
    return {
        "sfw_count": len(sfw),
        "nsfw_count": len(nsfw),
        "confirmed_count": sum(
            1 for e in list(sfw.values()) + list(nsfw.values())
            if isinstance(e, dict) and e.get("confirmed_by_user")
        ),
        "sfw_path": sfw_path(),
        "nsfw_path": nsfw_path(),
    }


__all__ = [
    "SCHEMA_VERSION",
    "sfw_path",
    "nsfw_path",
    "load_sfw",
    "load_nsfw",
    "load_merged",
    "get_calibration",
    "write_calibration",
    "remove_calibration",
    "stats",
]
