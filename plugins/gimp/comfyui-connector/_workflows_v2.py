"""Migrated workflow builders using NodeFactory + Architecture Registry.

These are drop-in replacements for the existing _build_* functions.
Each produces an identical workflow dict to the original.

Migration strategy: rename original to _build_*_legacy, add new version,
run golden test to verify identical output, then delete _legacy.
"""

from _nodes import NodeFactory
from _architectures import ARCHITECTURES, get_arch
from _composites import (
    load_model_stack, inject_lora_chain, encode_prompts,
    sample_standard, sample_klein_img2img,
    inject_controlnet, inject_controlnet_pair,
)


# ═══════════════════════════════════════════════════════════════════════════
#  img2img — Standard image-to-image generation
# ═══════════════════════════════════════════════════════════════════════════

def build_img2img(image_filename, preset, prompt_text, negative_text, seed,
                  loras=None, controlnet=None, controlnet_2=None,
                  guide_modes=None):
    """Standard img2img: load model → encode → sample → decode → save.

    Drop-in replacement for _build_img2img().
    """
    nf = NodeFactory()

    # 1. Load model stack (architecture-aware)
    model_ref, clip_ref, vae_ref = load_model_stack(nf, preset, "1")

    # 2. LoRA chain
    model_ref, clip_ref = inject_lora_chain(nf, loras or [], model_ref, clip_ref)

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
    samp_id = nf.ksampler(
        model_ref,
        [pos_id, 0], [neg_id, 0], [enc_id, 0],
        seed, preset["steps"], preset["cfg"],
        preset.get("sampler", "euler"), preset.get("scheduler", "normal"),
        preset.get("denoise", 0.65),
        node_id="6",
    )
    dec_id = nf.vae_decode([samp_id, 0], vae_ref, node_id="7")
    nf.save_image([dec_id, 0], "gimp_comfy", node_id="8")

    # 7. ControlNet injection (optional)
    if guide_modes and controlnet and controlnet.get("mode", "Off") != "Off":
        cn_pos, cn_neg = inject_controlnet(
            nf, controlnet, guide_modes, arch_key, img_ref,
            [pos_id, 0], [neg_id, 0], cn_base_id=20,
        )
        nf.patch_input("6", "positive", cn_pos)
        nf.patch_input("6", "negative", cn_neg)

    if guide_modes and controlnet_2 and controlnet_2.get("mode", "Off") != "Off":
        # Chain from CN1 if present, else from raw CLIP
        prev_pos = [str(22), 0] if nf.has_node("22") else [pos_id, 0]
        prev_neg = [str(22), 1] if nf.has_node("22") else [neg_id, 0]
        cn2_pos, cn2_neg = inject_controlnet(
            nf, controlnet_2, guide_modes, arch_key, [img_id, 0],
            prev_pos, prev_neg, cn_base_id=30,
        )
        nf.patch_input("6", "positive", cn2_pos)
        nf.patch_input("6", "negative", cn2_neg)

    return nf.build()


# ═══════════════════════════════════════════════════════════════════════════
#  txt2img — Text-to-image generation
# ═══════════════════════════════════════════════════════════════════════════

def build_txt2img(preset, prompt_text, negative_text, seed, loras=None):
    """Text-to-image: generate from empty latent.

    Drop-in replacement for _build_txt2img().
    """
    nf = NodeFactory()

    model_ref, clip_ref, vae_ref = load_model_stack(nf, preset, "1")
    model_ref, clip_ref = inject_lora_chain(nf, loras or [], model_ref, clip_ref)

    pos_id, neg_id = encode_prompts(nf, preset.get("arch", "sdxl"), clip_ref,
                                     prompt_text, negative_text,
                                     pos_id="2", neg_id="3")

    empty_id = nf.empty_latent_image(preset["width"], preset["height"],
                                      batch_size=1, node_id="4")

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
#  rembg — Background removal
# ═══════════════════════════════════════════════════════════════════════════

def build_rembg(image_filename):
    """Remove background. Drop-in replacement for _build_rembg()."""
    nf = NodeFactory()
    img_id = nf.load_image(image_filename, node_id="1")
    rembg_id = nf.rembg([img_id, 0], node_id="2")
    nf.save_image([rembg_id, 0], "spellcaster_rembg", node_id="3")
    return nf.build()


# ═══════════════════════════════════════════════════════════════════════════
#  upscale — Model-based super-resolution
# ═══════════════════════════════════════════════════════════════════════════

def build_upscale(image_filename, model_name, upscale_factor=1.0):
    """Upscale image. Drop-in replacement for _build_upscale()."""
    nf = NodeFactory()
    img_id = nf.load_image(image_filename, node_id="1")
    up_model_id = nf.upscale_model_loader(model_name, node_id="2")
    up_id = nf.image_upscale_with_model_by_factor(
        [up_model_id, 0], [img_id, 0], upscale_factor, node_id="3")
    nf.save_image([up_id, 0], "spellcaster_upscale", node_id="4")
    return nf.build()


# ═══════════════════════════════════════════════════════════════════════════
#  lama_remove — Object removal without diffusion
# ═══════════════════════════════════════════════════════════════════════════

def build_lama_remove(image_filename, mask_filename):
    """LaMa inpainting. Drop-in replacement for _build_lama_remove()."""
    nf = NodeFactory()
    img_id = nf.load_image(image_filename, node_id="1")
    mask_img_id = nf.load_image(mask_filename, node_id="2")
    mask_id = nf.image_to_mask([mask_img_id, 0], "red", node_id="5")
    lama_id = nf.lama_remover([img_id, 0], [mask_id, 0], node_id="3")
    nf.save_image([lama_id, 0], "spellcaster_lama", node_id="4")
    return nf.build()


# ═══════════════════════════════════════════════════════════════════════════
#  lut — Color grading
# ═══════════════════════════════════════════════════════════════════════════

def build_lut(image_filename, lut_name, strength):
    """Apply color LUT. Drop-in replacement for _build_lut()."""
    nf = NodeFactory()
    img_id = nf.load_image(image_filename, node_id="1")
    lut_id = nf.image_apply_lut([img_id, 0], lut_name, strength, node_id="2")
    nf.save_image([lut_id, 0], "spellcaster_lut", node_id="3")
    return nf.build()


# ═══════════════════════════════════════════════════════════════════════════
#  klein_img2img — Flux 2 Klein distilled img2img
# ═══════════════════════════════════════════════════════════════════════════

def build_klein_img2img(image_filename, klein_model_key, prompt_text, seed,
                         steps=4, denoise=0.65, guidance=1.0,
                         enhancer_mag=1.0, enhancer_contrast=0.0,
                         lora_name=None, lora_strength=1.0,
                         klein_models=None):
    """Flux 2 Klein img2img. Drop-in replacement for _build_klein_img2img().

    klein_models: the KLEIN_MODELS dict from the main plugin.
    """
    if klein_models is None:
        # Fallback — import from main module during migration
        klein_models = {
            "Klein 9B": {
                "unet": "A-Flux\\Flux2\\flux-2-klein-9b.safetensors",
                "clip": "qwen_3_8b_fp8mixed.safetensors",
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

    km = klein_models[klein_model_key]
    nf = NodeFactory()

    # Model loaders
    unet_id = nf.unet_loader(km["unet"], "default", node_id="1")
    clip_id = nf.clip_loader(
        km.get("clip", "qwen_3_8b_fp8mixed.safetensors"),
        clip_type="flux2", device="default", node_id="2",
    )
    vae_id = nf.vae_loader("flux2-vae.safetensors", node_id="3")

    # Text conditioning
    pos_id = nf.clip_encode([clip_id, 0], prompt_text, node_id="4")
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

    # Sampler setup
    guider_id = nf.cfg_guider([unet_id, 0], [ref_pos_id, 0], [ref_neg_id, 0],
                              guidance, node_id="30")
    sampler_id = nf.ksampler_select("euler", node_id="31")
    sched_id = nf.flux2_scheduler(steps, [size_id, 0], [size_id, 1],
                                   node_id="32")
    noise_id = nf.random_noise(seed, node_id="33")
    empty_id = nf.empty_flux2_latent_image([size_id, 0], [size_id, 1],
                                            batch_size=1, node_id="34")

    # Sample
    sample_id = nf.sampler_custom_advanced(
        [noise_id, 0], [guider_id, 0], [sampler_id, 0],
        [sched_id, 0], [empty_id, 0], node_id="40",
    )

    # Decode and save
    dec_id = nf.vae_decode([sample_id, 0], [vae_id, 0], node_id="50")
    nf.save_image([dec_id, 0], "gimp_klein", node_id="51")

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
    """ReActorFaceSwapOpt with Options + FaceBoost + optional double-pass.

    Drop-in replacement for _build_faceswap().
    quality_presets: the FACESWAP_QUALITY_PRESETS dict from the main plugin.
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
                        visibility, codeformer_weight):
    """Restore faces. Drop-in for _build_face_restore()."""
    nf = NodeFactory()
    img_id = nf.load_image(image_filename, node_id="1")
    restore_id = nf.reactor_restore_face(
        [img_id, 0], facedetection=facedetection,
        model=model_name, visibility=visibility,
        codeformer_weight=codeformer_weight, node_id="2",
    )
    nf.save_image([restore_id, 0], "spellcaster_facerestore", node_id="3")
    return nf.build()


# ═══════════════════════════════════════════════════════════════════════════
#  Photo Restore — Upscale + Face Restore + Sharpen pipeline
# ═══════════════════════════════════════════════════════════════════════════

def build_photo_restore(image_filename, upscale_model, face_model,
                         facedetection, visibility, codeformer_weight,
                         sharpen_radius, sigma, alpha):
    """Full photo restoration pipeline. Drop-in for _build_photo_restore()."""
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
                              controlnet=None, controlnet_2=None,
                              guide_modes=None):
    """Upscale + img2img hallucination. Drop-in for _build_detail_hallucinate().

    Note: _ensure_mod16 is handled at the caller level during migration.
    The v2 builder omits it (placeholder in composites).
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

    # Encode prompts
    arch_key = preset.get("arch", "sdxl")
    pos_id, neg_id = encode_prompts(nf, arch_key, clip_ref,
                                     prompt_text, negative_text,
                                     pos_id="5", neg_id="6")

    # VAE encode → sample → decode → save
    enc_id = nf.vae_encode(img_ref, vae_ref, node_id="7")
    samp_id = nf.ksampler(
        model_ref,
        [pos_id, 0], [neg_id, 0], [enc_id, 0],
        seed, steps or preset["steps"], cfg,
        preset.get("sampler", "euler"), preset.get("scheduler", "normal"),
        denoise, node_id="8",
    )
    dec_id = nf.vae_decode([samp_id, 0], vae_ref, node_id="9")
    nf.save_image([dec_id, 0], "spellcaster_hallucinate", node_id="10")

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
                    controlnet_2=None, guide_modes=None,
                    lineart_models=None):
    """Colorize B&W photo. Drop-in for _build_colorize().

    lineart_models: CONTROLNET_LINEART_MODELS dict from main plugin.
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

    # Lineart ControlNet
    cn_lineart = (lineart_models or {}).get(arch_key, "control-lora-openposeXL2-rank256.safetensors")
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
    samp_id = nf.ksampler(
        model_ref,
        [cn_apply_id, 0], [cn_apply_id, 1], [enc_id, 0],
        seed, steps or preset["steps"], cfg or preset["cfg"],
        preset.get("sampler", "euler"), preset.get("scheduler", "normal"),
        denoise, node_id="9",
    )
    dec_id = nf.vae_decode([samp_id, 0], vae_ref, node_id="10")
    nf.save_image([dec_id, 0], "spellcaster_colorize", node_id="11")

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
    """Generic ControlNet generation. Drop-in for _build_controlnet_gen()."""
    nf = NodeFactory()

    img_id = nf.load_image(image_filename, node_id="1")
    pre_id = nf.preprocessor(preprocessor_type, [img_id, 0], node_id="2")

    model_ref, clip_ref, vae_ref = load_model_stack(nf, preset, "3")
    model_ref, clip_ref = inject_lora_chain(nf, loras or [], model_ref, clip_ref)

    cn_loader_id = nf.controlnet_loader(controlnet_model, node_id="4")

    pos_id = nf.clip_encode(clip_ref, prompt, node_id="5")
    neg_id = nf.clip_encode(clip_ref, negative, node_id="6")

    cn_apply_id = nf.controlnet_apply_advanced(
        [pos_id, 0], [neg_id, 0],
        [cn_loader_id, 0], [pre_id, 0],
        cn_strength, 0.0, 1.0, node_id="7",
    )

    empty_id = nf.empty_latent_image(width, height, 1, node_id="8")
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
                   sampler="euler", scheduler="normal"):
    """IC-Light relighting. Drop-in for _build_iclight().

    IC-Light only works with SD1.5 models. Uses CheckpointLoaderSimple.
    ICLightConditioning.foreground expects LATENT, not IMAGE.
    """
    nf = NodeFactory()
    img_id = nf.load_image(image_filename, node_id="1")

    # Load SD1.5 checkpoint
    ckpt_id = nf.checkpoint_loader(ckpt_name, node_id="2")
    model_ref = [ckpt_id, 0]
    clip_ref = [ckpt_id, 1]
    vae_ref = [ckpt_id, 2]

    # VAEEncode foreground to latent (ICLightConditioning expects LATENT)
    latent_id = nf.vae_encode([img_id, 0], vae_ref, node_id="10")

    # Load and apply IC-Light UNET
    iclight_id = nf.load_and_apply_iclight_unet(
        model_ref, "SD-1.5\\iclight_sd15_fc.safetensors", node_id="3",
    )

    # Text encoding
    pos_id = nf.clip_encode(clip_ref, prompt, node_id="4")
    neg_id = nf.clip_encode(clip_ref, negative, node_id="5")

    # ICLightConditioning
    cond_id = nf.iclight_conditioning(
        [pos_id, 0], [neg_id, 0], vae_ref, [latent_id, 0],
        multiplier=multiplier, node_id="6",
    )

    # Sample
    samp_id = nf.ksampler(
        [iclight_id, 0],
        [cond_id, 0], [cond_id, 1], [cond_id, 2],
        seed, steps, cfg, sampler, scheduler, 1.0, node_id="7",
    )
    dec_id = nf.vae_decode([samp_id, 0], vae_ref, node_id="8")
    nf.save_image([dec_id, 0], "spellcaster_iclight", node_id="9")

    return nf.build()


# ═══════════════════════════════════════════════════════════════════════════
#  SUPIR AI Restoration
# ═══════════════════════════════════════════════════════════════════════════

def build_supir(image_filename, supir_model, sdxl_model, prompt, seed,
                 denoise=0.3, steps=45, scale_by=1.0,
                 controlnet=None, controlnet_2=None, guide_modes=None):
    """SUPIR AI restoration — full 5-stage pipeline. Drop-in for _build_supir().

    Stages: model_loader → first_stage → conditioner → sample → decode.
    Optional ControlNet refinement post-pass using SDXL checkpoint.
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
                   controlnet=None, controlnet_2=None, guide_modes=None):
    """Inpainting: regenerate only the masked region. Drop-in for _build_inpaint()."""
    nf = NodeFactory()

    # Model loading
    model_ref, clip_ref, vae_ref = load_model_stack(nf, preset, "1")
    model_ref, clip_ref = inject_lora_chain(nf, loras or [], model_ref, clip_ref)

    # Load image and mask
    img_id = nf.load_image(image_filename, node_id="4")
    img_ref = [img_id, 0]
    mask_img_id = nf.load_image(mask_filename, node_id="5")

    # Encode prompts
    arch_key = preset.get("arch", "sdxl")
    pos_id, neg_id = encode_prompts(nf, arch_key, clip_ref,
                                     prompt_text, negative_text,
                                     pos_id="2", neg_id="3")

    # Convert mask IMAGE to MASK (red channel)
    mask_id = nf.image_to_mask([mask_img_id, 0], "red", node_id="51")

    # Get original size for restoring after sampling
    size_id = nf.get_image_size_plus(img_ref, node_id="90")

    # Scale image and mask to working resolution
    scaled_img_id = nf.image_scale(
        img_ref, preset["width"], preset["height"],
        upscale_method="lanczos", crop="disabled", node_id="91",
    )
    scaled_mask_img_id = nf.image_scale(
        [mask_img_id, 0], preset["width"], preset["height"],
        upscale_method="nearest-exact", crop="disabled", node_id="92",
    )
    scaled_mask_id = nf.image_to_mask([scaled_mask_img_id, 0], "red", node_id="52")

    # VAE encode → SetLatentNoiseMask → sample
    enc_id = nf.vae_encode([scaled_img_id, 0], vae_ref, node_id="6")
    masked_id = nf.set_latent_noise_mask([enc_id, 0], [scaled_mask_id, 0], node_id="7")

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
    """Outpaint: extend the canvas. Drop-in for _build_outpaint().

    Klein uses standard KSampler pipeline (SamplerCustomAdvanced doesn't
    support SetLatentNoiseMask).
    """
    nf = NodeFactory()
    arch_key = preset.get("arch", "sdxl")
    is_klein = arch_key == "flux2klein"

    # Model loading
    model_ref, clip_ref, vae_ref = load_model_stack(nf, preset, "1")
    model_ref, clip_ref = inject_lora_chain(nf, loras or [], model_ref, clip_ref)

    # Load and pad image
    img_id = nf.load_image(image_filename, node_id="4")
    pad_id = nf.image_pad_for_outpaint(
        [img_id, 0], left, top, right, bottom, feathering, node_id="5",
    )
    padded_ref = [pad_id, 0]

    # All architectures use KSampler for outpaint (Klein included — see docstring)
    if is_klein:
        pos_id = nf.clip_encode(clip_ref, prompt_text, node_id="2")
        neg_id = nf.clip_encode(clip_ref, "blurry, low quality, artifacts, seam, border", node_id="3")
        enc_id = nf.vae_encode(padded_ref, vae_ref, node_id="6")
        masked_id = nf.set_latent_noise_mask([enc_id, 0], [pad_id, 1], node_id="7")
        samp_id = nf.ksampler(
            model_ref,
            [pos_id, 0], [neg_id, 0], [masked_id, 0],
            seed, preset.get("steps", 20), 3.5,
            "euler", "simple", 0.85, node_id="8",
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

    # ControlNet injection (optional)
    if guide_modes and controlnet and controlnet.get("mode", "Off") != "Off":
        cn_pos, cn_neg = inject_controlnet(
            nf, controlnet, guide_modes, arch_key, padded_ref,
            [pos_id, 0] if isinstance(pos_id, str) else pos_id,
            [neg_id, 0] if isinstance(neg_id, str) else neg_id,
            cn_base_id=20,
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
    model_ref, clip_ref = inject_lora_chain(nf, loras or [], model_ref, clip_ref)

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

    # Text encoding
    pos_id = nf.clip_encode(clip_ref, prompt_text, node_id="5")
    neg_id = nf.clip_encode(clip_ref, negative_text or "blurry, deformed, bad anatomy", node_id="6")

    # Target image → VAE encode → sample → decode → save
    target_id = nf.load_image(target_filename, node_id="7")
    enc_id = nf.vae_encode([target_id, 0], vae_ref, node_id="8")
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
    model_ref = [unet_id, 0]

    # CLIP loader (architecture-dependent)
    if is_flux2:
        clip_name = "qwen_3_8b_fp8mixed.safetensors"
        if "klein-4b" in lower or "klein_4b" in lower:
            clip_name = "qwen_3_4b_fp8mixed.safetensors"
        clip_id = nf.clip_loader(clip_name, clip_type="flux2", device="default", node_id="7")
    else:
        clip_id = nf.dual_clip_loader(
            "clip_l.safetensors", "t5xxl_fp8_e4m3fn.safetensors",
            clip_type="flux", node_id="7",
        )
    clip_ref = [clip_id, 0]

    # LoRA chain
    model_ref, clip_ref = inject_lora_chain(nf, loras or [], model_ref, clip_ref)

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
                             guidance=1.0, klein_models=None):
    """Klein img2img with separate reference image. Drop-in for _build_klein_img2img_ref().

    Same pipeline as build_klein_img2img but uses the reference image
    as the ReferenceLatent source instead of the main input image.
    """
    if klein_models is None:
        klein_models = {
            "Klein 9B": {"unet": "A-Flux\\Flux2\\flux-2-klein-9b.safetensors",
                         "clip": "qwen_3_8b_fp8mixed.safetensors"},
            "Klein 4B": {"unet": "A-Flux\\flux-2-klein-4b-fp8.safetensors",
                         "clip": "qwen_3_4b.safetensors"},
            "Klein Base 4B": {"unet": "A-Flux\\flux-2-klein-base-4b-fp8.safetensors",
                              "clip": "qwen_3_4b.safetensors"},
        }

    km = klein_models[klein_model_key]
    nf = NodeFactory()

    # Model loaders
    unet_id = nf.unet_loader(km["unet"], "default", node_id="1")
    clip_id = nf.clip_loader(
        km.get("clip", "qwen_3_8b_fp8mixed.safetensors"),
        clip_type="flux2", device="default", node_id="2",
    )
    vae_id = nf.vae_loader("flux2-vae.safetensors", node_id="3")

    # Text conditioning
    pos_id = nf.clip_encode([clip_id, 0], prompt_text, node_id="4")
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

    # ReferenceLatent: use main image latent for conditioning
    ref_pos_id = nf.reference_latent([pos_id, 0], [latent_id, 0], node_id="20")
    ref_neg_id = nf.reference_latent([neg_id, 0], [latent_id, 0], node_id="21")

    # Sampler setup
    guider_id = nf.cfg_guider([unet_id, 0], [ref_pos_id, 0], [ref_neg_id, 0],
                              guidance, node_id="30")
    sampler_id = nf.ksampler_select("euler", node_id="31")
    sched_id = nf.flux2_scheduler(steps, [size_id, 0], [size_id, 1], node_id="32")
    noise_id = nf.random_noise(seed, node_id="33")
    empty_id = nf.empty_flux2_latent_image([size_id, 0], [size_id, 1],
                                            batch_size=1, node_id="34")

    # Sample
    sample_id = nf.sampler_custom_advanced(
        [noise_id, 0], [guider_id, 0], [sampler_id, 0],
        [sched_id, 0], [empty_id, 0], node_id="40",
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
                          codeformer_weight=0.8, klein_models=None):
    """Klein headswap: ReActor + Klein img2img refinement. Drop-in for _build_klein_headswap().

    Uses BasicScheduler (not Flux2Scheduler) because Klein refinement needs denoise support.
    """
    if klein_models is None:
        klein_models = {
            "Klein 9B": {"unet": "A-Flux\\Flux2\\flux-2-klein-9b.safetensors",
                         "clip": "qwen_3_8b_fp8mixed.safetensors"},
            "Klein 4B": {"unet": "A-Flux\\flux-2-klein-4b-fp8.safetensors",
                         "clip": "qwen_3_4b.safetensors"},
            "Klein Base 4B": {"unet": "A-Flux\\flux-2-klein-base-4b-fp8.safetensors",
                              "clip": "qwen_3_4b.safetensors"},
        }

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
        km.get("clip", "qwen_3_8b_fp8mixed.safetensors"),
        clip_type="flux2", device="default", node_id="21",
    )
    vae_id = nf.vae_loader("flux2-vae.safetensors", node_id="22")

    pos_id = nf.clip_encode([clip_id, 0], prompt, node_id="23")
    neg_id = nf.conditioning_zero_out([pos_id, 0], node_id="24")

    # Scale swapped image + encode
    scaled_id = nf.image_scale_to_total_pixels([swap_id, 0], megapixels=1.0, node_id="30")
    size_id = nf.get_image_size([scaled_id, 0], node_id="31")
    latent_id = nf.vae_encode([scaled_id, 0], [vae_id, 0], node_id="32")

    # ReferenceLatent for context
    ref_pos_id = nf.reference_latent([pos_id, 0], [latent_id, 0], node_id="33")
    ref_neg_id = nf.reference_latent([neg_id, 0], [latent_id, 0], node_id="34")

    # Sampling — uses BasicScheduler for denoise support
    guider_id = nf.cfg_guider([unet_id, 0], [ref_pos_id, 0], [ref_neg_id, 0],
                              1.0, node_id="40")
    sampler_id = nf.ksampler_select("euler", node_id="41")
    sched_id = nf.basic_scheduler([unet_id, 0], steps, denoise, node_id="42")
    noise_id = nf.random_noise(seed, node_id="43")
    empty_id = nf.empty_flux2_latent_image([size_id, 0], [size_id, 1],
                                            batch_size=1, node_id="44")

    sample_id = nf.sampler_custom_advanced(
        [noise_id, 0], [guider_id, 0], [sampler_id, 0],
        [sched_id, 0], [empty_id, 0], node_id="50",
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
                         "force_size": "Disabled",
                         "custom_width": 0, "custom_height": 0,
                         "frame_load_cap": 0, "skip_first_frames": 0,
                         "select_every_nth": 1}},
    })
    video_ref = ["1", 0]

    if upscale_factor > 1.0 and upscale_model:
        nf.update({
            "10": {"class_type": "TS_Video_Upscale_With_Model",
                   "inputs": {"model_name": upscale_model, "images": video_ref,
                              "upscale_method": "lanczos", "factor": upscale_factor,
                              "device_strategy": "auto"}},
        })
        video_ref = ["10", 0]

    if rtx_scale > 1.0:
        rtx_id = nf.rtx_video_super_resolution(video_ref, scale_factor=rtx_scale,
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
                         "force_size": "Disabled",
                         "custom_width": 0, "custom_height": 0,
                         "frame_load_cap": 0, "skip_first_frames": 0,
                         "select_every_nth": 1}},
    })
    video_ref = ["1", 0]

    if upscale_factor > 1.0 and upscale_model:
        nf.update({
            "10": {"class_type": "TS_Video_Upscale_With_Model",
                   "inputs": {"model_name": upscale_model, "images": video_ref,
                              "upscale_method": "lanczos", "factor": upscale_factor,
                              "device_strategy": "auto"}},
        })
        video_ref = ["10", 0]

    if rtx_scale > 1.0:
        rtx_id = nf.rtx_video_super_resolution(video_ref, scale_factor=rtx_scale,
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
                     end_image_filename=None):
    """Wan 2.2 video generation — dual-model architecture. Drop-in for _build_wan_video().

    Uses NodeFactory for common nodes, nf.update() for exotic video/accelerator nodes.
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
    use_flf = loop or (end_image_filename is not None)

    # Model loaders
    if is_gguf_high:
        nf.update({"1": {"class_type": "CLIPLoaderGGUF",
                          "inputs": {"clip_name": clip_name, "type": "wan"}}})
        nf.update({"2": {"class_type": "UnetLoaderGGUF",
                          "inputs": {"unet_name": high_model}}})
    else:
        nf.update({"1": {"class_type": "CLIPLoaderGGUF",
                          "inputs": {"clip_name": clip_name, "type": "wan"}}})
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

    if end_image_filename and not loop:
        nf.load_image(end_image_filename, node_id="7b")

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
        nf.update({
            "97": {"class_type": "IPAdapterWANLoader",
                   "inputs": {"ipadapter": "ip-adapter.bin", "provider": "cuda"}},
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

    # Video conditioning
    if use_flf:
        end_ref = ["7", 0] if loop else ["7b", 0]
        flf_id = nf.wan_first_last_frame(
            ["5", 0], ["6", 0], ["4", 0],
            ["7", 0], end_ref, high_ref,
            width, height, length, seed, steps, cfg, node_id="40",
        )
    else:
        i2v_id = nf.wan_image_to_video(
            ["5", 0], ["6", 0], ["4", 0],
            ["7", 0], high_ref,
            width, height, length, seed, steps, cfg, node_id="40",
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

    # Save raw (optional)
    if save_raw:
        nf.update({
            "80": {"class_type": "VHS_VideoCombine",
                   "inputs": {"images": video_ref, "frame_rate": float(fps),
                              "loop_count": 0, "filename_prefix": f"{prefix}_raw",
                              "format": "video/h264-mp4", "pingpong": False,
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

    # RTX Video Super Resolution (optional)
    if rtx_scale > 1.0:
        rtx_id = nf.rtx_video_super_resolution(video_ref, scale_factor=rtx_scale,
                                                node_id="75")
        video_ref = [rtx_id, 0]

    # Final MP4
    final_fps = float(fps * (4 if interpolate else 1))
    nf.update({
        "83": {"class_type": "VHS_VideoCombine",
               "inputs": {"images": video_ref, "frame_rate": final_fps,
                          "loop_count": 0, "filename_prefix": f"{prefix}_final",
                          "format": "video/h264-mp4", "pix_fmt": "yuv420p",
                          "crf": 17, "pingpong": pingpong,
                          "save_output": True}},
    })

    # Last frame for GIMP
    nf.update({
        "85": {"class_type": "ImageFromBatch+",
               "inputs": {"images": [dec_id, 0], "start": length - 1, "length": 1}},
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
                                 batch_size=4, uniform_batch_size=True,
                                 color_correction=True, temporal_overlap=2,
                                 input_noise_scale=0.0, latent_noise_scale=0.0,
                                 vae_model="seedvr2_vae.safetensors",
                                 vae_tiled=True, fps=16):
    """SeedVR2 AI video upscaler. Drop-in for _build_seedvr2_video_upscale()."""
    import random as _random
    if seed < 0:
        seed = _random.randint(0, 2**32 - 1)

    nf = NodeFactory()
    nf.update({
        "1": {"class_type": "VHS_LoadVideo",
              "inputs": {"video": video_name, "force_rate": 0,
                         "force_size": "Disabled",
                         "custom_width": 0, "custom_height": 0,
                         "frame_load_cap": 0, "skip_first_frames": 0,
                         "select_every_nth": 1}},
        "2": {"class_type": "SeedVR2LoadVAEModel",
              "inputs": {"model": vae_model, "device": "cuda",
                         "encode_tiled": vae_tiled, "encode_tile_size": 256,
                         "encode_tile_overlap": 64,
                         "decode_tiled": vae_tiled, "decode_tile_size": 256,
                         "decode_tile_overlap": 64,
                         "tile_debug": False, "offload_device": "cpu",
                         "cache_model": True, "torch_compile_args": ""}},
        "3": {"class_type": "SeedVR2VideoUpscaler",
              "inputs": {"image": ["1", 0], "dit": ["1", 0],
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
                          ipadapter_preset="PLUS (high strength)",
                          weight=0.8, denoise=0.6,
                          controlnet=None, controlnet_2=None,
                          guide_modes=None):
    """Style transfer via IPAdapter. Drop-in for _build_style_transfer().

    Pipeline: model stack → IPAdapterUnifiedLoader → IPAdapterAdvanced(style transfer)
              → LoadImage(target) → encode → KSampler → decode → save
    """
    nf = NodeFactory()
    arch_key = preset.get("arch", "sdxl")

    # 1. Model stack
    model_ref, clip_ref, vae_ref = load_model_stack(nf, preset, "1")

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

    # 3. Encode prompts
    pos_id = nf.clip_encode(clip_ref, prompt_text, node_id="5")
    neg_id = nf.clip_encode(clip_ref, negative_text or "blurry, deformed, bad anatomy",
                             node_id="6")

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
    samp_id = nf.ksampler(
        [ipa_id, 0],
        [pos_id, 0], [neg_id, 0], [enc_id, 0],
        seed, preset["steps"], preset["cfg"],
        preset.get("sampler", "euler"), preset.get("scheduler", "normal"),
        denoise, node_id="9",
    )
    dec_id = nf.vae_decode([samp_id, 0], vae_ref, node_id="10")
    nf.save_image([dec_id, 0], "spellcaster_style", node_id="11")

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
                   controlnet=None, controlnet_2=None, guide_modes=None):
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

    # 5. Encode
    pos_id = nf.clip_encode(clip_ref, prompt_text, node_id="5")
    neg_id = nf.clip_encode(clip_ref, negative_text, node_id="6")

    # 6. VAE encode + sample + decode
    enc_id = nf.vae_encode(img_ref, vae_ref, node_id="7")
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
                     klein_model_key="Klein 9B", steps=20, guidance=30.0,
                     swap_model="reswapper_256.onnx",
                     face_restore_model="codeformer-v0.1.0.pth",
                     face_restore_vis=0.9, codeformer_weight=0.6,
                     klein_models=None):
    """Photobooth: generate passport-style headshots with extreme character fidelity.

    Three-stage single-workflow pipeline:

    1. **Klein ReferenceLatent generation** — generates a clean studio headshot
       guided by the reference photo. Prompt controls background/lighting/pose,
       ReferenceLatent provides structural guidance from the input face.
       This produces a well-composed headshot that RESEMBLES the person.

    2. **ReActor face swap** — transplants the EXACT face from the original
       reference onto the Klein output. This restores character fidelity
       that Klein may have drifted. Uses reswapper_256 + FaceBoost.

    3. **Face restore** — CodeFormer final pass for artifact cleanup and
       skin detail enhancement.

    The result is a clean passport-style headshot with the person's real face.
    """
    if klein_models is None:
        klein_models = {
            "Klein 9B": {"unet": "A-Flux\\Flux2\\flux-2-klein-9b.safetensors",
                         "clip": "qwen_3_8b_fp8mixed.safetensors"},
            "Klein 4B": {"unet": "A-Flux\\flux-2-klein-4b-fp8.safetensors",
                         "clip": "qwen_3_4b.safetensors"},
            "Klein Base 4B": {"unet": "A-Flux\\flux-2-klein-base-4b-fp8.safetensors",
                              "clip": "qwen_3_4b.safetensors"},
        }

    km = klein_models[klein_model_key]
    nf = NodeFactory()

    # ── Load reference image (shared: Klein input + ReActor source) ──
    ref_id = nf.load_image(ref_filename, node_id="1")

    # ══════════════════════════════════════════════════════════════════
    # Stage 1: Klein ReferenceLatent generation — clean headshot base
    # ══════════════════════════════════════════════════════════════════
    unet_id = nf.unet_loader(km["unet"], "default", node_id="10")
    clip_id = nf.clip_loader(
        km.get("clip", "qwen_3_8b_fp8mixed.safetensors"),
        clip_type="flux2", device="default", node_id="11",
    )
    vae_id = nf.vae_loader("flux2-vae.safetensors", node_id="12")

    # Text conditioning
    pos_id = nf.clip_encode([clip_id, 0], prompt_text, node_id="13")
    neg_id = nf.conditioning_zero_out([pos_id, 0], node_id="14")

    # Encode reference for ReferenceLatent conditioning
    scaled_id = nf.image_scale_to_total_pixels([ref_id, 0], megapixels=1.0,
                                                node_id="15")
    size_id = nf.get_image_size([scaled_id, 0], node_id="16")
    latent_id = nf.vae_encode([scaled_id, 0], [vae_id, 0], node_id="17")

    # ReferenceLatent wrapping
    ref_pos_id = nf.reference_latent([pos_id, 0], [latent_id, 0], node_id="18")
    ref_neg_id = nf.reference_latent([neg_id, 0], [latent_id, 0], node_id="19")

    # Sampling (Flux2Scheduler — full generation from noise)
    guider_id = nf.cfg_guider([unet_id, 0], [ref_pos_id, 0], [ref_neg_id, 0],
                              guidance, node_id="20")
    sampler_id = nf.ksampler_select("euler", node_id="21")
    sched_id = nf.flux2_scheduler(steps, [size_id, 0], [size_id, 1],
                                   node_id="22")
    noise_id = nf.random_noise(seed, node_id="23")
    empty_id = nf.empty_flux2_latent_image([size_id, 0], [size_id, 1],
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

    nf.save_image([restore_id, 0], "photobooth", node_id="60")

    return nf.build()


# ═══════════════════════════════════════════════════════════════════════════
#  Klein Re-poser — ReferenceLatent + BasicScheduler (denoise control)
# ═══════════════════════════════════════════════════════════════════════════

def build_klein_repose(image_filename, klein_model_key, prompt_text, seed,
                       steps=20, denoise=0.65, guidance=1.0,
                       klein_models=None):
    """Klein Re-poser: change character pose using ReferenceLatent + BasicScheduler.

    Same as build_klein_img2img but uses BasicScheduler with denoise instead of
    Flux2Scheduler. This allows partial regeneration (controlled by denoise) while
    keeping ReferenceLatent structural guidance from the input image.
    """
    if klein_models is None:
        klein_models = {
            "Klein 9B": {"unet": "A-Flux\\Flux2\\flux-2-klein-9b.safetensors",
                         "clip": "qwen_3_8b_fp8mixed.safetensors"},
            "Klein 4B": {"unet": "A-Flux\\flux-2-klein-4b-fp8.safetensors",
                         "clip": "qwen_3_4b.safetensors"},
            "Klein Base 4B": {"unet": "A-Flux\\flux-2-klein-base-4b-fp8.safetensors",
                              "clip": "qwen_3_4b.safetensors"},
        }

    km = klein_models[klein_model_key]
    nf = NodeFactory()

    # Model loaders
    unet_id = nf.unet_loader(km["unet"], "default", node_id="1")
    clip_id = nf.clip_loader(
        km.get("clip", "qwen_3_8b_fp8mixed.safetensors"),
        clip_type="flux2", device="default", node_id="2",
    )
    vae_id = nf.vae_loader("flux2-vae.safetensors", node_id="3")

    # Text conditioning
    pos_id = nf.clip_encode([clip_id, 0], prompt_text, node_id="4")
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

    # Sampler setup — BasicScheduler with denoise (unlike Flux2Scheduler)
    guider_id = nf.cfg_guider([unet_id, 0], [ref_pos_id, 0], [ref_neg_id, 0],
                              guidance, node_id="30")
    sampler_id = nf.ksampler_select("euler", node_id="31")
    sched_id = nf.basic_scheduler([unet_id, 0], steps, denoise,
                                   scheduler="simple", node_id="32")
    noise_id = nf.random_noise(seed, node_id="33")
    empty_id = nf.empty_flux2_latent_image([size_id, 0], [size_id, 1],
                                            batch_size=1, node_id="34")

    # Sample
    sample_id = nf.sampler_custom_advanced(
        [noise_id, 0], [guider_id, 0], [sampler_id, 0],
        [sched_id, 0], [empty_id, 0], node_id="40",
    )

    # Decode and save
    dec_id = nf.vae_decode([sample_id, 0], [vae_id, 0], node_id="50")
    nf.save_image([dec_id, 0], "spellcaster_repose", node_id="60")

    return nf.build()


# ═══════════════════════════════════════════════════════════════════════════
#  Klein Blend — AILab_ImageCombiner pre-compositing + Klein ReferenceLatent
# ═══════════════════════════════════════════════════════════════════════════

def build_klein_blend(fg_filename, bg_filename, prompt_text, seed,
                      blend_mode="normal", opacity=1.0, scale=1.0,
                      position_x=0.5, position_y=0.5,
                      klein_model_key="Klein 9B", steps=20, denoise=0.25,
                      guidance=1.0, klein_models=None):
    """Klein Blend: composite foreground onto background, then harmonize with Klein.

    Pipeline: LoadImage(FG) + LoadImage(BG) → AILab_ImageCombiner → Klein
    ReferenceLatent + BasicScheduler (low denoise for subtle integration).
    """
    if klein_models is None:
        klein_models = {
            "Klein 9B": {"unet": "A-Flux\\Flux2\\flux-2-klein-9b.safetensors",
                         "clip": "qwen_3_8b_fp8mixed.safetensors"},
            "Klein 4B": {"unet": "A-Flux\\flux-2-klein-4b-fp8.safetensors",
                         "clip": "qwen_3_4b.safetensors"},
            "Klein Base 4B": {"unet": "A-Flux\\flux-2-klein-base-4b-fp8.safetensors",
                              "clip": "qwen_3_4b.safetensors"},
        }

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
        km.get("clip", "qwen_3_8b_fp8mixed.safetensors"),
        clip_type="flux2", device="default", node_id="11",
    )
    vae_id = nf.vae_loader("flux2-vae.safetensors", node_id="12")

    # Text conditioning
    pos_id = nf.clip_encode([clip_id, 0], prompt_text, node_id="13")
    neg_id = nf.conditioning_zero_out([pos_id, 0], node_id="14")

    # Prepare composited image
    scaled_id = nf.image_scale_to_total_pixels([combine_id, 0], megapixels=1.0,
                                                node_id="15")
    size_id = nf.get_image_size([scaled_id, 0], node_id="16")
    latent_id = nf.vae_encode([scaled_id, 0], [vae_id, 0], node_id="17")

    # ReferenceLatent wrapping
    ref_pos_id = nf.reference_latent([pos_id, 0], [latent_id, 0], node_id="20")
    ref_neg_id = nf.reference_latent([neg_id, 0], [latent_id, 0], node_id="21")

    # Sampler — BasicScheduler with low denoise
    guider_id = nf.cfg_guider([unet_id, 0], [ref_pos_id, 0], [ref_neg_id, 0],
                              guidance, node_id="30")
    sampler_id = nf.ksampler_select("euler", node_id="31")
    sched_id = nf.basic_scheduler([unet_id, 0], steps, denoise,
                                   scheduler="simple", node_id="32")
    noise_id = nf.random_noise(seed, node_id="33")
    empty_id = nf.empty_flux2_latent_image([size_id, 0], [size_id, 1],
                                            batch_size=1, node_id="34")

    sample_id = nf.sampler_custom_advanced(
        [noise_id, 0], [guider_id, 0], [sampler_id, 0],
        [sched_id, 0], [empty_id, 0], node_id="40",
    )

    dec_id = nf.vae_decode([sample_id, 0], [vae_id, 0], node_id="50")
    nf.save_image([dec_id, 0], "spellcaster_blend", node_id="60")

    return nf.build()


# ═══════════════════════════════════════════════════════════════════════════
#  Klein Inpaint — mask-based with FluxGuidance + SetLatentNoiseMask
#                  + optional GrowMask + optional DifferentialDiffusion
# ═══════════════════════════════════════════════════════════════════════════

def build_klein_inpaint(image_filename, mask_filename, prompt_text, seed,
                        klein_model_key="Klein 9B", steps=25, denoise=0.92,
                        guidance=30.0, grow_px=0, use_differential_diffusion=False,
                        use_solid_mask=False, solid_mask_width=1024,
                        solid_mask_height=1024,
                        klein_models=None):
    """Klein Inpaint: regenerate masked area using FluxGuidance + SetLatentNoiseMask.

    Supports two mask sources:
    - Image mask (mask_filename → ImageToMask) — for selection-based inpainting
    - Solid mask (use_solid_mask=True) — for full-image inpainting (clothing store)

    Optional GrowMask expands the mask boundary.
    Optional DifferentialDiffusion enables smooth mask-edge blending.
    """
    if klein_models is None:
        klein_models = {
            "Klein 9B": {"unet": "A-Flux\\Flux2\\flux-2-klein-9b.safetensors",
                         "clip": "qwen_3_8b_fp8mixed.safetensors"},
            "Klein 4B": {"unet": "A-Flux\\flux-2-klein-4b-fp8.safetensors",
                         "clip": "qwen_3_4b.safetensors"},
            "Klein Base 4B": {"unet": "A-Flux\\flux-2-klein-base-4b-fp8.safetensors",
                              "clip": "qwen_3_4b.safetensors"},
        }

    km = klein_models[klein_model_key]
    nf = NodeFactory()

    # Model loaders
    unet_id = nf.unet_loader(km["unet"], "default", node_id="1")
    clip_id = nf.clip_loader(
        km.get("clip", "qwen_3_8b_fp8mixed.safetensors"),
        clip_type="flux2", device="default", node_id="2",
    )
    vae_id = nf.vae_loader("flux2-vae.safetensors", node_id="3")

    # Source image
    img_id = nf.load_image(image_filename, node_id="10")

    # Mask — either from image file or solid
    if use_solid_mask:
        mask_id = nf.solid_mask(value=1.0, width=solid_mask_width,
                                height=solid_mask_height, node_id="12")
        mask_ref = [mask_id, 0]
    else:
        mask_img_id = nf.load_image(mask_filename, node_id="11")
        mask_conv_id = nf.image_to_mask([mask_img_id, 0], "red", node_id="12")
        mask_ref = [mask_conv_id, 0]

    # Optional mask expansion
    if grow_px != 0:
        grow_id = nf.grow_mask(mask_ref, grow_px, tapered_corners=True,
                               node_id="13")
        mask_ref = [grow_id, 0]

    # Image size + text conditioning
    size_id = nf.get_image_size_plus([img_id, 0], node_id="14")
    pos_id = nf.clip_encode([clip_id, 0], prompt_text, node_id="15")
    guided_id = nf.flux_guidance([pos_id, 0], guidance, node_id="16")
    neg_id = nf.conditioning_zero_out([guided_id, 0], node_id="19")

    # VAE encode + SetLatentNoiseMask
    enc_id = nf.vae_encode([img_id, 0], [vae_id, 0], node_id="20")
    masked_latent_id = nf.set_latent_noise_mask([enc_id, 0], mask_ref,
                                                  node_id="21")

    # Optional DifferentialDiffusion
    model_ref = [unet_id, 0]
    if use_differential_diffusion:
        dd_id = nf.differential_diffusion([unet_id, 0], node_id="22")
        model_ref = [dd_id, 0]

    # Sampler
    guider_id = nf.cfg_guider(model_ref, [guided_id, 0], [neg_id, 0],
                              1.0, node_id="30")
    sampler_id = nf.ksampler_select("euler", node_id="31")
    sched_id = nf.basic_scheduler([unet_id, 0], steps, denoise,
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
#  Klein Scene img2img — actual img2img (VAEEncode → latent_image)
#                        NO ReferenceLatent, uses FluxGuidance + BasicScheduler
# ═══════════════════════════════════════════════════════════════════════════

def build_klein_scene_img2img(image_filename, prompt_text, seed,
                               klein_model_key="Klein 9B", steps=20,
                               denoise=0.30, guidance=30.0,
                               klein_models=None):
    """Klein scene img2img: harmonize a composited scene.

    Unlike build_klein_img2img which uses ReferenceLatent (generates from noise
    with reference guidance), this uses actual img2img: VAEEncode → latent_image
    with BasicScheduler denoise. The input image IS the starting latent.

    Used by Studio Set to blend actors into scenes with low denoise.
    """
    if klein_models is None:
        klein_models = {
            "Klein 9B": {"unet": "A-Flux\\Flux2\\flux-2-klein-9b.safetensors",
                         "clip": "qwen_3_8b_fp8mixed.safetensors"},
            "Klein 4B": {"unet": "A-Flux\\flux-2-klein-4b-fp8.safetensors",
                         "clip": "qwen_3_4b.safetensors"},
            "Klein Base 4B": {"unet": "A-Flux\\flux-2-klein-base-4b-fp8.safetensors",
                              "clip": "qwen_3_4b.safetensors"},
        }

    km = klein_models[klein_model_key]
    nf = NodeFactory()

    # Model loaders
    unet_id = nf.unet_loader(km["unet"], "default", node_id="1")
    clip_id = nf.clip_loader(
        km.get("clip", "qwen_3_8b_fp8mixed.safetensors"),
        clip_type="flux2", device="default", node_id="2",
    )
    vae_id = nf.vae_loader("flux2-vae.safetensors", node_id="3")

    # Source images (scene + actor — actor not used in workflow but loaded for context)
    scene_id = nf.load_image(image_filename, node_id="10")

    # Text conditioning with FluxGuidance
    pos_id = nf.clip_encode([clip_id, 0], prompt_text, node_id="15")
    guided_id = nf.flux_guidance([pos_id, 0], guidance, node_id="16")
    neg_id = nf.conditioning_zero_out([guided_id, 0], node_id="17")

    # VAEEncode input → latent (actual img2img, not ReferenceLatent)
    enc_id = nf.vae_encode([scene_id, 0], [vae_id, 0], node_id="20")
    size_id = nf.get_image_size([scene_id, 0], node_id="25")

    # Sampler — BasicScheduler with denoise
    guider_id = nf.cfg_guider([unet_id, 0], [guided_id, 0], [neg_id, 0],
                              1.0, node_id="30")
    sampler_id = nf.ksampler_select("euler", node_id="31")
    sched_id = nf.basic_scheduler([unet_id, 0], steps, denoise,
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
#  Layer Blend — simple two-image blend
# ═══════════════════════════════════════════════════════════════════════════

def build_layer_blend(image_a_filename, image_b_filename, blend_factor=0.5,
                      blend_mode="normal"):
    """Simple layer blend: two images → ImageBlend → SaveImage."""
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
    """Upscale with two models and blend results.

    Pipeline: LoadImage → UpscaleModelA(image) + UpscaleModelB(image)
              → ImageBlend(A_result, B_result, ratio) → SaveImage
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

def build_frame_assembly(frame_filenames, fps=16.0,
                         filename_prefix="gimp_frame_assembly"):
    """Assemble frames into a video via ImageBatch chain → VHS_VideoCombine.

    Handles any number of frames (≥1). Used by Wan Director and GIF Stitcher.
    """
    nf = NodeFactory()

    # Load all frames
    for i, fn in enumerate(frame_filenames):
        nf.load_image(fn, node_id=str(200 + i))

    # ImageBatch chain
    if len(frame_filenames) >= 2:
        batch_id = nf.image_batch([str(200), 0], [str(201), 0], node_id="300")
        batch_ref = [batch_id, 0]
        for i in range(2, len(frame_filenames)):
            nid = str(300 + i - 1)
            batch_id = nf.image_batch(batch_ref, [str(200 + i), 0], node_id=nid)
            batch_ref = [batch_id, 0]
    else:
        batch_ref = [str(200), 0]

    # Video output
    nf.vhs_video_combine(batch_ref, frame_rate=float(fps), loop_count=0,
                          filename_prefix=filename_prefix,
                          format_type="video/h264-mp4", node_id="400")

    return nf.build()
