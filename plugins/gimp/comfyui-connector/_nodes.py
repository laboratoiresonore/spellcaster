"""NodeFactory — Centralised ComfyUI node constructors.

Every ComfyUI node type used by Spellcaster gets exactly ONE constructor here.
When an upstream node changes its API (like the Flux2Scheduler incident), you
fix the single method in this file and all 39+ workflow builders are updated.

Usage:
    nf = NodeFactory()
    ckpt = nf.checkpoint_loader("model.safetensors")
    pos  = nf.clip_encode([ckpt, 1], "a photo of a cat")
    neg  = nf.clip_encode([ckpt, 1], "blurry, ugly")
    # ... etc ...
    workflow = nf.build()

Node IDs are auto-assigned (ascending integers) unless you pass node_id= to
pin a specific ID. This is needed when other parts of the code reference
hardcoded IDs (e.g. ControlNet injection targeting sampler node "6").
"""


class NodeFactory:
    """Builds a ComfyUI workflow dict one node at a time.

    Each method adds a node and returns its string ID.
    References between nodes use [node_id, output_index] lists.
    """

    def __init__(self, start_id=1):
        self._nodes = {}
        self._next_id = start_id

    # ── Internal ──────────────────────────────────────────────────────

    def _add(self, class_type, inputs, node_id=None):
        """Add a node. Returns the string node ID."""
        if node_id is None:
            nid = str(self._next_id)
            self._next_id += 1
        else:
            nid = str(node_id)
            # Keep auto-counter above any explicit ID
            try:
                self._next_id = max(self._next_id, int(nid) + 1)
            except ValueError:
                pass  # non-numeric IDs like "1b" are fine
        self._nodes[nid] = {"class_type": class_type, "inputs": dict(inputs)}
        return nid

    def ref(self, node_id, output=0):
        """Convenience: create a [node_id, output_index] reference."""
        return [str(node_id), output]

    def update(self, extra_nodes):
        """Merge a raw dict of nodes (for legacy interop during migration)."""
        self._nodes.update(extra_nodes)
        for k in extra_nodes:
            try:
                self._next_id = max(self._next_id, int(k) + 1)
            except ValueError:
                pass

    def patch_input(self, node_id, key, value):
        """Modify an existing node's input (e.g. redirect KSampler conditioning)."""
        self._nodes[str(node_id)]["inputs"][key] = value

    def has_node(self, node_id):
        """Check if a node ID exists in the workflow."""
        return str(node_id) in self._nodes

    def build(self):
        """Return the completed workflow dict (node_id → {class_type, inputs})."""
        return dict(self._nodes)

    # ═══════════════════════════════════════════════════════════════════
    #  MODEL LOADERS
    # ═══════════════════════════════════════════════════════════════════

    def checkpoint_loader(self, ckpt_name, node_id=None):
        """CheckpointLoaderSimple — loads model+clip+vae from single file.
        Outputs: [0]=MODEL, [1]=CLIP, [2]=VAE
        """
        return self._add("CheckpointLoaderSimple",
                         {"ckpt_name": ckpt_name}, node_id)

    def unet_loader(self, unet_name, weight_dtype="default", node_id=None):
        """UNETLoader — loads a standalone UNET (Flux, Klein).
        Outputs: [0]=MODEL
        """
        return self._add("UNETLoader",
                         {"unet_name": unet_name,
                          "weight_dtype": weight_dtype}, node_id)

    def unet_loader_gguf(self, unet_name, node_id=None):
        """UnetLoaderGGUF — loads GGUF-quantised UNET.
        Outputs: [0]=MODEL
        """
        return self._add("UnetLoaderGGUF",
                         {"unet_name": unet_name}, node_id)

    def clip_loader(self, clip_name, clip_type="stable_diffusion",
                    device="default", node_id=None):
        """CLIPLoader — loads a single CLIP model.
        Outputs: [0]=CLIP
        """
        return self._add("CLIPLoader",
                         {"clip_name": clip_name, "type": clip_type,
                          "device": device}, node_id)

    def clip_loader_gguf(self, clip_name, clip_type="stable_diffusion",
                         node_id=None):
        """CLIPLoaderGGUF — loads GGUF-quantised CLIP.
        Outputs: [0]=CLIP
        """
        return self._add("CLIPLoaderGGUF",
                         {"clip_name": clip_name, "type": clip_type}, node_id)

    def dual_clip_loader(self, clip_name1, clip_name2, clip_type="flux",
                         node_id=None):
        """DualCLIPLoader — loads two CLIP models (e.g. clip_l + t5xxl for Flux).
        Outputs: [0]=CLIP
        """
        return self._add("DualCLIPLoader",
                         {"clip_name1": clip_name1, "clip_name2": clip_name2,
                          "type": clip_type}, node_id)

    def vae_loader(self, vae_name, node_id=None):
        """VAELoader — loads a standalone VAE.
        Outputs: [0]=VAE
        """
        return self._add("VAELoader", {"vae_name": vae_name}, node_id)

    def lora_loader(self, model_ref, clip_ref, lora_name,
                    strength_model=1.0, strength_clip=1.0, node_id=None):
        """LoraLoader — applies LoRA to both model and CLIP.
        Outputs: [0]=MODEL, [1]=CLIP
        """
        return self._add("LoraLoader", {
            "model": model_ref, "clip": clip_ref,
            "lora_name": lora_name,
            "strength_model": strength_model,
            "strength_clip": strength_clip,
        }, node_id)

    def lora_loader_model_only(self, model_ref, lora_name,
                               strength_model=1.0, node_id=None):
        """LoraLoaderModelOnly — applies LoRA to model only (no CLIP).
        Outputs: [0]=MODEL
        """
        return self._add("LoraLoaderModelOnly", {
            "model": model_ref,
            "lora_name": lora_name,
            "strength_model": strength_model,
        }, node_id)

    def upscale_model_loader(self, model_name, node_id=None):
        """UpscaleModelLoader — loads a super-resolution model (RealESRGAN etc).
        Outputs: [0]=UPSCALE_MODEL
        """
        return self._add("UpscaleModelLoader",
                         {"model_name": model_name}, node_id)

    # ═══════════════════════════════════════════════════════════════════
    #  CONDITIONING / CLIP
    # ═══════════════════════════════════════════════════════════════════

    def clip_encode(self, clip_ref, text, node_id=None):
        """CLIPTextEncode — encode text prompt into conditioning.
        Outputs: [0]=CONDITIONING
        """
        return self._add("CLIPTextEncode",
                         {"clip": clip_ref, "text": text}, node_id)

    def conditioning_zero_out(self, conditioning_ref, node_id=None):
        """ConditioningZeroOut — create empty/null conditioning (Flux negative).
        Outputs: [0]=CONDITIONING
        """
        return self._add("ConditioningZeroOut",
                         {"conditioning": conditioning_ref}, node_id)

    def flux_guidance(self, conditioning_ref, guidance, node_id=None):
        """FluxGuidance — apply guidance scale to Flux conditioning.
        Outputs: [0]=CONDITIONING
        """
        return self._add("FluxGuidance",
                         {"conditioning": conditioning_ref,
                          "guidance": guidance}, node_id)

    def clip_vision_loader(self, clip_name, node_id=None):
        """CLIPVisionLoader.
        Outputs: [0]=CLIP_VISION
        """
        return self._add("CLIPVisionLoader",
                         {"clip_name": clip_name}, node_id)

    def clip_vision_encode(self, clip_vision_ref, image_ref, node_id=None):
        """CLIPVisionEncode.
        Outputs: [0]=CLIP_VISION_OUTPUT
        """
        return self._add("CLIPVisionEncode",
                         {"clip_vision": clip_vision_ref,
                          "image": image_ref}, node_id)

    # ═══════════════════════════════════════════════════════════════════
    #  SAMPLING
    # ═══════════════════════════════════════════════════════════════════

    def ksampler(self, model_ref, positive_ref, negative_ref, latent_ref,
                 seed, steps, cfg, sampler_name, scheduler, denoise,
                 node_id=None):
        """KSampler — standard diffusion sampler.
        Outputs: [0]=LATENT
        """
        return self._add("KSampler", {
            "model": model_ref,
            "positive": positive_ref,
            "negative": negative_ref,
            "latent_image": latent_ref,
            "seed": seed,
            "steps": steps,
            "cfg": cfg,
            "sampler_name": sampler_name,
            "scheduler": scheduler,
            "denoise": denoise,
        }, node_id)

    def ksampler_advanced(self, model_ref, positive_ref, negative_ref,
                          latent_ref, noise_seed, steps, cfg, sampler_name,
                          scheduler, start_at_step=0, end_at_step=10000,
                          add_noise="enable", return_with_leftover_noise="disable",
                          node_id=None):
        """KSamplerAdvanced — sampler with step range and noise control.
        Outputs: [0]=LATENT
        """
        return self._add("KSamplerAdvanced", {
            "model": model_ref,
            "positive": positive_ref,
            "negative": negative_ref,
            "latent_image": latent_ref,
            "noise_seed": noise_seed,
            "steps": steps,
            "cfg": cfg,
            "sampler_name": sampler_name,
            "scheduler": scheduler,
            "start_at_step": start_at_step,
            "end_at_step": end_at_step,
            "add_noise": add_noise,
            "return_with_leftover_noise": return_with_leftover_noise,
        }, node_id)

    def ksampler_select(self, sampler_name="euler", node_id=None):
        """KSamplerSelect — select sampler by name (for SamplerCustomAdvanced).
        Outputs: [0]=SAMPLER
        """
        return self._add("KSamplerSelect",
                         {"sampler_name": sampler_name}, node_id)

    def cfg_guider(self, model_ref, positive_ref, negative_ref, cfg,
                   node_id=None):
        """CFGGuider — wraps model + conditioning for SamplerCustomAdvanced.
        Outputs: [0]=GUIDER
        """
        return self._add("CFGGuider", {
            "model": model_ref,
            "positive": positive_ref,
            "negative": negative_ref,
            "cfg": cfg,
        }, node_id)

    def sampler_custom_advanced(self, noise_ref, guider_ref, sampler_ref,
                                sigmas_ref, latent_ref, node_id=None):
        """SamplerCustomAdvanced — Flux2/Klein sampling pipeline.
        Outputs: [0]=LATENT (output), [1]=LATENT (denoised_output)
        """
        return self._add("SamplerCustomAdvanced", {
            "noise": noise_ref,
            "guider": guider_ref,
            "sampler": sampler_ref,
            "sigmas": sigmas_ref,
            "latent_image": latent_ref,
        }, node_id)

    def random_noise(self, seed, node_id=None):
        """RandomNoise — generate a noise tensor from seed.
        Outputs: [0]=NOISE
        """
        return self._add("RandomNoise", {"noise_seed": seed}, node_id)

    def flux2_scheduler(self, steps, width_ref, height_ref, node_id=None):
        """Flux2Scheduler — NEW API (steps, width, height only).

        *** BREAKING CHANGE (April 2026): removed model, denoise, max_shift, base_shift ***
        For img2img with denoise, use basic_scheduler() instead.

        Outputs: [0]=SIGMAS
        """
        return self._add("Flux2Scheduler", {
            "steps": steps,
            "width": width_ref,
            "height": height_ref,
        }, node_id)

    def basic_scheduler(self, model_ref, steps, denoise,
                        scheduler="simple", node_id=None):
        """BasicScheduler — general-purpose scheduler with denoise support.
        Use this for Flux2 img2img where Flux2Scheduler can't do denoise.

        Outputs: [0]=SIGMAS
        """
        return self._add("BasicScheduler", {
            "model": model_ref,
            "scheduler": scheduler,
            "steps": steps,
            "denoise": denoise,
        }, node_id)

    def model_sampling_sd3(self, model_ref, shift, node_id=None):
        """ModelSamplingSD3 — shift noise schedule (used for some Flux variants).
        Outputs: [0]=MODEL
        """
        return self._add("ModelSamplingSD3",
                         {"model": model_ref, "shift": shift}, node_id)

    # ═══════════════════════════════════════════════════════════════════
    #  LATENT OPERATIONS
    # ═══════════════════════════════════════════════════════════════════

    def empty_latent_image(self, width, height, batch_size=1, node_id=None):
        """EmptyLatentImage — blank latent for txt2img.
        Outputs: [0]=LATENT
        """
        return self._add("EmptyLatentImage", {
            "width": width, "height": height, "batch_size": batch_size,
        }, node_id)

    def empty_flux2_latent_image(self, width_ref, height_ref, batch_size=1,
                                 node_id=None):
        """EmptyFlux2LatentImage — blank latent for Flux2 txt2img.
        Accepts refs (from GetImageSize) for dynamic sizing.
        Outputs: [0]=LATENT
        """
        return self._add("EmptyFlux2LatentImage", {
            "width": width_ref, "height": height_ref,
            "batch_size": batch_size,
        }, node_id)

    def reference_latent(self, conditioning_ref, latent_ref=None, node_id=None):
        """ReferenceLatent — wrap conditioning with reference image latent (Klein).
        latent_ref is optional (backward compatible).
        Outputs: [0]=CONDITIONING
        """
        inputs = {"conditioning": conditioning_ref}
        if latent_ref is not None:
            inputs["latent"] = latent_ref
        return self._add("ReferenceLatent", inputs, node_id)

    def set_latent_noise_mask(self, latent_ref, mask_ref, node_id=None):
        """SetLatentNoiseMask — apply inpainting mask to latent.
        Outputs: [0]=LATENT
        """
        return self._add("SetLatentNoiseMask", {
            "samples": latent_ref, "mask": mask_ref,
        }, node_id)

    def vae_encode(self, pixels_ref, vae_ref, node_id=None):
        """VAEEncode — image pixels → latent space.
        Outputs: [0]=LATENT
        """
        return self._add("VAEEncode", {
            "pixels": pixels_ref, "vae": vae_ref,
        }, node_id)

    def vae_decode(self, samples_ref, vae_ref, node_id=None):
        """VAEDecode — latent space → image pixels.
        Outputs: [0]=IMAGE
        """
        return self._add("VAEDecode", {
            "samples": samples_ref, "vae": vae_ref,
        }, node_id)

    def vae_decode_tiled(self, samples_ref, vae_ref, tile_size=512,
                         node_id=None):
        """VAEDecodeTiled — tiled decode for large images.
        Outputs: [0]=IMAGE
        """
        return self._add("VAEDecodeTiled", {
            "samples": samples_ref, "vae": vae_ref,
            "tile_size": tile_size,
        }, node_id)

    # ═══════════════════════════════════════════════════════════════════
    #  IMAGE I/O & PROCESSING
    # ═══════════════════════════════════════════════════════════════════

    def load_image(self, filename, node_id=None):
        """LoadImage — load image from ComfyUI input directory.
        Outputs: [0]=IMAGE, [1]=MASK (alpha channel)
        """
        return self._add("LoadImage", {"image": filename}, node_id)

    def save_image(self, images_ref, prefix="gimp_comfy", node_id=None):
        """SaveImage — save image to ComfyUI output directory.
        Outputs: (none — terminal node)
        """
        return self._add("SaveImage", {
            "images": images_ref, "filename_prefix": prefix,
        }, node_id)

    def image_scale(self, image_ref, width, height,
                    upscale_method="lanczos", crop="disabled", node_id=None):
        """ImageScale — resize image to exact dimensions.
        Outputs: [0]=IMAGE
        """
        return self._add("ImageScale", {
            "image": image_ref,
            "width": width, "height": height,
            "upscale_method": upscale_method, "crop": crop,
        }, node_id)

    def image_scale_to_total_pixels(self, image_ref, megapixels=1.0,
                                     upscale_method="nearest-exact",
                                     resolution_steps=1, node_id=None):
        """ImageScaleToTotalPixels — scale to target megapixel count.
        Outputs: [0]=IMAGE
        """
        return self._add("ImageScaleToTotalPixels", {
            "image": image_ref,
            "upscale_method": upscale_method,
            "megapixels": megapixels,
            "resolution_steps": resolution_steps,
        }, node_id)

    def image_upscale_with_model_by_factor(self, upscale_model_ref,
                                            image_ref, scale_by,
                                            node_id=None):
        """ImageUpscaleWithModelByFactor — model-based upscale at given factor.
        Outputs: [0]=IMAGE
        """
        return self._add("ImageUpscaleWithModelByFactor", {
            "upscale_model": upscale_model_ref,
            "image": image_ref,
            "scale_by": scale_by,
        }, node_id)

    def image_sharpen(self, image_ref, sharpen_radius=1, sigma=1.0,
                      alpha=1.0, node_id=None):
        """ImageSharpen.
        Outputs: [0]=IMAGE
        """
        return self._add("ImageSharpen", {
            "image": image_ref,
            "sharpen_radius": sharpen_radius,
            "sigma": sigma,
            "alpha": alpha,
        }, node_id)

    def image_blend(self, image1_ref, image2_ref, blend_factor=0.5,
                    blend_mode="normal", node_id=None):
        """ImageBlend — blend two images.
        Outputs: [0]=IMAGE
        """
        return self._add("ImageBlend", {
            "image1": image1_ref, "image2": image2_ref,
            "blend_factor": blend_factor, "blend_mode": blend_mode,
        }, node_id)

    def image_batch(self, image1_ref, image2_ref, node_id=None):
        """ImageBatch — concatenate images into a batch.
        Outputs: [0]=IMAGE
        """
        return self._add("ImageBatch", {
            "image1": image1_ref, "image2": image2_ref,
        }, node_id)

    def image_from_batch(self, image_ref, batch_index=0, length=1,
                         node_id=None):
        """ImageFromBatch+ — extract frame(s) from a batch.
        Outputs: [0]=IMAGE
        """
        return self._add("ImageFromBatch+", {
            "image": image_ref,
            "batch_index": batch_index,
            "length": length,
        }, node_id)

    def image_pad_for_outpaint(self, image_ref, left, top, right, bottom,
                                feathering, node_id=None):
        """ImagePadForOutpaint — pad image and generate outpaint mask.
        Outputs: [0]=IMAGE (padded), [1]=MASK (outpaint area)
        """
        return self._add("ImagePadForOutpaint", {
            "image": image_ref,
            "left": left, "top": top, "right": right, "bottom": bottom,
            "feathering": feathering,
        }, node_id)

    def get_image_size(self, image_ref, node_id=None):
        """GetImageSize — returns width, height.
        Outputs: [0]=INT (width), [1]=INT (height)
        """
        return self._add("GetImageSize",
                         {"image": image_ref}, node_id)

    def get_image_size_plus(self, image_ref, node_id=None):
        """GetImageSize+ — enhanced size getter.
        Outputs: [0]=INT (width), [1]=INT (height)
        """
        return self._add("GetImageSize+",
                         {"image": image_ref}, node_id)

    def image_to_mask(self, image_ref, channel="red", node_id=None):
        """ImageToMask — convert image channel to mask tensor.
        Outputs: [0]=MASK
        """
        return self._add("ImageToMask", {
            "image": image_ref, "channel": channel,
        }, node_id)

    def grow_mask(self, mask_ref, expand, tapered_corners=True, node_id=None):
        """GrowMask — expand or contract a mask.
        Outputs: [0]=MASK
        """
        return self._add("GrowMask", {
            "mask": mask_ref, "expand": expand,
            "tapered_corners": tapered_corners,
        }, node_id)

    def solid_mask(self, value=1.0, width=512, height=512, node_id=None):
        """SolidMask — create a uniform mask.
        Outputs: [0]=MASK
        """
        return self._add("SolidMask", {
            "value": value, "width": width, "height": height,
        }, node_id)

    def image_apply_lut(self, image_ref, lut_file, strength=1.0,
                        log=False, clip_values=True, gamma_correction=False,
                        node_id=None):
        """ImageApplyLUT+ — apply a 3D color LUT.
        Outputs: [0]=IMAGE
        """
        return self._add("ImageApplyLUT+", {
            "image": image_ref,
            "lut_file": lut_file,
            "strength": strength,
            "log": log,
            "clip_values": clip_values,
            "gamma_correction": gamma_correction,
        }, node_id)

    def image_combiner(self, images, node_id=None):
        """AILab_ImageCombiner — combine multiple images.
        Outputs: [0]=IMAGE
        """
        return self._add("AILab_ImageCombiner",
                         {"images": images}, node_id)

    # ═══════════════════════════════════════════════════════════════════
    #  CONTROLNET
    # ═══════════════════════════════════════════════════════════════════

    def controlnet_loader(self, control_net_name, node_id=None):
        """ControlNetLoader.
        Outputs: [0]=CONTROL_NET
        """
        return self._add("ControlNetLoader",
                         {"control_net_name": control_net_name}, node_id)

    def controlnet_apply_advanced(self, positive_ref, negative_ref,
                                   control_net_ref, image_ref, strength,
                                   start_percent=0.0, end_percent=1.0,
                                   node_id=None):
        """ControlNetApplyAdvanced — apply ControlNet to conditioning.
        Outputs: [0]=CONDITIONING (positive), [1]=CONDITIONING (negative)
        """
        return self._add("ControlNetApplyAdvanced", {
            "positive": positive_ref,
            "negative": negative_ref,
            "control_net": control_net_ref,
            "image": image_ref,
            "strength": strength,
            "start_percent": start_percent,
            "end_percent": end_percent,
        }, node_id)

    def preprocessor(self, class_type, image_ref, node_id=None, **kwargs):
        """Generic preprocessor (LineArtPreprocessor, CannyEdgePreprocessor, etc).
        Outputs: [0]=IMAGE (preprocessed)
        """
        inputs = {"image": image_ref}
        inputs.update(kwargs)
        return self._add(class_type, inputs, node_id)

    def differential_diffusion(self, model_ref, node_id=None):
        """DifferentialDiffusion — enable differential diffusion on model.
        Outputs: [0]=MODEL
        """
        return self._add("DifferentialDiffusion",
                         {"model": model_ref}, node_id)

    # ═══════════════════════════════════════════════════════════════════
    #  FACE SWAP (ReActor)
    # ═══════════════════════════════════════════════════════════════════

    def reactor_face_swap_opt(self, input_image_ref, source_image_ref=None,
                               swap_model="inswapper_128.onnx",
                               face_restore_model="codeformer-v0.1.0.pth",
                               face_restore_visibility=1.0,
                               codeformer_weight=0.7,
                               options_ref=None, face_boost_ref=None,
                               face_model_ref=None,
                               node_id=None):
        """ReActorFaceSwapOpt — face swap with optional quality pipeline.

        Uses either source_image_ref (source image) or face_model_ref (saved model).
        """
        inputs = {
            "enabled": True,
            "input_image": input_image_ref,
            "swap_model": swap_model,
            "facedetection": "retinaface_resnet50",
            "face_restore_model": face_restore_model,
            "face_restore_visibility": face_restore_visibility,
            "codeformer_weight": codeformer_weight,
        }
        if source_image_ref is not None:
            inputs["source_image"] = source_image_ref
        if face_model_ref is not None:
            inputs["face_model"] = face_model_ref
        if options_ref is not None:
            inputs["options"] = options_ref
        if face_boost_ref is not None:
            inputs["face_boost"] = face_boost_ref
        return self._add("ReActorFaceSwapOpt", inputs, node_id)

    def reactor_options(self, input_faces_order="left-right",
                        input_faces_index="0",
                        detect_gender_input="no",
                        source_faces_order="left-right",
                        source_faces_index="0",
                        detect_gender_source="no",
                        console_log_level=1,
                        node_id=None):
        """ReActorOptions — face ordering and restore configuration."""
        return self._add("ReActorOptions", {
            "input_faces_order": input_faces_order,
            "input_faces_index": input_faces_index,
            "detect_gender_input": detect_gender_input,
            "source_faces_order": source_faces_order,
            "source_faces_index": source_faces_index,
            "detect_gender_source": detect_gender_source,
            "console_log_level": console_log_level,
            "restore_swapped_only": True,
        }, node_id)

    def reactor_face_boost(self, enabled=True, boost_model="GFPGANv1.4.pth",
                           interpolation="Bicubic", visibility=1.0,
                           codeformer_weight=0.7,
                           restore_with_main_after=False, node_id=None):
        """ReActorFaceBoost — additional face enhancement pass."""
        return self._add("ReActorFaceBoost", {
            "enabled": enabled,
            "boost_model": boost_model,
            "interpolation": interpolation,
            "visibility": visibility,
            "codeformer_weight": codeformer_weight,
            "restore_with_main_after": restore_with_main_after,
        }, node_id)

    def reactor_load_face_model(self, face_model, node_id=None):
        """ReActorLoadFaceModel — load a saved face model."""
        return self._add("ReActorLoadFaceModel",
                         {"face_model": face_model}, node_id)

    def reactor_build_face_model(self, image_ref, face_index=0,
                                  compute_method="CPU", node_id=None):
        """ReActorBuildFaceModel — extract face embedding from image."""
        return self._add("ReActorBuildFaceModel", {
            "images": image_ref, "face_index": face_index,
            "compute_method": compute_method,
        }, node_id)

    def reactor_save_face_model(self, face_model_ref, save_mode="overwrite",
                                face_model_name="face_model", node_id=None):
        """ReActorSaveFaceModel — save face model to disk.

        save_mode: "overwrite" or "new" (add numeric suffix).
        """
        mode = save_mode if isinstance(save_mode, str) else ("overwrite" if save_mode else "new")
        return self._add("ReActorSaveFaceModel", {
            "face_model": face_model_ref,
            "save_mode": mode,
            "face_model_name": face_model_name,
        }, node_id)

    def reactor_restore_face(self, image_ref,
                             facedetection="retinaface_resnet50",
                             model="codeformer-v0.1.0.pth",
                             visibility=1.0, codeformer_weight=0.5,
                             node_id=None):
        """ReActorRestoreFace — standalone face restoration."""
        return self._add("ReActorRestoreFace", {
            "image": image_ref,
            "facedetection": facedetection,
            "model": model,
            "visibility": visibility,
            "codeformer_weight": codeformer_weight,
        }, node_id)

    # ── MTB Face Swap ──

    def mtb_load_face_analysis(self, faceswap_model="buffalo_l", node_id=None):
        """Load Face Analysis Model (mtb)."""
        return self._add("Load Face Analysis Model (mtb)",
                         {"faceswap_model": faceswap_model}, node_id)

    def mtb_load_face_swap(self, faceswap_model="inswapper_128.onnx",
                           node_id=None):
        """Load Face Swap Model (mtb)."""
        return self._add("Load Face Swap Model (mtb)",
                         {"faceswap_model": faceswap_model}, node_id)

    def mtb_face_swap(self, image_ref, reference_ref, analysis_ref, swap_ref,
                      faces_index="0", node_id=None):
        """Face Swap (mtb) — execute the swap."""
        return self._add("Face Swap (mtb)", {
            "image": image_ref, "reference": reference_ref,
            "faces_index": faces_index,
            "faceanalysis_model": analysis_ref,
            "faceswap_model": swap_ref,
        }, node_id)

    # ═══════════════════════════════════════════════════════════════════
    #  IPADAPTER / FACEID / PULID
    # ═══════════════════════════════════════════════════════════════════

    def ipadapter_unified_loader(self, model_ref, preset="PLUS (high strength)",
                                  node_id=None):
        """IPAdapterUnifiedLoader."""
        return self._add("IPAdapterUnifiedLoader", {
            "model": model_ref, "preset": preset,
        }, node_id)

    def ipadapter_unified_loader_faceid(self, model_ref,
                                         preset="FACEID PLUS V2",
                                         lora_strength=0.6,
                                         provider="CUDA",
                                         node_id=None):
        """IPAdapterUnifiedLoaderFaceID."""
        return self._add("IPAdapterUnifiedLoaderFaceID", {
            "model": model_ref, "preset": preset,
            "lora_strength": lora_strength,
            "provider": provider,
        }, node_id)

    def ipadapter_advanced(self, model_ref, ipadapter_ref, image_ref,
                           weight=1.0, weight_type="linear",
                           start_at=0.0, end_at=1.0,
                           node_id=None):
        """IPAdapterAdvanced — apply IPAdapter with strength control."""
        return self._add("IPAdapterAdvanced", {
            "model": model_ref, "ipadapter": ipadapter_ref,
            "image": image_ref, "weight": weight,
            "weight_type": weight_type,
            "start_at": start_at, "end_at": end_at,
        }, node_id)

    def ipadapter_faceid(self, model_ref, ipadapter_ref, image_ref,
                         weight=0.85, weight_faceidv2=1.0,
                         weight_type="linear", combine_embeds="concat",
                         start_at=0.0, end_at=1.0,
                         embeds_scaling="V only",
                         node_id=None):
        """IPAdapterFaceID — face identity transfer."""
        return self._add("IPAdapterFaceID", {
            "model": model_ref, "ipadapter": ipadapter_ref,
            "image": image_ref, "weight": weight,
            "weight_faceidv2": weight_faceidv2,
            "weight_type": weight_type,
            "combine_embeds": combine_embeds,
            "start_at": start_at, "end_at": end_at,
            "embeds_scaling": embeds_scaling,
        }, node_id)

    def pulid_flux_model_loader(self, pulid_file="pulid_flux_v0.9.1.safetensors",
                                 node_id=None):
        """PulidFluxModelLoader — for Flux1 PuLID."""
        return self._add("PulidFluxModelLoader", {
            "pulid_file": pulid_file,
        }, node_id)

    def pulid_flux_insightface_loader(self, provider="CPU", node_id=None):
        """PulidFluxInsightFaceLoader."""
        return self._add("PulidFluxInsightFaceLoader",
                         {"provider": provider}, node_id)

    def pulid_flux_eva_clip_loader(self, node_id=None):
        """PulidFluxEvaClipLoader."""
        return self._add("PulidFluxEvaClipLoader", {}, node_id)

    def apply_pulid_flux(self, model_ref, pulid_flux_ref, eva_clip_ref,
                          face_analysis_ref, image_ref,
                          weight=1.0, start_at=0.0, end_at=1.0,
                          node_id=None):
        """ApplyPulidFlux — apply PuLID face transfer to Flux1 model."""
        return self._add("ApplyPulidFlux", {
            "model": model_ref, "pulid_flux": pulid_flux_ref,
            "eva_clip": eva_clip_ref, "face_analysis": face_analysis_ref,
            "image": image_ref, "weight": weight,
            "start_at": start_at, "end_at": end_at,
        }, node_id)

    def apply_pulid_flux2(self, model_ref, pulid_model_ref, eva_clip_ref,
                          face_analysis_ref, image_ref,
                          strength=1.0, node_id=None):
        """ApplyPuLIDFlux2 — apply PuLID face transfer to Flux2 model."""
        return self._add("ApplyPuLIDFlux2", {
            "model": model_ref, "pulid_model": pulid_model_ref,
            "strength": strength,
            "eva_clip": eva_clip_ref, "face_analysis": face_analysis_ref,
            "image": image_ref,
        }, node_id)

    def pulid_model_loader(self, pulid_file, node_id=None):
        """PuLIDModelLoader — for Flux2 PuLID."""
        return self._add("PuLIDModelLoader", {
            "pulid_file": pulid_file,
        }, node_id)

    def pulid_eva_clip_loader(self, node_id=None):
        """PuLIDEVACLIPLoader — for Flux2 PuLID."""
        return self._add("PuLIDEVACLIPLoader", {}, node_id)

    def pulid_insightface_loader(self, provider="CUDA", node_id=None):
        """PuLIDInsightFaceLoader — for Flux2 PuLID."""
        return self._add("PuLIDInsightFaceLoader", {
            "provider": provider,
        }, node_id)

    # ═══════════════════════════════════════════════════════════════════
    #  BACKGROUND REMOVAL / INPAINTING
    # ═══════════════════════════════════════════════════════════════════

    def rembg(self, images_ref, model="isnet-general-use",
              transparency=True, alpha_matting=False, node_id=None):
        """Image Rembg (Remove Background)."""
        return self._add("Image Rembg (Remove Background)", {
            "images": images_ref,
            "transparency": transparency,
            "model": model,
            "post_processing": False,
            "only_mask": False,
            "alpha_matting": alpha_matting,
            "alpha_matting_foreground_threshold": 240,
            "alpha_matting_background_threshold": 10,
            "alpha_matting_erode_size": 10,
            "background_color": "none",
        }, node_id)

    def lama_remover(self, images_ref, masks_ref, mask_threshold=0.5,
                     gaussblur_radius=8, invert_mask=False, node_id=None):
        """LamaRemover — LaMa inpainting without diffusion."""
        return self._add("LamaRemover", {
            "images": images_ref,
            "masks": masks_ref,
            "mask_threshold": mask_threshold,
            "gaussblur_radius": gaussblur_radius,
            "invert_mask": invert_mask,
        }, node_id)

    # ═══════════════════════════════════════════════════════════════════
    #  IC-LIGHT / SUPIR
    # ═══════════════════════════════════════════════════════════════════

    def supir_model_loader(self, supir_model, sdxl_model, fp8_unet=False,
                            diffusion_dtype="auto", node_id=None):
        """SUPIR_model_loader — loads SUPIR weights + SDXL backbone."""
        return self._add("SUPIR_model_loader", {
            "supir_model": supir_model, "sdxl_model": sdxl_model,
            "fp8_unet": fp8_unet, "diffusion_dtype": diffusion_dtype,
        }, node_id)

    def supir_first_stage(self, supir_vae_ref, image_ref,
                           use_tiled_vae=True, encoder_tile_size=512,
                           decoder_tile_size=64, encoder_dtype="auto",
                           node_id=None):
        """SUPIR_first_stage — stage-1 denoising (pre-clean)."""
        return self._add("SUPIR_first_stage", {
            "SUPIR_VAE": supir_vae_ref, "image": image_ref,
            "use_tiled_vae": use_tiled_vae,
            "encoder_tile_size": encoder_tile_size,
            "decoder_tile_size": decoder_tile_size,
            "encoder_dtype": encoder_dtype,
        }, node_id)

    def supir_conditioner(self, supir_model_ref, latents_ref,
                           positive_prompt, negative_prompt, node_id=None):
        """SUPIR_conditioner — builds conditioning from prompts."""
        return self._add("SUPIR_conditioner", {
            "SUPIR_model": supir_model_ref, "latents": latents_ref,
            "positive_prompt": positive_prompt,
            "negative_prompt": negative_prompt,
        }, node_id)

    def supir_sample(self, supir_model_ref, latents_ref, positive_ref,
                      negative_ref, seed, steps,
                      cfg_scale_start=4.0, cfg_scale_end=2.0,
                      edm_s_churn=5, s_noise=1.003, dpmpp_eta=1.0,
                      control_scale_start=0.5, control_scale_end=1.0,
                      restore_cfg=-1.0, keep_model_loaded=False,
                      sampler="RestoreEDMSampler", node_id=None):
        """SUPIR_sample — main restoration sampling."""
        return self._add("SUPIR_sample", {
            "SUPIR_model": supir_model_ref, "latents": latents_ref,
            "positive": positive_ref, "negative": negative_ref,
            "seed": seed, "steps": steps,
            "cfg_scale_start": cfg_scale_start, "cfg_scale_end": cfg_scale_end,
            "EDM_s_churn": edm_s_churn, "s_noise": s_noise,
            "DPMPP_eta": dpmpp_eta,
            "control_scale_start": control_scale_start,
            "control_scale_end": control_scale_end,
            "restore_cfg": restore_cfg,
            "keep_model_loaded": keep_model_loaded,
            "sampler": sampler,
        }, node_id)

    def supir_decode(self, supir_vae_ref, latents_ref,
                      use_tiled_vae=True, decoder_tile_size=64,
                      node_id=None):
        """SUPIR_decode — tiled VAE decode."""
        return self._add("SUPIR_decode", {
            "SUPIR_VAE": supir_vae_ref, "latents": latents_ref,
            "use_tiled_vae": use_tiled_vae,
            "decoder_tile_size": decoder_tile_size,
        }, node_id)

    def load_and_apply_iclight_unet(self, model_ref, iclight_file, node_id=None):
        """LoadAndApplyICLightUnet."""
        return self._add("LoadAndApplyICLightUnet", {
            "model": model_ref,
            "model_path": iclight_file,
        }, node_id)

    def iclight_conditioning(self, positive_ref, negative_ref, vae_ref,
                              foreground_ref, multiplier=0.18, node_id=None):
        """ICLightConditioning."""
        return self._add("ICLightConditioning", {
            "positive": positive_ref, "negative": negative_ref,
            "vae": vae_ref, "foreground": foreground_ref,
            "multiplier": multiplier,
        }, node_id)

    # ═══════════════════════════════════════════════════════════════════
    #  VIDEO (Wan, VHS, RIFE)
    # ═══════════════════════════════════════════════════════════════════

    def wan_image_to_video(self, positive_ref, negative_ref, vae_ref,
                           image_ref, model_ref, width, height, length,
                           seed, steps, cfg, node_id=None):
        """WanImageToVideo."""
        return self._add("WanImageToVideo", {
            "positive": positive_ref, "negative": negative_ref,
            "vae": vae_ref, "clip_vision_output": image_ref,
            "model": model_ref,
            "width": width, "height": height, "length": length,
            "seed": seed, "steps": steps, "cfg": cfg,
        }, node_id)

    def wan_first_last_frame(self, positive_ref, negative_ref, vae_ref,
                              start_image_ref, end_image_ref, model_ref,
                              width, height, length, seed, steps, cfg,
                              node_id=None):
        """WanFirstLastFrameToVideo."""
        return self._add("WanFirstLastFrameToVideo", {
            "positive": positive_ref, "negative": negative_ref,
            "vae": vae_ref,
            "start_image": start_image_ref, "end_image": end_image_ref,
            "model": model_ref,
            "width": width, "height": height, "length": length,
            "seed": seed, "steps": steps, "cfg": cfg,
        }, node_id)

    def vhs_video_combine(self, images_ref, frame_rate=24, loop_count=0,
                           filename_prefix="spellcaster",
                           format_type="video/h264-mp4",
                           node_id=None):
        """VHS_VideoCombine — combine frames into video."""
        return self._add("VHS_VideoCombine", {
            "images": images_ref,
            "frame_rate": frame_rate,
            "loop_count": loop_count,
            "filename_prefix": filename_prefix,
            "format": format_type,
        }, node_id)

    def rife_vfi(self, frames_ref, multiplier=2, node_id=None):
        """RIFE VFI — frame interpolation."""
        return self._add("RIFE VFI", {
            "frames": frames_ref,
            "multiplier": multiplier,
            "ckpt_name": "rife49.pth",
            "clear_cache_after_n_frames": 10,
            "fast_mode": True,
            "ensemble": True,
            "scale_factor": 1.0,
        }, node_id)

    # ═══════════════════════════════════════════════════════════════════
    #  TAGGING / TEXT
    # ═══════════════════════════════════════════════════════════════════

    def wd14_tagger(self, image_ref, model="wd-v1-4-moat-tagger-v2",
                    threshold=0.35, node_id=None):
        """WD14Tagger|pysssss — auto-tag image content."""
        return self._add("WD14Tagger|pysssss", {
            "image": image_ref, "model": model,
            "threshold": threshold,
            "character_threshold": 0.85,
            "replace_underscore": True,
            "trailing_comma": False,
            "exclude_tags": "",
        }, node_id)

    def show_text(self, text_ref, node_id=None):
        """ShowText|pysssss — display text (debug)."""
        return self._add("ShowText|pysssss", {"text": text_ref}, node_id)

    # ═══════════════════════════════════════════════════════════════════
    #  ACCELERATION
    # ═══════════════════════════════════════════════════════════════════

    def apply_tea_cache_patch(self, model_ref, rel_l1_thresh=0.4,
                              cache_device="main_device", node_id=None):
        """ApplyTeaCachePatch — TeaCache acceleration for Wan video."""
        return self._add("ApplyTeaCachePatch", {
            "model": model_ref,
            "rel_l1_thresh": rel_l1_thresh,
            "cache_device": cache_device,
        }, node_id)

    # ═══════════════════════════════════════════════════════════════════
    #  VIDEO UPSCALE
    # ═══════════════════════════════════════════════════════════════════

    def rtx_video_super_resolution(self, images_ref, scale_factor=2,
                                    node_id=None):
        """RTXVideoSuperResolution."""
        return self._add("RTXVideoSuperResolution", {
            "images": images_ref, "scale_factor": scale_factor,
        }, node_id)

    def seedvr2_video_upscaler(self, images_ref, node_id=None):
        """SeedVR2VideoUpscaler."""
        return self._add("SeedVR2VideoUpscaler",
                         {"images": images_ref}, node_id)

    def ts_video_upscale(self, upscale_model_ref, images_ref, node_id=None):
        """TS_Video_Upscale_With_Model."""
        return self._add("TS_Video_Upscale_With_Model", {
            "upscale_model": upscale_model_ref,
            "images": images_ref,
        }, node_id)
