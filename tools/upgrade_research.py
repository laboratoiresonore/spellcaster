#!/usr/bin/env python3
"""upgrade_research.py — inventory current integration state.

The 48-hour ecosystem-research routine (see PR #… / _dev_docs/ecosystem_digest_*.md)
starts its sweep by asking: "what does Spellcaster already integrate, so I know
what NOT to re-propose?". Prior runs of the routine re-crawled the repo every
time — this is that crawl, extracted so the cloud agent can `python
tools/upgrade_research.py` and get a stable, machine-readable snapshot in
one call instead of grepping around.

Output shape (stdout, JSON):

    {
      "generated_at": "<iso8601 utc>",
      "arch_registry": {
        "count": 27,
        "registered": ["sd15", "sdxl", ...],
        "stubs":      ["sd3", "supir", ...],   # registered=False
      },
      "builders": {
        "count": 73,
        "ids":   ["build_txt2img", ...],
      },
      "detect_keywords": {
        "unet_ckpt_arch_rules": [ ["klein", "flux2klein"], ... ],
      },
      "notes": [ "one-line strings about non-obvious integration state" ],
    }

The digest routine consumes this to skip already-covered ground.

Deliberately zero deps beyond stdlib so it runs on any CI runner /
sandbox without needing pip install.
"""
from __future__ import annotations

import ast
import datetime as _dt
import importlib.util
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
CORE = ROOT / "comfyui-spellcaster" / "spellcaster_core"


def _load_architectures():
    """Import architectures.py in isolation and return (registered, stubs)."""
    path = CORE / "architectures.py"
    spec = importlib.util.spec_from_file_location("_arch_probe", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    registered, stubs = [], []
    for key, cfg in sorted(module.ARCHITECTURES.items()):
        (registered if cfg.registered else stubs).append(key)
    return registered, stubs


def _extract_builder_ids():
    """Read builders_manifest.json and return the sorted id list."""
    path = CORE / "builders_manifest.json"
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    # Schema (see comfyui-spellcaster/spellcaster_core/build_builders_manifest.py):
    #   {"schema_version": ..., "generator": ..., "source": ...,
    #    "method_count": N, "methods": [ {"id": ..., "builder": ..., ...}, ... ]}
    methods = data.get("methods", []) if isinstance(data, dict) else data
    ids = [m["id"] for m in methods if isinstance(m, dict) and "id" in m]
    return sorted(set(ids))


_KW_RE = re.compile(
    r'^(UNET_ARCH_RULES|CKPT_ARCH_RULES)\s*=\s*(\[.*?\])',
    re.DOTALL | re.MULTILINE,
)


def _extract_detect_rules():
    """Parse the substring→arch rule tables out of model_detect.py."""
    src = (CORE / "model_detect.py").read_text(encoding="utf-8")
    out = {}
    for match in _KW_RE.finditer(src):
        name, body = match.group(1), match.group(2)
        try:
            out[name.lower()] = [list(t) for t in ast.literal_eval(body) if isinstance(t, tuple)]
        except (SyntaxError, ValueError):
            continue
    return out


def _notes(registered, stubs, builder_ids):
    notes = []
    if "supir" in stubs:
        notes.append("supir: restoration companion for SDXL, not summonable alone (build_supir(sdxl_model, supir_model)).")
    dit_stubs = [k for k in ("sd3", "sd3_turbo", "hunyuan_dit", "pixart", "auraflow", "kolors") if k in stubs]
    if dit_stubs:
        notes.append(f"DiT-only stubs (no builder yet): {', '.join(dit_stubs)}. Do not re-propose without pairing with a workflow builder.")
    video_covered = {"wan", "ltx", "seedvr", "cogvideo", "framepack", "hunyuan_video", "mochi"}
    live_video = sorted(video_covered.intersection(registered))
    if live_video:
        notes.append(f"Video archs already live: {', '.join(live_video)}.")
    if "hunyuan_3d" in registered:
        notes.append("hunyuan_3d: only 3D modality currently wired (mesh_gen + mesh_textured).")
    notes.append(f"{len(builder_ids)} builder ids in builders_manifest.json (source of truth for method dispatch).")
    return notes


def main() -> int:
    registered, stubs = _load_architectures()
    builder_ids = _extract_builder_ids()
    payload = {
        "generated_at": _dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "arch_registry": {
            "count": len(registered) + len(stubs),
            "registered": registered,
            "stubs": stubs,
        },
        "builders": {
            "count": len(builder_ids),
            "ids": builder_ids,
        },
        "detect_keywords": _extract_detect_rules(),
        "notes": _notes(registered, stubs, builder_ids),
    }
    json.dump(payload, sys.stdout, indent=2, sort_keys=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
