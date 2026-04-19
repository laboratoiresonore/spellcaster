"""Bake looping animated avatars for the canon Spellcaster wizards.

Why this exists
---------------
Every user installs the same 9 core studio wizards (Spellcaster,
Imaginus, Transmutex, Masquerade, Restorix, Erasure, Videomancer,
Cinematic, Studiocraft). Their avatars ship baked into
`tavern/default_assets/` so first launch looks polished without a
10-minute ComfyUI render queue.

This tool generates the *animated* versions — high-quality looping
I2V videos seeded by each canon PNG — and commits them alongside the
stills so every install ships with the wizards already breathing.

How it works
------------
1. Reads the list of wizards from `tavern/characters/*.json` (spec
   v2 character cards).
2. For each wizard, locates the corresponding static PNG in
   `tavern/default_assets/` (via manifest.avatars) OR falls back to
   `tavern/characters/<Name>.png` if the manifest doesn't list it
   (Spellcaster lives here).
3. Uploads the PNG to the running ComfyUI, then POSTs
   `/api/animated_avatar_queue` to the live Wizard Guild. The Guild
   picks WAN or LTX I2V based on what's installed (`_workflows_v2`
   + `_get_ltx_preset` / `_get_wan_preset`).
4. Polls `/api/animated_avatar_poll` until every job is done.
5. Downloads each resulting WebP / MP4 via the cached-asset URL,
   saves it under `tavern/default_assets/anim_<hex>.webp` (or .mp4,
   preserving whatever extension ComfyUI produced).
6. Updates `tavern/default_assets/manifest.json` with a new
   `animated_avatars: {char_id: filename}` section. The server's
   `_seed_default_assets` already honours this map — on fresh install,
   the sidebar chip for each canon wizard will autoplay the loop.

Usage
-----
    # From the host running the Wizard Guild (with ComfyUI reachable):
    python tools/bake_canon_animated_avatars.py \\
        --guild http://localhost:7777

    # If ComfyUI + LTX / WAN presets aren't on that box, use the
    # --comfy flag to point at a remote host (paired antenna):
    python tools/bake_canon_animated_avatars.py \\
        --guild http://localhost:7777 \\
        --comfy http://comfy.lan:8188

    # Dry-run (list what it would do, no API calls):
    python tools/bake_canon_animated_avatars.py --dry-run

The script is idempotent — re-running skips wizards that already have
a baked animated asset in the manifest. Use `--force` to re-render
everything (e.g. after a LoRA / preset change).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ASSETS_DIR = REPO_ROOT / "tavern" / "default_assets"
CHARACTERS_DIR = REPO_ROOT / "tavern" / "characters"
MANIFEST_PATH = DEFAULT_ASSETS_DIR / "manifest.json"


# ── The 9 core wizards. char_id must match tavern/server.py's wizard
# ── registry or the Guild's chip won't pick up the baked asset.
CANON_WIZARDS: list[tuple[str, str]] = [
    # (char_id, character-card filename stem under tavern/characters/)
    ("studio_spellcaster", "Spellcaster"),
    ("studio_imaginus",    "Imaginus"),
    ("studio_transmutex",  "Transmutex"),
    ("studio_masquerade",  "Masquerade"),
    ("studio_restorix",    "Restorix"),
    ("studio_erasure",     "Erasure"),
    ("studio_videomancer", "Videomancer"),
    ("studio_cinematic",   "Cinematic"),
    ("studio_studiocraft", "Studiocraft"),
]


def _load_manifest() -> dict:
    if not MANIFEST_PATH.is_file():
        return {"avatars": {}, "animated_avatars": {}}
    with MANIFEST_PATH.open("r", encoding="utf-8") as f:
        data = json.load(f)
    data.setdefault("animated_avatars", {})
    return data


def _save_manifest(data: dict) -> None:
    tmp = MANIFEST_PATH.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    tmp.replace(MANIFEST_PATH)


def _find_static_png(char_id: str, name_stem: str, manifest: dict) -> Optional[Path]:
    """Find the static PNG we should seed the animation from.
    Priority: manifest.avatars[char_id] → characters/<stem>.png."""
    baked_name = manifest.get("avatars", {}).get(char_id)
    if baked_name:
        p = DEFAULT_ASSETS_DIR / baked_name
        if p.is_file():
            return p
    p = CHARACTERS_DIR / f"{name_stem}.png"
    if p.is_file():
        return p
    return None


def _upload_to_comfyui(png_path: Path, comfy_url: str) -> Optional[str]:
    """POST the PNG to ComfyUI's /upload/image endpoint. Returns the
    filename ComfyUI assigned (may be renamed to avoid collisions)."""
    boundary = f"spellcasterbake{int(time.time())}"
    data = png_path.read_bytes()
    parts = [
        f"--{boundary}".encode(),
        (f'Content-Disposition: form-data; name="image"; '
         f'filename="{png_path.name}"').encode(),
        b"Content-Type: image/png",
        b"", data,
        f"--{boundary}".encode(),
        b'Content-Disposition: form-data; name="overwrite"',
        b"", b"true",
        f"--{boundary}--".encode(), b"",
    ]
    body = b"\r\n".join(parts)
    req = urllib.request.Request(
        f"{comfy_url.rstrip('/')}/upload/image",
        data=body,
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        }, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            out = json.loads(resp.read().decode("utf-8", "replace"))
            return out.get("name") or png_path.name
    except Exception as e:
        print(f"    [upload] {png_path.name} -> {comfy_url}: {e}")
        return None


def _enqueue(guild_url: str, char_id: str, comfy_filename: str,
              comfy_url: str) -> Optional[dict]:
    body = json.dumps({
        "id": char_id,
        "static_avatar_url": f"{comfy_url.rstrip('/')}/view?filename={comfy_filename}",
        "comfy_url": comfy_url,
    }).encode()
    req = urllib.request.Request(
        f"{guild_url.rstrip('/')}/api/animated_avatar_queue",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode("utf-8", "replace"))
        except Exception:
            return {"status": "error", "reason": f"HTTP {e.code}"}
    except Exception as e:
        return {"status": "error", "reason": str(e)}


def _poll(guild_url: str, wait_ids: set[str],
           poll_interval: float = 5.0,
           total_timeout: float = 1800.0) -> dict:
    """Poll /api/animated_avatar_poll until every id in wait_ids is
    done / errored or we hit total_timeout. Returns the final status
    map."""
    t0 = time.time()
    status: dict = {}
    while time.time() - t0 < total_timeout:
        try:
            with urllib.request.urlopen(
                    f"{guild_url.rstrip('/')}/api/animated_avatar_poll",
                    timeout=15) as resp:
                status = json.loads(resp.read().decode("utf-8", "replace"))
        except Exception as e:
            print(f"    [poll] failed: {e}")
            time.sleep(poll_interval)
            continue
        pending = [cid for cid in wait_ids
                    if status.get(cid, {}).get("status") == "queued"]
        done = [cid for cid in wait_ids
                 if status.get(cid, {}).get("status") in ("done", "error")]
        print(f"    [poll] {len(done)}/{len(wait_ids)} complete"
              + (f" - still rendering: {', '.join(pending[:3])}"
                  + ("..." if len(pending) > 3 else "")
                  if pending else ""))
        if not pending:
            return status
        time.sleep(poll_interval)
    return status


def _download(result_url: str, dest_dir: Path,
               stem_hint: str) -> Optional[Path]:
    """Download result_url to dest_dir. Filename is the content hash +
    extension ComfyUI produced so the commit is deterministic."""
    try:
        with urllib.request.urlopen(result_url, timeout=60) as resp:
            data = resp.read()
            ctype = (resp.headers.get("Content-Type") or "").lower()
    except Exception as e:
        print(f"    [download] {result_url}: {e}")
        return None
    # Derive extension from the URL / content-type
    ext = ".webp"
    low = result_url.lower()
    for cand in (".webp", ".mp4", ".webm", ".mov", ".gif"):
        if cand in low:
            ext = cand; break
    else:
        if "video/mp4" in ctype: ext = ".mp4"
        elif "image/gif" in ctype: ext = ".gif"
        elif "image/webp" in ctype: ext = ".webp"
    sha = hashlib.sha256(data).hexdigest()[:16]
    name = f"anim_{stem_hint}_{sha}{ext}"
    out = dest_dir / name
    out.write_bytes(data)
    return out


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--guild", default="http://127.0.0.1:7777",
                    help="Wizard Guild URL (default http://127.0.0.1:7777).")
    p.add_argument("--comfy", default=None,
                    help="Override ComfyUI URL (defaults to whatever the "
                          "Guild's config says).")
    p.add_argument("--force", action="store_true",
                    help="Re-render every wizard even if manifest already "
                          "has a baked animated avatar for them.")
    p.add_argument("--dry-run", action="store_true",
                    help="List what would be baked; make no API calls.")
    p.add_argument("--timeout-s", type=float, default=1800.0,
                    help="Total polling timeout (default 30 min).")
    args = p.parse_args()

    manifest = _load_manifest()

    # Resolve ComfyUI URL if not explicitly provided
    comfy_url = args.comfy
    if not comfy_url:
        try:
            cfg_path = REPO_ROOT / "tavern" / "guild_config.json"
            if cfg_path.is_file():
                with cfg_path.open("r", encoding="utf-8") as f:
                    gcfg = json.load(f)
                comfy_url = gcfg.get("comfyui_url")
        except Exception:
            comfy_url = None
    if not comfy_url:
        comfy_url = "http://127.0.0.1:8188"
        print(f"  [warn] --comfy not set and guild_config has no "
               f"comfyui_url; defaulting to {comfy_url}")

    plan: list[tuple[str, str, Path]] = []
    for char_id, stem in CANON_WIZARDS:
        if not args.force and manifest["animated_avatars"].get(char_id):
            print(f"  [skip] {char_id} — already baked "
                   f"({manifest['animated_avatars'][char_id]})")
            continue
        png = _find_static_png(char_id, stem, manifest)
        if png is None:
            print(f"  [warn] {char_id} — no canon PNG found, skipping")
            continue
        plan.append((char_id, stem, png))

    if not plan:
        print("\nNothing to bake. Use --force to re-render.")
        return 0

    print(f"\nPlan ({len(plan)} wizard(s)):")
    for char_id, stem, png in plan:
        print(f"  {char_id:28s}  <-{png.relative_to(REPO_ROOT)}")
    if args.dry_run:
        return 0

    # 1. Upload each PNG to ComfyUI
    print(f"\n1. Uploading {len(plan)} PNG(s) to {comfy_url}…")
    uploads: dict[str, str] = {}
    for char_id, _stem, png in plan:
        name = _upload_to_comfyui(png, comfy_url)
        if not name:
            print(f"    [fail] {char_id} upload failed — skipping wizard")
            continue
        uploads[char_id] = name

    # 2. Enqueue each via the Guild
    print(f"\n2. Enqueuing {len(uploads)} animation job(s) at {args.guild}…")
    enqueued: set[str] = set()
    for char_id, name in uploads.items():
        res = _enqueue(args.guild, char_id, name, comfy_url)
        tag = res.get("status") or res.get("queued") or "?"
        engine = res.get("engine") or ""
        reason = res.get("reason") or res.get("error") or ""
        print(f"    [{tag}] {char_id:28s}  engine={engine}  {reason}")
        if tag in ("queued", True):
            enqueued.add(char_id)

    if not enqueued:
        print("\nNo jobs queued. Is ComfyUI reachable and WAN/LTX installed?")
        return 2

    # 3. Poll
    print(f"\n3. Polling (timeout {args.timeout_s:.0f}s)…")
    final = _poll(args.guild, enqueued, total_timeout=args.timeout_s)

    # 4. Download + commit
    DEFAULT_ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    print(f"\n4. Downloading results into {DEFAULT_ASSETS_DIR.relative_to(REPO_ROOT)}…")
    updated = 0
    for char_id in enqueued:
        st = final.get(char_id, {})
        if st.get("status") != "done":
            print(f"    [skip] {char_id} — status={st.get('status')} "
                   f"{st.get('error') or ''}")
            continue
        url = st.get("result_url") or ""
        # result_url is a Guild-local /api/cached_asset/… URL; we turn
        # it into an absolute URL via the Guild.
        if url.startswith("/api/"):
            url = args.guild.rstrip("/") + url
        stem_hint = char_id.replace("studio_", "")
        out = _download(url, DEFAULT_ASSETS_DIR, stem_hint)
        if not out:
            continue
        manifest["animated_avatars"][char_id] = out.name
        updated += 1
        print(f"    [ok]   {char_id:28s}  <-{out.name}")

    # 5. Persist manifest
    if updated:
        _save_manifest(manifest)
        print(f"\nUpdated manifest with {updated} new animated avatar(s).")
        print(f"Commit {DEFAULT_ASSETS_DIR.relative_to(REPO_ROOT)}/ to ship "
               f"them to every future install.")
    else:
        print("\nNothing new to commit.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
