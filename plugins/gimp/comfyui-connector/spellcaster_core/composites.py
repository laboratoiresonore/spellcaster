"""Composite workflow helpers — reusable multi-node building blocks.

Composites combine multiple NodeFactory calls into higher-level patterns.
Instead of manually wiring 5-10 nodes to load a model, apply LoRAs, and
encode prompts, a single call to load_model_stack() + inject_lora_chain()
+ encode_prompts() handles it all, respecting the architecture's
loading strategy and sampler type.

COMPOSITE PATTERNS (each is a function here):
  load_model_stack()    — Load model + CLIP + VAE per architecture
                          Handles checkpoint vs separate loader logic
  inject_lora_chain()   — Chain multiple LoRAs (architecture-agnostic)
  encode_prompts()      — Encode positive/negative prompts
                          Respects arch.supports_negative (Flux = False)
  sample_standard()     — Standard KSampler path (sd15/sdxl/flux1dev/zit)
  sample_klein()        — Flux2 Klein path (SamplerCustomAdvanced + CFGGuider)
  sample_klein_img2img()— Klein img2img with ReferenceLatent wrapping
  inject_controlnet()   — Single ControlNet with optional preprocessing
  inject_controlnet_pair()  — Chain two ControlNets
  ensure_mod16()        — Scale image to mod-16 for Flux ControlNets

WHY COMPOSITES:
  1. DRY: Don't repeat the same 10-node pattern in 20 workflows
  2. Consistency: All txt2img workflows use the same model-loading pattern
  3. Maintainability: If architecture loading changes, fix it once here
  4. Clarity: High-level composition reads like a recipe

PATTERN:
  nf = NodeFactory()
  model_ref, clip_ref, vae_ref = load_model_stack(nf, preset)
  model_ref, clip_ref, triggers = inject_lora_chain(nf, loras, model_ref, clip_ref)
  pos_id, neg_id = encode_prompts(nf, arch_key, clip_ref, pos_text, neg_text)
  sample_id = sample_standard(nf, model_ref, pos_id, neg_id, latent_ref, ...)
  workflow = nf.build()

Each function takes nf as first argument and returns references for wiring.
"""

from .architectures import ARCHITECTURES, get_arch


# ═══════════════════════════════════════════════════════════════════════════
#  MODEL LOADING COMPOSITE
# ═══════════════════════════════════════════════════════════════════════════
# The architecture determines how models are loaded:
#   - Checkpoint-based: one CheckpointLoaderSimple outputs [MODEL, CLIP, VAE]
#   - Separate loaders: UNET + CLIP + VAE loaded separately and composed
#
# This function abstracts that logic so callers never think about loader
# strategy; they just pass a preset and get back (model_ref, clip_ref, vae_ref).

def load_model_stack(nf, preset, node_id="1"):
    """Load model + CLIP + VAE stack, respecting architecture loader strategy.

    The architecture detection (ARCHITECTURES dict) determines whether to use:
      - CheckpointLoaderSimple for bundled checkpoint-based models
      - UNETLoader + CLIPLoader + VAELoader for Flux/Klein separate loaders

    This single function handles both patterns transparently.

    Args:
        nf: NodeFactory instance to add nodes to
        preset: Dict containing at least "arch" and "ckpt" keys, plus optional
                "clip", "sampler", "cfg", "steps", "denoise", etc.
                Example: {"arch": "sdxl", "ckpt": "sd_xl_base.safetensors"}
        node_id: Starting node ID (default "1"). For Flux with separate loaders,
                 will create nodes "1", "1b", "1c" to avoid collisions.

    Returns:
        Tuple (model_ref, clip_ref, vae_ref) where each is a [node_id, output_slot]:
          - model_ref: Reference to loaded diffusion model (UNET)
          - clip_ref: Reference to loaded text encoder (CLIP)
          - vae_ref: Reference to loaded VAE (encoder/decoder)

        These refs are ready to wire into downstream nodes like KSampler.

    Example (SDXL checkpoint):
        model_ref, clip_ref, vae_ref = load_model_stack(
            nf, {"arch": "sdxl", "ckpt": "xl_base.safetensors"}, node_id="1"
        )
        # Returns: (["1", 0], ["1", 1], ["1", 2])

    Example (Flux1 separate loaders):
        model_ref, clip_ref, vae_ref = load_model_stack(
            nf, {"arch": "flux1dev", "ckpt": "flux1-dev-q6.gguf"}, node_id="1"
        )
        # Returns: (["1", 0], ["1b", 0], ["1c", 0])
    """
    arch_key = preset.get("arch", "sdxl")
    arch = get_arch(arch_key)

    # GOTCHA: Some architectures (e.g. Chroma v2) can ship as either separate
    # UNET+CLIP+VAE files OR as a single merged checkpoint. The architecture
    # definition defaults to unet_clip_vae, but if the user selected a merged
    # checkpoint file, we must override to use CheckpointLoaderSimple instead.
    # The preset's "model_type" field (set by the model detection layer) tells us.
    actual_loader = arch.loader
    model_type = preset.get("model_type")
    if model_type == "checkpoint" and actual_loader == "unet_clip_vae":
        actual_loader = "checkpoint"

    if actual_loader == "unet_clip_vae":
        # Flux / Klein / Chroma — three separate loader nodes required.
        # Each loader outputs exactly one thing (MODEL, CLIP, or VAE),
        # unlike CheckpointLoaderSimple which outputs all three from slot 0/1/2.
        unet_id = nf.unet_loader(preset["ckpt"], "default", node_id=node_id)

        if arch.clip_mode == "single_chroma":
            # Chroma v1/v2: single CLIPLoader with type="chroma"
            extra = arch.extra
            clip_name = extra.get("clip_name", "t5xxl_fp8_e4m3fn.safetensors")
            clip_id = nf.clip_loader(clip_name, clip_type="chroma",
                                     device="default",
                                     node_id=f"{node_id}b")
        elif arch.clip_mode == "single_flux2":
            # Klein CLIP selection: the CLIP model MUST match the UNET size.
            # Using qwen_3_8b with a 4B UNET silently produces garbage output;
            # using qwen_3_4b with a 9B UNET throws an explicit shape mismatch error.
            # We prefer defaulting to 9B because the failure mode is louder (better UX).
            extra = arch.extra
            ckpt_lower = preset["ckpt"].lower()
            is_9b = ("9b" in ckpt_lower or
                     ("dev" in ckpt_lower and "4b" not in ckpt_lower))
            is_4b = ("4b" in ckpt_lower or "schnell" in ckpt_lower
                     or "lite" in ckpt_lower or "kaleidoscope" in ckpt_lower)
            if is_9b:
                clip_name = extra.get("clip_name_9b", "qwen_3_8b.safetensors")
            else:
                clip_name = "qwen_3_4b.safetensors" if is_4b else "qwen_3_8b.safetensors"
                clip_name = extra.get("clip_name_4b", clip_name)

            print(f"  [Klein CLIP] ckpt={preset['ckpt']} is_9b={is_9b} is_4b={is_4b} -> clip={clip_name}")
            clip_id = nf.clip_loader(clip_name, clip_type="flux2",
                                     device="default",
                                     node_id=f"{node_id}b")
        elif arch.clip_mode == "dual":
            # Flux Dev / Kontext: DualCLIPLoader
            extra = arch.extra
            clip_id = nf.dual_clip_loader(
                extra.get("clip_name1", "clip_l.safetensors"),
                extra.get("clip_name2", "t5xxl_fp8_e4m3fn.safetensors"),
                clip_type=extra.get("clip_type", "flux"),
                node_id=f"{node_id}b",
            )
        else:
            clip_id = nf.clip_loader(preset.get("clip", ""),
                                     node_id=f"{node_id}b")

        vae_name = arch.extra.get("vae_name", "ae.safetensors")
        vae_id = nf.vae_loader(vae_name, node_id=f"{node_id}c")

        # Each separate loader has exactly one output at slot 0
        return [unet_id, 0], [clip_id, 0], [vae_id, 0]

    else:
        # Checkpoint-based (sd15, sdxl, zit, illustrious, or forced-checkpoint).
        # CheckpointLoaderSimple outputs: slot 0=MODEL, slot 1=CLIP, slot 2=VAE.
        # All three refs point to the same node ID, differing only in slot index.
        ckpt_id = nf.checkpoint_loader(preset["ckpt"], node_id=node_id)
        return [ckpt_id, 0], [ckpt_id, 1], [ckpt_id, 2]


# ═══════════════════════════════════════════════════════════════════════════
#  LoRA CHAIN COMPOSITE
# ═══════════════════════════════════════════════════════════════════════════
# LoRAs (Low-Rank Adapters) are lightweight model fine-tunings that can be
# stacked in chains. This composite handles sequential application, updating
# the model_ref and clip_ref after each LoRA to feed into the next one.

def inject_lora_chain(nf, loras, model_ref, clip_ref, base_id=100,
                      use_triggers=False):
    """Apply a sequence of LoRAs to model and CLIP (or skip if empty list).

    LoRAs are applied in order, each one receiving the previous LoRA's output.
    For example, [detail_lora, style_lora] means:
      base_model → [detail_lora] → [style_lora] → final model

    Args:
        nf: NodeFactory instance
        loras: List of LoRA dicts, each with keys:
               - name: LoRA filename (str)
               - strength_model: How much to apply to model (float, 0-1)
               - strength_clip: How much to apply to CLIP (float, 0-1)
               Example: [
                   {"name": "add_detail.safetensors", "strength_model": 0.5,
                    "strength_clip": 0.5},
                   {"name": "style.safetensors", "strength_model": 0.3,
                    "strength_clip": 0.2}
               ]
        model_ref: Initial model reference (from checkpoint or UNET loader)
        clip_ref: Initial CLIP reference
        base_id: Starting node ID for LoRA nodes (default 100).
                 High IDs prevent collision with core workflow (nodes 1-50).
        use_triggers: If True, use LoraLoaderAdvanced (from
                      ComfyUI-Lora-Auto-Trigger-Words) which extracts trigger
                      words from LoRA metadata/CivitAI alongside loading.
                      trigger_refs will contain [node_id, 2] refs for each LoRA.
                      Falls back to standard LoraLoader if node unavailable.

    Returns:
        Tuple (updated_model_ref, updated_clip_ref, trigger_refs).
        trigger_refs is a list of [node_id, 2] references to STRING outputs
        containing trigger words. Empty list if use_triggers=False.

        If loras is empty, returns (model_ref, clip_ref, []) unchanged.

    Example:
        loras = [
            {"name": "SD15/add_detail.safetensors", "strength_model": 0.5,
             "strength_clip": 0.5}
        ]
        model_ref, clip_ref, triggers = inject_lora_chain(
            nf, loras, [ckpt_id, 0], [ckpt_id, 1], base_id=100,
            use_triggers=True,
        )
        # triggers = [["100", 2]]  — STRING output with trigger words
    """
    if not loras:
        return model_ref, clip_ref, []

    prev_model = model_ref
    prev_clip = clip_ref
    trigger_refs = []

    for i, lora in enumerate(loras):
        nid_str = str(base_id + i)
        if use_triggers:
            nid = nf.lora_loader_triggers(
                prev_model, prev_clip,
                lora["name"],
                lora.get("strength_model", 1.0),
                lora.get("strength_clip", 1.0),
                node_id=nid_str,
            )
            # LoraLoaderAdvanced outputs: slot 0=MODEL, slot 1=CLIP, slot 2=STRING (triggers)
            trigger_refs.append([nid, 2])
        else:
            nid = nf.lora_loader(
                prev_model, prev_clip,
                lora["name"],
                lora.get("strength_model", 1.0),
                lora.get("strength_clip", 1.0),
                node_id=nid_str,
            )
        # Chain: each LoRA's output feeds into the next LoRA's input.
        # LoraLoader outputs: slot 0=MODEL (patched), slot 1=CLIP (patched).
        prev_model = [nid, 0]
        prev_clip = [nid, 1]

    return prev_model, prev_clip, trigger_refs


def collect_lora_trigger_tags(nf, lora_names, base_id=150):
    """Extract trigger words from LoRAs WITHOUT loading them (metadata only).

    Uses the LoraTagsOnly node from ComfyUI-Lora-Auto-Trigger-Words.
    Useful when LoRAs are loaded via LoraLoaderModelOnly (e.g. video) and
    you still need their trigger words for the prompt.

    Args:
        nf: NodeFactory instance
        lora_names: List of LoRA filenames
        base_id: Starting node ID (default 150)

    Returns:
        List of [node_id, 0] references to STRING outputs containing triggers.
    """
    refs = []
    for i, name in enumerate(lora_names):
        nid = nf.lora_tags_only(name, node_id=str(base_id + i))
        refs.append([nid, 0])
    return refs


# ═══════════════════════════════════════════════════════════════════════════
#  PROMPT ENCODING COMPOSITE
# ═══════════════════════════════════════════════════════════════════════════
# Converts text prompts into conditioning tensors. The architecture determines
# how negative conditioning is handled: most support explicit negative prompts,
# but Flux/Klein use ConditioningZeroOut (empty/null conditioning) instead.

def encode_prompts(nf, arch_key, clip_ref, positive, negative,
                   pos_id=None, neg_id=None):
    """Encode positive and negative prompts per architecture.

    Different architectures handle negatives differently:
      - SD1.5, SDXL, Illustrious, ZIT: Normal negative prompts (CLIPTextEncode)
      - Flux1Dev, Flux2Klein: No negative prompts; use ConditioningZeroOut
        to create null/empty conditioning for guidance scale only.

    Args:
        nf: NodeFactory instance
        arch_key: Architecture identifier (e.g. "sdxl", "flux2klein")
                 Used to look up supports_negative in ARCHITECTURES
        clip_ref: Reference to CLIP encoder, e.g. [clip_id, 0]
        positive: Positive prompt text (str)
        negative: Negative prompt text (str), ignored if arch doesn't support it
        pos_id: Optional explicit node ID for positive encoding
        neg_id: Optional explicit node ID for negative/null encoding

    Returns:
        Tuple (pos_node_id, neg_node_id) where each is a node ID string.

        Both can be used directly in downstream nodes:
          - Use [pos_node_id, 0] as positive_ref in KSampler
          - Use [neg_node_id, 0] as negative_ref in KSampler
            (even if arch doesn't support negatives; the ConditioningZeroOut
             node still produces valid conditioning)

    Example (SDXL with negatives):
        pos_id, neg_id = encode_prompts(
            nf, "sdxl", [clip_id, 0],
            positive="a beautiful cat",
            negative="blurry, low quality"
        )
        # pos_id and neg_id are both CLIPTextEncode nodes

    Example (Flux2Klein without negatives):
        pos_id, neg_id = encode_prompts(
            nf, "flux2klein", [clip_id, 0],
            positive="a beautiful cat",
            negative="ignored"  # Not used; arch.supports_negative=False
        )
        # pos_id is CLIPTextEncode, neg_id is ConditioningZeroOut
    """
    arch = get_arch(arch_key)

    pos_nid = nf.clip_encode(clip_ref, positive, node_id=pos_id)

    if arch.supports_negative and negative:
        # SD1.5/SDXL/Illustrious: encode the negative prompt normally
        neg_nid = nf.clip_encode(clip_ref, negative, node_id=neg_id)
    else:
        # Flux/Klein/Chroma: these architectures ignore negative prompts entirely.
        # ConditioningZeroOut creates a zero-valued conditioning tensor from the
        # positive encoding's shape. This satisfies KSampler's required neg input
        # without influencing the output. The input is the positive conditioning
        # (not the clip_ref) because ZeroOut needs a conditioning tensor to zero.
        neg_nid = nf.conditioning_zero_out([pos_nid, 0], node_id=neg_id)

    return pos_nid, neg_nid


# ═══════════════════════════════════════════════════════════════════════════
#  SAMPLING COMPOSITES
# ═══════════════════════════════════════════════════════════════════════════
# These composites abstract the different sampling pipelines:
#   - sample_standard(): KSampler for most architectures
#   - sample_klein(): SamplerCustomAdvanced + CFGGuider for Flux2Klein
#
# Each builds the full sampling pipeline and returns the sampler node ID.

def sample_standard(nf, model_ref, pos_ref, neg_ref, latent_ref,
                    seed, preset, denoise_override=None, node_id=None):
    """Standard KSampler path for most architectures.

    Applies to: SD1.5, SDXL, Illustrious, ZIT, Flux1Dev, Flux Kontext.
    Each of these uses the same KSampler node type; differences are only
    in parameters (cfg, steps, sampler_name, scheduler, denoise).

    Args:
        nf: NodeFactory instance
        model_ref: Diffusion model reference, e.g. [ckpt_id, 0]
        pos_ref: Positive conditioning, e.g. [pos_encode_id, 0]
        neg_ref: Negative conditioning, e.g. [neg_encode_id, 0]
        latent_ref: Starting latent (EmptyLatentImage or VAEEncode)
        seed: Random seed (int)
        preset: Dict with sampling parameters:
                "steps", "cfg", "sampler", "scheduler", "denoise"
        denoise_override: Optional override for denoise strength
        node_id: Optional explicit node ID

    Returns:
        Node ID (string) of the KSampler node.

    Example:
        sample_id = sample_standard(
            nf, [ckpt_id, 0], [pos_id, 0], [neg_id, 0], [empty_id, 0],
            seed=42,
            preset={
                "steps": 25, "cfg": 7.0,
                "sampler": "dpmpp_2m", "scheduler": "karras",
                "denoise": 1.0
            }
        )
    """
    # Refs can be either a bare node_id string (e.g. "5") or an already-formed
    # [node_id, slot] list. Normalize to [node_id, 0] when a string is passed.
    return nf.ksampler(
        model_ref,
        [pos_ref, 0] if isinstance(pos_ref, str) else pos_ref,
        [neg_ref, 0] if isinstance(neg_ref, str) else neg_ref,
        [latent_ref, 0] if isinstance(latent_ref, str) else latent_ref,
        seed,
        preset["steps"],
        preset["cfg"],
        preset.get("sampler", "euler"),
        preset.get("scheduler", "normal"),
        denoise_override if denoise_override is not None else preset.get("denoise", 1.0),
        node_id=node_id,
    )


def sample_klein(nf, model_ref, pos_ref, neg_ref, latent_ref, seed,
                 steps, guidance=1.0, width_ref=None, height_ref=None,
                 node_id=None):
    """Flux2Klein sampling pipeline (SamplerCustomAdvanced + CFGGuider).

    Klein uses a different sampling architecture than standard KSampler:
      1. CFGGuider — wraps model + conditioning for guidance
      2. KSamplerSelect — selects the sampler algorithm (euler)
      3. Flux2Scheduler — generates noise schedule for steps
      4. RandomNoise — seed-based noise initialization
      5. EmptyFlux2LatentImage — blank latent (can be overridden for img2img)
      6. SamplerCustomAdvanced — orchestrates the full sampling loop

    This composite builds all 6 nodes and wires them together.

    Args:
        nf: NodeFactory instance
        model_ref: Flux2 UNET reference, e.g. [unet_id, 0]
        pos_ref: Positive conditioning, e.g. [pos_encode_id, 0]
        neg_ref: Negative conditioning (usually ConditioningZeroOut for Flux)
        latent_ref: Starting latent (ignored; new latent is created)
        seed: Random seed
        steps: Number of sampling steps (typically 4-8 for Klein)
        guidance: CFG scale / guidance strength (typically 1.0 for Klein)
        width_ref: Width reference (from preset or image), e.g. 1024 or [size_id, 0]
        height_ref: Height reference (from preset or image), e.g. 1024 or [size_id, 1]
        node_id: Optional explicit node ID for the SamplerCustomAdvanced

    Returns:
        Node ID (string) of the SamplerCustomAdvanced node.

    Example:
        sample_id = sample_klein(
            nf, [unet_id, 0], [pos_id, 0], [zero_id, 0], None,
            seed=42, steps=4, guidance=1.0,
            width_ref=1024, height_ref=1024
        )
    """
    guider_id = nf.cfg_guider(
        model_ref,
        [pos_ref, 0] if isinstance(pos_ref, str) else pos_ref,
        [neg_ref, 0] if isinstance(neg_ref, str) else neg_ref,
        guidance,
    )
    sampler_id = nf.ksampler_select("euler")
    sched_id = nf.flux2_scheduler(steps, width_ref, height_ref)
    noise_id = nf.random_noise(seed)
    empty_id = nf.empty_flux2_latent_image(width_ref, height_ref, batch_size=1)

    return nf.sampler_custom_advanced(
        [noise_id, 0], [guider_id, 0], [sampler_id, 0],
        [sched_id, 0], [empty_id, 0],
        node_id=node_id,
    )


def sample_klein_img2img(nf, model_ref, pos_ref, neg_ref, latent_ref, seed,
                         steps, guidance=1.0, width_ref=None, height_ref=None,
                         node_id=None):
    """Klein img2img with ReferenceLatent.

    Same as sample_klein but wraps pos/neg conditioning with ReferenceLatent
    referencing the encoded input image.

    Returns the SamplerCustomAdvanced node ID.
    """
    # Klein img2img: wrap conditioning with the encoded input image latent.
    # ReferenceLatent tells the CFGGuider to condition on the source image,
    # not just the text prompt. This is how Klein achieves img2img without
    # the standard noise-then-denoise approach.
    ref_pos_id = nf.reference_latent(
        [pos_ref, 0] if isinstance(pos_ref, str) else pos_ref,
        latent_ref,
    )
    ref_neg_id = nf.reference_latent(
        [neg_ref, 0] if isinstance(neg_ref, str) else neg_ref,
        latent_ref,
    )

    guider_id = nf.cfg_guider(
        model_ref,
        [ref_pos_id, 0], [ref_neg_id, 0],
        guidance,
    )
    sampler_id = nf.ksampler_select("euler")
    sched_id = nf.flux2_scheduler(steps, width_ref, height_ref)
    noise_id = nf.random_noise(seed)
    empty_id = nf.empty_flux2_latent_image(width_ref, height_ref, batch_size=1)

    return nf.sampler_custom_advanced(
        [noise_id, 0], [guider_id, 0], [sampler_id, 0],
        [sched_id, 0], [empty_id, 0],
        node_id=node_id,
    )


# ═══════════════════════════════════════════════════════════════════════════
#  CONTROLNET INJECTION COMPOSITES
# ═══════════════════════════════════════════════════════════════════════════
# ControlNets inject spatial guidance into diffusion. inject_controlnet() handles
# one ControlNet; inject_controlnet_pair() chains two. The key steps:
#   1. Preprocess input image if needed (edge detection, depth estimation, etc)
#   2. Load the ControlNet model
#   3. Apply via ControlNetApplyAdvanced (returns updated conditioning)

def inject_controlnet(nf, controlnet_config, guide_modes, arch_key,
                      image_ref, pos_ref, neg_ref,
                      cn_base_id=20, debug_images=False):
    """Inject a single ControlNet into the workflow (with optional preprocessing).

    ControlNets add spatial constraints to the diffusion process. For example,
    a Canny edge detector might preprocess the input image to extract edges,
    then feed the edge map + the canny ControlNet model to guide generation.

    Args:
        nf: NodeFactory instance
        controlnet_config: Dict with keys:
                          "mode": ControlNet identifier (e.g. "Canny Edge — SDXL")
                          "strength": ControlNet influence (0-1, default 1.0)
                          "start_percent": When to start applying (0-1, default 0.0)
                          "end_percent": When to stop applying (0-1, default 1.0)
        guide_modes: Dict mapping ControlNet mode names to config dicts.
                    Each config has: {cn_models: {arch: name}, preprocessor: ...}
        arch_key: Architecture identifier ("sdxl", "flux1dev", etc) for CN selection
        image_ref: Reference to input image, e.g. [load_image_id, 0]
        pos_ref, neg_ref: Current conditioning references (updated if CN applied)
        cn_base_id: Starting node ID for CN nodes (default 20)
        debug_images: Save preprocessed images for debugging

    Returns:
        Tuple (updated_pos_ref, updated_neg_ref).

        If controlnet_config is None or mode is "Off", returns unchanged refs.
        Otherwise, returns conditioning updated by ControlNetApplyAdvanced.

    Example:
        cn_config = {"mode": "Canny Edge — SDXL", "strength": 0.7,
                     "start_percent": 0.0, "end_percent": 1.0}
        pos, neg = inject_controlnet(
            nf, cn_config, CONTROLNET_GUIDE_MODES, "sdxl",
            [image_id, 0], [pos_id, 0], [neg_id, 0],
            cn_base_id=20
        )
        # pos, neg now have ControlNet applied (if mode wasn't "Off")
    """
    if not controlnet_config or controlnet_config.get("mode", "Off") == "Off":
        return pos_ref, neg_ref

    guide = guide_modes.get(controlnet_config["mode"])
    if not guide:
        return pos_ref, neg_ref

    # Look up the ControlNet model for this architecture, falling back to SDXL
    # variant (most CN models have SDXL versions; SD1.5/Flux may not).
    cn_model = guide["cn_models"].get(arch_key, guide["cn_models"].get("sdxl"))
    if not cn_model:
        return pos_ref, neg_ref  # no CN model available for this architecture

    # Preprocessor transforms the input image into a guidance signal
    # (e.g. Canny -> edge map, Depth -> depth map). Some ControlNets
    # don't need preprocessing (e.g. IP-Adapter, Tile at full resolution).
    preprocessor = guide.get("preprocessor")
    cn_image_ref = image_ref

    if preprocessor:
        pre_id = nf.preprocessor(preprocessor, image_ref,
                                 node_id=str(cn_base_id))
        cn_image_ref = [pre_id, 0]

    cn_loader_id = nf.controlnet_loader(cn_model,
                                        node_id=str(cn_base_id + 1))

    # ControlNetApplyAdvanced takes BOTH pos and neg conditioning and returns
    # updated versions of both. This is why we return two refs, not one.
    # start/end_percent control when during the diffusion process the CN is active
    # (e.g. 0.0-0.5 = apply only in early steps for composition guidance).
    cn_apply_id = nf.controlnet_apply_advanced(
        pos_ref, neg_ref,
        [cn_loader_id, 0], cn_image_ref,
        controlnet_config["strength"],
        controlnet_config.get("start_percent", 0.0),
        controlnet_config.get("end_percent", 1.0),
        node_id=str(cn_base_id + 2),
    )

    # Debug: save the preprocessed image (edge map, depth map, etc.) to inspect
    # what the ControlNet actually sees. Only saves if preprocessing was applied.
    if debug_images and cn_image_ref != image_ref:
        nf.save_image(cn_image_ref, "spellcaster_cn_debug",
                      node_id=str(cn_base_id + 5))

    # Output slots: 0=positive conditioning, 1=negative conditioning
    return [cn_apply_id, 0], [cn_apply_id, 1]


def inject_controlnet_pair(nf, cn1_config, cn2_config, guide_modes, arch_key,
                            image_ref, pos_ref, neg_ref, debug_images=False):
    """Inject two ControlNets in sequence (one feeds into the next).

    Multiple ControlNets can be chained: the conditioning output of the first
    becomes the input to the second. This allows combining constraints, e.g.
    "keep structure (tile detail) + fix colors (depth)".

    Args:
        nf: NodeFactory instance
        cn1_config: First ControlNet config (see inject_controlnet for format)
        cn2_config: Second ControlNet config
        guide_modes: ControlNet guide modes dict
        arch_key: Architecture identifier
        image_ref: Input image reference
        pos_ref, neg_ref: Initial conditioning
        debug_images: Save preprocessed images

    Returns:
        Tuple (final_pos_ref, final_neg_ref) after both ControlNets applied.

    Example:
        cn1 = {"mode": "Tile (detail) — SDXL", "strength": 0.7, ...}
        cn2 = {"mode": "Depth (spatial) — SDXL", "strength": 0.5, ...}
        pos, neg = inject_controlnet_pair(
            nf, cn1, cn2, CONTROLNET_GUIDE_MODES, "sdxl",
            [image_id, 0], [pos_id, 0], [neg_id, 0]
        )
        # Both ControlNets have been applied in sequence
    """
    # First CN gets base IDs 20-25, second gets 30-35 to avoid node ID collisions.
    # The second CN receives the first CN's updated conditioning, creating a chain:
    # original_cond -> [CN1] -> [CN2] -> final_cond
    pos, neg = inject_controlnet(
        nf, cn1_config, guide_modes, arch_key, image_ref,
        pos_ref, neg_ref, cn_base_id=20, debug_images=debug_images,
    )
    pos, neg = inject_controlnet(
        nf, cn2_config, guide_modes, arch_key, image_ref,
        pos, neg, cn_base_id=30, debug_images=debug_images,
    )
    return pos, neg


# ═══════════════════════════════════════════════════════════════════════════
#  IMAGE DIMENSION HELPERS
# ═══════════════════════════════════════════════════════════════════════════
# Flux ControlNets require input images to be multiples of 16 pixels.
# This helper ensures that constraint is met.

def ensure_mod16(nf, image_ref, arch_key, scale_node_id=None):
    """Scale image to mod-16 dimensions if needed (Flux ControlNets only).

    Flux ControlNets have a hard requirement: input images must have widths
    and heights divisible by 16. This helper checks the architecture and
    applies ImageScale if necessary.

    Args:
        nf: NodeFactory instance
        image_ref: Reference to image, e.g. [load_image_id, 0]
        arch_key: Architecture identifier (e.g. "sdxl", "flux1dev")
        scale_node_id: Optional explicit node ID for ImageScale

    Returns:
        Image reference (original if no scaling needed, or [new_node_id, 0]
        if scaled). Ready to pass to ControlNet.

    Note:
        This function is a placeholder for integration. The actual mod-16
        enforcement is currently handled inline in workflow builders via
        get_image_size + ImageScale nodes. This function will be expanded
        to fully encapsulate the logic.
    """
    if arch_key not in ("flux1dev", "flux_kontext", "flux2klein"):
        return image_ref

    # Get current dimensions, then scale to nearest mod-16
    size_id = nf.get_image_size_plus(image_ref)
    # The actual mod-16 enforcement is done by ImageScale with computed dims.
    # For now, return the original ref — the existing _ensure_mod16 logic
    # computes the target dims in Python and injects an ImageScale node.
    # This will be integrated when workflow builders are migrated.
    return image_ref
