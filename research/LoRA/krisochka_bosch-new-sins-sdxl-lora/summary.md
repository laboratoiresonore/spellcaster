# LoRA Research Summary: krisochka/bosch-new-sins-sdxl-lora

## Model Information
- **Model Name:** krisochka/bosch-new-sins-sdxl-lora
- **Source Repo URL:** https://huggingface.co/krisochka/bosch-new-sins-sdxl-lora
- **Downloads:** 0
- **Likes:** 0
- **Last Modified:** 2026-10-28T08:00:15.000Z
- **License:** Unknown (no license file found in repository)

## Technical Summary

DreamBooth LoRA trained on 118 fragments of Hieronymus Bosch paintings (public domain, Wikimedia Commons). The model is fine-tuned for generating images in the "BSCH style" (Bosch-style) using Stable Diffusion XL base 1.0. The trigger phrase is "painting in BSCH style". This appears to be an academic project from HSE Design (Higher School of Economics, Russia).

## Assessment Notes

- **Base Model:** stabilityai/stable-diffusion-xl-base-1.0
- **Training Data:** 118 Bosch painting fragments (Wikimedia Commons - public domain)
- **Trigger Word:** "painting in BSCH style"
- **File:** pytorch_lora_weights.safetensors (93 MB)

## Priority Recommendation

**LOW PRIORITY** - The model is technically functional but has limited novelty:
- Niche artistic style (Bosch-specific) with no demonstrated unique capabilities beyond existing LoRAs
- Zero community adoption (0 downloads, 0 likes)
- No license clearly declared (though training data is public domain)
- Academic project with no active community development indicated

## Related Tasks
- **Parent:** t_7543f336
- **Assessment Task:** t_28dde513
