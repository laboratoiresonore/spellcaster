"""Per-LoRA knowledge aggregator.

Shootouts and auto-calibration need more than a filename to pick a
sensible recipe. This module merges every source the app has:

  1. User-local registry / confirmation (caller supplies).
  2. Shipped community-curated defaults — `lora_calibrations_sfw.json`
     in this package, plus `lora_calibrations_nsfw.json` dropped in by
     the NSFW build when present.
  3. `.civitai.info` sidecar next to the LoRA file (A1111 convention).
  4. Safetensors `__metadata__` header (trigger words + training hints).
  5. Civitai public API by SHA256 hash — one-shot fetch, cached forever
     per hash. Skipped when offline or when the caller opts out.
  6. Heuristic defaults keyed on purpose_group + architecture.

Every source contributes what it can; later sources fill gaps left by
earlier ones. The final `LoraKnowledge` record never lies about where
each field came from — `provenance["recommended_weight"] == "civitai"`
tells the UI to badge that field as "Civitai recommendation" instead
of "community default".

This module lives in `spellcaster_core` because the Guild server, the
GIMP plugin, the Darktable bridge, and ComfyUI nodes all want the
exact same lookup logic. Per CLAUDE.md §3 it must stay in sync across
all 5 copies.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import struct
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field, asdict
from typing import Optional


# ── Constants ───────────────────────────────────────────────────────────

CIVITAI_API = "https://civitai.com/api/v1/model-versions/by-hash/{h}"
CIVITAI_TIMEOUT = 5.0
CIVITAI_USER_AGENT = "Spellcaster-LoRA-Knowledge/1.0"

# ComfyUI base-model strings → our arch keys.
_BASE_MODEL_MAP = {
    "sd 1.5":       "sd15",
    "sd 1.4":       "sd15",
    "sd 2.1":       "sd21",
    "sdxl 1.0":     "sdxl",
    "sdxl":         "sdxl",
    "sdxl turbo":   "sdxl",
    "sdxl lightning": "sdxl",
    "pony":         "sdxl",
    "illustrious":  "illustrious",
    "noobai":       "illustrious",
    "flux.1 d":     "flux1dev",
    "flux.1 s":     "flux1dev",
    "flux.1 kontext": "flux_kontext",
    "flux.2 klein": "flux2klein",
    "zit":          "zit",
    "z-image-turbo": "zit",
    "chroma":       "chroma",
    "wan video 1.3b": "wan",
    "wan video":    "wan",
    "wan 2.1":      "wan",
    "wan 2.2":      "wan",
    "hunyuan video": "hunyuan",
    "ltxv":         "ltx",
    "ltx":          "ltx",
}

# Keywords that, on their own, flag a LoRA as NSFW when Civitai has no
# opinion. Conservative list — false-positive on a benign LoRA just
# routes it to the NSFW calibration store in NSFW builds, which is
# harmless; false-NEGATIVE would leak NSFW into the SFW store, which
# is not. Err on the side of NSFW.
_NSFW_KEYWORDS = frozenset({
    "nsfw", "porn", "sex", "nude", "naked", "hentai", "explicit",
    "pussy", "vagina", "vulva", "penis", "cock", "dick", "cum",
    "cumshot", "blowjob", "oral", "anal", "tentacle", "bondage",
    "bdsm", "fetish", "erotic", "lewd", "ecchi", "r18", "r-18",
    "xxx", "18+", "adult",
})

# Trigger-word fields set by different trainers / Civitai conventions.
_METADATA_TRIGGER_FIELDS = (
    "ss_output_name",
    "ss_network_trigger",
    "ss_trigger_word",
    "ss_prompt_template",
    "modelspec.trigger_phrase",
    "trigger_phrase",
    "activation",
    "activation_text",
    "invocation",
)


# ── Knowledge record ────────────────────────────────────────────────────

@dataclass
class LoraKnowledge:
    """Everything we know about one LoRA, with per-field provenance.

    `provenance` maps each populated field name to the SOURCE label
    ("user" / "civitai" / "civitai_sidecar" / "shipped" / "safetensors"
    / "heuristic"). UI surfaces use this to show confidence badges.
    """
    name: str
    path: Optional[str] = None
    sha256: Optional[str] = None
    trigger_words: list[str] = field(default_factory=list)
    recommended_weight: Optional[float] = None
    recommended_sampler: Optional[str] = None
    recommended_cfg: Optional[float] = None
    base_model: Optional[str] = None        # normalised arch key
    example_prompts: list[str] = field(default_factory=list)
    civitai_url: Optional[str] = None
    civitai_model_id: Optional[int] = None
    civitai_version_id: Optional[int] = None
    nsfw: bool = False
    provenance: dict[str, str] = field(default_factory=dict)
    fetched_at: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


# ── Cache (in-process + on-disk) ────────────────────────────────────────

_CACHE_LOCK = threading.Lock()
_MEM_CACHE: dict[str, dict] = {}   # keyed by sha256 OR name-if-no-sha
_DISK_CACHE_PATH: Optional[str] = None


def set_cache_path(path: str) -> None:
    """Tell the module where to persist the Civitai hash cache.

    Callers (Guild server, GIMP plugin) pass their state dir so we
    don't fight over file locations. Safe to call multiple times; the
    last call wins.
    """
    global _DISK_CACHE_PATH
    with _CACHE_LOCK:
        _DISK_CACHE_PATH = path
        _load_disk_cache_locked()


def _load_disk_cache_locked() -> None:
    if not _DISK_CACHE_PATH or not os.path.exists(_DISK_CACHE_PATH):
        return
    try:
        with open(_DISK_CACHE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            entries = data.get("entries")
            if isinstance(entries, dict):
                _MEM_CACHE.update(entries)
    except Exception:
        pass


def _save_disk_cache_locked() -> None:
    if not _DISK_CACHE_PATH:
        return
    try:
        os.makedirs(os.path.dirname(_DISK_CACHE_PATH), exist_ok=True)
        tmp = _DISK_CACHE_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"entries": _MEM_CACHE, "saved_at": time.time()},
                      f, ensure_ascii=False, indent=1)
        os.replace(tmp, _DISK_CACHE_PATH)
    except Exception:
        pass


def clear_cache() -> None:
    with _CACHE_LOCK:
        _MEM_CACHE.clear()
        _save_disk_cache_locked()


# ── Safetensors header reader ───────────────────────────────────────────

def _read_safetensors_header(path: str) -> dict:
    try:
        with open(path, "rb") as f:
            raw_len = f.read(8)
            if len(raw_len) != 8:
                return {}
            header_len = struct.unpack("<Q", raw_len)[0]
            if header_len <= 0 or header_len > 64 * 1024 * 1024:
                return {}
            header_bytes = f.read(header_len)
        header = json.loads(header_bytes.decode("utf-8", errors="replace"))
        return header.get("__metadata__") or {}
    except Exception:
        return {}


def _extract_triggers_from_metadata(meta: dict) -> list[str]:
    triggers: list[str] = []
    for name in _METADATA_TRIGGER_FIELDS:
        val = meta.get(name)
        if not isinstance(val, str) or not val:
            continue
        for part in re.split(r"[,|;]+", val):
            p = part.strip()
            if p and p not in triggers and len(p) <= 64:
                triggers.append(p)
    if triggers:
        return triggers
    raw_freq = meta.get("ss_tag_frequency")
    if raw_freq:
        try:
            freq = json.loads(raw_freq) if isinstance(raw_freq, str) else raw_freq
            flat: dict[str, int] = {}
            if isinstance(freq, dict):
                for tags in freq.values():
                    if isinstance(tags, dict):
                        for tag, count in tags.items():
                            try:
                                flat[tag] = flat.get(tag, 0) + int(count)
                            except (TypeError, ValueError):
                                pass
            top = sorted(flat.items(), key=lambda kv: kv[1], reverse=True)[:3]
            triggers = [t for t, _c in top if t and len(t) <= 64]
        except Exception:
            pass
    return triggers


# ── Hash computation ────────────────────────────────────────────────────

def _sha256_of_file(path: str, chunk_size: int = 1024 * 1024) -> Optional[str]:
    """Compute full SHA-256. Cached to memory so multiple lookups for
    the same path don't re-read a multi-gigabyte checkpoint."""
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


# ── Civitai ─────────────────────────────────────────────────────────────

def _civitai_by_hash(sha256_hex: str, timeout: float = CIVITAI_TIMEOUT) -> Optional[dict]:
    """GET /model-versions/by-hash/{sha256}. Returns the parsed JSON or
    None on any failure. Does NOT raise — callers rely on graceful
    degradation."""
    if not sha256_hex:
        return None
    url = CIVITAI_API.format(h=sha256_hex)
    req = urllib.request.Request(url, headers={"User-Agent": CIVITAI_USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return None
            body = resp.read()
        return json.loads(body.decode("utf-8", errors="replace"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError,
            json.JSONDecodeError, ValueError):
        return None


def _read_civitai_sidecar(lora_path: str) -> Optional[dict]:
    """A1111 / Forge convention: `<lora>.civitai.info` JSON next to the
    LoRA file. Users often have these pre-downloaded for hundreds of
    LoRAs; reading them saves us an API call."""
    if not lora_path:
        return None
    candidates = [
        lora_path + ".civitai.info",
        os.path.splitext(lora_path)[0] + ".civitai.info",
    ]
    for p in candidates:
        try:
            if os.path.exists(p):
                with open(p, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception:
            continue
    return None


def _map_civitai_to_knowledge(civ: dict, k: LoraKnowledge) -> None:
    """Extract every field we care about from a Civitai response and
    patch it into `k`. Only fills fields that are still empty — caller
    order (user > shipped > civitai > safetensors > heuristic) is
    preserved by the ordering in `get_knowledge`."""
    if not isinstance(civ, dict):
        return

    # Trigger words — Civitai calls them "trainedWords".
    words = civ.get("trainedWords") or []
    if isinstance(words, list) and not k.trigger_words:
        clean = [str(w).strip() for w in words if isinstance(w, str) and w.strip()]
        if clean:
            k.trigger_words = clean[:10]
            k.provenance["trigger_words"] = "civitai"

    # Base model — the arch-identifying string on the version record.
    base = str(civ.get("baseModel") or "").lower().strip()
    if base and not k.base_model:
        mapped = _BASE_MODEL_MAP.get(base)
        if not mapped:
            # Prefix-match common variants ("SDXL 1.0 LCM" → sdxl).
            for key, val in _BASE_MODEL_MAP.items():
                if base.startswith(key):
                    mapped = val
                    break
        if mapped:
            k.base_model = mapped
            k.provenance["base_model"] = "civitai"

    # NSFW flag — Civitai sets `nsfw` on the model record; the version
    # response nests it under `model`.
    model_info = civ.get("model") or {}
    if isinstance(model_info, dict):
        if model_info.get("nsfw"):
            k.nsfw = True
            k.provenance["nsfw"] = "civitai"
        # Model URL lets the UI link out.
        model_id = model_info.get("id")
        if isinstance(model_id, int):
            k.civitai_model_id = model_id
            k.civitai_url = f"https://civitai.com/models/{model_id}"
            k.provenance.setdefault("civitai_url", "civitai")

    version_id = civ.get("id")
    if isinstance(version_id, int):
        k.civitai_version_id = version_id

    # Example prompts — Civitai publishes generation examples with each
    # version; pull positive prompts from the first few.
    images = civ.get("images") or []
    examples: list[str] = []
    if isinstance(images, list):
        for img in images[:6]:
            if not isinstance(img, dict):
                continue
            meta = img.get("meta") or {}
            if isinstance(meta, dict):
                prompt = meta.get("prompt")
                if isinstance(prompt, str) and prompt.strip():
                    examples.append(prompt.strip()[:400])
    if examples and not k.example_prompts:
        k.example_prompts = examples[:3]
        k.provenance["example_prompts"] = "civitai"

    # Recommended generation params. Civitai's metadata isn't uniform;
    # many users save sampler/cfg inside image.meta, so we average
    # across the first few posted examples.
    samplers: list[str] = []
    cfgs: list[float] = []
    weights: list[float] = []
    if isinstance(images, list):
        for img in images[:6]:
            meta = (img or {}).get("meta") or {}
            if not isinstance(meta, dict):
                continue
            s = meta.get("sampler") or meta.get("Sampler")
            if isinstance(s, str) and s:
                samplers.append(s.strip().lower())
            c = meta.get("cfgScale") or meta.get("CFG scale") or meta.get("cfg_scale")
            try:
                if c is not None:
                    cfgs.append(float(c))
            except (TypeError, ValueError):
                pass
            # Look for "<lora:Name:0.85>" in the prompt and pull the weight.
            prompt = meta.get("prompt") or ""
            if isinstance(prompt, str):
                for m in re.finditer(r"<lora:[^:>]+:([\d.]+)>", prompt):
                    try:
                        weights.append(float(m.group(1)))
                    except ValueError:
                        pass

    if samplers and not k.recommended_sampler:
        # Pick the mode; break ties alphabetically for determinism.
        by_count: dict[str, int] = {}
        for s in samplers:
            by_count[s] = by_count.get(s, 0) + 1
        best = sorted(by_count.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
        k.recommended_sampler = _normalise_sampler(best)
        if k.recommended_sampler:
            k.provenance["recommended_sampler"] = "civitai"

    if cfgs and k.recommended_cfg is None:
        k.recommended_cfg = round(sum(cfgs) / len(cfgs), 2)
        k.provenance["recommended_cfg"] = "civitai"

    if weights and k.recommended_weight is None:
        # Trim to a plausible range — some users put 1.5 or 2.0 which is
        # a burn-in weight, not a generic recommendation.
        sane = [w for w in weights if 0.1 <= w <= 1.5]
        if sane:
            k.recommended_weight = round(sum(sane) / len(sane), 2)
            k.provenance["recommended_weight"] = "civitai"


def _normalise_sampler(s: str) -> Optional[str]:
    """A1111 → ComfyUI sampler name mapping. Empty / unknown → None."""
    if not s:
        return None
    t = s.lower().replace(" ", "_").replace("-", "_")
    synonyms = {
        "euler_a":              "euler_ancestral",
        "euler_ancestral":      "euler_ancestral",
        "euler":                "euler",
        "dpm++_2m_karras":      "dpmpp_2m",
        "dpm++_2m":             "dpmpp_2m",
        "dpmpp_2m":             "dpmpp_2m",
        "dpm++_sde":            "dpmpp_sde",
        "dpm++_sde_karras":     "dpmpp_sde",
        "dpm++_2m_sde":         "dpmpp_2m_sde",
        "dpmpp_2m_sde":         "dpmpp_2m_sde",
        "dpm++_2m_sde_karras":  "dpmpp_2m_sde",
        "lms":                  "lms",
        "heun":                 "heun",
        "ddim":                 "ddim",
        "plms":                 "plms",
        "uni_pc":               "uni_pc",
        "unipc":                "uni_pc",
        "restart":              "restart",
        "lcm":                  "lcm",
    }
    return synonyms.get(t)


# ── Shipped defaults (community-curated JSON) ──────────────────────────

_SHIPPED_SFW: Optional[dict] = None
_SHIPPED_NSFW: Optional[dict] = None


def _load_shipped() -> tuple[dict, dict]:
    """Load the JSON files that ship alongside this module."""
    global _SHIPPED_SFW, _SHIPPED_NSFW
    if _SHIPPED_SFW is not None and _SHIPPED_NSFW is not None:
        return _SHIPPED_SFW, _SHIPPED_NSFW
    pkg_dir = os.path.dirname(os.path.abspath(__file__))
    sfw_path = os.path.join(pkg_dir, "lora_calibrations_sfw.json")
    nsfw_path = os.path.join(pkg_dir, "lora_calibrations_nsfw.json")

    def _read(p: str) -> dict:
        try:
            if os.path.exists(p):
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    return data.get("loras") or {}
        except Exception:
            pass
        return {}

    _SHIPPED_SFW = _read(sfw_path)
    _SHIPPED_NSFW = _read(nsfw_path)
    return _SHIPPED_SFW, _SHIPPED_NSFW


def _apply_shipped_entry(entry: dict, k: LoraKnowledge, source: str) -> None:
    """Patch fields from a shipped calibration record into `k`."""
    if not isinstance(entry, dict):
        return
    if (k.recommended_weight is None
            and isinstance(entry.get("recommended_weight"), (int, float))):
        k.recommended_weight = float(entry["recommended_weight"])
        k.provenance["recommended_weight"] = source
    if not k.recommended_sampler and isinstance(entry.get("recommended_sampler"), str):
        k.recommended_sampler = entry["recommended_sampler"]
        k.provenance["recommended_sampler"] = source
    if (k.recommended_cfg is None
            and isinstance(entry.get("recommended_cfg"), (int, float))):
        k.recommended_cfg = float(entry["recommended_cfg"])
        k.provenance["recommended_cfg"] = source
    if not k.trigger_words and isinstance(entry.get("trigger_words"), list):
        k.trigger_words = [str(t) for t in entry["trigger_words"] if t][:10]
        if k.trigger_words:
            k.provenance["trigger_words"] = source
    if not k.example_prompts and isinstance(entry.get("example_prompts"), list):
        k.example_prompts = [str(p) for p in entry["example_prompts"] if p][:3]
        if k.example_prompts:
            k.provenance["example_prompts"] = source
    if entry.get("nsfw") and not k.nsfw:
        k.nsfw = True
        k.provenance["nsfw"] = source
    if not k.base_model and isinstance(entry.get("base_model"), str):
        k.base_model = entry["base_model"]
        k.provenance["base_model"] = source


# ── NSFW classifier ─────────────────────────────────────────────────────

def classify_nsfw(k: LoraKnowledge, filename: Optional[str] = None) -> bool:
    """True if the LoRA should live in the NSFW calibration store.

    Order of authority: explicit flag on the knowledge record →
    keyword scan of filename + trigger words. The keyword set is
    deliberately conservative; a false-positive just routes an
    innocent LoRA to the NSFW build's store, which is harmless. A
    false-negative would leak NSFW content into the public SFW store,
    which is not.
    """
    if k.nsfw:
        return True
    probe_parts: list[str] = []
    if filename:
        probe_parts.append(filename)
    if k.name:
        probe_parts.append(k.name)
    probe_parts.extend(k.trigger_words)
    probe = " ".join(probe_parts).lower()
    tokens = set(re.sub(r"[^a-z0-9]+", " ", probe).split())
    if tokens & _NSFW_KEYWORDS:
        return True
    # Substring match for keywords containing punctuation ("r-18",
    # "18+") that our word tokeniser flattens away. The false-positive
    # bar is deliberately low here — better to mis-route a benign
    # LoRA into the NSFW store (private) than leak explicit material
    # into the public SFW store.
    for kw in _NSFW_KEYWORDS:
        if not kw:
            continue
        if any(ch in kw for ch in "-+._"):
            if kw in probe:
                return True
    return False


# ── Heuristic fallbacks ─────────────────────────────────────────────────

_HEURISTIC_WEIGHT_BY_BASE: dict[str, float] = {
    "sd15":         0.75,
    "sdxl":         0.80,
    "illustrious":  0.85,
    "zit":          0.70,
    "flux1dev":     1.00,
    "flux_kontext": 1.00,
    "flux2klein":   1.00,
    "chroma":       1.00,
    "wan":          1.00,
    "ltx":          1.00,
    "hunyuan":      1.00,
}


def _apply_heuristic(k: LoraKnowledge) -> None:
    if k.recommended_weight is None and k.base_model:
        w = _HEURISTIC_WEIGHT_BY_BASE.get(k.base_model)
        if w is not None:
            k.recommended_weight = w
            k.provenance["recommended_weight"] = "heuristic"


# ── Main entry ──────────────────────────────────────────────────────────

def get_knowledge(
    name: str,
    path: Optional[str] = None,
    *,
    user_override: Optional[dict] = None,
    use_civitai: bool = True,
    use_network: bool = True,
    timeout: float = CIVITAI_TIMEOUT,
) -> LoraKnowledge:
    """Merge every source into one LoRA-knowledge record.

    `name` is the filename (relative to ComfyUI's `loras/` directory).
    `path` is the absolute disk path when available (caller can read
    the LoRA's safetensors header + compute SHA256). If `path=None`
    the function still works but degrades to filename heuristics
    plus any cached / shipped entry by `name`.

    `user_override` is the per-user registry entry (from
    `lora_registry.json`) — its fields, when populated, beat all
    other sources.

    `use_network=False` forbids the Civitai API call (useful for
    offline / privacy-sensitive contexts). The sidecar file IS still
    consulted — that's a local read.
    """
    k = LoraKnowledge(name=name, path=path, fetched_at=time.time())

    # 1. User-local confirmed record wins outright. Treat missing
    # values as "not yet confirmed" and fall through to the rest.
    if isinstance(user_override, dict):
        if isinstance(user_override.get("recommended_weight"), (int, float)):
            k.recommended_weight = float(user_override["recommended_weight"])
            k.provenance["recommended_weight"] = "user"
        if isinstance(user_override.get("user_default_strength"), (int, float)):
            # Legacy field name — map it.
            if k.recommended_weight is None:
                k.recommended_weight = float(user_override["user_default_strength"])
                k.provenance["recommended_weight"] = "user"
        if isinstance(user_override.get("recommended_sampler"), str):
            k.recommended_sampler = user_override["recommended_sampler"]
            k.provenance["recommended_sampler"] = "user"
        if isinstance(user_override.get("recommended_cfg"), (int, float)):
            k.recommended_cfg = float(user_override["recommended_cfg"])
            k.provenance["recommended_cfg"] = "user"
        if isinstance(user_override.get("trigger_words"), list):
            clean = [str(t).strip() for t in user_override["trigger_words"] if str(t).strip()]
            if clean:
                k.trigger_words = clean[:10]
                k.provenance["trigger_words"] = "user"
        if user_override.get("nsfw") is True:
            k.nsfw = True
            k.provenance["nsfw"] = "user"
        archs = user_override.get("archs")
        if isinstance(archs, list) and archs and not k.base_model:
            k.base_model = str(archs[0])
            k.provenance["base_model"] = "user"

    # 2. Safetensors header — fills triggers + hash if the file is on disk.
    if path and os.path.exists(path):
        meta = _read_safetensors_header(path)
        if not k.trigger_words:
            triggers = _extract_triggers_from_metadata(meta)
            if triggers:
                k.trigger_words = triggers
                k.provenance["trigger_words"] = "safetensors"
        # Some trainers write the hash directly into the header, which
        # saves us from having to SHA-256 a 2 GB file.
        for field_name in ("sshs_model_hash", "ss_sd_model_hash",
                           "modelspec.hash_sha256"):
            val = meta.get(field_name)
            if isinstance(val, str) and re.fullmatch(r"[0-9a-fA-F]{64}", val):
                k.sha256 = val.lower()
                break

    # 3. Cache lookup by hash — skip the network if we already know it.
    with _CACHE_LOCK:
        cache_key = k.sha256 or f"name:{name.lower()}"
        cached = _MEM_CACHE.get(cache_key)
    if isinstance(cached, dict):
        _apply_shipped_entry(cached, k, source="civitai")
        # Re-play cached civitai metadata that survives round-tripping.
        for fld in ("civitai_url", "civitai_model_id", "civitai_version_id",
                    "example_prompts"):
            if cached.get(fld) and not getattr(k, fld, None):
                setattr(k, fld, cached[fld])
                k.provenance.setdefault(fld, "civitai")

    # 4. Sidecar file (fast local read; works offline).
    sidecar = _read_civitai_sidecar(path) if path else None
    if isinstance(sidecar, dict):
        _map_civitai_to_knowledge(sidecar, k)
        for fld in k.provenance:
            if k.provenance[fld] == "civitai":
                k.provenance[fld] = "civitai_sidecar"

    # 5. Shipped community defaults — SFW always consulted; NSFW only
    # in NSFW builds (where build_nsfw.py wrote the JSON next to this
    # module).
    sfw, nsfw = _load_shipped()
    by_key = k.sha256 and (sfw.get(k.sha256) or nsfw.get(k.sha256))
    by_name = sfw.get(name) or nsfw.get(name)
    for entry in (by_key, by_name):
        if isinstance(entry, dict):
            _apply_shipped_entry(entry, k, source="shipped")

    # 6. Civitai live fetch — only when we have a hash and network.
    if use_civitai and use_network and k.sha256:
        # If the cache had a negative result, don't hammer the API.
        with _CACHE_LOCK:
            already_tried = _MEM_CACHE.get(k.sha256, {}).get("_civitai_tried")
        if not already_tried:
            civ = _civitai_by_hash(k.sha256, timeout=timeout)
            if civ:
                _map_civitai_to_knowledge(civ, k)
            with _CACHE_LOCK:
                _MEM_CACHE[k.sha256] = {
                    "_civitai_tried": True,
                    "recommended_weight": k.recommended_weight,
                    "recommended_sampler": k.recommended_sampler,
                    "recommended_cfg": k.recommended_cfg,
                    "trigger_words": list(k.trigger_words),
                    "example_prompts": list(k.example_prompts),
                    "base_model": k.base_model,
                    "nsfw": k.nsfw,
                    "civitai_url": k.civitai_url,
                    "civitai_model_id": k.civitai_model_id,
                    "civitai_version_id": k.civitai_version_id,
                }
                _save_disk_cache_locked()

    # 7. Compute hash lazily if still missing AND we're ALLOWED to hit
    # the network — otherwise hashing is pointless work. This is the
    # last-resort path; most users either have sidecars or a trainer
    # that writes the hash to the header.
    if use_civitai and use_network and not k.sha256 and path and os.path.exists(path):
        k.sha256 = _sha256_of_file(path)
        if k.sha256:
            with _CACHE_LOCK:
                prior = _MEM_CACHE.get(k.sha256)
            if not prior:
                civ = _civitai_by_hash(k.sha256, timeout=timeout)
                if civ:
                    _map_civitai_to_knowledge(civ, k)
                with _CACHE_LOCK:
                    _MEM_CACHE[k.sha256] = {
                        "_civitai_tried": True,
                        "recommended_weight": k.recommended_weight,
                        "recommended_sampler": k.recommended_sampler,
                        "recommended_cfg": k.recommended_cfg,
                        "trigger_words": list(k.trigger_words),
                        "example_prompts": list(k.example_prompts),
                        "base_model": k.base_model,
                        "nsfw": k.nsfw,
                        "civitai_url": k.civitai_url,
                        "civitai_model_id": k.civitai_model_id,
                        "civitai_version_id": k.civitai_version_id,
                    }
                    _save_disk_cache_locked()

    # 8. Final heuristic fill-ins.
    _apply_heuristic(k)
    return k


__all__ = [
    "LoraKnowledge",
    "get_knowledge",
    "classify_nsfw",
    "set_cache_path",
    "clear_cache",
]
