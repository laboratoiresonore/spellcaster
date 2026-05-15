# Whimweaver replay-value bridge surface — proposal

Status: **proposal**, scaffolding shipped spellcaster-side only.
Audit item: **#5** from the 2026-05-15 spellcaster audit.
Authors: spellcaster master dev. Reviewers: whimweaver team.

## Why this exists

Whimweaver's characters have "infinite memory + HIGH replay value", so
the same character will show up across many sessions and conversations.
Today, every time a portrait of that character is regenerated we lose
identity continuity: the face drifts, the wardrobe drifts, sometimes the
gender drifts. Players notice. The audit flagged this as the biggest
remaining replay-value blocker.

The fix is a thin proxy surface on spellcaster's side that whimweaver
can call to:

1. recover the portrait history for a known character;
2. pick the right identity-preserving builder (PuLID-Flux → Klein
   img2img_ref → Klein headswap → Klein img2img → SDXL img2img) and
   produce a ready-to-submit kwargs packet;
3. promote one portrait to "canonical" so subsequent regenerations
   always condition on the same anchor face.

Critically, **whimweaver owns the reservoir on disk**. Spellcaster only
reads and rewrites the JSONL files it points to. No portrait bytes are
copied between repos — they live wherever whimweaver puts them and
spellcaster gets paths.

## Helper API

All three helpers live in
`comfyui-spellcaster/spellcaster_core/asset_gallery.py` so they ride
along with the existing hash-indexed gallery import surface. They are
re-exportable through whimweaver's existing
`app.services.spellcaster_proxy` shim with no changes to that shim
(PEP-562 module `__getattr__` already forwards arbitrary names through
to `spellcaster_core.*`).

### `get_character_portrait_history`

```python
def get_character_portrait_history(
    character_id: str,
    *,
    reservoir_root,         # path-like; whimweaver owns its location
    limit: int = 20,
) -> list[dict]: ...
```

Returns a list of portrait records, newest first. Each record carries:

| Field                | Type            | Notes |
|----------------------|-----------------|-------|
| `portrait_id`        | `str`           | unique within the character |
| `image_path`         | `str`           | absolute path OR a gallery-hash `gallery://sha256:…` URI |
| `builder`            | `str`           | the `build_*` name that produced it |
| `model_family`       | `str`           | e.g. `flux2_klein`, `flux1_dev`, `sdxl` |
| `prompt_seed`        | `int`           | seed used at generation |
| `parent_portrait_id` | `str \| None`   | the reference portrait this one was conditioned on |
| `generated_at`       | `float`         | unix ts |
| `canonical`          | `bool`          | the seed portrait the consistency loop references |

Returns `[]` when the reservoir file is missing — first-call safe.

### `build_consistent_portrait_for_character`

```python
def build_consistent_portrait_for_character(
    character_id: str,
    prompt: str,
    *,
    reservoir_root,
    builder_hint: str | None = None,
    feature_caps: dict | None = None,    # /v1/capabilities payload
) -> dict: ...
```

Returns:

```python
{
  "builder": "build_pulid_flux",          # chosen builder name
  "builder_args": {                       # kwargs whimweaver splats
    "face_ref_filename": "...path...",
    "prompt_text": "...",
    "negative_text": "",
    "seed": 1234,
  },
  "reference_portrait_id": "...",         # which past portrait we picked
  "reference_image_path": "...path...",
  "fallback_chain": [                     # builders considered, in order
    "build_pulid_flux",
    "build_klein_img2img_ref",
    "build_klein_headswap",
    "build_klein_img2img",
    "build_sdxl_img2img",
  ],
}
```

Strategy:

1. Read history. Pick the **canonical** portrait if one exists; else
   pick the newest portrait; else `None`.
2. Walk the builder preference order. Honor `builder_hint` when the
   capability map allows it. Skip identity-preserving builders when no
   reference is available.
3. Translate to a kwargs packet. Seed defaults to the reference
   portrait's seed so re-rolls converge.

The helper does **not** submit to ComfyUI — that stays whimweaver's
job through the existing proxy + submitter.

### `mark_canonical_portrait`

```python
def mark_canonical_portrait(
    character_id: str,
    portrait_id: str,
    *,
    reservoir_root,
) -> bool: ...
```

Sets `canonical=True` on the named portrait and `canonical=False` on
every other portrait for the same character. Atomic rewrite via
tempfile + `os.replace`. Returns `True` on success, `False` if the file
or id is missing.

## Proposed reservoir layout (whimweaver-owned)

```
<reservoir_root>/
  <character_id>/
    portraits.jsonl              # one record per line, append-only
    blobs/                       # whimweaver-internal — spellcaster doesn't touch
      <portrait_id>.png
    notes.md                     # optional, whimweaver-owned
```

`portraits.jsonl` line schema (one JSON object per line):

```json
{
  "portrait_id":        "p-2026-05-15-001",
  "image_path":         "C:/whimweaver/.../blobs/p-2026-05-15-001.png",
  "builder":            "build_pulid_flux",
  "model_family":       "flux1_dev",
  "prompt_seed":        1234,
  "parent_portrait_id": null,
  "generated_at":       1747353600.0,
  "canonical":          true
}
```

Append-only writes from whimweaver. Spellcaster only rewrites when
flipping the `canonical` flag (atomic — via tempfile + `os.replace`).

Crash safety: a half-written tail line is tolerated by the reader; a
torn rewrite is impossible because we go through `os.replace`.

## How whimweaver calls in

Suggested `character_manager.py` integration sketch (whimweaver-side,
not shipped here):

```python
from pathlib import Path
from app.services import spellcaster_proxy as sc

RESERVOIR_ROOT = Path(settings.whimweaver_data_dir) / "characters"


def get_portrait_for_turn(character_id: str, scene_prompt: str) -> Path:
    # 1) Ask spellcaster which builder to use.
    plan = sc.build_consistent_portrait_for_character(
        character_id=character_id,
        prompt=scene_prompt,
        reservoir_root=RESERVOIR_ROOT,
        feature_caps=current_caps_cache(),
    )

    # 2) Resolve the actual builder and submit through the existing proxy.
    builder_fn = getattr(sc, plan["builder"])
    workflow   = builder_fn(**plan["builder_args"])
    image_path = comfy_submitter.submit_and_collect(workflow)

    # 3) Append the new portrait to the reservoir (whimweaver-owned writer).
    portrait_id = f"p-{datetime.utcnow().strftime('%Y-%m-%d-%H%M%S')}"
    append_portrait_record(
        character_id, {
            "portrait_id":        portrait_id,
            "image_path":         str(image_path),
            "builder":            plan["builder"],
            "model_family":       resolve_family(plan["builder"]),
            "prompt_seed":        plan["builder_args"].get("seed"),
            "parent_portrait_id": plan["reference_portrait_id"],
            "generated_at":       time.time(),
            "canonical":          False,
        },
    )

    # 4) First portrait ever → promote it to canonical.
    if plan["reference_portrait_id"] is None:
        sc.mark_canonical_portrait(
            character_id, portrait_id, reservoir_root=RESERVOIR_ROOT
        )

    return image_path
```

## Identity-similarity test plan (follow-up)

After whimweaver wires this in, we should land a smoke test that
exercises continuity:

1. Spin up a fresh character `ada-lovelace`.
2. Drive a 3-turn conversation with the same character. At each turn,
   call `get_portrait_for_turn(...)` with a different scene prompt.
3. Run face-CLIP on the resulting 3 portraits. Assert that pairwise
   similarity between portrait 1 ↔ 2 and 1 ↔ 3 is `> 0.85` (the
   threshold the audit recommended).
4. Repeat with `canonical` flipped to portrait 2 and verify the next
   portrait pulls toward portrait 2 instead of portrait 1.

This test belongs in whimweaver's repo (it owns the reservoir writer)
but should import the spellcaster helpers via the proxy. We are NOT
shipping it as part of this PR — that crosses the spellcaster-only
scope of the audit item.

## Open questions for the whimweaver team

1. **Reservoir root** — is `<whimweaver_data_dir>/characters/` the
   right home, or should this live under
   `<whimweaver_data_dir>/replay/characters/` to leave room for other
   per-character assets (voice, music, lore deltas)?
2. **portrait_id format** — happy with the timestamp scheme above, or
   do you want a content-hash so collisions are impossible across
   parallel agents?
3. **gallery URIs vs raw paths** — whimweaver currently stores raw
   paths. Would you rather store `gallery://sha256:…` URIs and let
   spellcaster's `AssetGallery` deduplicate? That would mean piping
   bytes through `AssetGallery.put(...)` on every save.
4. **Feature caps wiring** — whimweaver caches `/v1/capabilities`
   somewhere already; can we agree on a function name on the
   whimweaver side (e.g. `current_caps_cache()`) so the proxy call
   doesn't have to round-trip HTTP on every portrait?
5. **Canonical drift** — should we expose a helper that
   auto-promotes a "better" portrait to canonical once we have N
   variations and a face-CLIP score? Out of scope for this PR.
6. **NSFW divergence** — `asset_gallery.py` is currently byte-identical
   in `spellcaster` and `spellcaster_NSFW`. We're mirroring this change
   into NSFW. If NSFW ever diverges these helpers should stay in sync.

## Files touched

- `comfyui-spellcaster/spellcaster_core/asset_gallery.py` — added the
  three helpers + private support functions (~270 LOC).
- `_dev_docs/WHIMWEAVER_REPLAY_BRIDGE_PROPOSAL.md` — this doc.

Mirrored into `spellcaster_NSFW` at the same path so both ecosystems
expose the same proxy surface.

No whimweaver code changes. The audit constraint "No whimweaver code
changes from spellcaster master" is respected.
