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
import threading
import urllib.parse
import urllib.request
import urllib.error


# ═══════════════════════════════════════════════════════════════════════
#  Live status — surfaced by the Guild UI as "LLM: <Host>:<Backend>"
# ═══════════════════════════════════════════════════════════════════════
# Any call that crosses chat() updates this snapshot. It is the single
# source of truth for the sidebar LLM indicator — the Guild polls it via
# /api/llm_status, which calls get_status() below.

_STATUS_LOCK = threading.Lock()
_STATUS = {
    "backend": None,    # "ollama" | "comfyui" | "kobold" | None
    "host": None,       # human label — "Local", "Theo", hostname, etc.
    "host_url": None,   # raw url (no personal data leaked to UI layer)
    "state": "idle",    # "idle" | "busy" | "reloading" | "unloaded" | "error"
    "model": None,
    "purpose": None,
    "last_used_at": 0.0,
    "last_error": None,
}


def _set_status(**kwargs):
    """Merge into the module-level status dict under the lock."""
    with _STATUS_LOCK:
        _STATUS.update(kwargs)


def get_status():
    """Return a snapshot of the current LLM state. UI polls this."""
    with _STATUS_LOCK:
        return dict(_STATUS)


def mark_state(state, **extra):
    """Public hook for backends to announce fine-grained transitions
    (e.g. comfyui_llm can flip to 'reloading' when swapping models)."""
    _set_status(state=state, **extra)


def _host_label(url):
    """Turn a URL like http://192.168.x.x:8188 into 'LAN' / 'Local'.
    Short, user-friendly, no IP leak in the UI. Falls back to host[:port]."""
    if not url:
        return "?"
    try:
        parsed = urllib.parse.urlparse(url)
        host = (parsed.hostname or "").lower()
    except Exception:
        return "?"
    if not host or host in ("127.0.0.1", "localhost", "::1"):
        return "Local"
    # Strip first label if it's numeric (IP) — expose bare hostname or
    # first octet pair ('192.168.x.x' → 'LAN'). Prefer a user-friendly
    # alias if the caller wired one via set_host_alias below.
    alias = _HOST_ALIASES.get(host)
    if alias:
        return alias
    if host.replace(".", "").isdigit():
        return "LAN"
    # Just the first dotted part — "theo.local" → "theo"
    return host.split(".")[0].capitalize()


_HOST_ALIASES = {}


def set_host_alias(host, alias):
    """Map an IP or hostname to a friendly label (used by the UI)."""
    if host and alias:
        _HOST_ALIASES[host.lower()] = alias


# ── Preferred backend ─────────────────────────────────────────────────
# The user can pin one of the three chat backends (comfyui / ollama /
# kobold) as their primary via the sidebar LLM picker. chat() rotates
# the backend chain so the pinned one is tried first; the rest stay in
# the chain as live fallbacks. Nothing is ever disabled — it's OK to
# have ComfyUI + Ollama + Kobold all running at once, the preference
# just decides who answers first.

_PREFERRED_BACKEND = None   # None = use the purpose-default chain order


def set_preferred_backend(name):
    """Store the user's chosen primary backend. Pass None to revert to
    the purpose-driven default chain."""
    global _PREFERRED_BACKEND
    if name is None:
        _PREFERRED_BACKEND = None
        return
    name = str(name).strip().lower()
    # kobold_rp is the chat variant; kobold_tts is STT-only and should
    # not participate in chat rotation.
    if name == "kobold_rp":
        name = "kobold"
    if name in ("comfyui", "ollama", "kobold"):
        _PREFERRED_BACKEND = name


def get_preferred_backend():
    return _PREFERRED_BACKEND


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
         model=None, max_tokens=512, temperature=0.7, purpose="chat",
         arch_key=None, method=None):
    """THE single LLM entry point for every surface (Guild, GIMP, Darktable,
    ComfyUI nodes, scaffolding). Do not implement parallel LLM paths
    elsewhere — everything goes through this function.

    arch_key (optional): diffusion family (sdxl, sd15, flux1dev,
    flux2klein, chroma, illustrious, pony, wan, ltx, flux_kontext).
    Reaches comfyui_llm.generate_text for per-family VRAM management:
    model size/quant caps, keep_model_loaded override, poll timeout.
    Ignored by Ollama / Kobold backends — they manage their own memory.

    Tries every available backend in an order determined by `purpose`:

      purpose='chat' (default): conversation / scaffolding / wizard replies.
          Backend priority: Ollama local -> ComfyUI nodes -> KoboldCpp.
          WHY: the ComfyUI AILab_QwenVL_GGUF_PromptEnhancer node is
          hard-wired to rewrite any input as an image-generation prompt,
          which ruins conversation. Ollama runs a general-purpose chat
          model that honours system prompts and can hold a dialog. For
          wizard Guild chat, scaffolded install flows, and anything
          conversational, ALWAYS prefer Ollama when available.

      purpose='enhance': single-shot prompt enhancement for image gen.
          Backend priority: ComfyUI nodes -> Ollama local -> KoboldCpp.
          WHY: the AILab_QwenVL node is purpose-built for this, it's
          already on the ComfyUI box, and its VRAM is auto-managed
          against the diffusion model (the load-LLM / unload-LLM /
          generate / reload-LLM cycle). For the prompt-enhancement
          use case that's the right tool.

    Returns the response text, or None if every backend fails.
    """
    if purpose not in ("chat", "enhance"):
        purpose = "chat"

    # Scheme + host clamp on caller-supplied backend URLs. guild_llm is
    # imported by plugins (GIMP, Darktable, Resolve) that take these
    # URLs from config files or /settings endpoints — an attacker who
    # can tamper with those surfaces could otherwise smuggle
    # `file://` or `gopher://` URLs that urllib follows blindly.
    def _valid_backend_url(u):
        if not isinstance(u, str) or not u:
            return False
        try:
            import urllib.parse as _up
            p = _up.urlparse(u)
            return p.scheme in ("http", "https") and bool(p.netloc)
        except Exception:
            return False
    if server is not None and not _valid_backend_url(server):
        server = None
    if kobold_url is not None and not _valid_backend_url(kobold_url):
        kobold_url = None

    # Build the backend sequence based on purpose.
    def try_ollama():
        return _chat_ollama(message, system_prompt, max_tokens,
                            temperature, model=model)

    def try_comfyui():
        if not server:
            return None
        return _chat_comfyui(message, system_prompt, server, model,
                             max_tokens, temperature,
                             arch_key=arch_key, method=method)

    def try_kobold():
        if not kobold_url:
            return None
        return _chat_kobold(message, system_prompt, kobold_url,
                            max_tokens, temperature)

    if purpose == "chat":
        chain = [
            ("ollama", "http://127.0.0.1:11434", try_ollama),
            ("comfyui", server, try_comfyui),
            ("kobold", kobold_url, try_kobold),
        ]
    else:  # 'enhance'
        chain = [
            ("comfyui", server, try_comfyui),
            ("ollama", "http://127.0.0.1:11434", try_ollama),
            ("kobold", kobold_url, try_kobold),
        ]
    # Honour the user's pinned primary backend (if any). Move the
    # matching tuple to the front of the chain; leave the rest in
    # place as live fallbacks. ComfyUI stays a valid "reroute" choice
    # — it won't be skipped even when another backend is preferred.
    pref = _PREFERRED_BACKEND
    if pref:
        for i, entry in enumerate(chain):
            if entry[0] == pref and i != 0:
                chain.insert(0, chain.pop(i))
                break

    for backend_name, backend_url, backend in chain:
        _set_status(state="busy", backend=backend_name,
                    host=_host_label(backend_url), host_url=backend_url,
                    purpose=purpose, model=model, last_error=None)
        try:
            resp = backend()
        except Exception as e:
            _set_status(state="error", last_error=str(e)[:120])
            resp = None
        if resp is not None:
            _set_status(state="idle", last_used_at=time.time(),
                        last_error=None)
            return resp
    _set_status(state="error",
                last_error="All LLM backends exhausted")
    return None  # every backend exhausted


def _chat_comfyui(message, system_prompt, server, model, max_tokens,
                   temperature, arch_key=None, method=None):
    """Chat via ComfyUI's native LLM nodes (GGUF models loaded on server).

    Forwards arch_key + method so generate_text can apply:
      - per-family VRAM caps / keep_model_loaded (_PER_FAMILY_LLM_CONFIG)
      - per-method preset selection on the AILab node (_METHOD_PRESET)
    """
    try:
        from .comfyui_llm import generate_text
        return generate_text(
            server, prompt=message, system_prompt=system_prompt,
            model=model, max_tokens=max_tokens, temperature=temperature,
            arch_key=arch_key, method=method)
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


# Ollama model preference — first substring match on installed models wins.
# Instruction-tuned chat models beat base completion models; smaller
# quantisations beat huge ones so the LLM doesn't fight the diffusion
# model for VRAM. Anything not matching stays eligible as a last resort
# so single-model installs still work.
_OLLAMA_MODEL_PREFERENCE = (
    "qwen3:4b", "qwen2.5:7b", "qwen2.5:3b",
    "gemma3:4b", "gemma2:9b", "gemma2:2b",
    "llama3.2:3b", "llama3.1:8b",
    "phi3:3.8b", "phi3:mini",
    "mistral:7b",
)
# Host → best-installed model, TTL'd so /api/tags isn't hammered.
_OLLAMA_CACHE = {}
_OLLAMA_CACHE_TTL = 300.0


def _ollama_pick_model(host):
    """Probe Ollama /api/tags and return the best installed model.

    Cached per-host for 5 min. Returns None if Ollama isn't reachable or
    has no models installed.
    """
    now = time.time()
    cached = _OLLAMA_CACHE.get(host)
    if cached and now - cached[0] < _OLLAMA_CACHE_TTL:
        return cached[1]
    try:
        req = urllib.request.Request(f"{host}/api/tags")
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        _OLLAMA_CACHE[host] = (now, None)
        return None
    names = [m.get("name", "") for m in data.get("models", [])]
    if not names:
        _OLLAMA_CACHE[host] = (now, None)
        return None
    chosen = None
    for pref in _OLLAMA_MODEL_PREFERENCE:
        for n in names:
            if n.startswith(pref) or pref in n:
                chosen = n
                break
        if chosen:
            break
    if not chosen:
        chosen = names[0]
    _OLLAMA_CACHE[host] = (now, chosen)
    return chosen


def _chat_ollama(message, system_prompt, max_tokens, temperature, model=None):
    """Chat via Ollama's native /api/chat.

    Probes localhost on Ollama's default ports (11434, 11435) and uses
    whichever responds first. Model is auto-detected from /api/tags
    unless the caller passes one explicitly, so installs with gemma3,
    qwen2.5, llama3, or anything else work out of the box.
    """
    for port in (11434, 11435):
        host = f"http://127.0.0.1:{port}"
        mdl = model or _ollama_pick_model(host)
        if not mdl:
            continue
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": message})
        body = json.dumps({
            "model": mdl,
            "messages": messages,
            "stream": False,
            "options": {"num_predict": max_tokens, "temperature": temperature},
        }).encode()
        try:
            req = urllib.request.Request(
                f"{host}/api/chat",
                data=body, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read())
                content = data.get("message", {}).get("content", "")
                if content:
                    return content
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
    # Auto mode: try vision models in order of quality/reliability.
    # Florence2 is preferred (best accuracy, small footprint).
    # Moondream is the fallback (even smaller, slightly less accurate).
    # JoyCaption is last (art-focused, may not be installed).
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

        # Poll every 1 second for up to 60 seconds. Vision models (Florence2,
        # Moondream) typically finish in 3-15s depending on image size and GPU.
        for _ in range(60):
            time.sleep(1)
            try:
                r2 = urllib.request.urlopen(f"{server}/history/{pid}", timeout=5)
                d = json.loads(r2.read())
                if pid in d:
                    st = d[pid].get("status", {})
                    if st.get("completed"):
                        # Different vision nodes use different output key names.
                        # Florence2 -> "text", Moondream -> "string", etc.
                        for out in d[pid].get("outputs", {}).values():
                            if "text" in out:
                                return out["text"][0] if isinstance(out["text"], list) else str(out["text"])
                            if "string" in out:
                                return out["string"][0] if isinstance(out["string"], list) else str(out["string"])
                        return None  # completed but no text output found
                    # Check for execution errors (missing model, OOM, etc.).
                    # Vision LLM has no "partial success" concept (text
                    # is either generated or not), so error → None.
                    if st.get("status_str") == "error":
                        try:
                            from .dispatch import (
                                extract_execution_error,
                            )
                            err, _ = extract_execution_error(st)
                            print(f"[guild_llm] vision failed: {err[:200]}")
                        except ImportError:
                            pass
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
    # TWO-STEP PIPELINE:
    # Step 1: Vision model (Florence2/Moondream) generates a text description
    #         of what it actually sees in the image (no prompt knowledge).
    # Step 2: Text LLM compares the description against the original prompt
    #         to evaluate accuracy and suggest improvements.
    # This separation lets us use specialized models for each task.
    desc = describe_image(image_filename, server)
    if not desc:
        return {"description": None, "error": "No vision model available"}
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
            # LLMs often wrap JSON in markdown fences or add preamble text.
            # Extract the first {...} block via regex rather than parsing the
            # entire response. [^{}]+ ensures we grab a flat JSON object
            # (no nested braces), which is all we expect from the eval format.
            import re
            json_match = re.search(r'\{[^{}]+\}', llm_response, re.DOTALL)
            if json_match:
                parsed = json.loads(json_match.group())
                result.update(parsed)
        except Exception:
            # JSON parsing failed — save raw LLM response as a quality note
            # (truncated to 200 chars to avoid bloating the result dict).
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
        from .pipeline import Pipeline

    variants = []
    for i in range(num_variants):
        import random
        p = Pipeline(server, verbose=False)
        kwargs = dict(gen_kwargs)
        # Each variant gets a unique seed for different noise initialization
        kwargs["seed"] = random.randint(1, 2**32 - 1)

        # Vary CFG (classifier-free guidance) by +/-20% across variants.
        # This produces noticeably different outputs: lower CFG = more creative/loose,
        # higher CFG = more prompt-adherent/saturated. Three tiers cycle via modulo.
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
