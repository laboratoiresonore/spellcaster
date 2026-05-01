"""Calibration System — verify every model+LoRA combination works.

The "it only works if I tried it and it worked" philosophy:
  1. Enumerate all checkpoints, UNETs, and LoRAs on the ComfyUI server
  2. Test each model with a tiny 64x64 generation (< 2 seconds each)
  3. Test each LoRA against its claimed-compatible architecture
  4. Build a compatibility matrix: {model: {lora: True/False}}
  5. Store the matrix so scaffolds only offer verified-working combos

This runs during installation (first-time calibration) or on-demand
via the Wizard Guild health system. Results persist across sessions.

Usage:
    from .calibration import calibrate, load_matrix

    # Full calibration (may take 5-20 minutes depending on model count)
    matrix = calibrate("http://192.168.x.x:8188", callback=print)

    # Quick check: is this combo verified?
    if matrix.is_verified("model.safetensors", "lora.safetensors"):
        print("This combo works!")

    # Get all verified LoRAs for a model
    loras = matrix.verified_loras("model.safetensors")
"""

import json
import os
import random
import time
import urllib.request
import urllib.error

try:
    from .model_detect import classify_unet_model, classify_ckpt_model
    from .architectures import get_arch, ARCHITECTURES
    from .preflight import preflight_workflow, get_available_nodes
except ImportError:
    from .model_detect import classify_unet_model, classify_ckpt_model
    from .architectures import get_arch, ARCHITECTURES
    from .preflight import preflight_workflow, get_available_nodes


class CompatibilityMatrix:
    """Stores verified model + LoRA compatibility results."""

    def __init__(self):
        self.models = {}        # model_name -> {"arch": key, "verified": bool, "error": str}
        self.loras = {}         # lora_name -> {"archs": [keys], "verified": {model: bool}}
        self.combos_tested = 0
        self.combos_passed = 0
        self.timestamp = ""

    def is_model_verified(self, model):
        """Check if a model has been tested and works."""
        return self.models.get(model, {}).get("verified", False)

    def is_verified(self, model, lora):
        """Check if a specific model+LoRA combo has been verified."""
        lora_info = self.loras.get(lora, {})
        return lora_info.get("verified", {}).get(model, False)

    def verified_loras(self, model):
        """Get all LoRAs verified to work with a model."""
        result = []
        for lora_name, lora_info in self.loras.items():
            if lora_info.get("verified", {}).get(model, False):
                result.append(lora_name)
        return result

    def verified_models(self):
        """Get all models that passed basic generation test."""
        return [m for m, info in self.models.items() if info.get("verified")]

    def broken_models(self):
        """Get models that failed basic generation test."""
        return [(m, info.get("error", "?")) for m, info in self.models.items()
                if not info.get("verified")]

    def summary(self):
        """Human-readable summary."""
        total_m = len(self.models)
        ok_m = sum(1 for v in self.models.values() if v.get("verified"))
        total_l = len(self.loras)
        lines = [
            f"Compatibility Matrix",
            f"  Models: {ok_m}/{total_m} verified",
            f"  LoRAs: {total_l} registered",
            f"  Combos tested: {self.combos_tested} ({self.combos_passed} passed)",
            f"  Timestamp: {self.timestamp}",
        ]
        if total_m - ok_m > 0:
            lines.append(f"  Broken models:")
            for m, err in self.broken_models():
                lines.append(f"    - {m}: {err[:60]}")
        return "\n".join(lines)

    def to_json(self):
        return {
            "models": self.models,
            "loras": self.loras,
            "combos_tested": self.combos_tested,
            "combos_passed": self.combos_passed,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_json(cls, data):
        m = cls()
        m.models = data.get("models", {})
        m.loras = data.get("loras", {})
        m.combos_tested = data.get("combos_tested", 0)
        m.combos_passed = data.get("combos_passed", 0)
        m.timestamp = data.get("timestamp", "")
        return m


# ═══════════════════════════════════════════════════════════════════════
#  Calibration engine
# ═══════════════════════════════════════════════════════════════════════

def _get_opts(server, node, field):
    """Get options for a node input from ComfyUI."""
    try:
        r = urllib.request.urlopen(f"{server}/object_info/{node}", timeout=5)
        d = json.loads(r.read())
        spec = d[node]["input"]["required"][field]
        if isinstance(spec[0], list):
            return spec[0]
        elif isinstance(spec[1], dict) and "options" in spec[1]:
            return spec[1]["options"]
        return []
    except Exception:
        return []


def _submit_and_wait(server, workflow, timeout=60):
    """Submit a workflow and wait. Returns (ok, elapsed, error).

    Delegates to spellcaster_core.dispatch when available. Calibration
    jobs are lightweight (64x64, 2 steps) so free_vram and optimize are
    skipped for speed.
    """
    try:
        from .dispatch import dispatch_workflow
        result = dispatch_workflow(
            server, workflow, timeout=timeout,
            free_vram=False,   # 64x64 jobs — no VRAM pressure
            optimize=False,    # already minimal resolution
            privacy=False,     # test outputs are disposable noise
        )
        return True, result.elapsed, ""
    except ImportError:
        pass  # dispatch not available — fall through
    except RuntimeError as e:
        return False, 0, str(e)[:120]
    except Exception as e:
        return False, 0, str(e)[:120]

    # Fallback: inline implementation
    try:
        ok_pf, workflow, _ = preflight_workflow(workflow, server)
    except Exception:
        pass

    body = json.dumps({"prompt": workflow}).encode()
    req = urllib.request.Request(
        f"{server}/prompt", data=body,
        headers={"Content-Type": "application/json"})
    try:
        r = urllib.request.urlopen(req, timeout=10)
        pid = json.loads(r.read()).get("prompt_id")
    except urllib.error.HTTPError as e:
        try:
            err = json.loads(e.read().decode())
            details = []
            for ne in err.get("node_errors", {}).values():
                for er in ne.get("errors", []):
                    details.append(er.get("details", str(er))[:80])
            return False, 0, "; ".join(details) or str(e)
        except Exception:
            return False, 0, str(e)
    except Exception as e:
        return False, 0, str(e)

    if not pid:
        return False, 0, "No prompt_id"

    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            r = urllib.request.urlopen(f"{server}/history/{pid}", timeout=5)
            d = json.loads(r.read())
            if pid in d:
                st = d[pid].get("status", {})
                if st.get("completed"):
                    return True, time.time() - t0, ""
                for msg in st.get("messages", []):
                    if msg[0] == "execution_error":
                        return False, time.time() - t0, msg[1].get("exception_message", "?")[:120]
        except Exception:
            pass
        time.sleep(1)
    return False, timeout, "Timeout"


def _build_test_workflow(model, arch_key, lora=None, lora_strength=0.5):
    """Build a tiny 64x64, 2-step test workflow."""
    try:
        from .workflows import build_txt2img
    except ImportError:
        from .workflows import build_txt2img

    a = get_arch(arch_key)
    if not a:
        return None

    preset = {
        "ckpt": model, "arch": arch_key,
        "width": 64, "height": 64, "steps": 2,
        "cfg": a.default_cfg, "sampler": a.default_sampler,
        "scheduler": a.default_scheduler, "loader": a.loader,
        "clip_name1": "", "clip_name2": "", "vae_name": "",
    }

    loras = None
    if lora:
        loras = [{"name": lora, "strength_model": lora_strength, "strength_clip": lora_strength}]

    try:
        return build_txt2img(preset, "test", "", random.randint(1, 2**31), loras=loras)
    except Exception:
        return None


def calibrate(server, callback=None, test_loras=True, max_loras_per_model=5):
    """Run full calibration: test every model and LoRA combination.

    Args:
        server: ComfyUI server URL
        callback: Progress callback function (receives status strings)
        test_loras: Whether to test LoRA compatibility (slower but thorough)
        max_loras_per_model: Max LoRAs to test per model (for speed)

    Returns: CompatibilityMatrix
    """
    log = callback or print
    matrix = CompatibilityMatrix()
    matrix.timestamp = time.strftime("%Y-%m-%d %H:%M:%S")

    # Skip patterns for non-model files
    skip = ("vae", "embeddings", "audio", "clip_", "t5xxl", "umt5",
            "gemma", "qwen", "mistral", "llava", "connector", "refiner",
            "upscale", "rife", "reactor", "ip-adapter", "controlnet",
            "ipadapter", "insightface", "face_restore", "codeformer",
            "gfpgan", "reswapper", "inswapper", "siglip", "ldsr")

    # Gather all models
    log("Calibration: gathering models...")
    all_models = []
    for node, field, cfn in [
        ("UnetLoaderGGUF", "unet_name", classify_unet_model),
        ("UNETLoader", "unet_name", classify_unet_model),
        ("CheckpointLoaderSimple", "ckpt_name", classify_ckpt_model),
    ]:
        for m in _get_opts(server, node, field):
            if any(s in m.lower() for s in skip):
                continue
            arch = cfn(m)
            if arch not in ("unknown",):
                all_models.append((m, arch, node))

    # Deduplicate by name
    seen = set()
    models = []
    for m, arch, node in all_models:
        if m not in seen:
            seen.add(m)
            models.append((m, arch))

    log(f"Calibration: {len(models)} models to test")

    # Gather LoRAs
    all_loras = _get_opts(server, "LoraLoader", "lora_name")
    log(f"Calibration: {len(all_loras)} LoRAs found")

    # Phase 1: Test each model with a bare generation
    log("\nPhase 1: Testing models (64x64, 2 steps each)...")
    for i, (model, arch) in enumerate(models):
        short = model.split("\\")[-1].split("/")[-1]
        log(f"  [{i+1}/{len(models)}] {short} ({arch})...", end=" ")

        wf = _build_test_workflow(model, arch)
        if wf is None:
            matrix.models[model] = {"arch": arch, "verified": False, "error": "Could not build workflow"}
            log("BUILD FAIL")
            continue

        ok, elapsed, err = _submit_and_wait(server, wf, timeout=60)
        matrix.models[model] = {"arch": arch, "verified": ok, "error": err, "time": elapsed}
        if ok:
            log(f"OK ({elapsed:.0f}s)")
        else:
            log(f"FAIL: {err[:60]}")

    # Phase 2: Test LoRA compatibility
    if test_loras and all_loras:
        log(f"\nPhase 2: Testing LoRA compatibility...")
        verified_models = [(m, info["arch"]) for m, info in matrix.models.items() if info["verified"]]

        # For each LoRA, find compatible architectures and test
        from .model_detect import LORA_ARCH_PREFIXES, LORA_NAME_ARCH_HINTS
        for lora in all_loras:
            ll = lora.lower()
            # Determine expected architecture from prefix/name
            lora_archs = set()
            for arch_key, prefixes in LORA_ARCH_PREFIXES.items():
                for p in prefixes:
                    alt = p.replace("\\", "/")
                    if lora.startswith(p) or lora.startswith(alt):
                        lora_archs.add(arch_key)
            if not lora_archs:
                for kw, arch_key in LORA_NAME_ARCH_HINTS:
                    if kw in ll:
                        lora_archs.add(arch_key)

            matrix.loras[lora] = {"archs": list(lora_archs), "verified": {}}

            # Test against one verified model per architecture
            tested = 0
            for model, arch in verified_models:
                if arch not in lora_archs:
                    continue
                if tested >= max_loras_per_model:
                    break

                short_m = model.split("\\")[-1][:20]
                short_l = lora.split("\\")[-1][:30]
                log(f"  {short_l} + {short_m}...", end=" ")

                wf = _build_test_workflow(model, arch, lora=lora)
                if wf is None:
                    matrix.loras[lora]["verified"][model] = False
                    log("BUILD FAIL")
                    continue

                ok, elapsed, err = _submit_and_wait(server, wf, timeout=30)
                matrix.loras[lora]["verified"][model] = ok
                matrix.combos_tested += 1
                if ok:
                    matrix.combos_passed += 1
                    log(f"OK ({elapsed:.0f}s)")
                else:
                    log(f"FAIL: {err[:40]}")
                tested += 1

    log(f"\n{matrix.summary()}")
    return matrix


# ═══════════════════════════════════════════════════════════════════════
#  Persistence
# ═══════════════════════════════════════════════════════════════════════

def save_matrix(matrix, filepath):
    """Save compatibility matrix to JSON file."""
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(matrix.to_json(), f, indent=2)


def load_matrix(filepath):
    """Load compatibility matrix from JSON file."""
    if not os.path.exists(filepath):
        return None
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return CompatibilityMatrix.from_json(json.load(f))
    except Exception:
        return None
