"""SpellcasterOutput — VAE decode + privacy-aware save.

Combines VAEDecode + SaveImage in one node, with metadata stripping
enabled by default so generation parameters don't leak into saved PNGs.

Follows the exact same save pattern as ComfyUI's built-in SaveImage.
"""

import os
import json
import numpy as np
import folder_paths

from PIL import Image
from PIL.PngImagePlugin import PngInfo


class SpellcasterOutput:
    """VAE decode + save with privacy-aware metadata stripping."""

    def __init__(self):
        self.output_dir = folder_paths.get_output_directory()
        self.type = "output"
        self.compress_level = 4

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "samples": ("LATENT", {
                    "tooltip": "Latent samples from the sampler.",
                }),
                "vae": ("VAE", {
                    "tooltip": "VAE decoder (from Spellcaster Loader or standalone).",
                }),
                "filename_prefix": ("STRING", {
                    "default": "Spellcaster",
                    "tooltip": "Prefix for saved files. Supports ComfyUI formatting "
                               "like %date:yyyy-MM-dd%.",
                }),
            },
            "optional": {
                "strip_metadata": ("BOOLEAN", {
                    "default": True,
                    "tooltip": "Strip generation parameters from PNG metadata "
                               "(prompt, workflow). Enabled by default for privacy.",
                }),
            },
            "hidden": {
                "prompt": "PROMPT",
                "extra_pnginfo": "EXTRA_PNGINFO",
            },
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("image",)
    OUTPUT_TOOLTIPS = ("Decoded image tensor (for chaining to preview/other nodes).",)
    FUNCTION = "decode_and_save"
    OUTPUT_NODE = True
    CATEGORY = "Spellcaster"
    DESCRIPTION = (
        "VAE decode + save with metadata stripping. "
        "Combines VAEDecode and SaveImage — strips generation params by default."
    )
    SEARCH_ALIASES = ["spellcaster save", "privacy save", "clean save"]

    def decode_and_save(self, samples, vae, filename_prefix="Spellcaster",
                        strip_metadata=True, prompt=None, extra_pnginfo=None):

        # ── 1. VAE decode ──────────────────────────────────────────────
        images = vae.decode(samples["samples"])
        print(f"\033[36m[Spellcaster]\033[0m Decoded {images.shape[0]} image(s) "
              f"@ {images.shape[2]}×{images.shape[1]}")

        # ── 2. Save images (follows SaveImage pattern exactly) ─────────
        full_output_folder, filename, counter, subfolder, filename_prefix = \
            folder_paths.get_save_image_path(
                filename_prefix, self.output_dir,
                images[0].shape[1], images[0].shape[0],
            )

        results = []
        for batch_number, image in enumerate(images):
            i = 255.0 * image.cpu().numpy()
            img = Image.fromarray(np.clip(i, 0, 255).astype(np.uint8))

            # Build metadata — or skip entirely for privacy
            metadata = None
            if not strip_metadata:
                metadata = PngInfo()
                metadata.add_text("Generator", "Spellcaster")
                if prompt is not None:
                    metadata.add_text("prompt", json.dumps(prompt))
                if extra_pnginfo is not None:
                    for key in extra_pnginfo:
                        metadata.add_text(key, json.dumps(extra_pnginfo[key]))

            filename_with_batch = filename.replace("%batch_num%", str(batch_number))
            file = f"{filename_with_batch}_{counter:05}_.png"
            filepath = os.path.join(full_output_folder, file)

            img.save(filepath, pnginfo=metadata, compress_level=self.compress_level)

            results.append({
                "filename": file,
                "subfolder": subfolder,
                "type": self.type,
            })
            counter += 1

        label = "clean" if strip_metadata else "with metadata"
        print(f"\033[36m[Spellcaster]\033[0m Saved {len(results)} image(s) ({label})")

        # Return both UI results (for ComfyUI frontend) and tensor (for chaining)
        return {"ui": {"images": results}, "result": (images,)}
