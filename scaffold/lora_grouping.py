"""LoRA purpose grouping + shootout engine.

The user's ComfyUI install often holds several LoRAs that do the same thing
— a dozen "feet" LoRAs, three "hand fix" LoRAs, five "skin detail" LoRAs.
If Spellcaster auto-injects all of them stacking will degrade the output.
This module:

  1. Scans the calibration-verified LoRA registry and assigns a
     `purpose_group` to each entry based on trigger words, filename
     keywords, and any user-supplied purpose string.
  2. Exposes the groups that have more than one member per architecture —
     those are the ones that need a human pick.
  3. Runs a *shootout*: render the same neutral prompt with each candidate
     LoRA at the same seed / strength, hand the gallery to the user.
  4. Accepts the user's pick + marks the winner `preferred_for_purpose=True`
     and the losers `deprioritized=True` in the shared registry. The
     `_get_loras_for_wizard` helper in tavern/server.py filters on these
     flags so the per-wizard sidebar only recommends the winner.

Same threaded-job pattern as lora_calibration.py and scaffold_calibration.py
— jobs live in a module-global dict, caller polls by `job_id`. All test-gen
heavy lifting delegates to the existing `_build_test_workflow` +
`generate_and_download` — no duplicated dispatch logic.
"""
from __future__ import annotations

import base64
import re
import threading
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Callable, Optional


# ── Purpose taxonomy ─────────────────────────────────────────────────────
#
# Keyword clusters that map to a canonical purpose_group. First-match wins;
# order the clusters most-specific → most-general so 'face_detail' beats the
# generic 'face' cluster.

_PURPOSE_RULES: list[tuple[str, tuple[str, ...]]] = [
    # Anatomy fixes (specific body parts) — the biggest source of LoRA
    # bloat. Tag as "<part>_fix" so we group a "feet LoRA" with every
    # other "feet LoRA" regardless of trainer name.
    ("hand_fix",      ("hand", "hands", "fingers", "finger")),
    ("feet_fix",      ("feet", "foot", "toes", "toe", "soles", "footjob",
                       "foot_worship")),
    ("face_detail",   ("face_detail", "facedetail", "facial", "face_fix",
                       "head", "headshot")),
    ("skin_detail",   ("skin", "pore", "realskin", "skinmix", "epidermis",
                       "oiled", "chrome skin")),
    ("eye_detail",    ("eye", "eyes", "iris", "pupil", "sclera")),
    ("teeth_fix",     ("teeth", "mouth", "smile", "lips")),
    ("hair_detail",   ("hair", "hairstyle", "bangs", "ponytail", "braid")),

    # Body / anatomy — catches a massive bucket of NSFW and non-NSFW
    # LoRAs that all describe body parts or body-shape modifiers.
    # These were previously all landing under "other".
    ("anatomy_body",  ("body", "anatomy", "torso", "back", "shoulder",
                       "waist", "hip", "hips", "thigh", "thighs",
                       "leg", "legs", "arm", "arms", "butt", "ass",
                       "booty", "curves", "curvy")),
    ("anatomy_chest", ("breast", "breasts", "tits", "boob", "boobs",
                       "sideboob", "underboob", "nipple", "nipples",
                       "cleavage", "chest", "bust", "perky", "c tits",
                       "perkyctits")),
    ("anatomy_genital", ("pussy", "vagina", "vulva", "penis", "cock",
                         "dick", "genital", "genitals", "pubic")),

    # Global quality / detail tweakers
    ("detail_boost",  ("detail", "details", "tweaker", "sharp", "crisp",
                       "enhance", "detailer")),
    ("contrast_fix",  ("contrast", "vivid", "saturat")),

    # Acceleration / turbo paths
    ("acceleration",  ("lcm", "turbo", "lightning", "hyper", "lightx2v",
                       "accel", "distill", "4step", "8step", "speed")),

    # Style / aesthetic
    ("style_anime",   ("anime", "manga", "toon", "2d", "waifu")),
    ("style_photoreal", ("photoreal", "realistic", "photo", "realism",
                         "cinematic", "analog", "film", "photograph")),
    ("style_paint",   ("paint", "oil", "watercolor", "impasto", "brush",
                       "illustration", "digital art")),
    ("style_cyber",   ("cyber", "neon", "synthwave", "retrowave")),
    ("style_gothic",  ("gothic", "dark fantasy", "noir", "dark")),
    ("style_ethereal", ("ethereal", "elegance", "elegant", "fantasy",
                        "dreamy", "surreal", "magical")),

    # Clothing / outfit
    ("clothing",      ("dress", "outfit", "costume", "armor", "uniform",
                       "lingerie", "kimono", "corset", "suit", "underwear",
                       "bikini", "swimsuit", "nude", "clothed")),

    # Lighting / environment
    ("lighting",      ("light", "lighting", "shadow", "ambient",
                       "rim_light", "golden_hour", "sunset")),
    ("environment",   ("landscape", "scenery", "environment", "background",
                       "forest", "city", "interior")),

    # Poses / composition
    ("pose",          ("pose", "posing", "gesture", "sitting", "standing",
                       "action", "portrait")),

    # Motion / video
    ("motion",        ("motion", "movement", "camera", "zoom", "pan",
                       "dolly", "i2v", "t2v", "animate")),

    # Character identity (personal likeness LoRAs). Big bucket; includes
    # named characters (2B, Jasmine), OC handles, and generic "pretty
    # person" descriptors.
    ("character",     ("character", "person", "identity", "ocs", "oc_",
                       "kawaii", "pretty", "princess", "queen", "girl",
                       "nier", "2b", "tifa", "jasmine", "jessica",
                       "disney", "goddess", "seraphim", "witch", "lady")),

    # NSFW action / pose LoRAs — these all describe a specific depiction
    # rather than a body part or style, so a dedicated bucket keeps them
    # separate from e.g. anatomy_body.
    ("action_pose",   ("cum", "cumshot", "kiss", "kissing", "blowjob",
                       "tentacled", "bondage", "spank", "grab")),
]


_PURPOSE_PRIORITY = {name: i for i, (name, _) in enumerate(_PURPOSE_RULES)}


def classify_lora_purpose(name: str, registry_entry: Optional[dict] = None) -> str:
    """Assign a canonical `purpose_group` to a LoRA.

    Priority: explicit `purpose_group` field → `purpose` keyword match →
    trigger words → filename keywords. Returns `"other"` when nothing fires.
    """
    e = registry_entry or {}
    if isinstance(e.get("purpose_group"), str) and e["purpose_group"]:
        return e["purpose_group"]

    # Strip the file extension BEFORE building the probe — otherwise
    # short keywords like "ass" false-match inside "safetensors" and
    # mis-classify anything as anatomy_body.
    bare = str(name or "").replace("\\", "/").rsplit("/", 1)[-1]
    if bare.lower().endswith(".safetensors"):
        bare = bare[:-len(".safetensors")]
    elif bare.lower().endswith(".ckpt"):
        bare = bare[:-len(".ckpt")]

    # Build probe WITHOUT lowercasing yet — the camelCase split needs
    # case information, and lowercase() before the split would turn
    # "FluxSideboob" into "fluxsideboob" (one token, unsplittable).
    probe = " ".join([
        str(e.get("purpose", "")),
        " ".join(str(t) for t in (e.get("trigger_words") or [])),
        str(e.get("user_desc", "")),
        bare,
    ])

    # Collapse separators so "hand_fix" and "hand-fix" both match "hand fix".
    normalised = re.sub(r"[\-_.]+", " ", probe)
    # Split camelCase ("FluxSideboob" -> "Flux Sideboob").
    normalised = re.sub(r"([a-z])([A-Z])", r"\1 \2", normalised)
    # Break letter↔digit boundaries ("Wan22" -> "Wan 22", "2B" -> "2 B").
    normalised = re.sub(r"([a-zA-Z])(\d)", r"\1 \2", normalised)
    normalised = re.sub(r"(\d)([a-zA-Z])", r"\1 \2", normalised)
    normalised = normalised.lower()
    # Word-boundary tokens so "ass" doesn't hit "classic", "bass", etc.
    tokens = set(normalised.split())

    for group, keywords in _PURPOSE_RULES:
        for kw in keywords:
            # Multi-word keywords (e.g. "dark fantasy") stay as substring
            # matches against the full normalised string; single-word
            # keywords use the whole-token set to avoid substring false
            # positives.
            if " " in kw:
                if kw in normalised:
                    return group
            else:
                if kw in tokens:
                    return group
    return "other"


# ── Group enumeration ────────────────────────────────────────────────────

def enumerate_groups(lora_registry: dict) -> dict[tuple[str, str], list[dict]]:
    """Given `_LORA_REGISTRY` (dict[name, entry]), return
    {(arch, purpose_group): [entries]} for every (arch, group) with at
    least ONE member. The caller filters for `len > 1` to find groups
    that actually need a shootout.
    """
    groups: dict[tuple[str, str], list[dict]] = {}
    for name, entry in (lora_registry or {}).items():
        if not isinstance(entry, dict):
            continue
        archs = entry.get("archs") or ["unknown"]
        if isinstance(archs, str):
            archs = [archs]
        purpose = classify_lora_purpose(name, entry)
        entry_pub = dict(entry)
        entry_pub["name"] = name
        entry_pub["purpose_group"] = purpose
        for a in archs:
            groups.setdefault((a, purpose), []).append(entry_pub)
    return groups


def groups_needing_pick(lora_registry: dict) -> list[dict]:
    """Return one record per (arch, purpose_group) that has ≥2 candidates
    AND no existing preferred winner. UI's "pending shootouts" list.

    Video archs (wan, ltx) are skipped — their LoRAs stay usable at
    strength 1.0 through the video inference path; a txt2img shootout
    would fail to dispatch and confuse the user. Acceleration LoRAs
    are skipped for the same reason: they're always used at 1.0 with
    a single correct option per arch.
    """
    out = []
    for (arch, purpose), members in enumerate_groups(lora_registry).items():
        if (arch or "").lower() in _SKIP_SHOOTOUT_ARCHS:
            continue
        if purpose in _SKIP_SHOOTOUT_GROUPS:
            continue
        if len(members) < 2:
            continue
        # NOTE: With multi-approve (Phase 3) we allow re-running a
        # shootout even when a winner already exists — the user may
        # want to approve more LoRAs from the same group. Only skip
        # groups that already have EVERY member explicitly approved.
        all_approved = all(
            m.get("approved") or m.get("preferred_for_purpose")
            for m in members
        )
        if all_approved and all(m.get("preferred_for_purpose") for m in members):
            continue
        out.append({
            "arch":          arch,
            "purpose_group": purpose,
            "candidates":    [m["name"] for m in members],
            "count":         len(members),
        })
    # Highest-count groups first so the user can tackle the biggest clutter.
    out.sort(key=lambda r: (-r["count"], r["arch"], r["purpose_group"]))
    return out


# ── Shootout engine ──────────────────────────────────────────────────────

# Archs that never benefit from a diffusion-style shootout (video archs
# route through WanGP, not build_txt2img) — skip their LoRAs from
# groups_needing_pick. The LoRAs stay usable at strength 1.0 through the
# normal wan/ltx inference path.
_SKIP_SHOOTOUT_ARCHS = {"wan", "ltx"}

# Groups the user never wants to shoot out. Acceleration LoRAs are
# always used at strength 1.0 with a single correct option per arch;
# a visual pick doesn't help.
_SKIP_SHOOTOUT_GROUPS = {"acceleration"}

# Subject templates — one human-readable prompt per subject the user
# can test LoRAs against. The UI lets the user pick any of these on a
# per-LoRA basis via the subject dropdown; Phase 2 resample endpoint
# accepts the subject key and rebuilds the prompt from this table.
# Each entry is (positive, negative).
_SUBJECT_TEMPLATES: dict[str, tuple[str, str]] = {
    "portrait_f":  ("portrait of a woman, soft natural light, detailed "
                     "skin, neutral background, photograph",
                     "blurry, low quality, deformed, cartoon, 3d render"),
    "portrait_m":  ("portrait of a man, soft natural light, detailed "
                     "skin, neutral background, photograph",
                     "blurry, low quality, deformed, cartoon, 3d render"),
    "fullbody_f":  ("full body photo of a woman standing in a studio, "
                     "neutral pose, natural light, realistic",
                     "blurry, low quality, deformed, cropped"),
    "fullbody_m":  ("full body photo of a man standing in a studio, "
                     "neutral pose, natural light, realistic",
                     "blurry, low quality, deformed, cropped"),
    "animal":      ("a detailed photograph of an animal in a natural "
                     "setting, soft natural light",
                     "blurry, low quality, deformed, human"),
    "feet":        ("close-up of two bare feet on a wooden floor, detailed "
                     "toes, natural lighting, photograph",
                     "blurry, extra toes, missing toes, deformed, sketch, "
                     "drawing, painting, low quality"),
    "hands":       ("close-up of two hands folded in lap, detailed fingers, "
                     "natural skin tone, photograph",
                     "blurry, extra fingers, fused fingers, deformed, "
                     "sketch, drawing, low quality"),
    "face_macro":  ("extreme close-up portrait of a face, detailed skin "
                     "texture, natural light, photograph",
                     "blurry, low quality, deformed, airbrushed, cartoon"),
    "eye_macro":   ("extreme close-up of a human eye, detailed iris, "
                     "natural light, eyelashes, photograph",
                     "blurry, low quality, cartoon, distorted"),
    "scene":       ("a detailed outdoor scene with a person walking, "
                     "cinematic composition, natural light, photograph",
                     "blurry, low quality, flat, sketch"),
}

# Default subject per purpose_group. Tuned so each LoRA's effect is
# visible without fighting the subject choice — feet LoRAs get a feet
# close-up, skin LoRAs get a portrait, pose LoRAs get a full body, etc.
# "skin_detail" explicitly uses a photo portrait to avoid the sketchy
# output users got from the old generic "person" prompt against realism
# LoRAs (the SDXL sketch-bug).
_DEFAULT_SUBJECT_FOR_GROUP: dict[str, str] = {
    "hand_fix":          "hands",
    "feet_fix":          "feet",
    "face_detail":       "face_macro",
    "skin_detail":       "portrait_f",
    "eye_detail":        "eye_macro",
    "teeth_fix":         "face_macro",
    "hair_detail":       "portrait_f",
    "anatomy_body":      "fullbody_f",
    "anatomy_chest":     "fullbody_f",
    "anatomy_genital":   "fullbody_f",
    "clothing":          "fullbody_f",
    "pose":              "fullbody_f",
    "action_pose":       "fullbody_f",
    "detail_boost":      "scene",
    "contrast_fix":      "scene",
    "character":         "portrait_f",
    "style_anime":       "portrait_f",
    "style_photoreal":   "portrait_f",
    "style_paint":       "portrait_f",
    "style_cyber":       "fullbody_f",
    "style_gothic":      "portrait_f",
    "style_ethereal":    "portrait_f",
    "lighting":          "scene",
    "environment":       "scene",
    "motion":            "scene",
    "acceleration":      "portrait_f",  # never shot but kept for safety
    "other":             "portrait_f",
}

# Per-arch overrides. Flux 2 Klein uniformly looks best on a male
# full-body subject at full strength — applying blanket defaults here
# avoids hand-tuning every group separately.
_ARCH_DEFAULT_OVERRIDES: dict[str, dict] = {
    "flux2klein":   {"subject": "fullbody_m", "strength": 1.0},
    # Flux 1 Dev + Kontext have no blanket subject change but the strength
    # cap stays at 1.0 (their LoRAs normally train at 1.0).
    "flux1dev":     {"strength": 1.0},
    "flux_kontext": {"strength": 1.0},
}

# Suggested strength per group (when no arch override applies). Values
# tuned so the default first-render is in the usable range — the user
# can retry Softer (x0.6) or Harder (x1.3) from there.
_DEFAULT_STRENGTH_FOR_GROUP: dict[str, float] = {
    "hand_fix": 0.7, "feet_fix": 0.7,
    "face_detail": 0.5, "skin_detail": 0.5, "eye_detail": 0.6,
    "teeth_fix": 0.5, "hair_detail": 0.5,
    "detail_boost": 0.5, "contrast_fix": 0.5,
    "style_anime": 0.7, "style_photoreal": 0.6, "style_paint": 0.7,
    "style_cyber": 0.7, "style_gothic": 0.7, "style_ethereal": 0.7,
    "clothing": 0.6, "lighting": 0.6, "environment": 0.6,
    "pose": 0.6, "action_pose": 0.7, "motion": 0.8,
    "character": 0.7,
    "anatomy_body": 0.6, "anatomy_chest": 0.6, "anatomy_genital": 0.6,
    "acceleration": 1.0,
    "other": 0.5,
}


def resolve_shootout_recipe(
    purpose_group: str,
    arch: str,
    subject: Optional[str] = None,
    strength: Optional[float] = None,
) -> tuple[str, str, str, float]:
    """Turn (group, arch, optional overrides) into a concrete recipe.

    Returns (subject_key, positive_prompt, negative_prompt, strength).
    The subject key is echoed back so the UI can show which template
    the server actually used. Arch overrides (e.g. Klein → fullbody_m)
    beat the group default UNLESS the caller passed an explicit subject.
    """
    arch_over = _ARCH_DEFAULT_OVERRIDES.get((arch or "").lower(), {})
    chosen_subject = (
        subject
        or arch_over.get("subject")
        or _DEFAULT_SUBJECT_FOR_GROUP.get(purpose_group, "portrait_f")
    )
    if chosen_subject not in _SUBJECT_TEMPLATES:
        chosen_subject = "portrait_f"
    pos, neg = _SUBJECT_TEMPLATES[chosen_subject]
    if strength is None:
        strength = arch_over.get("strength",
                                  _DEFAULT_STRENGTH_FOR_GROUP.get(
                                      purpose_group, 0.5))
    return chosen_subject, pos, neg, float(strength)


def _stitch_triggers_into_prompt(base_prompt: str, trigger_words: list[str]) -> str:
    """Prepend distinct trigger words to `base_prompt`, skipping any
    already present (case-insensitive). Keeps the template readable
    instead of just concatenating duplicates.
    """
    if not trigger_words:
        return base_prompt
    lowered = base_prompt.lower()
    to_add: list[str] = []
    for t in trigger_words:
        t = (t or "").strip()
        if not t:
            continue
        if t.lower() in lowered or t.lower() in (x.lower() for x in to_add):
            continue
        to_add.append(t)
    if not to_add:
        return base_prompt
    return ", ".join(to_add) + ", " + base_prompt


def _pick_example_snippet(examples: list[str], max_words: int = 14) -> str:
    """Return a short, template-friendly snippet from a Civitai example
    prompt. We trim to `max_words` tokens, strip lora/embedding tags,
    and reject anything that looks like a full recipe. The goal is
    flavour, not a verbatim copy — this keeps the comparison shootout
    honest (same base subject + each LoRA's contextual cue).
    """
    import re as _re
    for ex in examples:
        if not isinstance(ex, str):
            continue
        ex = _re.sub(r"<[^>]+>", "", ex).strip()          # drop <lora:...> tags
        ex = _re.sub(r"\s+", " ", ex)
        if not ex:
            continue
        tokens = ex.split()
        if len(tokens) > max_words:
            tokens = tokens[:max_words]
        candidate = " ".join(tokens).strip(" ,;:-")
        if len(candidate) >= 8:
            return candidate
    return ""


def resolve_shootout_recipe_for_lora(
    lora_name: str,
    purpose_group: str,
    arch: str,
    *,
    subject: Optional[str] = None,
    strength: Optional[float] = None,
    lora_abs_path: Optional[str] = None,
    user_override: Optional[dict] = None,
    use_network: bool = True,
) -> dict:
    """Per-LoRA recipe blending group defaults with `lora_knowledge`.

    Returns a dict with the full rendering recipe PLUS a `provenance`
    map so the UI can show "weight from Civitai / sampler from
    community / trigger from safetensors". On any failure we fall
    back to `resolve_shootout_recipe` — the caller always gets a
    rendering-ready result.

    Never raises: every step is wrapped so a bad import or a flaky
    Civitai response doesn't crash the shootout engine.
    """
    try:
        try:
            from spellcaster_core.lora_knowledge import (
                get_knowledge, classify_nsfw,
            )
        except ImportError:
            from lora_knowledge import get_knowledge, classify_nsfw  # type: ignore

        k = get_knowledge(
            lora_name,
            path=lora_abs_path,
            user_override=user_override,
            use_network=use_network,
        )
    except Exception as e:
        # Full fallback to group defaults on any knowledge error.
        subj, pos, neg, s = resolve_shootout_recipe(
            purpose_group, arch, subject=subject, strength=strength,
        )
        return {
            "subject_key":   subj,
            "prompt":        pos,
            "negative":      neg,
            "strength":      s,
            "sampler":       None,
            "cfg":           None,
            "trigger_words": [],
            "nsfw":          False,
            "provenance":    {"error": f"knowledge_error: {e!s}"[:160]},
            "knowledge":     None,
        }

    # Base template comes from subject picker (user override > arch
    # override > group default). Same resolver as the plain recipe.
    subj, base_pos, base_neg, group_strength = resolve_shootout_recipe(
        purpose_group, arch, subject=subject, strength=strength,
    )

    # Weave in trigger words (every LoRA's style head key) + one short
    # example phrase from Civitai. The example phrase gives the LoRA a
    # context it was trained on so the comparison shootout actually
    # exercises the LoRA rather than just the base model.
    prompt = _stitch_triggers_into_prompt(base_pos, k.trigger_words)
    snippet = _pick_example_snippet(k.example_prompts)
    if snippet and snippet.lower() not in prompt.lower():
        prompt = prompt + ", " + snippet

    # Strength: explicit caller > knowledge > group default. The
    # knowledge layer already applied user registry + shipped +
    # civitai + heuristic in that order, so we trust it when
    # populated.
    if strength is not None:
        final_strength = float(strength)
    elif k.recommended_weight is not None:
        final_strength = float(k.recommended_weight)
    else:
        final_strength = float(group_strength)
    # Clamp to a sane band — burn-in weights from bad training
    # crashes the LoRA's output into noise.
    if final_strength > 1.5:
        final_strength = 1.5
    if final_strength < 0.1:
        final_strength = 0.1

    try:
        nsfw = classify_nsfw(k, filename=lora_name)
    except Exception:
        nsfw = bool(getattr(k, "nsfw", False))

    return {
        "subject_key":   subj,
        "prompt":        prompt,
        "negative":      base_neg,
        "strength":      final_strength,
        "sampler":       k.recommended_sampler,
        "cfg":           k.recommended_cfg,
        "trigger_words": list(k.trigger_words),
        "nsfw":          nsfw,
        "provenance":    dict(k.provenance),
        "knowledge":     k.to_dict(),
    }


def list_subject_templates() -> list[dict]:
    """Public list for the UI's subject dropdown."""
    labels = {
        "portrait_f":  "Woman portrait",
        "portrait_m":  "Man portrait",
        "fullbody_f":  "Woman full body",
        "fullbody_m":  "Man full body",
        "animal":      "Animal",
        "feet":        "Feet close-up",
        "hands":       "Hands close-up",
        "face_macro":  "Face close-up",
        "eye_macro":   "Eye close-up",
        "scene":       "Scene with person",
    }
    return [{"key": k, "label": labels.get(k, k), "prompt": v[0]}
            for k, v in _SUBJECT_TEMPLATES.items()]


# Legacy per-group prompts — kept for backward compatibility with any
# older caller that still asks `shootout_prompt_for(group)`. New code
# should call `resolve_shootout_recipe()` which honours arch overrides
# and the subject dropdown.
_SHOOTOUT_PROMPTS: dict[str, tuple[str, str, float]] = {
    "hand_fix":     ("close-up of two hands folded in lap, detailed fingers, "
                     "natural skin tone, soft light",
                     "blurry, extra fingers, fused fingers, deformed hands",
                     0.7),
    "feet_fix":     ("close-up of two bare feet on a wooden floor, "
                     "detailed toes, natural lighting",
                     "blurry, extra toes, missing toes, deformed, low quality",
                     0.7),
    "face_detail":  ("portrait of a person's face, soft frontal light, "
                     "detailed skin, natural expression",
                     "blurry, low quality, deformed, airbrushed",
                     0.5),
    "skin_detail":  ("portrait of a person, soft natural light, detailed "
                     "skin texture, pores visible, realistic",
                     "plastic skin, smooth, airbrushed, doll-like, blurry",
                     0.5),
    "eye_detail":   ("extreme close-up of a human eye, detailed iris, "
                     "natural light, eyelashes",
                     "blurry, low quality, cartoon, distorted",
                     0.6),
    "teeth_fix":    ("person smiling, close-up of teeth, natural lighting",
                     "blurry, deformed teeth, bad anatomy",
                     0.5),
    "hair_detail":  ("portrait of a person, detailed flowing hair, "
                     "backlight highlights, natural movement",
                     "blurry, frizzy, flat, plastic hair",
                     0.5),
    "detail_boost": ("a detailed scene with a person in a garden, natural "
                     "light, fine textures, high detail",
                     "blurry, low quality, flat",
                     0.5),
    "contrast_fix": ("vivid colorful scene with a character, rich saturation",
                     "washed out, desaturated, flat",
                     0.5),
    "acceleration": ("a portrait of a person in a sunlit room, detailed",
                     "blurry, low quality",
                     1.0),  # acceleration LoRAs typically use strength 1.0
    "style_anime":  ("a character in an anime style scene",
                     "photorealistic, 3d render",
                     0.7),
    "style_photoreal": ("portrait of a person, natural light, cinematic, "
                        "detailed skin, realistic",
                        "cartoon, anime, 3d render, cgi",
                        0.6),
    "style_paint":  ("painted portrait of a person, visible brushstrokes",
                     "photograph, photoreal",
                     0.7),
    "style_cyber":  ("a character in a neon-lit cyberpunk city",
                     "plain, boring, monochrome",
                     0.7),
    "clothing":     ("a person wearing detailed clothing, full body shot, "
                     "natural lighting",
                     "nude, blurry, low quality",
                     0.6),
    "lighting":     ("a person in an atmospheric scene with dramatic light",
                     "flat, dull, low quality",
                     0.6),
    "environment":  ("a wide shot of a detailed environment, natural light",
                     "blurry, low detail, flat",
                     0.6),
    "pose":         ("a person in a dynamic pose, full body, natural light",
                     "blurry, deformed, bad anatomy",
                     0.6),
    "motion":       ("a person walking through a scene, motion blur, "
                     "cinematic",
                     "static, frozen, blurry",
                     0.8),
    "character":    ("a portrait of the character, neutral background, "
                     "soft light, detailed",
                     "blurry, low quality",
                     0.7),
    # Anatomy / body / action — test prompts that naturally exercise
    # each cluster so the user sees the LoRA's effect clearly.
    "anatomy_body":   ("full body shot of a person, natural pose, "
                       "neutral background, soft studio lighting",
                       "blurry, low quality, deformed",
                       0.6),
    "anatomy_chest":  ("upper body portrait of a person, natural pose, "
                       "detailed anatomy",
                       "blurry, low quality, deformed",
                       0.6),
    "anatomy_genital": ("full body study, detailed anatomy, natural pose",
                        "blurry, low quality, deformed",
                        0.6),
    "action_pose":    ("a dynamic scene, natural depiction, cinematic",
                       "blurry, low quality, static, flat",
                       0.7),
    "style_gothic":   ("a portrait in gothic aesthetic, dark atmospheric "
                       "lighting, detailed ornament",
                       "plain, generic, low quality",
                       0.7),
    "style_ethereal": ("an ethereal portrait, dreamy soft light, magical "
                       "atmosphere",
                       "harsh, grainy, low quality",
                       0.7),
    "other":        ("a portrait of a person in natural light, detailed, "
                     "neutral composition",
                     "blurry, low quality",
                     0.5),
}


def shootout_prompt_for(purpose_group: str) -> tuple[str, str, float]:
    return _SHOOTOUT_PROMPTS.get(purpose_group, _SHOOTOUT_PROMPTS["other"])


@dataclass
class ShootoutSample:
    lora_name: str
    strength: float
    image_b64: Optional[str]
    ok: bool
    error: str = ""
    elapsed_ms: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ShootoutResult:
    arch: str
    purpose_group: str
    prompt: str
    negative: str
    seed: int
    model: str
    samples: list[ShootoutSample] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["samples"] = [s.to_dict() for s in self.samples]
        return d


@dataclass
class ShootoutJobState:
    job_id: str
    arch: str
    purpose_group: str
    total: int
    done: int = 0
    current: str = ""
    result: Optional[ShootoutResult] = None
    status: str = "running"           # running | complete | error | cancelled
    error: str = ""
    started_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None
    cancel_requested: bool = False
    server: str = ""                   # retained so cancel can call ComfyUI

    def to_public_dict(self) -> dict:
        return {
            "job_id":        self.job_id,
            "arch":          self.arch,
            "purpose_group": self.purpose_group,
            "status":        self.status,
            "total":         self.total,
            "done":          self.done,
            "current":       self.current,
            "error":         self.error,
            "started_at":    self.started_at,
            "finished_at":   self.finished_at,
            "result":        self.result.to_dict() if self.result else None,
            "cancel_requested": self.cancel_requested,
        }


_JOBS: dict[str, ShootoutJobState] = {}
_JOBS_LOCK = threading.Lock()


def _comfy_cancel(server: str, timeout: float = 3.0) -> dict:
    """Interrupt the current ComfyUI render + clear the queue.

    Used by both shootout and calibration cancel paths. Two calls:
    `POST /interrupt` stops whatever's mid-sampling, and
    `POST /queue` with `{"clear": true}` drops everything queued.
    Errors are swallowed (best-effort) and reported in the returned
    dict so the caller can surface a warning without failing the
    cancel flow.
    """
    import urllib.error
    import urllib.request
    results = {"interrupt": False, "queue_clear": False, "errors": []}
    base = (server or "").rstrip("/")
    if not base:
        results["errors"].append("no ComfyUI server configured")
        return results
    for endpoint, label, body in (
        ("/interrupt", "interrupt", b"{}"),
        ("/queue", "queue_clear", b'{"clear": true}'),
    ):
        try:
            req = urllib.request.Request(
                base + endpoint,
                data=body,
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=timeout):
                results[label] = True
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as e:
            results["errors"].append(f"{label}: {e!s}"[:120])
    return results


def _pick_representative_model(discover_models_out: list, arch: str) -> Optional[dict]:
    candidates = [m for m in discover_models_out if m.get("arch") == arch]
    if not candidates:
        return None
    # Prefer models whose names suggest realism / photo (avoids NoobAI
    # and similar anime-trained checkpoints for the SDXL feet shootout
    # the user flagged as sketchy). Realism hints are purely heuristic
    # — if nothing matches, we fall back to alphabetical.
    realism_hints = ("realism", "realistic", "photo", "dreamshaper",
                     "juggernaut", "epicrealism", "realvis", "cyberreal")
    realistic = [m for m in candidates
                  if any(h in str(m.get("name", "")).lower()
                          for h in realism_hints)]
    pool = realistic or candidates
    return sorted(pool, key=lambda m: str(m.get("name", "")))[0]


def _models_for_arch(discover_models_out: list, arch: str,
                      exclude: Optional[set] = None) -> list[dict]:
    """Return every installed model matching `arch`, excluding a set of
    names (used for the auto-fallback path — if model A failed, try B).
    """
    exclude = exclude or set()
    return [
        m for m in discover_models_out
        if m.get("arch") == arch and m.get("name") not in exclude
    ]


def _render_single_sample(
    server: str,
    arch: str,
    lora_name: str,
    strength: float,
    prompt: str,
    negative: str,
    seed: int,
    models_pool: list[dict],
    preferred_model: Optional[str] = None,
    timeout: int = 90,
    sampler_override: Optional[str] = None,
    cfg_override: Optional[float] = None,
) -> ShootoutSample:
    """Render one LoRA sample with automatic model fallback.

    On generation failure (dispatch error, empty output, workflow build
    error) we try the next installed model of the same arch — up to
    three attempts. This turns a single broken checkpoint into a
    successful sample instead of a red "dispatch failed" card.

    preferred_model lets the caller pin a specific checkpoint (UI model
    picker); if it fails the fallback still kicks in.
    """
    try:
        from spellcaster_core.workflows import build_txt2img
        from spellcaster_core.architectures import get_arch
        from spellcaster_core.preference_calibration import generate_and_download
    except ImportError:
        from workflows import build_txt2img  # type: ignore
        from architectures import get_arch  # type: ignore
        from preference_calibration import generate_and_download  # type: ignore

    arch_obj = get_arch(arch)
    w, h = arch_obj.default_resolution if arch_obj else (768, 768)
    if w >= 1024:
        w, h = 768, 768

    # Build the model-try order: pinned first (if any), then
    # _pick_representative_model's choice, then every other arch model.
    tried: set[str] = set()
    order: list[dict] = []
    if preferred_model:
        pinned = next((m for m in models_pool
                        if m.get("name") == preferred_model), None)
        if pinned:
            order.append(pinned); tried.add(pinned["name"])
    rep = _pick_representative_model(models_pool, arch)
    if rep and rep["name"] not in tried:
        order.append(rep); tried.add(rep["name"])
    for m in _models_for_arch(models_pool, arch, exclude=tried):
        order.append(m); tried.add(m["name"])

    if not order:
        return ShootoutSample(
            lora_name=lora_name, strength=strength,
            image_b64=None, ok=False,
            error=f"no installed model for arch {arch!r}",
            elapsed_ms=0,
        )

    t0 = time.time()
    attempts: list[str] = []
    MAX_ATTEMPTS = 3
    # `extra` carries the per-arch CLIP / VAE filenames that Flux 1 Dev,
    # Flux Kontext, Flux 2 Klein, and Chroma ALL need — load_model_stack
    # reads clip_name1 / clip_name2 / clip_type / vae_name from the
    # preset. Before this change the shootout passed empty strings,
    # which is exactly why every Flux-family shootout returned "no
    # image" and NoobAI was the only SDXL that fired at all.
    arch_extra = dict(getattr(arch_obj, "extra", {}) or {})
    for model in order[:MAX_ATTEMPTS]:
        preset = {
            "arch": arch, "ckpt": model["name"],
            "width": w, "height": h,
            "steps": getattr(arch_obj, "default_steps", 20),
            "cfg":   (cfg_override
                      if cfg_override is not None
                      else getattr(arch_obj, "default_cfg", 6.0)),
            "denoise": 1.0,
            "sampler":   (sampler_override
                          or getattr(arch_obj, "default_sampler", "euler")),
            "scheduler": getattr(arch_obj, "default_scheduler", "normal"),
            "loader":    getattr(arch_obj, "loader", "checkpoint"),
            # Default filenames — arch_extra overrides below when the
            # arch (flux1dev / flux_kontext / flux2klein / chroma) needs
            # separate CLIP + VAE loaders.
            "clip_name1": arch_extra.get("clip_name1", ""),
            "clip_name2": arch_extra.get("clip_name2", ""),
            "clip_type":  arch_extra.get("clip_type",  ""),
            "vae_name":   arch_extra.get("vae_name",   ""),
        }
        loras = [{"name": lora_name,
                   "strength_model": strength,
                   "strength_clip": strength}]
        try:
            wf = build_txt2img(preset, prompt, negative, seed, loras=loras)
        except Exception as e:
            attempts.append(f"{model['name']}: build failed: {e}"[:140])
            continue
        try:
            png = generate_and_download(server, wf, timeout=timeout)
        except Exception as e:
            attempts.append(f"{model['name']}: dispatch failed: {e}"[:140])
            continue
        if png:
            return ShootoutSample(
                lora_name=lora_name, strength=strength,
                image_b64=base64.b64encode(png).decode("ascii"),
                ok=True,
                elapsed_ms=int((time.time() - t0) * 1000),
                error=(f"used fallback model {model['name']}"
                        if model is not order[0] else ""),
            )
        attempts.append(f"{model['name']}: empty output")
    return ShootoutSample(
        lora_name=lora_name, strength=strength,
        image_b64=None, ok=False,
        error=" | ".join(attempts)[:400],
        elapsed_ms=int((time.time() - t0) * 1000),
    )


def run_shootout(
    server: str,
    arch: str,
    purpose_group: str,
    candidate_loras: list[str],
    models: list[dict],
    seed: int = 12345,
    strength: Optional[float] = None,
    subject: Optional[str] = None,
    override_prompt: Optional[str] = None,
    override_negative: Optional[str] = None,
    override_model: Optional[str] = None,
    timeout: int = 90,
) -> ShootoutResult:
    """Render the same prompt with each candidate LoRA; return all samples.

    Reuses spellcaster_core.workflows.build_txt2img and
    preference_calibration.generate_and_download — no duplicated dispatch.
    Honours subject/prompt/model overrides from the UI.
    """
    subject_key, default_pos, default_neg, default_str = resolve_shootout_recipe(
        purpose_group, arch, subject=subject, strength=strength,
    )
    prompt = override_prompt if override_prompt else default_pos
    negative = override_negative if override_negative else default_neg
    eff_strength = float(strength if strength is not None else default_str)

    result = ShootoutResult(
        arch=arch, purpose_group=purpose_group,
        prompt=prompt, negative=negative, seed=seed, model=override_model or "",
    )
    for lora_name in candidate_loras:
        sample = _render_single_sample(
            server, arch, lora_name, eff_strength,
            prompt, negative, seed, models,
            preferred_model=override_model, timeout=timeout,
        )
        result.samples.append(sample)
    # Fill in representative model for the UI even when no override
    if not result.model:
        rep = _pick_representative_model(models, arch)
        if rep: result.model = rep["name"]
    return result


def start_shootout_job(
    server: str,
    arch: str,
    purpose_group: str,
    candidate_loras: list[str],
    models: list[dict],
    seed: int = 12345,
    strength: Optional[float] = None,
    subject: Optional[str] = None,
    override_prompt: Optional[str] = None,
    override_negative: Optional[str] = None,
    override_model: Optional[str] = None,
) -> ShootoutJobState:
    """Kick off an async shootout job. All overrides are optional —
    with none passed, we fall back to the subject + strength + model
    chosen by resolve_shootout_recipe + _pick_representative_model.

    The worker delegates per-LoRA rendering to _render_single_sample,
    which handles model auto-fallback so a single broken checkpoint
    doesn't kill the whole row of cards.
    """
    if (arch or "").lower() in _SKIP_SHOOTOUT_ARCHS:
        # Caller shouldn't dispatch shootouts for wan/ltx — return a
        # terminated job so the UI can show a clean "not applicable"
        # message instead of spinning forever.
        state = ShootoutJobState(
            job_id=f"lshoot_{uuid.uuid4().hex[:12]}",
            arch=arch, purpose_group=purpose_group, total=0,
            status="error",
            error=f"shootout not supported for arch {arch!r} "
                   f"(video archs use strength 1.0 directly)",
            finished_at=time.time(),
        )
        with _JOBS_LOCK:
            _JOBS[state.job_id] = state
        return state

    job_id = f"lshoot_{uuid.uuid4().hex[:12]}"
    state = ShootoutJobState(
        job_id=job_id, arch=arch, purpose_group=purpose_group,
        total=len(candidate_loras), server=server,
    )
    with _JOBS_LOCK:
        _JOBS[job_id] = state

    def _worker():
        try:
            subject_key, pos, neg, default_str = resolve_shootout_recipe(
                purpose_group, arch, subject=subject, strength=strength,
            )
            final_prompt = override_prompt if override_prompt else pos
            final_neg = override_negative if override_negative else neg
            eff_strength = float(strength if strength is not None else default_str)

            rep = (next((m for m in models
                          if m.get("name") == override_model), None)
                   if override_model
                   else _pick_representative_model(models, arch))
            if not rep and not any(m.get("arch") == arch for m in models):
                state.status = "error"
                state.error = f"no installed model for arch {arch!r}"
                return

            result = ShootoutResult(
                arch=arch, purpose_group=purpose_group,
                prompt=final_prompt, negative=final_neg,
                seed=seed, model=rep["name"] if rep else "",
            )
            for lora_name in candidate_loras:
                if state.cancel_requested:
                    break
                state.current = lora_name
                sample = _render_single_sample(
                    server, arch, lora_name, eff_strength,
                    final_prompt, final_neg, seed, models,
                    preferred_model=override_model, timeout=90,
                )
                result.samples.append(sample)
                state.done += 1
            state.result = result
            state.status = "cancelled" if state.cancel_requested else "complete"
        except Exception as e:
            state.status = "error"
            state.error = f"{e!s}"[:400]
        finally:
            state.finished_at = time.time()

    t = threading.Thread(target=_worker, daemon=True,
                         name=f"lora-shootout-{job_id}")
    t.start()
    return state


def resample_single_lora(
    server: str,
    arch: str,
    purpose_group: str,
    lora_name: str,
    models: list[dict],
    *,
    strength: Optional[float] = None,
    subject: Optional[str] = None,
    override_prompt: Optional[str] = None,
    override_negative: Optional[str] = None,
    override_model: Optional[str] = None,
    seed: int = 12345,
    timeout: int = 90,
) -> dict:
    """Synchronous per-LoRA resample — used by the UI's Retry /
    Softer / Harder buttons + manual-edit workflow. Returns a dict
    compatible with the sample shape the UI already renders. Blocks
    up to `timeout` seconds, so the HTTP handler should run this on a
    worker thread (GuildHandler already uses ThreadingHTTPServer)."""
    subject_key, pos, neg, default_str = resolve_shootout_recipe(
        purpose_group, arch, subject=subject, strength=strength,
    )
    final_prompt = override_prompt if override_prompt else pos
    final_neg = override_negative if override_negative else neg
    eff_strength = float(strength if strength is not None else default_str)
    sample = _render_single_sample(
        server, arch, lora_name, eff_strength,
        final_prompt, final_neg, seed, models,
        preferred_model=override_model, timeout=timeout,
    )
    out = sample.to_dict()
    out.update({
        "arch": arch,
        "purpose_group": purpose_group,
        "prompt": final_prompt,
        "negative": final_neg,
        "subject": subject_key,
        "model": override_model or (_pick_representative_model(models, arch) or {}).get("name", ""),
    })
    return out


def get_shootout_job(job_id: str) -> Optional[ShootoutJobState]:
    with _JOBS_LOCK:
        return _JOBS.get(job_id)


# ── Auto-calibration (one confirm-ready sample per unconfirmed LoRA) ────

def render_calibration_sample(
    server: str,
    lora_name: str,
    purpose_group: str,
    arch: str,
    models: list[dict],
    *,
    lora_abs_path: Optional[str] = None,
    user_override: Optional[dict] = None,
    subject: Optional[str] = None,
    seed: int = 12345,
    timeout: int = 90,
    use_network: bool = True,
    preferred_model: Optional[str] = None,
    score_with_llm: bool = False,
    ollama_url: Optional[str] = None,
    scorer_model: Optional[str] = None,
) -> dict:
    """Render ONE sample using the LoRA's auto-derived recipe.

    Pulls from `lora_knowledge` (Civitai + safetensors + sidecar +
    shipped defaults + heuristic), then dispatches the same way the
    shootout does. Return shape matches the shootout sample dict so
    the UI can reuse its card renderer.

    When `score_with_llm=True`, a successful render is also sent to
    a local Ollama multimodal model (default `gemma3:4b`) which
    returns a 0-10 quality score. The score is stapled onto the
    sample dict as `score` / `score_reason` so the UI can auto-
    confirm everything above a threshold. Scoring failures degrade
    silently — the sample still returns.
    """
    recipe = resolve_shootout_recipe_for_lora(
        lora_name, purpose_group, arch,
        subject=subject,
        lora_abs_path=lora_abs_path,
        user_override=user_override,
        use_network=use_network,
    )
    sample = _render_single_sample(
        server, arch, lora_name, float(recipe["strength"]),
        recipe["prompt"], recipe["negative"], seed, models,
        preferred_model=preferred_model,
        timeout=timeout,
        sampler_override=recipe.get("sampler"),
        cfg_override=recipe.get("cfg"),
    )
    out = sample.to_dict()
    out.update({
        "arch":          arch,
        "purpose_group": purpose_group,
        "prompt":        recipe["prompt"],
        "negative":      recipe["negative"],
        "subject":       recipe["subject_key"],
        "strength":      recipe["strength"],
        "sampler":       recipe.get("sampler"),
        "cfg":           recipe.get("cfg"),
        "trigger_words": recipe.get("trigger_words") or [],
        "nsfw":          recipe.get("nsfw"),
        "provenance":    recipe.get("provenance") or {},
        "knowledge":     recipe.get("knowledge"),
        "model":         preferred_model or (
                            _pick_representative_model(models, arch) or {}
                         ).get("name", ""),
    })
    # Optional vision scoring. Only attempt when the render succeeded
    # (no point scoring a red error card) and when the caller opted in.
    if score_with_llm and out.get("ok") and out.get("image_b64"):
        try:
            try:
                from spellcaster_core.lora_scorer import (
                    score_image, DEFAULT_OLLAMA_URL, DEFAULT_MODEL,
                )
            except ImportError:
                from lora_scorer import score_image, DEFAULT_OLLAMA_URL, DEFAULT_MODEL  # type: ignore
            result = score_image(
                out["image_b64"], out["prompt"],
                ollama_url=ollama_url or DEFAULT_OLLAMA_URL,
                model=scorer_model or DEFAULT_MODEL,
            )
            out["score"] = result.score
            out["score_reason"] = result.reason
            out["score_ok"] = bool(result.ok)
            if not result.ok:
                out["score_error"] = result.error
            out["score_model"] = result.model
            out["score_elapsed_ms"] = result.elapsed_ms
        except Exception as e:
            # Scoring is strictly optional; don't let its failures
            # corrupt the sample return value.
            out["score_ok"] = False
            out["score_error"] = f"scorer exception: {e!s}"[:160]
    return out


@dataclass
class CalibrationJobState:
    job_id: str
    total: int
    done: int = 0
    current: str = ""
    samples: list[dict] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)
    status: str = "running"           # running | complete | error | cancelled
    error: str = ""
    started_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None
    cancel_requested: bool = False
    server: str = ""                   # kept so cancel can call ComfyUI

    def to_public_dict(self) -> dict:
        return {
            "job_id":      self.job_id,
            "status":      self.status,
            "total":       self.total,
            "done":        self.done,
            "current":     self.current,
            "error":       self.error,
            "started_at":  self.started_at,
            "finished_at": self.finished_at,
            "samples":     list(self.samples),
            "skipped":     list(self.skipped),
            "cancel_requested": self.cancel_requested,
        }


_CALIB_JOBS: dict[str, CalibrationJobState] = {}
_CALIB_LOCK = threading.Lock()


def start_calibration_job(
    server: str,
    targets: list[dict],
    models: list[dict],
    *,
    lora_path_resolver: Optional[Callable[[str], Optional[str]]] = None,
    user_override_resolver: Optional[Callable[[str], Optional[dict]]] = None,
    seed: int = 12345,
    use_network: bool = True,
    score_with_llm: bool = False,
    ollama_url: Optional[str] = None,
    scorer_model: Optional[str] = None,
) -> CalibrationJobState:
    """Kick off a background batch auto-calibration.

    `targets` is a list of dicts with keys:
        {"name": <lora filename>, "arch": <arch>, "purpose_group": <group>}
    The worker renders one sample per target using that LoRA's
    `resolve_shootout_recipe_for_lora` recipe. The UI polls via
    `get_calibration_job(job_id)` and, on completion, walks each
    sample to show the user a "Confirm / Customize" card.

    Callers supply optional resolvers so this module stays decoupled
    from the Guild's registry + filesystem layout.
    """
    # Pre-filter: split targets into renderable vs skipped so the
    # progress bar counts only LoRAs we can actually render. A LoRA is
    # skipped when (a) its arch has zero installed base models, (b) the
    # arch is video-only (wan/ltx use a different inference path), or
    # (c) required fields are missing from the target dict. Skipped
    # entries still surface in the UI but don't trigger a failed
    # render attempt.
    archs_with_models: set[str] = {
        str(m.get("arch") or "").lower() for m in models if m.get("arch")
    }
    renderable: list[dict] = []
    skipped: list[dict] = []
    for t in targets:
        name = str(t.get("name") or "").strip()
        arch = str(t.get("arch") or "").strip()
        group = str(t.get("purpose_group") or "other").strip()
        if not name or not arch:
            skipped.append({"lora_name": name, "arch": arch,
                             "purpose_group": group,
                             "reason": "missing name or arch"})
            continue
        if arch.lower() in _SKIP_SHOOTOUT_ARCHS:
            skipped.append({"lora_name": name, "arch": arch,
                             "purpose_group": group,
                             "reason": "video arch (uses its own inference path)"})
            continue
        if arch.lower() not in archs_with_models:
            skipped.append({"lora_name": name, "arch": arch,
                             "purpose_group": group,
                             "reason": f"no installed model for arch {arch!r}"})
            continue
        renderable.append({"name": name, "arch": arch,
                            "purpose_group": group})

    job_id = f"lcal_{uuid.uuid4().hex[:12]}"
    state = CalibrationJobState(
        job_id=job_id, total=len(renderable), server=server,
    )
    state.skipped = skipped
    with _CALIB_LOCK:
        _CALIB_JOBS[job_id] = state

    def _worker():
        try:
            for t in renderable:
                if state.cancel_requested:
                    break
                name = t["name"]
                arch = t["arch"]
                group = t["purpose_group"]
                state.current = name
                lora_abs_path = (lora_path_resolver(name)
                                  if lora_path_resolver else None)
                user_over = (user_override_resolver(name)
                              if user_override_resolver else None)
                try:
                    out = render_calibration_sample(
                        server, name, group, arch, models,
                        lora_abs_path=lora_abs_path,
                        user_override=user_over,
                        seed=seed,
                        use_network=use_network,
                        score_with_llm=score_with_llm,
                        ollama_url=ollama_url,
                        scorer_model=scorer_model,
                    )
                except Exception as e:
                    out = {
                        "lora_name": name, "arch": arch,
                        "purpose_group": group, "ok": False,
                        "error": f"calibration error: {e!s}"[:200],
                    }
                state.samples.append(out)
                state.done += 1
            state.status = "cancelled" if state.cancel_requested else "complete"
        except Exception as e:
            state.status = "error"
            state.error = f"{e!s}"[:400]
        finally:
            state.finished_at = time.time()

    t = threading.Thread(target=_worker, daemon=True,
                         name=f"lora-calibrate-{job_id}")
    t.start()
    return state


def get_calibration_job(job_id: str) -> Optional[CalibrationJobState]:
    with _CALIB_LOCK:
        return _CALIB_JOBS.get(job_id)


# ── Cancel paths ────────────────────────────────────────────────────────

def cancel_shootout_job(job_id: str) -> dict:
    """Request stop of an in-flight shootout job. Flags the worker
    to break out of its loop AFTER the current render finishes, and
    tells ComfyUI to interrupt whatever is sampling right now."""
    with _JOBS_LOCK:
        state = _JOBS.get(job_id)
        if not state:
            return {"ok": False, "error": f"unknown job {job_id!r}"}
        if state.status in ("complete", "cancelled", "error"):
            return {"ok": True, "status": state.status,
                    "note": "job already finished"}
        state.cancel_requested = True
        server = state.server
    comfy = _comfy_cancel(server)
    return {"ok": True, "status": "cancel_requested",
            "comfy": comfy}


def cancel_calibration_job(job_id: str) -> dict:
    """Same contract as cancel_shootout_job but for the batch auto-
    calibrate worker."""
    with _CALIB_LOCK:
        state = _CALIB_JOBS.get(job_id)
        if not state:
            return {"ok": False, "error": f"unknown job {job_id!r}"}
        if state.status in ("complete", "cancelled", "error"):
            return {"ok": True, "status": state.status,
                    "note": "job already finished"}
        state.cancel_requested = True
        server = state.server
    comfy = _comfy_cancel(server)
    return {"ok": True, "status": "cancel_requested",
            "comfy": comfy}


__all__ = [
    "classify_lora_purpose",
    "enumerate_groups",
    "groups_needing_pick",
    "shootout_prompt_for",
    "resolve_shootout_recipe",
    "resolve_shootout_recipe_for_lora",
    "ShootoutSample",
    "ShootoutResult",
    "ShootoutJobState",
    "CalibrationJobState",
    "run_shootout",
    "start_shootout_job",
    "get_shootout_job",
    "render_calibration_sample",
    "start_calibration_job",
    "get_calibration_job",
    "cancel_shootout_job",
    "cancel_calibration_job",
]
