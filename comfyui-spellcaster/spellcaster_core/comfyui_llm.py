"""ComfyUI-native LLM — text generation via GGUF nodes on the ComfyUI server.

Instead of requiring a separate KoboldCpp/Ollama server, this module
discovers LLM-capable nodes already installed on the ComfyUI server and
submits text-generation workflows through the standard /prompt API.

The ComfyUI server handles VRAM management natively — the LLM auto-unloads
when image generation needs VRAM, and reloads when queried again.

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


def _pick_model(models, exclude=None):
    """Choose the best model from the available list.

    Skips models in _failed_models (not downloaded) and any in exclude set.
    """
    # Combine permanently-failed models with this call's exclusion set
    skip = _failed_models | (exclude or set())
    available = [m for m in models if m not in skip]
    if not available:
        # All models have failed at some point — reset and try again.
        # This handles the edge case where a model was re-downloaded since
        # the last attempt.
        available = models

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
                  max_tokens=300, temperature=0.7):
    """Generate text via a ComfyUI LLM node.

    Builds a single-node workflow, submits it, and polls for the result.
    If the chosen model isn't downloaded, automatically retries with the
    next best model (up to 3 attempts).

    Returns the generated text string, or None on any failure.
    This function never raises — all errors return None so callers
    can fall through to the next LLM backend.
    """
    url = comfy_url.rstrip("/")

    try:
        info = discover_llm(url)
        if not info:
            return None

        tried = set()
        # If caller specified a model, don't retry with alternatives —
        # they asked for that specific model. Otherwise try up to 3
        # different models from the preference list.
        max_retries = 3 if model is None else 1

        for attempt in range(max_retries):
            chosen = model if model else _pick_model(info["models"],
                                                     exclude=tried)
            if chosen in tried:
                break  # _pick_model returned one we already tried = exhausted
            tried.add(chosen)

            wf = _build_workflow(info, prompt, system_prompt, chosen,
                                 max_tokens, temperature)

            pid = _submit(url, wf)
            if not pid:
                return None  # Server unreachable or rejected the workflow

            text, error = _poll_result(url, pid, info["output_name"],
                                       timeout=90)

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
                    max_tokens, temperature):
    """Build a ComfyUI workflow for text generation.

    Includes an output node (required by ComfyUI) that captures the
    generated text so it appears in /history/{prompt_id} outputs.
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
