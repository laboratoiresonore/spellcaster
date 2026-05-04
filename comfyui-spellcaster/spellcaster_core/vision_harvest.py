"""Vision-LLM appearance harvester.

Sends an image to a local Ollama vision model (default qwen2.5-vl-7b) and
extracts structured appearance facts: age, gender, build, skin, hair, eyes,
distinctive features. The output dict is consumed by PASSPORT_PROMPT_TEMPLATE
to produce a Klein-friendly passport prompt.

Defensive at the network boundary: any Ollama failure (server down, model
not loaded, malformed JSON) returns ``None`` instead of raising. Callers
should surface "vision harvest unavailable" and fall back to a generic
prompt.

Usage:
    from spellcaster_core.vision_harvest import harvest_appearance, build_passport_prompt
    facts = harvest_appearance("avatar.png")
    if facts:
        prompt = build_passport_prompt(facts)

Smoke test:
    python -m spellcaster_core.vision_harvest path/to/image.png
"""
from __future__ import annotations

import base64
import json
import logging
import re
import sys
import urllib.error
import urllib.request
from typing import Optional, Union

LOG = logging.getLogger(__name__)

DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"
DEFAULT_MODEL = "qwen2.5-vl-7b"

# The vision model is asked to emit JSON with these exact keys. Any
# missing key falls back to "" so PASSPORT_PROMPT_TEMPLATE can still
# format a usable string.
_FIELDS = ("age", "gender", "build", "skin", "hair", "eyes", "features")

_EXTRACTION_PROMPT = (
    "Look at this person's face and describe their physical appearance in "
    "concise comma-separated facts. Return ONLY a JSON object with these "
    "keys (no commentary, no markdown):\n"
    '  "age": apparent age (e.g. "28" or "mid-30s")\n'
    '  "gender": "woman" / "man" / "androgynous"\n'
    '  "build": body build (e.g. "slim", "athletic", "stocky")\n'
    '  "skin": skin description (e.g. "fair freckled", "warm brown", "olive")\n'
    '  "hair": hair description (e.g. "long wavy chestnut", "short black undercut")\n'
    '  "eyes": eye color and shape (e.g. "green almond-shaped")\n'
    '  "features": 1-3 distinctive features (e.g. "dimples, small nose stud")\n'
    "If unsure of a field, give a best-effort guess from visual context."
)

PASSPORT_PROMPT_TEMPLATE = (
    "professional passport photograph of a {age}yo {build} {gender}, "
    "{skin} skin, {hair} hair, {eyes}, {features}, neutral expression, "
    "looking directly at camera, plain studio backdrop, even softbox lighting, "
    "sharp focus on face, shoulders visible, photorealistic, 50mm lens, "
    "shallow depth of field"
)


def _read_image_b64(image: Union[bytes, str]) -> Optional[str]:
    if isinstance(image, (bytes, bytearray)):
        return base64.b64encode(bytes(image)).decode("ascii")
    if isinstance(image, str):
        try:
            with open(image, "rb") as f:
                return base64.b64encode(f.read()).decode("ascii")
        except OSError as e:
            LOG.warning("vision_harvest: cannot read image %r: %s", image, e)
            return None
    LOG.warning("vision_harvest: unsupported image type %s", type(image))
    return None


def _coerce_to_dict(payload: str) -> dict:
    """Parse Ollama's response 'response' field into a fact dict.

    Ollama with format='json' usually returns clean JSON, but some
    smaller vision models drift (extra commentary, code fences). We try
    strict JSON first, then fall back to per-field regex extraction so
    a partially-broken response still yields *something* usable.
    """
    text = (payload or "").strip()
    if not text:
        return {}
    # Strip code-fence wrapping the model sometimes adds despite format='json'.
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text).strip()
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return {k: str(data.get(k, "")).strip() for k in _FIELDS}
    except (json.JSONDecodeError, TypeError):
        pass
    # Regex fallback: find "key": "value" pairs anywhere in the blob.
    out = {}
    for k in _FIELDS:
        m = re.search(rf'"{k}"\s*:\s*"([^"]*)"', text, flags=re.IGNORECASE)
        if m:
            out[k] = m.group(1).strip()
        else:
            out[k] = ""
    return out


def harvest_appearance(image: Union[bytes, str],
                       ollama_url: str = DEFAULT_OLLAMA_URL,
                       model: str = DEFAULT_MODEL,
                       timeout: float = 60.0) -> Optional[dict]:
    """Extract structured appearance facts from an image via Ollama vision.

    Args:
        image: Either a path to an image file (str) or raw image bytes.
        ollama_url: Base URL of the Ollama server (no trailing slash needed).
        model: Vision model tag (must already be pulled on the server).
        timeout: HTTP timeout in seconds.

    Returns:
        Dict with keys {age, gender, build, skin, hair, eyes, features}
        on success, or None if anything failed (server down, model
        missing, response unparseable). Never raises — boundary code.
    """
    b64 = _read_image_b64(image)
    if b64 is None:
        return None

    url = ollama_url.rstrip("/") + "/api/generate"
    body = json.dumps({
        "model": model,
        "prompt": _EXTRACTION_PROMPT,
        "images": [b64],
        "stream": False,
        "format": "json",
    }).encode("utf-8")

    req = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        LOG.warning("vision_harvest: Ollama request failed: %s", e)
        return None

    try:
        envelope = json.loads(raw)
    except json.JSONDecodeError as e:
        LOG.warning("vision_harvest: Ollama envelope unparseable: %s", e)
        return None
    if not isinstance(envelope, dict):
        LOG.warning("vision_harvest: Ollama envelope not a dict: %r", envelope)
        return None
    if envelope.get("error"):
        LOG.warning("vision_harvest: Ollama returned error: %s",
                    envelope.get("error"))
        return None

    facts = _coerce_to_dict(envelope.get("response", ""))
    if not any(facts.get(k) for k in _FIELDS):
        LOG.warning("vision_harvest: empty harvest from %s", model)
        return None
    return facts


def build_passport_prompt(facts: dict) -> str:
    """Render PASSPORT_PROMPT_TEMPLATE with safe defaults for missing keys."""
    safe = {k: (str(facts.get(k, "") or "").strip() or _DEFAULTS[k])
            for k in _FIELDS}
    return PASSPORT_PROMPT_TEMPLATE.format(**safe)


_DEFAULTS = {
    "age": "30",
    "gender": "person",
    "build": "average",
    "skin": "neutral",
    "hair": "natural",
    "eyes": "expressive eyes",
    "features": "approachable face",
}


def _smoke():
    if len(sys.argv) < 2:
        print("usage: python -m spellcaster_core.vision_harvest <image_path> "
              "[ollama_url] [model]")
        return 2
    image = sys.argv[1]
    url = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_OLLAMA_URL
    model = sys.argv[3] if len(sys.argv) > 3 else DEFAULT_MODEL
    logging.basicConfig(level=logging.INFO,
                        format="%(levelname)s %(name)s: %(message)s")
    facts = harvest_appearance(image, ollama_url=url, model=model)
    if facts is None:
        print("HARVEST FAILED — see warnings above")
        return 1
    print("HARVESTED FACTS:")
    print(json.dumps(facts, indent=2))
    print()
    print("PASSPORT PROMPT:")
    print(build_passport_prompt(facts))
    return 0


if __name__ == "__main__":
    sys.exit(_smoke())
