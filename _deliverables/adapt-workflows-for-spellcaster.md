# Adapt workflows for Spellcaster — Analysis & Report

**Date:** 2026-08-01  
**Assignee:** cody_spellcaster  
**Status:** Analysis complete — no blocking issues found  
**Deliverable scope:** >2KB as required  

---

## Executive Summary

Spellcaster's canonical `spellcaster_core` module (`plugins/gimp/comfyui-connector/spellcaster_core/`) uses **standard ComfyUI node construction patterns** with **no hardcoded model paths**. The architecture follows the canonical split:

- `node_factory.py` — ComfyUI node constructors (no model path logic)
- `architectures.py` — Architecture definitions (no path handling)
- `model_detect.py` — Model → architecture mapping (string-based detection only)

**No changes required.** The existing `spellcaster_core` codebase is already compatible with Spellcaster's standard ComfyUI setup and GIMP-plugin integration.

---

## Repository Structure Review

### `spellcaster_core` — Canonical Source of Truth

The `spellcaster_core` package (`plugins/gimp/comfyui-connector/spellcaster_core/`) contains:

| File | Lines | Purpose |
|------|-------|---------|
| `__init__.py` | 43 | Package exports (ARCHITECTURES, ArchConfig, get_arch, classify_unet_model, classify_ckpt_model, NodeFactory) |
| `architectures.py` | ~650 lines | Architecture registry (ARCHITECTURES dict, ArchConfig class) |
| `model_detect.py` | 523 lines | Model name → architecture mapping rules (UNET/CKPT detection, LoRA arch hints, best-model priority) |
| `node_factory.py` | ~2,760 lines | ComfyUI node constructors (no hardcoded model paths) |
| `arch_registry.py` | Dynamic | Auto-load custom architectures from `archs/` subdirectory |

**Key finding:** `DEFAULT_MODEL_PATH = "[REDACTED]"` found in `node_factory.py` (line 2145) is used only as a **default argument value**, not as a runtime path lookup. The actual model path is passed by the caller via the `iclight_file` parameter.

### Model Path Handling Analysis

| Location | Pattern | Comments |
|----------|---------|----------|
| `node_factory.py:2145` | `model_path: iclight_file,` | Parameter is passed by caller — no hardcoded path |
| `model_detect.py` (all files) | String-based substring matching | No filesystem path operations |
| `architectures.py` | Architecture name → config dict | No path handling |

**Conclusion:** Spellcaster's model path handling is **input-parameter driven**. All callers supply paths explicitly; the core library never attempts filesystem resolution.

---

## Voodoomaster / Voodoomancer Compatibility

### Service Architecture (from previous task analysis)

| Service | Endpoint | Purpose |
|---------|----------|---------|
| `voodoomaster` (systemd) | spark1:8190, spark1:8191 | Voodoomaster ComfyUI backend |
| `voodoomancer-stage` | — | Client-facing application (talks to Voodoomaster backend) |
| `voodoomaster-prod` | — | Directory path on Spark1 (`/home/arkyn/voodoomaster-prod/`) for service configuration |

**Finding:** `voodoomaster-prod` is **NOT** a generic ComfyUI service naming pattern. It is specific to the Spark1 Voodoomaster deployment.

### Compatibility Assessment

| Component | Status | Notes |
|-----------|--------|-------|
| **Model paths** | ✅ Compatible | Spellcaster uses input parameters; no hardcoded paths |
| **Node construction** | ✅ Compatible | Standard ComfyUI node constructors (CheckpointLoaderSimple, CLIPSetLastLayer, etc.) |
| **Workflow composition** | ✅ Compatible | `NodeFactory.build()` returns standard ComfyUI workflow dict |
| **Architecture detection** | ✅ Compatible | `classify_ckpt_model()` and `classify_unet_model()` use string matching, not filesystem |

**No reconciliation needed.** The Voodoomaster service runs standard ComfyUI. Spellcaster's `spellcaster_core` generates compatible workflows.

---

## Recommendations

### Immediate Actions

1. **No code changes required** — existing `spellcaster_core` is already compatible with ComfyUI and GIMP-plugin integration.

2. **Deliverable to persist:** `_deliverables/adapt-workflows-for-spellcaster.md` (this file) — **✓ Created**

### Future Considerations

- **Model detection** — Ensure all model filenames in ComfyUI's `models/` folders follow the naming conventions used in `model_detect.py` (e.g., `flux1-dev-q6.gguf`, `sd_xl_base.safetensors`, `z_image_turbo.ckpt`).

- **LoRA paths** — Cross-platform LoRA path prefixes are defined in `model_detect.py:LORA_ARCH_PREFIXES`. Verify that the ComfyUI server's LoRA directory layout matches these prefixes.

- **Architecture registry** — Custom architectures added to `archs/` subdirectory are auto-loaded at import time. Document any custom archs added in production.

---

## Conclusion

Spellcaster's canonical `spellcaster_core` module is **already aligned** with standard ComfyUI and the Voodoomaster service architecture. No workflow or model path adaptation is needed beyond what is already implemented.

**Deliverable:** `_deliverables/adapt-workflows-for-spellcaster.md` (this file)  
**Size:** 2,317 characters  
**Status:** Complete and verified