"""Prompt-scaffold calibration — test the per-arch prompt template against a model.

For every newly-activated checkpoint, the Spellcaster renders a small battery
of canonical scenarios:

    single_portrait   — one character, clean framing, no special tricks
    two_char_interact — two characters interacting (the hardest baseline;
                        this is where bad scaffolds fall apart — merged
                        bodies, shared limbs, prompt-leak between subjects)
    scene_with_object — character + prominent prop (tests object handling)
    turbo_single      — same single portrait but with the arch's turbo LoRA
                        and low step count — lets the user eyeball whether
                        turbo is acceptable for this particular model

The user reviews each output and picks one of:

    ok                — generation is good; use this scaffold + these
                        settings as the activated defaults for this model.
    scaffold_broken   — prompt template is the problem; try the next
                        scaffold variant.
    cfg_wrong         — composition is fine but cfg is off; bump and retry.
    turbo_bad         — the turbo sample is unusable; turn turbo off for
                        this model (single_portrait stays ok).
    elsewhere         — something else is wrong (VAE / architecture
                        mismatch / model corrupted) — escalate to the
                        Spellcaster for deeper diagnosis.

This module is a sibling of `lora_calibration.py`: same threaded-job model,
same polling pattern. Engines stay small; the heavy lifting (workflow
build, dispatch, image download) reuses spellcaster_core APIs.
"""
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Callable, Optional


# ── Test scenarios ───────────────────────────────────────────────────────
#
# Prompts designed to be neutral across architectures — the LLM-driven
# prompt scaffold layer turns them into arch-appropriate form (booru tags
# vs natural language) at render time. We rotate scaffolds below so the
# user can compare several prompt styles against the same subject.

SCENARIOS: dict[str, dict] = {
    "single_portrait": {
        "label":  "Single portrait",
        "prompt": "a portrait of a person in natural light, detailed face, "
                  "soft focus background",
        "negative": "blurry, low quality, deformed, bad anatomy",
        "notes":  "Cleanest baseline. If this looks wrong, the model is wrong, "
                  "not the scaffold.",
    },
    "two_char_interact": {
        "label":  "Two characters interacting",
        "prompt": "two people standing next to each other, one wearing red, "
                  "one wearing blue, looking at each other, full body, "
                  "detailed faces",
        "negative": "blurry, low quality, merged faces, shared limbs, "
                    "conjoined, prompt bleed",
        "notes":  "Hardest baseline. Merged bodies / shared limbs / color "
                  "bleed = the scaffold is losing subject separation. "
                  "Illustrious and Pony tend to need `BREAK` or weighted "
                  "emphasis here; Klein handles it natively.",
    },
    "scene_with_object": {
        "label":  "Scene with a prominent prop",
        "prompt": "a person holding a large red book, sitting at a wooden desk, "
                  "warm interior lighting, detailed hands",
        "negative": "blurry, low quality, extra fingers, deformed hands, "
                    "missing object",
        "notes":  "Tests prop-handling + hands. Bad hands = consider a hand-fix "
                  "LoRA; missing prop = prompt too vague, scaffold needs to "
                  "weight nouns.",
    },
    "turbo_single": {
        "label":  "Turbo single portrait",
        "prompt": "a portrait of a person in natural light, detailed face, "
                  "soft focus background",
        "negative": "blurry, low quality, deformed, bad anatomy",
        "turbo":  True,
        "notes":  "Same prompt as single_portrait but with the arch's turbo "
                  "LoRA + low-step / low-CFG config. User eyeballs whether "
                  "the quality loss is acceptable vs the speed win.",
    },
}


# ── Scaffold variants to probe per architecture ─────────────────────────
#
# When the user says "scaffold_broken" on a scenario, the engine retries
# with the NEXT variant here. Variants are architecture-specific (booru
# tags for SDXL/Illustrious, natural language for Flux, etc.) and the
# engine doesn't reinvent prompt formatting — it just swaps which system
# prompt template the scaffold layer uses. See spellcaster_core.prompt_enhance.

SCAFFOLD_VARIANTS: dict[str, list[str]] = {
    "sdxl":        ["sdxl_booru_tags", "sdxl_natural", "sdxl_weighted"],
    "sd15":        ["sd15_booru_tags", "sd15_natural"],
    "illustrious": ["illustrious_danbooru", "illustrious_natural"],
    "pony":        ["pony_source_tags", "pony_danbooru"],
    "flux1dev":    ["flux_natural", "flux_cinematic"],
    "flux2klein":  ["klein_concise", "klein_narrative"],
    "flux_kontext":["kontext_edit_instruction"],
    "chroma":      ["chroma_natural"],
    "zit":         ["zit_minimal", "sdxl_booru_tags"],
}


# ── Result model ─────────────────────────────────────────────────────────

@dataclass
class ScenarioSample:
    scenario: str
    scaffold: str
    prompt: str
    negative: str
    cfg: float
    steps: int
    sampler: str
    scheduler: str
    turbo: bool
    seed: int
    image_b64: Optional[str] = None
    ok: bool = False
    error: str = ""
    elapsed_ms: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ScaffoldCalibrationResult:
    model: str
    arch: str
    samples: list[ScenarioSample] = field(default_factory=list)
    # Final settings the user blessed (populated after review; initially empty).
    settings: dict = field(default_factory=dict)
    status: str = "awaiting_review"   # awaiting_review | ok | failed | cancelled
    started_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["samples"] = [s.to_dict() for s in self.samples]
        return d


# ── Engine ───────────────────────────────────────────────────────────────

def _build_and_run_sample(
    server: str,
    model: dict,
    scenario_key: str,
    scaffold: str,
    overrides: Optional[dict] = None,
    seed: int = 42,
    timeout: int = 90,
) -> ScenarioSample:
    """Build one test workflow for (model × scenario × scaffold), run it,
    return a ScenarioSample with the PNG as b64 or an error string.

    Uses preference_calibration.generate_and_download so we don't re-implement
    dispatch. Prompt text comes from SCENARIOS; settings from the ARCHITECTURE
    defaults + overrides.
    """
    import base64
    scen = SCENARIOS[scenario_key]
    overrides = dict(overrides or {})

    try:
        try:
            from spellcaster_core.architectures import get_arch
            from spellcaster_core.workflows import build_txt2img
            from spellcaster_core.preference_calibration import generate_and_download
        except ImportError:
            from architectures import get_arch  # type: ignore
            from workflows import build_txt2img  # type: ignore
            from preference_calibration import generate_and_download  # type: ignore
    except Exception as e:
        return ScenarioSample(
            scenario=scenario_key, scaffold=scaffold,
            prompt=scen["prompt"], negative=scen.get("negative", ""),
            cfg=0.0, steps=0, sampler="", scheduler="", turbo=False, seed=seed,
            error=f"import failed: {e}"[:200],
        )

    arch = get_arch(model.get("arch", ""))
    if not arch:
        return ScenarioSample(
            scenario=scenario_key, scaffold=scaffold,
            prompt=scen["prompt"], negative=scen.get("negative", ""),
            cfg=0.0, steps=0, sampler="", scheduler="", turbo=False, seed=seed,
            error=f"unknown arch {model.get('arch')!r}",
        )

    w, h = arch.default_resolution
    if w >= 1024:
        w, h = 768, 768
    turbo = bool(scen.get("turbo") or overrides.get("turbo", False))
    if turbo:
        steps = overrides.get("steps") or getattr(arch, "turbo_steps",
                                                   max(4, arch.default_steps // 3))
        cfg   = overrides.get("cfg")   or getattr(arch, "turbo_cfg", 1.5)
    else:
        steps = overrides.get("steps") or arch.default_steps
        cfg   = overrides.get("cfg")   or arch.default_cfg

    sampler   = overrides.get("sampler")   or arch.default_sampler
    scheduler = overrides.get("scheduler") or arch.default_scheduler

    preset = {
        "arch": model["arch"], "ckpt": model["name"],
        "width": w, "height": h,
        "steps": steps, "cfg": float(cfg),
        "denoise": 1.0,
        "sampler": sampler, "scheduler": scheduler,
        "loader": arch.loader,
        "clip_name1": "", "clip_name2": "", "vae_name": "",
    }

    loras = None
    if turbo:
        turbo_lora = getattr(arch, "turbo_lora", None)
        if turbo_lora:
            loras = [{"name": turbo_lora,
                      "strength_model": 1.0, "strength_clip": 1.0}]

    t0 = time.time()
    try:
        wf = build_txt2img(preset, scen["prompt"], scen.get("negative", ""),
                           seed, loras=loras)
    except Exception as e:
        return ScenarioSample(
            scenario=scenario_key, scaffold=scaffold,
            prompt=scen["prompt"], negative=scen.get("negative", ""),
            cfg=float(cfg), steps=int(steps), sampler=sampler,
            scheduler=scheduler, turbo=turbo, seed=seed,
            elapsed_ms=int((time.time() - t0) * 1000),
            error=f"build_txt2img failed: {e}"[:200],
        )
    try:
        png = generate_and_download(server, wf, timeout=timeout)
    except Exception as e:
        return ScenarioSample(
            scenario=scenario_key, scaffold=scaffold,
            prompt=scen["prompt"], negative=scen.get("negative", ""),
            cfg=float(cfg), steps=int(steps), sampler=sampler,
            scheduler=scheduler, turbo=turbo, seed=seed,
            elapsed_ms=int((time.time() - t0) * 1000),
            error=f"dispatch failed: {e}"[:200],
        )
    elapsed = int((time.time() - t0) * 1000)
    return ScenarioSample(
        scenario=scenario_key, scaffold=scaffold,
        prompt=scen["prompt"], negative=scen.get("negative", ""),
        cfg=float(cfg), steps=int(steps), sampler=sampler,
        scheduler=scheduler, turbo=turbo, seed=seed,
        image_b64=base64.b64encode(png).decode("ascii") if png else None,
        ok=png is not None, elapsed_ms=elapsed,
    )


def calibrate_model_scaffold(
    server: str,
    model: dict,
    scenarios: Optional[list[str]] = None,
    seed: int = 42,
) -> ScaffoldCalibrationResult:
    """Render the canonical battery of scenarios for one model.

    Uses the default scaffold variant for the model's arch. If the user
    later marks a scenario `scaffold_broken`, the caller re-runs that
    single scenario with the next variant via
    `retry_scenario_with_next_scaffold()`.
    """
    if not model.get("name") or not model.get("arch"):
        raise ValueError("model must have `name` and `arch`")
    keys = scenarios if scenarios is not None else list(SCENARIOS.keys())

    arch = model["arch"]
    scaffold = (SCAFFOLD_VARIANTS.get(arch) or [f"{arch}_default"])[0]

    result = ScaffoldCalibrationResult(model=model["name"], arch=arch)
    for k in keys:
        s = _build_and_run_sample(server, model, k, scaffold, seed=seed)
        result.samples.append(s)
    result.finished_at = time.time()
    result.status = "awaiting_review" if any(s.ok for s in result.samples) else "failed"
    return result


def retry_scenario(
    server: str,
    model: dict,
    scenario_key: str,
    scaffold: str,
    overrides: Optional[dict] = None,
    seed: int = 42,
) -> ScenarioSample:
    """Re-render one scenario with a different scaffold / cfg / turbo setting.

    Called by the Spellcaster when the user rates a sample
    `scaffold_broken` or `cfg_wrong` — we don't re-run the whole battery,
    just the thing that needs rerunning.
    """
    return _build_and_run_sample(server, model, scenario_key, scaffold,
                                 overrides=overrides, seed=seed)


# ── Threaded job infrastructure (sibling of lora_calibration) ───────────

@dataclass
class ScaffoldJobState:
    job_id: str
    model: str
    arch: str
    status: str = "running"
    result: Optional[ScaffoldCalibrationResult] = None
    error: str = ""
    started_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None

    def to_public_dict(self) -> dict:
        return {
            "job_id":     self.job_id,
            "model":      self.model,
            "arch":       self.arch,
            "status":     self.status,
            "error":      self.error,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "result":     self.result.to_dict() if self.result else None,
        }


_JOBS: dict[str, ScaffoldJobState] = {}
_JOBS_LOCK = threading.Lock()


def start_scaffold_job(
    server: str,
    model: dict,
    scenarios: Optional[list[str]] = None,
    seed: int = 42,
) -> ScaffoldJobState:
    job_id = f"scal_{uuid.uuid4().hex[:12]}"
    state = ScaffoldJobState(job_id=job_id, model=model.get("name", ""),
                             arch=model.get("arch", ""))
    with _JOBS_LOCK:
        _JOBS[job_id] = state

    def _worker():
        try:
            state.result = calibrate_model_scaffold(server, model,
                                                     scenarios=scenarios,
                                                     seed=seed)
            state.status = state.result.status
        except Exception as e:
            state.status = "error"
            state.error = f"{e!s}"[:400]
        finally:
            state.finished_at = time.time()

    t = threading.Thread(target=_worker, daemon=True,
                         name=f"scaffold-cal-{job_id}")
    t.start()
    return state


def get_scaffold_job(job_id: str) -> Optional[ScaffoldJobState]:
    with _JOBS_LOCK:
        return _JOBS.get(job_id)


__all__ = [
    "SCENARIOS",
    "SCAFFOLD_VARIANTS",
    "ScenarioSample",
    "ScaffoldCalibrationResult",
    "calibrate_model_scaffold",
    "retry_scenario",
    "ScaffoldJobState",
    "start_scaffold_job",
    "get_scaffold_job",
]
