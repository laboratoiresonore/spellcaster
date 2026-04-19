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

    probe = " ".join([
        str(e.get("purpose", "")),
        " ".join(str(t) for t in (e.get("trigger_words") or [])),
        str(e.get("user_desc", "")),
        str(name or "").replace("\\", "/").rsplit("/", 1)[-1],
    ]).lower()

    # Collapse separators so "hand_fix.safetensors" matches "hand_fix"
    normalised = re.sub(r"[\-_.]+", " ", probe)

    for group, keywords in _PURPOSE_RULES:
        for kw in keywords:
            # Whole-word match with light fuzziness — the separator
            # collapse above makes substrings safe enough to use `in`.
            if kw in normalised:
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
    """
    out = []
    for (arch, purpose), members in enumerate_groups(lora_registry).items():
        if len(members) < 2:
            continue
        if any(m.get("preferred_for_purpose") for m in members):
            continue  # already resolved
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

# Neutral prompts per purpose_group — designed so the user can see the
# LoRA's effect cleanly without fighting subject choice. Each entry is
# (prompt, negative, suggested_strength).
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
    status: str = "running"           # running | complete | error
    error: str = ""
    started_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None

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
        }


_JOBS: dict[str, ShootoutJobState] = {}
_JOBS_LOCK = threading.Lock()


def _pick_representative_model(discover_models_out: list, arch: str) -> Optional[dict]:
    candidates = [m for m in discover_models_out if m.get("arch") == arch]
    if not candidates:
        return None
    return sorted(candidates, key=lambda m: str(m.get("name", "")))[0]


def run_shootout(
    server: str,
    arch: str,
    purpose_group: str,
    candidate_loras: list[str],
    models: list[dict],
    seed: int = 12345,
    strength: Optional[float] = None,
    timeout: int = 90,
) -> ShootoutResult:
    """Render the same prompt with each candidate LoRA; return all samples.

    Reuses spellcaster_core.workflows.build_txt2img and
    preference_calibration.generate_and_download — no duplicated dispatch.
    """
    try:
        from spellcaster_core.workflows import build_txt2img
        from spellcaster_core.architectures import get_arch
        from spellcaster_core.preference_calibration import generate_and_download
    except ImportError:
        from workflows import build_txt2img  # type: ignore
        from architectures import get_arch  # type: ignore
        from preference_calibration import generate_and_download  # type: ignore

    prompt, negative, default_strength = shootout_prompt_for(purpose_group)
    strength = float(strength if strength is not None else default_strength)

    model = _pick_representative_model(models, arch)
    if not model:
        return ShootoutResult(
            arch=arch, purpose_group=purpose_group,
            prompt=prompt, negative=negative, seed=seed, model="",
            samples=[],
        )

    arch_obj = get_arch(arch)
    w, h = arch_obj.default_resolution if arch_obj else (768, 768)
    if w >= 1024:
        w, h = 768, 768

    result = ShootoutResult(
        arch=arch, purpose_group=purpose_group,
        prompt=prompt, negative=negative, seed=seed, model=model["name"],
    )

    for lora_name in candidate_loras:
        t0 = time.time()
        preset = {
            "arch": arch, "ckpt": model["name"],
            "width": w, "height": h,
            "steps": getattr(arch_obj, "default_steps", 20),
            "cfg":   getattr(arch_obj, "default_cfg", 6.0),
            "denoise": 1.0,
            "sampler":   getattr(arch_obj, "default_sampler", "euler"),
            "scheduler": getattr(arch_obj, "default_scheduler", "normal"),
            "loader":    getattr(arch_obj, "loader", "checkpoint"),
            "clip_name1": "", "clip_name2": "", "vae_name": "",
        }
        loras = [{"name": lora_name, "strength_model": strength,
                  "strength_clip": strength}]
        try:
            wf = build_txt2img(preset, prompt, negative, seed, loras=loras)
        except Exception as e:
            result.samples.append(ShootoutSample(
                lora_name=lora_name, strength=strength,
                image_b64=None, ok=False,
                error=f"build failed: {e}"[:200],
                elapsed_ms=int((time.time() - t0) * 1000),
            ))
            continue
        try:
            png = generate_and_download(server, wf, timeout=timeout)
        except Exception as e:
            result.samples.append(ShootoutSample(
                lora_name=lora_name, strength=strength,
                image_b64=None, ok=False,
                error=f"dispatch failed: {e}"[:200],
                elapsed_ms=int((time.time() - t0) * 1000),
            ))
            continue
        result.samples.append(ShootoutSample(
            lora_name=lora_name, strength=strength,
            image_b64=base64.b64encode(png).decode("ascii") if png else None,
            ok=png is not None,
            elapsed_ms=int((time.time() - t0) * 1000),
        ))
    return result


def start_shootout_job(
    server: str,
    arch: str,
    purpose_group: str,
    candidate_loras: list[str],
    models: list[dict],
    seed: int = 12345,
    strength: Optional[float] = None,
) -> ShootoutJobState:
    job_id = f"lshoot_{uuid.uuid4().hex[:12]}"
    state = ShootoutJobState(
        job_id=job_id, arch=arch, purpose_group=purpose_group,
        total=len(candidate_loras),
    )
    with _JOBS_LOCK:
        _JOBS[job_id] = state

    def _worker():
        try:
            result = ShootoutResult(
                arch=arch, purpose_group=purpose_group,
                prompt="", negative="", seed=seed, model="",
            )
            try:
                from spellcaster_core.workflows import build_txt2img
                from spellcaster_core.architectures import get_arch
                from spellcaster_core.preference_calibration import generate_and_download
            except ImportError:
                from workflows import build_txt2img  # type: ignore
                from architectures import get_arch  # type: ignore
                from preference_calibration import generate_and_download  # type: ignore

            prompt, negative, default_strength = shootout_prompt_for(purpose_group)
            eff_strength = float(strength if strength is not None else default_strength)
            result.prompt = prompt
            result.negative = negative

            model = _pick_representative_model(models, arch)
            if not model:
                state.status = "error"
                state.error = f"no installed model for arch {arch!r}"
                return
            result.model = model["name"]
            arch_obj = get_arch(arch)
            w, h = arch_obj.default_resolution if arch_obj else (768, 768)
            if w >= 1024:
                w, h = 768, 768
            for lora_name in candidate_loras:
                state.current = lora_name
                t0 = time.time()
                preset = {
                    "arch": arch, "ckpt": model["name"],
                    "width": w, "height": h,
                    "steps": getattr(arch_obj, "default_steps", 20),
                    "cfg":   getattr(arch_obj, "default_cfg", 6.0),
                    "denoise": 1.0,
                    "sampler":   getattr(arch_obj, "default_sampler", "euler"),
                    "scheduler": getattr(arch_obj, "default_scheduler", "normal"),
                    "loader":    getattr(arch_obj, "loader", "checkpoint"),
                    "clip_name1": "", "clip_name2": "", "vae_name": "",
                }
                loras = [{"name": lora_name,
                          "strength_model": eff_strength,
                          "strength_clip":  eff_strength}]
                sample: ShootoutSample
                try:
                    wf = build_txt2img(preset, prompt, negative, seed, loras=loras)
                except Exception as e:
                    sample = ShootoutSample(
                        lora_name=lora_name, strength=eff_strength,
                        image_b64=None, ok=False,
                        error=f"build failed: {e}"[:200],
                        elapsed_ms=int((time.time() - t0) * 1000),
                    )
                else:
                    try:
                        png = generate_and_download(server, wf, timeout=90)
                        sample = ShootoutSample(
                            lora_name=lora_name, strength=eff_strength,
                            image_b64=base64.b64encode(png).decode("ascii") if png else None,
                            ok=png is not None,
                            elapsed_ms=int((time.time() - t0) * 1000),
                        )
                    except Exception as e:
                        sample = ShootoutSample(
                            lora_name=lora_name, strength=eff_strength,
                            image_b64=None, ok=False,
                            error=f"dispatch failed: {e}"[:200],
                            elapsed_ms=int((time.time() - t0) * 1000),
                        )
                result.samples.append(sample)
                state.done += 1
            state.result = result
            state.status = "complete"
        except Exception as e:
            state.status = "error"
            state.error = f"{e!s}"[:400]
        finally:
            state.finished_at = time.time()

    t = threading.Thread(target=_worker, daemon=True,
                         name=f"lora-shootout-{job_id}")
    t.start()
    return state


def get_shootout_job(job_id: str) -> Optional[ShootoutJobState]:
    with _JOBS_LOCK:
        return _JOBS.get(job_id)


__all__ = [
    "classify_lora_purpose",
    "enumerate_groups",
    "groups_needing_pick",
    "shootout_prompt_for",
    "ShootoutSample",
    "ShootoutResult",
    "ShootoutJobState",
    "run_shootout",
    "start_shootout_job",
    "get_shootout_job",
]
