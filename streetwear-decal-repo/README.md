---
language:
- en
license: mit
library_name: diffusers
pipeline_tag: text-to-image
tags:
- lora
- sdxl
- diffusers
- streetwear
- apparel-design
- screenprint
- text-to-image
base_model: stabilityai/stable-diffusion-xl-base-1.0
instance_prompt: TOK_DECAL
widget:
- text: "TOK_DECAL, TOK_ARCHIVAL_DECAL, Japanese woodblock dual cranes with botanical pine waves and mineral green ink, ukiyo-e aesthetic, clean vector contours, screenprint plastisol ready, isolated on black background, zero mockup, zero human"
  output:
    url: "generated_decal_woodblock.png"
- text: "TOK_DECAL, TOK_VARSITY_DECAL, 90s collegiate athletics crest with 3D high-relief puff lettering, distressed vintage acid wash varsity graphic, bold typography, screenprint ready, isolated on black background"
  output:
    url: "generated_decal_varsity.png"
---

# 👕 Streetwear Decal SDXL LoRA

A specialized **SDXL 1.0 LoRA** trained strictly on isolated, production-grade streetwear graphic t-shirt decals.

Unlike generic image models that generate photorealistic wrinkly t-shirt mockups on human models in rooms, this model generates **pure 2D graphic decals** on solid backgrounds, directly suitable for screenprinting, plastisol transfers, direct-to-garment (DTG), and 3D garment texture projection.

---

## ⚡ Key Trigger Words & Aesthetics

| Trigger Word | Aesthetic Subgenre | Stylistic Features |
|---|---|---|
| `TOK_DECAL`, `TOK_ARCHIVAL_DECAL` | Japanese Archival & Ukiyo-e | Woodblock ink, Japanese cranes, botanical motifs, mineral pigments |
| `TOK_DECAL`, `TOK_VARSITY_DECAL`, `TOK_PUFF_DECAL` | 90s Acid Surf & 3D Puff Varsity | High-relief tactile puff lettering, collegiate athletics crests, speedway typography |
| `TOK_DECAL`, `TOK_CHROME_DECAL` | Liquid Chrome & Cyber-Sigilism | Tribal metallic chrome, iridescent liquid steel, techwear glyphs |
| `TOK_DECAL`, `TOK_MANGA_DECAL` | Monochrome Manga & Cyberpunk | High-contrast screentone ink, Japanese typography, mecha motifs |
| `TOK_DECAL`, `TOK_LINEART_DECAL` | Scandinavian Minimalist | Clean geometric contours, fine continuous line art, architectural balance |
| `TOK_DECAL`, `TOK_MINERAL_DECAL` | Artisanal Mineral & Field | Distressed stone washes, botanical field drawings, earthy military typography |

**Negative Prompt recommendation:**
`photorealistic human model, wrinkled fabric mockup, collar ribbing, studio room background, selfie, hanger, 3D person, low quality, blurry`

---

## 💻 Python / Diffusers Inference

```python
import torch
from diffusers import StableDiffusionXLPipeline

# Load base SDXL 1.0
pipe = StableDiffusionXLPipeline.from_pretrained(
    "stabilityai/stable-diffusion-xl-base-1.0",
    torch_dtype=torch.float16,
    variant="fp16",
    use_safetensors=True
).to("cuda")

# Attach Streetwear Decal LoRA
pipe.load_lora_weights("adarrshDev/streetwear-decal-sdxl-lora", weight_name="streetwear_decal_sdxl_lora.safetensors")

prompt = (
    "TOK_DECAL, TOK_ARCHIVAL_DECAL, Japanese woodblock dual cranes with botanical pine waves "
    "and mineral green ink, ukiyo-e aesthetic, clean vector contours, screenprint plastisol ready, "
    "isolated on black background, zero mockup, zero human"
)
negative_prompt = "wrinkled mockup, human model, person wearing shirt, collar, sleeves, room background"

image = pipe(
    prompt=prompt,
    negative_prompt=negative_prompt,
    num_inference_steps=30,
    guidance_scale=7.5
).images[0]

image.save("streetwear_decal.png")
```

---

## 🔬 Dataset & Training Rigor

- **Dataset**: Curated streetwear apparel graphic pack isolated from studio packshots across 10 signature streetwear design aesthetics.
- **Zero-Defect Masking**: 100% garment fabric, neck ribbing, sleeves, and human models algorithmically zeroed out, retaining purely the printable torso decal art.
- **Hardware**: Fine-tuned on Tesla T4 with 8-bit AdamW optimizer, mixed precision FP16, and gradient checkpointing.
- **Resolution**: 1024 × 1024
- **Rank**: 32

---

## 🌐 3D Apparel Studio Integration

This model is integrated directly into the **Axiom 3D Apparel Studio**, where generated decals are projected directly onto UV-mapped 3D cotton t-shirt meshes with real-time normal maps and roughness parameters.
