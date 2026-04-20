"""Remap NSFW personal config to match the current ComfyUI LoRA library.

The user ships dozens of LoRAs referenced by exact filename in NSFW
presets. When they upgrade a pack (v1 -> v2), add a new WAN Lightning
LoRA, or swap one file out for another, those references go stale
silently \u2014 the workflow builds but picks the wrong (or missing) file.

This tool probes the ComfyUI server and reports / fixes three classes
of drift:

  1. **Orphan LoRA references** \u2014 any filename mentioned in an
     ``nsfw/*.json`` preset that is no longer on the server. For each
     orphan, the tool scores every present LoRA using the same
     stem-match heuristic as the Guild's ``_find_replacement_lora``
     (version / epoch / rank / quant / hash suffixes stripped) and
     proposes the best candidate.
  2. **Stale WAN accel LoRAs in ``nsfw/build_nsfw.py``** \u2014 the
     NSFW build patches ``video_presets.py`` with specific
     ``high_accel_lora`` / ``low_accel_lora`` filenames. When the user
     upgrades to a new Lightning / CausVid pair we re-detect the
     current best pair with ``pick_wan_accel_loras`` and propose an
     in-place patch.
  3. **Orphan WAN accel references in presets** \u2014 same as (1) but
     specifically for the I2V HIGH/LOW pair so the recommendation can
     reuse the newly-detected file.

NSFW-ONLY: the tool refuses to touch anything outside ``nsfw/``. Every
rewrite is atomic (``*.tmp`` + ``os.replace``) with a
``.pre-remap-<ts>.bak`` sidecar next to any modified file.

Usage::

    python tools/remap_nsfw_config.py --comfyui-url http://192.168.x.x:8188
    python tools/remap_nsfw_config.py --comfyui-url ... --apply
    python tools/remap_nsfw_config.py --comfyui-url ... --apply --verbose
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import time
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
NSFW_DIR = ROOT / "nsfw"

# Re-use the version-suffix peeler from the migration module. We don't
# import it because the tool may run against a tree where the Guild
# isn't running \u2014 inlining the same regex set keeps this tool
# usable even from a detached state.
_LORA_VERSION_SUFFIXES = [
    re.compile(r'[._-]?v\d+(?:\.\d+)*[a-z]?$', re.IGNORECASE),
    re.compile(r'[._-]?version\d+$', re.IGNORECASE),
    re.compile(r'[._-]?epoch[-_]?\d+$', re.IGNORECASE),
    re.compile(r'[._-]?e\d{2,}$', re.IGNORECASE),
    re.compile(r'[._-]?step\d+$', re.IGNORECASE),
    re.compile(r'[._-]?rank[-_]?\d+$', re.IGNORECASE),
    re.compile(r'[._-]?r\d{2,}$', re.IGNORECASE),
    re.compile(r'[._-]?fp\d+(?:_scaled)?$', re.IGNORECASE),
    re.compile(r'[._-]?bf\d+$', re.IGNORECASE),
    re.compile(r'[._-]?q\d+(?:_\d*)?(?:_[kKmMsS])?$', re.IGNORECASE),
    re.compile(r'[._-]?000\d{3}$'),
    re.compile(r'[._-]?[a-f0-9]{8,40}$', re.IGNORECASE),
    re.compile(r'[._-]?\d{4,6}$'),
    re.compile(r'[._-]?final$', re.IGNORECASE),
    re.compile(r'[._-]?new$', re.IGNORECASE),
]


def lora_stem(name: str) -> str:
    """Strip directory, extension, and version suffixes to a stable
    stem. ``MyLora_V2_rank128.safetensors`` \u2192 ``mylora``."""
    s = str(name or "").replace("\\", "/").rsplit("/", 1)[-1]
    if "." in s:
        s = s.rsplit(".", 1)[0]
    s = s.strip()
    changed = True
    while changed:
        changed = False
        for pat in _LORA_VERSION_SUFFIXES:
            new = pat.sub("", s).strip("._- ")
            if new and new != s:
                s = new
                changed = True
    return s.lower()


def fetch_server_loras(comfyui_url: str) -> list[str]:
    """Pull the full LoRA list from ComfyUI via ``/object_info``.

    The LoraLoader node's input metadata exposes every installed LoRA
    filename. Raises on network / API failure so the caller shows a
    clear "server unreachable" message instead of silently rebasing
    against an empty list (which would mark every LoRA as orphan).
    """
    url = comfyui_url.rstrip("/") + "/object_info/LoraLoader"
    with urllib.request.urlopen(url, timeout=15) as r:
        data = json.loads(r.read().decode("utf-8"))
    inputs = (
        data.get("LoraLoader", {})
            .get("input", {})
            .get("required", {})
    )
    lora_values = inputs.get("lora_name", [[]])
    if (isinstance(lora_values, list) and lora_values
            and isinstance(lora_values[0], list)):
        return list(lora_values[0])
    return []


def score_candidate(old_name: str, new_name: str) -> tuple[float, list[str]]:
    """Score how likely ``new_name`` is a replacement for ``old_name``.
    Mirrors ``_score_migration_candidate`` in ``tavern/server.py`` so
    the tool's proposals line up with what the Guild would auto-apply
    on next refresh. Returns ``(score_0_to_1, reasons_list)``."""
    reasons: list[str] = []
    score = 0.0
    os_stem = lora_stem(old_name)
    ns_stem = lora_stem(new_name)
    if os_stem and ns_stem and os_stem == ns_stem:
        score += 0.7
        reasons.append(f"stem='{os_stem}'")
    elif os_stem and ns_stem and (os_stem in ns_stem or ns_stem in os_stem):
        overlap = min(len(os_stem), len(ns_stem)) / max(len(os_stem), len(ns_stem))
        if overlap >= 0.6:
            score += 0.4 * overlap
            reasons.append(f"partial stem overlap ({int(overlap * 100)}%)")
    od = old_name.replace("\\", "/").rsplit("/", 1)[0] if "/" in old_name.replace("\\", "/") else ""
    nd = new_name.replace("\\", "/").rsplit("/", 1)[0] if "/" in new_name.replace("\\", "/") else ""
    if od and nd and od.lower() == nd.lower():
        score += 0.15
        reasons.append("same folder")
    return min(score, 1.0), reasons


def find_best_replacement(old_name: str, candidates: list[str]) -> tuple[str, float, list[str]] | None:
    """Pick the highest-scoring candidate above 0.5 confidence, or None."""
    best = None
    best_score = 0.0
    best_reasons: list[str] = []
    for c in candidates:
        if c == old_name:
            continue
        s, r = score_candidate(old_name, c)
        if s > best_score and s >= 0.5:
            best_score = s
            best = c
            best_reasons = r
    if best is None:
        return None
    return best, round(best_score, 2), best_reasons


def collect_preset_lora_refs(files: list[Path]) -> set[str]:
    """Walk every referenced LoRA filename across the NSFW preset JSONs.

    Handles both shapes the presets use:
      - ``[name_str, model_strength, clip_strength]`` tuples
      - ``{"path": name_str, "strength": float}`` (Klein inpaint)
      - Any leaf ``"lora": "name_str"`` or ``"lora_name": "name_str"``
    """
    refs: set[str] = set()

    def walk(obj):
        if isinstance(obj, dict):
            if isinstance(obj.get("path"), str) and "strength" in obj:
                refs.add(obj["path"])
            for k, v in obj.items():
                if isinstance(v, str) and k in ("lora", "lora_name", "path"):
                    if v.lower().endswith((".safetensors", ".pt", ".gguf")):
                        refs.add(v)
                else:
                    walk(v)
        elif isinstance(obj, list):
            for item in obj:
                if (isinstance(item, list) and len(item) == 3
                        and isinstance(item[0], str)):
                    refs.add(item[0])
                else:
                    walk(item)

    for p in files:
        try:
            with open(p, "r", encoding="utf-8") as f:
                walk(json.load(f))
        except Exception as e:
            print(f"  [skip] {p.name}: {e}")
    return refs


def rewrite_preset_refs(path: Path, mapping: dict[str, str], *,
                        apply: bool) -> int:
    """Rewrite LoRA filename references in a preset JSON using the
    supplied ``{old: new}`` mapping. Atomic write + backup on apply.
    Returns the number of replacements.
    """
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    count = 0

    def walk(obj):
        nonlocal count
        if isinstance(obj, dict):
            for k, v in list(obj.items()):
                if isinstance(v, str) and v in mapping and k in ("lora", "lora_name", "path"):
                    obj[k] = mapping[v]
                    count += 1
                else:
                    walk(v)
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                if (isinstance(item, list) and len(item) >= 1
                        and isinstance(item[0], str) and item[0] in mapping):
                    item[0] = mapping[item[0]]
                    count += 1
                else:
                    walk(item)

    walk(data)
    if count and apply:
        ts = time.strftime("%Y%m%d-%H%M%S")
        backup = path.with_name(path.name + f".pre-remap-{ts}.bak")
        shutil.copy2(path, backup)
        tmp = path.with_suffix(path.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, path)
    return count


def pick_wan_accel_pair(lora_list: list[str]) -> tuple[str | None, str | None]:
    """Mirror of ``video_presets.pick_wan_accel_loras`` \u2014 returns
    the current best WAN I2V HIGH + LOW accel pair on the server.

    Kept inline so this tool runs standalone even when ``spellcaster_core``
    isn't importable (different working dir, no PYTHONPATH).
    """
    high = low = None
    for l in lora_list:
        ll = l.lower()
        if "wan" not in ll:
            continue
        is_accel = (
            ("lightx2v" in ll and "i2v" in ll)
            or ("lightning" in ll and "i2v" in ll)
            or ("causvid" in ll and "i2v" in ll)
            or ("causvid" in ll)
            or ("accel" in ll)
        )
        if not is_accel or "t2v" in ll:
            continue
        if "high" in ll and not high:
            high = l
        elif "low" in ll and not low:
            low = l
    return high, low


def patch_build_nsfw_accel(high: str, low: str, *, apply: bool) -> list[dict]:
    """Update the hardcoded ``high_accel_lora`` / ``low_accel_lora``
    filenames inside ``nsfw/build_nsfw.py`` if they differ from the
    currently-detected pair on the server. Returns a list of
    ``{line, old, new}`` change records so the caller can render a
    dry-run diff.
    """
    p = NSFW_DIR / "build_nsfw.py"
    if not p.exists():
        return []
    with open(p, "r", encoding="utf-8") as f:
        src = f.read()
    # Escape for Python source (the build script embeds the path as a
    # raw Python literal, with Windows-style ``\\\\`` to survive one
    # round of backslash-escaping).
    high_py = high.replace("\\", "\\\\")
    low_py = low.replace("\\", "\\\\")

    pat_high = re.compile(r'("high_accel_lora":\s*")([^"]+)(")')
    pat_low = re.compile(r'("low_accel_lora":\s*")([^"]+)(")')
    lua_high = re.compile(r'(high_accel_lora\s*=\s*")([^"]+)(")')
    lua_low = re.compile(r'(low_accel_lora\s*=\s*")([^"]+)(")')

    changes: list[dict] = []
    new_src = src
    for name, pat, repl in (
        ("high/py", pat_high, high_py),
        ("low/py",  pat_low,  low_py),
        ("high/lua", lua_high, high_py),
        ("low/lua",  lua_low,  low_py),
    ):
        for m in list(pat.finditer(new_src)):
            existing = m.group(2)
            if existing == repl:
                continue
            line_no = new_src[:m.start()].count("\n") + 1
            changes.append({
                "kind": name, "line": line_no,
                "old": existing, "new": repl,
            })
        new_src = pat.sub(lambda m, r=repl: m.group(1) + r + m.group(3), new_src)

    if changes and apply:
        ts = time.strftime("%Y%m%d-%H%M%S")
        backup = p.with_name(p.name + f".pre-remap-{ts}.bak")
        shutil.copy2(p, backup)
        tmp = p.with_suffix(p.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(new_src)
        os.replace(tmp, p)
    return changes


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--comfyui-url", required=True,
                    help="http://host:8188 of your ComfyUI server")
    ap.add_argument("--apply", action="store_true",
                    help="Write changes (default: dry run)")
    ap.add_argument("--verbose", action="store_true",
                    help="Show per-reference detail")
    ap.add_argument("--files", nargs="*", default=None,
                    help="Override the NSFW preset file allowlist")
    args = ap.parse_args()

    if not NSFW_DIR.exists():
        print(f"ERROR: {NSFW_DIR} missing \u2014 this tool is NSFW-only.",
              file=sys.stderr)
        return 3

    # 1. Pull current server LoRA set.
    try:
        server_loras = fetch_server_loras(args.comfyui_url)
    except Exception as e:
        print(f"ERROR: could not reach ComfyUI at {args.comfyui_url}: {e}",
              file=sys.stderr)
        return 2
    print(f"Server has {len(server_loras)} LoRA(s).")
    server_set = set(server_loras)

    # 2. Collect every LoRA reference across NSFW presets.
    default_files = [
        "lora_presets.json", "nsfw_klein_presets.json",
        "nsfw_presets_extras.json", "nsfw_presets_inpaint.json",
        "nsfw_presets_video.json", "nsfw_loras.json",
    ]
    names = args.files or default_files
    file_paths: list[Path] = []
    for n in names:
        p = NSFW_DIR / n
        if p.exists():
            file_paths.append(p)
        else:
            print(f"  [skip] {n} not present")
    refs = collect_preset_lora_refs(file_paths)
    print(f"Found {len(refs)} unique LoRA reference(s) across "
          f"{len(file_paths)} file(s).")

    # 3. Orphan classification + replacement proposal.
    orphans = sorted(r for r in refs if r and r not in server_set)
    print(f"\n{len(orphans)} orphan reference(s) (on disk in a preset, "
          f"not on the ComfyUI server):")

    auto_mapping: dict[str, str] = {}
    manual_list: list[tuple[str, str, float, list[str]]] = []
    unresolved: list[str] = []

    for orphan in orphans:
        best = find_best_replacement(orphan, server_loras)
        if not best:
            unresolved.append(orphan)
            continue
        new, conf, reasons = best
        if conf >= 0.9:
            auto_mapping[orphan] = new
        else:
            manual_list.append((orphan, new, conf, reasons))

    if args.verbose or not args.apply:
        for orphan, new in auto_mapping.items():
            print(f"  [auto]   {orphan}\n           \u2192 {new}")
        for orphan, new, conf, reasons in manual_list:
            print(f"  [manual] {orphan}\n           \u2192 {new} "
                  f"({int(conf * 100)}%: {', '.join(reasons)})")
        for orphan in unresolved:
            print(f"  [ERROR]  {orphan}  \u2014 no replacement found on server")

    # 4. Rewrite orphan refs (auto-only; manual list requires
    #    explicit confirmation the user gives by running with --apply
    #    after reviewing the dry run).
    if auto_mapping:
        total = 0
        for p in file_paths:
            n = rewrite_preset_refs(p, auto_mapping, apply=args.apply)
            if n:
                print(f"  {p.name}: {n} ref(s) "
                      f"{'REWRITTEN' if args.apply else 'would rewrite'}")
                total += n
        print(f"  Total auto-remap replacements: {total}")

    # 5. WAN accel LoRA detection + build_nsfw.py patch.
    high, low = pick_wan_accel_pair(server_loras)
    print(f"\nDetected WAN accel pair on server:")
    print(f"  HIGH: {high or '(none)'}")
    print(f"  LOW:  {low or '(none)'}")
    if high and low:
        changes = patch_build_nsfw_accel(high, low, apply=args.apply)
        if not changes:
            print("  build_nsfw.py already up to date.")
        else:
            for c in changes:
                print(f"  {c['kind']} line {c['line']}: "
                      f"{c['old']} \u2192 {c['new']}")
            print(f"  build_nsfw.py: {len(changes)} change(s) "
                  f"{'APPLIED' if args.apply else 'would apply'}")
    else:
        print("  Could not detect complete WAN accel pair "
              "\u2014 leave build_nsfw.py untouched.")

    # 6. Summary.
    print("\n" + "=" * 60)
    print(f"Summary:")
    print(f"  auto-remap orphans:      {len(auto_mapping)}")
    print(f"  manual-review orphans:   {len(manual_list)}   "
          f"(re-run with --apply after reviewing proposals)")
    print(f"  UNRESOLVED orphans:      {len(unresolved)}   "
          f"(no candidate found \u2014 edit preset manually)")
    if not args.apply and (auto_mapping or (high and low)):
        print("\nRe-run with --apply to write the changes.")
    if unresolved:
        print("\nUNRESOLVED LoRA references need manual attention. "
              "Either:")
        print("  (a) upload the missing file to ComfyUI, OR")
        print("  (b) remove / replace the reference in the preset JSON")
        print("Re-run this tool afterwards.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
