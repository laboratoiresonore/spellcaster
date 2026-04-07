"""Composite workflow helpers — reusable building blocks for workflows.

These combine multiple NodeFactory calls into higher-level operations:
  load_model_stack()   — architecture-aware model loading
  inject_lora_chain()  — insert LoRA chain between model and workflow
  encode_prompts()     — positive/negative encoding (arch-aware)
  sample_standard()    — KSampler path (sd15/sdxl/flux1dev)
  sample_klein()       — SamplerCustomAdvanced path (flux2klein)
  inject_controlnet()  — optional ControlNet preprocessing + application

Each function takes a NodeFactory instance and returns references
that downstream nodes can wire into.
"""

from _architectures import ARCHITECTURES, get_arch


# ═══════════════════════════════════════════════════════════════════════════
#  Model Loading
# ═══════════════════════════════════════════════════════════════════════════

def load_model_stack(nf, preset, node_id="1"):
    """Load model + CLIP + VAE per architecture.

    Handles:
      - CheckpointLoaderSimple (sd15, sdxl, zit, illustrious)
      - UNETLoader + CLIPLoader + VAELoader (flux2klein)
      - UNETLoader + DualCLIPLoader + VAELoader (flux1dev, flux_kontext)

    Returns (model_ref, clip_ref, vae_ref) — each is a [node_id, output] list.
    """
    arch_key = preset.get("arch", "sdxl")
    arch = get_arch(arch_key)

    if arch.loader == "unet_clip_vae":
        # Flux / Klein — separate loaders
        unet_id = nf.unet_loader(preset["ckpt"], "default", node_id=node_id)

        if arch.clip_mode == "single_flux2":
            # Klein: single CLIPLoader, CLIP selection is model-dependent
            ckpt_lower = preset["ckpt"].lower()
            clip_name = ("qwen_3_8b_fp8mixed.safetensors"
                         if "9b" in ckpt_lower
                         else "qwen_3_4b.safetensors")
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

        return [unet_id, 0], [clip_id, 0], [vae_id, 0]

    else:
        # Checkpoint-based (sd15, sdxl, zit, illustrious)
        ckpt_id = nf.checkpoint_loader(preset["ckpt"], node_id=node_id)
        return [ckpt_id, 0], [ckpt_id, 1], [ckpt_id, 2]


# ═══════════════════════════════════════════════════════════════════════════
#  LoRA Chain
# ═══════════════════════════════════════════════════════════════════════════

def inject_lora_chain(nf, loras, model_ref, clip_ref, base_id=100):
    """Insert LoRA loader chain. Returns updated (model_ref, clip_ref).

    Uses high node IDs (base_id+) to avoid collision with the caller's nodes.
    Each LoRA is a dict with keys: name, strength_model, strength_clip.
    """
    if not loras:
        return model_ref, clip_ref

    prev_model = model_ref
    prev_clip = clip_ref

    for i, lora in enumerate(loras):
        nid = nf.lora_loader(
            prev_model, prev_clip,
            lora["name"],
            lora.get("strength_model", 1.0),
            lora.get("strength_clip", 1.0),
            node_id=str(base_id + i),
        )
        prev_model = [nid, 0]
        prev_clip = [nid, 1]

    return prev_model, prev_clip


# ═══════════════════════════════════════════════════════════════════════════
#  Prompt Encoding
# ═══════════════════════════════════════════════════════════════════════════

def encode_prompts(nf, arch_key, clip_ref, positive, negative,
                   pos_id=None, neg_id=None):
    """Encode positive and negative prompts, respecting architecture.

    For Flux architectures (supports_negative=False), negative is replaced
    with ConditioningZeroOut.

    Returns (pos_node_id, neg_node_id).
    """
    arch = get_arch(arch_key)

    pos_nid = nf.clip_encode(clip_ref, positive, node_id=pos_id)

    if arch.supports_negative and negative:
        neg_nid = nf.clip_encode(clip_ref, negative, node_id=neg_id)
    else:
        neg_nid = nf.conditioning_zero_out([pos_nid, 0], node_id=neg_id)

    return pos_nid, neg_nid


# ═══════════════════════════════════════════════════════════════════════════
#  Sampling
# ═══════════════════════════════════════════════════════════════════════════

def sample_standard(nf, model_ref, pos_ref, neg_ref, latent_ref,
                    seed, preset, denoise_override=None, node_id=None):
    """Standard KSampler path (sd15, sdxl, flux1dev, flux_kontext, zit, illustrious).

    Returns the sampler node ID.
    """
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
    """Klein SamplerCustomAdvanced path.

    Builds: CFGGuider + KSamplerSelect + Flux2Scheduler + RandomNoise
            + EmptyFlux2LatentImage → SamplerCustomAdvanced

    Returns the SamplerCustomAdvanced node ID.
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
    # Wrap conditioning with reference latent
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
#  ControlNet Injection
# ═══════════════════════════════════════════════════════════════════════════

def inject_controlnet(nf, controlnet_config, guide_modes, arch_key,
                      image_ref, pos_ref, neg_ref,
                      cn_base_id=20, debug_images=False):
    """Inject a single ControlNet into the workflow.

    controlnet_config: dict with mode, strength, start_percent, end_percent
    guide_modes: the CONTROLNET_GUIDE_MODES dict from the main plugin
    image_ref: reference to the source image for preprocessing
    pos_ref, neg_ref: current conditioning references

    Returns (new_pos_ref, new_neg_ref) — either redirected through CN or unchanged.
    """
    if not controlnet_config or controlnet_config.get("mode", "Off") == "Off":
        return pos_ref, neg_ref

    guide = guide_modes.get(controlnet_config["mode"])
    if not guide:
        return pos_ref, neg_ref

    cn_model = guide["cn_models"].get(arch_key, guide["cn_models"].get("sdxl"))
    if not cn_model:
        return pos_ref, neg_ref

    preprocessor = guide.get("preprocessor")
    cn_image_ref = image_ref

    if preprocessor:
        pre_id = nf.preprocessor(preprocessor, image_ref,
                                 node_id=str(cn_base_id))
        cn_image_ref = [pre_id, 0]

    cn_loader_id = nf.controlnet_loader(cn_model,
                                        node_id=str(cn_base_id + 1))

    cn_apply_id = nf.controlnet_apply_advanced(
        pos_ref, neg_ref,
        [cn_loader_id, 0], cn_image_ref,
        controlnet_config["strength"],
        controlnet_config.get("start_percent", 0.0),
        controlnet_config.get("end_percent", 1.0),
        node_id=str(cn_base_id + 2),
    )

    # Debug save
    if debug_images and cn_image_ref != image_ref:
        nf.save_image(cn_image_ref, "spellcaster_cn_debug",
                      node_id=str(cn_base_id + 5))

    return [cn_apply_id, 0], [cn_apply_id, 1]


def inject_controlnet_pair(nf, cn1_config, cn2_config, guide_modes, arch_key,
                            image_ref, pos_ref, neg_ref, debug_images=False):
    """Inject up to two chained ControlNets.

    Returns (final_pos_ref, final_neg_ref).
    """
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
#  Image Dimension Helpers
# ═══════════════════════════════════════════════════════════════════════════

def ensure_mod16(nf, image_ref, arch_key, scale_node_id=None):
    """Scale image to mod-16 dimensions if needed for Flux ControlNet.

    Only applies for flux1dev and flux_kontext architectures.
    Returns the (possibly new) image reference.
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
