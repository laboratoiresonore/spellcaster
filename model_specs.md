# Depth-Anything 3 Small - Model Architecture & Performance Specs

## Repository
- **HF Hub**: https://huggingface.co/Arm/depth-anything-v3-small-mix-precision
- **Base model**: https://huggingface.co/depth-anything/DA3-SMALL
- **Paper**: https://arxiv.org/abs/2511.10647
- **GitHub**: https://github.com/ByteDance-Seed/Depth-Anything-3

## Architecture

### Backbone
- **Type**: Vision Transformer (ViT)
- **Variant**: DINOv2 (vanilla DINO encoder)
- **Size**: Small (vits)
- **Parameters**: 0.08B (80M)
- **Out layers**: [5, 7, 9, 11]
- **RoPE**: enabled (start: layer 4)
- **QKNorm**: enabled (start: layer 4)

### Head
- **Type**: Dual-DPT (DPT for both depth and ray branches)
- **Input dim**: 768
- **Output dim**: 2 (depth + ray)
- **Features**: 64
- **Output channels**: [48, 96, 192, 384]

### Camera Conditioning
- **Camera Encoder**: Light MLP for pose input
- **Camera Decoder**: For output conditioning
- **Tokens**: Optional camera tokens appended to patch tokens

### Key Features
- Single plain transformer backbone (no architectural specialization)
- Input-adaptive cross-view self-attention mechanism
- Unified depth-ray representation (no multi-task learning needed)
- Camera pose conditioning support (optional)

## Input/Output Specifications

### Input
- **Format**: RGB image, planar FP32, normalized [0, 1]
- **Resolution**: Static 504x378 pixels (width x height)
- **Max dimensions**: 4096 pixels per dimension, 1,440,000 total pixels

### Output
- **Format**: 2D FP32 relative inverse-depth map
- **Resolution**: Matches input image resolution
- **Values**: Relative inverse depth (larger = closer to camera)

## Precision & Quantization

### Current Package
- **Base precision**: FP32 weights, FP32 tensor interfaces
- **FP16 marker**: FP16 arithmetic for supported XNNPACK operations
- **Model size**: 100.4 MB total

### LiteRT Model
- **Format**: TFLite
- **Precision**: FP16 compute (request via XNNPACK)
- **Model**: `da3_small_static_core_fp16_compute.tflite`
- **Resolution**: 504x378 static core

## Performance Metrics (FP16 vs FP32)

### End-to-End Performance (Android Vivo X300, single CPU thread)
| Metric | FP32 | FP16 | Uplift |
|--------|------|------|--------|
| Throughput | 2.68 img/s | 6.34 img/s | 2.36× |
| p50 latency | 372.8 ms | 157.8 ms | 2.36× faster |
| p90 latency | 384.7 ms | 168.2 ms | 2.29× faster |
| p99 latency | 392.2 ms | 172.6 ms | 2.27× faster |
| Peak memory | 811.5 MiB | 772.1 MiB | 4.9% lower |
| Avg memory | 799.0 MiB | 746.4 MiB | 6.6% lower |

### Accuracy (NYU Depth V2, 654 samples)
| Metric | FP32 | FP16 | Delta |
|--------|------|------|-------|
| δ1 accuracy | 91.63% | 91.63% | 0.00 pp |
| AbsRel | 8.85% | 8.85% | 0.00 pp |

## SOTA Benchmarks (DA3 vs Prior Art)

### Monocular Depth (Accuracy %)
| Model | Mono Depth |
|-------|-----------|
| DA2 | 90.3 |
| DA3 | 92.4 |
| DA3-Teacher | 94.6 |

### Pose Accuracy (Scene Average)
| Dataset | DA3 | Pi3 | VGGT |
|---------|-----|-----|------|
| HiRoom | 0.9 | 0.8 | 0.6 |
| ScanNet++ | 0.9 | 0.7 | 0.8 |
| 7Scenes | 0.9 | 0.8 | 0.8 |
| DTU | 0.9 | 0.6 | 0.8 |
| ETH3D | 0.9 | 0.8 | 0.7 |

### Reconstruction Accuracy (Scene Average)
| Dataset | DA3 | Pi3 | VGGT |
|---------|-----|-----|------|
| HiRoom | 0.9 | 0.8 | 0.6 |
| ScanNet++ | 0.9 | 0.8 | 0.8 |
| 7Scenes | 0.9 | 0.8 | 0.8 |
| DTU | 0.9 | 0.6 | 0.8 |
| ETH3D | 0.9 | 0.8 | 0.7 |

## License
- **Type**: Apache License 2.0

## Developer
- **Organization**: ByteDance Seed Team

## Files in Repository
- `da3_small_static_core_fp16_compute.tflite` — static 504x378 LiteRT depth model
- `da3_prepare_image.pte` — dynamic ExecuTorch input resize
- `da3_restore_depth.pte` — dynamic ExecuTorch output resize
- `da3_small_manifest.json` — model package manifest
- `samples/` — input/output examples
- `metadata.yaml` — model metadata
- `benchmarks/` — benchmark results
- `LICENSE` — Apache 2.0 license
- `SHA256SUMS` — model checksums

## Repository Metadata
- **Downloads (last month)**: 17
- **Last modified**: 2026-09-09T16:15:44.000Z
- **Downloads (base model DA3-SMALL)**: 66,851 (last month)
