"""Guild LLM — embedded language model that lives inside ComfyUI.

Instead of requiring a separate KoboldCpp/Ollama instance, this uses
ComfyUI's own model management to load a small LLM for:
  - Conversational installation
  - Wizard Guild chat (when no external LLM is configured)
  - Image inspection and A/B testing feedback
  - Calibration result interpretation

The LLM auto-unloads when ComfyUI needs VRAM for generation, and
reloads after the queue clears. Zero manual management needed.

Architecture:
  TEXT:   Submit a simple workflow with a text generation node
  VISION: Submit Florence2/Moondream workflow, get image description,
          feed it to the text LLM for interpretation

Supported backends (auto-detected in priority order):
  1. ComfyUI LLM nodes (if installed) — zero external deps
  2. KoboldCpp (existing integration) — fallback
  3. Ollama API — secondary fallback

Model requirements (auto-downloaded during install):
  - Text: Qwen3-4B-Q4_K_M.gguf (~2.5GB) — instruction following
  - Vision: Florence-2 base (auto-downloaded by ComfyUI node)
"""

import json
import time
import urllib.request
import urllib.error


# ═══════════════════════════════════════════════════════════════════════
#  LLM Chat — text generation via ComfyUI or external backend
# ═══════════════════════════════════════════════════════════════════════

# Recommended smallest LLM for scaffolding (auto-downloaded by installer)
RECOMMENDED_LLM = {
    "model": "Qwen3-4B-Q8_0.gguf",
    "download_url": "https://huggingface.co/Qwen/Qwen3-4B-GGUF/resolve/main/qwen3-4b-q4_k_m.gguf",
    "size_gb": 2.5,
    "description": "Qwen3 4B — excellent instruction following, multilingual, small footprint",
}


def chat(message, system_prompt="", server=None, kobold_url=None,
         model=None, max_tokens=512, temperature=0.7):
    """Send a message to the best available LLM backend.

    Tries in order: ComfyUI LLM nodes -> KoboldCpp -> Ollama
    Returns the response text, or None if no backend available.

    The LLM auto-unloads from VRAM during ComfyUI generation and
    reloads after the queue clears — no manual management needed.
    """
    # Try ComfyUI LLM nodes first (zero external deps)
    if server:
        resp = _chat_comfyui(message, system_prompt, server, model,
                             max_tokens, temperature)
        if resp is not None:
            return resp

    # Try KoboldCpp (external server)
    if kobold_url:
        resp = _chat_kobold(message, system_prompt, kobold_url, max_tokens, temperature)
        if resp is not None:
            return resp

    # Try Ollama
    resp = _chat_ollama(message, system_prompt, max_tokens, temperature)
    if resp is not None:
        return resp

    # No LLM available
    return None


def _chat_comfyui(message, system_prompt, server, model, max_tokens, temperature):
    """Chat via ComfyUI's native LLM nodes (GGUF models loaded on server)."""
    try:
        from .comfyui_llm import generate_text
        return generate_text(
            server, prompt=message, system_prompt=system_prompt,
            model=model, max_tokens=max_tokens, temperature=temperature)
    except Exception:
        return None


def _chat_kobold(message, system_prompt, url, max_tokens, temperature):
    """Chat via KoboldCpp's OpenAI-compatible API."""
    try:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": message})

        body = json.dumps({
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }).encode()
        req = urllib.request.Request(
            f"{url.rstrip('/')}/v1/chat/completions",
            data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
            return data["choices"][0]["message"]["content"]
    except Exception:
        return None


def _chat_ollama(message, system_prompt, max_tokens, temperature):
    """Chat via Ollama's API (if running locally)."""
    for port in [11434, 11435]:
        try:
            body = json.dumps({
                "model": "qwen3:4b",
                "messages": [
                    {"role": "system", "content": system_prompt} if system_prompt else None,
                    {"role": "user", "content": message},
                ],
                "stream": False,
                "options": {"num_predict": max_tokens, "temperature": temperature},
            }).encode()
            # Filter None messages
            payload = json.loads(body)
            payload["messages"] = [m for m in payload["messages"] if m]
            body = json.dumps(payload).encode()

            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/chat",
                data=body, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read())
                return data.get("message", {}).get("content", "")
        except Exception:
            continue
    return None


# ═══════════════════════════════════════════════════════════════════════
#  Vision — image inspection via ComfyUI nodes
# ═══════════════════════════════════════════════════════════════════════

def describe_image(image_filename, server, method="auto"):
    """Get a text description of an image using ComfyUI vision nodes.

    The vision model loads into VRAM, runs inference, then auto-unloads
    when the next generation job arrives. ComfyUI manages this natively.

    Methods:
      "florence2" — Microsoft Florence-2 (best quality, ~1GB VRAM)
      "moondream" — Moondream2 (smallest, ~1GB)
      "joycaption" — JoyCaption (detailed, art-focused)
      "auto" — tries florence2 -> moondream -> joycaption

    Returns description string, or None if no vision node available.
    """
    if method == "auto":
        for m in ["florence2", "moondream", "joycaption"]:
            result = describe_image(image_filename, server, method=m)
            if result:
                return result
        return None

    wf = _build_vision_workflow(image_filename, method)
    if not wf:
        return None

    try:
        body = json.dumps({"prompt": wf}).encode()
        req = urllib.request.Request(
            f"{server}/prompt", data=body,
            headers={"Content-Type": "application/json"})
        r = urllib.request.urlopen(req, timeout=10)
        pid = json.loads(r.read()).get("prompt_id")
        if not pid:
            return None

        # Poll for result
        for _ in range(60):
            time.sleep(1)
            try:
                r2 = urllib.request.urlopen(f"{server}/history/{pid}", timeout=5)
                d = json.loads(r2.read())
                if pid in d:
                    st = d[pid].get("status", {})
                    if st.get("completed"):
                        # Extract text output
                        for out in d[pid].get("outputs", {}).values():
                            # Florence2 outputs text in "text" key
                            if "text" in out:
                                return out["text"][0] if isinstance(out["text"], list) else str(out["text"])
                            # Some nodes output in "string"
                            if "string" in out:
                                return out["string"][0] if isinstance(out["string"], list) else str(out["string"])
                        return None
                    for msg in st.get("messages", []):
                        if msg[0] == "execution_error":
                            return None
            except Exception:
                pass
        return None
    except Exception:
        return None


def _build_vision_workflow(image_filename, method):
    """Build a ComfyUI workflow for image description."""
    if method == "florence2":
        return {
            "1": {"class_type": "Florence2ModelLoader",
                  "inputs": {"model": "florence-2-base", "precision": "fp16"}},
            "2": {"class_type": "LoadImage",
                  "inputs": {"image": image_filename}},
            "3": {"class_type": "Florence2Run",
                  "inputs": {
                      "model": ["1", 0],
                      "processor": ["1", 1],
                      "image": ["2", 0],
                      "task": "detailed_caption",
                      "text_input": "",
                      "max_new_tokens": 256,
                      "num_beams": 3,
                  }},
        }

    elif method == "moondream":
        return {
            "1": {"class_type": "LoadImage",
                  "inputs": {"image": image_filename}},
            "2": {"class_type": "MoondreamQuery",
                  "inputs": {
                      "image": ["1", 0],
                      "question": "Describe this image in detail. Include style, subject, composition, lighting, and quality.",
                  }},
        }

    elif method == "joycaption":
        return {
            "1": {"class_type": "LoadImage",
                  "inputs": {"image": image_filename}},
            "2": {"class_type": "JoyCaption",
                  "inputs": {
                      "image": ["1", 0],
                      "caption_type": "descriptive",
                  }},
        }

    return None


def inspect_generation(image_filename, server, kobold_url=None, original_prompt=""):
    """Inspect a generated image and provide quality feedback.

    Combines vision (Florence2/Moondream) with text LLM to analyze
    whether a generated image matches the original prompt and is
    good quality.

    Returns dict with:
      description: what the vision model sees
      matches_prompt: bool
      quality_notes: list of observations
      suggestions: list of improvement suggestions
    """
    # Step 1: Get image description via vision model
    desc = describe_image(image_filename, server)
    if not desc:
        return {"description": None, "error": "No vision model available"}

    # Step 2: Ask LLM to evaluate
    eval_prompt = f"""You are an AI image quality evaluator. Analyze this generated image.

Original prompt: "{original_prompt}"
Vision model description: "{desc}"

Evaluate:
1. Does the image match the prompt? (yes/no)
2. Quality issues? (list any: blurry, distorted, wrong colors, etc.)
3. Suggestions to improve? (more steps, different CFG, add LoRA, etc.)

Reply in JSON format:
{{"matches_prompt": true/false, "quality_notes": ["note1", ...], "suggestions": ["suggestion1", ...]}}"""

    llm_response = chat(eval_prompt, kobold_url=kobold_url)

    result = {
        "description": desc,
        "matches_prompt": True,
        "quality_notes": [],
        "suggestions": [],
    }

    if llm_response:
        try:
            # Try to parse JSON from LLM response
            import re
            json_match = re.search(r'\{[^{}]+\}', llm_response, re.DOTALL)
            if json_match:
                parsed = json.loads(json_match.group())
                result.update(parsed)
        except Exception:
            result["quality_notes"] = [llm_response[:200]]

    return result


# ═══════════════════════════════════════════════════════════════════════
#  A/B Testing — generate variations, ask user to pick
# ═══════════════════════════════════════════════════════════════════════

def generate_ab_test(prompt, server, num_variants=3, **gen_kwargs):
    """Generate multiple variations and describe each for comparison.

    Returns list of dicts:
      [{"image": filename, "description": text, "settings": {...}}, ...]
    """
    try:
        from .pipeline import Pipeline
    except ImportError:
        from spellcaster_core.pipeline import Pipeline

    variants = []
    for i in range(num_variants):
        # Vary settings slightly
        import random
        p = Pipeline(server, verbose=False)
        kwargs = dict(gen_kwargs)
        kwargs["seed"] = random.randint(1, 2**32 - 1)

        # Vary CFG slightly for each variant
        base_cfg = kwargs.get("cfg") or 7.0
        cfg_variants = [base_cfg * 0.8, base_cfg, base_cfg * 1.2]
        kwargs["cfg"] = cfg_variants[i % len(cfg_variants)]

        results = p.txt2img(prompt, **kwargs).run()
        if results:
            fn = results[0][0]  # First output filename
            desc = describe_image(fn, server) or "No description available"
            variants.append({
                "image": fn,
                "description": desc,
                "settings": {"seed": kwargs["seed"], "cfg": kwargs["cfg"]},
                "variant": i + 1,
            })

    return variants
