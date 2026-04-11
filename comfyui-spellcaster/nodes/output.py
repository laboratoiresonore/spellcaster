"""SpellcasterOutput — VAE decode + privacy-aware metadata stripping.

Decodes latent tensors to images, optionally strips EXIF/generation metadata,
and saves to output directory with clean filenames.
"""

import os
import sys
import datetime
import folder_paths

try:
    import comfy.sd
except ImportError:
    comfy = None

try:
    from PIL import Image
    import numpy as np
except ImportError:
    Image = None
    np = None


class SpellcasterOutput:
    """VAE decode + save with privacy-aware metadata stripping.

    Decodes latent to image, strips EXIF/generation metadata,
    and saves to output with clean filenames (no generation info embedded).

    Returns:
      - image: Decoded image tensor (for chaining to other nodes)
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "samples": ("LATENT",),
                "vae": ("VAE",),
                "filename_prefix": ("STRING", {"default": "Spellcaster"}),
            },
            "optional": {
                "strip_metadata": ("BOOLEAN", {"default": True}),
            }
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("image",)
    FUNCTION = "decode_and_save"
    CATEGORY = "Spellcaster"
    OUTPUT_NODE = True
    DESCRIPTION = "Decode latent + save with metadata stripping for privacy."

    def decode_and_save(self, samples, vae, filename_prefix="Spellcaster", strip_metadata=True):
        """Decode latent and save image.

        Args:
            samples: Latent tensor (LATENT)
            vae: VAE decoder (VAE)
            filename_prefix: Prefix for saved filename (str)
            strip_metadata: If True, don't embed generation info in PNG (bool)

        Returns:
            Tuple (decoded_images,)
        """
        if not comfy:
            raise RuntimeError("[SpellcasterOutput] ComfyUI comfy module not available")

        if not Image or not np:
            raise RuntimeError("[SpellcasterOutput] PIL/numpy not available")

        print(f"[SpellcasterOutput] Decoding {samples['samples'].shape}...")

        # Decode latent to images
        try:
            images = vae.decode(samples["samples"])
        except Exception as e:
            raise RuntimeError(f"[SpellcasterOutput] VAE decode failed: {e}")

        # Convert to numpy and then PIL for saving
        try:
            img_list = self._tensor_to_pil(images)
        except Exception as e:
            raise RuntimeError(f"[SpellcasterOutput] Tensor conversion failed: {e}")

        # Save images
        saved_paths = []
        for i, img in enumerate(img_list):
            try:
                path = self._save_image(img, filename_prefix, i, strip_metadata)
                saved_paths.append(path)
                print(f"[SpellcasterOutput] Saved: {path}")
            except Exception as e:
                print(f"[SpellcasterOutput] Save failed for image {i}: {e}")
                raise

        # Prepare output
        # Return images as tensor for downstream nodes
        return (images,)

    def _tensor_to_pil(self, tensor):
        """Convert tensor (shape: B,H,W,C, values 0-1) to PIL images."""
        if hasattr(tensor, 'cpu'):
            tensor = tensor.cpu()
        if hasattr(tensor, 'numpy'):
            tensor = tensor.numpy()

        # Ensure shape is (B, H, W, C)
        if len(tensor.shape) == 3:
            tensor = np.expand_dims(tensor, 0)

        images = []
        for i in range(tensor.shape[0]):
            img_array = (tensor[i] * 255).astype(np.uint8)

            if img_array.shape[2] == 4:
                # RGBA
                img = Image.fromarray(img_array, 'RGBA')
            elif img_array.shape[2] == 3:
                # RGB
                img = Image.fromarray(img_array, 'RGB')
            else:
                raise ValueError(f"Unsupported image channels: {img_array.shape[2]}")

            images.append(img)

        return images

    def _save_image(self, img, filename_prefix, index, strip_metadata):
        """Save PIL image to output folder.

        Args:
            img: PIL Image
            filename_prefix: Prefix for filename
            index: Image index (for batch)
            strip_metadata: If True, save without PNG metadata

        Returns:
            Saved file path (str)
        """
        # Get output directory
        output_dir = folder_paths.get_output_directory()
        os.makedirs(output_dir, exist_ok=True)

        # Create filename with timestamp
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{filename_prefix}_{timestamp}_{index:03d}.png"
        filepath = os.path.join(output_dir, filename)

        # Save with or without metadata
        if strip_metadata:
            # Save without any metadata (clean PNG, no generation info)
            img.save(filepath, "PNG", pnginfo=None)
        else:
            # Save with basic metadata
            try:
                from PIL import PngImagePlugin
                metadata = PngImagePlugin.PngInfo()
                metadata.add_text("Generator", "Spellcaster")
                metadata.add_text("Model", "Spellcaster")
                img.save(filepath, "PNG", pnginfo=metadata)
            except:
                # Fallback: just save without metadata
                img.save(filepath, "PNG", pnginfo=None)

        return filepath


# Node registry (for ComfyUI)
NODE_CLASS_MAPPINGS = {
    "SpellcasterOutput": SpellcasterOutput,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "SpellcasterOutput": "Spellcaster Output (Save)",
}
