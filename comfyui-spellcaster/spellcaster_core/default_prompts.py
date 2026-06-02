"""Default prompt templates for the Krita Spellcaster plugin.

When the user picks a tool from the Spellcaster menu the QInputDialog
pre-fills with a sensible starter prompt drawn from this module
instead of an empty field. The user edits the template before
submitting — saves typing the same boilerplate every time.

Templates here intentionally avoid subject specifics (no "woman in
red dress") and focus on STYLE / COMPOSITION / QUALITY / OPERATION
intent. The user supplies the subject. Bracketed placeholders like
[describe the subject] signal where to insert specifics.

The dict is keyed by the same op key the Krita plugin uses internally
(== method name on the KritaSpellcaster class). default_for(op) is the
single lookup point; unknown ops fall back to an empty string.
"""
from __future__ import annotations


# Ops where the prompt template is non-trivial (>80 chars) get rendered
# in a multi-line QInputDialog so the user can see the whole template
# while editing. Short tag-style defaults stay single-line.

DEFAULT_PROMPTS: dict[str, str] = {
    # ───── Generic generate / edit ─────────────────────────────────
    "txt2img": (
        "masterpiece, best quality, highly detailed, professional "
        "composition, sharp focus, [describe your scene]"
    ),
    "auto": (
        "[describe your scene — Spellcaster will pick the right model "
        "and quality tags automatically]"
    ),
    "img2img": (
        "enhance this image, refined detail, improved composition, "
        "professional quality, sharper focus, [optional: style hint]"
    ),
    "inpaint": (
        "anatomically correct, matching surrounding lighting and tone, "
        "seamless integration, [describe what should fill the selection]"
    ),
    "outpaint": (
        "extending the scene naturally, matching existing composition "
        "and lighting, consistent perspective, photorealistic"
    ),
    "iclight": (
        "natural soft directional light from upper left, gentle "
        "shadows, photorealistic relighting, preserved subject"
    ),
    "normal_map": "",  # no prompt
    "upscale": "",
    "rembg": "",
    "face_restore": "",
    "detail_hallucinate": (
        "highly detailed texture, sharp focus, fine details, "
        "professional rendering, crisp edges"
    ),
    "colorize": (
        "natural colors, warm midtones, photographic color grading, "
        "film stock palette, gentle saturation"
    ),
    "magic_eraser": (
        "[name the object to remove — e.g. power line, tourist, "
        "watermark, distracting object]"
    ),
    "style_transfer": (
        "matching the style of the reference image, preserved subject "
        "and composition, seamless style transfer"
    ),
    "style_transfer_from_bytes": (
        "matching the style of the reference image, preserved subject "
        "and composition, seamless style transfer"
    ),

    # ───── Klein 4B family (Flux 2 distilled — natural language) ───
    "klein_img2img": (
        "enhance this image, maintain subject and composition, "
        "improved detail and texture, photorealistic refinement"
    ),
    "klein_refine": (
        "sharper detail, finer skin texture, anatomically correct, "
        "photorealistic refinement, crisp focus on key features"
    ),
    "klein_repose": (
        "natural relaxed pose, full body visible, anatomically "
        "correct proportions, balanced composition"
    ),
    "klein_face_detail": (
        "beautiful detailed face, symmetric features, clear sharp "
        "eyes with catchlights, natural skin texture, defined "
        "lashes, photorealistic"
    ),
    "klein_batch_variations": (
        "varied poses and expressions, consistent subject identity, "
        "professional editorial photography, different angles"
    ),
    "photobooth": (
        "professional passport-style portrait, neutral expression, "
        "plain studio backdrop, soft natural light, photorealistic, "
        "sharp focus on eyes"
    ),
    "klein_virtual_tryon": (
        "wearing this outfit, natural fit on body, matching pose and "
        "lighting, realistic fabric drape and shadow"
    ),
    "klein_color_match": "",  # no prompt — uses reference bytes
    "klein_headswap": "",     # no prompt — uses face bytes
    "klein_blend": (
        "seamless composite, matching lighting and color tones, "
        "natural integration, consistent perspective and shadow"
    ),
    "klein_scene_img2img": (
        "transform this scene, atmospheric depth, professional "
        "cinematography, improved lighting, enhanced detail"
    ),
    "klein_generate_object": (
        "[describe the object], professional product photography, "
        "clean studio backdrop, detailed texture, sharp focus, "
        "soft three-point lighting"
    ),
    "klein_detail": (
        "highly detailed skin texture, visible pores, natural skin "
        "tone, sharp focus on key features, photographic realism"
    ),
    "klein_img2img_ref": (
        "matching the reference style and composition, [describe "
        "transformation], maintained subject identity"
    ),
    "klein_inpaint": (
        "anatomically correct, matching surrounding lighting and "
        "skin tone, seamless integration, photorealistic"
    ),
    # klein_auto_inpaint takes TWO prompts; expose both via dotted keys.
    "klein_auto_inpaint.mask": (
        "[the object/area in the canvas to replace — e.g. 'shirt', "
        "'background', 'hat']"
    ),
    "klein_auto_inpaint.fill": (
        "[describe what should appear in the masked area], "
        "anatomically correct, matching scene lighting"
    ),
    "klein_sam3_inpaint.segment": (
        "[area to segment via SAM3 — e.g. 'person', 'sky', 'face']"
    ),
    "klein_sam3_inpaint.fill": (
        "[describe the new content for the segmented region], "
        "matching scene lighting and perspective"
    ),

    # ───── Face / identity ─────────────────────────────────────────
    "pulid_flux": (
        "professional portrait photograph of this person, soft "
        "natural lighting, detailed skin texture, sharp focus on "
        "eyes with catchlights, photorealistic, 85mm lens"
    ),
    "faceid_img2img": (
        "transform this image to match the face reference, "
        "maintaining identity, natural skin tones, consistent "
        "lighting"
    ),

    # ───── Segmentation / extraction ───────────────────────────────
    "sam3_segment": "face",
    "sam3_extract": "person",

    # ───── Qwen / SUPIR ────────────────────────────────────────────
    "qwen_edit": (
        "remove distracting background elements, enhance the main "
        "subject, improve overall composition"
    ),
    "supir_upscale": (
        "highly detailed, sharp focus, photorealistic, high "
        "resolution, crisp textures, no compression artifacts"
    ),
    "seedv2r_upscale": (
        "highly detailed, sharp focus, photorealistic upscale, "
        "preserved detail"
    ),

    # ───── Video ───────────────────────────────────────────────────
    "ltx_t2v": (
        "smooth cinematic motion, natural movement, professional "
        "cinematography, gentle camera flow, [describe the scene]"
    ),
    "ltx_i2v": (
        "smooth subtle motion of the subject, gentle camera "
        "movement, cinematic atmosphere"
    ),
    "wan_i2v": (
        "natural smooth motion, cinematic quality, fluid movement, "
        "consistent lighting and composition"
    ),
    "wan22_t2v": (
        "smooth cinematic motion, natural fluid movement, professional "
        "cinematography, gentle camera work, [describe the scene]"
    ),
    "wan_animate": (
        "smooth natural animation, fluid character motion, consistent "
        "lighting and style, [describe the action]"
    ),
    "hunyuan_video": (
        "cinematic video, smooth motion, high production value, "
        "professional cinematography, [describe the scene]"
    ),
    "mochi_video": (
        "smooth cinematic motion, high-quality video, natural camera "
        "movement, [describe the scene]"
    ),
    "cogvideo_video": (
        "smooth cinematic motion, natural movement, professional "
        "video production, [describe the scene]"
    ),
    "framepack_video": (
        "smooth motion derived from canvas, natural camera flow, "
        "cinematic quality, [describe how the canvas should move]"
    ),

    # ───── Lumina 2 (natural-language DiT model) ───────────────────
    "lumina2_txt2img": (
        "a detailed scene, cinematic composition, sharp focus, "
        "professional photography, soft natural lighting"
    ),

    # ───── Face model lookup (NOT a prompt — uses prompt field
    # to receive the saved-model name; the docker exposes this as
    # needs_prompt=True so the user has somewhere to type the name)
    "faceswap_from_model": (
        "[name of a previously-saved face model]"
    ),

    # ───── Restoration / advanced inpaint ──────────────────────────
    "photo_restore": "",  # no prompt -- pure quality restoration pipeline
    "inpaint_fooocus": (
        "high quality inpaint, matching surrounding context, seamless "
        "integration, detailed texture, photorealistic"
    ),
    "video_upscale": "",  # no prompt -- upscale only
}


def default_for(op_key: str) -> str:
    """Return the ideal-prompt template for an op key.

    Unknown keys return ``""`` so callers can safely use::

        prompt = default_for("some_op") or ""
    """
    return DEFAULT_PROMPTS.get(op_key, "")
