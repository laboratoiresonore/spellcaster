"""Vision-based quality scorer for LoRA calibration samples.

Given a rendered sample (as base64 PNG bytes) and the prompt the
sample was rendered from, ask a local multimodal LLM (Ollama
`gemma3:4b` by default) whether the image matches the prompt and
looks clean, and return a 0-10 score.

The auto-calibration flow uses this to short-circuit "the user
confirms every card" into "auto-confirm everything the model scored
≥ threshold" and only surface the borderline / low-scoring samples
for human attention.

Failure modes (model unavailable, bad JSON, timeout) never raise —
callers get `{"ok": False, "error": "..."}` and should treat scoring
as optional. The calibration pipeline still works with scoring off.
"""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, asdict
from typing import Optional


DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"
DEFAULT_MODEL = "gemma3:4b"
DEFAULT_TIMEOUT = 45.0

# Hard bounds — the LLM sometimes returns 15 / "11/10" / other noise.
MIN_SCORE = 0.0
MAX_SCORE = 10.0


_PROMPT_TEMPLATE = (
    "You are a calibration judge for a text-to-image model. An AI "
    "just rendered the attached image from this prompt:\n\n"
    "PROMPT: {prompt}\n\n"
    "Rate the image on a scale of 0 to 10 for BOTH:\n"
    "  (a) how well it matches the prompt's subject and style, and\n"
    "  (b) whether it's visually clean (no broken anatomy, no "
    "artifacts, no heavy noise).\n\n"
    "A score of 10 means the image is on-prompt and clean. 5 means "
    "it's roughly on-prompt but has visible issues. 0 means it's "
    "unrecognisable or completely off-prompt.\n\n"
    "Respond with ONLY a JSON object in this shape (no prose):\n"
    '{{"score": <float 0-10>, "reason": "<one short sentence>"}}'
)


@dataclass
class ScoreResult:
    ok: bool
    score: Optional[float] = None       # 0-10 inclusive
    reason: str = ""
    model: str = ""
    elapsed_ms: int = 0
    error: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _extract_score_json(text: str) -> Optional[dict]:
    """Pull a {score, reason} JSON object from `text`. Tolerates the
    model wrapping its response in prose, markdown fences, or extra
    keys. Returns None on complete failure."""
    if not text:
        return None
    text = text.strip()
    # Fast path: pure JSON.
    try:
        obj = json.loads(text)
        if isinstance(obj, dict) and "score" in obj:
            return obj
    except (json.JSONDecodeError, ValueError):
        pass
    # Look for the first { ... } block. Non-greedy so we don't swallow
    # a second object if the model got chatty.
    for m in re.finditer(r"\{[^{}]*\}", text):
        try:
            obj = json.loads(m.group(0))
            if isinstance(obj, dict) and "score" in obj:
                return obj
        except (json.JSONDecodeError, ValueError):
            continue
    # Last-resort: scrape a number from any "score" line.
    m = re.search(r"score[\s:=]*([0-9]+(?:\.[0-9]+)?)", text, re.IGNORECASE)
    if m:
        try:
            return {"score": float(m.group(1)), "reason": ""}
        except ValueError:
            pass
    return None


def _clamp_score(raw) -> Optional[float]:
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return None
    # Some models return "80" (percent-like) or "11/10" (overshoot).
    # Rescale ONLY for clearly percent-scale answers (>20 on a 0-10
    # rubric is unambiguously wrong-scale), and clamp small overshoots.
    if v > 100:
        return None
    if 20 < v <= 100:
        v = v / 10.0
    if v < MIN_SCORE:
        v = MIN_SCORE
    if v > MAX_SCORE:
        v = MAX_SCORE
    return round(v, 2)


def score_image(
    image_b64: str,
    prompt: str,
    *,
    ollama_url: str = DEFAULT_OLLAMA_URL,
    model: str = DEFAULT_MODEL,
    timeout: float = DEFAULT_TIMEOUT,
) -> ScoreResult:
    """Send the image + prompt to Ollama, return a ScoreResult.

    `image_b64` is the raw PNG bytes base64-encoded (no `data:...;base64,`
    prefix — Ollama expects naked base64). Network / parse failures are
    swallowed into ScoreResult.error so the calibration pipeline keeps
    moving.
    """
    t0 = time.time()
    if not image_b64:
        return ScoreResult(ok=False, error="no image", model=model)
    if not prompt:
        prompt = "(empty prompt)"
    host = (ollama_url or DEFAULT_OLLAMA_URL).rstrip("/")
    endpoint = host + "/api/chat"
    payload = {
        "model": model,
        "messages": [{
            "role": "user",
            "content": _PROMPT_TEMPLATE.format(prompt=prompt[:1500]),
            "images": [image_b64],
        }],
        "stream": False,
        "format": "json",
        "options": {
            "temperature": 0.1,          # scorer should be ~deterministic
            "num_predict": 120,
        },
    }
    try:
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            endpoint, data=body, method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return ScoreResult(
                    ok=False, model=model,
                    error=f"HTTP {resp.status} from Ollama",
                    elapsed_ms=int((time.time() - t0) * 1000),
                )
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return ScoreResult(
            ok=False, model=model,
            error=f"HTTP {e.code}: {e.reason}"[:160],
            elapsed_ms=int((time.time() - t0) * 1000),
        )
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return ScoreResult(
            ok=False, model=model,
            error=f"network: {e!s}"[:160],
            elapsed_ms=int((time.time() - t0) * 1000),
        )
    try:
        outer = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return ScoreResult(
            ok=False, model=model,
            error="non-JSON Ollama response",
            elapsed_ms=int((time.time() - t0) * 1000),
        )
    content = ((outer or {}).get("message") or {}).get("content") or ""
    parsed = _extract_score_json(content)
    if not parsed:
        return ScoreResult(
            ok=False, model=model,
            error=f"bad content: {content[:120]!r}",
            elapsed_ms=int((time.time() - t0) * 1000),
        )
    score = _clamp_score(parsed.get("score"))
    if score is None:
        return ScoreResult(
            ok=False, model=model,
            error=f"unparseable score: {parsed.get('score')!r}",
            elapsed_ms=int((time.time() - t0) * 1000),
        )
    return ScoreResult(
        ok=True,
        score=score,
        reason=str(parsed.get("reason") or "")[:200],
        model=model,
        elapsed_ms=int((time.time() - t0) * 1000),
    )


def probe_available(
    ollama_url: str = DEFAULT_OLLAMA_URL,
    model: str = DEFAULT_MODEL,
    timeout: float = 3.0,
) -> dict:
    """Check whether the scorer model is actually installed on the
    Ollama host. Returns {"ok": bool, "model": str, "reason": str}.
    Used by the UI to gray out the "auto-confirm" toggle when
    scoring can't work.
    """
    host = (ollama_url or DEFAULT_OLLAMA_URL).rstrip("/")
    try:
        req = urllib.request.Request(host + "/api/tags")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return {"ok": False, "model": model,
                        "reason": f"HTTP {resp.status}"}
            raw = resp.read().decode("utf-8", errors="replace")
        data = json.loads(raw)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError,
            OSError, json.JSONDecodeError, ValueError) as e:
        return {"ok": False, "model": model,
                "reason": f"unreachable: {e!s}"[:120]}
    models = [m.get("name", "") for m in (data.get("models") or [])]
    # Match either exact tag ("gemma3:4b") or prefix ("gemma3:4b-q4_K_M").
    exact = model in models
    prefix = any(n.startswith(model + ":") or n.startswith(model + "-")
                  for n in models)
    if not (exact or prefix):
        return {"ok": False, "model": model,
                "reason": f"not installed (have: {', '.join(models[:5])})",
                "installed": models}
    return {"ok": True, "model": model, "reason": "", "installed": models}


__all__ = [
    "DEFAULT_OLLAMA_URL",
    "DEFAULT_MODEL",
    "ScoreResult",
    "score_image",
    "probe_available",
]
