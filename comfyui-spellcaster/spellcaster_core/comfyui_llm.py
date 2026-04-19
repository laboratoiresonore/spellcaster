"""ComfyUI-native LLM — text generation via GGUF nodes on the ComfyUI server.

Instead of requiring a separate KoboldCpp/Ollama server, this module
discovers LLM-capable nodes already installed on the ComfyUI server and
submits text-generation workflows through the standard /prompt API.

VRAM MANAGEMENT — the load / enhance / unload / generate / reload cycle
──────────────────────────────────────────────────────────────────────────
This cycle ONLY matters when the LLM is running inside ComfyUI — the
LLM and the diffusion model share one GPU, so they have to take turns.
If the user's LLM backend is Ollama on a separate process (or a
separate machine), Ollama manages its own memory and the cycle doesn't
apply; guild_llm.chat() routes to Ollama directly without invoking
any of this.

When ComfyUI IS hosting the LLM, the server handles the cycle natively
for us, but ONLY if the LLM node is configured to surrender VRAM. Our
canonical config sets `keep_model_loaded: False` on the enhancer node
(see _LLM_NODE_CANDIDATES below). That makes the full cycle work:

  1. LOAD       ComfyUI auto-loads the GGUF model when the LLM node runs.
  2. ENHANCE    Node rewrites the user's prompt per arch-specific profile.
  3. UNLOAD     keep_model_loaded=False → ComfyUI frees the LLM's VRAM
                slot as soon as the node completes. No lingering tenant.
  4. GENERATE   Image / video workflow runs with the FULL GPU available.
  5. RELOAD     Next enhancement call — ComfyUI reloads the GGUF from
                the OS page cache (warm NVMe ~0.8s for a 4B Q4 model).

If you set keep_model_loaded=True you gain ~1s per call but lose VRAM
headroom for every subsequent image gen. On 8GB consumer GPUs this
means OOMs on larger flux/klein models. Don't flip it unless you have
unified memory (Mac) or a 24GB+ card and know what you're doing.

Supported nodes (tried in priority order):
  1. AILab_QwenVL_GGUF_PromptEnhancer — local GGUF, custom system prompt
  2. (future nodes can be added here)

USAGE:
    from spellcaster_core.comfyui_llm import discover_llm, generate_text

    info = discover_llm("http://192.168.x.x:8188")
    # {"node_class": "AILab_QwenVL_GGUF_PromptEnhancer",
    #  "models": ["Qwen3-4B-Instruct-Q4_K_M.gguf", ...]}

    text = generate_text(
        "http://192.168.x.x:8188",
        prompt="a cat sleeping in sunlight",
        system_prompt="You are a prompt engineer for SDXL...",
    )

If no LLM node is available or generation fails, returns None.
"""

import json
import random
import re
import time
import urllib.request
import urllib.error


# ═══════════════════════════════════════════════════════════════════════════
#  NODE DISCOVERY
# ═══════════════════════════════════════════════════════════════════════════

# Nodes to try, in priority order.  Each entry:
#   class_type, model_field, prompt_field, system_prompt_field
# WHY a list: future LLM nodes can be appended here. discover_llm() iterates
# this list and stops at the first node the server actually has installed.
_LLM_NODE_CANDIDATES = [
    {
        "class_type": "AILab_QwenVL_GGUF_PromptEnhancer",
        "model_field": "model_name",
        "prompt_field": "prompt_text",
        "system_field": "custom_system_prompt",
        # Required fields with sensible defaults — the node errors without these
        # even though we only use it for text (not vision).
        "extra_inputs": {
            "preset_system_prompt": "\U0001f4dd Enhance",
            "english_output": False,       # let model respond in any language
            "device": "auto",              # let ComfyUI pick GPU/CPU
            "keep_model_loaded": False,     # free VRAM after generation
            "keep_last_prompt": False,
            "top_p": 0.9,
            "repetition_penalty": 1.1,     # mild anti-repetition penalty
        },
    },
]

# Text output nodes — ComfyUI refuses to execute a workflow that has no
# output_node=True node. These are "sink" nodes that accept a STRING input
# and display it, causing ComfyUI to record the text in /history/{prompt_id}.
# Without one of these, the LLM node runs but the result is silently discarded.
# Tried in order; first one found on the server wins.
_TEXT_OUTPUT_NODES = [
    ("PreviewTextNode", "text"),
    ("ShowText|pysssss", "text"),     # pysssss = ComfyUI-Custom-Scripts pack
    ("ShowText|LP", "text"),          # LP = LoopPerfect node pack
    ("VRGDG_ShowText", "text"),
]

# Model preference — first match wins (substring match, case-insensitive).
# Abliterated/Josiefied models are preferred because they follow prompt-engineering
# instructions without safety refusals (important for creative/NSFW workflows).
# The "Instruct" vanilla variants are usable fallbacks but may refuse edge cases.
# 4B models are preferred over 8B to minimize VRAM contention with image generation.
_MODEL_PREFERENCE = [
    "josiefied-qwen3-4b-instruct",     # abliterated instruct — best
    "josiefied-qwen3-4b-abliterated",
    "qwen3-4b-abliterated",
    "qwen3-4b-instruct-q4_k_m",        # Q4_K_M = good quality/size tradeoff (~2.5GB)
    "qwen3-4b-instruct-q5_k_m",
    "qwen3-4b-instruct",
    "qwen3-4b-q4_k_m",
    "qwen3-4b",
    "qwen3-8b-instruct-q4_k_m",        # 8B models: better quality but 2x VRAM
    "qwen3-8b-instruct",
    "qwen3-8b",
]


# ═══════════════════════════════════════════════════════════════════════════
#  PER-FAMILY LLM MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════════
# Every diffusion family has a different VRAM profile and a different
# prompt-length target. The LLM we run on the SAME ComfyUI GPU competes
# with the diffusion model for that VRAM; the bigger the diffusion model,
# the more aggressive we have to be about unloading the LLM after each
# enhancement call. On the other end of the spectrum, tiny families like
# SD 1.5 (~2 GB) leave enough headroom that we can leave the LLM warm
# across turns and save the 0.8 s reload each time.
#
# Fields
# ──────
#   keep_model_loaded   False = unload LLM after enhance (default, safe).
#                       True  = keep it resident (only on small diffusion
#                               families + plenty of VRAM).
#   keep_last_prompt    True  = cache the last prompt text server-side so
#                               repeated same-prompt calls short-circuit.
#                               Useful for iterative-seed workflows.
#   max_quant_bits      Cap on the LLM quantisation we're willing to load.
#                       4 = Q4_K_M (~2.5 GB). 5 = Q5_K_M (~3 GB). 8 = Q8
#                       (~4.5 GB). Families with large diffusion models
#                       should stay at 4; text-only tasks can go higher.
#   max_model_size_b    Cap on the LLM parameter count in billions. 4 for
#                       most image families, 8 only when the diffusion
#                       model is tiny or video generation is so slow that
#                       an extra 2 GB of LLM doesn't matter.
#   poll_timeout_s      How long to wait for the LLM to finish. Tuned per
#                       prompt-length target in the arch profile — longer
#                       targets (LTX 100-200 words) need longer timeouts.
#
# When a caller passes arch_key to generate_text, the matching family
# config's extra_inputs override the defaults baked into
# _LLM_NODE_CANDIDATES (which stay safe for unknown families).
_PER_FAMILY_LLM_CONFIG = {
    # SDXL (~6-8 GB): tight on 8 GB cards. Unload LLM, 4B quant only.
    "sdxl":        {"keep_model_loaded": False, "keep_last_prompt": False,
                    "max_quant_bits": 4, "max_model_size_b": 4,
                    "poll_timeout_s": 45},
    # Illustrious / Pony are SDXL finetunes — same VRAM footprint.
    "illustrious": {"keep_model_loaded": False, "keep_last_prompt": False,
                    "max_quant_bits": 4, "max_model_size_b": 4,
                    "poll_timeout_s": 45},
    "pony":        {"keep_model_loaded": False, "keep_last_prompt": False,
                    "max_quant_bits": 4, "max_model_size_b": 4,
                    "poll_timeout_s": 45},
    # SD 1.5 (~2 GB): lots of headroom. Keep LLM resident for fast
    # iteration, but DO NOT set keep_last_prompt=True — live testing
    # showed the AILab node returns the PREVIOUS call's output for
    # different prompts (cross-prompt cache bleed). The 0.8 s saving
    # isn't worth the correctness bug; only keep_model_loaded stays on.
    "sd15":        {"keep_model_loaded": True,  "keep_last_prompt": False,
                    "max_quant_bits": 8, "max_model_size_b": 8,
                    "poll_timeout_s": 30},
    # Flux 1 Dev (~12-16 GB): must unload LLM, tight quant.
    "flux1dev":    {"keep_model_loaded": False, "keep_last_prompt": False,
                    "max_quant_bits": 4, "max_model_size_b": 4,
                    "poll_timeout_s": 60},   # 80-150 word target
    # Flux 2 Klein (~11-14 GB): same pressure.
    "flux2klein":  {"keep_model_loaded": False, "keep_last_prompt": False,
                    "max_quant_bits": 4, "max_model_size_b": 4,
                    "poll_timeout_s": 45},
    # Chroma uses the Flux 2 engine.
    "chroma":      {"keep_model_loaded": False, "keep_last_prompt": False,
                    "max_quant_bits": 4, "max_model_size_b": 4,
                    "poll_timeout_s": 45},
    # Flux Kontext (edit-instructions): skip enhancement; kept for
    # completeness so callers that still invoke it get safe defaults.
    "flux_kontext":{"keep_model_loaded": False, "keep_last_prompt": False,
                    "max_quant_bits": 4, "max_model_size_b": 4,
                    "poll_timeout_s": 30},
    # Video: generation takes minutes — reload cost is noise. Use a
    # roomier quant for better cinematic vocabulary (Q5_K_M fits 4B in
    # ~3 GB), and push the poll timeout up because video prompts are
    # long (80-150 words for WAN, 100-200 for LTX).
    "wan":         {"keep_model_loaded": False, "keep_last_prompt": False,
                    "max_quant_bits": 5, "max_model_size_b": 4,
                    "poll_timeout_s": 75},
    "ltx":         {"keep_model_loaded": False, "keep_last_prompt": False,
                    "max_quant_bits": 5, "max_model_size_b": 4,
                    "poll_timeout_s": 90},
}

# Default config for families not in the table (unknown archs, custom
# registrations). Conservative: unload, 4B/Q4, 45s timeout.
_DEFAULT_FAMILY_CONFIG = {
    "keep_model_loaded": False, "keep_last_prompt": False,
    "max_quant_bits": 4, "max_model_size_b": 4,
    "poll_timeout_s": 45,
}


def _family_config(arch_key):
    """Return the per-family LLM-management config for an arch key,
    falling back to conservative defaults for unknown families.
    """
    return _PER_FAMILY_LLM_CONFIG.get(arch_key or "", _DEFAULT_FAMILY_CONFIG)

# Cache: comfy_url -> discovery result dict (or None).
# WHY cache: /object_info calls are slow (~200ms each) and the node inventory
# doesn't change during a session. Cleared via invalidate_cache().
_llm_cache = {}
# Models that returned "not found" errors (GGUF file not downloaded on server).
# Persists for the process lifetime so we don't retry unavailable models every call.
_failed_models = set()


def discover_llm(comfy_url):
    """Discover available LLM nodes and models on a ComfyUI server.

    Returns dict with node_class, models list, and internal config,
    or None if no LLM node is found.

    Results are cached per server URL.  Call invalidate_cache() after
    installing new nodes.
    """
    url = comfy_url.rstrip("/")
    if url in _llm_cache:
        return _llm_cache[url]

    for candidate in _LLM_NODE_CANDIDATES:
        ct = candidate["class_type"]
        try:
            info_url = f"{url}/object_info/{ct}"
            req = urllib.request.Request(info_url,
                                        headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            node_info = data.get(ct)
            if not node_info:
                continue

            # Extract available models from the model field's choice list
            model_field = candidate["model_field"]
            model_spec = (node_info.get("input", {})
                          .get("required", {})
                          .get(model_field, []))
            models = []
            if model_spec and isinstance(model_spec[0], list):
                models = model_spec[0]

            if not models:
                continue

            # Find a text output node (ComfyUI requires output_node in workflow)
            output_node = _find_text_output_node(url)

            result = {
                "node_class": ct,
                "models": models,
                "model_field": model_field,
                "prompt_field": candidate["prompt_field"],
                "system_field": candidate["system_field"],
                "extra_inputs": candidate["extra_inputs"],
                "output_name": node_info.get("output_name", ["STRING"])[0],
                "output_node": output_node,
            }
            _llm_cache[url] = result
            print(f"  [LLM] ComfyUI LLM node detected: {ct} "
                  f"({len(models)} models)")
            return result

        except Exception:
            continue

    _llm_cache[url] = None
    return None


def invalidate_cache(comfy_url=None):
    """Clear cached discovery results."""
    if comfy_url:
        _llm_cache.pop(comfy_url.rstrip("/"), None)
    else:
        _llm_cache.clear()


def _find_text_output_node(url):
    """Find an available text output node on the server."""
    for class_type, field in _TEXT_OUTPUT_NODES:
        try:
            # URL-encode the pipe character for nodes like ShowText|pysssss
            encoded = class_type.replace("|", "%7C")
            info_url = f"{url}/object_info/{encoded}"
            req = urllib.request.Request(info_url,
                                        headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            if data.get(class_type, {}).get("output_node"):
                return {"class_type": class_type, "field": field}
        except Exception:
            continue
    return None


def _model_quant_bits(name):
    """Parse a GGUF filename for quantisation bit count.
    Qwen3-4B-Instruct-Q4_K_M.gguf → 4, ...Q5_K_M... → 5, ...Q8_0... → 8,
    fp16 / f16 → 16. Unknown → 8 (treat as heavy, so filters err on safe).
    """
    low = (name or "").lower()
    if "f16" in low or "fp16" in low:
        return 16
    if "q8" in low:
        return 8
    if "q6" in low:
        return 6
    if "q5" in low:
        return 5
    if "q4" in low:
        return 4
    if "q3" in low:
        return 3
    if "q2" in low:
        return 2
    return 8


def _model_size_b(name):
    """Parse a GGUF filename for parameter count in billions.
    Substring match on -4b- / -8b- / -13b- etc. Unknown → 999 so the
    filter treats it as larger than any cap.
    """
    low = (name or "").lower()
    for n in (1, 2, 3, 4, 6, 7, 8, 13, 14, 20, 30, 34, 70):
        if f"-{n}b-" in low or f"-{n}b." in low or f"_{n}b_" in low \
                or f"_{n}b." in low or f":{n}b" in low:
            return n
    return 999


def _pick_model(models, exclude=None, arch_key=None):
    """Choose the best model from the available list.

    Skips models in _failed_models (not downloaded) and any in exclude set.
    When arch_key is given, filters models whose quantisation or size
    exceed the family's cap (see _PER_FAMILY_LLM_CONFIG) — so SDXL won't
    try to load a Q8 8B model into a GPU that also has to host the SDXL
    checkpoint.
    """
    # Combine permanently-failed models with this call's exclusion set
    skip = _failed_models | (exclude or set())
    available = [m for m in models if m not in skip]
    if not available:
        # All models have failed at some point — reset and try again.
        # This handles the edge case where a model was re-downloaded since
        # the last attempt.
        available = models

    # Apply per-family caps if we know the arch. We DON'T apply this before
    # the _failed_models fallback above — if every preferred model failed
    # we'd rather try an oversized one than return nothing.
    if arch_key:
        cfg = _family_config(arch_key)
        max_bits = cfg.get("max_quant_bits", 4)
        max_size = cfg.get("max_model_size_b", 4)
        filtered = [m for m in available
                    if _model_quant_bits(m) <= max_bits
                    and _model_size_b(m) <= max_size]
        if filtered:  # keep the cap; if it empties the list, fall through
            available = filtered

    # Walk the preference list: first substring match in available models wins
    for pref in _MODEL_PREFERENCE:
        for m in available:
            if pref in m.lower():
                return m
    # No preference match — heuristic fallback: pick the smallest non-VL
    # instruct model (VL = vision-language, much larger and slower for text-only).
    # Q4 quantization is preferred for minimal VRAM footprint.
    for m in available:
        low = m.lower()
        if "instruct" in low and "vl" not in low and "q4" in low:
            return m
    # Absolute last resort: just pick the first model alphabetically
    return available[0]


# ═══════════════════════════════════════════════════════════════════════════
#  TEXT GENERATION
# ═══════════════════════════════════════════════════════════════════════════

def generate_text(comfy_url, prompt, system_prompt="", model=None,
                  max_tokens=300, temperature=0.7, arch_key=None):
    """Generate text via a ComfyUI LLM node.

    Builds a single-node workflow, submits it, and polls for the result.
    If the chosen model isn't downloaded, automatically retries with the
    next best model (up to 3 attempts).

    arch_key (optional): diffusion family this text will feed (sdxl,
    sd15, flux1dev, flux2klein, chroma, illustrious, pony, wan, ltx,
    flux_kontext). Controls LLM-side VRAM management via
    _PER_FAMILY_LLM_CONFIG: model size / quant caps, keep_model_loaded
    override, poll timeout, keep_last_prompt hint. Families with large
    diffusion models stay on smaller LLM quants and always unload;
    SD 1.5 (tiny diffusion) stays warm across calls.

    Returns the generated text string, or None on any failure.
    This function never raises — all errors return None so callers
    can fall through to the next LLM backend.
    """
    url = comfy_url.rstrip("/")

    try:
        info = discover_llm(url)
        if not info:
            return None

        # Per-family VRAM / timeout profile. Falls back to safe defaults
        # when arch_key is None or unrecognised.
        fam = _family_config(arch_key)

        tried = set()
        # If caller specified a model, don't retry with alternatives —
        # they asked for that specific model. Otherwise try up to 3
        # different models from the preference list.
        max_retries = 3 if model is None else 1

        for attempt in range(max_retries):
            chosen = model if model else _pick_model(info["models"],
                                                     exclude=tried,
                                                     arch_key=arch_key)
            if chosen in tried:
                break  # _pick_model returned one we already tried = exhausted
            tried.add(chosen)

            wf = _build_workflow(info, prompt, system_prompt, chosen,
                                 max_tokens, temperature, family=fam)

            pid = _submit(url, wf)
            if not pid:
                return None  # Server unreachable or rejected the workflow

            # Poll timeout scales with the family's prompt-length target:
            # LTX needs 100-200 words → 90 s; SDXL 40-100 → 45 s; SD 1.5
            # short tags → 30 s. Default 45 when the arch is unknown.
            text, error = _poll_result(url, pid, info["output_name"],
                                       timeout=fam.get("poll_timeout_s", 45))

            # "not found" = GGUF file listed in node dropdown but not actually
            # downloaded on the server. Mark it failed so future calls skip it.
            if error and "not found" in error.lower():
                _failed_models.add(chosen)
                print(f"  [LLM] Model not available: {chosen} — trying next")
                continue

            if text:
                text = _clean_output(text)
                # 10-char minimum filters out junk like "Sure!" or empty tags
                if text and len(text) > 10:
                    return text

            return None  # Non-model error or junk output — don't retry

        return None  # Exhausted all model candidates

    except Exception:
        return None


def _build_workflow(info, prompt, system_prompt, model,
                    max_tokens, temperature, family=None):
    """Build a ComfyUI workflow for text generation.

    Includes an output node (required by ComfyUI) that captures the
    generated text so it appears in /history/{prompt_id} outputs.

    family (optional): per-family LLM-management config (from
    _PER_FAMILY_LLM_CONFIG). Overrides keep_model_loaded /
    keep_last_prompt baked into info["extra_inputs"] so SD 1.5 can keep
    the LLM warm while Flux / Klein / WAN / LTX force an unload.
    """
    inputs = {
        info["model_field"]: model,
        info["prompt_field"]: prompt,
        info["system_field"]: system_prompt,
        "max_tokens": max_tokens,
        "temperature": temperature,
        # Random seed ensures different outputs per call even with same prompt
        "seed": random.randint(1, 2**32 - 1),
    }
    # Merge in required extra fields (preset_system_prompt, device, etc.)
    # but don't overwrite anything we already set above
    for k, v in info["extra_inputs"].items():
        if k not in inputs:
            inputs[k] = v
    # Per-family overrides LAST so they win over the node's default
    # extra_inputs. Both fields are boolean in the AILab node schema.
    if family:
        for key in ("keep_model_loaded", "keep_last_prompt"):
            if key in family:
                inputs[key] = bool(family[key])

    workflow = {
        "1": {
            "class_type": info["node_class"],
            "inputs": inputs,
        },
    }

    # CRITICAL: ComfyUI silently skips execution if the workflow has no
    # output_node=True. Node "2" is a text display sink that forces execution
    # and captures the LLM output into /history/{prompt_id} for polling.
    # ["1", 0] = connect to node "1", output slot 0 (the generated text).
    out = info.get("output_node")
    if out:
        workflow["2"] = {
            "class_type": out["class_type"],
            "inputs": {out["field"]: ["1", 0]},
        }

    return workflow


def _submit(url, workflow):
    """Submit a workflow to ComfyUI, return prompt_id or None."""
    try:
        body = json.dumps({"prompt": workflow}).encode("utf-8")
        req = urllib.request.Request(
            f"{url}/prompt", data=body,
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("prompt_id")
    except Exception:
        return None


def _poll_result(url, prompt_id, output_key, timeout=90):
    """Poll ComfyUI history until text result is available.

    Returns (text, error) tuple.  On success: (text, None).
    On error: (None, error_message).  On timeout: (None, None).
    """
    history_url = f"{url}/history/{prompt_id}"
    # Poll every 2 seconds. LLM inference on a 4B Q4 model typically takes
    # 5-30s depending on max_tokens, so 90s timeout is generous.
    polls = int(timeout / 2)

    for _ in range(polls):
        time.sleep(2)
        try:
            req = urllib.request.Request(history_url)
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            # prompt_id won't appear in history until the job starts executing
            if prompt_id not in data:
                continue

            entry = data[prompt_id]

            # Check for execution errors (model not found, OOM, node crash, etc.)
            status = entry.get("status", {})
            if status.get("status_str") == "error":
                # ComfyUI packs error details into status.messages as
                # [["execution_error", {exception_message: "..."}], ...]
                err_msg = ""
                for msg in status.get("messages", []):
                    if msg[0] == "execution_error":
                        err_msg = msg[1].get("exception_message", "")
                return None, err_msg or "execution error"

            # Search all output nodes for text. Different LLM nodes use
            # different output key names, so we try several known variants.
            outputs = entry.get("outputs", {})
            for nid, node_out in outputs.items():
                for key in [output_key, "ENHANCED_OUTPUT", "RESPONSE",
                            "text", "string", "STRING", "generated_text"]:
                    if key in node_out:
                        val = node_out[key]
                        # ComfyUI wraps single outputs in a list
                        if isinstance(val, list):
                            return (val[0] if val else None), None
                        return str(val), None

            # outputs dict exists but is empty = job queued, not yet finished
            if not outputs:
                continue
            # Outputs present but no recognized text key — unexpected node output
            return None, None

        except Exception:
            continue  # Network hiccup — keep polling

    return None, None  # Timed out waiting for result


def _clean_output(text):
    """Clean LLM output — strip thinking blocks, markdown fences, etc.

    LLMs are unpredictable in their output formatting. Even with "output ONLY
    the prompt" instructions, they frequently wrap output in markdown fences,
    prepend labels, or include chain-of-thought reasoning blocks.
    Each pattern below addresses a real failure mode observed in production.
    """
    # Qwen3 models emit <think>...</think> reasoning blocks by default.
    # These can be hundreds of tokens and must be stripped before use.
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    # Some models wrap output in markdown code fences (```prompt\n...\n```)
    text = re.sub(r"^```\w*\n?", "", text)
    text = re.sub(r"\n?```$", "", text)
    # Strip common preamble phrases the LLM adds despite instructions not to.
    # Case-insensitive prefix match; we check startswith then slice by
    # the prefix length to preserve the rest exactly.
    for prefix in ["Enhanced prompt:", "Here is", "Here's", "Output:",
                   "Prompt:", "Enhanced:"]:
        if text.lower().startswith(prefix.lower()):
            text = text[len(prefix):].strip()
    # Some models wrap the entire output in double quotes
    if len(text) > 2 and text[0] == '"' and text[-1] == '"':
        text = text[1:-1]
    return text.strip()
