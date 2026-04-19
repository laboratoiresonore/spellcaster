"""ComfyUI Workflow Builders using NodeFactory Pattern.

This module contains all workflow construction functions for Spellcaster. Each function
builds a complete ComfyUI node graph (workflow) and returns it as a JSON-serializable dict.

ARCHITECTURE OVERVIEW
═════════════════════
ComfyUI operates via a node graph: nodes are connected by referencing outputs.
A workflow is represented as:
    {
        "1": {"class_type": "CheckpointLoader", "inputs": {"ckpt_name": "model.safetensors"}},
        "2": {"class_type": "CLIPEncode", "inputs": {"clip": ["1", 1], "text": "a cat"}},
        ...
    }

Each node has:
  - class_type: The ComfyUI node class (e.g., "KSampler", "VAEDecode")
  - inputs: A dict of input parameters
    - Scalar values (strings, numbers): passed as-is
    - References to other node outputs: [node_id, output_index] lists

THE NODEFACTORY PATTERN
═══════════════════════
All workflows are built using NodeFactory (from _nodes.py):
    nf = NodeFactory()
    ckpt_id = nf.checkpoint_loader("model.safetensors", node_id="1")
    clip_id = nf.clip_loader("clip.safetensors", node_id="2")
    pos_id = nf.clip_encode(_ref(clip_id), "a beautiful photo", node_id="3")
    workflow = nf.build()  # Returns the node dict

Benefits:
  - NodeFactory.build() returns the final node dict
  - Each nf.some_node(...) returns its string ID for referencing
  - References are [id, output_index] lists
  - node_id= parameter pins specific numeric IDs (needed for ControlNet injection, etc.)
  - Auto-incrementing IDs when node_id= is not specified
  - patch_input() modifies existing node inputs (used for ControlNet redirection)

COMMON PATTERNS
═══════════════
1. MODEL LOADING (load_model_stack composite):
   - CheckpointLoader: loads model + clip + vae from a single .safetensors file
   - Outputs: [0]=MODEL, [1]=CLIP, [2]=VAE
   - For Flux models: separate UNETLoader + CLIPLoader + VAELoader

2. TEXT ENCODING (CLIP encode → conditioning):
   - clip_encode(): TEXT → CONDITIONING
   - Takes CLIP and text prompt, returns CONDITIONING output
   - Used for both positive and negative prompts

3. IMAGE ENCODING (VAE encode):
   - load_image(): filename → IMAGE
   - vae_encode(): IMAGE → LATENT (compressed representation for diffusion)
   - Used before sampling in img2img workflows

4. SAMPLING (the core diffusion step):
   - ksampler(): MODEL + CONDITIONING + LATENT → LATENT
   - Takes: model, positive conditioning, negative conditioning, latent seed, steps, CFG
   - Returns: modified latent ready for decoding

5. IMAGE DECODING (VAE decode):
   - vae_decode(): LATENT → IMAGE
   - Converts compressed latent back to image pixels
   - Always follows sampling

6. SAVING:
   - save_image(): IMAGE + folder_name → saves to disk
   - Last step in most workflows

7. CONTROLNET INJECTION:
   - inject_controlnet(): adds spatial guidance to conditioning
   - Preprocesses input image with a control method (canny, depth, pose, etc.)
   - Creates ControlNet conditioning paired with text conditioning
   - Patches the sampler's positive/negative inputs to use ControlNet conditioning

ARCHITECTURE-AWARE LOADING
═══════════════════════════
The load_model_stack() composite (from _composites.py) handles architecture differences:
  - "sdxl": Uses SDXL checkpoint (unet + clip + vae in one file)
  - "flux": Uses Flux unet + dual CLIP (clip_l + t5xxl) + flux2-vae
  - "klein": Uses Flux2 Klein (9B/4B variants) with specific CLIP pairing:
    * Klein 9B → qwen_3_8b.safetensors
    * Klein 4B → qwen_3_4b.safetensors

LoRA INJECTION
═════════════
inject_lora_chain() stacks multiple LoRAs:
  - Each LoRA is applied to both model and clip
  - Chains them: lora1 → lora2 → lora3 → sampler
  - Earlier LoRAs have full strength, later ones can override

KLEIN (FLUX2 DISTILLED) SPECIFICS
═════════════════════════════════
Klein is a 4B/9B parameter distilled Flux2 model. Key differences:
  - Uses separate UNETLoader (not CheckpointLoader)
  - Must use matching CLIP: 9B needs qwen_3_8b, 4B needs qwen_3_4b
  - Uses flux2-vae for decoding
  - Reference Latent wrapping: latent outputs wrapped in conditioning for guidance
  - Custom scheduler: flux2_scheduler() instead of standard scheduler
  - Custom sampler: sampler_custom_advanced() for precise Flux2 control

See Klein Config in project memory for VAE/CLIP pairings.

AVAILABLE WORKFLOWS
═══════════════════
Core Diffusion:
  - build_img2img(): Image-to-image generation (load image → encode → sample → decode)
  - build_txt2img(): Text-to-image (empty latent → sample → decode)
  - build_inpaint(): Regenerate masked region only
  - build_outpaint(): Extend canvas with new content

Face & Body:
  - build_faceswap(): ReActor face swap + optional CodeFormer restoration
  - build_faceswap_model(): Train a new face swap model
  - build_faceswap_mtb(): MTB face swap variant
  - build_face_restore(): CodeFormer face restoration
  - build_faceid_img2img(): Use face ID embedding for consistency
  - build_pulid_flux(): PuLID face ID with Flux
  - build_klein_headswap(): Head swap with Klein Flux2

Image Enhancement:
  - build_upscale(): Super-resolution upscaling
  - build_photo_restore(): Combine upscale + face restore
  - build_supir(): SUPIR AI restoration (5-stage pipeline)
  - build_detail_hallucinate(): Super-resolution with detail enhancement
  - build_rembg(): Background removal (no diffusion)
  - build_lama_remove(): Object removal via LaMa inpainting

Lighting & Rendering:
  - build_iclight(): IC-Light relighting (reposition light sources)
  - build_klein_repose(): Pose + composition adjustment with Klein

Styling & Color:
  - build_colorize(): Colorize greyscale images with Klein
  - build_lut(): Apply color grading LUT (Look-Up Table)
  - build_style_transfer(): Transfer style from reference image

Reference-Based:
  - build_klein_img2img_ref(): Klein with reference image guidance
  - build_klein_inpaint(): Klein inpainting with reference
  - build_klein_scene_img2img(): Klein with scene semantics
  - build_klein_blend(): Blend foreground (generated) with background

ControlNet & Guidance:
  - build_controlnet_gen(): Generate ControlNet guidance map from image

Video:
  - build_wan_video(): WAN frame-by-frame video generation
  - build_wan_flf(): WAN first-last-frame video (semantic interpolation)
  - build_video_upscale(): Upscale video frame-by-frame
  - build_video_reactor(): Face swap on every video frame
  - build_seedvr2_video_upscale(): SeedVR2 temporal upscaling
  - build_seedv2r(): SeedVR temporal consistency

Composition:
  - build_frame_assembly(): Assemble frames into video
  - build_layer_blend(): Blend two images with opacity
  - build_upscale_blend(): Blend two different upscalers
  - build_photobooth(): Iterative generation with previous frame reference

MIGRATION NOTES
═══════════════
This file is built on the NodeFactory architecture. Earlier versions used raw
dicts. The pattern here:
  1. Load models via load_model_stack() composite
  2. Apply LoRAs via inject_lora_chain()
  3. Encode text via encode_prompts()
  4. Optionally inject ControlNet
  5. Sample via ksampler()
  6. Decode and save

All original _build_* functions have been migrated to this pattern for consistency
and maintainability.
"""

def _ref(var, slot=0):
    """Normalize a node reference to [node_id, slot] format.

    Handles both raw strings from loaders (e.g. "2") and full refs
    from LoRA chains (e.g. ["100", 1]).  After inject_lora_chain(),
    unet_id is ["100", 0] and clip_id is ["100", 1].  This helper
    ensures [_ref(clip_id, 0)] never produces nested lists.
    """
    if isinstance(var, list):
        return var  # already [node_id, slot] — use as-is
    return [var, slot]


try:
    # When running as part of spellcaster_core package (CLI, ComfyUI nodes)
    from .node_factory import NodeFactory
    from .architectures import ARCHITECTURES, get_arch
    from .composites import (
        load_model_stack, inject_lora_chain, encode_prompts,
        sample_standard, sample_klein_img2img,
        inject_controlnet, inject_controlnet_pair,
        build_sam3_mask, apply_sam3_scope,
    )
except ImportError:
    # Fallback: when running from GIMP plugin directory (shim imports via _nodes etc.)
    from _nodes import NodeFactory
    from _architectures import ARCHITECTURES, get_arch
    from _composites import (
        load_model_stack, inject_lora_chain, encode_prompts,
        sample_standard, sample_klein_img2img,
        inject_controlnet, inject_controlnet_pair,
        build_sam3_mask, apply_sam3_scope,
    )


# ═══════════════════════════════════════════════════════════════════════════
#  SHARED CONSTANTS — Single source of truth for Klein / Flux2 / Studio
# ═══════════════════════════════════════════════════════════════════════════

# ── Camera / cinematography presets ────────────────────────────────────
# Shared between GIMP plugin (repose dialog) and Wizard Guild (LLM
# system prompt). Each preset is a prompt fragment that works with any
# architecture — the model interprets the description as a composition
# directive. Organized by cinematic discipline.

CAMERA_SHOT_PRESETS = {
    "extreme_closeup": "extreme close-up shot, only the eyes visible, macro skin texture, shallow DOF",
    "closeup":         "close-up shot, face fills frame, 85mm lens, shallow depth of field",
    "medium_closeup":  "medium close-up, head and shoulders, portrait framing, 50mm lens",
    "medium":          "medium shot, waist up, conversational framing",
    "full":            "full body shot, entire figure head to toe",
    "wide":            "wide shot, full body with environment, establishing context",
    "extreme_wide":    "extreme wide shot, tiny figure in vast landscape, epic scale",
}

CAMERA_ANGLE_PRESETS = {
    "eye_level":       "shot at eye level, neutral perspective",
    "low_angle":       "shot from low angle looking up, heroic perspective",
    "extreme_low":     "extreme low angle worm's eye view, camera near ground looking straight up",
    "high_angle":      "shot from high angle looking down, diminutive perspective",
    "birds_eye":       "bird's eye view, camera directly overhead, top-down",
    "dutch":           "dutch angle shot, 15-25 degree tilt, dramatic tension",
    "over_shoulder":   "over the shoulder shot, depth composition",
}

CAMERA_LENS_PRESETS = {
    "wide_24mm":       "wide angle 24mm lens, spacious, slight barrel distortion",
    "normal_50mm":     "50mm lens, natural perspective, no distortion",
    "portrait_85mm":   "85mm portrait lens, shallow DOF, background separation",
    "telephoto_200mm": "telephoto 200mm lens, compressed depth, bokeh background",
    "anamorphic":      "anamorphic lens, horizontal flares, oval bokeh, cinematic widescreen",
    "macro":           "macro photography, extreme detail, razor-thin DOF",
    "tilt_shift":      "tilt-shift, selective focus, miniature diorama effect",
    "fisheye":         "fish-eye lens, spherical distortion, 180 degree FOV",
}

CAMERA_MOVE_PRESETS = {
    "dolly_in":        "camera dollying in toward subject, approaching intimacy",
    "dolly_out":       "camera pulling back, widening reveal",
    "truck_left":      "camera tracking laterally left, smooth panning",
    "truck_right":     "camera tracking laterally right, smooth panning",
    "pedestal_up":     "camera rising vertically, ascending perspective",
    "pedestal_down":   "camera lowering, descending to subject level",
    "crane":           "elevated crane shot, sweeping overhead, cinematic grandeur",
    "tracking_follow": "steadicam tracking from behind, immersive follow",
}

CAMERA_COMPOSITION_PRESETS = {
    "rule_of_thirds":  "rule of thirds, subject off-center at power point",
    "center_frame":    "subject centered, symmetrical, direct confrontational",
    "negative_space":  "extensive negative space, subject small, minimalist",
    "frame_in_frame":  "frame within a frame, viewed through doorway or arch",
    "leading_lines":   "strong leading lines converging on subject",
    "symmetrical":     "perfectly symmetrical, mirror composition, Kubrick-style",
}


KLEIN_MODELS = {
    "Klein 9B": {
        "unet": "A-Flux\\Flux2\\flux-2-klein-9b.safetensors",
        "clip": "qwen_3_8b.safetensors",
    },
    "Klein 4B": {
        "unet": "A-Flux\\flux-2-klein-4b-fp8.safetensors",
        "clip": "qwen_3_4b.safetensors",
    },
    "Klein Base 4B": {
        "unet": "A-Flux\\flux-2-klein-base-4b-fp8.safetensors",
        "clip": "qwen_3_4b.safetensors",
    },
}

FLUX2_VAE = "flux2-vae.safetensors"

# ── Studio Canvas — canonical dimensions for the Magic Studio pipeline ──
# All stages generate at these sizes so compositing has a shared spatial
# reference.  Dimensions are multiples of 16 and ≈1 MP each.
STUDIO_FACE_W, STUDIO_FACE_H = 896, 1152    # portrait ratio — optimized for faces
STUDIO_BODY_W, STUDIO_BODY_H = 768, 1152    # 2:3 portrait — full-body
STUDIO_SCENE_W, STUDIO_SCENE_H = 1152, 768  # 3:2 landscape — scene backdrops

# Derived: default foreground_scale when placing a body PNG into a scene.
# The body should fill ~85% of the scene height.
STUDIO_BODY_IN_SCENE_SCALE = round((STUDIO_SCENE_H * 0.85) / STUDIO_BODY_H, 3)


# ═══════════════════════════════════════════════════════════════════════════
#  img2img — Standard image-to-image generation
# ═══════════════════════════════════════════════════════════════════════════

def build_img2img(image_filename, preset, prompt_text, negative_text, seed,
                  loras=None, controlnet=None, controlnet_2=None,
                  guide_modes=None,
                  # SAM3 scoping — when sam3_prompt is set, the transform is
                  # composited back onto the original image using a SAM3 mask,
                  # so only the described region visibly changes. Requires
                  # SAM3Segment on the server (preflight at the caller side).
                  sam3_prompt=None, sam3_invert=False, sam3_confidence=0.6,
                  sam3_expand=4, sam3_blur=4):
    """Image-to-image generation (standard diffusion variant).

    Loads an input image, encodes it to latent space, diffuses it with a prompt,
    and decodes back to image space. Respects denoise parameter (0.0 = no change,
    1.0 = full regeneration).

    Pipeline:
      1. Load model, CLIP, VAE (architecture-aware via preset)
      2. Apply LoRA chain if provided
      3. Load input image and encode to latent
      4. Encode positive and negative prompts
      5. Run KSampler with configured denoise/cfg/steps
      6. Decode latent to image
      7. Save to disk
      8. Optionally inject ControlNet(s) for spatial guidance

    Args:
        image_filename (str): Path to input image file.
        preset (dict): Sampling preset containing:
          - arch: "sdxl", "flux", or "klein" (default "sdxl")
          - width, height: Output dimensions
          - steps: Diffusion steps (int)
          - cfg: Classifier-free guidance scale (float, typically 7.0-15.0)
          - sampler: Sampler type, e.g. "euler", "dpmpp_2m" (default "euler")
          - scheduler: Noise scheduler, e.g. "normal", "karras" (default "normal")
          - denoise: Denoising strength 0.0-1.0 (default 0.65)
        prompt_text (str): Positive prompt describing desired output
        negative_text (str): Negative prompt (things to avoid)
        seed (int): Random seed for reproducibility
        loras (list, optional): List of LoRA dicts: [{"name": "...", "strength": 1.0}, ...]
        controlnet (dict, optional): First ControlNet config:
          {"mode": "canny"|"depth"|"pose"|..., "strength": 1.0}
        controlnet_2 (dict, optional): Second ControlNet (chains from first if present)
        guide_modes (dict, optional): Maps control mode names to preprocessor info

    Returns:
        dict: ComfyUI workflow node graph ready for submission.

    Node IDs Reference:
      - "1": model/clip/vae loaders
      - "2","3": positive/negative conditioning
      - "4": input image
      - "5": VAE encode
      - "6": KSampler (the main diffusion step)
      - "7": VAE decode
      - "8": save_image
      - "20","30": ControlNet(s) if used
      - "22": First CN conditioning output (if CN1 present, CN2 chains from this)

    Gotchas:
      - denoise < 1.0 means preservation of input image structure
      - cfg > 20 may cause artifacts or distortion
      - ControlNet requires matching architecture preprocessor
      - Second ControlNet chains from first's output if both present
    """
    nf = NodeFactory()

    # 1. Load model stack (architecture-aware)
    model_ref, clip_ref, vae_ref = load_model_stack(nf, preset, "1")

    # 2. LoRA chain
    model_ref, clip_ref, _trig = inject_lora_chain(nf, loras or [], model_ref, clip_ref)

    # 3. Load image
    img_id = nf.load_image(image_filename, node_id="4")
    img_ref = [img_id, 0]

    # 4. Mod-16 scaling for Flux ControlNet (if needed)
    arch_key = preset.get("arch", "sdxl")
    # NOTE: _ensure_mod16 needs Python-side dimension computation,
    # so we preserve the original pattern for now. This will be refactored
    # in Phase 3 when image dimension helpers are ported.

    # 5. Encode prompts
    pos_id, neg_id = encode_prompts(nf, arch_key, clip_ref,
                                     prompt_text, negative_text,
                                     pos_id="2", neg_id="3")

    # 6. VAE encode → sample → VAE decode → save
    enc_id = nf.vae_encode(img_ref, vae_ref, node_id="5")
    is_klein = arch_key == "flux2klein"
    if is_klein:
        ref_pos = nf.reference_latent([pos_id, 0], [enc_id, 0], node_id="60")
        ref_neg = nf.reference_latent([neg_id, 0], [enc_id, 0], node_id="61")
        guider_id = nf.cfg_guider(model_ref, [ref_pos, 0], [ref_neg, 0],
                                  preset.get("cfg", 1.0), node_id="62")
        sampler_sel = nf.ksampler_select("euler", node_id="63")
        sched_id = nf.basic_scheduler(model_ref, preset.get("steps", 20),
                                       preset.get("denoise", 0.65),
                                       scheduler="simple", node_id="64")
        noise_id = nf.random_noise(seed, node_id="65")
        samp_id = nf.sampler_custom_advanced(
            [noise_id, 0], [guider_id, 0], [sampler_sel, 0],
            [sched_id, 0], [enc_id, 0], node_id="6",
        )
    else:
        samp_id = nf.ksampler(
            model_ref,
            [pos_id, 0], [neg_id, 0], [enc_id, 0],
            seed, preset["steps"], preset["cfg"],
            preset.get("sampler", "euler"), preset.get("scheduler", "normal"),
            preset.get("denoise", 0.65),
            node_id="6",
        )
    dec_id = nf.vae_decode([samp_id, 0], vae_ref, node_id="7")
    # Optional SAM3 scoping — gate the transform with a SAM3 mask so only
    # the described region is visibly altered in the final save.
    final_ref = [dec_id, 0]
    if sam3_prompt:
        _mask = build_sam3_mask(nf, img_ref, sam3_prompt,
                                 invert=sam3_invert,
                                 confidence=sam3_confidence,
                                 mask_expand=sam3_expand,
                                 mask_blur=sam3_blur)
        final_ref = apply_sam3_scope(nf, final_ref, img_ref, _mask)
    nf.save_image(final_ref, "gimp_comfy", node_id="8")

    # 7. ControlNet injection (optional)
    # ControlNet adds spatial constraints to the diffusion process. It:
    #   1. Preprocesses the input image with a specific method (canny edges, depth map, pose, etc.)
    #   2. Loads a ControlNet model trained on that preprocessor output
    #   3. Creates conditioning that pairs with text conditioning
    #   4. Redirects the KSampler's positive/negative inputs to use the ControlNet conditioning
    # This constrains generation to follow the spatial structure while respecting the prompt.
    if guide_modes and controlnet and controlnet.get("mode", "Off") != "Off":
        # Inject first ControlNet: preprocesses img_ref and creates CN-augmented conditioning
        cn_pos, cn_neg = inject_controlnet(
            nf, controlnet, guide_modes, arch_key, img_ref,
            [pos_id, 0], [neg_id, 0], cn_base_id=20,
        )
        # Patch the KSampler node (node "6") to use CN-augmented conditioning instead of raw CLIP
        nf.patch_input("6", "positive", cn_pos)
        nf.patch_input("6", "negative", cn_neg)

    if guide_modes and controlnet_2 and controlnet_2.get("mode", "Off") != "Off":
        # Second ControlNet chains from first's output if CN1 is present.
        # This allows stacking multiple spatial constraints (e.g., canny edges + depth map).
        # If CN1 present: use its output conditioning as base for CN2
        # If CN1 absent: fall back to raw text conditioning
        prev_pos = [str(22), 0] if nf.has_node("22") else [pos_id, 0]
        prev_neg = [str(22), 1] if nf.has_node("22") else [neg_id, 0]
        cn2_pos, cn2_neg = inject_controlnet(
            nf, controlnet_2, guide_modes, arch_key, [img_id, 0],
            prev_pos, prev_neg, cn_base_id=30,
        )
        # Update KSampler to use CN2 output (which already includes CN1 if both present)
        nf.patch_input("6", "positive", cn2_pos)
        nf.patch_input("6", "negative", cn2_neg)

    return nf.build()


# ═══════════════════════════════════════════════════════════════════════════
#  txt2img — Text-to-image generation
# ═══════════════════════════════════════════════════════════════════════════

def build_txt2img(preset, prompt_text, negative_text, seed, loras=None):
    """Text-to-image generation (from scratch).

    Generates an image entirely from a text prompt by starting with an empty
    (random noise) latent and diffusing it. Denoise is always 1.0 (full generation).

    Pipeline:
      1. Load model, CLIP, VAE
      2. Apply LoRA chain if provided
      3. Encode positive and negative prompts
      4. Create empty latent at target dimensions
      5. Run KSampler starting from noise
      6. Decode to image and save

    Args:
        preset (dict): Sampling preset containing:
          - arch: "sdxl", "flux", or "klein" (default "sdxl")
          - width, height: Output dimensions
          - steps: Diffusion steps (int)
          - cfg: Classifier-free guidance scale (float)
          - sampler: Sampler type, e.g. "euler", "dpmpp_2m" (default "euler")
          - scheduler: Noise scheduler, e.g. "normal", "karras" (default "normal")
        prompt_text (str): Main description of desired image
        negative_text (str): What to avoid in the image
        seed (int): Random seed for reproducibility
        loras (list, optional): List of LoRA dicts to apply

    Returns:
        dict: ComfyUI workflow node graph.

    Note:
      - No input image, so denoise is always 1.0
      - Output dimensions must be specified in preset (width, height)
      - Takes longer than img2img due to generating from scratch
    """
    nf = NodeFactory()

    model_ref, clip_ref, vae_ref = load_model_stack(nf, preset, "1")
    model_ref, clip_ref, _trig = inject_lora_chain(nf, loras or [], model_ref, clip_ref)

    pos_id, neg_id = encode_prompts(nf, preset.get("arch", "sdxl"), clip_ref,
                                     prompt_text, negative_text,
                                     pos_id="2", neg_id="3")

    empty_id = nf.empty_latent_image(preset["width"], preset["height"],
                                      batch_size=1, node_id="4")

    is_klein = preset.get("arch") == "flux2klein"
    if is_klein:
        guider_id = nf.cfg_guider(model_ref, [pos_id, 0], [neg_id, 0],
                                  preset.get("cfg", 1.0), node_id="60")
        sampler_sel = nf.ksampler_select("euler", node_id="61")
        sched_id = nf.basic_scheduler(model_ref, preset.get("steps", 20),
                                       1.0, scheduler="simple", node_id="62")
        noise_id = nf.random_noise(seed, node_id="63")
        samp_id = nf.sampler_custom_advanced(
            [noise_id, 0], [guider_id, 0], [sampler_sel, 0],
            [sched_id, 0], [empty_id, 0], node_id="5",
        )
    else:
        samp_id = nf.ksampler(
            model_ref,
            [pos_id, 0], [neg_id, 0], [empty_id, 0],
            seed, preset["steps"], preset["cfg"],
            preset.get("sampler", "euler"), preset.get("scheduler", "normal"),
            1.0,  # denoise always 1.0 for txt2img
            node_id="5",
        )
    dec_id = nf.vae_decode([samp_id, 0], vae_ref, node_id="6")
    nf.save_image([dec_id, 0], "gimp_comfy", node_id="7")

    return nf.build()


# ═══════════════════════════════════════════════════════════════════════════
#  Generate Anything — any model → transparent object layer
# ═══════════════════════════════════════════════════════════════════════════

def build_generate_anything(prompt_text, negative_text, seed, preset,
                             loras=None, scene_filename=None):
    """Generate any object/person as a transparent layer using ANY model.

    Architecture-universal version of Klein Generate Object. Works with
    SDXL, SD1.5, Illustrious, Flux Dev, Klein, Kontext — any model.

    Pipeline:
      1. txt2img with "on plain white background" appended for clean cutout
      2. If scene_filename provided AND arch is Klein/Flux: use it as
         ReferenceLatent for lighting/style matching
      3. BiRefNet removes background → transparent PNG
      4. Two outputs: raw generation + transparent cutout

    For Klein: uses ReferenceLatent + Enhancer chain (max quality)
    For SDXL/SD15: uses standard KSampler with quality tokens
    For Flux Dev: uses KSampler with natural language prompt

    Args:
        prompt_text (str): What to generate (the object/person).
        negative_text (str): What to avoid.
        seed (int): Random seed.
        preset (dict): Model preset with arch, ckpt, steps, cfg, etc.
        loras (list): Optional LoRAs.
        scene_filename (str): Optional scene image for lighting reference
            (Klein/Flux only — SDXL ignores this).

    Returns:
        dict: ComfyUI workflow with two SaveImage outputs.
    """
    nf = NodeFactory()
    arch_key = preset.get("arch", "sdxl")

    # ── Model stack ──────────────────────────────────────────────────
    model_ref, clip_ref, vae_ref = load_model_stack(nf, preset, "1")
    model_ref, clip_ref, _trig = inject_lora_chain(nf, loras or [],
                                                     model_ref, clip_ref)

    # ── Prompt: append isolation instructions ────────────────────────
    _bg_instruction = (
        ", isolated on a plain solid white background, centered in frame, "
        "studio product photography, clean edges, professional lighting"
    )
    full_prompt = prompt_text + _bg_instruction

    # Architecture-specific negative
    arch = get_arch(arch_key)
    if arch.supports_negative:
        full_negative = (negative_text or "") + (
            ", busy background, clutter, multiple objects, watermark, text"
        )
    else:
        full_negative = ""

    # ── Encode prompts ───────────────────────────────────────────────
    pos_id, neg_id = encode_prompts(nf, arch_key, clip_ref,
                                     full_prompt, full_negative,
                                     pos_id="2", neg_id="3")

    # ── Klein enhancer chain ─────────────────────────────────────────
    if arch_key == "flux2klein":
        model_ref = _klein_enhance_model(nf, model_ref, [pos_id, 0])

    # ── Scene reference (Klein/Flux only) ────────────────────────────
    if scene_filename and arch_key in ("flux2klein", "flux1dev"):
        scene_id = nf.load_image(scene_filename, node_id="80")
        scene_scaled = nf.image_scale_to_total_pixels([scene_id, 0],
                                                        megapixels=1.0,
                                                        node_id="81")
        scene_enc = nf.vae_encode([scene_scaled, 0], vae_ref, node_id="82")
        # Wrap conditioning with scene reference for style matching
        ref_pos = nf.reference_latent([pos_id, 0], [scene_enc, 0], node_id="83")
        ref_neg = nf.reference_latent([neg_id, 0], [scene_enc, 0], node_id="84")
        pos_ref = [ref_pos, 0]
        neg_ref = [ref_neg, 0]
    else:
        pos_ref = [pos_id, 0]
        neg_ref = [neg_id, 0]

    # ── Empty latent ─────────────────────────────────────────────────
    empty_id = nf.empty_latent_image(preset["width"], preset["height"],
                                      batch_size=1, node_id="4")

    # ── Sample (architecture-aware) ──────────────────────────────────
    if arch_key == "flux2klein":
        guider_id = nf.cfg_guider(model_ref, pos_ref, neg_ref,
                                  preset.get("cfg", 1.0), node_id="60")
        sampler_sel = nf.ksampler_select("euler", node_id="61")
        sched_id = nf.basic_scheduler(model_ref, preset.get("steps", 6),
                                       1.0, scheduler="simple", node_id="62")
        noise_id = nf.random_noise(seed, node_id="63")
        samp_id = nf.sampler_custom_advanced(
            [noise_id, 0], [guider_id, 0], [sampler_sel, 0],
            [sched_id, 0], [empty_id, 0], node_id="5",
        )
    else:
        samp_id = nf.ksampler(
            model_ref, pos_ref, neg_ref, [empty_id, 0],
            seed, preset["steps"], preset["cfg"],
            preset.get("sampler", "euler"),
            preset.get("scheduler", "normal"),
            1.0, node_id="5",
        )

    dec_id = nf.vae_decode([samp_id, 0], vae_ref, node_id="6")
    nf.save_image([dec_id, 0], "generated_raw", node_id="7")

    # ── BiRefNet background removal → transparent cutout ─────────────
    rmbg_id = nf._add("BiRefNetRMBG", {
        "model": "BiRefNet-general",
        "mask_blur": 2,
        "mask_offset": 0,
        "invert_output": False,
        "refine_foreground": True,
        "background": "Alpha",
        "background_color": "#000000",
        "image": [dec_id, 0],
    }, node_id="50")
    nf.save_image([rmbg_id, 0], "generated_object", node_id="51")

    return nf.build()


# ═══════════════════════════════════════════════════════════════════════════
#  rembg — Background removal
# ═══════════════════════════════════════════════════════════════════════════

def build_rembg(image_filename, alpha_matting=False,
                model="isnet-general-use"):
    """Background removal (transparent cutout).

    Uses rembg (remove background) to extract subject from background, creating
    an alpha-channel image with transparent background.

    Pipeline:
      1. Load input image
      2. Apply rembg node (segments foreground from background)
      3. Save with transparency

    Args:
        image_filename (str): Path to input image
        alpha_matting (bool): Enable alpha matting for cleaner edges around
            hair and fine detail.  Slower but produces much better cutouts
            for portrait / full-body work.  Default False for back-compat.
        model (str): Rembg segmentation model.  Default "isnet-general-use".
            "u2net" is a lighter alternative.

    Returns:
        dict: ComfyUI workflow (simple 3-node graph: load → rembg → save)

    Note:
      - Does not use diffusion, purely segmentation-based
      - Fastest edge-removal option
      - Quality depends on image clarity and subject definition
    """
    nf = NodeFactory()
    img_id = nf.load_image(image_filename, node_id="1")
    rembg_id = nf.rembg([img_id, 0], model=model,
                         alpha_matting=alpha_matting, node_id="2")
    nf.save_image([rembg_id, 0], "spellcaster_rembg", node_id="3")
    return nf.build()


def build_rembg_birefnet(image_filename, model="BiRefNet-general"):
    """Background removal using BiRefNet (higher quality than rembg).

    BiRefNet produces significantly better results for hair, fur, and
    transparent/semi-transparent objects. Uses the ComfyUI-RMBG node pack.

    Models:
      - BiRefNet-general: best all-around (default)
      - BiRefNet-portrait: optimized for people
      - BiRefNet-HR: highest detail but may over-correct

    Returns:
        dict: ComfyUI workflow (load -> BiRefNetRMBG -> save)
    """
    nf = NodeFactory()
    img_id = nf.load_image(image_filename, node_id="1")
    biref_id = nf._add("BiRefNetRMBG", {
        "image": [img_id, 0],
        "model": model,
    }, node_id="2")
    nf.save_image([biref_id, 0], "spellcaster_rembg", node_id="3")
    return nf.build()


def build_ddcolor(image_filename, checkpoint="ddcolor_artistic.pth",
                  model_input_size=512):
    """Colorize B&W photo using DDColor (fast, no diffusion).

    DDColor uses dual decoders for state-of-the-art automatic
    colorization without requiring a text prompt or diffusion model.
    Much faster than ControlNet-guided colorization.

    Checkpoints:
      - ddcolor_artistic.pth: best for artistic/creative colors (default)
      - ddcolor_modelscope.pth: most accurate/natural colors
      - ddcolor_paper.pth: academic baseline
      - ddcolor_paper_tiny.pth: fastest, lower quality

    Returns:
        dict: ComfyUI workflow (load -> DDColor_Colorize -> save)
    """
    nf = NodeFactory()
    img_id = nf.load_image(image_filename, node_id="1")
    dd_id = nf._add("DDColor_Colorize", {
        "image": [img_id, 0],
        "checkpoint": checkpoint,
        "model_input_size": model_input_size,
    }, node_id="2")
    nf.save_image([dd_id, 0], "spellcaster_colorize", node_id="3")
    return nf.build()


# ═══════════════════════════════════════════════════════════════════════════
#  upscale — Model-based super-resolution
# ═══════════════════════════════════════════════════════════════════════════

def build_upscale(image_filename, model_name, upscale_factor=1.0):
    """Super-resolution upscaling using a trained upscaler model.

    Uses pre-trained models (e.g., RealESRGAN, SRVGGNet) to enhance resolution
    and details. Non-diffusion approach, purely neural-network based.

    Pipeline:
      1. Load input image
      2. Load upscaler model (e.g., "4x-UltraSharp.pth")
      3. Apply upscaling
      4. Save upscaled image

    Args:
        image_filename (str): Path to input image
        model_name (str): Name of upscaler model file, e.g. "4x-UltraSharp.pth",
                         "RealESRGAN_x4plus.pth", etc.
        upscale_factor (float): Scale factor if not embedded in model (default 1.0).
                               Model filename typically encodes scale (e.g., "4x")

    Returns:
        dict: ComfyUI workflow (simple 4-node graph)

    Note:
      - No diffusion involved, purely deterministic
      - Quality varies by model; RealESRGAN best for photographs
      - Fast compared to diffusion-based super-resolution
      - Result quality plateaus at ~4x scaling
    """
    nf = NodeFactory()
    img_id = nf.load_image(image_filename, node_id="1")
    up_model_id = nf.upscale_model_loader(model_name, node_id="2")
    up_id = nf.image_upscale_with_model_by_factor(
        [up_model_id, 0], [img_id, 0], upscale_factor, node_id="3")
    nf.save_image([up_id, 0], "spellcaster_upscale", node_id="4")
    return nf.build()


def build_wavespeed_upscale(image_filename, model="SeedVR2", target="2K"):
    """WaveSpeed AI upscale — fast one-node upscale to 2K/4K/8K.

    Uses WaveSpeed's optimized SeedVR2 or Ultimate model for fast,
    high-quality upscaling without manual model selection.

    Args:
        image_filename: Input image
        model: "SeedVR2" (default) or "Ultimate"
        target: "2K", "4K", or "8K"
    """
    nf = NodeFactory()
    img_id = nf.load_image(image_filename, node_id="1")
    up_id = nf.wavespeed_upscale([img_id, 0], model=model,
                                  target=target, node_id="2")
    nf.save_image([up_id, 0], "spellcaster_upscale", node_id="3")
    return nf.build()


def build_normal_map(image_filename, seed=42, max_res=1024,
                      sam3_prompt=None, sam3_invert=False, sam3_confidence=0.6,
                      sam3_expand=4, sam3_blur=4):
    """Generate 3D surface normal map using NormalCrafter.

    Produces a normal map image useful for relighting, 3D reconstruction,
    and ControlNet normal guidance.

    When sam3_prompt is set, the transform is composited back onto the original
    using a SAM3 mask so only the described region changes.
    """
    nf = NodeFactory()
    img_id = nf.load_image(image_filename, node_id="1")
    img_ref = [img_id, 0]
    normal_id = nf.normal_crafter(img_ref, seed=seed,
                                   max_res=max_res, node_id="2")
    # NormalCrafter may rescale to max_res; resize the original to match the
    # output so ImageCompositeMasked accepts them. We use GetImageSize on the
    # normal output and ImageScale the original to match.
    final_ref = [normal_id, 0]
    if sam3_prompt:
        _mask = build_sam3_mask(nf, img_ref, sam3_prompt,
                                 invert=sam3_invert,
                                 confidence=sam3_confidence,
                                 mask_expand=sam3_expand,
                                 mask_blur=sam3_blur)
        # Resize original to match the (possibly rescaled) normal-map output.
        size_id = nf.get_image_size([normal_id, 0], node_id="910")
        orig_resized_id = nf.image_scale(
            img_ref, [size_id, 0], [size_id, 1],
            upscale_method="lanczos", crop="disabled", node_id="911",
        )
        final_ref = apply_sam3_scope(nf, final_ref, [orig_resized_id, 0], _mask)
    nf.save_image(final_ref, "spellcaster_normals", node_id="3")
    return nf.build()


# ═══════════════════════════════════════════════════════════════════════════
#  lama_remove — Object removal without diffusion
# ═══════════════════════════════════════════════════════════════════════════

def build_lama_remove(image_filename, mask_filename=None,
                       sam3_prompt=None, sam3_invert=False,
                       sam3_confidence=0.6, sam3_expand=4, sam3_blur=4):
    """Object removal via LaMa inpainting (no diffusion).

    LaMa (Large Mask Inpainting) removes unwanted objects by inpainting masked
    regions using a trained CNN. Fast, deterministic, no randomness.

    Pipeline:
      1. Load input image and mask image
      2. Convert mask to MASK type (red channel)
      3. Apply LaMa remover
      4. Save result

    Args:
        image_filename (str): Path to input image
        mask_filename (str, optional): Path to mask image (white = remove,
                            black = keep). Converted from red channel.
                            Required unless sam3_prompt is provided.
        sam3_prompt (str, optional): If set (and mask_filename is None), build
                            the removal mask server-side from SAM3 instead of
                            loading it from a file.

    Returns:
        dict: ComfyUI workflow

    Note:
      - Faster than diffusion-based inpainting
      - Deterministic (same mask = same output)
      - Good for removing small objects or unwanted people
      - Quality lower for complex/large removals compared to diffusion
    """
    nf = NodeFactory()
    img_id = nf.load_image(image_filename, node_id="1")

    # Mask source: file-loaded overrides SAM3 when both supplied.
    if mask_filename:
        mask_img_id = nf.load_image(mask_filename, node_id="2")
        mask_id = nf.image_to_mask([mask_img_id, 0], "red", node_id="5")
        mask_ref = [mask_id, 0]
    elif sam3_prompt:
        # build_sam3_mask returns a MASK-typed ref directly — no image_to_mask
        # conversion needed.
        mask_ref = build_sam3_mask(nf, [img_id, 0], sam3_prompt,
                                    invert=sam3_invert,
                                    confidence=sam3_confidence,
                                    mask_expand=sam3_expand,
                                    mask_blur=sam3_blur)
    else:
        raise ValueError("build_lama_remove requires either mask_filename or sam3_prompt")

    lama_id = nf.lama_remover([img_id, 0], mask_ref, node_id="3")
    nf.save_image([lama_id, 0], "spellcaster_lama", node_id="4")
    return nf.build()


# ═══════════════════════════════════════════════════════════════════════════
#  lut — Color grading
# ═══════════════════════════════════════════════════════════════════════════

def build_lut(image_filename, lut_name, strength,
               sam3_prompt=None, sam3_invert=False, sam3_confidence=0.6,
               sam3_expand=4, sam3_blur=4):
    """Color grading via LUT (Look-Up Table) application.

    When sam3_prompt is set, the transform is composited back onto the original
    using a SAM3 mask so only the described region changes.

    LUTs are pre-baked color transformations (like Photoshop grading presets).
    Applied with variable strength for blended effect.

    Pipeline:
      1. Load input image
      2. Apply LUT with blending strength
      3. Save graded image

    Args:
        image_filename (str): Path to input image
        lut_name (str): Name of LUT file (e.g., "cinematic.3dl", "cool_tone.cube")
        strength (float): Blend factor 0.0-1.0 (0=original, 1=full LUT applied)

    Returns:
        dict: ComfyUI workflow

    Note:
      - Deterministic, no randomness or AI involved
      - Very fast operation
      - Quality depends on LUT quality and match to image style
      - Can be stacked with other adjustments
    """
    nf = NodeFactory()
    img_id = nf.load_image(image_filename, node_id="1")
    img_ref = [img_id, 0]
    lut_id = nf.image_apply_lut(img_ref, lut_name, strength, node_id="2")
    # LUT preserves dimensions — no resize needed.
    final_ref = [lut_id, 0]
    if sam3_prompt:
        _mask = build_sam3_mask(nf, img_ref, sam3_prompt,
                                 invert=sam3_invert,
                                 confidence=sam3_confidence,
                                 mask_expand=sam3_expand,
                                 mask_blur=sam3_blur)
        final_ref = apply_sam3_scope(nf, final_ref, img_ref, _mask)
    nf.save_image(final_ref, "spellcaster_lut", node_id="3")
    return nf.build()


# ═══════════════════════════════════════════════════════════════════════════
#  AI Color Match — transfer color palette from a reference image
# ═══════════════════════════════════════════════════════════════════════════

def build_color_match(source_filename, reference_filename, strength=1.0,
                      method="mkl"):
    """AI Color Match — transfer color palette from a reference image.

    Uses histogram-based color transfer to match the source image's color
    palette, tone, and mood to a reference image. Useful for:
      - Matching lighting/color between composited layers
      - Applying a color mood from a reference photo
      - Color-correcting to match a series or scene

    Args:
        source_filename (str): Image to recolor.
        reference_filename (str): Image whose colors to copy.
        strength (float): Blend 0.0-1.0 (0=original, 1=full transfer).
        method (str): Transfer algorithm:
            "mkl" — Monge-Kantorovitch (best for photos)
            "hm"  — Histogram matching (faster, less accurate)
            "reinhard" — Reinhard et al. (classic, good for landscapes)

    Returns:
        dict: ComfyUI workflow.

    Requires: ColorMatch node (ComfyUI_essentials or similar).
    """
    nf = NodeFactory()
    src_id = nf.load_image(source_filename, node_id="1")
    ref_id = nf.load_image(reference_filename, node_id="2")
    match_id = nf._add("ColorMatch", {
        "image_ref": [ref_id, 0],
        "image_target": [src_id, 0],
        "method": method,
        "strength": strength,
    }, node_id="3")
    nf.save_image([match_id, 0], "spellcaster_colormatch", node_id="4")
    return nf.build()


# ═══════════════════════════════════════════════════════════════════════════
#  Flux2Klein-Enhancer — optional quality upgrade for ALL Klein pipelines
# ═══════════════════════════════════════════════════════════════════════════
# If the ComfyUI-Flux2Klein-Enhancer custom node pack is installed, these
# nodes wrap the model to improve reference latent fidelity and fix color
# drift. The helper below is called from every build_klein_* function
# that accepts enhance=True. When enhance=False (default) it's a no-op.
#
# The node pack must be installed via ComfyUI Manager:
#   https://civitai.com/models/2492746/comfyui-flux2klein-enhancer

# Class types to probe for when detecting enhancer availability.
KLEIN_ENHANCER_NODE_TYPES = {
    "Flux2KleinRefLatentController",
    "Flux2KleinTextRefBalance",
    "Flux2KleinColorAnchor",
}


def _klein_enhance_model(nf, model_ref, conditioning_ref,
                          ref_strength=500, text_ref_balance=0.5,
                          color_anchor_strength=0.5, node_base_id=900):
    """Wrap a Klein model with the Flux2Klein-Enhancer nodes.

    Chains: model → RefLatentController → TextRefBalance → ColorAnchor.
    Each node takes MODEL + CONDITIONING and outputs MODEL.

    Called from build_klein_* functions when enhance=True. If enhance is
    False the caller skips this entirely — there's no runtime check here
    (the preflight system handles missing-node detection).

    Args:
        nf: NodeFactory instance.
        model_ref: [node_id, slot] for the UNET/model output.
        conditioning_ref: [node_id, slot] for the positive conditioning.
        ref_strength: Reference latent injection strength (1-1000).
        text_ref_balance: 0.0=text only, 0.999=reference only.
        color_anchor_strength: Color drift correction (0.3-0.6 rec).
        node_base_id: Starting node ID for the enhancer chain.

    Returns:
        Enhanced model reference [node_id, 0].
    """
    ref_ctrl = nf.flux2klein_ref_latent_controller(
        model_ref, conditioning_ref, strength=ref_strength,
        node_id=str(node_base_id))
    balance = nf.flux2klein_text_ref_balance(
        [ref_ctrl, 0], conditioning_ref, balance=text_ref_balance,
        node_id=str(node_base_id + 1))
    anchor = nf.flux2klein_color_anchor(
        [balance, 0], conditioning_ref, strength=color_anchor_strength,
        node_id=str(node_base_id + 2))
    return [anchor, 0]


# ═══════════════════════════════════════════════════════════════════════════
#  klein_img2img — Flux 2 Klein distilled img2img
# ═══════════════════════════════════════════════════════════════════════════

def build_klein_img2img(image_filename, klein_model_key, prompt_text, seed,
                         steps=4, denoise=0.65, guidance=1.0,
                         enhancer_mag=1.0, enhancer_contrast=0.0, loras=None,
                         lora_name=None, lora_strength=1.0,
                         klein_models=None, enhance=True,
                         sam3_prompt=None, sam3_invert=False,
                         sam3_confidence=0.6, sam3_expand=4, sam3_blur=4):
    """Image-to-image with Flux 2 Klein (distilled fast model).

    When sam3_prompt is set, the transform is composited back onto the original
    using a SAM3 mask so only the described region changes.

    Klein is a 4B/9B parameter distilled variant of Flux that runs 6-8x faster
    while maintaining quality. Uses custom sampler pipeline and ReferenceLatent
    wrapping for image guidance.

    Pipeline:
      1. Load Klein UNET (9B, 4B, or 4B-base variant)
      2. Load matching CLIP (qwen_3_8b for 9B, qwen_3_4b for 4B/4B-base)
      3. Load flux2-vae
      4. Encode prompt → positive conditioning
      5. Create zero conditioning for negative
      6. Load and scale input image to 1.0 megapixel
      7. Encode image to latent
      8. Wrap both positive and negative in ReferenceLatent (ties conditioning to latent)
      9. Build custom sampler: CFG guider + euler sampler + basic_scheduler (with denoise)
      10. Sample with custom_advanced sampler
      11. Decode and save

    Args:
        image_filename (str): Path to input image
        klein_model_key (str): "Klein 9B", "Klein 4B", or "Klein 4B Base"
                              (must match a key in klein_models dict)
        prompt_text (str): Positive prompt
        seed (int): Random seed
        steps (int): Diffusion steps, typically 4-6 for Klein (default 4)
        denoise (float): Denoising strength 0.0-1.0 (default 0.65)
        guidance (float): Guidance scale, typically 1.0-3.0 (default 1.0)
                         Klein works best with low guidance
        enhancer_mag (float): Not used in current implementation (legacy param)
        enhancer_contrast (float): Not used (legacy param)
        lora_name (str, optional): Path to optional LoRA to apply
        lora_strength (float): LoRA strength if lora_name provided (default 1.0)
        klein_models (dict, optional): Mapping of klein_model_key to
            {"unet": "path/to/unet.safetensors", "clip": "path/to/clip.safetensors"}

    Returns:
        dict: ComfyUI workflow with custom Flux2 sampler setup.

    CRITICAL: VAE/CLIP PAIRING
      - Klein 9B REQUIRES qwen_3_8b.safetensors
      - Klein 4B REQUIRES qwen_3_4b.safetensors
      - Using wrong pairing = degraded quality or silent failures
      - See Klein Config in project memory

    Node IDs:
      - "1": unet_loader
      - "2": clip_loader (model-specific CLIP)
      - "3": vae_loader (flux2-vae.safetensors)
      - "4","5": positive/negative text encoding
      - "10"-"12": input image loading and scaling
      - "13": vae_encode (image → latent)
      - "20","21": ReferenceLatent wrappers (conditioning tied to latent)
      - "30"-"33": Sampler components (guider, sampler, scheduler, noise)
      - "40": custom_advanced sampler (main diffusion)
      - "50": vae_decode
      - "51": save_image

    Differences from standard KSampler:
      - No LoRA chain support in current implementation (legacy)
      - Uses CFG guider + custom sampler instead of built-in ksampler
      - ReferenceLatent wrapping provides latent-aware guidance
      - basic_scheduler() with denoise for proper img2img partial denoising
      - Low guidance values work better (1.0-3.0 vs 7-15 for SDXL)
    """
    if klein_models is None:
        klein_models = KLEIN_MODELS

    # Convert single lora_name/lora_strength to loras list format
    if lora_name and not loras:
        loras = [{"name": lora_name, "strength": lora_strength}]

    km = klein_models[klein_model_key]
    nf = NodeFactory()

    # Model loaders
    unet_id = nf.unet_loader(km["unet"], "default", node_id="1")
    clip_id = nf.clip_loader(
        km.get("clip", "qwen_3_8b.safetensors"),
        clip_type="flux2", device="default", node_id="2",
    )
    vae_id = nf.vae_loader(FLUX2_VAE, node_id="3")


    # Apply LoRA chain
    if loras:
        unet_id, clip_id, _trig = inject_lora_chain(nf, loras, _ref(unet_id), _ref(clip_id), base_id=100)
        # After LoRA chain, refs are [node_id, slot] lists.
        # Leave them as-is. Use _ref() for all downstream references.
    # Text conditioning
    pos_id = nf.clip_encode(_ref(clip_id), prompt_text, node_id="4")
    neg_id = nf.conditioning_zero_out([pos_id, 0], node_id="5")

    # Input image processing
    img_id = nf.load_image(image_filename, node_id="10")
    scaled_id = nf.image_scale_to_total_pixels([img_id, 0], megapixels=1.0,
                                                node_id="11")
    size_id = nf.get_image_size([scaled_id, 0], node_id="12")

    # Encode reference image to latent
    latent_id = nf.vae_encode([scaled_id, 0], [vae_id, 0], node_id="13")

    # ReferenceLatent wrapping
    ref_pos_id = nf.reference_latent([pos_id, 0], [latent_id, 0], node_id="20")
    ref_neg_id = nf.reference_latent([neg_id, 0], [latent_id, 0], node_id="21")

    # Optional Flux2Klein-Enhancer — wraps the model with reference
    # strength control + text/ref balance + color anchor if installed.
    model_for_guider = _ref(unet_id)
    if enhance:
        model_for_guider = _klein_enhance_model(nf, _ref(unet_id), [ref_pos_id, 0])

    # Sampler setup
    guider_id = nf.cfg_guider(model_for_guider, [ref_pos_id, 0], [ref_neg_id, 0],
                              guidance, node_id="30")
    sampler_id = nf.ksampler_select("euler", node_id="31")
    sched_id = nf.basic_scheduler(_ref(unet_id), steps, denoise,
                                   scheduler="simple", node_id="32")
    noise_id = nf.random_noise(seed, node_id="33")

    # Sample -- feed encoded image latent, NOT empty latent
    sample_id = nf.sampler_custom_advanced(
        [noise_id, 0], [guider_id, 0], [sampler_id, 0],
        [sched_id, 0], [latent_id, 0], node_id="40",
    )

    # Decode and save
    dec_id = nf.vae_decode([sample_id, 0], [vae_id, 0], node_id="50")
    # Klein rescales input to 1 MP via image_scale_to_total_pixels (node "11"),
    # so the PRE-SCALED input (scaled_id) matches the output dimensions.
    # Use that as the compositing "original".
    final_ref = [dec_id, 0]
    if sam3_prompt:
        _mask = build_sam3_mask(nf, [scaled_id, 0], sam3_prompt,
                                 invert=sam3_invert,
                                 confidence=sam3_confidence,
                                 mask_expand=sam3_expand,
                                 mask_blur=sam3_blur)
        final_ref = apply_sam3_scope(nf, final_ref, [scaled_id, 0], _mask)
    nf.save_image(final_ref, "gimp_klein", node_id="51")

    return nf.build()


# ═══════════════════════════════════════════════════════════════════════════
#  Face Swap — ReActor with quality presets and double-pass
# ═══════════════════════════════════════════════════════════════════════════

def build_faceswap(target_filename, source_filename, swap_model="inswapper_128.onnx",
                   face_restore_model="codeformer-v0.1.0.pth",
                   face_restore_vis=1.0, codeformer_weight=0.7,
                   detect_gender_input="no", detect_gender_source="no",
                   input_face_idx="0", source_face_idx="0",
                   quality_preset=None, quality_presets=None):
    """Face swap using ReActor with optional quality presets and restoration.

    Swaps faces from source image into target image using ReActor (a face-swap
    node based on ONNX models). Includes optional CodeFormer post-processing
    to restore swapped face quality, with two-pass capability for high quality.

    Pipeline:
      1. Load target and source images
      2. Create ReActor options (face detection, gender matching)
      3. Create face boost settings (CodeFormer restoration parameters)
      4. Run reactor_face_swap_opt with specified swap model
      5. Post-process with CodeFormer face restoration (if enabled)
      6. Save result

    Args:
        target_filename (str): Image to receive the new face
        source_filename (str): Image with face to swap in
        swap_model (str): ONNX swap model file, e.g. "inswapper_128.onnx",
                         "inswapper_128_fp16.onnx" (default "inswapper_128.onnx")
        face_restore_model (str): CodeFormer or GFPGan model for post-processing
                                (default "codeformer-v0.1.0.pth")
        face_restore_vis (float): CodeFormer restoration blend, 0.0-1.0
                                (0=original, 1=full restoration, default 1.0)
        codeformer_weight (float): CodeFormer quality weight 0.0-1.0
                                 (higher = more aggressive enhancement, default 0.7)
        detect_gender_input (str): "no" or gender to enforce for target face
        detect_gender_source (str): "no" or gender to enforce for source face
        input_face_idx (str): Face index in target (0=first/largest, default "0")
        source_face_idx (str): Face index in source (default "0")
        quality_preset (str): Optional quality preset name (e.g., "ultra", "high")
                            Overrides swap_model and restore_model if provided
        quality_presets (dict, optional): Maps preset names to
            {"pass1_model": "...", "pass1_restore": "...", "pass1_vis": ..., "pass1_cf": ...}

    Returns:
        dict: ComfyUI workflow with face swap and optional restoration.

    Node IDs:
      - "1": load target image
      - "2": load source image
      - "4": reactor_options (detection settings)
      - "5": reactor_face_boost (CodeFormer settings)
      - "6": reactor_face_swap_opt (the actual swap)
      - "7": codeformer_boost (restoration)
      - "8": save_image

    Quality Presets:
      Presets override individual model/parameter settings for consistent results.
      Example preset structure:
        {
            "ultra": {
                "pass1_model": "inswapper_128.onnx",
                "pass1_restore": "codeformer-v0.1.0.pth",
                "pass1_vis": 1.0,
                "pass1_cf": 0.7
            }
        }

    Gotchas:
      - Face detection may fail on multiple faces; use input_face_idx to select
      - Gender mismatch can cause detection to fail; set to "no" if having issues
      - CodeFormer restoration adds time but significantly improves quality
      - codeformer_weight 0.5-0.7 recommended (too high = over-processing)
      - Models must be ONNX format (inswapper_*.onnx), not PyTorch
    """
    if quality_presets and quality_preset and quality_preset in quality_presets:
        qp = quality_presets[quality_preset]
        swap_model = qp["pass1_model"]
        face_restore_model = qp["pass1_restore"]
        face_restore_vis = qp["pass1_vis"]
        codeformer_weight = qp["pass1_cf"]

    nf = NodeFactory()
    img_id = nf.load_image(target_filename, node_id="1")
    src_id = nf.load_image(source_filename, node_id="2")

    opts_id = nf.reactor_options(
        input_faces_index=input_face_idx,
        detect_gender_input=detect_gender_input,
        source_faces_index=source_face_idx,
        detect_gender_source=detect_gender_source,
        node_id="4",
    )
    boost_id = nf.reactor_face_boost(
        boost_model=face_restore_model,
        codeformer_weight=codeformer_weight,
        node_id="5",
    )
    swap_id = nf.reactor_face_swap_opt(
        [img_id, 0], [src_id, 0],
        swap_model=swap_model,
        face_restore_model=face_restore_model,
        face_restore_visibility=face_restore_vis,
        codeformer_weight=codeformer_weight,
        options_ref=[opts_id, 0],
        face_boost_ref=[boost_id, 0],
        node_id="3",
    )

    result_ref = [swap_id, 0]

    # Double-pass: run a second swap with a different model for refinement
    if quality_presets and quality_preset and quality_preset in quality_presets:
        qp = quality_presets[quality_preset]
        if qp.get("double_pass"):
            opts2_id = nf.reactor_options(
                input_faces_index=input_face_idx,
                detect_gender_input=detect_gender_input,
                source_faces_index=source_face_idx,
                detect_gender_source=detect_gender_source,
                node_id="21",
            )
            boost2_id = nf.reactor_face_boost(
                boost_model=qp["pass2_restore"],
                codeformer_weight=qp["pass2_cf"],
                node_id="22",
            )
            swap2_id = nf.reactor_face_swap_opt(
                [swap_id, 0], [src_id, 0],
                swap_model=qp["pass2_model"],
                face_restore_model=qp["pass2_restore"],
                face_restore_visibility=qp["pass2_vis"],
                codeformer_weight=qp["pass2_cf"],
                options_ref=[opts2_id, 0],
                face_boost_ref=[boost2_id, 0],
                node_id="20",
            )
            result_ref = [swap2_id, 0]

    nf.save_image(result_ref, "gimp_faceswap", node_id="10")
    return nf.build()


def build_faceswap_model(target_filename, face_model_name,
                          swap_model="inswapper_128.onnx",
                          face_restore_model="codeformer-v0.1.0.pth",
                          face_restore_vis=1.0, codeformer_weight=0.5,
                          detect_gender_input="no", detect_gender_source="no",
                          input_face_idx="0", source_face_idx="0",
                          quality_preset=None, quality_presets=None):
    """ReActor face swap using a saved face model. Drop-in for _build_faceswap_model()."""
    if quality_presets and quality_preset and quality_preset in quality_presets:
        qp = quality_presets[quality_preset]
        swap_model = qp["pass1_model"]
        face_restore_model = qp["pass1_restore"]
        face_restore_vis = qp["pass1_vis"]
        codeformer_weight = qp["pass1_cf"]

    nf = NodeFactory()
    img_id = nf.load_image(target_filename, node_id="1")
    face_model_id = nf.reactor_load_face_model(face_model_name, node_id="2")

    opts_id = nf.reactor_options(
        input_faces_index=input_face_idx,
        detect_gender_input=detect_gender_input,
        source_faces_index=source_face_idx,
        detect_gender_source=detect_gender_source,
        node_id="4",
    )
    boost_id = nf.reactor_face_boost(
        boost_model=face_restore_model,
        codeformer_weight=codeformer_weight,
        node_id="5",
    )
    swap_id = nf.reactor_face_swap_opt(
        [img_id, 0], None,
        swap_model=swap_model,
        face_restore_model=face_restore_model,
        face_restore_visibility=face_restore_vis,
        codeformer_weight=codeformer_weight,
        options_ref=[opts_id, 0],
        face_boost_ref=[boost_id, 0],
        face_model_ref=[face_model_id, 0],
        node_id="3",
    )

    result_ref = [swap_id, 0]

    # Double-pass
    if quality_presets and quality_preset and quality_preset in quality_presets:
        qp = quality_presets[quality_preset]
        if qp.get("double_pass"):
            opts2_id = nf.reactor_options(
                input_faces_index=input_face_idx,
                detect_gender_input=detect_gender_input,
                source_faces_index=source_face_idx,
                detect_gender_source=detect_gender_source,
                node_id="21",
            )
            boost2_id = nf.reactor_face_boost(
                boost_model=qp["pass2_restore"],
                codeformer_weight=qp["pass2_cf"],
                node_id="22",
            )
            swap2_id = nf.reactor_face_swap_opt(
                [swap_id, 0], None,
                swap_model=qp["pass2_model"],
                face_restore_model=qp["pass2_restore"],
                face_restore_visibility=qp["pass2_vis"],
                codeformer_weight=qp["pass2_cf"],
                options_ref=[opts2_id, 0],
                face_boost_ref=[boost2_id, 0],
                face_model_ref=[face_model_id, 0],
                node_id="20",
            )
            result_ref = [swap2_id, 0]

    nf.save_image(result_ref, "gimp_faceswap_model", node_id="10")
    return nf.build()


def build_save_face_model(source_filename, model_name, overwrite=True):
    """Build and save a ReActor face model. Drop-in for _build_save_face_model()."""
    nf = NodeFactory()
    img_id = nf.load_image(source_filename, node_id="1")
    build_id = nf.reactor_build_face_model([img_id, 0], node_id="2")
    nf.reactor_save_face_model(
        [build_id, 0],
        save_mode=overwrite,
        face_model_name=model_name,
        node_id="3",
    )
    # Terminal output node so ComfyUI considers the workflow complete
    nf.save_image([img_id, 0], "gimp_face_model_src", node_id="4")
    return nf.build()


def build_faceswap_mtb(target_filename, source_filename,
                        analysis_model="buffalo_l",
                        swap_model="inswapper_128.onnx",
                        faces_index="0"):
    """Face swap using mtb facetools. Drop-in for _build_faceswap_mtb()."""
    nf = NodeFactory()
    target_id = nf.load_image(target_filename, node_id="1")
    source_id = nf.load_image(source_filename, node_id="2")
    analysis_id = nf.mtb_load_face_analysis(analysis_model, node_id="3")
    swap_model_id = nf.mtb_load_face_swap(swap_model, node_id="4")
    swap_id = nf.mtb_face_swap(
        [target_id, 0], [source_id, 0],
        [analysis_id, 0], [swap_model_id, 0],
        faces_index=faces_index, node_id="5",
    )
    nf.save_image([swap_id, 0], "gimp_faceswap_mtb", node_id="10")
    return nf.build()


# ═══════════════════════════════════════════════════════════════════════════
#  Face Restore — ReActorRestoreFace
# ═══════════════════════════════════════════════════════════════════════════

def build_face_restore(image_filename, model_name, facedetection,
                        visibility, codeformer_weight,
                        sam3_prompt=None, sam3_invert=False,
                        sam3_confidence=0.6, sam3_expand=4, sam3_blur=4):
    """Restore faces. Drop-in for _build_face_restore().

    When sam3_prompt is set, the transform is composited back onto the original
    using a SAM3 mask so only the described region changes.
    """
    nf = NodeFactory()
    img_id = nf.load_image(image_filename, node_id="1")
    img_ref = [img_id, 0]
    restore_id = nf.reactor_restore_face(
        img_ref, facedetection=facedetection,
        model=model_name, visibility=visibility,
        codeformer_weight=codeformer_weight, node_id="2",
    )
    # ReActorRestoreFace preserves dimensions — no resize needed.
    final_ref = [restore_id, 0]
    if sam3_prompt:
        _mask = build_sam3_mask(nf, img_ref, sam3_prompt,
                                 invert=sam3_invert,
                                 confidence=sam3_confidence,
                                 mask_expand=sam3_expand,
                                 mask_blur=sam3_blur)
        final_ref = apply_sam3_scope(nf, final_ref, img_ref, _mask)
    nf.save_image(final_ref, "spellcaster_facerestore", node_id="3")
    return nf.build()


# ═══════════════════════════════════════════════════════════════════════════
#  Photo Restore — Upscale + Face Restore + Sharpen pipeline
# ═══════════════════════════════════════════════════════════════════════════

def build_photo_restore(image_filename, upscale_model, face_model,
                         facedetection, visibility, codeformer_weight,
                         sharpen_radius, sigma, alpha):
    """Complete old photo restoration: upscale + face enhance + sharpen.

    Comprehensive restoration pipeline for old/damaged photos:
      1. Upscale the entire image using a trained super-resolution model
      2. Detect and enhance any faces using CodeFormer
      3. Sharpen the result to enhance details

    Pipeline:
      1. Load input image
      2. Load upscaler model (e.g., RealESRGAN)
      3. Apply upscaling
      4. Detect faces and apply CodeFormer restoration
      5. Sharpen edges to restore fine details
      6. Save result

    Args:
        image_filename (str): Path to old/damaged photo
        upscale_model (str): Upscaler model file, e.g. "4x-UltraSharp.pth"
        face_model (str): Face restoration model, typically "codeformer-v0.1.0.pth"
        facedetection (str): Face detection backend, e.g. "retinaface_resnet50"
        visibility (float): CodeFormer restoration blend 0.0-1.0
                          (0=original face, 1=full restoration, default ~1.0)
        codeformer_weight (float): CodeFormer quality weight 0.0-1.0
                                 (higher = more aggressive, default ~0.7)
        sharpen_radius (float): Sharpening kernel radius in pixels (default ~1.0)
        sigma (float): Gaussian blur sigma for sharpening (default ~1.0)
        alpha (float): Sharpening strength 0.0-2.0 (default ~1.0)
                      (0=no sharpening, >1=aggressive sharpening)

    Returns:
        dict: ComfyUI workflow (6-node pipeline)

    Node IDs:
      - "1": load_image
      - "2": upscale_model_loader
      - "3": image_upscale (applies upscaler)
      - "4": reactor_restore_face (face detection + CodeFormer)
      - "5": image_sharpen (edge enhancement)
      - "6": save_image

    Use Cases:
      - Restoring faded family photos
      - Recovering old scanned photographs
      - Enhancing damaged prints
      - Improving quality of photos taken on old cameras

    Sharpening Parameters:
      - radius: 0.5-1.0 = subtle detail enhancement
      - radius: 1.0-2.0 = noticeable sharpening
      - radius: >2.0 = aggressive (risk of halos/artifacts)
      - sigma: 0.8-1.2 = natural-looking result
      - alpha: 0.5-1.0 = conservative
      - alpha: 1.0-1.5 = moderate-to-strong

    Gotchas:
      - Upscaling may amplify noise in grainy/old photos
      - Face detection may fail on heavily damaged face regions
      - Over-sharpening (alpha > 1.5) creates halos and artifacts
      - CodeFormer weight > 0.8 can over-smooth skin texture
      - Process is sequential: upscale → face → sharpen (no rollback)
    """
    nf = NodeFactory()
    img_id = nf.load_image(image_filename, node_id="1")
    up_model_id = nf.upscale_model_loader(upscale_model, node_id="2")
    up_id = nf.image_upscale_with_model_by_factor(
        [up_model_id, 0], [img_id, 0], 1.0, node_id="3")
    restore_id = nf.reactor_restore_face(
        [up_id, 0], facedetection=facedetection,
        model=face_model, visibility=visibility,
        codeformer_weight=codeformer_weight, node_id="4",
    )
    sharpen_id = nf.image_sharpen(
        [restore_id, 0], sharpen_radius=sharpen_radius,
        sigma=sigma, alpha=alpha, node_id="5",
    )
    nf.save_image([sharpen_id, 0], "spellcaster_photorestore", node_id="6")
    return nf.build()


# ═══════════════════════════════════════════════════════════════════════════
#  Detail Hallucinate — Upscale + img2img at low denoise
# ═══════════════════════════════════════════════════════════════════════════

def build_detail_hallucinate(image_filename, upscale_model, preset,
                              prompt_text, negative_text, seed,
                              denoise, cfg, steps=None, upscale_factor=1.0,
                              loras=None,
                              controlnet=None, controlnet_2=None,
                              guide_modes=None,
                              sam3_prompt=None, sam3_invert=False,
                              sam3_confidence=0.6, sam3_expand=4, sam3_blur=4):
    """Super-resolution with detail hallucination via img2img diffusion.

    When sam3_prompt is set, the transform is composited back onto the original
    using a SAM3 mask so only the described region changes.

    Combines traditional super-resolution with diffusion-based detail enhancement.
    First upscales the image using a trained model, then runs img2img at low denoise
    to "hallucinate" (synthesize) fine details guided by a text prompt.

    Pipeline:
      1. Load input image
      2. Optionally upscale using super-resolution model
      3. Load diffusion model, CLIP, VAE
      4. Apply LoRA chain if provided
      5. Encode prompts
      6. VAE encode (upscaled) image → latent
      7. Sample at low denoise (0.3-0.5) to enhance details
      8. Decode and save
      9. Optionally inject ControlNet(s)

    Args:
        image_filename (str): Input image to enhance
        upscale_model (str, optional): Super-resolution model file
                                      (e.g. "4x-UltraSharp.pth").
                                      If None, skips initial upscaling.
        preset (dict): Sampling preset (architecture, steps, cfg, sampler, scheduler)
        prompt_text (str): Guidance for detail hallucination
                         (e.g. "ultra high detail, 8k resolution, intricate details")
        negative_text (str): What to avoid (e.g. "blurry, low quality, artifacts")
        seed (int): Random seed
        denoise (float): Detail enhancement intensity 0.2-0.5 (typical range)
                        - 0.2: Subtle detail enhancement
                        - 0.35-0.4: Balanced hallucination
                        - 0.5+: Aggressive detail generation (risk of artifacts)
        cfg (float): Classifier-free guidance for prompt adherence
        steps (int, optional): Override preset steps for this operation
        upscale_factor (float): Upscaling multiplier if upscale_model provided (default 1.0)
        controlnet (dict, optional): Spatial guidance (rare for hallucination)
        controlnet_2 (dict, optional): Second ControlNet
        guide_modes (dict, optional): ControlNet preprocessor info

    Returns:
        dict: ComfyUI workflow

    Why Combine Upscale + Diffusion?
      - Traditional upscaler: Fast, deterministic, but creates blurry details
      - Diffusion alone: Creates authentic-looking details but changes image structure
      - Combined: Upscaler provides high-res structure, diffusion adds realistic details

    Use Cases:
      - Enhance low-resolution photos with synthetic detail
      - Improve texture quality on face crops
      - Upscale concept art and maintain painted quality
      - Restore old photographs with modern detail

    Node IDs (if upscale_model provided):
      - "1": load_image
      - "2": upscale_model_loader
      - "3": image_upscale
      - "4"-onwards: diffusion pipeline

    Node IDs (if upscale_model = None):
      - "1": load_image
      - "2"-onwards: diffusion pipeline

    Hallucination Prompt Tips:
      - Use high-detail descriptors: "intricate", "fine details", "8k"
      - Be specific about texture: "fabric weave", "skin pores", "wood grain"
      - Avoid contradicting original: "similar composition", "same subject"
      - Example: "ultra high detail, intricate textures, 8k quality, photorealistic, sharp focus"

    Gotchas:
      - Denoise > 0.5 risks losing original content (use lower values)
      - Upscale + diffusion doubles processing time
      - Hallucinated details may not match lighting/physics of original
      - cfg > 15.0 can cause the diffusion to diverge from upscaled structure
      - Negative prompt is critical to prevent artifact hallucination
    """
    nf = NodeFactory()
    img_id = nf.load_image(image_filename, node_id="1")

    # Optional upscale
    if upscale_model:
        up_model_id = nf.upscale_model_loader(upscale_model, node_id="2")
        up_id = nf.image_upscale_with_model_by_factor(
            [up_model_id, 0], [img_id, 0], upscale_factor, node_id="3")
        img_ref = [up_id, 0]
    else:
        img_ref = [img_id, 0]

    # Model loading (architecture-aware)
    model_ref, clip_ref, vae_ref = load_model_stack(nf, preset, "4")

    # LoRA chain
    if loras:
        model_ref, clip_ref, _trig = inject_lora_chain(nf, loras, model_ref, clip_ref, base_id=100)

    # Encode prompts
    arch_key = preset.get("arch", "sdxl")
    pos_id, neg_id = encode_prompts(nf, arch_key, clip_ref,
                                     prompt_text, negative_text,
                                     pos_id="5", neg_id="6")

    # VAE encode → sample → decode → save
    enc_id = nf.vae_encode(img_ref, vae_ref, node_id="7")
    is_klein = arch_key == "flux2klein"
    if is_klein:
        ref_pos = nf.reference_latent([pos_id, 0], [enc_id, 0], node_id="60")
        ref_neg = nf.reference_latent([neg_id, 0], [enc_id, 0], node_id="61")
        guider_id = nf.cfg_guider(model_ref, [ref_pos, 0], [ref_neg, 0],
                                  cfg, node_id="62")
        sampler_sel = nf.ksampler_select("euler", node_id="63")
        sched_id = nf.basic_scheduler(model_ref, steps or preset.get("steps", 20),
                                       denoise, scheduler="simple", node_id="64")
        noise_id = nf.random_noise(seed, node_id="65")
        samp_id = nf.sampler_custom_advanced(
            [noise_id, 0], [guider_id, 0], [sampler_sel, 0],
            [sched_id, 0], [enc_id, 0], node_id="8",
        )
    else:
        samp_id = nf.ksampler(
            model_ref,
            [pos_id, 0], [neg_id, 0], [enc_id, 0],
            seed, steps or preset["steps"], cfg,
            preset.get("sampler", "euler"), preset.get("scheduler", "normal"),
            denoise, node_id="8",
        )
    dec_id = nf.vae_decode([samp_id, 0], vae_ref, node_id="9")
    # img_ref is the POST-UPSCALE image, which matches the sampler output
    # dimensions exactly. Using img_ref (not the raw LoadImage) as the
    # compositing "original" avoids any ImageScale and preserves the enhanced
    # structure outside the SAM3 region.
    final_ref = [dec_id, 0]
    if sam3_prompt:
        _mask = build_sam3_mask(nf, img_ref, sam3_prompt,
                                 invert=sam3_invert,
                                 confidence=sam3_confidence,
                                 mask_expand=sam3_expand,
                                 mask_blur=sam3_blur)
        final_ref = apply_sam3_scope(nf, final_ref, img_ref, _mask)
    nf.save_image(final_ref, "spellcaster_hallucinate", node_id="10")

    # ControlNet injection (optional)
    if guide_modes and controlnet and controlnet.get("mode", "Off") != "Off":
        cn_pos, cn_neg = inject_controlnet(
            nf, controlnet, guide_modes, arch_key, img_ref,
            [pos_id, 0], [neg_id, 0], cn_base_id=20,
        )
        nf.patch_input("8", "positive", cn_pos)
        nf.patch_input("8", "negative", cn_neg)

    if guide_modes and controlnet_2 and controlnet_2.get("mode", "Off") != "Off":
        prev_pos = [str(22), 0] if nf.has_node("22") else [pos_id, 0]
        prev_neg = [str(22), 1] if nf.has_node("22") else [neg_id, 0]
        cn2_pos, cn2_neg = inject_controlnet(
            nf, controlnet_2, guide_modes, arch_key, img_ref,
            prev_pos, prev_neg, cn_base_id=30,
        )
        nf.patch_input("8", "positive", cn2_pos)
        nf.patch_input("8", "negative", cn2_neg)

    return nf.build()


# ═══════════════════════════════════════════════════════════════════════════
#  Colorize — dual ControlNet pipeline
# ═══════════════════════════════════════════════════════════════════════════

def build_colorize(image_filename, preset, prompt_text, negative_text, seed,
                    controlnet_strength, denoise, steps=None, cfg=None,
                    controlnet_2=None, guide_modes=None, loras=None,
                    lineart_models=None,
                    sam3_prompt=None, sam3_invert=False,
                    sam3_confidence=0.6, sam3_expand=4, sam3_blur=4):
    """Colorize B&W photo. Drop-in for _build_colorize().

    lineart_models: CONTROLNET_LINEART_MODELS dict from main plugin.

    When sam3_prompt is set, the transform is composited back onto the original
    using a SAM3 mask so only the described region changes.
    """
    nf = NodeFactory()
    arch_key = preset.get("arch", "sdxl")
    res = max(preset.get("width", 1024), preset.get("height", 1024))

    img_id = nf.load_image(image_filename, node_id="1")
    img_ref = [img_id, 0]

    # Lineart preprocessor at full resolution
    lineart_id = nf.preprocessor(
        "LineArtPreprocessor", img_ref,
        node_id="2", resolution=res, coarse="disable",
    )

    # Model loading
    model_ref, clip_ref, vae_ref = load_model_stack(nf, preset, "3")

    # LoRA chain
    if loras:
        model_ref, clip_ref, _trig = inject_lora_chain(nf, loras, model_ref, clip_ref, base_id=100)

    # Lineart ControlNet — architecture-specific model selection
    _LINEART_CN_MODELS = {
        "sd15": "control_v11p_sd15_lineart_fp16.safetensors",
        "sdxl": "SDXL\\controlnet-canny-sdxl-1.0.safetensors",
        "illustrious": "SDXL\\controlnet-canny-sdxl-1.0.safetensors",
        "zit": "Z-Image-Turbo-Fun-Controlnet-Union.safetensors",
        "flux1dev": "FLUX.1-dev-ControlNet-Union-Pro-2.0.safetensors",
    }
    cn_lineart = (lineart_models or _LINEART_CN_MODELS).get(
        arch_key, _LINEART_CN_MODELS.get("sdxl", "SDXL\\controlnet-canny-sdxl-1.0.safetensors"))
    cn_loader_id = nf.controlnet_loader(cn_lineart, node_id="4")

    # Encode prompts
    pos_id, neg_id = encode_prompts(nf, arch_key, clip_ref,
                                     prompt_text, negative_text,
                                     pos_id="5", neg_id="6")

    # Apply lineart ControlNet
    cn_apply_id = nf.controlnet_apply_advanced(
        [pos_id, 0], [neg_id, 0],
        [cn_loader_id, 0], [lineart_id, 0],
        controlnet_strength, 0.0, 1.0, node_id="7",
    )

    # VAE encode → sample → decode → save
    enc_id = nf.vae_encode(img_ref, vae_ref, node_id="8")
    is_klein = arch_key == "flux2klein"
    if is_klein:
        ref_pos = nf.reference_latent([cn_apply_id, 0], [enc_id, 0], node_id="60")
        ref_neg = nf.reference_latent([cn_apply_id, 1], [enc_id, 0], node_id="61")
        guider_id = nf.cfg_guider(model_ref, [ref_pos, 0], [ref_neg, 0],
                                  cfg or preset.get("cfg", 1.0), node_id="62")
        sampler_sel = nf.ksampler_select("euler", node_id="63")
        sched_id = nf.basic_scheduler(model_ref, steps or preset.get("steps", 20),
                                       denoise, scheduler="simple", node_id="64")
        noise_id = nf.random_noise(seed, node_id="65")
        samp_id = nf.sampler_custom_advanced(
            [noise_id, 0], [guider_id, 0], [sampler_sel, 0],
            [sched_id, 0], [enc_id, 0], node_id="9",
        )
    else:
        samp_id = nf.ksampler(
            model_ref,
            [cn_apply_id, 0], [cn_apply_id, 1], [enc_id, 0],
            seed, steps or preset["steps"], cfg or preset["cfg"],
            preset.get("sampler", "euler"), preset.get("scheduler", "normal"),
            denoise, node_id="9",
        )
    dec_id = nf.vae_decode([samp_id, 0], vae_ref, node_id="10")
    # Colorize keeps dimensions — no resize needed.
    final_ref = [dec_id, 0]
    if sam3_prompt:
        _mask = build_sam3_mask(nf, img_ref, sam3_prompt,
                                 invert=sam3_invert,
                                 confidence=sam3_confidence,
                                 mask_expand=sam3_expand,
                                 mask_blur=sam3_blur)
        final_ref = apply_sam3_scope(nf, final_ref, img_ref, _mask)
    nf.save_image(final_ref, "spellcaster_colorize", node_id="11")

    # Optional second ControlNet (Depth)
    if guide_modes and controlnet_2 and controlnet_2.get("mode", "Off") != "Off":
        cn2_pos, cn2_neg = inject_controlnet(
            nf, controlnet_2, guide_modes, arch_key, img_ref,
            [cn_apply_id, 0], [cn_apply_id, 1], cn_base_id=20,
        )
        nf.patch_input("9", "positive", cn2_pos)
        nf.patch_input("9", "negative", cn2_neg)

    return nf.build()


# ═══════════════════════════════════════════════════════════════════════════
#  Generic ControlNet Generation
# ═══════════════════════════════════════════════════════════════════════════

def build_controlnet_gen(image_filename, preprocessor_type, controlnet_model,
                          preset, prompt, negative, seed, width, height,
                          steps, cfg, sampler, scheduler, cn_strength=0.8,
                          loras=None):
    """Text-to-image generation with ControlNet spatial constraint.

    Generates an image from scratch (empty latent) with spatial guidance from
    a ControlNet. Useful for creating new images that match a reference structure
    (pose, composition, depth, edges, etc.) while respecting a text prompt.

    Pipeline:
      1. Load input image and preprocess it (canny edges, depth map, pose skeleton, etc.)
      2. Load model, CLIP, VAE
      3. Apply LoRA chain if provided
      4. Load ControlNet model
      5. Encode positive and negative prompts
      6. Apply ControlNet to create spatial-guided conditioning
      7. Generate from empty latent with ControlNet conditioning
      8. Decode and save

    Args:
        image_filename (str): Reference image for spatial structure (will be preprocessed)
        preprocessor_type (str): Type of preprocessing, e.g. "canny", "depth", "openpose",
                               "midas", "mlsd", "anime_lineart", etc.
                               The preprocessor extracts spatial structure from the image.
        controlnet_model (str): ControlNet model file trained on preprocessor outputs,
                              e.g. "control_canny-fp16.safetensors"
        preset (dict): Sampling preset (architecture, dimensions, etc.)
        prompt (str): Text description of what to generate
        negative (str): What to avoid
        seed (int): Random seed
        width (int): Output image width
        height (int): Output image height
        steps (int): Diffusion steps
        cfg (float): Classifier-free guidance scale
        sampler (str): Sampler type, e.g. "euler", "dpmpp_2m"
        scheduler (str): Scheduler, e.g. "normal", "karras"
        cn_strength (float): ControlNet influence 0.0-1.0 (default 0.8)
                           0.0 = ignore reference structure
                           1.0 = strictly follow reference structure
        loras (list, optional): LoRA chain

    Returns:
        dict: ComfyUI workflow

    Example Use Cases:
      - Canny edges: "Create new photo with same pose as reference"
      - OpenPose: "Recreate composition with different person"
      - Depth map: "Generate 3D-aware version of reference scene"
      - Midas depth: "Fill scene with new content, same depth structure"

    Node IDs:
      - "1": load reference image
      - "2": preprocessor (extracts spatial structure)
      - "3": model/clip/vae loaders
      - "4": controlnet_loader
      - "5","6": positive/negative text encoding
      - "7": controlnet_apply_advanced (spatial conditioning)
      - "8": empty_latent_image (start from noise, not image)
      - "9": ksampler (with ControlNet guidance)
      - "10": vae_decode
      - "11": save_image

    Differences from img2img + ControlNet:
      - Uses empty latent (txt2img style) instead of image encoding
      - Always generates from scratch; denoise = 1.0 (no input preservation)
      - Full canvas generation, not refinement
      - Preprocessor extracts spatial constraints from reference, doesn't use it directly
    """
    nf = NodeFactory()
    arch_key = preset.get("arch", "sdxl")

    img_id = nf.load_image(image_filename, node_id="1")
    pre_id = nf.preprocessor(preprocessor_type, [img_id, 0], node_id="2")

    model_ref, clip_ref, vae_ref = load_model_stack(nf, preset, "3")
    model_ref, clip_ref, _trig = inject_lora_chain(nf, loras or [], model_ref, clip_ref)

    cn_loader_id = nf.controlnet_loader(controlnet_model, node_id="4")

    pos_id, neg_id = encode_prompts(nf, arch_key, clip_ref,
                                     prompt, negative,
                                     pos_id="5", neg_id="6")

    cn_apply_id = nf.controlnet_apply_advanced(
        [pos_id, 0], [neg_id, 0],
        [cn_loader_id, 0], [pre_id, 0],
        cn_strength, 0.0, 1.0, node_id="7",
    )

    empty_id = nf.empty_latent_image(width, height, 1, node_id="8")
    is_klein = preset.get("arch") == "flux2klein"
    if is_klein:
        guider_id = nf.cfg_guider(model_ref, [cn_apply_id, 0], [cn_apply_id, 1],
                                  cfg, node_id="60")
        sampler_sel = nf.ksampler_select("euler", node_id="61")
        sched_id = nf.basic_scheduler(model_ref, steps, 1.0,
                                       scheduler="simple", node_id="62")
        noise_id = nf.random_noise(seed, node_id="63")
        samp_id = nf.sampler_custom_advanced(
            [noise_id, 0], [guider_id, 0], [sampler_sel, 0],
            [sched_id, 0], [empty_id, 0], node_id="9",
        )
    else:
        samp_id = nf.ksampler(
            model_ref,
            [cn_apply_id, 0], [cn_apply_id, 1], [empty_id, 0],
            seed, steps, cfg, sampler, scheduler, 1.0, node_id="9",
        )
    dec_id = nf.vae_decode([samp_id, 0], vae_ref, node_id="10")
    nf.save_image([dec_id, 0], "spellcaster_controlnet", node_id="11")

    return nf.build()


# ═══════════════════════════════════════════════════════════════════════════
#  IC-Light Relighting
# ═══════════════════════════════════════════════════════════════════════════

def build_iclight(image_filename, ckpt_name, prompt, negative, seed,
                   multiplier=0.18, steps=20, cfg=2.0,
                   sampler="euler", scheduler="normal", loras=None,
                   normal_map_filename=None,
                   sam3_prompt=None, sam3_invert=False,
                   sam3_confidence=0.6, sam3_expand=4, sam3_blur=4):
    """IC-Light relighting: adjust light sources and illumination.

    When sam3_prompt is set, the transform is composited back onto the original
    using a SAM3 mask so only the described region changes.

    IC-Light is a specialized model for controlling and adjusting light in images.
    It enables repositioning light sources, changing lighting direction, and adjusting
    illumination intensity while preserving object structure and content.

    Pipeline:
      1. Load image and SD-1.5 checkpoint (IC-Light works with SD-1.5)
      2. Load and apply IC-Light specialized UNET
      3. Encode positive and negative text prompts
      4. Prepare IC-Light conditioning (combines text encoding with image latent)
      5. Sample with IC-Light conditioning
      6. Decode and save

    Args:
        image_filename (str): Input image to relight
        ckpt_name (str): SD-1.5 checkpoint file name
        prompt (str): Lighting description, e.g. "bright sunlight from left",
                     "soft diffuse light", "neon red and blue lighting"
        negative (str): Lighting to avoid
        seed (int): Random seed
        multiplier (float): Light intensity multiplier (default 0.18)
                          Controls how strongly IC-Light conditions the sampling
                          0.0 = ignore light prompt
                          1.0+ = aggressive lighting changes
        steps (int): Diffusion steps, typically 15-25 (default 20)
        cfg (float): Classifier-free guidance, typically 1.0-5.0 (default 2.0)
                    IC-Light works best with moderate guidance
        sampler (str): Sampler type, e.g. "euler", "dpmpp_2m" (default "euler")
        scheduler (str): Scheduler, e.g. "normal", "karras" (default "normal")

    Returns:
        dict: ComfyUI workflow

    Node IDs:
      - "1": load input image
      - "2": checkpoint_loader (SD-1.5)
      - "3": load_and_apply_iclight_unet (replaces standard UNET)
      - "4","5": positive/negative text encoding
      - "6": iclight_conditioning (special conditioning that incorporates image)
      - "7": ksampler (runs diffusion with IC-Light conditioning)
      - "8": vae_decode
      - "9": save_image

    IC-Light Conditioning (node "6"):
      Outputs 3 values (not 1 like CLIP encode):
        [0] = positive conditioning (text-guided)
        [1] = negative conditioning (text-guided)
        [2] = image latent (used as control signal)
      All three are passed to the KSampler.

    Multiplier Effects:
      - 0.1-0.15: Subtle lighting adjustments, preserves original ambiance
      - 0.18-0.25: Moderate lighting changes, noticeable but not jarring
      - 0.4-0.6: Strong lighting effects, significant relight
      - >1.0: Very aggressive, may destabilize generation

    Example Prompts:
      - "key light from upper left, fill light from right, warm color temperature"
      - "top-down volumetric light rays, golden hour lighting, hazy atmosphere"
      - "cold blue darkness, single LED light source"
      - "neon glow, cyberpunk lighting, reflections in wet surface"

    Gotchas:
      - IC-Light best works with clear, well-lit input images
      - Very dark images may not relight well
      - Low CFG (1.0-2.0) recommended; high CFG may cause artifacts
      - Multiplier > 1.0 can cause generation instability
      - Works only with SD-1.5, not SDXL or Flux
      - Prompt quality significant; vague prompts = undefined lighting

    Implementation Notes:
      - IC-Light only works with SD1.5 models
      - Uses CheckpointLoaderSimple to load SD-1.5 checkpoint
      - ICLightConditioning.foreground expects LATENT, not IMAGE
    """
    nf = NodeFactory()
    img_id = nf.load_image(image_filename, node_id="1")

    # Load SD1.5 checkpoint
    ckpt_id = nf.checkpoint_loader(ckpt_name, node_id="2")
    model_ref = [ckpt_id, 0]
    clip_ref = [ckpt_id, 1]
    vae_ref = [ckpt_id, 2]

    # LoRA chain
    if loras:
        model_ref, clip_ref, _trig = inject_lora_chain(nf, loras, model_ref, clip_ref, base_id=100)

    # VAEEncode foreground to latent (ICLightConditioning expects LATENT)
    latent_id = nf.vae_encode([img_id, 0], vae_ref, node_id="10")

    # Load and apply IC-Light UNET
    # FBC model required when using opt_background (normal map / background latent)
    # FC model for foreground-only relighting (no background guidance)
    iclight_model = ("SD-1.5\\iclight_sd15_fbc.safetensors" if normal_map_filename
                     else "SD-1.5\\iclight_sd15_fc.safetensors")
    iclight_id = nf.load_and_apply_iclight_unet(
        model_ref, iclight_model, node_id="3",
    )

    # Text encoding
    pos_id = nf.clip_encode(clip_ref, prompt, node_id="4")
    neg_id = nf.clip_encode(clip_ref, negative, node_id="5")

    # Optional normal map → encode as background latent for surface guidance
    normal_bg_ref = None
    if normal_map_filename:
        normal_img_id = nf.load_image(normal_map_filename, node_id="50")
        normal_latent_id = nf.vae_encode([normal_img_id, 0], vae_ref, node_id="51")
        normal_bg_ref = [normal_latent_id, 0]

    # ICLightConditioning (with optional normal map as background geometry)
    cond_id = nf.iclight_conditioning(
        [pos_id, 0], [neg_id, 0], vae_ref, [latent_id, 0],
        multiplier=multiplier, opt_background_ref=normal_bg_ref,
        node_id="6",
    )

    # Sample
    samp_id = nf.ksampler(
        [iclight_id, 0],
        [cond_id, 0], [cond_id, 1], [cond_id, 2],
        seed, steps, cfg, sampler, scheduler, 1.0, node_id="7",
    )
    dec_id = nf.vae_decode([samp_id, 0], vae_ref, node_id="8")
    # IC-Light preserves dimensions — no resize needed.
    final_ref = [dec_id, 0]
    if sam3_prompt:
        _mask = build_sam3_mask(nf, [img_id, 0], sam3_prompt,
                                 invert=sam3_invert,
                                 confidence=sam3_confidence,
                                 mask_expand=sam3_expand,
                                 mask_blur=sam3_blur)
        final_ref = apply_sam3_scope(nf, final_ref, [img_id, 0], _mask)
    nf.save_image(final_ref, "spellcaster_iclight", node_id="9")

    return nf.build()


# ═══════════════════════════════════════════════════════════════════════════
#  SUPIR AI Restoration
# ═══════════════════════════════════════════════════════════════════════════

def build_supir(image_filename, supir_model, sdxl_model, prompt, seed,
                 denoise=0.3, steps=45, scale_by=1.0,
                 controlnet=None, controlnet_2=None, guide_modes=None):
    """SUPIR AI restoration - specialized 5-stage restoration pipeline.

    SUPIR (Super Image Restoration) is a specialized diffusion model for photo
    restoration. It works in 5 stages: loads image, does first-stage denoising,
    conditions on text + image features, applies main restoration sampling, then
    decodes using tiled VAE (for memory efficiency on large images).

    Optional secondary pass: SDXL refinement with optional ControlNet guidance.

    Pipeline (Main Pass):
      1. Load SUPIR model + SDXL backbone (they're paired)
      2. Load input image
      3. First-stage processing (initial denoising; output used as reference)
      4. Conditioner: encodes text prompt + SDXL features
      5. Main restoration sampling (EDM-based with custom schedules)
      6. Tiled VAE decode (memory-efficient for 4K+)

    Pipeline (Optional SDXL Refinement):
      7. Load SDXL checkpoint for secondary pass
      8. Encode SUPIR output with SDXL CLIP
      9. Optional ControlNet preprocessing
      10. Apply ControlNet to SDXL conditioning
      11. Re-sample SUPIR output through SDXL at low denoise (0.12)
      12. Decode and save refined output

    Args:
        image_filename (str): Path to damaged/low-quality image
        supir_model (str): SUPIR model file name
        sdxl_model (str): SDXL checkpoint file (paired with SUPIR model)
        prompt (str): Restoration guidance prompt (e.g., "high quality, sharp focus")
        seed (int): Random seed
        denoise (float): Restoration intensity 0.0-1.0 (default 0.3)
          - 0.0: minimal change
          - 0.3-0.5: balanced restoration
          - 1.0: aggressive restoration (may add artifacts)
        steps (int): Main sampling steps, typically 20-45 (default 45)
        scale_by (float): Internal upscaling during restoration (default 1.0)
          - 1.0: no upscaling, pure restoration
          - 1.5-2.0: upscale + restore (slower, memory-hungry)
          - >1.5 uses TiledRestoreEDMSampler instead of RestoreEDMSampler
        controlnet (dict, optional): SDXL ControlNet for refinement pass
        controlnet_2 (dict, optional): Second ControlNet in refinement
        guide_modes (dict, optional): ControlNet preprocessor info

    Returns:
        dict: ComfyUI workflow with SUPIR main + optional SDXL refinement

    The Denoise-to-Schedule Mapping (internal logic):
      SUPIR maps denoise parameter to different CFG + control scales:
      - denoise → control_start/control_end (how much to control each step)
      - denoise → cfg_start/cfg_end (how much text guidance each step)
      Example: denoise=0.3 yields moderate control, low CFG (4.0-2.0 range)

    Node IDs (Main Pass):
      - "1": input image
      - "10": supir_model_loader (returns both SUPIR model [0] and SDXL backbone [1])
      - "20": supir_first_stage (initial denoising)
      - "30": supir_conditioner (text + features)
      - "40": supir_sample (main restoration)
      - "50": supir_decode (tiled VAE)
      - "60": save_image

    Node IDs (SDXL Refinement, if used):
      - "70"-"72": SDXL checkpoint + CLIP encode
      - "73"-"82": Optional ControlNet(s)
      - "76"-"78": Secondary SDXL sampling + decode
      - "80"-"82": Optional second ControlNet in refinement

    Gotchas:
      - Very slow (45 steps + optional refinement = minutes per image)
      - High memory usage; scale_by > 1.0 requires 24GB+ VRAM
      - Denoise > 0.5 may add artifacts (hallucination)
      - For tiled operation (scale_by >= 1.5), uses TiledRestoreEDMSampler
      - ControlNet in refinement is applied to SUPIR output (not original image)
      - Default negative prompt is embedded (long, specific to restoration)
    """
    nf = NodeFactory()

    neg_prompt = (
        "painting, illustration, drawing, art, sketch, anime, cartoon, 3d render, "
        "CG, low quality, blurry, noisy, oversmoothed, plastic skin, washed out, "
        "oversaturated, artifacts, compression, jpeg, watermark, text, logo, "
        "deformed, distorted, disfigured, bad anatomy, extra limbs"
    )

    # Map denoise to control_scale / CFG ranges
    control_start = max(0.0, 1.0 - denoise * 1.5)
    control_end = min(1.0, denoise * 2.0 + 0.4)
    cfg_start = 4.0 + denoise * 2.0
    cfg_end = max(1.5, 4.0 - denoise)
    sampler_type = "TiledRestoreEDMSampler" if scale_by >= 1.5 else "RestoreEDMSampler"

    # Stage 0: Load input
    img_id = nf.load_image(image_filename, node_id="1")

    # Stage 1: Load SUPIR model + SDXL backbone
    loader_id = nf.supir_model_loader(supir_model, sdxl_model, node_id="10")

    # Stage 2: First-stage denoising
    first_id = nf.supir_first_stage(
        [loader_id, 1], [img_id, 0], node_id="20",
    )

    # Stage 3: Conditioning
    cond_id = nf.supir_conditioner(
        [loader_id, 0], [first_id, 2],
        positive_prompt=prompt.strip() or "high quality, detailed, sharp focus, professional photograph, natural colors, clean",
        negative_prompt=neg_prompt, node_id="30",
    )

    # Stage 4: Main restoration sampling
    sample_id = nf.supir_sample(
        [loader_id, 0], [first_id, 2],
        [cond_id, 0], [cond_id, 1],
        seed, steps,
        cfg_scale_start=cfg_start, cfg_scale_end=cfg_end,
        edm_s_churn=5, s_noise=1.003, dpmpp_eta=1.0,
        control_scale_start=control_start, control_scale_end=control_end,
        restore_cfg=-1.0, keep_model_loaded=False,
        sampler=sampler_type, node_id="40",
    )

    # Stage 5: Tiled VAE decode
    decode_id = nf.supir_decode(
        [first_id, 0], [sample_id, 0], node_id="50",
    )

    nf.save_image([decode_id, 0], "spellcaster_supir", node_id="60")

    # Optional ControlNet refinement post-pass
    if guide_modes and controlnet and controlnet.get("mode", "Off") != "Off":
        guide = guide_modes.get(controlnet["mode"])
        if guide:
            cn_model = guide["cn_models"].get("sdxl", guide["cn_models"].get("sd15"))
            if cn_model:
                # Load SDXL checkpoint for refinement
                ref_ckpt_id = nf.checkpoint_loader(sdxl_model, node_id="70")
                ref_pos_id = nf.clip_encode(
                    [ref_ckpt_id, 1],
                    prompt.strip() or "high quality, detailed, sharp",
                    node_id="71",
                )
                ref_neg_id = nf.clip_encode(
                    [ref_ckpt_id, 1],
                    "blurry, noisy, artifacts, low quality",
                    node_id="72",
                )

                # Preprocess SUPIR output for ControlNet
                preprocessor = guide.get("preprocessor")
                cn_image_ref = [decode_id, 0]
                if preprocessor:
                    pre_id = nf.preprocessor(preprocessor, [decode_id, 0], node_id="73")
                    cn_image_ref = [pre_id, 0]

                cn_loader_id = nf.controlnet_loader(cn_model, node_id="74")
                cn_apply_id = nf.controlnet_apply_advanced(
                    [ref_pos_id, 0], [ref_neg_id, 0],
                    [cn_loader_id, 0], cn_image_ref,
                    controlnet["strength"], 0.0, 1.0, node_id="75",
                )

                # Encode SUPIR output → sample at low denoise → decode
                ref_enc_id = nf.vae_encode([decode_id, 0], [ref_ckpt_id, 2], node_id="76")
                ref_samp_id = nf.ksampler(
                    [ref_ckpt_id, 0],
                    [cn_apply_id, 0], [cn_apply_id, 1], [ref_enc_id, 0],
                    seed + 1, 15, 4.0,
                    "dpmpp_2m_sde", "karras", 0.12, node_id="77",
                )
                ref_dec_id = nf.vae_decode([ref_samp_id, 0], [ref_ckpt_id, 2], node_id="78")

                # Optional second ControlNet in refinement
                if controlnet_2 and controlnet_2.get("mode", "Off") != "Off":
                    guide2 = guide_modes.get(controlnet_2["mode"])
                    if guide2:
                        cn_model_2 = guide2["cn_models"].get("sdxl", guide2["cn_models"].get("sd15"))
                        if cn_model_2:
                            pre2 = guide2.get("preprocessor")
                            cn_img2 = [decode_id, 0]
                            if pre2:
                                pre2_id = nf.preprocessor(pre2, [decode_id, 0], node_id="80")
                                cn_img2 = [pre2_id, 0]
                            cn_loader2_id = nf.controlnet_loader(cn_model_2, node_id="81")
                            cn_apply2_id = nf.controlnet_apply_advanced(
                                [cn_apply_id, 0], [cn_apply_id, 1],
                                [cn_loader2_id, 0], cn_img2,
                                controlnet_2["strength"], 0.0, 1.0, node_id="82",
                            )
                            nf.patch_input("77", "positive", [cn_apply2_id, 0])
                            nf.patch_input("77", "negative", [cn_apply2_id, 1])

                # Replace output to use refined image
                nf.patch_input("60", "images", [ref_dec_id, 0])

    return nf.build()


# ═══════════════════════════════════════════════════════════════════════════
#  Inpaint — regenerate masked region
# ═══════════════════════════════════════════════════════════════════════════

def build_inpaint(image_filename, mask_filename, preset, prompt_text,
                   negative_text, seed, loras=None,
                   controlnet=None, controlnet_2=None, guide_modes=None,
                   sam3_prompt=None, sam3_invert=False,
                   sam3_confidence=0.6, sam3_expand=4, sam3_blur=4):
    """Inpainting: regenerate masked region using diffusion.

    Selectively regenerates only the masked area of an image while preserving
    the unmasked regions. Useful for object removal, editing, and corrections.

    Pipeline:
      1. Load model, CLIP, VAE
      2. Apply LoRA chain if provided
      3. Load image and mask; convert mask to MASK type
      4. Scale both image and mask to working resolution
      5. Encode prompts
      6. VAE encode scaled image → latent
      7. Grow/shrink mask to prevent visible edges
      8. Encode mask to latent space
      9. Mix original latent with noise at masked region (MASK_BLUR)
      10. KSampler restricted to masked region
      11. Scale output back to original dimensions
      12. Save result
      13. Optional ControlNet for spatial guidance

    Args:
        image_filename (str): Path to input image
        mask_filename (str): Path to mask image (white = inpaint, black = preserve)
        preset (dict): Sampling preset (see build_img2img for contents)
        prompt_text (str): What to generate in masked region
        negative_text (str): Things to avoid
        seed (int): Random seed
        loras (list, optional): LoRA chain
        controlnet (dict, optional): Spatial guidance
        controlnet_2 (dict, optional): Second ControlNet
        guide_modes (dict, optional): ControlNet preprocessor info

    Returns:
        dict: ComfyUI workflow

    Key Difference from img2img:
      - Uses MASK_BLUR node to grow mask borders (prevents visible seams)
      - Only diffuses latents at masked region
      - Scales back to original resolution post-sampling (img2img uses fixed resolution)

    Node IDs:
      - "4": input image
      - "5": input mask
      - "6": KSampler (respects mask)
      - "51": mask converted to MASK type
      - "90": original image size (for post-scaling)

    Gotchas:
      - Mask must be pure black/white (no gray); will be thresholded
      - Mask edges often show visible seams; MASK_BLUR helps but not foolproof
      - Masked area sometimes shows "corruption" at edges; lower cfg or increase blur
      - Denoise < 1.0 in masked area may not fully regenerate detail
    """
    nf = NodeFactory()

    # Model loading
    model_ref, clip_ref, vae_ref = load_model_stack(nf, preset, "1")
    model_ref, clip_ref, _trig = inject_lora_chain(nf, loras or [], model_ref, clip_ref)

    # Load image and determine mask source.
    # Precedence: mask_filename (user override) → sam3_prompt → error.
    img_id = nf.load_image(image_filename, node_id="4")
    img_ref = [img_id, 0]

    # Encode prompts
    arch_key = preset.get("arch", "sdxl")
    pos_id, neg_id = encode_prompts(nf, arch_key, clip_ref,
                                     prompt_text, negative_text,
                                     pos_id="2", neg_id="3")

    # Get original size for restoring after sampling
    size_id = nf.get_image_size_plus(img_ref, node_id="90")

    # Scale image to working resolution (always needed for sampler).
    scaled_img_id = nf.image_scale(
        img_ref, preset["width"], preset["height"],
        upscale_method="lanczos", crop="disabled", node_id="91",
    )

    if mask_filename:
        # File-loaded mask (user-painted selection).
        mask_img_id = nf.load_image(mask_filename, node_id="5")
        # Full-resolution MASK (kept for symmetry; currently unused by sampler).
        mask_id = nf.image_to_mask([mask_img_id, 0], "red", node_id="51")
        # Scale the mask IMAGE to working resolution then convert to MASK.
        scaled_mask_img_id = nf.image_scale(
            [mask_img_id, 0], preset["width"], preset["height"],
            upscale_method="nearest-exact", crop="disabled", node_id="92",
        )
        scaled_mask_id = nf.image_to_mask([scaled_mask_img_id, 0], "red", node_id="52")
        scaled_mask_ref = [scaled_mask_id, 0]
    elif sam3_prompt:
        # SAM3 mask generated server-side against the WORKING-RESOLUTION
        # image — so dimensions match the latent exactly. Helper returns
        # MASK-typed ref directly; no image_to_mask conversion needed.
        scaled_mask_ref = build_sam3_mask(nf, [scaled_img_id, 0], sam3_prompt,
                                           invert=sam3_invert,
                                           confidence=sam3_confidence,
                                           mask_expand=sam3_expand,
                                           mask_blur=sam3_blur)
    else:
        raise ValueError("build_inpaint requires either mask_filename or sam3_prompt")

    # VAE encode → SetLatentNoiseMask → sample
    enc_id = nf.vae_encode([scaled_img_id, 0], vae_ref, node_id="6")
    masked_id = nf.set_latent_noise_mask([enc_id, 0], scaled_mask_ref, node_id="7")

    is_klein = arch_key == "flux2klein"
    if is_klein:
        ref_pos = nf.reference_latent([pos_id, 0], [enc_id, 0], node_id="60")
        ref_neg = nf.reference_latent([neg_id, 0], [enc_id, 0], node_id="61")
        guider_id = nf.cfg_guider(model_ref, [ref_pos, 0], [ref_neg, 0],
                                  preset.get("cfg", 1.0), node_id="62")
        sampler_sel = nf.ksampler_select("euler", node_id="63")
        sched_id = nf.basic_scheduler(model_ref, preset.get("steps", 20),
                                       preset.get("denoise", 0.65),
                                       scheduler="simple", node_id="64")
        noise_id = nf.random_noise(seed, node_id="65")
        samp_id = nf.sampler_custom_advanced(
            [noise_id, 0], [guider_id, 0], [sampler_sel, 0],
            [sched_id, 0], [masked_id, 0], node_id="8",
        )
    else:
        samp_id = nf.ksampler(
            model_ref,
            [pos_id, 0], [neg_id, 0], [masked_id, 0],
            seed, preset["steps"], preset["cfg"],
            preset.get("sampler", "euler"), preset.get("scheduler", "normal"),
            preset.get("denoise", 0.65), node_id="8",
        )

    # Decode → restore to original size → save
    dec_id = nf.vae_decode([samp_id, 0], vae_ref, node_id="9")
    restored_id = nf.image_scale(
        [dec_id, 0], [size_id, 0], [size_id, 1],
        upscale_method="lanczos", crop="disabled", node_id="95",
    )
    nf.save_image([restored_id, 0], "gimp_inpaint", node_id="10")

    # ControlNet injection (optional)
    if guide_modes and controlnet and controlnet.get("mode", "Off") != "Off":
        cn_pos, cn_neg = inject_controlnet(
            nf, controlnet, guide_modes, arch_key, img_ref,
            [pos_id, 0], [neg_id, 0], cn_base_id=20,
        )
        nf.patch_input("8", "positive", cn_pos)
        nf.patch_input("8", "negative", cn_neg)

    if guide_modes and controlnet_2 and controlnet_2.get("mode", "Off") != "Off":
        prev_pos = [str(22), 0] if nf.has_node("22") else [pos_id, 0]
        prev_neg = [str(22), 1] if nf.has_node("22") else [neg_id, 0]
        cn2_pos, cn2_neg = inject_controlnet(
            nf, controlnet_2, guide_modes, arch_key, img_ref,
            prev_pos, prev_neg, cn_base_id=30,
        )
        nf.patch_input("8", "positive", cn2_pos)
        nf.patch_input("8", "negative", cn2_neg)

    return nf.build()


# ═══════════════════════════════════════════════════════════════════════════
#  Outpaint — extend canvas
# ═══════════════════════════════════════════════════════════════════════════

def build_outpaint(image_filename, preset, prompt_text, negative_text, seed,
                    left, top, right, bottom, feathering, loras=None,
                    controlnet=None, guide_modes=None):
    """Canvas extension via outpainting.

    Extends an image beyond its original boundaries by generating new content
    in the expanded regions. The original image is preserved (at reduced strength),
    and the new pixels are filled with AI-generated content matching the prompt
    and visual style of the original.

    Pipeline:
      1. Load model, CLIP, VAE
      2. Apply LoRA chain if provided
      3. Load input image
      4. Pad image with feathered borders (left, top, right, bottom)
      5. Encode prompts
      6. VAE encode padded image → latent
      7. Create noise mask (original region = low noise, padded region = high noise)
      8. Set latent noise mask (tells sampler where to preserve vs. regenerate)
      9. KSampler respects the mask, generating only in padded regions
      10. Decode and crop back to original size
      11. Save result

    Args:
        image_filename (str): Input image to extend
        preset (dict): Sampling preset (architecture, steps, cfg, etc.)
        prompt_text (str): Description for extended content
        negative_text (str): Things to avoid in extension
        seed (int): Random seed
        left (int): Pixels to add on left side
        top (int): Pixels to add on top
        right (int): Pixels to add on right side
        bottom (int): Pixels to add on bottom
        feathering (int): Blend radius at original/generated boundary (default ~10)
                         Prevents visible seams; higher = softer transition
        loras (list, optional): LoRA chain
        controlnet (dict, optional): Spatial guidance (optional)
        guide_modes (dict, optional): ControlNet preprocessor info

    Returns:
        dict: ComfyUI workflow

    How It Works (Noise Masking):
      1. image_pad_for_outpaint(): Creates padded image + binary mask
         - Mask[0] = padded image (original + extended border)
         - Mask[1] = noise mask (0 in original region, 1 in padded region)
      2. set_latent_noise_mask(): Applies mask to latent space
         - KSampler will inject noise heavily in masked (=1) regions
         - KSampler will preserve signal in unmasked (=0) regions
      3. Denoise value (from preset) controls preservation:
         - denoise=0.5: Keep 50% of original signal, regenerate 50%
         - denoise=1.0: Full regeneration even in original region (seams!)

    Feathering Effect:
      The feathering parameter blurs the boundary mask to prevent hard edges:
      - feathering=0: Sharp visible seam at boundary
      - feathering=10: Soft gradual blend (recommended)
      - feathering=20+: Very soft, may blur original image boundary slightly

    Node IDs:
      - "4": input image
      - "5": padded image + mask
      - "6": VAE encode
      - "7": set_latent_noise_mask (tells sampler preserve/regenerate regions)
      - "8": ksampler (respects mask)
      - "9": vae_decode
      - "10": crop_to_original_size
      - "11": save_image

    Gotchas:
      - Denoise > 0.8 causes visible seams (original area gets regenerated)
      - Feathering too low (< 5) shows hard boundaries
      - Feathering too high (> 30) may blur original content
      - Prompt quality critical; vague prompts = incoherent extension
      - Large padding (> 512 pixels per side) may cause memory issues
      - Sky/background extensions often work better than complex foreground
    """
    nf = NodeFactory()
    arch_key = preset.get("arch", "sdxl")
    is_klein = arch_key == "flux2klein"

    # Model loading
    model_ref, clip_ref, vae_ref = load_model_stack(nf, preset, "1")
    model_ref, clip_ref, _trig = inject_lora_chain(nf, loras or [], model_ref, clip_ref)

    # Load and pad image
    img_id = nf.load_image(image_filename, node_id="4")
    pad_id = nf.image_pad_for_outpaint(
        [img_id, 0], left, top, right, bottom, feathering, node_id="5",
    )
    padded_ref = [pad_id, 0]

    # Klein/Flux2 uses custom_advanced sampler with ReferenceLatent
    if is_klein:
        pos_id = nf.clip_encode(clip_ref, prompt_text, node_id="2")
        neg_id = nf.conditioning_zero_out([pos_id, 0], node_id="3")

        # Klein Enhancer chain for quality boost
        enhanced_model = _klein_enhance_model(nf, model_ref, [pos_id, 0],
                                               node_base_id=960)

        # Encode ORIGINAL (un-padded) image for ReferenceLatent context
        orig_enc_id = nf.vae_encode([img_id, 0], vae_ref, node_id="6o")
        # Encode PADDED image for the sampler latent (with noise mask)
        enc_id = nf.vae_encode(padded_ref, vae_ref, node_id="6")
        masked_id = nf.set_latent_noise_mask([enc_id, 0], [pad_id, 1], node_id="7")
        # ReferenceLatent uses the ORIGINAL image — not the padded one
        ref_pos_id = nf.reference_latent([pos_id, 0], [orig_enc_id, 0], node_id="20")
        ref_neg_id = nf.reference_latent([neg_id, 0], [orig_enc_id, 0], node_id="21")
        # Custom sampler pipeline with enhanced model
        guider_id = nf.cfg_guider(enhanced_model, [ref_pos_id, 0], [ref_neg_id, 0],
                                  preset.get("cfg", 1.0), node_id="30")
        sampler_id = nf.ksampler_select("euler", node_id="31")
        sched_id = nf.basic_scheduler(enhanced_model, preset.get("steps", 20),
                                       0.92, scheduler="simple", node_id="32")
        noise_id = nf.random_noise(seed, node_id="33")
        samp_id = nf.sampler_custom_advanced(
            [noise_id, 0], [guider_id, 0], [sampler_id, 0],
            [sched_id, 0], [masked_id, 0], node_id="8",
        )
    else:
        pos_id, neg_id = encode_prompts(nf, arch_key, clip_ref,
                                         prompt_text, negative_text,
                                         pos_id="2", neg_id="3")
        enc_id = nf.vae_encode(padded_ref, vae_ref, node_id="6")
        masked_id = nf.set_latent_noise_mask([enc_id, 0], [pad_id, 1], node_id="7")
        samp_id = nf.ksampler(
            model_ref,
            [pos_id, 0], [neg_id, 0], [masked_id, 0],
            seed, preset["steps"], preset["cfg"],
            preset.get("sampler", "euler"), preset.get("scheduler", "normal"),
            0.85, node_id="8",
        )

    dec_id = nf.vae_decode([samp_id, 0], vae_ref, node_id="9")
    nf.save_image([dec_id, 0], "spellcaster_outpaint", node_id="10")

    # ControlNet injection (optional — skipped for Klein which can't use CN)
    if (guide_modes and controlnet and controlnet.get("mode", "Off") != "Off"
            and arch_key not in ("flux2klein", "flux_kontext", "chroma")):
        # cn_base_id=40 avoids collision with Klein's reference_latent at 20-21
        cn_pos, cn_neg = inject_controlnet(
            nf, controlnet, guide_modes, arch_key, padded_ref,
            [pos_id, 0] if isinstance(pos_id, str) else pos_id,
            [neg_id, 0] if isinstance(neg_id, str) else neg_id,
            cn_base_id=40,
        )
        nf.patch_input("8", "positive", cn_pos)
        nf.patch_input("8", "negative", cn_neg)

    return nf.build()


# ═══════════════════════════════════════════════════════════════════════════
#  IPAdapter FaceID img2img
# ═══════════════════════════════════════════════════════════════════════════

def build_faceid_img2img(target_filename, face_ref_filename, preset,
                          prompt_text, negative_text, seed,
                          faceid_preset="FACEID PLUS V2",
                          lora_strength=0.6, weight=0.85, weight_v2=1.0,
                          denoise=None, steps=None, cfg=None,
                          loras=None):
    """IPAdapter FaceID img2img. Drop-in for _build_faceid_img2img().

    preset: dict with ckpt, arch, width, height, steps, cfg, denoise, sampler, scheduler.
    """
    nf = NodeFactory()
    steps = steps or preset["steps"]
    cfg = cfg or preset["cfg"]
    denoise = denoise or preset.get("denoise", 0.55)
    sampler = preset.get("sampler", "euler")
    scheduler = preset.get("scheduler", "normal")

    model_ref, clip_ref, vae_ref = load_model_stack(nf, preset, "1")
    model_ref, clip_ref, _trig = inject_lora_chain(nf, loras or [], model_ref, clip_ref)

    # FaceID unified loader
    faceid_loader_id = nf.ipadapter_unified_loader_faceid(
        model_ref, preset=faceid_preset, lora_strength=lora_strength,
        node_id="2",
    )

    # Load face reference and apply FaceID
    face_ref_id = nf.load_image(face_ref_filename, node_id="3")
    faceid_id = nf.ipadapter_faceid(
        [faceid_loader_id, 0], [faceid_loader_id, 1], [face_ref_id, 0],
        weight=weight, weight_faceidv2=weight_v2, node_id="4",
    )

    # Text encoding (architecture-aware: no-negative archs get zero_out)
    pos_id, neg_id = encode_prompts(nf, arch_key, clip_ref,
                                     prompt_text,
                                     negative_text or "blurry, deformed, bad anatomy",
                                     pos_id="5", neg_id="6")

    # Target image → VAE encode → sample → decode → save
    target_id = nf.load_image(target_filename, node_id="7")
    enc_id = nf.vae_encode([target_id, 0], vae_ref, node_id="8")
    is_klein = preset.get("arch") == "flux2klein"
    if is_klein:
        ref_pos = nf.reference_latent([pos_id, 0], [enc_id, 0], node_id="60")
        ref_neg = nf.reference_latent([neg_id, 0], [enc_id, 0], node_id="61")
        guider_id = nf.cfg_guider([faceid_id, 0], [ref_pos, 0], [ref_neg, 0],
                                  cfg, node_id="62")
        sampler_sel = nf.ksampler_select("euler", node_id="63")
        sched_id = nf.basic_scheduler([faceid_id, 0], steps, denoise,
                                       scheduler="simple", node_id="64")
        noise_id = nf.random_noise(seed, node_id="65")
        samp_id = nf.sampler_custom_advanced(
            [noise_id, 0], [guider_id, 0], [sampler_sel, 0],
            [sched_id, 0], [enc_id, 0], node_id="9",
        )
    else:
        samp_id = nf.ksampler(
            [faceid_id, 0],
            [pos_id, 0], [neg_id, 0], [enc_id, 0],
            seed, steps, cfg, sampler, scheduler, denoise, node_id="9",
        )
    dec_id = nf.vae_decode([samp_id, 0], vae_ref, node_id="11")
    nf.save_image([dec_id, 0], "gimp_faceid", node_id="12")

    return nf.build()


# ═══════════════════════════════════════════════════════════════════════════
#  PuLID Flux — face identity-preserving generation
# ═══════════════════════════════════════════════════════════════════════════

def build_pulid_flux(target_filename, face_ref_filename,
                      prompt_text, negative_text, seed,
                      flux_model="Flux\\FLUX1 Dev fp8.safetensors",
                      pulid_model="pulid_flux_v0.9.1.safetensors",
                      strength=0.9, steps=20, guidance=3.5,
                      denoise=0.65, width=1024, height=1024,
                      loras=None):
    """PuLID Flux — auto-detects Flux1 vs Flux2 (Klein). Drop-in for _build_pulid_flux().

    Flux.1-dev → PulidFlux* nodes
    Flux.2     → PuLID* nodes (different node family)
    """
    nf = NodeFactory()
    lower = flux_model.lower()
    is_flux2 = "flux2" in lower or "flux-2" in lower or "klein" in lower

    # UNET loader
    unet_id = nf.unet_loader(flux_model, "default", node_id="1")
    model_ref = _ref(unet_id)

    # CLIP loader (architecture-dependent)
    # Klein 9B → qwen_3_8b, Klein 4B/Base → qwen_3_4b (must match KLEIN_MODELS)
    if is_flux2:
        if "4b" in lower or "base" in lower or "schnell" in lower:
            clip_name = "qwen_3_4b.safetensors"
        else:
            clip_name = "qwen_3_8b.safetensors"
        clip_id = nf.clip_loader(clip_name, clip_type="flux2", device="default", node_id="7")
    else:
        clip_id = nf.dual_clip_loader(
            "clip_l.safetensors", "t5xxl_fp8_e4m3fn.safetensors",
            clip_type="flux", node_id="7",
        )
    clip_ref = _ref(clip_id)

    # LoRA chain
    model_ref, clip_ref, _trig = inject_lora_chain(nf, loras or [], model_ref, clip_ref)

    # PuLID loaders (different node families per architecture)
    if is_flux2:
        pulid_id = nf.pulid_model_loader(pulid_model, node_id="2")
        eva_id = nf.pulid_eva_clip_loader(node_id="3")
        face_analysis_id = nf.pulid_insightface_loader(provider="CUDA", node_id="4")
        face_ref_id = nf.load_image(face_ref_filename, node_id="5")
        apply_id = nf.apply_pulid_flux2(
            model_ref, [pulid_id, 0], [eva_id, 0],
            [face_analysis_id, 0], [face_ref_id, 0],
            strength=strength, node_id="6",
        )
    else:
        pulid_id = nf.pulid_flux_model_loader(pulid_model, node_id="2")
        eva_id = nf.pulid_flux_eva_clip_loader(node_id="3")
        face_analysis_id = nf.pulid_flux_insightface_loader(provider="CUDA", node_id="4")
        face_ref_id = nf.load_image(face_ref_filename, node_id="5")
        apply_id = nf.apply_pulid_flux(
            model_ref, [pulid_id, 0], [eva_id, 0],
            [face_analysis_id, 0], [face_ref_id, 0],
            weight=strength, node_id="6",
        )

    # Text encoding
    pos_id = nf.clip_encode(clip_ref, prompt_text, node_id="8")

    # Target image + VAE
    target_id = nf.load_image(target_filename, node_id="9")
    vae_name = "flux2-vae.safetensors" if is_flux2 else "ae.safetensors"
    vae_id = nf.vae_loader(vae_name, node_id="10")
    enc_id = nf.vae_encode([target_id, 0], [vae_id, 0], node_id="11")

    # Sample (Flux uses positive for both pos and neg)
    samp_id = nf.ksampler(
        [apply_id, 0],
        [pos_id, 0], [pos_id, 0],  # Flux: no negative, use same conditioning
        [enc_id, 0],
        seed, steps, guidance, "euler", "simple", denoise, node_id="12",
    )

    dec_id = nf.vae_decode([samp_id, 0], [vae_id, 0], node_id="13")
    nf.save_image([dec_id, 0], "gimp_pulid_flux", node_id="14")

    return nf.build()


# ═══════════════════════════════════════════════════════════════════════════
#  Klein img2img with reference image
# ═══════════════════════════════════════════════════════════════════════════

def build_klein_img2img_ref(image_filename, ref_filename, klein_model_key,
                             prompt_text, seed, steps=4, denoise=0.65,
                             guidance=1.0, enhancer_mag=1.0, enhancer_contrast=0.0,
                             ref_strength=1.0, text_ref_balance=0.5,
                             loras=None, lora_name=None, lora_strength=1.0,
                             klein_models=None, enhance=True):
    """Klein img2img with separate reference image.

    Same pipeline as build_klein_img2img but uses the reference image
    as the ReferenceLatent source instead of the main input image.
    """
    if klein_models is None:
        klein_models = KLEIN_MODELS

    # Convert single lora_name/lora_strength to loras list format
    if lora_name and not loras:
        loras = [{"name": lora_name, "strength": lora_strength}]

    km = klein_models[klein_model_key]
    nf = NodeFactory()

    # Model loaders
    unet_id = nf.unet_loader(km["unet"], "default", node_id="1")
    clip_id = nf.clip_loader(
        km.get("clip", "qwen_3_8b.safetensors"),
        clip_type="flux2", device="default", node_id="2",
    )
    vae_id = nf.vae_loader(FLUX2_VAE, node_id="3")


    # Apply LoRA chain
    if loras:
        unet_id, clip_id, _trig = inject_lora_chain(nf, loras, _ref(unet_id), _ref(clip_id), base_id=100)
        # After LoRA chain, refs are [node_id, slot] lists.
        # Leave them as-is. Use _ref() for all downstream references.
    # Text conditioning
    pos_id = nf.clip_encode(_ref(clip_id), prompt_text, node_id="4")
    neg_id = nf.conditioning_zero_out([pos_id, 0], node_id="5")

    # Main input image processing
    img_id = nf.load_image(image_filename, node_id="10")
    scaled_id = nf.image_scale_to_total_pixels([img_id, 0], megapixels=1.0, node_id="11")
    size_id = nf.get_image_size([scaled_id, 0], node_id="12")
    latent_id = nf.vae_encode([scaled_id, 0], [vae_id, 0], node_id="13")

    # Reference image (style/structure source)
    ref_id = nf.load_image(ref_filename, node_id="15")
    ref_scaled_id = nf.image_scale_to_total_pixels([ref_id, 0], megapixels=1.0, node_id="16")
    ref_latent_id = nf.vae_encode([ref_scaled_id, 0], [vae_id, 0], node_id="17")

    # ReferenceLatent: use REFERENCE image latent for conditioning guidance
    ref_pos_id = nf.reference_latent([pos_id, 0], [ref_latent_id, 0], node_id="20")
    ref_neg_id = nf.reference_latent([neg_id, 0], [ref_latent_id, 0], node_id="21")

    # Enhancer chain (Flux2Klein-Enhancer nodes for quality boost)
    model_for_guider = _ref(unet_id)
    if enhance:
        model_for_guider = _klein_enhance_model(nf, _ref(unet_id), [ref_pos_id, 0])

    # Sampler setup
    guider_id = nf.cfg_guider(model_for_guider, [ref_pos_id, 0], [ref_neg_id, 0],
                              guidance, node_id="30")
    sampler_id = nf.ksampler_select("euler", node_id="31")
    sched_id = nf.basic_scheduler(model_for_guider, steps, denoise,
                                   scheduler="simple", node_id="32")
    noise_id = nf.random_noise(seed, node_id="33")

    # Sample -- feed encoded image latent, NOT empty latent
    sample_id = nf.sampler_custom_advanced(
        [noise_id, 0], [guider_id, 0], [sampler_id, 0],
        [sched_id, 0], [latent_id, 0], node_id="40",
    )

    dec_id = nf.vae_decode([sample_id, 0], [vae_id, 0], node_id="50")
    nf.save_image([dec_id, 0], "gimp_klein_ref", node_id="51")

    return nf.build()


# ═══════════════════════════════════════════════════════════════════════════
#  Klein Headswap — ReActor face swap + Klein refinement
# ═══════════════════════════════════════════════════════════════════════════

def build_klein_headswap(target_filename, source_filename, klein_model_key,
                          prompt, seed, denoise=0.35, steps=20,
                          face_model=None, face_restore_vis=0.7,
                          codeformer_weight=0.8, loras=None, klein_models=None,
                          enhance=True):
    """Head swap with Klein Flux2 refinement.

    Two-stage head swap: first uses ReActor for fast face swap, then refines
    the result with Klein Flux2 img2img to improve quality and blend edges.

    Stage 1: ReActor Face Swap
      - Detects face in target image
      - Detects face in source image
      - Swaps source face into target using ONNX swap model
      - Applies CodeFormer restoration to improve swapped face

    Stage 2: Klein Refinement
      - Loads swapped image
      - Applies Klein Flux2 img2img at low denoise for blending
      - Text prompt guides aesthetic improvements
      - Reduces visible artifacts from face swap

    Pipeline:
      1. Load target and source images
      2. Create ReActor options (face detection)
      3. Create face boost settings (CodeFormer)
      4. Run ReActor face swap with quality restoration
      5. Load Klein model, CLIP, VAE (with matching CLIP)
      6. Scale swapped image to 1.0 megapixel
      7. Encode prompt text
      8. VAE encode swapped image → latent
      9. Run Klein img2img at low denoise for refinement
      10. Decode and save

    Args:
        target_filename (str): Image to receive new head
        source_filename (str): Image with head to swap
        klein_model_key (str): "Klein 9B", "Klein 4B", or "Klein 4B Base"
        prompt (str): Refinement guidance, e.g. "professional headshot, perfect skin,
                     sharp focus, natural lighting"
        seed (int): Random seed
        denoise (float): Klein refinement intensity 0.2-0.5 (default 0.35)
                        - 0.2: Minimal refinement, preserve swap details
                        - 0.35: Balanced refinement
                        - 0.5: Aggressive blending (risk of losing swap fidelity)
        steps (int): Klein sampling steps, typically 4-20 (default 20, more = slower/better)
        face_model (str, optional): CodeFormer model for restoration (fallback only)
        face_restore_vis (float): CodeFormer restoration blend (default 0.7)
        codeformer_weight (float): CodeFormer quality weight (default 0.8)
        klein_models (dict, optional): Klein model configuration

    Returns:
        dict: ComfyUI workflow with ReActor + Klein two-stage pipeline

    CRITICAL VAE/CLIP Pairing:
      - Klein 9B REQUIRES qwen_3_8b.safetensors
      - Klein 4B REQUIRES qwen_3_4b.safetensors
      - Mismatched pairing = degraded quality

    Node IDs:
      - "1": target image loader
      - "2": source image loader
      - "10o": reactor_options
      - "10b": reactor_face_boost (CodeFormer settings)
      - "10": reactor_face_swap_opt (the swap)
      - "11": codeformer_boost (restoration)
      - "20": klein unet_loader
      - "21": klein clip_loader
      - "22": klein vae_loader
      - "23": klein prompt encode
      - "24": klein image scale
      - "25": klein vae_encode
      - "30": klein cfg_guider
      - "31": klein sampler_select
      - "32": klein scheduler
      - "33": klein noise
      - "34": klein empty latent
      - "40": klein sampler_custom_advanced
      - "50": klein vae_decode
      - "51": save_image

    Refinement Prompt Tips:
      - Focus on aesthetics: "high quality", "professional", "sharp focus"
      - Add lighting/style: "studio lighting", "natural shadows", "cinematic"
      - Avoid contradicting swap: "same person", "consistent skin tone"
      - Example: "professional headshot, clear skin, sharp focus, natural lighting, studio quality"

    Two-Stage Benefits:
      - ReActor provides face identity swap
      - Klein refinement blends the swap and improves overall aesthetics
      - Better than ReActor alone for visible swap quality
      - Better than Klein alone if you need face identity change

    Gotchas:
      - Denoise > 0.5 risks losing swap fidelity (face changes)
      - Steps < 4 may not refine adequately
      - Both ReActor and Klein have separate failure modes:
        * ReActor fails: poor face detection or wrong face indices
        * Klein fails: prompt too aggressive or denoise too high
      - Swapped face quality depends on source image quality and angle match
    """
    if klein_models is None:
        klein_models = KLEIN_MODELS

    km = klein_models[klein_model_key]
    nf = NodeFactory()

    # Load images
    target_id = nf.load_image(target_filename, node_id="1")
    source_id = nf.load_image(source_filename, node_id="2")

    # Face swap via ReActor
    opts_id = nf.reactor_options(node_id="10o")
    boost_id = nf.reactor_face_boost(
        boost_model="codeformer-v0.1.0.pth",
        codeformer_weight=codeformer_weight, node_id="10b",
    )
    swap_id = nf.reactor_face_swap_opt(
        [target_id, 0], [source_id, 0],
        swap_model="reswapper_256.onnx",
        face_restore_model="codeformer-v0.1.0.pth",
        face_restore_visibility=face_restore_vis,
        codeformer_weight=codeformer_weight,
        options_ref=[opts_id, 0],
        face_boost_ref=[boost_id, 0],
        node_id="10",
    )

    # If saved face model, use it instead of source image
    if face_model:
        fm_id = nf.reactor_load_face_model(face_model, node_id="3")
        nf.patch_input("10", "face_model", [fm_id, 0])
        # Remove source_image from swap node (can't have both)
        # This is handled by the NodeFactory — the face_model_ref param
        # but since we already created the node, we patch it directly
        if "source_image" in nf._nodes["10"]["inputs"]:
            del nf._nodes["10"]["inputs"]["source_image"]

    # Klein refinement pass — harmonize the swapped face
    unet_id = nf.unet_loader(km["unet"], "default", node_id="20")
    clip_id = nf.clip_loader(
        km.get("clip", "qwen_3_8b.safetensors"),
        clip_type="flux2", device="default", node_id="21",
    )
    vae_id = nf.vae_loader(FLUX2_VAE, node_id="22")


    # Apply LoRA chain
    if loras:
        unet_id, clip_id, _trig = inject_lora_chain(nf, loras, _ref(unet_id), _ref(clip_id), base_id=100)
        # After LoRA chain, refs are [node_id, slot] lists.
        # Leave them as-is. Use _ref() for all downstream references.
    pos_id = nf.clip_encode(_ref(clip_id), prompt, node_id="23")
    neg_id = nf.conditioning_zero_out([pos_id, 0], node_id="24")

    # Scale swapped image + encode
    scaled_id = nf.image_scale_to_total_pixels([swap_id, 0], megapixels=1.0, node_id="30")
    size_id = nf.get_image_size([scaled_id, 0], node_id="31")
    latent_id = nf.vae_encode([scaled_id, 0], [vae_id, 0], node_id="32")

    # ReferenceLatent for context
    ref_pos_id = nf.reference_latent([pos_id, 0], [latent_id, 0], node_id="33")
    ref_neg_id = nf.reference_latent([neg_id, 0], [latent_id, 0], node_id="34")

    # Enhancer chain (Klein quality boost)
    _hs_model = _klein_enhance_model(nf, _ref(unet_id), [ref_pos_id, 0], node_base_id=910) if enhance else _ref(unet_id)

    # Sampling — uses BasicScheduler for denoise support
    guider_id = nf.cfg_guider(_hs_model, [ref_pos_id, 0], [ref_neg_id, 0],
                              1.0, node_id="40")
    sampler_id = nf.ksampler_select("euler", node_id="41")
    sched_id = nf.basic_scheduler(_hs_model, steps, denoise, node_id="42")
    noise_id = nf.random_noise(seed, node_id="43")

    # Sample -- feed encoded image latent, NOT empty latent
    sample_id = nf.sampler_custom_advanced(
        [noise_id, 0], [guider_id, 0], [sampler_id, 0],
        [sched_id, 0], [latent_id, 0], node_id="50",
    )

    dec_id = nf.vae_decode([sample_id, 0], [vae_id, 0], node_id="60")
    nf.save_image([dec_id, 0], "spellcaster_headswap", node_id="70")

    return nf.build()


# ═══════════════════════════════════════════════════════════════════════════
#  Video Upscale
# ═══════════════════════════════════════════════════════════════════════════

def build_video_upscale(video_name, upscale_model="4x-UltraSharp.pth",
                         upscale_factor=1.0, rtx_scale=2.0, fps=16):
    """Upscale video. Drop-in for _build_video_upscale().

    Uses nf.update() for exotic node types not in NodeFactory (VHS, TS, CreateVideo).
    """
    nf = NodeFactory()

    # VHS_LoadVideo (raw dict — exotic node)
    nf.update({
        "1": {"class_type": "VHS_LoadVideo",
              "inputs": {"video": video_name, "force_rate": 0,
                         "custom_width": 0, "custom_height": 0,
                         "frame_load_cap": 0, "skip_first_frames": 0,
                         "select_every_nth": 1}},
    })
    video_ref = ["1", 0]

    if upscale_factor > 1.0 and upscale_model:
        nf.update({
            "10": {"class_type": "TS_Video_Upscale_With_Model",
                   "inputs": {"model_name": upscale_model, "images": video_ref,
                              "upscale_method": "bicubic", "factor": upscale_factor,
                              "device_strategy": "auto"}},
        })
        video_ref = ["10", 0]

    if rtx_scale > 1.0:
        rtx_id = nf.video_upscale(video_ref, scale_factor=rtx_scale,
                                  node_id="20")
        video_ref = [rtx_id, 0]

    nf.update({
        "30": {"class_type": "CreateVideo",
               "inputs": {"fps": float(fps), "images": video_ref}},
        "31": {"class_type": "SaveVideo",
               "inputs": {"filename_prefix": "gimp_video_upscale",
                          "format": "auto", "codec": "auto",
                          "video": ["30", 0]}},
    })
    nf.save_image(video_ref, "gimp_video_upscale_frame", node_id="32")

    return nf.build()


# ═══════════════════════════════════════════════════════════════════════════
#  Video ReActor — upscale + face swap chain
# ═══════════════════════════════════════════════════════════════════════════

def build_video_reactor(video_name, face_models, upscale_model="4x-UltraSharp.pth",
                         upscale_factor=1.0, rtx_scale=2.0, fps=16,
                         face_restore_visibility=1.0, codeformer_weight=0.7):
    """Upscale + face swap a video. Drop-in for _build_video_reactor()."""
    nf = NodeFactory()

    nf.update({
        "1": {"class_type": "VHS_LoadVideo",
              "inputs": {"video": video_name, "force_rate": 0,
                         "custom_width": 0, "custom_height": 0,
                         "frame_load_cap": 0, "skip_first_frames": 0,
                         "select_every_nth": 1}},
    })
    video_ref = ["1", 0]

    if upscale_factor > 1.0 and upscale_model:
        nf.update({
            "10": {"class_type": "TS_Video_Upscale_With_Model",
                   "inputs": {"model_name": upscale_model, "images": video_ref,
                              "upscale_method": "bicubic", "factor": upscale_factor,
                              "device_strategy": "auto"}},
        })
        video_ref = ["10", 0]

    if rtx_scale > 1.0:
        rtx_id = nf.video_upscale(video_ref, scale_factor=rtx_scale,
                                  node_id="20")
        video_ref = [rtx_id, 0]

    # Face swap chain — one ReActorFaceSwapOpt per face model
    img_ref = video_ref
    for i, fm_name in enumerate(face_models):
        fm_id = nf.reactor_load_face_model(fm_name, node_id=str(40 + i))
        opts_id = nf.reactor_options(
            input_faces_index=str(i), node_id=f"{50 + i}o",
        )
        boost_id = nf.reactor_face_boost(
            boost_model="codeformer-v0.1.0.pth",
            codeformer_weight=codeformer_weight, node_id=f"{50 + i}b",
        )
        swap_id = nf.reactor_face_swap_opt(
            img_ref, None,
            swap_model="reswapper_256.onnx",
            face_restore_model="codeformer-v0.1.0.pth",
            face_restore_visibility=face_restore_visibility,
            codeformer_weight=codeformer_weight,
            options_ref=[opts_id, 0],
            face_boost_ref=[boost_id, 0],
            face_model_ref=[fm_id, 0],
            node_id=str(50 + i),
        )
        img_ref = [swap_id, 0]

    nf.update({
        "70": {"class_type": "CreateVideo",
               "inputs": {"fps": float(fps), "images": img_ref}},
        "71": {"class_type": "SaveVideo",
               "inputs": {"filename_prefix": "gimp_video_reactor",
                          "format": "auto", "codec": "auto",
                          "video": ["70", 0]}},
    })
    nf.save_image(img_ref, "gimp_video_reactor_frame", node_id="72")

    return nf.build()


# ═══════════════════════════════════════════════════════════════════════════
#  Wan 2.2 Video — dual-model GGUF architecture
# ═══════════════════════════════════════════════════════════════════════════

def build_wan_video(image_filename, preset, prompt_text, negative_text, seed,
                     width=832, height=480, length=81,
                     steps=None, cfg=None, shift=None, second_step=None,
                     turbo=True, loop=False,
                     loras_high=None, loras_low=None,
                     rtx_scale=2.5, interpolate=True,
                     face_swap=True, save_raw=False,
                     teacache=False, tiled_vae=False,
                     ip_adapter_image=None, ip_adapter_weight=0.5,
                     ip_adapter_start=0.0, ip_adapter_end=1.0,
                     motion_mask=None, pingpong=False, fps=16,
                     end_image_filename=None,
                     # Quality patches (both off by default). Callers should
                     # probe /object_info for the nodes before enabling.
                     #   - SLG (SkipLayerGuidanceSD3) is core ComfyUI since
                     #     the SD3 nodes landed — safe to enable on any recent
                     #     server. Skips the last 3 layers during CFG for
                     #     cleaner motion.
                     #   - NAG (WanVideoNAG) ships with Kijai's
                     #     WanVideoWrapper — NOT core. Requires that pack.
                     # Defaults mirror xb1n0ry's WAN 2.2 I2V preset.
                     enable_slg=False,
                     slg_layers="7, 8, 9", slg_scale=3.0,
                     slg_start=0.01, slg_end=0.15,
                     enable_nag=False,
                     nag_scale=11.0, nag_alpha=0.25, nag_tau=2.5):
    """WAN 2.2 frame-by-frame video generation with dual-model architecture.

    Generates video frame-by-frame using WAN (a lightweight video diffusion model).
    Uses a two-model approach: a high-quality model for initial generation + a
    lightweight low-quality model for intermediate frames (for speed/memory efficiency).
    Includes optional post-processing: upscaling, face swapping, motion blending.

    Pipeline (Simplified):
      1. Load high-res and low-res WAN models
      2. Load CLIP and VAE (from preset)
      3. Load reference image (or generate first frame from prompt)
      4. Encode prompt
      5. For each frame:
         a. Encode previous frame to latent
         b. Sample next frame using selected model (high or low)
         c. Decode to image
      6. Optional upscaling (RTX VSR) to restore detail
      7. Optional face swap on each frame
      8. Interpolate frames (smooth 16fps to 60fps+)
      9. Assemble into video file

    Args:
        image_filename (str): Reference/starting image (motion anchor)
        preset (dict): Video preset containing:
          - high_model: High-quality model (e.g., "wan-2.2-high.safetensors")
          - low_model: Low-quality model for efficiency
          - clip: CLIP model for text encoding
          - vae: VAE for latent encoding
          - steps: Default sampling steps (overridable)
          - cfg: Default CFG (overridable)
          - shift: Timestep shift for prompt weighting
          - second_step: When to switch from high to low model (default 10)
          - high_accel_lora: Optional LoRA for high model
          - low_accel_lora: Optional LoRA for low model
        prompt_text (str): What to generate/how to evolve
        negative_text (str): Things to avoid
        seed (int): Random seed
        width (int): Frame width (default 832, must be multiple of 16)
        height (int): Frame height (default 480)
        length (int): Number of frames to generate (default 81 = ~5 sec at 16fps)
        steps (int, optional): Sampling steps (overrides preset)
        cfg (float, optional): Guidance scale (overrides preset)
        shift (float, optional): Prompt weighting shift (overrides preset)
        second_step (int, optional): Frame where low model starts (default preset or 10)
        turbo (bool): Auto-adjust steps/cfg for speed (2-10 steps, default True)
        loop (bool): Make video loop seamlessly (default False)
        loras_high (list, optional): LoRAs for high-quality model
        loras_low (list, optional): LoRAs for low-quality model
        rtx_scale (float): Post-generation upscaling factor (default 2.5)
        interpolate (bool): Temporal interpolation for smoothness (default True)
        face_swap (bool): Apply face swap to each frame (default True)
        save_raw (bool): Save unprocessed frames before post-processing (default False)
        teacache (bool): Use TeaCache acceleration (faster, lower quality, default False)
        tiled_vae (bool): Use tiled VAE for memory efficiency (default False)
        ip_adapter_image (str, optional): Image for IP-Adapter style guidance
        ip_adapter_weight (float): IP-Adapter influence 0.0-1.0 (default 0.5)
        ip_adapter_start (float): When to start IP-Adapter in diffusion (0.0-1.0)
        ip_adapter_end (float): When to end IP-Adapter in diffusion (0.0-1.0)
        motion_mask (str, optional): Mask image constraining motion to regions
        pingpong (bool): Reverse video at end for seamless loop (default False)
        fps (int): Output video framerate (default 16, typical 24-60)
        end_image_filename (str, optional): Final frame target (for conditioning end)

    Returns:
        dict: ComfyUI workflow with video generation, upscaling, and assembly

    Turbo Mode:
      Auto-scales parameters for speed:
        - steps: 2-10 (vs typical 20-50)
        - second_step: 1-3 (switches to fast model very early)
        - Reduces quality but enables interactive generation

    Two-Model Strategy:
      - Frames 0-second_step: Use high-quality model (slower, better)
      - Frames second_step+: Use low-quality model (faster, acceptable)
      - Saves ~40% time while maintaining acceptable quality

    Post-Processing Chain:
      1. RTX Video Super Resolution (upscale)
      2. Face Swap on each frame (optional)
      3. Frame interpolation (temporal smoothing)
      4. Video assembly (CreateVideo → SaveVideo)

    Example Prompts:
      - "Cinematic pan across a forest. Camera movement is smooth and natural."
      - "A woman's face gradually smiling. Focus on facial expressions."
      - "Car driving down a highway at sunset. Motion is smooth."

    Node IDs (approximate):
      - "1": load_video or load_image
      - "2": wan_model_high_loader
      - "3": wan_model_low_loader
      - "4": clip_loader
      - "5": vae_loader
      - "10"+: Frame generation loop (dynamic)
      - "20": RTX upscaling (if rtx_scale > 1)
      - "21": Frame interpolation (if interpolate=True)
      - "30": CreateVideo
      - "31": SaveVideo

    Gotchas:
      - Very slow: ~10-30 seconds per frame on RTX 5060
      - High memory: may need tiled_vae=True for 1024x1024+
      - Turbo mode reduces quality noticeably at cfg < 3.0
      - IP-Adapter requires specific compatible models
      - Face swap fails on some angles/lighting
      - Loop requires matching start/end semantically
      - Motion masks must match frame dimensions exactly
    """
    nf = NodeFactory()
    steps = steps or preset["steps"]
    cfg = cfg if cfg is not None else preset["cfg"]
    shift = shift if shift is not None else preset.get("shift")
    second_step = second_step if second_step is not None else preset.get("second_step", 10)

    if turbo:
        if not (2 <= steps <= 10):
            steps = 6
        if not (1 <= second_step < steps):
            second_step = min(3, steps - 1)

    high_model = preset["high_model"]
    low_model = preset["low_model"]
    clip_name = preset["clip"]
    vae_name = preset["vae"]
    high_accel_lora = preset.get("high_accel_lora")
    low_accel_lora = preset.get("low_accel_lora")

    is_gguf_high = high_model.endswith(".gguf")
    is_gguf_low = low_model.endswith(".gguf")
    is_gguf_clip = preset.get("clip_is_gguf", clip_name.endswith(".gguf"))
    use_flf = loop or (end_image_filename is not None)

    # Model loaders -- use CLIPLoaderGGUF only for .gguf clips, regular CLIPLoader otherwise
    if is_gguf_clip:
        nf.update({"1": {"class_type": "CLIPLoaderGGUF",
                          "inputs": {"clip_name": clip_name, "type": "wan"}}})
    else:
        clip_id = nf.clip_loader(clip_name, clip_type="wan", node_id="1")

    if is_gguf_high:
        nf.update({"2": {"class_type": "UnetLoaderGGUF",
                          "inputs": {"unet_name": high_model}}})
    else:
        unet_id = nf.unet_loader(high_model, "default", node_id="2")

    if is_gguf_low:
        nf.update({"3": {"class_type": "UnetLoaderGGUF",
                          "inputs": {"unet_name": low_model}}})
    else:
        nf.unet_loader(low_model, "default", node_id="3")

    vae_id = nf.vae_loader(vae_name, node_id="4")
    pos_id = nf.clip_encode(["1", 0], prompt_text, node_id="5")
    neg_id = nf.clip_encode(["1", 0], negative_text or "", node_id="6")
    img_id = nf.load_image(image_filename, node_id="7")

    # Pre-resize the start image to EXACTLY width × height before handing it
    # to WanImageToVideo. Without this, the WAN node's internal VAE encoder
    # makes its own decision about how to fit the source into the latent
    # spatial dimensions — typically a center-crop that loses content on
    # whichever axis doesn't match. Users who pick a target size that's
    # close-but-not-identical to their source aspect ratio see horizontal
    # cutoff in the output even though they expected a clean down-scale.
    # Using ImageScale with crop="center" (Lanczos) produces a deterministic
    # exact-size frame that matches the latent dimensions perfectly.
    nf.image_scale(["7", 0], width, height,
                    upscale_method="lanczos", crop="center", node_id="7r")
    start_img_ref_for_wan = ["7r", 0]

    # CLIPVision: encode start image for WanImageToVideo/WanFirstLastFrameToVideo
    # The WAN v2 API requires CLIP_VISION_OUTPUT, not raw IMAGE.
    # Use the ORIGINAL full-resolution image for CLIP Vision (more semantic
    # detail = better conditioning), not the down-scaled "7r".
    cv_loader_id = nf.clip_vision_loader("clip_vision_h.safetensors", node_id="7cv")
    cv_enc_id = nf.clip_vision_encode([cv_loader_id, 0], ["7", 0], node_id="7ce")
    cv_start_ref = [cv_enc_id, 0]

    if end_image_filename and not loop:
        nf.load_image(end_image_filename, node_id="7b")
        # Same pre-resize for the end image so FLF gets a matched pair.
        nf.image_scale(["7b", 0], width, height,
                        upscale_method="lanczos", crop="center", node_id="7br")
        end_img_ref_for_wan = ["7br", 0]
        cv_enc_end_id = nf.clip_vision_encode([cv_loader_id, 0], ["7b", 0], node_id="7be")
        cv_end_ref = [cv_enc_end_id, 0]
    else:
        end_img_ref_for_wan = start_img_ref_for_wan  # loop uses same start/end
        cv_end_ref = cv_start_ref

    # LoRA chains
    high_ref = ["2", 0]
    low_ref = ["3", 0]

    if turbo:
        if high_accel_lora:
            accel_str = preset.get("accel_strength", 1.5)
            nf.lora_loader_model_only(high_ref, high_accel_lora, accel_str, node_id="100")
            high_ref = ["100", 0]
        if low_accel_lora:
            accel_str = preset.get("accel_strength", 1.5)
            nf.lora_loader_model_only(low_ref, low_accel_lora, accel_str, node_id="120")
            low_ref = ["120", 0]

    hi_n = 101 if turbo else 100
    lo_n = 121 if turbo else 120
    if loras_high:
        for i, (ln, ls) in enumerate(loras_high):
            nid = str(hi_n + i)
            nf.lora_loader_model_only(high_ref, ln, ls, node_id=nid)
            high_ref = [nid, 0]
    if loras_low:
        for i, (ln, ls) in enumerate(loras_low):
            nid = str(lo_n + i)
            nf.lora_loader_model_only(low_ref, ln, ls, node_id=nid)
            low_ref = [nid, 0]

    # TeaCache (optional)
    if teacache:
        tc_h = nf.apply_tea_cache_patch(high_ref, rel_l1_thresh=0.20, node_id="90")
        high_ref = [tc_h, 0]
        tc_l = nf.apply_tea_cache_patch(low_ref, rel_l1_thresh=0.20, node_id="91")
        low_ref = [tc_l, 0]

    # IP-Adapter WAN (optional)
    if ip_adapter_image:
        cv_id = nf.clip_vision_loader("siglip2_so400m_patch16_naflex.safetensors", node_id="95")
        cv_enc_id = nf.clip_vision_encode([cv_id, 0], ["7", 0], node_id="96")
        # Select IP-Adapter model matching the WAN model size.
        # 14B models use different attention dims than 1.3B — using the wrong
        # adapter causes "size mismatch for N.to_k_ip.weight" errors.
        ipa_model = preset.get("ip_adapter_model", "ip-adapter.bin")
        nf.update({
            "97": {"class_type": "IPAdapterWANLoader",
                   "inputs": {"ipadapter": ipa_model, "provider": "cuda"}},
        })
        if ip_adapter_image != "__start_image__":
            ip_img_id = nf.load_image(ip_adapter_image, node_id="98")
            nf.patch_input("96", "image", [ip_img_id, 0])
        nf.update({
            "99a": {"class_type": "ApplyIPAdapterWAN",
                    "inputs": {"model": high_ref, "ipadapter": ["97", 0],
                               "image_embed": [cv_enc_id, 0],
                               "weight": ip_adapter_weight,
                               "start_percent": ip_adapter_start,
                               "end_percent": ip_adapter_end}},
            "99b": {"class_type": "ApplyIPAdapterWAN",
                    "inputs": {"model": low_ref, "ipadapter": ["97", 0],
                               "image_embed": [cv_enc_id, 0],
                               "weight": ip_adapter_weight,
                               "start_percent": ip_adapter_start,
                               "end_percent": ip_adapter_end}},
        })
        high_ref = ["99a", 0]
        low_ref = ["99b", 0]

    # ModelSamplingSD3 (shift)
    if shift is not None and shift > 0:
        sh_h = nf.model_sampling_sd3(high_ref, shift, node_id="30")
        sh_l = nf.model_sampling_sd3(low_ref, shift, node_id="31")
        high_ref = [sh_h, 0]
        low_ref = [sh_l, 0]

    # ── Quality patches from xb1n0ry's WAN 2.2 I2V workflow ─────────────
    # NAG (Normalized Attention Guidance): wraps each branch's model with
    # the negative-conditioning attention for sharper motion / less drift.
    # Requires Kijai's WanVideoWrapper (`WanVideoNAG` node). Preflight
    # should probe /object_info/WanVideoNAG and set enable_nag accordingly.
    if enable_nag:
        nag_h = nf._add("WanVideoNAG", {
            "model": high_ref,
            "conditioning": [neg_id, 0],
            "nag_scale": nag_scale,
            "nag_alpha": nag_alpha,
            "nag_tau": nag_tau,
            "input_type": "default",
        }, node_id="32a")
        high_ref = [nag_h, 0]
        nag_l = nf._add("WanVideoNAG", {
            "model": low_ref,
            "conditioning": [neg_id, 0],
            "nag_scale": nag_scale,
            "nag_alpha": nag_alpha,
            "nag_tau": nag_tau,
            "input_type": "default",
        }, node_id="32b")
        low_ref = [nag_l, 0]

    # SLG (SkipLayerGuidanceSD3): skips mid-block layers during CFG for
    # cleaner output. Core ComfyUI node — no extra pack needed.
    if enable_slg:
        slg_h = nf._add("SkipLayerGuidanceSD3", {
            "model": high_ref,
            "layers": slg_layers,
            "scale": slg_scale,
            "start_percent": slg_start,
            "end_percent": slg_end,
        }, node_id="33a")
        high_ref = [slg_h, 0]
        slg_l = nf._add("SkipLayerGuidanceSD3", {
            "model": low_ref,
            "layers": slg_layers,
            "scale": slg_scale,
            "start_percent": slg_start,
            "end_percent": slg_end,
        }, node_id="33b")
        low_ref = [slg_l, 0]

    # Video conditioning — WanImageToVideo/WanFirstLastFrameToVideo
    # These nodes output: [0]=CONDITIONING(pos), [1]=CONDITIONING(neg), [2]=LATENT
    # Model/seed/steps/cfg are handled by the KSamplerAdvanced below.
    if use_flf:
        flf_id = nf.wan_first_last_frame(
            ["5", 0], ["6", 0], ["4", 0],
            width, height, length,
            clip_vision_start_ref=cv_start_ref,
            clip_vision_end_ref=cv_end_ref,
            start_image_ref=start_img_ref_for_wan,
            end_image_ref=end_img_ref_for_wan,
            node_id="40",
        )
    else:
        i2v_id = nf.wan_image_to_video(
            ["5", 0], ["6", 0], ["4", 0],
            width, height, length,
            clip_vision_output_ref=cv_start_ref,
            start_image_ref=start_img_ref_for_wan,
            node_id="40",
        )

    # Motion mask (optional)
    latent_ref = ["40", 2]
    if motion_mask:
        mask_img_id = nf.load_image(motion_mask, node_id="45")
        mask_id = nf.image_to_mask([mask_img_id, 0], "red", node_id="46")
        mask_latent_id = nf.set_latent_noise_mask(latent_ref, [mask_id, 0], node_id="47")
        latent_ref = [mask_latent_id, 0]

    # Two-pass KSamplerAdvanced
    pass1_id = nf.ksampler_advanced(
        high_ref, ["40", 0], ["40", 1], latent_ref,
        add_noise="enable", noise_seed=seed,
        steps=steps, cfg=cfg, sampler_name="euler_ancestral", scheduler="simple",
        start_at_step=0, end_at_step=second_step,
        return_with_leftover_noise="enable", node_id="50",
    )
    pass2_id = nf.ksampler_advanced(
        low_ref, ["40", 0], ["40", 1], [pass1_id, 0],
        add_noise="disable", noise_seed=0,
        steps=steps, cfg=1, sampler_name="euler_ancestral", scheduler="simple",
        start_at_step=second_step, end_at_step=10000,
        return_with_leftover_noise="disable", node_id="51",
    )

    # VAE Decode
    if tiled_vae:
        dec_id = nf.vae_decode_tiled([pass2_id, 0], ["4", 0], tile_size=256, node_id="60")
    else:
        dec_id = nf.vae_decode([pass2_id, 0], ["4", 0], node_id="60")

    video_ref = [dec_id, 0]
    prefix = "gimp_wan_loop" if loop else ("gimp_wan_flf" if use_flf else "gimp_wan_i2v")
    # Force boolean — VHS_VideoCombine's INPUT_TYPES expects BOOLEAN, but
    # mis-typed values (None, "false") have caused the pingpong flag to be
    # silently ignored in some VHS releases. Casting here is cheap insurance.
    pingpong_bool = bool(pingpong)

    # Save raw (optional). When the user has BOTH save_raw and pingpong
    # enabled we apply pingpong to the raw save too — otherwise the raw
    # MP4 plays forward-only while the final MP4 pingpongs, and the user's
    # video player shows them BOTH (because GIMP imports every result),
    # creating the false impression that pingpong is broken.
    if save_raw:
        nf.update({
            "80": {"class_type": "VHS_VideoCombine",
                   "inputs": {"images": video_ref, "frame_rate": float(fps),
                              "loop_count": 0, "filename_prefix": f"{prefix}_raw",
                              "format": "video/h264-mp4", "pingpong": pingpong_bool,
                              "save_output": True, "pix_fmt": "yuv420p", "crf": 19}},
        })

    # ReActor face swap on raw frames (optional)
    if face_swap:
        opts_id = nf.reactor_options(console_log_level=0, node_id="71o")
        boost_id = nf.reactor_face_boost(node_id="71b")
        swap_id = nf.reactor_face_swap_opt(
            video_ref, ["7", 0],
            swap_model="reswapper_256.onnx",
            face_restore_model="codeformer-v0.1.0.pth",
            options_ref=[opts_id, 0],
            face_boost_ref=[boost_id, 0],
            node_id="71",
        )
        video_ref = [swap_id, 0]

    # RIFE 4× interpolation (optional)
    if interpolate:
        rife_id = nf.rife_vfi(video_ref, multiplier=4, node_id="70")
        video_ref = [rife_id, 0]

    # AI upscale (optional — replaces RTX with native model upscale)
    if rtx_scale > 1.0:
        rtx_id = nf.video_upscale(video_ref, scale_factor=rtx_scale,
                                   node_id="75")
        video_ref = [rtx_id, 0]

    # Final MP4
    final_fps = float(fps * (4 if interpolate else 1))
    nf.update({
        "83": {"class_type": "VHS_VideoCombine",
               "inputs": {"images": video_ref, "frame_rate": final_fps,
                          "loop_count": 0, "filename_prefix": f"{prefix}_final",
                          "format": "video/h264-mp4", "pix_fmt": "yuv420p",
                          "crf": 17, "pingpong": pingpong_bool,
                          "save_output": True}},
    })

    # Last frame for GIMP
    nf.update({
        "85": {"class_type": "ImageFromBatch+",
               "inputs": {"image": [dec_id, 0], "start": length - 1, "length": 1}},
    })
    nf.save_image(["85", 0], f"{prefix}_lastframe", node_id="86")

    return nf.build()


def build_wan_flf(start_filename, end_filename, preset, prompt_text, negative_text,
                   seed, **kwargs):
    """Thin wrapper: delegates to build_wan_video with end_image_filename."""
    return build_wan_video(
        start_filename, preset, prompt_text, negative_text, seed,
        end_image_filename=end_filename, **kwargs,
    )


# ═══════════════════════════════════════════════════════════════════════════
#  SeedVR2 Video Upscaler
# ═══════════════════════════════════════════════════════════════════════════

def build_seedvr2_video_upscale(video_name, seed=-1,
                                 resolution=1024, max_resolution=2048,
                                 batch_size=5, uniform_batch_size=True,
                                 color_correction="lab", temporal_overlap=2,
                                 input_noise_scale=0.0, latent_noise_scale=0.0,
                                 dit_model="seedvr2_ema_3b_fp8_e4m3fn.safetensors",
                                 vae_model="ema_vae_fp16.safetensors",
                                 vae_tiled=True, fps=16):
    """SeedVR2 AI video upscaler. Drop-in for _build_seedvr2_video_upscale()."""
    import random as _random
    if seed < 0:
        seed = _random.randint(0, 2**32 - 1)

    nf = NodeFactory()
    nf.update({
        "1": {"class_type": "VHS_LoadVideo",
              "inputs": {"video": video_name, "force_rate": 0,
                         "custom_width": 0, "custom_height": 0,
                         "frame_load_cap": 0, "skip_first_frames": 0,
                         "select_every_nth": 1}},
        "2d": {"class_type": "SeedVR2LoadDiTModel",
               "inputs": {"model": dit_model,
                          "device": "cuda:0"}},
        "2": {"class_type": "SeedVR2LoadVAEModel",
              "inputs": {"model": vae_model, "device": "cuda:0",
                         "encode_tiled": vae_tiled, "encode_tile_size": 256,
                         "encode_tile_overlap": 64,
                         "decode_tiled": vae_tiled, "decode_tile_size": 256,
                         "decode_tile_overlap": 64,
                         "tile_debug": "false", "offload_device": "cpu",
                         "cache_model": True, "torch_compile_args": ""}},
        "3": {"class_type": "SeedVR2VideoUpscaler",
              "inputs": {"image": ["1", 0], "dit": ["2d", 0],
                         "vae": ["2", 0], "seed": seed,
                         "resolution": resolution,
                         "max_resolution": max_resolution,
                         "batch_size": batch_size,
                         "uniform_batch_size": uniform_batch_size,
                         "color_correction": color_correction,
                         "temporal_overlap": temporal_overlap,
                         "prepend_frames": 0,
                         "input_noise_scale": input_noise_scale,
                         "latent_noise_scale": latent_noise_scale,
                         "offload_device": "cpu",
                         "enable_debug": False}},
        "10": {"class_type": "VHS_VideoCombine",
               "inputs": {"images": ["3", 0], "frame_rate": float(fps),
                          "loop_count": 0, "filename_prefix": "seedvr2_upscale",
                          "format": "video/h264-mp4", "pix_fmt": "yuv420p",
                          "crf": 17, "pingpong": False,
                          "save_output": True}},
    })
    nf.save_image(["3", 0], "seedvr2_upscale_frame", node_id="11")

    return nf.build()


# ═══════════════════════════════════════════════════════════════════════════
#  Style Transfer — IPAdapter style transfer + ControlNet
# ═══════════════════════════════════════════════════════════════════════════

def build_style_transfer(target_filename, style_ref_filename, preset,
                          prompt_text, negative_text, seed,
                          ipadapter_preset="PLUS (high strength)", loras=None,
                          weight=0.8, denoise=0.6,
                          controlnet=None, controlnet_2=None,
                          guide_modes=None,
                          sam3_prompt=None, sam3_invert=False,
                          sam3_confidence=0.6, sam3_expand=4, sam3_blur=4):
    """Style transfer via IPAdapter. Drop-in for _build_style_transfer().

    Pipeline: model stack → IPAdapterUnifiedLoader → IPAdapterAdvanced(style transfer)
              → LoadImage(target) → encode → KSampler → decode → save

    When sam3_prompt is set, the transform is composited back onto the TARGET
    image using a SAM3 mask so only the described region changes.
    """
    nf = NodeFactory()
    arch_key = preset.get("arch", "sdxl")

    # 1. Model stack
    model_ref, clip_ref, vae_ref = load_model_stack(nf, preset, "1")

    # LoRA chain
    if loras:
        model_ref, clip_ref, _trig = inject_lora_chain(nf, loras, model_ref, clip_ref, base_id=100)

    # 2. IPAdapter
    ipa_loader_id = nf.ipadapter_unified_loader(model_ref, ipadapter_preset,
                                                 node_id="2")
    style_img_id = nf.load_image(style_ref_filename, node_id="3")
    ipa_id = nf.ipadapter_advanced(
        [ipa_loader_id, 0], [ipa_loader_id, 1], [style_img_id, 0],
        weight=weight, weight_type="style transfer",
        combine_embeds="concat", start_at=0.0, end_at=1.0,
        embeds_scaling="V only", node_id="4",
    )

    # 3. Encode prompts (architecture-aware: no-negative archs get zero_out)
    pos_id, neg_id = encode_prompts(nf, arch_key, clip_ref,
                                     prompt_text,
                                     negative_text or "blurry, deformed, bad anatomy",
                                     pos_id="5", neg_id="6")

    # 4. Load target + encode
    target_img_id = nf.load_image(target_filename, node_id="7")
    target_ref = [target_img_id, 0]

    # Mod-16 for Flux architectures
    if arch_key in ("flux1dev", "flux_kontext", "flux2klein"):
        scale_id = nf.image_scale_to_total_pixels(target_ref, megapixels=1.0,
                                                    node_id="7s")
        target_ref = [scale_id, 0]

    enc_id = nf.vae_encode(target_ref, vae_ref, node_id="8")

    # 5. Sample
    is_klein = arch_key == "flux2klein"
    if is_klein:
        ref_pos = nf.reference_latent([pos_id, 0], [enc_id, 0], node_id="60")
        ref_neg = nf.reference_latent([neg_id, 0], [enc_id, 0], node_id="61")
        guider_id = nf.cfg_guider([ipa_id, 0], [ref_pos, 0], [ref_neg, 0],
                                  preset.get("cfg", 1.0), node_id="62")
        sampler_sel = nf.ksampler_select("euler", node_id="63")
        sched_id = nf.basic_scheduler([ipa_id, 0], preset.get("steps", 20),
                                       denoise, scheduler="simple", node_id="64")
        noise_id = nf.random_noise(seed, node_id="65")
        samp_id = nf.sampler_custom_advanced(
            [noise_id, 0], [guider_id, 0], [sampler_sel, 0],
            [sched_id, 0], [enc_id, 0], node_id="9",
        )
    else:
        samp_id = nf.ksampler(
            [ipa_id, 0],
            [pos_id, 0], [neg_id, 0], [enc_id, 0],
            seed, preset["steps"], preset["cfg"],
            preset.get("sampler", "euler"), preset.get("scheduler", "normal"),
            denoise, node_id="9",
        )
    dec_id = nf.vae_decode([samp_id, 0], vae_ref, node_id="10")
    # Use TARGET image (post-scale if Flux) as compositing "original" — that's
    # what the user wants to preserve outside the SAM3 region. target_ref
    # matches the sampler output dimensions after any Flux rescale.
    final_ref = [dec_id, 0]
    if sam3_prompt:
        _mask = build_sam3_mask(nf, target_ref, sam3_prompt,
                                 invert=sam3_invert,
                                 confidence=sam3_confidence,
                                 mask_expand=sam3_expand,
                                 mask_blur=sam3_blur)
        final_ref = apply_sam3_scope(nf, final_ref, target_ref, _mask)
    nf.save_image(final_ref, "spellcaster_style", node_id="11")

    # 6. ControlNet injection (optional)
    if guide_modes and controlnet and controlnet.get("mode", "Off") != "Off":
        cn_pos, cn_neg = inject_controlnet(
            nf, controlnet, guide_modes, arch_key, target_ref,
            [pos_id, 0], [neg_id, 0], cn_base_id=20,
        )
        nf.patch_input("9", "positive", cn_pos)
        nf.patch_input("9", "negative", cn_neg)

    if guide_modes and controlnet_2 and controlnet_2.get("mode", "Off") != "Off":
        prev_pos = ["22", 0] if nf.has_node("22") else [pos_id, 0]
        prev_neg = ["22", 1] if nf.has_node("22") else [neg_id, 0]
        cn2_pos, cn2_neg = inject_controlnet(
            nf, controlnet_2, guide_modes, arch_key, target_ref,
            prev_pos, prev_neg, cn_base_id=30,
        )
        nf.patch_input("9", "positive", cn2_pos)
        nf.patch_input("9", "negative", cn2_neg)

    return nf.build()


# ═══════════════════════════════════════════════════════════════════════════
#  SeedV2R — Upscale + img2img hallucinate (like detail_hallucinate but
#  with user-controlled scale factor)
# ═══════════════════════════════════════════════════════════════════════════

def build_seedv2r(image_filename, upscale_model, preset, prompt_text, negative_text,
                   seed, denoise, cfg, steps, scale_factor, orig_width, orig_height,
                   controlnet=None, controlnet_2=None, guide_modes=None,
                   loras=None):
    """SeedV2R: upscale + img2img. Drop-in for _build_seedv2r().

    For scale > 1x: upscale with model to target factor, then img2img.
    For 1x: straight img2img on original.
    """
    nf = NodeFactory()
    arch_key = preset.get("arch", "sdxl")

    # 1. Load source image
    img_id = nf.load_image(image_filename, node_id="1")
    img_ref = [img_id, 0]

    # 2. Optional upscale
    if scale_factor > 1.0 and upscale_model:
        up_model_id = nf.upscale_model_loader(upscale_model, node_id="2")
        up_id = nf.image_upscale_with_model_by_factor([up_model_id, 0], img_ref,
                                                      scale_factor, node_id="3")
        img_ref = [up_id, 0]

    # 3. Mod-16 for Flux
    if arch_key in ("flux1dev", "flux_kontext", "flux2klein"):
        scale_id = nf.image_scale_to_total_pixels(img_ref, megapixels=1.0,
                                                    node_id="3s")
        img_ref = [scale_id, 0]

    # 4. Model stack
    model_ref, clip_ref, vae_ref = load_model_stack(nf, preset, "4")

    # LoRA chain
    if loras:
        model_ref, clip_ref, _trig = inject_lora_chain(nf, loras, model_ref, clip_ref, base_id=100)

    # 5. Encode (architecture-aware: no-negative archs get zero_out)
    pos_id, neg_id = encode_prompts(nf, arch_key, clip_ref,
                                     prompt_text, negative_text,
                                     pos_id="5", neg_id="6")

    # 6. VAE encode + sample + decode
    enc_id = nf.vae_encode(img_ref, vae_ref, node_id="7")
    is_klein = arch_key == "flux2klein"
    if is_klein:
        ref_pos = nf.reference_latent([pos_id, 0], [enc_id, 0], node_id="60")
        ref_neg = nf.reference_latent([neg_id, 0], [enc_id, 0], node_id="61")
        guider_id = nf.cfg_guider(model_ref, [ref_pos, 0], [ref_neg, 0],
                                  cfg, node_id="62")
        sampler_sel = nf.ksampler_select("euler", node_id="63")
        sched_id = nf.basic_scheduler(model_ref, steps, denoise,
                                       scheduler="simple", node_id="64")
        noise_id = nf.random_noise(seed, node_id="65")
        samp_id = nf.sampler_custom_advanced(
            [noise_id, 0], [guider_id, 0], [sampler_sel, 0],
            [sched_id, 0], [enc_id, 0], node_id="8",
        )
    else:
        samp_id = nf.ksampler(
            model_ref,
            [pos_id, 0], [neg_id, 0], [enc_id, 0],
            seed, steps, cfg,
            preset.get("sampler", "euler"), preset.get("scheduler", "normal"),
            denoise, node_id="8",
        )
    dec_id = nf.vae_decode([samp_id, 0], vae_ref, node_id="9")
    nf.save_image([dec_id, 0], "spellcaster_seedv2r", node_id="10")

    # 7. ControlNet injection (optional)
    if guide_modes and controlnet and controlnet.get("mode", "Off") != "Off":
        cn_pos, cn_neg = inject_controlnet(
            nf, controlnet, guide_modes, arch_key, img_ref,
            [pos_id, 0], [neg_id, 0], cn_base_id=20,
        )
        nf.patch_input("8", "positive", cn_pos)
        nf.patch_input("8", "negative", cn_neg)

    if guide_modes and controlnet_2 and controlnet_2.get("mode", "Off") != "Off":
        prev_pos = ["22", 0] if nf.has_node("22") else [pos_id, 0]
        prev_neg = ["22", 1] if nf.has_node("22") else [neg_id, 0]
        cn2_pos, cn2_neg = inject_controlnet(
            nf, controlnet_2, guide_modes, arch_key, img_ref,
            prev_pos, prev_neg, cn_base_id=30,
        )
        nf.patch_input("8", "positive", cn2_pos)
        nf.patch_input("8", "negative", cn2_neg)

    return nf.build()


# ═══════════════════════════════════════════════════════════════════════════
#  Photobooth — Klein headshot generation → ReActor identity → face restore
# ═══════════════════════════════════════════════════════════════════════════

def build_photobooth(ref_filename, prompt_text, seed,
                     klein_model_key="Klein 9B", steps=20, guidance=1.0,
                     swap_model="reswapper_256.onnx",
                     face_restore_model="codeformer-v0.1.0.pth",
                     face_restore_vis=0.9, codeformer_weight=0.6,
                     transparent=False,
                     klein_models=None):
    """Photobooth: generate passport-style headshots with extreme character fidelity.

    Four-stage single-workflow pipeline:

    1. **Klein ReferenceLatent generation** — generates a clean studio headshot
       at fixed STUDIO_FACE_W × STUDIO_FACE_H (square) dimensions, guided by
       the reference photo.  Prompt controls background/lighting/pose,
       ReferenceLatent provides structural guidance from the input face.

    2. **ReActor face swap** — transplants the EXACT face from the original
       reference onto the Klein output. This restores character fidelity
       that Klein may have drifted. Uses reswapper_256 + FaceBoost.

    3. **Face restore** — CodeFormer final pass for artifact cleanup and
       skin detail enhancement.

    4. **Background removal** (optional, ``transparent=True``) — rembg with
       alpha matting produces a transparent PNG cutout suitable for compositing
       in later Studio pipeline stages.

    The result is a clean passport-style headshot with the person's real face,
    always at a predictable square resolution for downstream compositing.
    """
    if klein_models is None:
        klein_models = KLEIN_MODELS

    km = klein_models[klein_model_key]
    nf = NodeFactory()

    # ── Load reference image (shared: Klein input + ReActor source) ──
    ref_id = nf.load_image(ref_filename, node_id="1")

    # ══════════════════════════════════════════════════════════════════
    # Stage 1: Klein ReferenceLatent generation — clean headshot base
    #          Fixed square output (STUDIO_FACE_W × STUDIO_FACE_H) so
    #          all photobooth results share the same spatial reference.
    # ══════════════════════════════════════════════════════════════════
    unet_id = nf.unet_loader(km["unet"], "default", node_id="10")
    clip_id = nf.clip_loader(
        km.get("clip", "qwen_3_8b.safetensors"),
        clip_type="flux2", device="default", node_id="11",
    )
    vae_id = nf.vae_loader(FLUX2_VAE, node_id="12")

    # Text conditioning
    pos_id = nf.clip_encode(_ref(clip_id), prompt_text, node_id="13")
    neg_id = nf.conditioning_zero_out([pos_id, 0], node_id="14")

    # Encode reference — scale to 1 MP but ReferenceLatent only needs
    # the structural guidance, NOT the output resolution.
    scaled_id = nf.image_scale_to_total_pixels([ref_id, 0], megapixels=1.0,
                                                node_id="15")
    latent_id = nf.vae_encode([scaled_id, 0], [vae_id, 0], node_id="17")

    # ReferenceLatent wrapping
    ref_pos_id = nf.reference_latent([pos_id, 0], [latent_id, 0], node_id="18")
    ref_neg_id = nf.reference_latent([neg_id, 0], [latent_id, 0], node_id="19")

    # Enhancer chain for maximum quality
    _pb_model = _klein_enhance_model(nf, _ref(unet_id), [ref_pos_id, 0], node_base_id=970)

    # Sampling at FIXED portrait dimensions (not derived from reference)
    guider_id = nf.cfg_guider(_pb_model, [ref_pos_id, 0], [ref_neg_id, 0],
                              guidance, node_id="20")
    sampler_id = nf.ksampler_select("euler", node_id="21")
    sched_id = nf.flux2_scheduler(steps, STUDIO_FACE_W, STUDIO_FACE_H,
                                   node_id="22")
    noise_id = nf.random_noise(seed, node_id="23")
    empty_id = nf.empty_flux2_latent_image(STUDIO_FACE_W, STUDIO_FACE_H,
                                            batch_size=1, node_id="24")

    sample_id = nf.sampler_custom_advanced(
        [noise_id, 0], [guider_id, 0], [sampler_id, 0],
        [sched_id, 0], [empty_id, 0], node_id="30",
    )

    klein_out = nf.vae_decode([sample_id, 0], [vae_id, 0], node_id="31")

    # ══════════════════════════════════════════════════════════════════
    # Stage 2: ReActor — restore identity from original reference
    # ══════════════════════════════════════════════════════════════════
    opts_id = nf.reactor_options(node_id="40o")
    boost_id = nf.reactor_face_boost(
        boost_model=face_restore_model,
        codeformer_weight=codeformer_weight, node_id="40b",
    )
    swap_id = nf.reactor_face_swap_opt(
        [klein_out, 0],     # target: the Klein headshot
        [ref_id, 0],        # source: the original reference face
        swap_model=swap_model,
        face_restore_model=face_restore_model,
        face_restore_visibility=face_restore_vis,
        codeformer_weight=codeformer_weight,
        options_ref=[opts_id, 0],
        face_boost_ref=[boost_id, 0],
        node_id="40",
    )

    # ══════════════════════════════════════════════════════════════════
    # Stage 3: Face restore — final quality pass
    # ══════════════════════════════════════════════════════════════════
    restore_id = nf.reactor_restore_face(
        [swap_id, 0],
        model=face_restore_model,
        facedetection="retinaface_resnet50",
        visibility=1.0,
        codeformer_weight=0.5,
        node_id="50",
    )

    # ══════════════════════════════════════════════════════════════════
    # Stage 4 (optional): Background removal — transparent PNG cutout
    # ══════════════════════════════════════════════════════════════════
    final_ref = [restore_id, 0]
    if transparent:
        rembg_id = nf.rembg([restore_id, 0], alpha_matting=True, node_id="55")
        final_ref = [rembg_id, 0]

    nf.save_image(final_ref, "photobooth", node_id="60")

    return nf.build()


# ═══════════════════════════════════════════════════════════════════════════
#  Klein Re-poser — ReferenceLatent + BasicScheduler (denoise control)
# ═══════════════════════════════════════════════════════════════════════════

def build_klein_repose(image_filename, klein_model_key, prompt_text, seed,
                       steps=20, denoise=0.65, guidance=1.0, loras=None,
                       klein_models=None, enhance=True):
    """Klein Re-poser: change character pose using ReferenceLatent + BasicScheduler.

    Same as build_klein_img2img but uses BasicScheduler with denoise instead of
    Flux2Scheduler. This allows partial regeneration (controlled by denoise) while
    keeping ReferenceLatent structural guidance from the input image.
    """
    if klein_models is None:
        klein_models = KLEIN_MODELS

    km = klein_models[klein_model_key]
    nf = NodeFactory()

    # Model loaders
    unet_id = nf.unet_loader(km["unet"], "default", node_id="1")
    clip_id = nf.clip_loader(
        km.get("clip", "qwen_3_8b.safetensors"),
        clip_type="flux2", device="default", node_id="2",
    )
    vae_id = nf.vae_loader(FLUX2_VAE, node_id="3")


    # Apply LoRA chain
    if loras:
        unet_id, clip_id, _trig = inject_lora_chain(nf, loras, _ref(unet_id), _ref(clip_id), base_id=100)
        # After LoRA chain, refs are [node_id, slot] lists.
        # Leave them as-is. Use _ref() for all downstream references.
    # Text conditioning
    pos_id = nf.clip_encode(_ref(clip_id), prompt_text, node_id="4")
    neg_id = nf.conditioning_zero_out([pos_id, 0], node_id="5")

    # Input image processing
    img_id = nf.load_image(image_filename, node_id="10")
    scaled_id = nf.image_scale_to_total_pixels([img_id, 0], megapixels=1.0,
                                                node_id="11")
    size_id = nf.get_image_size([scaled_id, 0], node_id="12")
    latent_id = nf.vae_encode([scaled_id, 0], [vae_id, 0], node_id="13")

    # ReferenceLatent wrapping
    ref_pos_id = nf.reference_latent([pos_id, 0], [latent_id, 0], node_id="20")
    ref_neg_id = nf.reference_latent([neg_id, 0], [latent_id, 0], node_id="21")

    # Enhancer chain
    _rp_model = _klein_enhance_model(nf, _ref(unet_id), [ref_pos_id, 0], node_base_id=920) if enhance else _ref(unet_id)

    # Sampler setup — BasicScheduler with denoise (unlike Flux2Scheduler)
    guider_id = nf.cfg_guider(_rp_model, [ref_pos_id, 0], [ref_neg_id, 0],
                              guidance, node_id="30")
    sampler_id = nf.ksampler_select("euler", node_id="31")
    sched_id = nf.basic_scheduler(_rp_model, steps, denoise,
                                   scheduler="simple", node_id="32")
    noise_id = nf.random_noise(seed, node_id="33")

    # Sample -- feed encoded image latent, NOT empty latent
    sample_id = nf.sampler_custom_advanced(
        [noise_id, 0], [guider_id, 0], [sampler_id, 0],
        [sched_id, 0], [latent_id, 0], node_id="40",
    )

    # Decode and save
    dec_id = nf.vae_decode([sample_id, 0], [vae_id, 0], node_id="50")
    nf.save_image([dec_id, 0], "spellcaster_repose", node_id="60")

    return nf.build()


# ═══════════════════════════════════════════════════════════════════════════
#  Klein Blend — AILab_ImageCombiner pre-compositing + Klein ReferenceLatent
# ═══════════════════════════════════════════════════════════════════════════

def build_klein_blend(fg_filename, bg_filename, prompt_text, seed,
                      blend_mode="normal", opacity=1.0,
                      scale=None, position_x=0.5, position_y=0.5,
                      klein_model_key="Klein 9B", steps=20, denoise=0.25,
                      guidance=1.0, loras=None, klein_models=None,
                      enhance=True):
    """Klein Blend: composite foreground onto background, then harmonize with Klein.

    Pipeline: LoadImage(FG) + LoadImage(BG) → AILab_ImageCombiner → Klein
    ReferenceLatent + BasicScheduler (low denoise for subtle integration).

    When ``scale`` is None (default) it falls back to
    STUDIO_BODY_IN_SCENE_SCALE — the canvas-aware ratio that makes a
    full-body PNG fill ~85 % of the scene height.  Pass an explicit
    float to override.
    """
    if scale is None:
        scale = STUDIO_BODY_IN_SCENE_SCALE
    if klein_models is None:
        klein_models = KLEIN_MODELS

    km = klein_models[klein_model_key]
    nf = NodeFactory()

    # Load foreground and background
    fg_id = nf.load_image(fg_filename, node_id="1")
    bg_id = nf.load_image(bg_filename, node_id="2")

    # Composite (use _add directly — AILab_ImageCombiner has individual inputs)
    combine_id = nf._add("AILab_ImageCombiner", {
        "foreground": [fg_id, 0], "background": [bg_id, 0],
        "mode": blend_mode, "foreground_opacity": opacity,
        "foreground_scale": scale, "position_x": position_x, "position_y": position_y,
    }, node_id="3")

    # Klein model loaders
    unet_id = nf.unet_loader(km["unet"], "default", node_id="10")
    clip_id = nf.clip_loader(
        km.get("clip", "qwen_3_8b.safetensors"),
        clip_type="flux2", device="default", node_id="11",
    )
    vae_id = nf.vae_loader(FLUX2_VAE, node_id="12")


    # Apply LoRA chain
    if loras:
        unet_id, clip_id, _trig = inject_lora_chain(nf, loras, _ref(unet_id), _ref(clip_id), base_id=100)
        # After LoRA chain, refs are [node_id, slot] lists.
        # Leave them as-is. Use _ref() for all downstream references.
    # Text conditioning
    pos_id = nf.clip_encode(_ref(clip_id), prompt_text, node_id="13")
    neg_id = nf.conditioning_zero_out([pos_id, 0], node_id="14")

    # Prepare composited image
    scaled_id = nf.image_scale_to_total_pixels([combine_id, 0], megapixels=1.0,
                                                node_id="15")
    size_id = nf.get_image_size([scaled_id, 0], node_id="16")
    latent_id = nf.vae_encode([scaled_id, 0], [vae_id, 0], node_id="17")

    # ReferenceLatent wrapping
    ref_pos_id = nf.reference_latent([pos_id, 0], [latent_id, 0], node_id="20")
    ref_neg_id = nf.reference_latent([neg_id, 0], [latent_id, 0], node_id="21")

    # Enhancer chain
    _bl_model = _klein_enhance_model(nf, _ref(unet_id), [ref_pos_id, 0], node_base_id=930) if enhance else _ref(unet_id)

    # Sampler — BasicScheduler with low denoise
    guider_id = nf.cfg_guider(_bl_model, [ref_pos_id, 0], [ref_neg_id, 0],
                              guidance, node_id="30")
    sampler_id = nf.ksampler_select("euler", node_id="31")
    sched_id = nf.basic_scheduler(_bl_model, steps, denoise,
                                   scheduler="simple", node_id="32")
    noise_id = nf.random_noise(seed, node_id="33")

    # Sample -- feed encoded image latent, NOT empty latent
    sample_id = nf.sampler_custom_advanced(
        [noise_id, 0], [guider_id, 0], [sampler_id, 0],
        [sched_id, 0], [latent_id, 0], node_id="40",
    )

    dec_id = nf.vae_decode([sample_id, 0], [vae_id, 0], node_id="50")
    nf.save_image([dec_id, 0], "spellcaster_blend", node_id="60")

    return nf.build()


# ═══════════════════════════════════════════════════════════════════════════
#  Klein Inpaint — mask-based with FluxGuidance + SetLatentNoiseMask
#                  + optional GrowMask + optional DifferentialDiffusion
# ═══════════════════════════════════════════════════════════════════════════

def build_klein_inpaint(image_filename, mask_filename=None, prompt_text="", seed=0,
                        klein_model_key="Klein 9B", steps=25, denoise=0.92,
                        guidance=1.0, grow_px=0, use_differential_diffusion=False,
                        use_solid_mask=False, solid_mask_width=1024,
                        solid_mask_height=1024, loras=None,
                        klein_models=None, enhance=True,
                        sam3_prompt=None, sam3_invert=False,
                        sam3_confidence=0.6, sam3_expand=4, sam3_blur=4):
    """Klein Inpaint: regenerate masked area using FluxGuidance + SetLatentNoiseMask.

    Supports three mask sources (precedence top → bottom):
    - Solid mask (use_solid_mask=True) — full-image inpainting
    - Image mask (mask_filename → ImageToMask) — selection-based inpainting
    - SAM3 mask (sam3_prompt) — mask built server-side from text description

    Optional GrowMask expands the mask boundary.
    Optional DifferentialDiffusion enables smooth mask-edge blending.
    """
    if klein_models is None:
        klein_models = KLEIN_MODELS

    km = klein_models[klein_model_key]
    nf = NodeFactory()

    # Model loaders
    unet_id = nf.unet_loader(km["unet"], "default", node_id="1")
    clip_id = nf.clip_loader(
        km.get("clip", "qwen_3_8b.safetensors"),
        clip_type="flux2", device="default", node_id="2",
    )
    vae_id = nf.vae_loader(FLUX2_VAE, node_id="3")


    # Apply LoRA chain
    if loras:
        unet_id, clip_id, _trig = inject_lora_chain(nf, loras, _ref(unet_id), _ref(clip_id), base_id=100)
        # After LoRA chain, refs are [node_id, slot] lists.
        # Leave them as-is. Use _ref() for all downstream references.
    # Source image
    img_id = nf.load_image(image_filename, node_id="10")

    # Mask — solid > image file > SAM3 prompt. mask_filename wins over
    # sam3_prompt when both supplied (user override).
    if use_solid_mask:
        mask_id = nf.solid_mask(value=1.0, width=solid_mask_width,
                                height=solid_mask_height, node_id="12")
        mask_ref = [mask_id, 0]
    elif mask_filename:
        mask_img_id = nf.load_image(mask_filename, node_id="11")
        mask_conv_id = nf.image_to_mask([mask_img_id, 0], "red", node_id="12")
        mask_ref = [mask_conv_id, 0]
    elif sam3_prompt:
        # Helper returns MASK-typed ref directly; no ImageToMask needed.
        mask_ref = build_sam3_mask(nf, [img_id, 0], sam3_prompt,
                                    invert=sam3_invert,
                                    confidence=sam3_confidence,
                                    mask_expand=sam3_expand,
                                    mask_blur=sam3_blur)
    else:
        raise ValueError("build_klein_inpaint requires mask_filename, sam3_prompt, or use_solid_mask")

    # Optional mask expansion
    if grow_px != 0:
        grow_id = nf.grow_mask(mask_ref, grow_px, tapered_corners=True,
                               node_id="13")
        mask_ref = [grow_id, 0]

    # Image size + text conditioning
    size_id = nf.get_image_size_plus([img_id, 0], node_id="14")
    pos_id = nf.clip_encode(_ref(clip_id), prompt_text, node_id="15")
    guided_id = nf.flux_guidance([pos_id, 0], guidance, node_id="16")
    neg_id = nf.conditioning_zero_out([guided_id, 0], node_id="19")

    # VAE encode + SetLatentNoiseMask
    enc_id = nf.vae_encode([img_id, 0], [vae_id, 0], node_id="20")
    masked_latent_id = nf.set_latent_noise_mask([enc_id, 0], mask_ref,
                                                  node_id="21")

    # Optional DifferentialDiffusion + Enhancer chain
    model_ref = _ref(unet_id)
    if enhance:
        model_ref = _klein_enhance_model(nf, model_ref, [guided_id, 0], node_base_id=960)
    if use_differential_diffusion:
        dd_id = nf.differential_diffusion(model_ref, node_id="22")
        model_ref = [dd_id, 0]

    # Sampler — FluxGuidance (not ReferenceLatent) because
    # SetLatentNoiseMask already constrains generation to the masked region.
    guider_id = nf.cfg_guider(model_ref, [guided_id, 0], [neg_id, 0],
                              1.0, node_id="30")
    sampler_id = nf.ksampler_select("euler", node_id="31")
    sched_id = nf.basic_scheduler(model_ref, steps, denoise,
                                   scheduler="simple", node_id="32")
    noise_id = nf.random_noise(seed, node_id="33")

    sample_id = nf.sampler_custom_advanced(
        [noise_id, 0], [guider_id, 0], [sampler_id, 0],
        [sched_id, 0], [masked_latent_id, 0], node_id="40",
    )

    dec_id = nf.vae_decode([sample_id, 0], [vae_id, 0], node_id="50")
    nf.save_image([dec_id, 0], "spellcaster_klein_inpaint", node_id="60")

    return nf.build()


# ═══════════════════════════════════════════════════════════════════════════
#  Klein Virtual Try-On — 4-reference photoshoot composition
#  ─────────────────────────────────────────────────────────────────────────
#  Inspired by Sarcastic TOFU's "Flux.2 Klein 9B KV Dress Photoshoot"
#  workflow (CivitAI). Uses Klein's native multi-reference KV editing —
#  NO ControlNet, NO IPAdapter — just 4 parallel ReferenceLatent inputs
#  synthesised into one coherent output.
# ═══════════════════════════════════════════════════════════════════════════

def build_klein_virtual_tryon(face_filename, outfit_filename, prompt_text, seed,
                               bg_filename=None, pose_filename=None,
                               klein_model_key="Klein 9B", steps=4,
                               denoise=1.0, guidance=1.0,
                               loras=None, lora_name=None, lora_strength=1.0,
                               klein_models=None, enhance=False):
    """Klein Virtual Try-On — 4-reference photoshoot composition.

    Combines up to 4 reference images in a single Klein pass using
    chained ReferenceLatent nodes. Klein's KV editing natively
    synthesises the references into a coherent output — no ControlNet
    or IPAdapter needed.

    References (in chain order):
      1. Face / character identity (required)
      2. Outfit / wardrobe (required)
      3. Background / setting (optional — uses empty latent if omitted)
      4. Pose reference (optional — omit for model-decided pose)

    Pipeline:
      1. Load Klein UNET + CLIP + VAE
      2. Encode prompt (describes desired composition)
      3. Load + scale each reference image
      4. VAE-encode each reference to latent
      5. Chain ReferenceLatent: prompt → face → outfit → [bg] → [pose]
      6. Zero-out negative conditioning
      7. Klein sampler at full denoise (1.0)
      8. Decode + save

    Args:
        face_filename (str): Face / character identity reference.
        outfit_filename (str): Outfit / wardrobe reference (headless body).
        prompt_text (str): Scene description.
        seed (int): Random seed.
        bg_filename (str, optional): Background reference.
        pose_filename (str, optional): Pose reference (DAZ 3D render, etc).
        klein_model_key (str): "Klein 9B", "Klein 4B", etc.
        steps (int): 4 is standard for Klein.
        denoise (float): 1.0 for full generation from references.
        guidance (float): CFG, typically 1.0 for Klein.
        loras, lora_name, lora_strength: Optional LoRA.
        klein_models (dict, optional): Model path mapping.
        enhance (bool): Wire Flux2Klein-Enhancer nodes if True.

    Returns:
        dict: ComfyUI workflow.

    Credit: Virtual try-on concept from Sarcastic TOFU's Klein 9B KV
    Dress Photoshoot workflow (CivitAI).
    """
    if klein_models is None:
        klein_models = KLEIN_MODELS
    if lora_name and not loras:
        loras = [{"name": lora_name, "strength": lora_strength}]

    km = klein_models[klein_model_key]
    nf = NodeFactory()

    # Model loaders
    unet_id = nf.unet_loader(km["unet"], "default", node_id="1")
    clip_id = nf.clip_loader(
        km.get("clip", "qwen_3_8b.safetensors"),
        clip_type="flux2", device="default", node_id="2",
    )
    vae_id = nf.vae_loader(FLUX2_VAE, node_id="3")

    # LoRA chain
    if loras:
        unet_id, clip_id, _trig = inject_lora_chain(
            nf, loras, _ref(unet_id), _ref(clip_id), base_id=100)
        # After LoRA chain, refs are [node_id, slot] lists.
        # Leave them as-is. Use _ref() for all downstream references.

    # Text conditioning
    pos_id = nf.clip_encode(_ref(clip_id), prompt_text, node_id="4")
    neg_id = nf.conditioning_zero_out([pos_id, 0], node_id="5")

    # Load + scale + encode each reference, then chain as ReferenceLatent.
    # Required: face (slot 1), outfit (slot 2). Optional: bg (3), pose (4).
    ref_inputs = [
        ("face", face_filename),
        ("outfit", outfit_filename),
    ]
    if bg_filename:
        ref_inputs.append(("bg", bg_filename))
    if pose_filename:
        ref_inputs.append(("pose", pose_filename))

    cond_chain = [pos_id, 0]
    first_size_id = None
    for i, (label, filename) in enumerate(ref_inputs):
        base = 200 + i * 10
        img = nf.load_image(filename, node_id=str(base))
        scaled = nf.image_scale_to_total_pixels(
            [img, 0], megapixels=1.0, node_id=str(base + 1))
        enc = nf.vae_encode([scaled, 0], [vae_id, 0], node_id=str(base + 2))
        ref = nf.reference_latent(cond_chain, [enc, 0], node_id=str(base + 3))
        cond_chain = [ref, 0]
        # Use first reference (face) dimensions for the empty latent
        if i == 0:
            first_size_id = nf.get_image_size([scaled, 0], node_id=str(base + 4))

    # Empty latent at face-reference dimensions
    empty_latent_id = nf.empty_latent_image(1024, 1024, node_id="15")
    if first_size_id:
        # Overwrite with dynamic size from face reference
        empty_latent_id = nf._add("EmptyLatentImage", {
            "width": [first_size_id, 0],
            "height": [first_size_id, 1],
            "batch_size": 1,
        }, node_id="16")

    # Optional Flux2Klein-Enhancer
    model_for_guider = _ref(unet_id)
    if enhance:
        model_for_guider = _klein_enhance_model(nf, _ref(unet_id), [pos_id, 0])

    # Sampler — full denoise since references provide all structure
    guider_id = nf.cfg_guider(model_for_guider, cond_chain, [neg_id, 0],
                              guidance, node_id="30")
    sampler_id = nf.ksampler_select("euler", node_id="31")
    sched_id = nf.basic_scheduler(_ref(unet_id), steps, denoise,
                                   scheduler="simple", node_id="32")
    noise_id = nf.random_noise(seed, node_id="33")

    sample_id = nf.sampler_custom_advanced(
        [noise_id, 0], [guider_id, 0], [sampler_id, 0],
        [sched_id, 0], [empty_latent_id, 0], node_id="40",
    )

    dec_id = nf.vae_decode([sample_id, 0], [vae_id, 0], node_id="50")
    nf.save_image([dec_id, 0], "klein_tryon", node_id="51")

    return nf.build()


# ═══════════════════════════════════════════════════════════════════════════
#  Klein Scene img2img — actual img2img (VAEEncode → latent_image)
#                        NO ReferenceLatent, uses FluxGuidance + BasicScheduler
# ═══════════════════════════════════════════════════════════════════════════

def build_klein_scene_img2img(image_filename, prompt_text, seed,
                               klein_model_key="Klein 9B", steps=20,
                               denoise=0.30, guidance=1.0,
                               klein_models=None,
                               loras=None, enhance=True):
    """Klein scene img2img: harmonize a composited scene.

    Unlike build_klein_img2img which uses ReferenceLatent (generates from noise
    with reference guidance), this uses actual img2img: VAEEncode → latent_image
    with BasicScheduler denoise. The input image IS the starting latent.

    Used by Studio Set to blend actors into scenes with low denoise.
    """
    if klein_models is None:
        klein_models = KLEIN_MODELS

    km = klein_models[klein_model_key]
    nf = NodeFactory()

    # Model loaders
    unet_id = nf.unet_loader(km["unet"], "default", node_id="1")
    clip_id = nf.clip_loader(
        km.get("clip", "qwen_3_8b.safetensors"),
        clip_type="flux2", device="default", node_id="2",
    )
    vae_id = nf.vae_loader(FLUX2_VAE, node_id="3")


    # Apply LoRA chain
    if loras:
        unet_id, clip_id, _trig = inject_lora_chain(nf, loras, _ref(unet_id), _ref(clip_id), base_id=100)
        # After LoRA chain, refs are [node_id, slot] lists.
        # Leave them as-is. Use _ref() for all downstream references.
    # Source images (scene + actor — actor not used in workflow but loaded for context)
    scene_id = nf.load_image(image_filename, node_id="10")

    # Text conditioning with FluxGuidance
    pos_id = nf.clip_encode(_ref(clip_id), prompt_text, node_id="15")
    guided_id = nf.flux_guidance([pos_id, 0], guidance, node_id="16")
    neg_id = nf.conditioning_zero_out([guided_id, 0], node_id="17")

    # VAEEncode input → latent (actual img2img, not ReferenceLatent)
    enc_id = nf.vae_encode([scene_id, 0], [vae_id, 0], node_id="20")
    size_id = nf.get_image_size([scene_id, 0], node_id="25")

    # Enhancer chain
    _sc_model = _klein_enhance_model(nf, _ref(unet_id), [guided_id, 0], node_base_id=940) if enhance else _ref(unet_id)

    # Sampler — BasicScheduler with denoise
    guider_id = nf.cfg_guider(_sc_model, [guided_id, 0], [neg_id, 0],
                              1.0, node_id="30")
    sampler_id = nf.ksampler_select("euler", node_id="31")
    sched_id = nf.basic_scheduler(_sc_model, steps, denoise,
                                   scheduler="simple", node_id="32")
    noise_id = nf.random_noise(seed, node_id="33")

    sample_id = nf.sampler_custom_advanced(
        [noise_id, 0], [guider_id, 0], [sampler_id, 0],
        [sched_id, 0], [enc_id, 0], node_id="40",
    )

    dec_id = nf.vae_decode([sample_id, 0], [vae_id, 0], node_id="50")
    nf.save_image([dec_id, 0], "studio_set", node_id="60")

    return nf.build()


# ═══════════════════════════════════════════════════════════════════════════
#  Klein Multi-Reference Refiner
#  ─────────────────────────────────────────────────────────────────────────
#  Inspired by Elusarca's "Flux2 Klein 9B Ultimate 6-in-1 Workflow"
#  (https://civitai.com/models/2543188) — refiner pipeline adapted for
#  Spellcaster with permission from the author.
# ═══════════════════════════════════════════════════════════════════════════

def build_klein_refine(image_filename, klein_model_key, prompt_text, seed,
                       steps=4, guidance=1.0,
                       preprocessors=None,
                       loras=None, lora_name=None, lora_strength=1.0,
                       klein_models=None, enhance=False):
    """Klein Multi-Reference Refiner — enhance detail using structural references.

    Runs the input image through multiple preprocessors (LineArt, HED, Tile,
    DepthAnything) to extract structural features, then chains each as a
    ReferenceLatent feeding into a single Klein pass at full denoise.
    The result is a refined version of the input that preserves composition
    and structure while enhancing detail, lighting, and texture.

    This is the "make it look professional" one-click enhancement.

    Pipeline:
      1. Load Klein UNET + CLIP + VAE
      2. Encode prompt (enhancement/refinement instructions)
      3. Load and scale input image
      4. Run input through up to 4 preprocessors:
         - LineArtPreprocessor → structural lines
         - HEDPreprocessor → soft edges
         - TilePreprocessor → tile detail
         - DepthAnythingV2Preprocessor → depth map
      5. Encode each preprocessor output through VAE
      6. Chain ReferenceLatent nodes: prompt → ref1 → ref2 → ref3 → ref4
      7. Zero-out negative conditioning
      8. Encode ORIGINAL image → latent for the sampler input
      9. Run Klein sampler at full denoise (1.0)
      10. Decode + optional ColorMatchV2 to preserve input colors
      11. Save

    Args:
        image_filename (str): Path to input image.
        klein_model_key (str): "Klein 9B", "Klein 4B", etc.
        prompt_text (str): Enhancement prompt (e.g. "Cinematic studio
            lighting, ultra-realistic skin texture, 8k resolution")
        seed (int): Random seed.
        steps (int): 4 is standard for Klein.
        guidance (float): CFG, typically 1.0 for Klein.
        preprocessors (list[str], optional): Which preprocessors to use.
            Defaults to all four: ["lineart", "hed", "tile", "depth"].
            Set to a subset to save VRAM or skip unavailable nodes.
        loras (list, optional): LoRA chain dicts.
        lora_name (str, optional): Single LoRA fallback.
        lora_strength (float): Strength if lora_name used.
        klein_models (dict, optional): Model path mapping.

    Returns:
        dict: ComfyUI workflow.

    Credit: Refiner pipeline adapted from Elusarca's Flux2 Klein 9B
    Ultimate 6-in-1 Workflow (CivitAI, April 2026) with permission.
    """
    if klein_models is None:
        klein_models = KLEIN_MODELS
    if preprocessors is None:
        preprocessors = ["lineart", "hed", "tile", "depth"]
    if lora_name and not loras:
        loras = [{"name": lora_name, "strength": lora_strength}]

    km = klein_models[klein_model_key]
    nf = NodeFactory()

    # Model loaders
    unet_id = nf.unet_loader(km["unet"], "default", node_id="1")
    clip_id = nf.clip_loader(
        km.get("clip", "qwen_3_8b.safetensors"),
        clip_type="flux2", device="default", node_id="2",
    )
    vae_id = nf.vae_loader(FLUX2_VAE, node_id="3")

    # LoRA chain
    if loras:
        unet_id, clip_id, _trig = inject_lora_chain(
            nf, loras, _ref(unet_id), _ref(clip_id), base_id=100)
        # After LoRA chain, refs are [node_id, slot] lists.
        # Leave them as-is. Use _ref() for all downstream references.

    # Text conditioning
    pos_id = nf.clip_encode(_ref(clip_id), prompt_text, node_id="4")
    neg_id = nf.conditioning_zero_out([pos_id, 0], node_id="5")

    # Load and scale input image
    img_id = nf.load_image(image_filename, node_id="10")
    scaled_id = nf.image_scale_to_total_pixels([img_id, 0], megapixels=1.0,
                                                node_id="11")

    # Run preprocessors and chain ReferenceLatent nodes.
    # Each preprocessor output is VAE-encoded, then fed as a
    # ReferenceLatent so Klein sees multiple structural "hints"
    # simultaneously.
    _PREPROC_MAP = {
        "lineart": ("LineArtPreprocessor", {"coarse": "disable", "resolution": 1024}),
        "hed":     ("HEDPreprocessor", {"safe": "disable", "resolution": 1024}),
        "tile":    ("TilePreprocessor", {"pyrUp_iters": 4, "resolution": 384}),
        "depth":   ("DepthAnythingV2Preprocessor", {"ckpt_name": "depth_anything_v2_vitl.pth", "resolution": 1024}),
    }

    # Start the conditioning chain from the prompt
    cond_chain = [pos_id, 0]
    pp_base_id = 200
    for i, pp_name in enumerate(preprocessors):
        if pp_name not in _PREPROC_MAP:
            continue
        class_type, kwargs = _PREPROC_MAP[pp_name]
        pp_id = nf.preprocessor(class_type, [scaled_id, 0],
                                node_id=str(pp_base_id + i * 10), **kwargs)
        enc_id = nf.vae_encode([pp_id, 0], [vae_id, 0],
                               node_id=str(pp_base_id + i * 10 + 1))
        ref_id = nf.reference_latent(cond_chain, [enc_id, 0],
                                     node_id=str(pp_base_id + i * 10 + 2))
        cond_chain = [ref_id, 0]

    # Encode original image for the sampler latent input
    orig_enc_id = nf.vae_encode([scaled_id, 0], [vae_id, 0], node_id="13")

    # Optional Flux2Klein-Enhancer
    model_for_guider = _ref(unet_id)
    if enhance:
        model_for_guider = _klein_enhance_model(nf, _ref(unet_id), [pos_id, 0])

    # Sampler — full denoise (1.0) since the references provide structure
    guider_id = nf.cfg_guider(model_for_guider, cond_chain, [neg_id, 0],
                              guidance, node_id="30")
    sampler_id = nf.ksampler_select("euler", node_id="31")
    sched_id = nf.basic_scheduler(_ref(unet_id), steps, 1.0,
                                   scheduler="simple", node_id="32")
    noise_id = nf.random_noise(seed, node_id="33")

    sample_id = nf.sampler_custom_advanced(
        [noise_id, 0], [guider_id, 0], [sampler_id, 0],
        [sched_id, 0], [orig_enc_id, 0], node_id="40",
    )

    dec_id = nf.vae_decode([sample_id, 0], [vae_id, 0], node_id="50")
    nf.save_image([dec_id, 0], "klein_refine", node_id="51")

    return nf.build()


# ═══════════════════════════════════════════════════════════════════════════
#  Klein Auto-Inpaint — Florence2 segmentation mask + Klein inpaint
#  ─────────────────────────────────────────────────────────────────────────
#  Inspired by Elusarca's "Flux2 Klein 9B Ultimate 6-in-1 Workflow"
#  (https://civitai.com/models/2543188) — auto-mask pipeline adapted for
#  Spellcaster with permission from the author.
# ═══════════════════════════════════════════════════════════════════════════

def build_klein_auto_inpaint(image_filename, mask_prompt, inpaint_prompt, seed,
                              klein_model_key="Klein 9B",
                              steps=4, denoise=1.0, guidance=1.0,
                              florence_model="microsoft/Florence-2-base",
                              loras=None, lora_name=None, lora_strength=1.0,
                              klein_models=None, enhance=True):
    """Klein Auto-Inpaint — describe what to mask, then inpaint it.

    Uses Florence2's referring_expression_segmentation to automatically
    generate a mask from a text description (e.g. "the shirt", "the
    background", "her hair"), then feeds the mask into Klein's inpaint
    pipeline. No manual mask painting needed.

    Pipeline:
      1. Load Klein UNET + CLIP + VAE
      2. Load Florence2 model
      3. Run Florence2 with mask_prompt → get segmentation mask
      4. Encode image + mask with VAEEncodeForInpaint
      5. ReferenceLatent chain with original encoded image
      6. Klein sampler pass
      7. Decode + save

    Args:
        image_filename (str): Path to input image.
        mask_prompt (str): What to segment, e.g. "the shirt", "the hair".
        inpaint_prompt (str): What should replace the masked area.
        seed (int): Random seed.
        klein_model_key (str): Model variant.
        steps (int): Klein steps (default 4).
        denoise (float): Inpaint strength (default 1.0).
        guidance (float): CFG scale (default 1.0).
        florence_model (str): Florence2 model name.
        loras, lora_name, lora_strength: Optional LoRA.
        klein_models (dict, optional): Model path mapping.

    Returns:
        dict: ComfyUI workflow.

    Requires: ComfyUI-Florence2 custom node pack (kijai).

    Credit: Auto-mask concept from Elusarca's Flux2 Klein 9B Ultimate
    6-in-1 Workflow (CivitAI, April 2026) with permission.
    """
    if klein_models is None:
        klein_models = KLEIN_MODELS
    if lora_name and not loras:
        loras = [{"name": lora_name, "strength": lora_strength}]

    km = klein_models[klein_model_key]
    nf = NodeFactory()

    # Model loaders
    unet_id = nf.unet_loader(km["unet"], "default", node_id="1")
    clip_id = nf.clip_loader(
        km.get("clip", "qwen_3_8b.safetensors"),
        clip_type="flux2", device="default", node_id="2",
    )
    vae_id = nf.vae_loader(FLUX2_VAE, node_id="3")

    # LoRA chain
    if loras:
        unet_id, clip_id, _trig = inject_lora_chain(
            nf, loras, _ref(unet_id), _ref(clip_id), base_id=100)
        # After LoRA chain, refs are [node_id, slot] lists.
        # Leave them as-is. Use _ref() for all downstream references.

    # Text conditioning
    pos_id = nf.clip_encode(_ref(clip_id), inpaint_prompt, node_id="4")
    neg_zero = nf.conditioning_zero_out([pos_id, 0], node_id="5")

    # Input image
    img_id = nf.load_image(image_filename, node_id="10")
    scaled_id = nf.image_scale_to_total_pixels([img_id, 0], megapixels=1.0,
                                                node_id="11")

    # Florence2 auto-segmentation → mask
    fl2_model_id = nf._add("DownloadAndLoadFlorence2Model", {
        "model": florence_model,
        "precision": "fp16",
    }, node_id="60")

    fl2_run_id = nf._add("Florence2Run", {
        "image": [scaled_id, 0],
        "florence2_model": [fl2_model_id, 0],
        "text_input": mask_prompt,
        "task": "referring_expression_segmentation",
        "fill_mask": True,
        "output_mask_select": True,
        "max_new_tokens": 1024,
        "num_beams": 3,
        "keep_model_loaded": True,
        "seed": seed,
    }, node_id="61")

    # VAEEncodeForInpaint with Florence2's mask (output slot 1)
    inpaint_enc_id = nf._add("VAEEncodeForInpaint", {
        "pixels": [scaled_id, 0],
        "vae": [vae_id, 0],
        "mask": [fl2_run_id, 1],  # mask output
        "grow_mask_by": 15,
    }, node_id="13")

    # ReferenceLatent chain — original image provides context
    orig_enc_id = nf.vae_encode([scaled_id, 0], [vae_id, 0], node_id="14")
    ref_pos = nf.reference_latent([pos_id, 0], [inpaint_enc_id, 0],
                                  node_id="20")
    ref2_pos = nf.reference_latent([ref_pos, 0], [orig_enc_id, 0],
                                   node_id="21")
    neg_id = nf.conditioning_zero_out([pos_id, 0], node_id="22")

    # Enhancer chain
    _ai_model = _klein_enhance_model(nf, _ref(unet_id), [pos_id, 0], node_base_id=950) if enhance else _ref(unet_id)

    # Sampler
    guider_id = nf.cfg_guider(_ai_model, [ref2_pos, 0], [neg_id, 0],
                              guidance, node_id="30")
    sampler_id = nf.ksampler_select("euler", node_id="31")
    sched_id = nf.basic_scheduler(_ai_model, steps, denoise,
                                   scheduler="simple", node_id="32")
    noise_id = nf.random_noise(seed, node_id="33")

    sample_id = nf.sampler_custom_advanced(
        [noise_id, 0], [guider_id, 0], [sampler_id, 0],
        [sched_id, 0], [inpaint_enc_id, 0], node_id="40",
    )

    dec_id = nf.vae_decode([sample_id, 0], [vae_id, 0], node_id="50")
    nf.save_image([dec_id, 0], "klein_auto_inpaint", node_id="51")

    return nf.build()


# ═══════════════════════════════════════════════════════════════════════════
#  Klein Color Match — post-generation color correction
#  ─────────────────────────────────────────────────────────────────────────
#  Inspired by Elusarca's "Flux2 Klein 9B Ultimate 6-in-1 Workflow"
#  (https://civitai.com/models/2543188) — color match step adapted for
#  Spellcaster with permission from the author.
# ═══════════════════════════════════════════════════════════════════════════

def build_klein_color_match(target_filename, reference_filename,
                            method="mkl", strength=0.95):
    """Color-match a generated image to a reference photo.

    Useful when Klein's output drifts in color temperature compared to
    the input (Klein has a known warm/red shift). Also works as a batch
    consistency tool — generate N variants, then color-match them all
    to one reference so they share a coherent palette.

    Pipeline:
      1. Load target image (the generated output)
      2. Load reference image (the color source)
      3. ColorMatchV2 (MKL / histogram / reinhard)
      4. Save

    Args:
        target_filename (str): Image to color-correct.
        reference_filename (str): Image whose colors to match.
        method (str): "mkl" (default, best), "histogram", or "reinhard".
        strength (float): Blend factor 0.0-1.0 (default 0.95).

    Returns:
        dict: ComfyUI workflow.

    Requires: comfyui-kjnodes custom node pack.

    Credit: Color match technique from Elusarca's Flux2 Klein 9B Ultimate
    6-in-1 Workflow (CivitAI, April 2026) with permission.
    """
    nf = NodeFactory()

    target_id = nf.load_image(target_filename, node_id="1")
    ref_id = nf.load_image(reference_filename, node_id="2")

    match_id = nf._add("ColorMatchV2", {
        "image_target": [target_id, 0],
        "image_ref": [ref_id, 0],
        "method": method,
        "strength": strength,
        "multithread": True,
    }, node_id="10")

    nf.save_image([match_id, 0], "klein_color_match", node_id="20")

    return nf.build()


# ═══════════════════════════════════════════════════════════════════════════
#  SAM3 Segment — standalone text-prompted segmentation -> mask
#  ───────────────────────────────────────────────────────────────────────
#  Architecture-agnostic. Works with ANY downstream tool (inpaint, rembg,
#  face detail, etc). In the GIMP plugin this becomes a selection tool.
# ═══════════════════════════════════════════════════════════════════════════

def build_sam3_segment(image_filename, prompt, confidence=0.6,
                       output_mode="Merged", mask_expand=0, mask_blur=0,
                       invert=False):
    """SAM3 Segment — detect a subject by text and return its mask.

    Uses SAM3's text-prompted segmentation to find any subject in the
    image. The mask can be used as a GIMP selection, an inpaint mask,
    or fed into any downstream tool.

    Output: a black-and-white mask image (white = detected subject).

    Args:
        image_filename (str): Image to segment.
        prompt (str): What to detect, e.g. "person", "shirt", "hair",
            "background", "cat". Empty string = auto-detect all.
        confidence (float): Detection threshold (0.0-1.0, default 0.6).
        output_mode (str): "Merged" (all matches as one mask) or
            "Separate" (one mask per instance).
        mask_expand (int): Pixels to grow the mask outward.
        mask_blur (int): Gaussian blur on mask edges.
        invert (bool): Invert the mask (select everything EXCEPT target).

    Returns:
        dict: ComfyUI workflow. Output is a mask saved as image.

    Requires: SAM3 node pack.
    """
    nf = NodeFactory()

    img_id = nf.load_image(image_filename, node_id="1")

    sam3_id = nf._add("SAM3Segment", {
        "prompt": prompt,
        "output_mode": output_mode,
        "confidence_threshold": confidence,
        "max_segments": 0,
        "segment_pick": 0,
        "mask_blur": 0,
        "mask_offset": 0,
        "device": "Auto",
        "invert_output": invert,
        "unload_model": False,
        "background": "Alpha",
        "background_color": "#222222",
        "image": [img_id, 0],
    }, node_id="10")

    # Optionally expand + blur the mask
    mask_ref = [sam3_id, 1]
    if mask_expand > 0 or mask_blur > 0:
        grow_id = nf._add("GrowMaskWithBlur", {
            "expand": mask_expand,
            "incremental_expandrate": 0,
            "tapered_corners": True,
            "flip_input": False,
            "blur_radius": mask_blur,
            "lerp_alpha": 1,
            "decay_factor": 1,
            "fill_holes": False,
            "mask": mask_ref,
        }, node_id="11")
        mask_ref = [grow_id, 0]

    # Convert mask to saveable image
    mask_img = nf._add("MaskToImage", {
        "mask": mask_ref,
    }, node_id="20")

    # Save the segmented subject (foreground on alpha from SAM3 slot 0)
    nf.save_image([sam3_id, 0], "sam3_subject", node_id="30")
    # Save the mask as a separate image
    nf.save_image([mask_img, 0], "sam3_mask", node_id="31")

    return nf.build()


# ═══════════════════════════════════════════════════════════════════════════
#  SAM3 + Background Remove + Auto-Crop — standalone subject extraction
# ═══════════════════════════════════════════════════════════════════════════

def build_sam3_extract(image_filename, prompt="person", confidence=0.6,
                       auto_crop=False):
    """SAM3 Extract — detect a subject, remove background.

    Combines SAM3 segmentation with BiRefNet background removal.
    Output is a full-canvas-size PNG with the subject on transparent
    background, preserving original position and scale.

    When auto_crop=True, additionally crops to subject bounds (useful
    for standalone export, but not for GIMP layer overlay).

    Args:
        image_filename (str): Image containing the subject.
        prompt (str): What to extract, e.g. "person", "cat".
        confidence (float): Detection threshold.
        auto_crop (bool): If True, crop to subject bounds. Default False
            to preserve position when importing as a GIMP layer.

    Returns:
        dict: ComfyUI workflow.

    Requires: SAM3 node pack + BiRefNet RMBG.
    """
    nf = NodeFactory()

    img_id = nf.load_image(image_filename, node_id="1")

    # BiRefNet background removal (higher quality than SAM3's built-in)
    rmbg_id = nf._add("BiRefNetRMBG", {
        "model": "BiRefNet-general",
        "mask_blur": 0,
        "mask_offset": 0,
        "invert_output": False,
        "refine_foreground": False,
        "background": "Alpha",
        "background_color": "#222222",
        "image": [img_id, 0],
    }, node_id="10")

    output_ref = [rmbg_id, 0]

    # Optional auto-crop to subject bounds
    if auto_crop:
        crop_id = nf._add("ImageCropByMask", {
            "image": [rmbg_id, 0],
            "mask": [rmbg_id, 1],
        }, node_id="20")
        output_ref = [crop_id, 0]

    nf.save_image(output_ref, "sam3_extracted", node_id="30")

    return nf.build()


# ═══════════════════════════════════════════════════════════════════════════
#  Magic Eraser — SAM3 detect + LaMa inpaint (zero-config distraction removal)
# ═══════════════════════════════════════════════════════════════════════════

def build_magic_eraser(image_filename, prompt, confidence=0.6,
                       mask_expand=8, mask_blur=4, gaussblur_radius=8):
    """Magic Eraser — SAM3 detect + LaMa inpaint.

    User describes an unwanted object ("power line", "tourist in the background",
    "car on the road", "watermark") and the pipeline:
      1. Runs SAM3 to segment the described object.
      2. Grows + blurs the mask so LaMa can hide edge artifacts and contact
         shadows.
      3. LaMa-inpaints over the mask (no diffusion, no seed, deterministic).
      4. Returns the cleaned image.

    No mask painting, no selection needed. The only thing the user provides is
    the description.

    Args:
        image_filename (str): Image to clean up.
        prompt (str): Description of what to remove.
        confidence (float): SAM3 detection threshold (0.0-1.0, default 0.6).
        mask_expand (int): Grow the detected mask by this many pixels before
            inpainting (default 8). Helps LaMa cover shadows and fringing.
        mask_blur (int): Gaussian blur on the grown mask edge (default 4) for
            seamless blending.
        gaussblur_radius (int): LaMa's own edge feather (default 8).

    Returns:
        dict: ComfyUI workflow.

    Node IDs:
      - "1":  LoadImage
      - "10": SAM3Segment
      - "11": GrowMaskWithBlur (optional)
      - "20": LamaRemover
      - "30": SaveImage

    Requires: SAM3 node pack AND ComfyUI-LaMA-Preprocessor (LamaRemover).

    Gotchas:
      - Large removals (>30% of image) hit LaMa's quality ceiling — fall back
        to diffusion inpaint for those.
      - If SAM3 returns an empty mask (nothing matched), LaMa is a no-op and
        the image comes back essentially unchanged. Check the prompt spelling.
    """
    nf = NodeFactory()
    img_id = nf.load_image(image_filename, node_id="1")

    sam3_id = nf._add("SAM3Segment", {
        "prompt": prompt,
        "output_mode": "Merged",
        "confidence_threshold": confidence,
        "max_segments": 0,
        "segment_pick": 0,
        "mask_blur": 0,
        "mask_offset": 0,
        "device": "Auto",
        "invert_output": False,
        "unload_model": False,
        "background": "Alpha",
        "background_color": "#000000",
        "image": [img_id, 0],
    }, node_id="10")

    mask_ref = [sam3_id, 1]
    if mask_expand > 0 or mask_blur > 0:
        grown_id = nf._add("GrowMaskWithBlur", {
            "expand": int(mask_expand),
            "incremental_expandrate": 0,
            "tapered_corners": True,
            "flip_input": False,
            "blur_radius": int(mask_blur),
            "lerp_alpha": 1,
            "decay_factor": 1,
            "fill_holes": False,
            "mask": mask_ref,
        }, node_id="11")
        mask_ref = [grown_id, 0]

    lama_id = nf.lama_remover([img_id, 0], mask_ref,
                              gaussblur_radius=int(gaussblur_radius),
                              node_id="20")
    nf.save_image([lama_id, 0], "spellcaster_magic_eraser", node_id="30")

    return nf.build()


# ═══════════════════════════════════════════════════════════════════════════
#  Klein SAM3 Inpaint — text-prompted segmentation + Klein inpainting
#  ───────────────────────────────────────────────────────────────────────
#  Adapted from a local ComfyUI workflow using SAM3Segment + Klein
#  ReferenceLatent + DifferentialDiffusion + InpaintCropImproved.
#  The original used per-segment for-loops; Spellcaster simplifies to
#  single-segment mode (call multiple times for multi-segment).
# ═══════════════════════════════════════════════════════════════════════════

def build_klein_sam3_inpaint(image_filename, segment_prompt, inpaint_prompt, seed,
                              ref_filename=None,
                              klein_model_key="Klein 9B",
                              steps=10, guidance=1.0,
                              mask_expand=120, mask_blur=15,
                              confidence=0.6,
                              loras=None, lora_name=None, lora_strength=1.0,
                              klein_models=None, enhance=False):
    """Klein SAM3 Inpaint — detect a region by text and inpaint it.

    Uses SAM3's text-prompted segmentation to automatically detect a
    subject (e.g. "person", "shirt", "background"), then inpaints the
    detected region using Klein with optional reference image guidance.

    Two modes:
      - **With reference** (ref_filename provided): The reference image is
        background-removed, cropped, and VAE-encoded as a ReferenceLatent.
        Klein uses it as structural/identity guidance for the inpaint.
        Use case: replace one person with another.
      - **Without reference** (ref_filename=None): Standard Klein inpaint
        guided only by the text prompt. Use case: change clothing, fix
        details, remove objects.

    Pipeline:
      1. Load Klein UNET + CLIP + VAE
      2. Load source image
      3. SAM3Segment with segment_prompt → mask of detected region
      4. GrowMaskWithBlur to expand + feather the mask edges
      5. (Optional) Load reference → BiRefNetRMBG → crop → scale → VAEEncode
         → ReferenceLatent conditioning chain
      6. FluxGuidance on positive conditioning
      7. InpaintModelConditioning (combines positive, negative, image, mask)
      8. DifferentialDiffusion on model for smooth edge transitions
      9. BasicGuider + SamplerCustomAdvanced with BetaSamplingScheduler
      10. VAEDecode + save

    Args:
        image_filename (str): Source image to edit.
        segment_prompt (str): What SAM3 should detect, e.g. "person",
            "the shirt", "hair", "background".
        inpaint_prompt (str): What to generate in the masked area.
        seed (int): Random seed.
        ref_filename (str, optional): Reference image for identity/style.
        klein_model_key (str): Model variant.
        steps (int): Sampling steps (default 10 for quality inpaint).
        guidance (float): FluxGuidance scale (default 4.0 for inpaint).
        mask_expand (int): Pixels to grow the SAM3 mask (default 120).
        mask_blur (int): Blur radius on expanded mask (default 15).
        confidence (float): SAM3 detection confidence (default 0.6).
        loras, lora_name, lora_strength: Optional LoRA.
        klein_models (dict, optional): Model path mapping.
        enhance (bool): Wire Flux2Klein-Enhancer if True.

    Returns:
        dict: ComfyUI workflow.

    Requires: SAM3 node pack, comfyui-inpaint-nodes (optional but
    recommended for InpaintCropImproved/Stitch).
    """
    if klein_models is None:
        klein_models = KLEIN_MODELS
    if lora_name and not loras:
        loras = [{"name": lora_name, "strength": lora_strength}]

    km = klein_models[klein_model_key]
    nf = NodeFactory()

    # Model loaders
    unet_id = nf.unet_loader(km["unet"], "default", node_id="1")
    clip_id = nf.clip_loader(
        km.get("clip", "qwen_3_8b.safetensors"),
        clip_type="flux2", device="default", node_id="2",
    )
    vae_id = nf.vae_loader(FLUX2_VAE, node_id="3")

    # LoRA chain
    if loras:
        unet_id, clip_id, _trig = inject_lora_chain(
            nf, loras, _ref(unet_id), _ref(clip_id), base_id=100)
        # After LoRA chain, refs are [node_id, slot] lists.
        # Leave them as-is. Use _ref() for all downstream references.

    # Load source image
    img_id = nf.load_image(image_filename, node_id="10")

    # SAM3 segmentation — detect the target region by text prompt
    sam3_id = nf._add("SAM3Segment", {
        "prompt": segment_prompt,
        "output_mode": "Merged",
        "confidence_threshold": confidence,
        "max_segments": 0,
        "segment_pick": 0,
        "mask_blur": 0,
        "mask_offset": 0,
        "device": "Auto",
        "invert_output": False,
        "unload_model": False,
        "background": "Alpha",
        "background_color": "#222222",
        "image": [img_id, 0],
    }, node_id="20")

    # Grow + blur the mask for smooth edges
    grow_id = nf._add("GrowMaskWithBlur", {
        "expand": mask_expand,
        "incremental_expandrate": 0,
        "tapered_corners": True,
        "flip_input": False,
        "blur_radius": mask_blur,
        "lerp_alpha": 1,
        "decay_factor": 1,
        "fill_holes": False,
        "mask": [sam3_id, 1],
    }, node_id="21")

    # Text conditioning
    pos_id = nf.clip_encode(_ref(clip_id), inpaint_prompt, node_id="4")
    guided_id = nf.flux_guidance([pos_id, 0], guidance, node_id="5")
    neg_id = nf.clip_encode(_ref(clip_id), "", node_id="6")

    # Build conditioning chain — optionally with reference image
    cond_for_inpaint = [guided_id, 0]
    if ref_filename:
        # Background-remove the reference, crop, scale, encode
        ref_img_id = nf.load_image(ref_filename, node_id="50")
        rmbg_id = nf._add("BiRefNetRMBG", {
            "model": "BiRefNet-general",
            "mask_blur": 0,
            "mask_offset": 0,
            "invert_output": False,
            "refine_foreground": False,
            "background": "Alpha",
            "background_color": "#222222",
            "image": [ref_img_id, 0],
        }, node_id="51")
        crop_id = nf._add("ImageCropByMask", {
            "image": [rmbg_id, 0],
            "mask": [rmbg_id, 1],
        }, node_id="52")
        scaled_ref = nf.image_scale_to_total_pixels(
            [crop_id, 0], megapixels=1.0, node_id="53")
        ref_enc = nf.vae_encode([scaled_ref, 0], [vae_id, 0], node_id="54")
        # ReferenceLatent: inpaint crop → reference character
        ref_cond = nf.reference_latent(cond_for_inpaint, [ref_enc, 0],
                                       node_id="55")
        cond_for_inpaint = [ref_cond, 0]

    # Smart crop around the masked region — InpaintCropImproved handles
    # resizing, padding, and mask-aware context extraction. The inpaint
    # runs at higher resolution (the crop is naturally smaller than the
    # full image) for better detail, then stitches back seamlessly.
    crop_id = nf._add("InpaintCropImproved", {
        "downscale_algorithm": "bicubic",
        "upscale_algorithm": "lanczos",
        "preresize": True,
        "preresize_mode": "ensure minimum resolution",
        "preresize_min_width": 1024,
        "preresize_min_height": 1024,
        "preresize_max_width": 16384,
        "preresize_max_height": 16384,
        "mask_fill_holes": False,
        "mask_expand_pixels": 0,
        "mask_invert": False,
        "mask_blend_pixels": 4,
        "mask_hipass_filter": 0.1,
        "extend_for_outpainting": False,
        "extend_up_factor": 1,
        "extend_down_factor": 1,
        "extend_left_factor": 1,
        "extend_right_factor": 1,
        "context_from_mask_extend_factor": 1.1,
        "output_resize_to_target_size": True,
        "output_target_width": 1536,
        "output_target_height": 1536,
        "output_padding": "8",
        "device_mode": "gpu (much faster)",
        "image": [img_id, 0],
        "mask": [grow_id, 0],
    }, node_id="25")
    # crop_id outputs: [0]=stitcher, [1]=cropped_image, [2]=cropped_mask

    # Self-reference: encode the cropped region as a ReferenceLatent so
    # Klein preserves the surrounding context during inpainting
    crop_enc = nf.vae_encode([crop_id, 1], [vae_id, 0], node_id="26")
    ref_cond = nf.reference_latent(cond_for_inpaint, [crop_enc, 0],
                                   node_id="27")

    # InpaintModelConditioning on the CROPPED image + mask
    inpaint_cond_id = nf._add("InpaintModelConditioning", {
        "noise_mask": True,
        "positive": [ref_cond, 0],
        "negative": [neg_id, 0],
        "vae": [vae_id, 0],
        "pixels": [crop_id, 1],
        "mask": [crop_id, 2],
    }, node_id="30")

    # DifferentialDiffusionAdvanced for smooth mask-edge blending
    # (Advanced variant takes the latent samples + mask for per-pixel
    # denoise control — smoother than plain DifferentialDiffusion)
    diff_model = nf._add("DifferentialDiffusionAdvanced", {
        "multiplier": 1,
        "model": _ref(unet_id),
        "samples": [inpaint_cond_id, 2],
        "mask": [crop_id, 2],
    }, node_id="31")

    # Optional Flux2Klein-Enhancer
    model_for_guider = [diff_model, 0]
    if enhance:
        model_for_guider = _klein_enhance_model(nf, [diff_model, 0],
                                                 [guided_id, 0],
                                                 node_base_id=900)

    # Sampler: BasicGuider + BetaSamplingScheduler (from the workflow)
    guider_id = nf._add("BasicGuider", {
        "model": model_for_guider,
        "conditioning": [inpaint_cond_id, 0],
    }, node_id="35")
    sampler_id = nf.ksampler_select("euler", node_id="36")
    sched_id = nf._add("BetaSamplingScheduler", {
        "steps": steps,
        "alpha": 0.5,
        "beta": 0.5,
        "model": model_for_guider,
    }, node_id="37")
    noise_id = nf.random_noise(seed, node_id="38")

    sample_id = nf.sampler_custom_advanced(
        [noise_id, 0], [guider_id, 0], [sampler_id, 0],
        [sched_id, 0], [diff_model, 1],  # slot 1 from DifferentialDiffusionAdvanced
        node_id="40",
    )

    # Decode the inpainted crop and stitch back into the original image
    dec_id = nf.vae_decode([sample_id, 0], [vae_id, 0], node_id="45")
    stitch_id = nf._add("InpaintStitchImproved", {
        "stitcher": [crop_id, 0],
        "inpainted_image": [dec_id, 0],
    }, node_id="46")
    nf.save_image([stitch_id, 0], "klein_sam3", node_id="47")

    return nf.build()


# ═══════════════════════════════════════════════════════════════════════════
#  Klein Face Detailer — auto-detect and re-generate faces at high detail
#  ─────────────────────────────────────────────────────────────────────────
#  Requires: ComfyUI-Impact-Pack (ltdrdata) + face_yolov8m.pt YOLO model.
#  The detailer crops each detected face, re-generates it through Klein at
#  higher resolution, then composites back. Fixes hands/fingers too if the
#  YOLO model detects them. This is a POST-PROCESSING step — run it on an
#  already-generated image to clean up faces.
# ═══════════════════════════════════════════════════════════════════════════

def build_klein_face_detail(image_filename, prompt_text, seed,
                             klein_model_key="Klein 9B",
                             steps=4, denoise=0.4, guidance=1.0,
                             guide_size=512, max_size=1024,
                             detector_model="bbox/face_yolov8m.pt",
                             loras=None, lora_name=None, lora_strength=1.0,
                             klein_models=None, enhance=False):
    """Klein Face Detailer — detect faces and re-generate them at high detail.

    Post-processing step: takes an already-generated image, runs YOLO face
    detection, crops each detected face, re-generates the crop through
    Klein at higher resolution, and composites it back into the original.
    Dramatically improves face quality, especially on full-body shots
    where faces are small and lack detail.

    Pipeline:
      1. Load Klein UNET + CLIP + VAE
      2. Load input image
      3. Encode prompt (face-specific refinement instructions)
      4. Load YOLO detector (face_yolov8m.pt)
      5. FaceDetailer: detects → crops → re-generates → composites
      6. Save

    Args:
        image_filename (str): Image to refine (from a previous generation).
        prompt_text (str): Face description prompt (e.g. "detailed realistic
            face, sharp eyes, smooth skin, studio lighting").
        seed (int): Random seed.
        klein_model_key (str): Model variant.
        steps (int): Klein steps for face regeneration.
        denoise (float): How much to change each face (0.3-0.5 recommended).
        guidance (float): CFG scale.
        guide_size (int): Target face crop size in pixels.
        max_size (int): Max face crop size.
        detector_model (str): YOLO model filename in ultralytics/ folder.
        loras, lora_name, lora_strength: Optional LoRA.
        klein_models (dict, optional): Model path mapping.
        enhance (bool): Wire Flux2Klein-Enhancer if True.

    Returns:
        dict: ComfyUI workflow.

    Requires: ComfyUI-Impact-Pack (install via ComfyUI Manager).
    Model: face_yolov8m.pt in ComfyUI/models/ultralytics/bbox/
    """
    if klein_models is None:
        klein_models = KLEIN_MODELS
    if lora_name and not loras:
        loras = [{"name": lora_name, "strength": lora_strength}]

    km = klein_models[klein_model_key]
    nf = NodeFactory()

    # Model loaders
    unet_id = nf.unet_loader(km["unet"], "default", node_id="1")
    clip_id = nf.clip_loader(
        km.get("clip", "qwen_3_8b.safetensors"),
        clip_type="flux2", device="default", node_id="2",
    )
    vae_id = nf.vae_loader(FLUX2_VAE, node_id="3")

    # LoRA chain
    if loras:
        unet_id, clip_id, _trig = inject_lora_chain(
            nf, loras, _ref(unet_id), _ref(clip_id), base_id=100)
        # After LoRA chain, refs are [node_id, slot] lists.
        # Leave them as-is. Use _ref() for all downstream references.

    # Text conditioning
    pos_id = nf.clip_encode(_ref(clip_id), prompt_text, node_id="4")
    neg_id = nf.conditioning_zero_out([pos_id, 0], node_id="5")

    # Optional enhancer
    model_for_detail = _ref(unet_id)
    if enhance:
        model_for_detail = _klein_enhance_model(nf, _ref(unet_id), [pos_id, 0])

    # Load input image
    img_id = nf.load_image(image_filename, node_id="10")

    # YOLO face detector
    detector_id = nf._add("UltralyticsDetectorProvider", {
        "model_name": detector_model,
    }, node_id="20")

    # FaceDetailer — the Impact Pack's monolithic detect→crop→regen→composite
    detail_id = nf._add("FaceDetailer", {
        "image": [img_id, 0],
        "model": model_for_detail,
        "clip": _ref(clip_id),
        "vae": [vae_id, 0],
        "positive": [pos_id, 0],
        "negative": [neg_id, 0],
        "bbox_detector": [detector_id, 0],
        "guide_size": guide_size,
        "guide_size_for": True,
        "max_size": max_size,
        "seed": seed,
        "steps": steps,
        "cfg": guidance,
        "sampler_name": "euler",
        "scheduler": "simple",
        "denoise": denoise,
        "feather": 5,
        "noise_mask": True,
        "force_inpaint": True,
        "wildcard": "",
        "cycle": 1,
        "drop_size": 10,
        "bbox_threshold": 0.5,
        "bbox_dilation": 10,
        "bbox_crop_factor": 3.0,
        "sam_detection_hint": "center-1",
        "sam_dilation": 0,
        "sam_threshold": 0.93,
        "sam_bbox_expansion": 0,
        "sam_mask_hint_threshold": 0.7,
        "sam_mask_hint_use_negative": "False",
    }, node_id="30")

    # FaceDetailer output slot 0 = refined image
    nf.save_image([detail_id, 0], "klein_face_detail", node_id="40")

    return nf.build()


# ═══════════════════════════════════════════════════════════════════════════
#  Klein Object Generator — generate anything as a transparent layer
# ═══════════════════════════════════════════════════════════════════════════

def build_klein_generate_object(scene_filename, prompt_text, seed,
                                 klein_model_key="Klein 9B",
                                 width=1024, height=1024,
                                 steps=6, guidance=1.0,
                                 loras=None, lora_name=None, lora_strength=1.0,
                                 klein_models=None, enhance=True,
                                 nsfw_unlock_loras=None):
    """Klein Object Generator — generate any object/person as a transparent layer.

    State-of-the-art pipeline for generating objects that integrate
    perfectly into an existing scene:

    1. Uses the current canvas as a ReferenceLatent so the generated
       object matches the scene's lighting, color palette, and style
    2. Generates the object via Klein txt2img (from empty latent, NOT
       img2img — the object is fully synthetic, not a modification)
    3. Removes the background with BiRefNet (high-quality alpha matting)
    4. Outputs a transparent PNG ready to layer on top

    The result matches the scene because Klein's ReferenceLatent
    injection ensures the generated object inherits the reference
    image's color temperature, lighting direction, and visual style
    — even though it's generating from scratch.

    Args:
        scene_filename (str): Current canvas image (used as style/lighting
            reference, NOT as the generation input).
        prompt_text (str): What to generate. Be specific:
            "a red sports car, side view, matching studio lighting"
            "a tabby cat sitting, natural daylight"
            "a medieval sword with ornate handle, dramatic lighting"
        seed (int): Random seed.
        width, height: Output dimensions (should match canvas).
        steps (int): Klein sampling steps (6-10 recommended).
        guidance (float): How closely to follow the prompt (1.0 for Klein).
        enhance (bool): Use Flux2Klein-Enhancer nodes (default True).

    Returns:
        dict: ComfyUI workflow. Two outputs:
            - "klein_generated": raw generation (with background)
            - "klein_object": transparent cutout (background removed)

    Requires: BiRefNet RMBG node pack.
    """
    if klein_models is None:
        klein_models = KLEIN_MODELS
    if lora_name and not loras:
        loras = [{"name": lora_name, "strength": lora_strength}]

    km = klein_models[klein_model_key]
    nf = NodeFactory()

    # ── Model loaders ────────────────────────────────────────────────
    unet_id = nf.unet_loader(km["unet"], "default", node_id="1")
    clip_id = nf.clip_loader(
        km.get("clip", "qwen_3_8b.safetensors"),
        clip_type="flux2", device="default", node_id="2",
    )
    vae_id = nf.vae_loader(FLUX2_VAE, node_id="3")

    # LoRA chain
    if loras:
        unet_id, clip_id, _trig = inject_lora_chain(
            nf, loras, _ref(unet_id), _ref(clip_id), base_id=100)
        # After LoRA chain, refs are [node_id, slot] lists.
        # Leave them as-is. Use _ref() for all downstream references.

    # ── NSFW unlock LoRAs (NSFW edition only — patched by build_nsfw.py)
    # These LoRAs remove content filters from Klein so it can generate
    # adult content. Accepts both Flux 2 Klein native LoRAs and Flux 1
    # Dev LoRAs (which Klein inherits compatibility with at lower strength).
    # In the SFW edition this list is always empty/None.
    if nsfw_unlock_loras:
        _nsfw_chain = []
        for l in nsfw_unlock_loras:
            _path = l.get("path", l.get("name", ""))
            _str = l.get("strength", 0.85)
            # Flux Dev LoRAs on Klein need reduced strength to avoid artifacts
            if "Flux-1-Dev" in _path or "flux-1-dev" in _path.lower():
                _str = min(_str, 0.65)
            _nsfw_chain.append({"name": _path, "strength_model": _str,
                                 "strength_clip": _str})
        if _nsfw_chain:
            _u, _c, _ = inject_lora_chain(nf, _nsfw_chain,
                                           _ref(unet_id), _ref(clip_id), base_id=150)
            unet_id = _u if isinstance(_u, str) else _u[0]
            clip_id = _c if isinstance(_c, str) else _c[0]

    # ── Prompt: append "on a plain solid background" so BiRefNet can
    #    cleanly separate the object from the background ──────────────
    full_prompt = (
        f"{prompt_text}, isolated on a plain solid white background, "
        "centered in frame, studio product photography, clean edges, "
        "no clutter, professional lighting matching the reference scene"
    )

    # Text conditioning
    pos_id = nf.clip_encode(_ref(clip_id), full_prompt, node_id="4")
    neg_id = nf.conditioning_zero_out([pos_id, 0], node_id="5")

    # ── Enhancer chain ───────────────────────────────────────────────
    model_ref = _ref(unet_id)
    if enhance:
        model_ref = _klein_enhance_model(nf, _ref(unet_id), [pos_id, 0])

    # ── Load scene image as style/lighting reference ─────────────────
    scene_id = nf.load_image(scene_filename, node_id="10")
    scene_scaled = nf.image_scale_to_total_pixels([scene_id, 0],
                                                    megapixels=1.0,
                                                    node_id="11")
    scene_enc = nf.vae_encode([scene_scaled, 0], [vae_id, 0], node_id="12")

    # ReferenceLatent: scene provides lighting/style context
    ref_pos = nf.reference_latent([pos_id, 0], [scene_enc, 0], node_id="20")
    ref_neg = nf.reference_latent([neg_id, 0], [scene_enc, 0], node_id="21")

    # ── Empty latent at target size (txt2img, NOT img2img) ───────────
    empty_id = nf._add("EmptyLatentImage", {
        "width": width,
        "height": height,
        "batch_size": 1,
    }, node_id="25")

    # ── Klein sampler ────────────────────────────────────────────────
    guider_id = nf.cfg_guider(model_ref, [ref_pos, 0], [ref_neg, 0],
                              guidance, node_id="30")
    sampler_id = nf.ksampler_select("euler", node_id="31")
    # Full denoise (1.0) — generating from scratch, not editing
    sched_id = nf.basic_scheduler(model_ref, steps, 1.0,
                                   scheduler="simple", node_id="32")
    noise_id = nf.random_noise(seed, node_id="33")

    sample_id = nf.sampler_custom_advanced(
        [noise_id, 0], [guider_id, 0], [sampler_id, 0],
        [sched_id, 0], [empty_id, 0], node_id="35",
    )

    dec_id = nf.vae_decode([sample_id, 0], [vae_id, 0], node_id="36")

    # Save the raw generation (with background)
    nf.save_image([dec_id, 0], "klein_generated", node_id="40")

    # ── Background removal — BiRefNet for high-quality alpha ─────────
    rmbg_id = nf._add("BiRefNetRMBG", {
        "model": "BiRefNet-general",
        "mask_blur": 2,
        "mask_offset": 0,
        "invert_output": False,
        "refine_foreground": True,
        "background": "Alpha",
        "background_color": "#000000",
        "image": [dec_id, 0],
    }, node_id="50")

    # Save the transparent cutout
    nf.save_image([rmbg_id, 0], "klein_object", node_id="51")

    return nf.build()


# ═══════════════════════════════════════════════════════════════════════════
#  Klein Detail Enhancer — universal region detailer with presets
# ═══════════════════════════════════════════════════════════════════════════

# Detection presets: each maps to either a YOLO model or SAM3 text prompt
DETAIL_PRESETS = {
    "Face (sharp eyes, skin)": {
        "detector": "yolo", "model": "bbox/face_yolov8m.pt",
        "prompt": "extremely detailed face, sharp eyes with visible iris texture, "
                  "natural skin with pores, individual eyelashes, studio lighting",
        "denoise": 0.35, "guide_size": 512, "steps": 6,
    },
    "Eyes (iris, reflection)": {
        "detector": "sam3", "sam3_prompt": "eyes",
        "prompt": "ultra detailed eyes, sharp iris with visible color striations, "
                  "catchlight reflections, individual eyelashes, hyper-realistic eye detail",
        "denoise": 0.40, "guide_size": 384, "steps": 6,
    },
    "Hands (fingers, nails)": {
        "detector": "yolo", "model": "bbox/hand_yolov8s.pt",
        "prompt": "perfectly detailed hands, correct anatomy, five fingers, "
                  "natural fingernails, realistic skin texture, proper proportions",
        "denoise": 0.45, "guide_size": 512, "steps": 8,
    },
    "Skin (pores, texture)": {
        "detector": "sam3", "sam3_prompt": "skin",
        "prompt": "hyper-detailed natural skin texture, visible pores, "
                  "subsurface scattering, realistic skin imperfections, "
                  "natural oil sheen, photorealistic dermis",
        "denoise": 0.30, "guide_size": 512, "steps": 6,
    },
    "Hair (strands, volume)": {
        "detector": "sam3", "sam3_prompt": "hair",
        "prompt": "individual hair strands, flyaway hairs, natural hair texture, "
                  "volumetric hair detail, light catching individual strands, "
                  "realistic hair sheen and highlights",
        "denoise": 0.35, "guide_size": 512, "steps": 6,
    },
    "Feet (toes, detail)": {
        "detector": "sam3", "sam3_prompt": "feet",
        "prompt": "detailed realistic feet, correct toe anatomy, "
                  "natural toenails, skin texture, proper proportions",
        "denoise": 0.40, "guide_size": 512, "steps": 6,
    },
    "Clothing (fabric, texture)": {
        "detector": "sam3", "sam3_prompt": "clothing",
        "prompt": "detailed fabric texture, realistic material surface, "
                  "stitching detail, natural cloth folds and wrinkles, "
                  "material-accurate sheen and weight",
        "denoise": 0.30, "guide_size": 512, "steps": 6,
    },
    "Jewelry (metal, gems)": {
        "detector": "sam3", "sam3_prompt": "jewelry",
        "prompt": "hyper-detailed jewelry, sharp metallic reflections, "
                  "gemstone facets, intricate metalwork, realistic sparkle",
        "denoise": 0.35, "guide_size": 384, "steps": 6,
    },
    "Full Body (overall)": {
        "detector": "yolo", "model": "segm/person_yolov8m-seg.pt",
        "prompt": "highly detailed full body, sharp features, "
                  "realistic proportions, natural skin and clothing texture",
        "denoise": 0.35, "guide_size": 768, "steps": 6,
    },
    "Custom (describe region)": {
        "detector": "sam3", "sam3_prompt": "",
        "prompt": "",
        "denoise": 0.40, "guide_size": 512, "steps": 6,
    },
}


def build_klein_detail(image_filename, preset_key, prompt_text, seed,
                       klein_model_key="Klein 9B", steps=None, denoise=None,
                       guidance=1.0, guide_size=None, max_size=1024,
                       sam3_prompt=None, loras=None, lora_name=None,
                       lora_strength=1.0, klein_models=None, enhance=True):
    """Klein Detail Enhancer — detect ANY region and re-generate at high detail.

    Universal detailer: works with YOLO bbox detection (face, hands, person)
    or SAM3 text-prompted segmentation (eyes, skin, hair, clothing, custom).

    Pipeline:
      1. Load Klein UNET + CLIP + VAE + optional enhancers
      2. Load image
      3. Detect region (YOLO bbox or SAM3 text-prompted mask)
      4. For YOLO: FaceDetailer (detect → crop → regen → composite)
         For SAM3: SAM3Segment → GrowMask → InpaintCropImproved →
                   Klein regen → InpaintStitchImproved
      5. Save

    Args:
        image_filename (str): Image to enhance.
        preset_key (str): Key from DETAIL_PRESETS (or "Custom").
        prompt_text (str): Override prompt (or empty to use preset default).
        seed (int): Random seed.
        sam3_prompt (str): Override SAM3 detection prompt (for Custom preset).
        Other args: same as build_klein_face_detail.

    Returns:
        dict: ComfyUI workflow.
    """
    preset = DETAIL_PRESETS.get(preset_key, DETAIL_PRESETS["Face (sharp eyes, skin)"])
    _steps = steps or preset.get("steps", 6)
    _denoise = denoise if denoise is not None else preset.get("denoise", 0.4)
    _guide = guide_size or preset.get("guide_size", 512)
    _prompt = prompt_text or preset.get("prompt", "detailed, sharp, realistic")
    _det_type = preset.get("detector", "yolo")

    if klein_models is None:
        klein_models = KLEIN_MODELS
    if lora_name and not loras:
        loras = [{"name": lora_name, "strength": lora_strength}]

    km = klein_models[klein_model_key]
    nf = NodeFactory()

    # Model loaders
    unet_id = nf.unet_loader(km["unet"], "default", node_id="1")
    clip_id = nf.clip_loader(
        km.get("clip", "qwen_3_8b.safetensors"),
        clip_type="flux2", device="default", node_id="2",
    )
    vae_id = nf.vae_loader(FLUX2_VAE, node_id="3")

    # LoRA chain
    if loras:
        unet_id, clip_id, _trig = inject_lora_chain(
            nf, loras, _ref(unet_id), _ref(clip_id), base_id=100)
        # After LoRA chain, refs are [node_id, slot] lists.
        # Leave them as-is. Use _ref() for all downstream references.

    # Text conditioning
    pos_id = nf.clip_encode(_ref(clip_id), _prompt, node_id="4")
    neg_id = nf.conditioning_zero_out([pos_id, 0], node_id="5")

    # Enhancer chain
    model_ref = _ref(unet_id)
    if enhance:
        model_ref = _klein_enhance_model(nf, _ref(unet_id), [pos_id, 0])

    # Load input image
    img_id = nf.load_image(image_filename, node_id="10")

    if _det_type == "yolo":
        # ── YOLO path: use FaceDetailer (works for any bbox detector) ──
        yolo_model = preset.get("model", "bbox/face_yolov8m.pt")
        detector_id = nf._add("UltralyticsDetectorProvider", {
            "model_name": yolo_model,
        }, node_id="20")

        detail_id = nf._add("FaceDetailer", {
            "image": [img_id, 0],
            "model": model_ref,
            "clip": _ref(clip_id),
            "vae": [vae_id, 0],
            "positive": [pos_id, 0],
            "negative": [neg_id, 0],
            "bbox_detector": [detector_id, 0],
            "guide_size": _guide,
            "guide_size_for": True,
            "max_size": max_size,
            "seed": seed,
            "steps": _steps,
            "cfg": guidance,
            "sampler_name": "euler",
            "scheduler": "simple",
            "denoise": _denoise,
            "feather": 5,
            "noise_mask": True,
            "force_inpaint": True,
            "wildcard": "",
            "cycle": 1,
            "drop_size": 10,
            "bbox_threshold": 0.5,
            "bbox_dilation": 10,
            "bbox_crop_factor": 3.0,
            "sam_detection_hint": "center-1",
            "sam_dilation": 0,
            "sam_threshold": 0.93,
            "sam_bbox_expansion": 0,
            "sam_mask_hint_threshold": 0.7,
            "sam_mask_hint_use_negative": "False",
        }, node_id="30")
        nf.save_image([detail_id, 0], "klein_detail", node_id="40")

    else:
        # ── SAM3 path: text-prompted segmentation → Klein inpaint ──
        _sam3_text = sam3_prompt or preset.get("sam3_prompt", "subject")

        sam3_id = nf._add("SAM3Segment", {
            "prompt": _sam3_text,
            "output_mode": "Merged",
            "confidence_threshold": 0.5,
            "max_segments": 0,
            "segment_pick": 0,
            "mask_blur": 0,
            "mask_offset": 0,
            "device": "Auto",
            "invert_output": False,
            "unload_model": False,
            "background": "Alpha",
            "background_color": "#222222",
            "image": [img_id, 0],
        }, node_id="20")

        # Grow mask slightly for smooth blending
        grow_id = nf._add("GrowMaskWithBlur", {
            "expand": 8,
            "incremental_expandrate": 0,
            "tapered_corners": True,
            "flip_input": False,
            "blur_radius": 6,
            "lerp_alpha": 1,
            "decay_factor": 1,
            "fill_holes": False,
            "mask": [sam3_id, 1],
        }, node_id="21")

        # Encode image for Klein
        scaled_id = nf.image_scale_to_total_pixels([img_id, 0], megapixels=1.0,
                                                    node_id="22")
        enc_id = nf.vae_encode([scaled_id, 0], [vae_id, 0], node_id="23")

        # Set mask on latent
        masked_id = nf.set_latent_noise_mask([enc_id, 0], [grow_id, 0],
                                              node_id="24")

        # FluxGuidance for inpaint (not ReferenceLatent)
        guided_id = nf.flux_guidance([pos_id, 0], guidance, node_id="25")
        neg2_id = nf.conditioning_zero_out([guided_id, 0], node_id="26")

        # DifferentialDiffusion for smooth mask edges
        dd_id = nf.differential_diffusion(model_ref, node_id="27")

        # Sampler
        guider_id = nf.cfg_guider([dd_id, 0], [guided_id, 0], [neg2_id, 0],
                                  1.0, node_id="30")
        sampler_id = nf.ksampler_select("euler", node_id="31")
        sched_id = nf.basic_scheduler([dd_id, 0], _steps, _denoise,
                                       scheduler="simple", node_id="32")
        noise_id = nf.random_noise(seed, node_id="33")

        sample_id = nf.sampler_custom_advanced(
            [noise_id, 0], [guider_id, 0], [sampler_id, 0],
            [sched_id, 0], [masked_id, 0], node_id="35",
        )

        dec_id = nf.vae_decode([sample_id, 0], [vae_id, 0], node_id="36")
        nf.save_image([dec_id, 0], "klein_detail", node_id="40")

    return nf.build()


# ═══════════════════════════════════════════════════════════════════════════
#  Layer Blend — simple two-image blend
# ═══════════════════════════════════════════════════════════════════════════

def build_layer_blend(image_a_filename, image_b_filename, blend_factor=0.5,
                      blend_mode="normal"):
    """Blend two images with adjustable opacity and blend mode.

    Creates a composite by overlaying image B on image A with opacity and
    blend mode control. Equivalent to Photoshop layer blending.

    Pipeline:
      1. Load image A (base layer)
      2. Load image B (overlay layer)
      3. Blend with specified mode and opacity
      4. Save composite

    Args:
        image_a_filename (str): Base image
        image_b_filename (str): Overlay image (blended onto A)
        blend_factor (float): Opacity of B on A, 0.0-1.0 (default 0.5)
                             - 0.0: Only image A
                             - 0.5: 50% blend
                             - 1.0: Only image B
        blend_mode (str): Photoshop-style blend mode (default "normal")
                         - "normal": Simple opacity blend
                         - "add": Additive blend (brightens)
                         - "multiply": Multiplicative blend (darkens)
                         - "screen": Screen blend (inverse multiply)
                         - "overlay": Overlay blend (contrast)

    Returns:
        dict: Simple 4-node workflow

    Note:
      - Images must be same resolution
      - Fast operation, no AI involved
      - Useful for compositing, layer effects, A/B comparison
    """
    nf = NodeFactory()
    a_id = nf.load_image(image_a_filename, node_id="1")
    b_id = nf.load_image(image_b_filename, node_id="2")
    blend_id = nf.image_blend([a_id, 0], [b_id, 0], blend_factor, blend_mode,
                               node_id="3")
    nf.save_image([blend_id, 0], "spellcaster_blend_ratio", node_id="4")
    return nf.build()


# ═══════════════════════════════════════════════════════════════════════════
#  Upscale Blend — dual model upscale + blend
# ═══════════════════════════════════════════════════════════════════════════

def build_upscale_blend(image_filename, model_a_name, model_b_name,
                        blend_factor=0.6, scale_by=1.0):
    """Upscale using two models and blend the results.

    Upscales an image with two different models in parallel, then blends
    the results. Useful for combining strengths of different upscalers
    (e.g., RealESRGAN sharp + Upscayl smooth = balanced result).

    Pipeline:
      1. Load image
      2. Load upscaler model A and upscale image
      3. Load upscaler model B and upscale same image
      4. Blend the two upscaled results
      5. Save composite

    Args:
        image_filename (str): Input image to upscale
        model_a_name (str): First upscaler model (e.g., "4x-UltraSharp.pth")
        model_b_name (str): Second upscaler model (e.g., "RealESRGAN_x4plus.pth")
        blend_factor (float): Blend ratio A→B, 0.0-1.0 (default 0.6)
                             - 0.0: Only model A
                             - 0.6: 60% A + 40% B
                             - 1.0: Only model B
        scale_by (float): Upscaling multiplier (default 1.0, typically embedded in model)

    Returns:
        dict: 7-node workflow (load, 2x loader+upscale, blend, save)

    Use Cases:
      - Combine sharp upscaler with smooth upscaler for balanced quality
      - Compare two models' outputs with arbitrary weighting
      - Reduce artifacts from one model by blending with another
      - Ensemble multiple upscalers for best-of-both-worlds

    Model Pairing Examples:
      - "4x-UltraSharp.pth" (sharp) + "RealESRGAN_x4plus.pth" (balanced) at 0.5
      - "SwinIR_x4.pth" (detail) + "BSRGAN_x4.pth" (smooth) at 0.4
      - "Upscayl_x4.pth" + "NtganSharp_x4.pth" at 0.7

    Gotchas:
      - Models must have same upscaling factor (e.g., both 4x, not 2x+4x)
      - Blending doesn't merge techniques, just interpolates results
      - Slower than single upscaler (both models run sequentially)
      - Memory usage is sum of both models + intermediate results
    """
    nf = NodeFactory()

    img_id = nf.load_image(image_filename, node_id="1")

    # Model A upscale
    up_a_id = nf.upscale_model_loader(model_a_name, node_id="10")
    up_a_img_id = nf.image_upscale_with_model_by_factor(
        [up_a_id, 0], [img_id, 0], scale_by, node_id="11")

    # Model B upscale
    up_b_id = nf.upscale_model_loader(model_b_name, node_id="20")
    up_b_img_id = nf.image_upscale_with_model_by_factor(
        [up_b_id, 0], [img_id, 0], scale_by, node_id="21")

    # Blend
    blend_id = nf.image_blend([up_a_img_id, 0], [up_b_img_id, 0],
                               blend_factor, "normal", node_id="30")
    nf.save_image([blend_id, 0], "spellcaster_upblend", node_id="40")

    return nf.build()


# ═══════════════════════════════════════════════════════════════════════════
#  Frame Assembly — dynamic LoadImage chain → ImageBatch → VHS_VideoCombine
# ═══════════════════════════════════════════════════════════════════════════

def build_frame_assembly(frame_filenames, fps=16.0, filename_prefix="gimp_assembled",
                         crf=19, pingpong=False):
    """Assemble a list of uploaded frame images into a single MP4 video.

    Loads each frame via LoadImage, chains them pairwise through ImageBatch
    nodes to build a single image batch, then encodes via VHS_VideoCombine.

    Args:
        frame_filenames (list[str]): Ordered list of filenames already in
            ComfyUI's input folder (e.g. from _upload_image).
        fps (float): Output video frame rate (default 16.0).
        filename_prefix (str): Prefix for the output MP4 file.
        crf (int): H.264 quality (lower = better, default 19).
        pingpong (bool): Whether to bounce the video back and forth.

    Returns:
        dict: ComfyUI workflow that produces an MP4 in the output folder.
    """
    if not frame_filenames:
        raise ValueError("build_frame_assembly: need at least 1 frame")

    nf = NodeFactory()

    if len(frame_filenames) == 1:
        # Single frame — just load and encode (produces a 1-frame video)
        img_id = nf.load_image(frame_filenames[0], node_id="f_0")
        batch_ref = [img_id, 0]
    else:
        # Load all frames
        img_ids = []
        for i, fname in enumerate(frame_filenames):
            img_ids.append(nf.load_image(fname, node_id=f"f_{i}"))

        # Chain through ImageBatch nodes pairwise:
        #   batch_0 = ImageBatch(frame_0, frame_1)
        #   batch_1 = ImageBatch(batch_0, frame_2)
        #   batch_2 = ImageBatch(batch_1, frame_3) ...
        batch_ref = [img_ids[0], 0]
        for i in range(1, len(img_ids)):
            batch_id = nf.image_batch(batch_ref, [img_ids[i], 0],
                                      node_id=f"b_{i}")
            batch_ref = [batch_id, 0]

    # Encode to MP4
    nf.update({
        "vhs_out": {"class_type": "VHS_VideoCombine",
                    "inputs": {"images": batch_ref,
                               "frame_rate": float(fps),
                               "loop_count": 0,
                               "filename_prefix": filename_prefix,
                               "format": "video/h264-mp4",
                               "pingpong": pingpong,
                               "save_output": True,
                               "pix_fmt": "yuv420p",
                               "crf": crf}},
    })

    return nf.build()


# ═══════════════════════════════════════════════════════════════════════════
#  LTX 2.3 VIDEO GENERATION
# ═══════════════════════════════════════════════════════════════════════════
# LTX Video 2.3 pipeline:
#   UnetLoaderGGUF → LTXVChunkFeedForward → LTXVApplySTG → STGGuider
#   Text: LTXAVTextEncoderLoader (Gemma 3 + embeddings connectors)
#   VAE: LTX23_video_vae_bf16.safetensors (NOT LTX2.2 VAEs!)
#   Sampler: LTXVBaseSampler → LTXVSpatioTemporalTiledVAEDecode
#   Two-stage: half-res → LatentUpscaleModelLoader + LTXVLatentUpsampler
#              → SamplerCustomAdvanced re-denoise at full res
#   Distilled: LoRA + cfg=1.0, stg=0.0, 8 steps — 4x faster
# ═══════════════════════════════════════════════════════════════════════════

def build_ltx_video(preset, prompt_text, seed,
                     width=768, height=512, num_frames=25,
                     steps=None, cfg=None, stg=None, rescale=None,
                     two_stage=False, distilled=False,
                     loras=None, interpolate=False, rtx_scale=0,
                     fps=25, pingpong=False,
                     image_filename=None, i2v_strength=0.9):
    """LTX Video 2.3 generation — text-to-video or image-to-video.

    Supports three modes:
      1. Single-stage: generate at target resolution (default)
      2. Two-stage: generate at half-res → latent upscale 2x → re-denoise
      3. Distilled: LoRA-accelerated, 8 steps, 4x faster

    Args:
        preset (dict): LTX preset containing:
          - unet: GGUF model path (e.g. "LTX\\ltx-2.3-22b-dev-Q4_K_M.gguf")
          - text_encoder: Gemma model name
          - embeddings_connector: LTX embeddings connector path
          - vae: LTX2.3 VAE name
          - steps: Default sampling steps (30 normal, 8 distilled)
          - cfg: Default CFG (4.0 normal, 1.0 distilled)
          - stg: Default STG strength (1.0 normal, 0.0 distilled)
          - rescale: Default STG rescale (0.7 normal, 0.0 distilled)
          - distilled_lora: Optional distilled LoRA path
          - latent_upscaler: Latent upscale model for two-stage
        prompt_text (str): Generation prompt
        seed (int): Random seed
        width (int): Target output width (default 768)
        height (int): Target output height (default 512)
        num_frames (int): Number of frames (default 25 = 1 sec at 25fps)
        steps (int): Override sampling steps
        cfg (float): Override CFG scale
        stg (float): Override STG strength
        rescale (float): Override STG rescale
        two_stage (bool): Use two-stage latent upscale pipeline
        distilled (bool): Use distilled LoRA fast mode
        loras (list): Additional [(lora_name, strength), ...] LoRAs
        interpolate (bool): RIFE frame interpolation (default False)
        rtx_scale (int): RTX Video Super Resolution scale (0=off)
        fps (int): Output frame rate (default 25)
        pingpong (bool): Bounce video back and forth
        image_filename (str): Optional start image for I2V mode

    Returns:
        dict: ComfyUI workflow
    """
    nf = NodeFactory()

    # Resolve parameters from preset
    steps = steps or preset.get("steps", 30)
    cfg = cfg if cfg is not None else preset.get("cfg", 4.0)
    stg = stg if stg is not None else preset.get("stg", 1.0)
    rescale = rescale if rescale is not None else preset.get("rescale", 0.7)

    unet_name = preset["unet"]
    text_encoder = preset["text_encoder"]
    embeddings_connector = preset["embeddings_connector"]
    vae_name = preset["vae"]

    # Distilled mode overrides
    if distilled:
        distilled_lora = preset.get("distilled_lora",
                                      "ltxv\\ltx-2.3-22b-distilled-lora-384.safetensors")
        steps = 8
        cfg = 1.0
        stg = 0.0
        rescale = 0.0

    # For two-stage, generate at half resolution
    gen_width = width // 2 if two_stage else width
    gen_height = height // 2 if two_stage else height

    # ── Model loading ─────────────────────────────────────────────
    unet_id = nf.unet_loader_gguf(unet_name, node_id="1")

    # Distilled LoRA (applied before chunking)
    model_ref = _ref(unet_id)
    if distilled:
        lora_id = nf.lora_loader_model_only(model_ref, distilled_lora, 1.0,
                                             node_id="1b")
        model_ref = [lora_id, 0]

    # Additional user LoRAs
    if loras:
        for i, (ln, ls) in enumerate(loras):
            nid = f"1l{i}"
            lid = nf.lora_loader_model_only(model_ref, ln, ls, node_id=nid)
            model_ref = [lid, 0]

    # VRAM optimization + STG
    chunk_id = nf.ltxv_chunk_feed_forward(model_ref, chunks=4, node_id="2")
    stg_model_id = nf.ltxv_apply_stg([chunk_id, 0], "14, 19", node_id="3")

    # ── Text encoding ─────────────────────────────────────────────
    enc_id = nf.ltxav_text_encoder_loader(text_encoder, embeddings_connector,
                                           node_id="4")
    pos_id = nf.clip_encode([enc_id, 0], prompt_text, node_id="10")
    neg_id = nf.clip_encode([enc_id, 0], "", node_id="11")

    # ── VAE ───────────────────────────────────────────────────────
    vae_id = nf.vae_loader(vae_name, node_id="5")

    # ── Conditioning ──────────────────────────────────────────────
    cond_id = nf.ltxv_conditioning([pos_id, 0], [neg_id, 0],
                                    frame_rate=float(fps), node_id="12")

    # ── Sampling ──────────────────────────────────────────────────
    sched_id = nf.ltxv_scheduler(steps=steps, node_id="15")
    guider_id = nf.stg_guider([stg_model_id, 0], [cond_id, 0], [cond_id, 1],
                               cfg=cfg, stg=stg, rescale=rescale, node_id="16")
    sampler_id = nf.ksampler_select("euler", node_id="17")
    noise_id = nf.random_noise(seed, node_id="18")

    # ── I2V conditioning (optional) ─────────────────────────────────────────────
    i2v_kwargs = {}
    if image_filename:
        i2v_img_id = nf.load_image(image_filename, node_id="19")
        i2v_kwargs = {
            "optional_cond_images": [i2v_img_id, 0],
            "optional_cond_indices": "0",
            "strength": i2v_strength,
        }

    base_id = nf.ltxv_base_sampler(
        [stg_model_id, 0], [vae_id, 0], [guider_id, 0],
        [sampler_id, 0], [sched_id, 0], [noise_id, 0],
        gen_width, gen_height, num_frames, **i2v_kwargs, node_id="20")

    decode_latent_ref = [base_id, 0]

    # ── Two-stage upscale (optional) ──────────────────────────────
    if two_stage:
        upscaler_model = preset.get("latent_upscaler",
                                      "ltx-2-spatial-upscaler-x2-1.0.safetensors")
        ups_loader_id = nf.latent_upscale_model_loader(upscaler_model, node_id="25")
        ups_id = nf.ltxv_latent_upsampler([base_id, 0], [ups_loader_id, 0],
                                           [vae_id, 0], node_id="26")

        # Stage 2 schedule (10 steps re-denoise)
        sched2_id = nf.ltxv_scheduler(steps=10, latent_ref=[ups_id, 0],
                                       node_id="30")
        noise2_id = nf.random_noise(seed, node_id="31")
        stage2_id = nf.sampler_custom_advanced(
            [noise2_id, 0], [guider_id, 0], [sampler_id, 0],
            [sched2_id, 0], [ups_id, 0], node_id="32")
        decode_latent_ref = [stage2_id, 0]

    # ── VAE decode ────────────────────────────────────────────────
    decode_id = nf.ltxv_spatiotemporal_tiled_vae_decode(
        [vae_id, 0], decode_latent_ref, node_id="40")

    frames_ref = [decode_id, 0]

    # ── Post-processing ───────────────────────────────────────────
    if rtx_scale and rtx_scale > 0:
        rtx_id = nf.video_upscale(frames_ref, scale_factor=rtx_scale,
                                   node_id="45")
        frames_ref = [rtx_id, 0]

    if interpolate:
        rife_id = nf.rife_vfi(frames_ref, multiplier=2, node_id="46")
        frames_ref = [rife_id, 0]

    # ── Output ────────────────────────────────────────────────────
    i2v_tag = "-i2v" if image_filename else ""
    mode_tag = "distilled" if distilled else ("2stage" if two_stage else "single")
    prefix = f"LTX23-{mode_tag}{i2v_tag}"
    nf.vhs_video_combine(frames_ref, frame_rate=fps, filename_prefix=prefix,
                          pingpong=pingpong, node_id="50")

    return nf.build()