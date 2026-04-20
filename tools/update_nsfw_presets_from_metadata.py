"""Bulk-update NSFW personal presets to the Civitai-recommended LoRA settings.

When the Wizard Guild's LoRA manager has finished downloading metadata
(Civitai ``trainedWords``, recommended weights, etc.) the ``_LORA_REGISTRY``
carries per-LoRA ``civitai_recommended_weight`` values for every LoRA the
user has. This tool walks every preset JSON under ``nsfw/`` and rewrites
``[name, model_strength, clip_strength]`` tuples (and Klein-style
``{path, strength}`` entries) so the strengths match the Civitai
recommendation \u2014 but only when the current strength looks like a
sentinel default (1.0 or 0.7).

The tool is opt-in (``--apply``), NSFW-only by construction (it refuses
to touch files outside ``nsfw/`` and the staging tree), and writes a
``<file>.pre-metadata-<ts>.bak`` sidecar next to every modified file so
recovery is one ``mv`` away.

Usage:

    python tools/update_nsfw_presets_from_metadata.py            # dry run
    python tools/update_nsfw_presets_from_metadata.py --apply    # rewrite

Add ``--verbose`` for a per-preset diff, ``--threshold 0.05`` to require
a larger delta before rewriting (useful when the Civitai average is
very close to the sentinel default and the churn wouldn't be worth it).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
NSFW_DIR = ROOT / "nsfw"
GUILD_STATE = ROOT / "tavern" / ".guild_state" / "lora_registry.json"

# Strengths we consider "unset defaults" that are fair game to replace.
# 1.0 is the usual "just use full strength" fallback; 0.7 is the
# registry's initial value for user-unset loras; 0.8 is the shipped
# scene-preset default for most arches.
SENTINEL_STRENGTHS = {0.7, 0.75, 0.8, 1.0}

# File-name allowlist \u2014 anything NOT on this list under nsfw/ is
# skipped defensively so we don't stomp unrelated JSON (scratch work,
# debug dumps). Add new preset files here explicitly.
NSFW_PRESET_FILES = [
    "lora_presets.json",
    "nsfw_klein_presets.json",
    "nsfw_presets_extras.json",
    "nsfw_presets_inpaint.json",
    "nsfw_presets_video.json",
    "nsfw_loras.json",
]


def load_registry() -> dict:
    """Load the running Guild's LoRA registry (with Civitai metadata)."""
    if not GUILD_STATE.exists():
        print(f"ERROR: {GUILD_STATE} not found. Start the Wizard Guild "
              f"and run a full 'Refresh LoRAs' first.", file=sys.stderr)
        sys.exit(2)
    with open(GUILD_STATE, "r", encoding="utf-8") as f:
        data = json.load(f)
    registry = data.get("registry") or {}
    if not registry:
        print("ERROR: registry is empty.", file=sys.stderr)
        sys.exit(2)
    have_civ = sum(1 for v in registry.values()
                   if v.get("civitai_recommended_weight") is not None)
    print(f"Loaded {len(registry)} registry entries "
          f"({have_civ} with Civitai-recommended weight).")
    return registry


def _civitai_weight(registry: dict, name: str) -> float | None:
    """Return the Civitai-recommended weight for a LoRA, or None.

    Tries an exact-name match first, then a basename match so presets
    written with Windows-style ``\\\\`` paths resolve even when the
    registry keys are forward-slash. Weights outside the safe band
    (0.1-1.5) are ignored \u2014 bad data shouldn't wreck presets.
    """
    if not name:
        return None
    entry = registry.get(name)
    if not entry:
        # Fall back to basename match.
        base = name.replace("\\", "/").rsplit("/", 1)[-1]
        for k, v in registry.items():
            if k.replace("\\", "/").rsplit("/", 1)[-1] == base:
                entry = v
                break
    if not entry:
        return None
    w = entry.get("civitai_recommended_weight")
    if not isinstance(w, (int, float)):
        return None
    w = float(w)
    if 0.1 <= w <= 1.5:
        return round(w, 2)
    return None


def _is_sentinel(x) -> bool:
    try:
        return round(float(x), 2) in SENTINEL_STRENGTHS
    except (TypeError, ValueError):
        return False


def _walk_and_update(obj, registry: dict, *, threshold: float,
                     path: str, changes: list[dict]) -> None:
    """Recursively walk a JSON tree, updating LoRA strength references.

    Recognised shapes:

      - ``[name_str, model_strength, clip_strength]`` \u2014 lora_presets.json
      - ``{"path": name_str, "strength": float}`` \u2014 klein inpaint presets
      - ``"loras": [...]`` list of any of the above
    """
    if isinstance(obj, dict):
        # Klein-style ``{"path", "strength"}``.
        if "path" in obj and "strength" in obj and isinstance(obj.get("path"), str):
            rec = _civitai_weight(registry, obj["path"])
            cur = obj.get("strength")
            if (rec is not None and _is_sentinel(cur)
                    and abs(float(cur) - rec) >= threshold):
                changes.append({
                    "file": path, "lora": obj["path"],
                    "old_strength": float(cur), "new_strength": rec,
                    "shape": "klein_lora",
                })
                obj["strength"] = rec
        for k, v in obj.items():
            _walk_and_update(v, registry, threshold=threshold,
                             path=f"{path}.{k}", changes=changes)
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            # ``[name, model_str, clip_str]`` tuple.
            if (isinstance(item, list) and len(item) == 3
                    and isinstance(item[0], str)):
                rec = _civitai_weight(registry, item[0])
                if rec is not None and _is_sentinel(item[1]):
                    if abs(float(item[1]) - rec) >= threshold:
                        changes.append({
                            "file": path, "lora": item[0],
                            "old_strength": float(item[1]),
                            "new_strength": rec,
                            "shape": "lora_tuple[model]",
                        })
                        item[1] = rec
                if rec is not None and _is_sentinel(item[2]):
                    if abs(float(item[2]) - rec) >= threshold:
                        changes.append({
                            "file": path, "lora": item[0],
                            "old_strength": float(item[2]),
                            "new_strength": rec,
                            "shape": "lora_tuple[clip]",
                        })
                        item[2] = rec
            else:
                _walk_and_update(item, registry, threshold=threshold,
                                 path=f"{path}[{i}]", changes=changes)


def process_file(p: Path, registry: dict, *, apply: bool,
                 threshold: float, verbose: bool) -> list[dict]:
    with open(p, "r", encoding="utf-8") as f:
        data = json.load(f)
    changes: list[dict] = []
    _walk_and_update(data, registry, threshold=threshold,
                     path=p.name, changes=changes)
    if not changes:
        print(f"  {p.name}: no changes")
        return []
    print(f"  {p.name}: {len(changes)} LoRA strength(s) to update")
    if verbose:
        for c in changes:
            print(f"    {c['lora']}: {c['old_strength']} \u2192 "
                  f"{c['new_strength']}  ({c['shape']})")
    if apply:
        ts = time.strftime("%Y%m%d-%H%M%S")
        backup = p.with_name(p.name + f".pre-metadata-{ts}.bak")
        backup.write_bytes(p.read_bytes())
        tmp = p.with_suffix(p.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, p)
        print(f"    wrote {p.name} (backup: {backup.name})")
    return changes


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true",
                    help="Write changes (default: dry run)")
    ap.add_argument("--verbose", action="store_true",
                    help="Print per-LoRA diffs")
    ap.add_argument("--threshold", type=float, default=0.0,
                    help="Minimum strength delta to rewrite (default 0.0)")
    ap.add_argument("--files", nargs="*", default=None,
                    help="Override the NSFW_PRESET_FILES allowlist")
    args = ap.parse_args()

    if not NSFW_DIR.exists():
        print(f"ERROR: {NSFW_DIR} does not exist. This tool is NSFW-only.",
              file=sys.stderr)
        return 3

    registry = load_registry()

    targets = args.files or NSFW_PRESET_FILES
    total_changes = 0
    print(f"\nProcessing {len(targets)} preset file(s) under {NSFW_DIR} ...")
    for name in targets:
        p = NSFW_DIR / name
        if not p.exists():
            print(f"  {name}: not present, skipping")
            continue
        # Refuse to walk anything outside nsfw/ even if passed explicitly.
        try:
            p.resolve().relative_to(NSFW_DIR.resolve())
        except ValueError:
            print(f"  {name}: REFUSED \u2014 path escapes nsfw/")
            continue
        try:
            changes = process_file(p, registry, apply=args.apply,
                                    threshold=args.threshold,
                                    verbose=args.verbose)
            total_changes += len(changes)
        except Exception as e:
            print(f"  {name}: ERROR {e}")

    print(f"\n{total_changes} strength rewrite(s) "
          f"{'APPLIED' if args.apply else 'planned (dry-run)'} across "
          f"{len(targets)} file(s).")
    if not args.apply and total_changes:
        print("Re-run with --apply to write the changes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
