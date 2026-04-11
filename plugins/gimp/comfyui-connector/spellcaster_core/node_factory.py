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
    """Centralised factory for constructing ComfyUI workflow nodes.

    The NodeFactory pattern consolidates all node construction logic into a
    single place, ensuring that when a ComfyUI node API changes (e.g. Flux2Scheduler
    parameter removal), the fix happens in exactly one method that all 39+ workflow
    builders depend on.

    ARCHITECTURE:
      Every method constructs one node dict and returns its auto-assigned or
      manually-pinned ID (string). Each node dict follows ComfyUI's format:
        { "class_type": "NodeClassName", "inputs": {...} }

    NODE REFERENCES:
      References between nodes use the [node_id, output_slot] list pattern:
        model_ref = [ckpt_id, 0]  # Output slot 0 from ckpt loader
        clip_ref = [ckpt_id, 1]   # Output slot 1 (CLIP) from ckpt loader

      This pattern is consistent throughout ComfyUI and critical for downstream
      node wiring. When a method says "Outputs: [0]=MODEL, [1]=CLIP, [2]=VAE",
      those indices map directly to reference lists.

    NODE ID SYSTEM:
      - Auto-assigned IDs are ascending integers (1, 2, 3, ...) unless pinned
      - Explicit node_id= parameter pins an ID for hardcoded references
      - High ID ranges (e.g. base_id=100) prevent collisions in composite patterns
      - The _next_id counter maintains the watermark even after explicit pins

    BUILD PATTERN:
      nf = NodeFactory()
      ckpt_id = nf.checkpoint_loader("model.safetensors")
      clip_id, vae_id = ckpt_id[0], ckpt_id[2]  # Extract from outputs
      pos_id = nf.clip_encode([ckpt_id, 1], "a photo of a cat")
      # ... more nodes ...
      workflow = nf.build()  # Returns final {node_id: node_dict} mapping
    """

    def __init__(self, start_id=1):
        """Initialize NodeFactory with optional starting ID.

        Args:
            start_id: First node ID to assign (default 1). Useful for downstream
                     insertion into existing workflows.
        """
        self._nodes = {}
        self._next_id = start_id

    # ── Internal ──────────────────────────────────────────────────────

    def _add(self, class_type, inputs, node_id=None):
        """Internal: Add a node dict to the workflow.

        Called by all public methods. Handles node ID auto-assignment and
        collision prevention. Returns the node's string ID so it can be
        referenced by downstream nodes.

        Args:
            class_type: ComfyUI class name (e.g. "CheckpointLoaderSimple")
            inputs: Dict of input parameters for the node
            node_id: Optional explicit ID; if None, auto-assign the next ID

        Returns:
            String node ID (e.g. "1", "2", or explicit "7b")
        """
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
        """Return the completed workflow dict for ComfyUI.

        The returned dict maps node_id (string) → node (dict) and is the
        final format expected by ComfyUI's API. This is typically serialized
        to JSON and sent via ComfyUI's REST API or embedded in a workflow file.

        Returns:
            Dict[str, Dict] in ComfyUI workflow format:
              {
                "1": {"class_type": "CheckpointLoaderSimple", "inputs": {...}},
                "2": {"class_type": "CLIPTextEncode", "inputs": {...}},
                ...
              }
        """
        return dict(self._nodes)

    # ═══════════════════════════════════════════════════════════════════
    #  MODEL LOADERS
    # ═══════════════════════════════════════════════════════════════════
    # These methods load the core diffusion models (UNETs), text encoders (CLIP),
    # and variational autoencoders (VAEs) that form the backbone of any workflow.
    # ComfyUI supports two loading patterns:
    #   1. Checkpoint-based (sd15, sdxl, illustrious, zit): single file with all 3
    #   2. Separate loaders (Flux, Klein): UNET + CLIP + VAE loaded independently
    # The architecture detection (_architectures.py) determines which pattern to use.

    def checkpoint_loader(self, ckpt_name, node_id=None):
        """CheckpointLoaderSimple — loads model+clip+vae from single safetensors file.

        This is the standard pattern for SD1.5, SDXL, Illustrious, and ZIT models.
        A single checkpoint file contains the UNET (diffusion model), CLIP text
        encoder, and VAE all bundled together.

        Args:
            ckpt_name: Checkpoint filename (e.g. "sd15_fp16.safetensors")
                      Must exist in ComfyUI's models/checkpoints/ directory

        Returns:
            Node ID (string). The node has three outputs:
              - [node_id, 0]: MODEL (the UNET for diffusion sampling)
              - [node_id, 1]: CLIP (the text encoder for prompt encoding)
              - [node_id, 2]: VAE (the image encoder/decoder)

        Example:
            ckpt_id = nf.checkpoint_loader("sd15.safetensors")
            model = [ckpt_id, 0]  # Use in KSampler
            clip = [ckpt_id, 1]   # Use in CLIPTextEncode
            vae = [ckpt_id, 2]    # Use in VAEEncode/VAEDecode
        """
        return self._add("CheckpointLoaderSimple",
                         {"ckpt_name": ckpt_name}, node_id)

    def unet_loader(self, unet_name, weight_dtype="default", node_id=None):
        """UNETLoader — loads the diffusion model for Flux / Klein architectures.

        Unlike checkpoint-based models, Flux and Klein architectures separate the
        UNET (diffusion model) from the CLIP and VAE. This loader handles the UNET
        only; CLIP and VAE are loaded separately via clip_loader/dual_clip_loader
        and vae_loader.

        Args:
            unet_name: UNET filename (e.g. "flux1-dev-Q6_K.gguf" or "flux2-klein.safetensors")
            weight_dtype: Data type ("default", "fp8", "fp16", "fp32", etc)

        Returns:
            Node ID (string). The node has one output:
              - [node_id, 0]: MODEL (the UNET for diffusion sampling)
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

    def lora_loader_triggers(self, model_ref, clip_ref, lora_name,
                             strength_model=1.0, strength_clip=1.0,
                             force_fetch=False, append_loraname_if_empty=True,
                             node_id=None):
        """LoraLoaderAdvanced (ComfyUI-Lora-Auto-Trigger-Words) — loads LoRA
        AND extracts trigger words from metadata/CivitAI.

        Outputs: [0]=MODEL, [1]=CLIP, [2]=STRING (trigger words)

        Falls back to standard LoraLoader if custom node not installed
        (caller checks via BUILTIN_AVAILABLE or object_info query).
        """
        return self._add("LoraLoaderAdvanced", {
            "model": model_ref, "clip": clip_ref,
            "lora_name": lora_name,
            "strength_model": strength_model,
            "strength_clip": strength_clip,
            "force_fetch": force_fetch,
            "append_loraname_if_empty": append_loraname_if_empty,
        }, node_id)

    def lora_tags_only(self, lora_name, force_fetch=False,
                       append_loraname_if_empty=True, node_id=None):
        """LoraTagsOnly (ComfyUI-Lora-Auto-Trigger-Words) — extracts trigger
        words from a LoRA's metadata WITHOUT loading it.

        Outputs: [0]=STRING (trigger words)

        Use when you need trigger words for prompt construction but the LoRA
        is loaded elsewhere (e.g. LoraLoaderModelOnly for video).
        """
        return self._add("LoraTagsOnly", {
            "lora_name": lora_name,
            "force_fetch": force_fetch,
            "append_loraname_if_empty": append_loraname_if_empty,
        }, node_id)

    def string_concat(self, text1, text2, separator=", ", node_id=None):
        """StringConcat — concatenate two strings (for prompt assembly).
        Outputs: [0]=STRING
        """
        return self._add("StringConcat", {
            "text1": text1, "text2": text2, "separator": separator,
        }, node_id)

    def upscale_model_loader(self, model_name, node_id=None):
        """UpscaleModelLoader — loads a super-resolution model (RealESRGAN etc).
        Outputs: [0]=UPSCALE_MODEL
        """
        return self._add("UpscaleModelLoader",
                         {"model_name": model_name}, node_id)

    # ═══════════════════════════════════════════════════════════════════
    #  CONDITIONING / CLIP TEXT ENCODING
    # ═══════════════════════════════════════════════════════════════════
    # These methods convert text prompts into conditioning tensors that guide
    # diffusion sampling. The CLIP text encoder tokenizes and embeds prompts.
    # For architectures with supports_negative=False (Flux, Klein), negative
    # conditioning is created via ConditioningZeroOut instead.

    def clip_encode(self, clip_ref, text, node_id=None):
        """CLIPTextEncode — encode text prompt into conditioning tensor.

        The CLIP text encoder takes a text prompt and produces a conditioning
        tensor that guides the diffusion model during sampling. This is the
        core mechanism for prompt-to-image generation.

        Args:
            clip_ref: Reference to a CLIP node, typically [clip_loader_id, 0]
            text: The text prompt (string). Can be arbitrarily long; CLIP will
                  truncate to max tokens.

        Returns:
            Node ID (string). The node has one output:
              - [node_id, 0]: CONDITIONING tensor for use in KSampler/CFGGuider

        Example:
            clip_id = nf.checkpoint_loader("sd15.safetensors")
            pos_cond = nf.clip_encode([clip_id, 1], "a beautiful cat, oil painting")
            # Now pos_cond = ["N", 0] where N is this node's ID
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

    def clip_vision_encode(self, clip_vision_ref, image_ref,
                            crop="center", node_id=None):
        """CLIPVisionEncode.
        Outputs: [0]=CLIP_VISION_OUTPUT
        """
        return self._add("CLIPVisionEncode",
                         {"clip_vision": clip_vision_ref,
                          "image": image_ref,
                          "crop": crop}, node_id)

    # ═══════════════════════════════════════════════════════════════════
    #  SAMPLING / DIFFUSION SCHEDULERS
    # ═══════════════════════════════════════════════════════════════════
    # These methods perform the core diffusion sampling process. KSampler is the
    # standard scheduler for most architectures (SD1.5, SDXL, Flux1). Klein uses
    # a separate SamplerCustomAdvanced + CFGGuider pipeline. All samplers accept
    # noise scheduling parameters (sampler_name, scheduler, steps) that control
    # the diffusion trajectory.

    def ksampler(self, model_ref, positive_ref, negative_ref, latent_ref,
                 seed, steps, cfg, sampler_name, scheduler, denoise,
                 node_id=None):
        """KSampler — standard diffusion sampling pipeline.

        The KSampler is the workhorse of ComfyUI. It iteratively denoises a
        latent starting from noise, guided by positive/negative conditioning
        and a noise schedule. The sampler_name and scheduler control the
        mathematical properties of the denoising trajectory.

        Args:
            model_ref: Reference to diffusion model (UNET), e.g. [ckpt_id, 0]
            positive_ref: Positive conditioning, e.g. [clip_encode_id, 0]
            negative_ref: Negative conditioning, e.g. [clip_encode_id, 0]
            latent_ref: Starting latent, typically from EmptyLatentImage or VAEEncode
            seed: Random seed for noise initialization (int)
            steps: Number of denoising steps (typically 20-50)
            cfg: Classifier-free guidance scale (float, e.g. 7.0)
                 Higher values make the model follow the prompt more strictly.
            sampler_name: Noise schedule family ("euler", "dpmpp_2m", "ddim", etc)
            scheduler: Noise schedule variant ("normal", "karras", "exponential", etc)
            denoise: Denoising strength (0.0 to 1.0)
                    1.0 = full generation from noise
                    0.5 = img2img strength where original image influence = 50%

        Returns:
            Node ID (string). The node has one output:
              - [node_id, 0]: LATENT (denoised latent space tensor)

        Example:
            sample_id = nf.ksampler(
                model=[ckpt_id, 0], positive=[pos_id, 0], negative=[neg_id, 0],
                latent=[empty_id, 0],
                seed=42, steps=25, cfg=7.0,
                sampler_name="euler", scheduler="normal", denoise=1.0
            )
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
    # Latents are the compressed (lower-dimensional) representation of images
    # used by diffusion models. Operations here initialize latents (EmptyLatentImage),
    # encode/decode between pixels and latent space (VAEEncode/VAEDecode), and apply
    # masks or references. Understanding latent space is critical: diffusion happens
    # in latent space, but final output requires VAE decoding back to pixel space.

    def empty_latent_image(self, width, height, batch_size=1, node_id=None):
        """EmptyLatentImage — initialize blank latent tensor for txt2img generation.

        Creates a latent tensor filled with noise, ready for the KSampler to denoise.
        This is the starting point for all txt2img (text-to-image) workflows.

        Args:
            width: Latent space width (pixels / 8). E.g., 768px → width=96
            height: Latent space height (pixels / 8). E.g., 512px → height=64
            batch_size: Number of images in batch (default 1)

        Returns:
            Node ID (string). The node has one output:
              - [node_id, 0]: LATENT (uninitialized latent tensor)
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
        """VAEEncode — compress image pixels into latent space (8x8x4 factor).

        Converts high-resolution pixel images into the compressed latent space
        where diffusion sampling operates. Essential for img2img and inpaint
        workflows: load an image, encode it, then use as starting latent.

        Args:
            pixels_ref: Reference to image pixels, typically [load_image_id, 0]
            vae_ref: Reference to VAE decoder, typically [ckpt_id, 2]

        Returns:
            Node ID (string). The node has one output:
              - [node_id, 0]: LATENT (compressed latent tensor)

        Example:
            img_id = nf.load_image("input.png")
            latent_id = nf.vae_encode([img_id, 0], [ckpt_id, 2])
            # Now latent_id can be passed to KSampler for img2img
        """
        return self._add("VAEEncode", {
            "pixels": pixels_ref, "vae": vae_ref,
        }, node_id)

    def vae_decode(self, samples_ref, vae_ref, node_id=None):
        """VAEDecode — decompress latent space back to pixel image (8x8x4 expansion).

        The inverse of VAEEncode: expands the compact latent tensor back to
        full-resolution pixel image. Always the final step before SaveImage
        in image generation workflows.

        Args:
            samples_ref: Reference to denoised latent from KSampler, typically [sampler_id, 0]
            vae_ref: Reference to VAE decoder, typically [ckpt_id, 2]

        Returns:
            Node ID (string). The node has one output:
              - [node_id, 0]: IMAGE (decompressed pixel image)

        Example:
            sample_id = nf.ksampler(...)  # Returns latent
            image_id = nf.vae_decode([sample_id, 0], [ckpt_id, 2])
            nf.save_image([image_id, 0])  # Now save the final image
        """
        return self._add("VAEDecode", {
            "samples": samples_ref, "vae": vae_ref,
        }, node_id)

    def vae_decode_tiled(self, samples_ref, vae_ref, tile_size=512,
                         overlap=64, temporal_size=64, temporal_overlap=8,
                         node_id=None):
        """VAEDecodeTiled — tiled decode for large images.
        Outputs: [0]=IMAGE
        """
        return self._add("VAEDecodeTiled", {
            "samples": samples_ref, "vae": vae_ref,
            "tile_size": tile_size,
            "overlap": overlap,
            "temporal_size": temporal_size,
            "temporal_overlap": temporal_overlap,
        }, node_id)

    # ═══════════════════════════════════════════════════════════════════
    #  IMAGE I/O & PROCESSING
    # ═══════════════════════════════════════════════════════════════════
    # These methods handle image loading/saving, scaling, blending, and other
    # pixel-level operations. Images are typically loaded for img2img workflows,
    # scaled for optimal performance, and saved as the final output. Masks are
    # extracted from images or generated programmatically for inpaint/outpaint.

    def load_image(self, filename, node_id=None):
        """LoadImage — load image file from ComfyUI's input directory.

        Supports common formats (PNG, JPG, WebP, etc). If the image has an
        alpha channel, it's automatically extracted as a mask.

        Args:
            filename: Filename relative to ComfyUI input/ folder
                     (e.g. "input.png", "photos/portrait.jpg")

        Returns:
            Node ID (string). The node has two outputs:
              - [node_id, 0]: IMAGE (pixel tensor)
              - [node_id, 1]: MASK (alpha channel as mask, if present)
        """
        return self._add("LoadImage", {"image": filename}, node_id)

    def save_image(self, images_ref, prefix="gimp_comfy", node_id=None):
        """SaveImage — save image(s) to ComfyUI output directory (terminal node).

        This is a terminal node (has no downstream consumers). Saves the final
        image and returns no output. Filename is auto-generated from prefix +
        timestamp (e.g. "gimp_comfy_001.png").

        Args:
            images_ref: Reference to image tensor, typically [vae_decode_id, 0]
            prefix: Filename prefix in output/ folder (default "gimp_comfy")

        Returns:
            Node ID (string), but has no outputs (terminal node).
        """
        return self._add("SaveImage", {
            "images": images_ref, "filename_prefix": prefix,
        }, node_id)

    def image_scale(self, image_ref, width, height,
                    upscale_method="lanczos", crop="disabled", node_id=None):
        """ImageScale — resize image to exact target dimensions.

        Simple deterministic scaling. For upscaling with model-based super-resolution,
        use image_upscale_with_model_by_factor instead.

        Args:
            image_ref: Reference to image, typically [load_image_id, 0]
            width: Target width in pixels
            height: Target height in pixels
            upscale_method: "lanczos", "bicubic", "nearest-exact", etc
            crop: "disabled" (stretch), "center" (crop to center), etc

        Returns:
            Node ID (string). The node has one output:
              - [node_id, 0]: IMAGE (scaled/cropped image)
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
                                            upscale_method="nearest-exact",
                                            node_id=None):
        """Upscale by Factor with Model (WLSH) — model-based upscale at given factor.

        Uses the WLSH custom node which applies a model upscale then resizes
        to the specified factor.

        Args:
            upscale_model_ref: Reference to UPSCALE_MODEL
            image_ref: Reference to IMAGE
            scale_by: Float factor (e.g. 2.0 for 2x)
            upscale_method: Resize method ("nearest-exact", "bilinear", "area")

        Outputs: [0]=IMAGE
        """
        return self._add("Upscale by Factor with Model (WLSH)", {
            "upscale_model": upscale_model_ref,
            "image": image_ref,
            "factor": float(scale_by),
            "upscale_method": upscale_method,
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

    def image_from_batch(self, image_ref, start=0, length=-1,
                         node_id=None):
        """ImageFromBatch+ — extract frame(s) from a batch.

        start: starting index (0-based).
        length: number of frames (-1 = all from start).
        Outputs: [0]=IMAGE
        """
        return self._add("ImageFromBatch+", {
            "image": image_ref,
            "start": start,
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

    def image_combiner(self, foreground_ref, background_ref,
                       mode="normal", foreground_opacity=1.0,
                       foreground_scale=1.0, position_x=50, position_y=50,
                       node_id=None):
        """AILab_ImageCombiner — composite foreground onto background.

        mode: normal, multiply, screen, overlay, add, subtract.
        position_x/y: 0-100 percentage positioning.
        Outputs: [0]=IMAGE
        """
        return self._add("AILab_ImageCombiner", {
            "foreground": foreground_ref,
            "background": background_ref,
            "mode": mode,
            "foreground_opacity": foreground_opacity,
            "foreground_scale": foreground_scale,
            "position_x": position_x,
            "position_y": position_y,
        }, node_id)

    # ═══════════════════════════════════════════════════════════════════
    #  CONTROLNET (SPATIAL CONTROL)
    # ═══════════════════════════════════════════════════════════════════
    # ControlNets inject spatial guidance (edges, depth, poses, etc) into diffusion.
    # A typical ControlNet workflow: preprocess input image → load ControlNet model →
    # apply to conditioning. Multiple ControlNets can be chained via the conditioning
    # output of ControlNetApplyAdvanced feeding into the next ControlNet.

    def controlnet_loader(self, control_net_name, node_id=None):
        """ControlNetLoader — load a ControlNet model file.

        ControlNets are lightweight models trained to guide diffusion based on
        spatial information (edges, depth maps, pose skeletons, etc).

        Args:
            control_net_name: Model filename, typically indicates type:
                            "control_canny-fp16.safetensors" (edge detection)
                            "control_depth-midas.safetensors" (depth maps)
                            "control_pose.safetensors" (pose guidance)

        Returns:
            Node ID (string). The node has one output:
              - [node_id, 0]: CONTROL_NET (model, passed to ControlNetApplyAdvanced)
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
                                  compute_method="Mean",
                                  face_model_name="default",
                                  save_mode=True, send_only=False,
                                  node_id=None):
        """ReActorBuildFaceModel — extract face embedding from image."""
        return self._add("ReActorBuildFaceModel", {
            "images": image_ref, "face_index": face_index,
            "compute_method": compute_method,
            "face_model_name": face_model_name,
            "save_mode": save_mode,
            "send_only": send_only,
        }, node_id)

    def reactor_save_face_model(self, face_model_ref, save_mode="overwrite",
                                face_model_name="face_model",
                                select_face_index=0, node_id=None):
        """ReActorSaveFaceModel — save face model to disk.

        save_mode: "overwrite" or "new" (add numeric suffix).
        """
        mode = save_mode if isinstance(save_mode, str) else ("overwrite" if save_mode else "new")
        return self._add("ReActorSaveFaceModel", {
            "face_model": face_model_ref,
            "save_mode": mode,
            "face_model_name": face_model_name,
            "select_face_index": select_face_index,
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
                           combine_embeds="concat",
                           start_at=0.0, end_at=1.0,
                           embeds_scaling="V only",
                           node_id=None):
        """IPAdapterAdvanced — apply IPAdapter with strength control."""
        return self._add("IPAdapterAdvanced", {
            "model": model_ref, "ipadapter": ipadapter_ref,
            "image": image_ref, "weight": weight,
            "weight_type": weight_type,
            "combine_embeds": combine_embeds,
            "start_at": start_at, "end_at": end_at,
            "embeds_scaling": embeds_scaling,
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

    def lama_remover(self, images_ref, masks_ref, mask_threshold=250,
                     gaussblur_radius=8, invert_mask=False, node_id=None):
        """LamaRemover — LaMa inpainting without diffusion."""
        return self._add("LamaRemover", {
            "images": images_ref,
            "masks": masks_ref,
            "mask_threshold": int(mask_threshold),
            "gaussblur_radius": int(gaussblur_radius),
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
                           width, height, length,
                           clip_vision_output_ref=None, start_image_ref=None,
                           batch_size=1, node_id=None):
        """WanImageToVideo — updated for ComfyUI WAN v2 API.

        The node now only takes conditioning, VAE, and dimensions.
        Model/seed/steps/cfg are handled by separate sampler nodes.
        clip_vision_output and start_image are optional.
        Outputs: [0]=CONDITIONING(pos), [1]=CONDITIONING(neg), [2]=LATENT
        """
        inputs = {
            "positive": positive_ref, "negative": negative_ref,
            "vae": vae_ref,
            "width": width, "height": height, "length": length,
            "batch_size": batch_size,
        }
        if clip_vision_output_ref is not None:
            inputs["clip_vision_output"] = clip_vision_output_ref
        if start_image_ref is not None:
            inputs["start_image"] = start_image_ref
        return self._add("WanImageToVideo", inputs, node_id)

    def wan_first_last_frame(self, positive_ref, negative_ref, vae_ref,
                              width, height, length,
                              clip_vision_start_ref=None, clip_vision_end_ref=None,
                              start_image_ref=None, end_image_ref=None,
                              batch_size=1, node_id=None):
        """WanFirstLastFrameToVideo — updated for ComfyUI WAN v2 API.

        Model/seed/steps/cfg are handled by separate sampler nodes.
        Outputs: [0]=CONDITIONING(pos), [1]=CONDITIONING(neg), [2]=LATENT
        """
        inputs = {
            "positive": positive_ref, "negative": negative_ref,
            "vae": vae_ref,
            "width": width, "height": height, "length": length,
            "batch_size": batch_size,
        }
        if clip_vision_start_ref is not None:
            inputs["clip_vision_start_image"] = clip_vision_start_ref
        if clip_vision_end_ref is not None:
            inputs["clip_vision_end_image"] = clip_vision_end_ref
        if start_image_ref is not None:
            inputs["start_image"] = start_image_ref
        if end_image_ref is not None:
            inputs["end_image"] = end_image_ref
        return self._add("WanFirstLastFrameToVideo", inputs, node_id)

    def vhs_video_combine(self, images_ref, frame_rate=24, loop_count=0,
                           filename_prefix="spellcaster",
                           format_type="video/h264-mp4",
                           pingpong=False, save_output=True,
                           node_id=None):
        """VHS_VideoCombine — combine frames into video."""
        return self._add("VHS_VideoCombine", {
            "images": images_ref,
            "frame_rate": frame_rate,
            "loop_count": loop_count,
            "filename_prefix": filename_prefix,
            "format": format_type,
            "pingpong": pingpong,
            "save_output": save_output,
        }, node_id)

    def rife_vfi(self, frames_ref, multiplier=2, batch_size=1,
                 dtype="float32", torch_compile=False, node_id=None):
        """RIFE VFI — frame interpolation."""
        return self._add("RIFE VFI", {
            "frames": frames_ref,
            "multiplier": multiplier,
            "ckpt_name": "rife49.pth",
            "clear_cache_after_n_frames": 10,
            "fast_mode": True,
            "ensemble": True,
            "scale_factor": 1.0,
            "batch_size": batch_size,
            "dtype": dtype,
            "torch_compile": torch_compile,
        }, node_id)

    # ═══════════════════════════════════════════════════════════════════
    #  VIDEO (LTX 2.3)
    # ═══════════════════════════════════════════════════════════════════
    # LTX Video 2.3 uses a distinct pipeline from Wan:
    #   UnetLoaderGGUF → LTXVChunkFeedForward → LTXVApplySTG → STGGuider
    #   → KSamplerSelect → LTXVBaseSampler → LTXVSpatioTemporalTiledVAEDecode
    # Text encoding uses LTXAVTextEncoderLoader (Gemma 3 12B + embeddings
    # connectors), NOT DualCLIPLoader.
    # Two-stage upscale: generate at half-res → LatentUpscaleModelLoader +
    # LTXVLatentUpsampler → SamplerCustomAdvanced re-denoise at full res.

    def ltxav_text_encoder_loader(self, text_encoder, ckpt_name,
                                   device="default", node_id=None):
        """LTXAVTextEncoderLoader — Gemma 3 text encoder + embeddings connector.

        LTX2.3 uses a dedicated text encoder loader that pairs a Gemma 3 model
        with LTX-specific embedding connectors, replacing the DualCLIPLoader
        used by Flux/Klein architectures.

        Args:
            text_encoder: Gemma model filename (e.g. "gemma_3_12B_it_fp4_mixed.safetensors")
            ckpt_name: Embeddings connector (e.g. "LTX\\ltx-2.3-22b-dev_embeddings_connectors.safetensors")
            device: Compute device ("default", "cpu", "cuda")

        Returns:
            Node ID. Outputs: [0]=CLIP
        """
        return self._add("LTXAVTextEncoderLoader", {
            "text_encoder": text_encoder,
            "ckpt_name": ckpt_name,
            "device": device,
        }, node_id)

    def ltxv_chunk_feed_forward(self, model_ref, chunks=4,
                                 dim_threshold=4096, node_id=None):
        """LTXVChunkFeedForward — VRAM-efficient chunked inference.

        Splits feed-forward layers into chunks to reduce peak VRAM usage.
        Essential for 22B parameter models on consumer GPUs (16GB).

        Args:
            model_ref: Reference to MODEL (from UnetLoaderGGUF or LoraLoaderModelOnly)
            chunks: Number of chunks (default 4, higher = less VRAM but slower)
            dim_threshold: Minimum dimension to chunk (default 4096)

        Returns:
            Node ID. Outputs: [0]=MODEL
        """
        return self._add("LTXVChunkFeedForward", {
            "model": model_ref,
            "chunks": chunks,
            "dim_threshold": dim_threshold,
        }, node_id)

    def ltxv_apply_stg(self, model_ref, block_indices="14, 19", node_id=None):
        """LTXVApplySTG — Spatiotemporal Guidance block injection.

        Marks specific transformer blocks for STG guidance during sampling.
        Default indices "14, 19" are the recommended blocks for LTX2.3.

        Args:
            model_ref: Reference to MODEL
            block_indices: Comma-separated block indices (default "14, 19")

        Returns:
            Node ID. Outputs: [0]=MODEL
        """
        return self._add("LTXVApplySTG", {
            "model": model_ref,
            "block_indices": block_indices,
        }, node_id)

    def ltxv_conditioning(self, positive_ref, negative_ref, frame_rate=25.0,
                           node_id=None):
        """LTXVConditioning — wraps conditioning with frame rate metadata.

        LTX2.3 uses 25fps (NOT 20fps like LTX2.2). This node attaches temporal
        metadata to the conditioning tensors.

        Args:
            positive_ref: Reference to positive CONDITIONING
            negative_ref: Reference to negative CONDITIONING
            frame_rate: Target frame rate (default 25.0 for LTX2.3)

        Returns:
            Node ID. Outputs: [0]=POSITIVE, [1]=NEGATIVE
        """
        return self._add("LTXVConditioning", {
            "positive": positive_ref,
            "negative": negative_ref,
            "frame_rate": frame_rate,
        }, node_id)

    def ltxv_scheduler(self, steps=30, max_shift=2.05, base_shift=0.95,
                        stretch=True, terminal=0.1, latent_ref=None,
                        node_id=None):
        """LTXVScheduler — noise schedule for LTX Video sampling.

        Args:
            steps: Number of sampling steps (30 for normal, 8 for distilled)
            max_shift: Maximum shift (default 2.05)
            base_shift: Base shift (default 0.95)
            stretch: Enable schedule stretching (default True)
            terminal: Terminal sigma (default 0.1)
            latent_ref: Optional latent reference for stage-2 re-denoise

        Returns:
            Node ID. Outputs: [0]=SIGMAS
        """
        inputs = {
            "steps": steps,
            "max_shift": max_shift,
            "base_shift": base_shift,
            "stretch": stretch,
            "terminal": terminal,
        }
        if latent_ref is not None:
            inputs["latent"] = latent_ref
        return self._add("LTXVScheduler", inputs, node_id)

    def stg_guider(self, model_ref, positive_ref, negative_ref,
                    cfg=4.0, stg=1.0, rescale=0.7, node_id=None):
        """STGGuider — Spatiotemporal Guidance guider for LTX sampling.

        Combines CFG and STG for LTX2.3 video generation. For distilled mode,
        use cfg=1.0, stg=0.0, rescale=0.0.

        Args:
            model_ref: Reference to MODEL (after LTXVApplySTG)
            positive_ref: Positive conditioning (from LTXVConditioning output 0)
            negative_ref: Negative conditioning (from LTXVConditioning output 1)
            cfg: Classifier-free guidance scale (default 4.0)
            stg: STG strength (default 1.0, 0.0 for distilled)
            rescale: STG rescale factor (default 0.7, 0.0 for distilled)

        Returns:
            Node ID. Outputs: [0]=GUIDER
        """
        return self._add("STGGuider", {
            "model": model_ref,
            "positive": positive_ref,
            "negative": negative_ref,
            "cfg": cfg,
            "stg": stg,
            "rescale": rescale,
        }, node_id)

    def ksampler_select(self, sampler_name="euler", node_id=None):
        """KSamplerSelect — select a sampler algorithm by name.

        Args:
            sampler_name: Sampler algorithm (default "euler")

        Returns:
            Node ID. Outputs: [0]=SAMPLER
        """
        return self._add("KSamplerSelect", {
            "sampler_name": sampler_name,
        }, node_id)

    def random_noise(self, noise_seed, node_id=None):
        """RandomNoise — generate noise tensor from seed.

        Args:
            noise_seed: Integer seed for reproducibility

        Returns:
            Node ID. Outputs: [0]=NOISE
        """
        return self._add("RandomNoise", {
            "noise_seed": noise_seed,
        }, node_id)

    def ltxv_base_sampler(self, model_ref, vae_ref, guider_ref, sampler_ref,
                           sigmas_ref, noise_ref, width, height, num_frames,
                           optional_cond_images=None, optional_cond_indices=None,
                           strength=0.9, crop="center", crf=0, blur=0,
                           node_id=None):
        """LTXVBaseSampler — core LTX Video sampler node.

        Generates latents at the specified resolution and frame count.
        For two-stage pipeline, use half resolution here (e.g. 384x256)
        then upscale via LTXVLatentUpsampler before stage-2 re-denoise.

        Args:
            model_ref: Reference to MODEL (after STG application)
            vae_ref: Reference to VAE
            guider_ref: Reference to GUIDER (from STGGuider)
            sampler_ref: Reference to SAMPLER (from KSamplerSelect)
            sigmas_ref: Reference to SIGMAS (from LTXVScheduler)
            noise_ref: Reference to NOISE (from RandomNoise)
            width: Output width in pixels
            height: Output height in pixels
            num_frames: Number of video frames to generate
            optional_cond_images: Reference to IMAGE for I2V conditioning (None=T2V)
            optional_cond_indices: Frame indices for conditioning, e.g. "0" (None=T2V)
            strength: I2V conditioning strength 0.0-1.0 (default 0.9)
            crop: Image crop mode: "center", "disabled" (default "center")
            crf: Compression ratio factor 0-63 (default 0)
            blur: Blur amount for conditioning (default 0)

        Returns:
            Node ID. Outputs: [0]=LATENT
        """
        inputs = {
            "model": model_ref,
            "vae": vae_ref,
            "guider": guider_ref,
            "sampler": sampler_ref,
            "sigmas": sigmas_ref,
            "noise": noise_ref,
            "width": width,
            "height": height,
            "num_frames": num_frames,
        }
        if optional_cond_images is not None:
            inputs["optional_cond_images"] = optional_cond_images
            inputs["optional_cond_indices"] = optional_cond_indices or "0"
            inputs["strength"] = strength
            inputs["crop"] = crop
            inputs["crf"] = crf
            inputs["blur"] = blur
        return self._add("LTXVBaseSampler", inputs, node_id)

    def latent_upscale_model_loader(self, model_name, node_id=None):
        """LatentUpscaleModelLoader — loads latent-space upscale model.

        Used in LTX2.3 two-stage pipeline for 2x latent upscale between
        generation passes.

        Args:
            model_name: Model filename (e.g. "ltx-2-spatial-upscaler-x2-1.0.safetensors")

        Returns:
            Node ID. Outputs: [0]=LATENT_UPSCALE_MODEL
        """
        return self._add("LatentUpscaleModelLoader", {
            "model_name": model_name,
        }, node_id)

    def ltxv_latent_upsampler(self, samples_ref, upscale_model_ref, vae_ref,
                               node_id=None):
        """LTXVLatentUpsampler — 2x latent-space upscale for two-stage pipeline.

        Takes half-resolution latents from LTXVBaseSampler and upscales them
        2x in latent space before stage-2 re-denoise via SamplerCustomAdvanced.

        Args:
            samples_ref: Reference to LATENT (from LTXVBaseSampler)
            upscale_model_ref: Reference to LATENT_UPSCALE_MODEL
            vae_ref: Reference to VAE

        Returns:
            Node ID. Outputs: [0]=LATENT
        """
        return self._add("LTXVLatentUpsampler", {
            "samples": samples_ref,
            "upscale_model": upscale_model_ref,
            "vae": vae_ref,
        }, node_id)

    def sampler_custom_advanced(self, noise_ref, guider_ref, sampler_ref,
                                 sigmas_ref, latent_image_ref, node_id=None):
        """SamplerCustomAdvanced — generic advanced sampler for re-denoise pass.

        Used in LTX2.3 two-stage pipeline for the second pass (10 steps)
        after latent upscale. Also usable for any custom sampling workflow.

        Args:
            noise_ref: Reference to NOISE
            guider_ref: Reference to GUIDER
            sampler_ref: Reference to SAMPLER
            sigmas_ref: Reference to SIGMAS
            latent_image_ref: Reference to LATENT (upscaled latents)

        Returns:
            Node ID. Outputs: [0]=OUTPUT (denoised latent), [1]=DENOISED_OUTPUT
        """
        return self._add("SamplerCustomAdvanced", {
            "noise": noise_ref,
            "guider": guider_ref,
            "sampler": sampler_ref,
            "sigmas": sigmas_ref,
            "latent_image": latent_image_ref,
        }, node_id)

    def ltxv_spatiotemporal_tiled_vae_decode(self, vae_ref, latents_ref,
                                              spatial_tiles=4, spatial_overlap=1,
                                              temporal_tile_length=16,
                                              temporal_overlap=1,
                                              last_frame_fix=False,
                                              working_device="auto",
                                              working_dtype="auto",
                                              node_id=None):
        """LTXVSpatioTemporalTiledVAEDecode — memory-efficient video VAE decode.

        Decodes LTX latents to pixel-space video frames using spatial and
        temporal tiling to fit within VRAM limits.

        Args:
            vae_ref: Reference to VAE
            latents_ref: Reference to LATENT
            spatial_tiles: Number of spatial tiles (default 4)
            spatial_overlap: Overlap between spatial tiles (default 1)
            temporal_tile_length: Frames per temporal tile (default 16)
            temporal_overlap: Overlap between temporal tiles (default 1)
            last_frame_fix: Fix for last-frame artifacts (default False)
            working_device: "auto", "cpu", or "cuda" (default "auto")
            working_dtype: "auto", "fp16", "bf16", etc (default "auto")

        Returns:
            Node ID. Outputs: [0]=IMAGE (video frames)
        """
        return self._add("LTXVSpatioTemporalTiledVAEDecode", {
            "vae": vae_ref,
            "latents": latents_ref,
            "spatial_tiles": spatial_tiles,
            "spatial_overlap": spatial_overlap,
            "temporal_tile_length": temporal_tile_length,
            "temporal_overlap": temporal_overlap,
            "last_frame_fix": last_frame_fix,
            "working_device": working_device,
            "working_dtype": working_dtype,
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

    def video_upscale(self, images_ref, scale_factor=2.0,
                      upscale_model="4x-UltraSharp.pth", node_id=None):
        """AI model upscaling for video frames (UpscaleModelLoader + ImageUpscaleWithModel).

        Uses a traditional upscale model file. The model runs at its native
        scale (typically 4x), then ImageScaleBy adjusts to the requested factor.

        Args:
            images_ref: Reference to input images/frames.
            scale_factor: Target scale (e.g. 2.0 = double resolution).
            upscale_model: Upscale model filename (default: 4x-UltraSharp.pth).
            node_id: Optional fixed node ID.
        """
        loader_id = self._add("UpscaleModelLoader",
                              {"model_name": upscale_model},
                              node_id=f"{node_id}_ml" if node_id else None)
        up_id = self._add("ImageUpscaleWithModel",
                          {"upscale_model": [loader_id, 0],
                           "image": images_ref},
                          node_id=node_id)
        # Model does 4x natively; scale down to target if needed
        if scale_factor < 3.5:
            ratio = scale_factor / 4.0
            down_id = self._add("ImageScaleBy",
                                {"image": [up_id, 0],
                                 "upscale_method": "lanczos",
                                 "scale_by": ratio},
                                node_id=f"{node_id}_ds" if node_id else None)
            return down_id
        return up_id

    def rtx_video_upscale(self, images_ref, scale_factor=2.0,
                          quality="ULTRA", node_id=None):
        """RTX GPU-accelerated super-resolution (RTXVideoSuperResolution).

        NOTE: Requires ComfyUI-NVIDIA-RTX with a compatible API version.
        Use video_upscale() for the standard model-based path.

        Args:
            images_ref: Reference to input images/frames.
            scale_factor: Scale multiplier (1.0-4.0).
            quality: 'LOW', 'MEDIUM', 'HIGH', or 'ULTRA'.
            node_id: Optional fixed node ID.
        """
        return self._add("RTXVideoSuperResolution", {
            "images": images_ref,
            "resize_type": "scale by multiplier",
            "scale": float(scale_factor),
            "quality": quality,
        }, node_id)

    # Backwards-compat alias
    rtx_video_super_resolution = video_upscale

    def seedvr2_video_upscaler(self, image_ref, dit_ref, vae_ref,
                               seed=42, resolution=1080, max_resolution=0,
                               batch_size=5, uniform_batch_size=False,
                               color_correction="lab", node_id=None):
        """SeedVR2VideoUpscaler — AI video upscaling.

        dit_ref: from SeedVR2 DiT model loader.
        vae_ref: from SeedVR2 VAE model loader.
        resolution: target shortest-edge pixels.
        batch_size: frames per batch (must be 4n+1: 1,5,9,13...).
        color_correction: lab, wavelet, wavelet_adaptive, hsv, adain, none.
        """
        return self._add("SeedVR2VideoUpscaler", {
            "image": image_ref,
            "dit": dit_ref,
            "vae": vae_ref,
            "seed": seed,
            "resolution": resolution,
            "max_resolution": max_resolution,
            "batch_size": batch_size,
            "uniform_batch_size": uniform_batch_size,
            "color_correction": color_correction,
        }, node_id)

    def ts_video_upscale(self, model_name, images_ref,
                         upscale_method="bicubic", factor=2.0,
                         device_strategy="auto", node_id=None):
        """TS_Video_Upscale_With_Model — upscale video with a model.

        model_name: upscale model filename (e.g. "4x-UltraSharp.pth").
        upscale_method: nearest-exact, bilinear, area, bicubic.
        factor: scale factor (0.1-8.0).
        device_strategy: auto, load_unload_each_frame, keep_loaded, cpu_only.
        """
        return self._add("TS_Video_Upscale_With_Model", {
            "model_name": model_name,
            "images": images_ref,
            "upscale_method": upscale_method,
            "factor": factor,
            "device_strategy": device_strategy,
        }, node_id)
