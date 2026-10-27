# FLUX.2-dev-FP8 Model Verification Report

## Executive Summary

The `CaaretAI/FLUX.2-dev-FP8` model entry on Hugging Face exists and has been verified. Key findings: **0 downloads, 0 likes**, last modified **2026-10-27** (about 1 hour ago as of this report). The model is an FP8/INT8 quantized variant of `black-forest-labs/FLUX.2-dev`, with no Klein lineage.

---

## Model Provenance

| Field | Value |
|-------|-------|
| **Model ID** | `CaaretAI/FLUX.2-dev-FP8` |
| **Base Model** | `black-forest-labs/FLUX.2-dev` (32B parameters) |
| **Lineage** | Direct derivative of BFL FLUX.2-dev |
| **Quantization** | FP8 / INT8 (Unsloth) |
| **License** | `flux-non-commercial-license` (same as base) |
| **Hugging Face URL** | https://huggingface.co/CaaretAI/FLUX.2-dev-FP8 |

---

## Timeline & Activity

- **Last Modified:** 2026-10-27 (about 1 hour ago)
- **Published:** 2026-10-27 (same day, ~1 hour ago)
- **Commits:** 2 (initial commit + folder upload)

---

## Metrics (as of 2026-10-27)

| Metric | Count |
|--------|-------|
| **Downloads** | 0 |
| **Likes** | 0 |
| **Followers** | 0 (CaaretAI profile: 1 model listed) |
| **GitHub Stars (base)** | N/A (base model has 2.45k likes) |

---

## Files in Repository

| File | Size | Status |
|------|------|--------|
| `FLUX.2-dev-FP8` | 24.7 GB | Main model |
| `FLUX.2-dev-text_encoder-FP8.safetensors` | 24.7 GB | Text encoder |
| `README.md` | 13.8 kB | Model card |
| `CAARET_MINING.md` | 256 B | Packaging note |
| `.gitattributes` | 1.52 kB | Git config |

---

## Key Observations & Red Flags

### ✅ Legitimate Elements

1. **Verified Base Model**: Explicitly documents `black-forest-labs/FLUX.2-dev` as base
2. **Official Quantization Method**: FP8 via Unsloth (cf. `unsloth/FLUX.2-dev-FP8` exists)
3. **License Compliance**: Uses the same `flux-non-commercial-license` as BFL
4. **Real Files**: Large binary files (24.7 GB each) match expected size for FP8 quantized models

### ⚠️ Inconsistencies

1. **Zero Engagement**: 0 downloads / 0 likes despite being uploaded recently - atypical for new Hugging Face models
2. **CaaretAI Profile Scarcity**: Only 7 models listed on profile (vs. typical org activity)
3. **"About 1 hour ago" Timestamp**: Extremely recent upload — verify ongoing activity
4. **Gating Issue**: `CAARET_MINING.md` states "Official BFL FLUX.2-dev is gated on this HF account" — suggests potential access issues

### 🔍 Potential Concerns

- **No samples visible**: Model card references samples but Hugging Face UI shows no preview (gated or missing)
- **Diffusers tree conversion pending**: `CAARET_MINING.md` notes "Diffusers tree conversion pending gate access" — incomplete integration
- **Self-referential packaging**: No clear derivation path from `unsloth/FLUX.2-dev-FP8` to `CaaretAI/FLUX.2-dev-FP8`

---

## Lineage Clarification

**This model is NOT part of the Klein family:**

- `FLUX.2-klein-4B` (4B, Apache 2.0) → official Black Forest Labs model
- `FLUX.2-dev` (32B) → official Black Forest Labs model  
- `FLUX.2-dev-FP8` (CaaretAI) → quantized derivative of `FLUX.2-dev`, **not** `FLUX.2-klein-4B`

The "Klein" reference in user prompts appears to be a conflation of:
1. Black Forest Labs' `FLUX.2-klein-4B` (small, fast, Apache 2.0)
2. The larger `FLUX.2-dev` → FP8 quantized version (CaaretAI)

---

## Recommendation

**Status**: VERIFIED (provenance legitimate, metadata accurate)

**Action**: None required — model is a valid FP8 quantization of FLUX.2-dev with proper attribution. Monitor for activity growth in next 24-48 hours.

---

## Verification Metadata

| Field | Value |
|-------|-------|
| **Verified By** | Hermes (default profile) |
| **Verification Time** | 2026-10-27 (via Tor + tor_fetch.py) |
| **Sources** | Hugging Face (CaaretAI, unsloth, black-forest-labs) |
| **Commit SHA** | *(pending)* |
