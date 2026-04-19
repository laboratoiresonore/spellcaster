"""Strategic install-order planner for the Spellcaster wizard.

Installing 240 GB in one silent lump is boring and risky — the user loses
interest, and a single download failure at the end wastes everything
upstream. The Spellcaster instead paces the install for maximum early
delight, interleaving quick wins with the heavyweight downloads so the
user is bought in long before the 50 GB video-model pull.

Design goals
------------
1. **Time-to-first-delight in under 10 minutes.** The SECOND item down
   the chute should already produce a usable image. The FIRST should be
   the local LLM so the Spellcaster wizard starts talking back richer.
2. **Small & proven before big & speculative.** Acceleration LoRAs and
   SAM3 utilities land before Klein / Flux weights; video comes last.
3. **Demo cues between steps.** Every milestone in the plan carries a
   `demo_cue` — a short narrative the Spellcaster speaks while the
   install runs, and a concrete `demo_gen_prompt` it fires as soon as
   the milestone completes. "You just unlocked SDXL — here's your first
   render to prove it."
4. **Fail soft.** Each step has a `blocking` flag. Non-blocking failures
   (e.g. "the Klein enhancer pack wasn't found") get flagged for later
   without stopping the overall sequence.

Callers (the Spellcaster scaffold + the Guild endpoints) treat the plan
as advisory; the user can always override the order. But the default
experience is orchestrated here.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional


# ── Priority tiers ──────────────────────────────────────────────────────

# Smaller tier number = earlier install.
# Tiers:
#   0 — infrastructure (LLM), blocks everything that follows
#   1 — quick wins that prove the stack (SDXL-turbo / ZIT, SAM3)
#   2 — headline image models (main SDXL, Klein)
#   3 — utility models (upscalers, rembg, face_restore)
#   4 — premium quality add-ons (Flux Dev, SUPIR)
#   5 — video (biggest downloads, save for last)

PLAN: list[dict] = [
    # ── Tier 0: infrastructure ─────────────────────────────────────────
    {
        "feature":   "prompt_enhance",
        "tier":      0,
        "blocking":  True,
        "label":     "Local LLM (prompt enhancer)",
        "why":       "This is how the Spellcaster thinks — every wizard's "
                     "replies and every prompt rewrite runs through it. "
                     "Tiny download (~1.5 GB), unlocks the whole chat flow.",
        "demo_cue":  "Once this lands I can start speaking in full sentences. "
                     "Hang tight.",
        "demo_gen_prompt": None,      # no image gen yet; the demo is the
                                       # wizard itself waking up.
    },

    # ── Tier 1: quick wins ─────────────────────────────────────────────
    {
        "feature":  "img2img",        # contains small SDXL-turbo / ZIT slices
        "tier":     1,
        "blocking": False,
        "label":    "First image model (ZIT + SDXL base)",
        "why":      "Proves your card + ComfyUI + the prompt path all work "
                     "end-to-end. ZIT is 6-step fast; we'll render you a "
                     "hello-world image the moment it's ready.",
        "demo_cue": "Opening the workshop doors — this is the moment "
                     "'a cat in a wizard hat' actually appears on your screen.",
        "demo_gen_prompt": ("a wise cat wearing a wizard hat, soft magical "
                            "lighting, detailed fur, studio quality",
                            "blurry, low quality"),
        "suggest_turbo": True,         # prefer the turbo variant for the demo
    },
    {
        "feature":  "segment",        # SAM3 + BiRefNet
        "tier":     1,
        "blocking": False,
        "label":    "AI selection (SAM3)",
        "why":      "Lets me understand words like 'hair' or 'background'. "
                     "Small download, huge capability jump — suddenly every "
                     "'select the shirt' instruction works.",
        "demo_cue": "After this I can read your image in plain English — "
                     "you describe a region, it gets selected.",
        "demo_gen_prompt": ("a portrait of a person in a blue shirt, "
                            "detailed face",
                            "blurry, low quality"),
    },
    {
        "feature":  "rembg",
        "tier":     1,
        "blocking": False,
        "label":    "Background removal",
        "why":      "One-click 'extract the subject, drop the background'. "
                     "Runs in seconds. Tiny model.",
        "demo_cue": "Small pack, big time-saver.",
        "demo_gen_prompt": None,
    },

    # ── Tier 2: headliners ─────────────────────────────────────────────
    {
        "feature":  "klein_flux2",
        "tier":     2,
        "blocking": False,
        "label":    "Flux 2 Klein (headline quality)",
        "why":      "~34 GB. This is where quality goes up visibly — "
                     "4-step renders that look like 20-step Flux Dev. Heavy "
                     "download, but you'll understand the cost the moment you "
                     "see your first render with it.",
        "demo_cue": "Pouring the good wine now. When this finishes I'll "
                     "render the same prompt on Klein so you can compare "
                     "against tier-1 side by side.",
        "demo_gen_prompt": ("a majestic phoenix taking flight over a "
                            "snowy mountain at dawn, volumetric light, "
                            "hyperdetailed feathers",
                            "blurry, low quality, deformed"),
    },

    # ── Tier 3: utility models ─────────────────────────────────────────
    {
        "feature":  "upscale",
        "tier":     3,
        "blocking": False,
        "label":    "Upscalers (SeedVR2, UltraSharp)",
        "why":      "Small downloads (~350 MB). After install, any image "
                     "you've already made today gets a 2x/4x button.",
        "demo_cue": "I'll grab the upscalers. Takes less than a minute.",
        "demo_gen_prompt": None,
    },
    {
        "feature":  "face_restore",
        "tier":     3,
        "blocking": False,
        "label":    "Face restoration (GPEN, CodeFormer)",
        "why":      "700 MB of face-repair specialists. Great on any "
                     "low-res or damaged portrait you feed it.",
        "demo_cue": "Pulling in the face-detail squad.",
        "demo_gen_prompt": None,
    },
    {
        "feature":  "iclight",
        "tier":     3,
        "blocking": False,
        "label":    "Relighting (IC-Light)",
        "why":      "1.7 GB. Lets you change where the light is coming from "
                     "on any already-rendered image. Magical when it works.",
        "demo_cue": "Installing the golden-hour machine.",
        "demo_gen_prompt": None,
    },
    {
        "feature":  "lama_remove",
        "tier":     3,
        "blocking": False,
        "label":    "LaMa object removal + Magic Eraser",
        "why":      "Paint a mask over anything unwanted; it disappears. "
                     "Small download, works with SAM3 for 'remove the car' "
                     "style commands.",
        "demo_cue": "One small pack, one big 'oops button' ability.",
        "demo_gen_prompt": None,
    },

    # ── Tier 4: premium quality ────────────────────────────────────────
    {
        "feature":  "supir",
        "tier":     4,
        "blocking": False,
        "label":    "SUPIR restoration (5 GB)",
        "why":      "State-of-the-art repair for scratched/compressed/JPEG'd "
                     "photos. Heavier; skip if you're not restoring old "
                     "photos.",
        "demo_cue": "Optional — skip if you don't restore old photos.",
        "demo_gen_prompt": None,
    },
    {
        "feature":  "face_swap_reactor",
        "tier":     4,
        "blocking": False,
        "label":    "Face swap (ReActor)",
        "why":      "~1 GB. Drop-in face swap. Also the substrate for "
                     "Masquerade's whole toolkit.",
        "demo_cue": "Identity tools incoming.",
        "demo_gen_prompt": None,
    },
    {
        "feature":  "controlnet",
        "tier":     4,
        "blocking": False,
        "label":    "ControlNet (6 structure guides)",
        "why":      "~10 GB of pose/depth/canny/scribble/lineart/tile "
                     "ControlNets. Gives you compositional control over "
                     "every generation.",
        "demo_cue": "The structural engineers. Heavier pack, but unlocks "
                     "pose-guided gen, scribble-to-image, etc.",
        "demo_gen_prompt": None,
    },
    {
        "feature":  "pulid_flux",
        "tier":     4,
        "blocking": False,
        "label":    "PuLID (Flux face-identity, 30 GB)",
        "why":      "Premium identity transfer on Flux. Huge download; skip "
                     "unless you specifically want to put someone's face on "
                     "generated characters.",
        "demo_cue": "Heavyweight identity pack — skip if you're not sure.",
        "demo_gen_prompt": None,
    },

    # ── Tier 5: video ──────────────────────────────────────────────────
    {
        "feature":  "wan_i2v",
        "tier":     5,
        "blocking": False,
        "label":    "Wan 2.2 image-to-video (~49 GB)",
        "why":      "The biggest single pull. Turns any still into a 2–5 "
                     "second clip. By the time you're here you already know "
                     "whether you want it — so we ask first, download only "
                     "if yes.",
        "demo_cue": "Optional and big. I'll confirm before pulling.",
        "demo_gen_prompt": None,
    },
]


@dataclass
class PlanStep:
    feature: str
    tier: int
    label: str
    why: str
    demo_cue: str
    demo_gen_prompt: Optional[tuple[str, str]]    # (prompt, neg) or None
    suggest_turbo: bool = False
    blocking: bool = False

    def to_dict(self) -> dict:
        d = asdict(self)
        # Tuples don't survive JSON; stringify only for wire format.
        if d["demo_gen_prompt"]:
            d["demo_gen_prompt"] = {
                "prompt":   d["demo_gen_prompt"][0],
                "negative": d["demo_gen_prompt"][1],
            }
        return d


def strategic_order(selected_features: list[str]) -> list[PlanStep]:
    """Return the user's chosen features in the strategic order.

    Features the user didn't pick are dropped. Features NOT in the plan
    (e.g. a brand-new manifest entry) are appended in tier 6 so they
    still land, just at the end.
    """
    selected = set(selected_features or [])
    seen: set[str] = set()
    ordered: list[PlanStep] = []
    for entry in PLAN:
        f = entry["feature"]
        if f in selected and f not in seen:
            ordered.append(PlanStep(
                feature=f,
                tier=int(entry["tier"]),
                label=entry["label"],
                why=entry["why"],
                demo_cue=entry.get("demo_cue", ""),
                demo_gen_prompt=entry.get("demo_gen_prompt"),
                suggest_turbo=bool(entry.get("suggest_turbo")),
                blocking=bool(entry.get("blocking", False)),
            ))
            seen.add(f)
    # Any user-picked features the static plan doesn't know about — append
    # at tier 6 so they install last without blocking demos above.
    for f in selected:
        if f not in seen:
            ordered.append(PlanStep(
                feature=f, tier=6, label=f, why="",
                demo_cue="", demo_gen_prompt=None,
            ))
    return ordered


def make_plan_view(selected_features: list[str]) -> dict:
    """UI-friendly dict: ordered steps + total tier count + a narrative arc.

    The narrative arc is 3-5 short lines the Spellcaster speaks at the
    start of the install, teasing what's about to happen.
    """
    steps = strategic_order(selected_features)

    tiers_present = sorted({s.tier for s in steps})
    tier_names = {
        0: "boot", 1: "first contact", 2: "headline",
        3: "utilities", 4: "premium", 5: "video",
        6: "unclassified",
    }

    narrative = []
    if 0 in tiers_present:
        narrative.append("Tier 0 (the LLM) first — that's how I talk back.")
    if 1 in tiers_present:
        narrative.append("Tier 1 — small, fast, and we'll render your "
                         "first image so you know it works.")
    if 2 in tiers_present:
        narrative.append("Tier 2 — the headline quality models. This is "
                         "where your card really stretches.")
    if 3 in tiers_present or 4 in tiers_present:
        narrative.append("Tiers 3–4 — the specialists: upscalers, face "
                         "restore, relighting, restoration. Short pulls, "
                         "big capability jumps.")
    if 5 in tiers_present:
        narrative.append("Tier 5 — video. The biggest download; I'll "
                         "confirm before starting it.")

    return {
        "steps":     [s.to_dict() for s in steps],
        "tiers":     [{"tier": t, "name": tier_names.get(t, "tier "+str(t))}
                      for t in tiers_present],
        "narrative": narrative,
        "total":     len(steps),
    }


__all__ = [
    "PLAN",
    "PlanStep",
    "strategic_order",
    "make_plan_view",
]
