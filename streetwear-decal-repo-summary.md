# Streetwear Decal SDXL LoRA — Repository Summary

## Repository Information

- **Repository**: `adarrshDev/streetwear-decal-sdxl-lora`
- **Source**: HuggingFace
- **License**: MIT
- **Base Model**: `stabilityai/stable-diffusion-xl-base-1.0`
- **Pipeline Tag**: text-to-image
- **Tags**: lora, sdxl, diffusers, streetwear, apparel-design, screenprint, text-to-image

## Repository Structure

| File | Size | Description |
|------|------|-------------|
| `README.md` | 4.3 KB | Repository documentation with usage instructions and prompt examples |
| `streetwear_decal_sdxl_lora.safetensors` | 186 MB | Trained LoRA weights file in SafeTensors format |
| `generated_decal_woodblock.png` | 1.2 MB | Example output: Japanese woodblock aesthetic with ukiyo-e motifs |
| `generated_decal_varsity.png` | 1.2 MB | Example output: 90s varsity collegiate crest with puff lettering |
| `golden_450_decal_montage.png` | 954 KB | Montage showing multiple generated decal variations |
| `.gitattributes` | 1.7 KB | Git configuration for LFS file filtering |

## Key Features

- **Trained on**: 10 streetwear design aesthetics (archival, varsity, chrome, manga, lineart, mineral)
- **Resolution**: 1024 × 1024
- **Rank**: 32
- **Hardware**: Tesla T4 with FP16 mixed precision, gradient checkpointing
- **Zero-defect masking**: 100% garment fabric, 0% human models/room backgrounds

## Trigger Words

| Trigger Word | Aesthetic |
|--------------|-----------|
| `TOK_DECAL`, `TOK_ARCHIVAL_DECAL` | Japanese Archival & Ukiyo-e |
| `TOK_DECAL`, `TOK_VARSITY_DECAL`, `TOK_PUFF_DECAL` | 90s Acid Surf & 3D Puff Varsity |
| `TOK_DECAL`, `TOK_CHROME_DECAL` | Liquid Chrome & Cyber-Sigilism |
| `TOK_DECAL`, `TOK_MANGA_DECAL` | Monochrome Manga & Cyberpunk |
| `TOK_DECAL`, `TOK_LINEART_DECAL` | Scandinavian Minimalist |
| `TOK_DECAL`, `TOK_MINERAL_DECAL` | Artisanal Mineral & Field |

## Integration

Integrated into **Axiom 3D Apparel Studio** for 3D apparel projection with UV-mapped meshes and real-time normal/roughness maps.

## Negative Prompt Recommendation

```
photorealistic human model, wrinkled fabric mockup, collar ribbing, studio room background, selfie, hanger, 3D person, low quality, blurry
```
