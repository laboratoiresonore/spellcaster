"""Dynamic system-prompt builder for the 8 non-Spellcaster studio wizards.

`studio_spellcaster` has its own scaffold (`spellcaster_wizard.py`) because
it's the install manager. The other 8 (Imaginus, Transmutex, Masquerade,
Restorix, Erasure, Videomancer, Cinematic, Studiocraft) previously used
hardcoded system prompts that mentioned tools the user might not have
installed and never mentioned which connected apps were live.

This module produces prompts tailored to the live install state:

  * Which `build_fn`s actually work on this ComfyUI server (needed-arch /
    needed-node-class satisfied).
  * Which architectures are available for txt2img / img2img (sd15, sdxl,
    flux1dev, flux2klein, chroma, illustrious, flux_kontext).
  * Which node packs are present for inpaint / SAM3 / Klein enhancer /
    ControlNet / IPAdapter / IC-Light.
  * Which connected apps are online (GIMP, Darktable, Resolve,
    SillyTavern) + which antennas are paired.
  * How many compatible LoRAs are available.

The output is a plain string returned by `build_prompt(studio_id, ctx)`
and spliced into the LLM system prompt in place of the static copy.

`ctx` shape
-----------
    {
      "comfyui_reachable": bool,
      "comfyui_url":       str,
      "archs":             set[str]  e.g. {"sd15","sdxl","flux1dev","flux2klein"}
      "node_classes":      set[str]  subset of the server's /object_info
      "connected_apps":    dict[str, dict]  from interface_registry.snapshot()
      "antennas":          list[dict]       from antenna_registry.list_entries()
      "lora_count":        int             compatible-LoRA count for this studio
      "personality":       str             auto-generated character personality
    }

All keys are optional; the builder degrades gracefully when a field is
missing or probe failed.
"""
from __future__ import annotations

from typing import Any


# ─── Tool requirements ───────────────────────────────────────────────────
#
# Per `build_fn`, list the ComfyUI capabilities needed. A tool is only
# surfaced to the LLM when every requirement is met.
#
#   archs     : at least one of these must be present in ctx["archs"]
#   nodes     : every class name must be present in ctx["node_classes"]
#   flag      : optional shorthand for "always include" (empty means yes)

TOOL_REQS: dict[str, dict[str, Any]] = {
    # ── Imaginus — image creation ──────────────────────────────────
    "build_txt2img":         {"archs": {"sd15","sdxl","flux1dev","flux2klein","chroma","illustrious","zit","pony"}},
    "build_controlnet_gen":  {"archs": {"sd15","sdxl","flux1dev","illustrious","zit"}, "nodes": {"ControlNetLoader"}},
    "build_colorize":        {"nodes": {"LoadImage"}},
    "build_ddcolor":         {"nodes": {"DDColor_Colorize"}},
    "build_iclight":         {"archs": {"sd15"}, "nodes": {"ICLightConditioning"}},
    "build_lut":             {"nodes": {"LoadImage"}},
    "build_generate_anything": {"archs": {"sd15","sdxl","flux1dev","flux2klein","chroma","illustrious","zit"}},

    # ── Transmutex — image transformation ──────────────────────────
    "build_img2img":             {"archs": {"sd15","sdxl","flux1dev","illustrious","zit","pony"}},
    "build_klein_img2img":       {"archs": {"flux2klein"}},
    "build_klein_img2img_ref":   {"archs": {"flux2klein"}},
    "build_klein_scene_img2img": {"archs": {"flux2klein"}},
    "build_klein_blend":         {"archs": {"flux2klein"}},
    "build_klein_repose":        {"archs": {"flux2klein"}},
    "build_klein_refine":        {"archs": {"flux2klein"}},
    "build_klein_color_match":   {"archs": {"flux2klein"}},
    "build_klein_virtual_tryon": {"archs": {"flux2klein"}},
    "build_style_transfer":      {"nodes": {"IPAdapterUnifiedLoader"}},
    "build_layer_blend":         {},
    "build_color_match":         {},
    "build_normal_map":          {"nodes": {"DepthAnythingPreprocessor"}},

    # ── Masquerade — faceswap + inpaint ────────────────────────────
    "build_inpaint":             {"archs": {"sd15","sdxl","flux1dev","illustrious"}},
    "build_klein_inpaint":       {"archs": {"flux2klein"}},
    "build_klein_auto_inpaint":  {"archs": {"flux2klein"}, "nodes": {"SAM3Segment"}},
    "build_klein_sam3_inpaint":  {"archs": {"flux2klein"}, "nodes": {"SAM3Segment"}},
    "build_klein_headswap":      {"archs": {"flux2klein"}},
    "build_klein_face_detail":   {"archs": {"flux2klein"}},
    "build_pulid_flux":          {"archs": {"flux1dev"}, "nodes": {"PulidFluxModelLoader"}},
    "build_faceswap":            {"nodes": {"ReActorFaceSwap"}},

    # ── Restorix — restoration / upscale ───────────────────────────
    "build_upscale":             {"nodes": {"ImageUpscaleWithModel"}},
    "build_klein_detail":        {"archs": {"flux2klein"}},
    "build_supir_upscale":       {"nodes": {"SUPIR_first_stage"}},
    "build_ccsr_upscale":        {"nodes": {"CCSR_Model_Loader"}},
    "build_klein_refine_anything": {"archs": {"flux2klein"}},

    # ── Erasure — removal / background ─────────────────────────────
    "build_rmbg":                {"nodes": {"RemoveBackground"}},
    "build_klein_erase":         {"archs": {"flux2klein"}},
    "build_klein_scene_clean":   {"archs": {"flux2klein"}, "nodes": {"SAM3Segment"}},

    # ── Videomancer — video generation ─────────────────────────────
    "build_wan_video":           {"archs": {"wan"}},
    "build_wan_flf":             {"archs": {"wan"}},
    "build_wan22_t2v":           {"archs": {"wan"}},
    "build_ltx_video":           {"archs": {"ltx"}, "nodes": {"LTXAVTextEncoderLoader"}},
    "build_seedvr2_video_upscale": {"nodes": {"SeedVR2VideoUpscaler"}},

    # ── Cinematic / Studiocraft — no generative build_fns today ────
}


# ─── Connected-app actions ───────────────────────────────────────────────
#
# Maps connected-app keys to a short tool description that makes sense for
# each studio wizard. When the app is live in ctx["connected_apps"] AND
# the current studio is in the studios set, the action is surfaced.

APP_ACTIONS: dict[str, dict[str, Any]] = {
    "gimp": {
        "label": "Send to GIMP",
        "desc":  "Push the generated image into GIMP as a new layer on the active canvas.",
        "studios": {"imaginus","transmutex","masquerade","restorix","erasure","studiocraft"},
    },
    "darktable": {
        "label": "Open in Darktable",
        "desc":  "Stage the image in the Darktable lighttable for RAW-style grading.",
        "studios": {"imaginus","transmutex","restorix","cinematic"},
    },
    "resolve": {
        "label": "Send to DaVinci Resolve",
        "desc":  "Drop the clip on the Resolve timeline for editing + colour.",
        "studios": {"videomancer","cinematic","studiocraft"},
    },
    "sillytavern": {
        "label": "Update SillyTavern character",
        "desc":  "Push this portrait to the matching SillyTavern character card.",
        "studios": {"imaginus","masquerade"},
    },
    "signal": {
        "label": "Send via Signal bridge",
        "desc":  "Deliver the result directly to the paired Signal chat.",
        "studios": {"imaginus","transmutex","videomancer","cinematic"},
    },
}


# ─── Per-studio static narrative + dispatch hints ────────────────────────

STUDIO_META = {
    "imaginus": {
        "name":     "Imaginus",
        "role":     "the Guild's master of image creation",
        "focus":    "creating images from text, generating guidance maps, colorising, and lighting tweaks",
    },
    "transmutex": {
        "name":     "Transmutex",
        "role":     "the Guild's alchemist of image transformation",
        "focus":    "transforming existing images: img2img, style transfer, Klein repose + scene swaps, blending",
    },
    "masquerade": {
        "name":     "Masquerade",
        "role":     "the Guild's masker — inpaint, face-swap, identity locks",
        "focus":    "editing parts of an image: inpainting, face swaps, head swaps, identity preservation",
    },
    "restorix": {
        "name":     "Restorix",
        "role":     "the Guild's restorer + upscaler",
        "focus":    "rescuing damaged images, super-resolution, face + detail enhancement",
    },
    "erasure": {
        "name":     "Erasure",
        "role":     "the Guild's eraser + background surgeon",
        "focus":    "removing objects, extracting subjects, cleaning scenes",
    },
    "videomancer": {
        "name":     "Videomancer",
        "role":     "the Guild's weaver of motion",
        "focus":    "animating stills (WAN / LTX i2v), text-to-video, frame interpolation, video upscaling",
    },
    "cinematic": {
        "name":     "Cinematic",
        "role":     "the Guild's cinematographer",
        "focus":    "shot design, camera vocabulary, colour grading, Resolve-aware editing pipelines",
    },
    "studiocraft": {
        "name":     "Studiocraft",
        "role":     "the Guild's scene builder",
        "focus":    "building multi-shot sequences, scene continuity, character-in-scene composition",
    },
}


def _tool_available(fn_name: str, ctx: dict[str, Any]) -> bool:
    """Return True iff every req for fn_name is satisfied by ctx."""
    reqs = TOOL_REQS.get(fn_name)
    if reqs is None:
        # Tools without explicit reqs are assumed always-available.
        return True
    if reqs.get("archs") and not (set(reqs["archs"]) & set(ctx.get("archs") or [])):
        return False
    if reqs.get("nodes") and not (set(reqs["nodes"]) <= set(ctx.get("node_classes") or [])):
        return False
    return True


def _available_tools(build_fns: list[str], ctx: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Partition build_fns into (available, unavailable) given ctx."""
    avail, blocked = [], []
    for fn in build_fns:
        if _tool_available(fn, ctx):
            avail.append(fn)
        else:
            blocked.append(fn)
    return avail, blocked


def _connected_apps_for_studio(studio_key: str, ctx: dict[str, Any]) -> list[dict]:
    """Return list of {key, label, desc} connected-app actions for this studio."""
    live = ctx.get("connected_apps") or {}
    results = []
    for app_key, info in APP_ACTIONS.items():
        if studio_key not in info.get("studios", set()):
            continue
        entry = live.get(app_key)
        if not entry:
            continue
        # Heartbeat or declared online — either counts. The interface
        # registry writes `online` when a recent heartbeat exists; plugins
        # that self-register via /api/interfaces/register set `declared`.
        is_live = bool(entry.get("online")) or bool(entry.get("declared"))
        if not is_live:
            continue
        results.append({
            "key":   app_key,
            "label": info["label"],
            "desc":  info["desc"],
        })
    return results


def _fmt_arch_list(archs: set[str]) -> str:
    """Friendly ordered list of the archs the user has installed."""
    if not archs:
        return "(no image-generation models detected)"
    order = ["sd15","sdxl","illustrious","pony","flux1dev","flux_kontext",
            "flux2klein","chroma","zit","wan","ltx"]
    ordered = [a for a in order if a in archs] + [a for a in archs if a not in order]
    pretty = {
        "sd15":"SD 1.5", "sdxl":"SDXL", "illustrious":"Illustrious",
        "pony":"Pony", "flux1dev":"Flux 1 Dev",
        "flux_kontext":"Flux Kontext",
        "flux2klein":"Flux 2 Klein", "chroma":"Chroma", "zit":"ZIT",
        "wan":"WAN 2.2", "ltx":"LTX 2.3",
    }
    return ", ".join(pretty.get(a, a) for a in ordered)


def _fmt_antennas(ctx: dict[str, Any]) -> str:
    ants = ctx.get("antennas") or []
    if not ants:
        return "  (no paired antennas)"
    lines = []
    for a in ants:
        host = a.get("hostname") or a.get("host") or "antenna"
        svcs = a.get("services") or a.get("services_declared") or []
        svc_str = ", ".join(svcs) if svcs else "(no declared services)"
        online = "online" if a.get("online") else "offline"
        lines.append(f"  {host} [{online}] — {svc_str}")
    return "\n".join(lines)


def _tool_display_line(fn_name: str, tool_descriptions: dict[str, str], idx: int) -> str:
    """One numbered line for a build_fn tool."""
    desc = tool_descriptions.get(fn_name)
    if not desc:
        nice = fn_name.replace("build_", "").replace("_", " ").title()
        desc = nice
    return f"{idx}. **{desc}** (`{fn_name}`)"


# ─── Per-studio tool descriptions (user-facing labels) ──────────────────
TOOL_DESC: dict[str, str] = {
    "build_txt2img":              "Text-to-Image — create a new image from a prompt",
    "build_controlnet_gen":       "ControlNet map — generate canny/depth/pose/lineart/tile from an image",
    "build_colorize":             "Colorize — turn a B&W image to colour",
    "build_ddcolor":              "DDColor — deep-learning colour restoration",
    "build_iclight":              "IC-Light — relight the subject with new lighting",
    "build_lut":                  "LUT grading — apply a cinematic colour LUT",
    "build_generate_anything":    "Generate Anything — arch-agnostic txt2img + SAM3 scope",

    "build_img2img":              "Image-to-Image — redirect an existing image with a prompt",
    "build_klein_img2img":        "Klein img2img — 4-20 step Flux 2 Klein transform",
    "build_klein_img2img_ref":    "Klein + reference — Klein transform with structure/style ref",
    "build_klein_scene_img2img":  "Klein scene — semantic scene-aware transform",
    "build_klein_blend":          "Klein blend — harmonise layers (lighting + shadows)",
    "build_klein_repose":         "Klein repose — change pose / angle / lens",
    "build_klein_refine":         "Klein refine — structural detail/quality enhancement",
    "build_klein_color_match":    "Klein colour match — fix colour drift to a reference",
    "build_klein_virtual_tryon":  "Virtual try-on — 4-ref photoshoot (face + outfit + bg + pose)",
    "build_style_transfer":       "Style transfer — IPAdapter-based style",
    "build_layer_blend":          "Layer blend — parametric blend of two images",
    "build_color_match":          "Colour match — match one image's palette to another",
    "build_normal_map":           "Normal map — generate a normal-map from depth",

    "build_inpaint":              "Inpaint — regenerate a masked region",
    "build_klein_inpaint":        "Klein inpaint — mask-driven regenerate on Flux 2 Klein",
    "build_klein_auto_inpaint":   "Klein auto-inpaint — SAM3-picked region, auto-masked",
    "build_klein_sam3_inpaint":   "Klein SAM3 inpaint — describe the region in plain text",
    "build_klein_headswap":       "Klein head swap — swap the head onto a body",
    "build_klein_face_detail":    "Klein face detail — face-only enhancement pass",
    "build_pulid_flux":           "PuLID (Flux) — identity-locked face condition",
    "build_faceswap":             "Face swap — ReActor face exchange",

    "build_upscale":              "AI upscale — model-based super-resolution",
    "build_klein_detail":         "Klein detail — resolution + detail restoration",
    "build_supir_upscale":        "SUPIR upscale — photoreal super-resolution",
    "build_ccsr_upscale":         "CCSR upscale — content-consistent super-resolution",
    "build_klein_refine_anything": "Klein refine-anything — universal quality pass",

    "build_rmbg":                 "Remove background — transparent cutout",
    "build_klein_erase":          "Klein erase — object removal with scene fill",
    "build_klein_scene_clean":    "Klein scene clean — SAM3-picked cleanup",

    "build_wan_video":            "WAN i2v — image-to-video loop/clip (canon LTX path)",
    "build_wan_flf":              "WAN first-last-frame — animate between two stills",
    "build_wan22_t2v":            "WAN t2v — text-to-video",
    "build_ltx_video":            "LTX i2v / t2v — 25-121 frames @ 25fps (distilled or full)",
    "build_seedvr2_video_upscale":"SeedVR2 upscale — temporal-consistent video SR",
}


def build_prompt(studio_id: str, build_fns: list[str], ctx: dict[str, Any]) -> str:
    """Produce the dynamic system prompt for a studio wizard.

    `studio_id` is the full char id (e.g. "studio_imaginus"); we strip the
    prefix to look up STUDIO_META. `build_fns` is the full hardcoded list
    from STUDIO_CHARACTERS — this function filters it by ctx capabilities.
    """
    key = studio_id.replace("studio_", "")
    meta = STUDIO_META.get(key, {
        "name": studio_id.replace("studio_", "").title(),
        "role": "a Guild wizard",
        "focus": "a unique specialty",
    })

    archs = set(ctx.get("archs") or [])
    avail, blocked = _available_tools(build_fns, ctx)
    apps = _connected_apps_for_studio(key, ctx)
    lora_count = ctx.get("lora_count", 0) or 0
    personality = ctx.get("personality", "")

    # ── Tools block ────────────────────────────────────────────────
    tool_lines = []
    for i, fn in enumerate(avail, 1):
        tool_lines.append(_tool_display_line(fn, TOOL_DESC, i))

    app_lines = []
    next_idx = len(avail) + 1
    for app in apps:
        app_lines.append(
            f"{next_idx}. **{app['label']}** — {app['desc']}"
        )
        next_idx += 1

    # Friendly arch list
    arch_line = _fmt_arch_list(archs) if archs else "(no image models detected — the user has nothing installed on ComfyUI yet)"

    # ── Blocked tools — tell the LLM why it can't offer them ───────
    blocked_block = ""
    if blocked:
        reasons = []
        for fn in blocked:
            req = TOOL_REQS.get(fn, {})
            archs_req = req.get("archs") or set()
            nodes_req = req.get("nodes") or set()
            missing_archs = archs_req - archs
            missing_nodes = nodes_req - set(ctx.get("node_classes") or [])
            why = []
            if missing_archs:
                why.append(f"arch missing: {', '.join(sorted(missing_archs))}")
            if missing_nodes:
                why.append(f"node missing: {', '.join(sorted(missing_nodes))}")
            reasons.append(f"  - {fn}: {' · '.join(why) or 'unknown'}")
        blocked_block = (
            "\nTOOLS NOT AVAILABLE (do not offer these — the ComfyUI server is missing "
            "the required models/nodes. Tell the user to install what's missing via "
            "the Spellcaster wizard if they ask for one of these):\n"
            + "\n".join(reasons)
        )

    # ── Antenna / connected-app status ─────────────────────────────
    antenna_block = _fmt_antennas(ctx)

    personality_block = ""
    if personality:
        personality_block = f"\nYOUR PERSONALITY: {personality}\n"

    # ── LoRA block ─────────────────────────────────────────────────
    lora_block = ""
    if lora_count:
        lora_block = (f"\nLoRAs available to you: {lora_count} compatible adapters. "
                      "Suggest activating one when the user's request matches its purpose.")

    # ── Assemble ───────────────────────────────────────────────────
    tools_block = "\n".join(tool_lines) if tool_lines else "  (none — this wizard is conversational only)"
    apps_block_str = ("\nCONNECTED APPS (these are live right now — offer them "
                      "as follow-up actions when they fit the user's goal):\n"
                      + "\n".join(app_lines)) if app_lines else ""

    return f"""You are {meta['name']}, {meta['role']}.
Focus: {meta['focus']}.
{personality_block}
LIVE INSTALL STATE (the Guild probes this every turn — tailor your offers to it):
  ComfyUI reachable:     {"yes" if ctx.get("comfyui_reachable") else "NO"}
  Installed image archs: {arch_line}
  Antennas:
{antenna_block}
{lora_block}

YOUR TOOLS ({len(avail) + len(apps)} total — {len(avail)} Spellcaster + {len(apps)} connected apps):
{tools_block}{apps_block_str}
{blocked_block}

PROTOCOL:
- Greet the user in character and ask what they want to do.
- Suggest the numbered tool that fits. If they want something not in the list,
  either point at a compatible tool or explain the missing install (see blocked list).
- Collect parameters conversationally in plain English — NEVER make the user write
  quality tags, negatives, weights, or engineering syntax. YOU handle that silently
  based on the arch of the model they (implicitly) pick.
- Connected-app actions are follow-ups: first generate, then offer to ship the
  result to GIMP / Darktable / Resolve / SillyTavern / Signal if the app is live.
- When ready to dispatch, output a JSON block:
  ```json
  {{"build_fn": "<fn>", "params": {{...}}}}
  ```
"""
