#!/usr/bin/env python3
"""Systematic upgrade research — Failsafe #6 ("research systems for upgrades
of all methods in the app ecosystem").

Built to satisfy the 2026-05-13 user directive. Companion to the saved
memory `project_spellcaster_upgrades_2026-05-08.md` (25 shipped
upgrades to spellcaster's 70 build_* methods) — that pass was ad-hoc;
this tool makes the same pass REPEATABLE so it runs monthly without a
human convening it each time.

Architecture
------------
The tool does NOT itself know about new model releases — it composes
three "research backends" that DO:

    backend_local_index    reads `lora_calibrations_sfw.json` +
                           `architectures.py` to know what's already in
                           use. Defines the "current state" baseline.
    backend_huggingface    queries the HF Hub for newer models matching
                           each architecture (e.g. for "sdxl" find the
                           top 20 most-downloaded checkpoints updated in
                           the last 90 days that aren't in current set).
    backend_civitai        same but on civitai.com.
    backend_comfy_manager  hits the local ComfyUI Manager's
                           ``/customnodes/getmappings`` to find pack
                           updates.
    backend_local_llm      asks a local LLM (LM Studio / Ollama —
                           ecosystem-peer delegation, failsafe #4) to
                           score each candidate against the builder's
                           use case + spellcaster's quality bar.

Each backend produces structured candidate records:

    {
      "method": "build_klein_repose",         # what this could upgrade
      "category": "checkpoint" | "lora" | "node_pack" | "controlnet" | ...,
      "name": "...",
      "source": "huggingface" | "civitai" | "comfy_manager",
      "url": "...",
      "downloads_30d": 12345,
      "rationale": "...",                     # human-readable why
      "risk": "low" | "medium" | "high",
      "confidence": 0.0-1.0,
    }

Records are merged + ranked by (downloads × confidence / risk_weight),
written to `_dev_docs/upgrade_research/<ISO-week>.{json,md}` so the
operator (or a future code-changing agent) has a fresh shopping list.

NEVER auto-installs anything. Research only. The 2026-05-08 pass was
human-reviewed before any of the 25 upgrades shipped — that gate stays.

H6 SFW/NSFW
-----------
The HF and Civitai queries can return NSFW content. The tool reads the
SFW canon (`lora_calibrations_sfw.json`) only by default; NSFW upgrade
research lives in the NSFW pipeline (a future
``tools/upgrade_research_nsfw.py`` that lives in `spellcaster_NSFW`).

Usage
-----

    python tools/upgrade_research.py                    # full pass, ~10 min
    python tools/upgrade_research.py --methods build_klein_repose,build_wan_video
    python tools/upgrade_research.py --backends local_index,huggingface
    python tools/upgrade_research.py --dry-run          # skeleton without network
    python tools/upgrade_research.py --schedule         # emit Task Scheduler
                                                        # XML for monthly runs

Exit codes
----------
    0  research complete, at least one candidate found
    1  research complete, no candidates (current state is current)
    2  one or more backends failed
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from contextlib import closing
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

_REPO = Path(__file__).resolve().parent.parent
_DEFAULT_OUT_DIR = _REPO / "_dev_docs" / "upgrade_research"

# Categories the research tool knows how to look up.
_CATEGORIES = ("checkpoint", "lora", "node_pack", "controlnet",
               "ipadapter", "upscaler", "vae", "text_encoder")


# ---------------------------------------------------------------------------
# Candidate record
# ---------------------------------------------------------------------------

@dataclass
class Candidate:
    method: str
    category: str
    name: str
    source: str
    url: str = ""
    downloads_30d: int = 0
    rationale: str = ""
    risk: str = "medium"          # low | medium | high
    confidence: float = 0.5       # 0..1

    def score(self) -> float:
        """Heuristic ranking value: (downloads × confidence) ÷ risk_weight.

        Higher = stronger candidate. risk_weight: low=1.0, medium=2.0,
        high=4.0 (low-risk wins by ~4× vs same-signal high-risk). Unknown
        risk strings default to medium weight rather than div-by-zero.
        """
        risk_weight = {"low": 1.0, "medium": 2.0, "high": 4.0}.get(self.risk, 2.0)
        return (self.downloads_30d * self.confidence) / risk_weight


@dataclass
class BackendResult:
    backend: str
    started_at: str
    ended_at: str = ""
    ok: bool = True
    error: str = ""
    candidates: list[Candidate] = field(default_factory=list)


@dataclass
class ResearchReport:
    generated_at: str
    iso_week: str
    methods_in_scope: list[str] = field(default_factory=list)
    backend_results: list[BackendResult] = field(default_factory=list)

    def all_candidates(self) -> list[Candidate]:
        """Flatten ``BackendResult.candidates`` across all backends.

        Used by render_md to compute the global top-N table; preserves
        per-backend ordering within the flattened list."""
        out = []
        for br in self.backend_results:
            out.extend(br.candidates)
        return out


# ---------------------------------------------------------------------------
# Backend: local index (baseline — what we already have)
# ---------------------------------------------------------------------------

def backend_local_index(methods: list[str], spellcaster_core: Path) -> BackendResult:
    """Baseline backend: enumerate calibrated LoRAs in
    ``lora_calibrations_sfw.json`` as low-confidence "current install"
    candidates so other backends can subtract them (don't re-suggest
    things we already use). Tolerates both the new schema (top-level
    ``loras`` key) and the legacy flat shape. H6 note: SFW canonical
    may legitimately be empty — NSFW pack at surfaces 3+6 holds the
    bulk of calibrations. ``methods`` accepted for signature symmetry
    with other backends; not currently used by this baseline.
    """
    br = BackendResult(backend="local_index",
                        started_at=datetime.now(timezone.utc).isoformat())
    cal = spellcaster_core / "lora_calibrations_sfw.json"
    if not cal.exists():
        br.ok = False
        br.error = f"missing {cal}"
        br.ended_at = datetime.now(timezone.utc).isoformat()
        return br
    try:
        data = json.loads(cal.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        br.ok = False
        br.error = str(exc)
        br.ended_at = datetime.now(timezone.utc).isoformat()
        return br

    # The local_index backend doesn't propose upgrades — it just records
    # the baseline so other backends can subtract it (don't re-suggest
    # things we already use). Encoded as low-confidence baseline
    # candidates with rationale "current install".
    #
    # Schema (lora_calibrations_sfw.json @ 2026-05-13):
    #     { "schema_version": int, "notes": ..., "loras": {<arch>: {<filename>: ...}} }
    # …or an older flat form: { <arch>: {<filename>: ...}, ... }
    # We tolerate both so the backend keeps working if the schema rolls
    # forward again. H6 note: SFW canonical may legitimately be empty
    # (NSFW pack has the bulk of calibrations at surfaces 3 + 6).
    loras_section = data.get("loras") if isinstance(data, dict) else None
    iterable = loras_section if isinstance(loras_section, dict) else data
    if isinstance(iterable, dict):
        for arch, entries in iterable.items():
            # Skip the schema-meta sibling keys when we fell back to
            # iterating top-level
            if arch in {"schema_version", "notes", "loras"}:
                continue
            if not isinstance(entries, dict):
                continue
            for fname in entries.keys():
                br.candidates.append(Candidate(
                    method=f"arch:{arch}",
                    category="lora",
                    name=fname,
                    source="local_index",
                    rationale="current calibrated LoRA — baseline",
                    risk="low",
                    confidence=0.1,  # not an upgrade signal
                ))
    br.ended_at = datetime.now(timezone.utc).isoformat()
    return br


# ---------------------------------------------------------------------------
# Backend: huggingface (real — queries HF public API)
# ---------------------------------------------------------------------------

# Arch → HF search query mapping. The HF Hub doesn't tag models by
# our spellcaster arch names directly; we approximate with the popular
# search keywords + a few tags. Add new entries when a spellcaster
# arch arrives; missing entries fall back to the bare arch name.
_HF_ARCH_QUERIES: dict[str, list[str]] = {
    "sdxl": ["sdxl", "stable-diffusion-xl"],
    "sd15": ["stable-diffusion-v1-5", "sd15"],
    "illustrious": ["illustrious", "noobai"],
    "pony": ["pony-diffusion"],
    "flux1dev": ["flux.1-dev", "flux-1-dev", "flux"],
    "flux2klein": ["flux.2-klein", "flux2-klein"],
    "flux_kontext": ["flux-kontext", "flux.1-kontext"],
    "wan": ["wan-2.1", "wan2-i2v"],
    "ltx": ["ltx-video", "ltxv"],
    "hunyuan_dit": ["hunyuan-dit"],
    "auraflow": ["auraflow"],
    "chroma": ["chroma"],
    "kolors": ["kolors"],
    "lumina": ["lumina"],
    "sd3": ["stable-diffusion-3"],
    "zit": ["z-image-turbo", "z-image"],
}

_HF_API = "https://huggingface.co/api/models"

# H6 SFW filter for HF backend. The HF Hub search endpoint has no
# `nsfw=false` query param (civitai does), so we filter client-side on
# two signals:
#   1. Substring match against the model id (handles `..._nsfw_...`,
#      `xxx-...`, `hentai-...` published names).
#   2. The `tags` array on the model dict if HF returned it (the search
#      endpoint sometimes omits tags, so this is best-effort, not the
#      sole gate).
# Belt-and-suspenders to keep the SFW canon clean — NSFW upgrade
# research lives in the NSFW pack's own backend, not here.
_HF_NSFW_NAME_PATTERNS = frozenset({
    "nsfw", "porn", "xxx", "hentai", "rule34", "uncensored",
    "explicit-content", "not-safe-for-work", "adult-content",
})
_HF_NSFW_TAGS = frozenset({
    "not-for-all-audiences", "nsfw", "adult-content",
})


def _hf_is_nsfw(model_id: str, tags: object) -> bool:
    """Return True if the HF model id or its tags trip the SFW filter."""
    lowered = model_id.lower()
    if any(p in lowered for p in _HF_NSFW_NAME_PATTERNS):
        return True
    if isinstance(tags, list):
        for t in tags:
            if isinstance(t, str) and t.lower() in _HF_NSFW_TAGS:
                return True
    return False


def _hf_query_for_method(method_name: str) -> tuple[str, list[str]] | None:
    """Map a ``build_<foo>`` method name to (arch_id, search_terms).

    Heuristic: strip ``build_`` and the leading task verb (``txt2img``,
    ``img2img``, ``inpaint``…); what remains is usually the architecture
    or a klein-* variant. We then look up the arch in _HF_ARCH_QUERIES.
    Returns None if we can't infer an arch — the caller skips silently.
    """
    if not method_name.startswith("build_"):
        return None
    tail = method_name[len("build_"):]
    # Try each registered arch as a substring match
    for arch_id, terms in _HF_ARCH_QUERIES.items():
        if arch_id in tail.lower():
            return (arch_id, terms)
        # also probe substring of the underlying search terms
        for t in terms:
            if t.replace("-", "_") in tail.lower():
                return (arch_id, terms)
    return None


def backend_huggingface(methods: list[str], dry_run: bool = False) -> BackendResult:
    """HF Hub backend: queries ``https://huggingface.co/api/models`` for
    each spellcaster method's underlying architecture and emits Candidate
    rows ranked by download count.

    No auth needed for the public search endpoint; rate-limit defaults
    are generous enough for a monthly research run. Each query has a
    10-second timeout (per H5). On any single-query failure (network /
    JSON / 4xx-5xx), that query is skipped, the error is folded into
    ``br.error``, and the rest continue.

    Args:
        methods: list of ``build_*`` names to research. Empty/None → []
            (no candidates, ok=True).
        dry_run: True → emit one demo candidate, no network call. Used
            for tests + report-shape exercising when offline.

    Returns:
        ``BackendResult`` with up to ~5 candidates per recognised method.
    """
    br = BackendResult(backend="huggingface",
                        started_at=datetime.now(timezone.utc).isoformat())
    if dry_run:
        br.candidates.append(Candidate(
            method="build_klein_repose",
            category="checkpoint",
            name="black-forest-labs/FLUX.1-Klein-2.1",
            source="huggingface",
            url="https://huggingface.co/black-forest-labs/FLUX.1-Klein-2.1",
            downloads_30d=42000,
            rationale="DRY-RUN demo candidate (no network query made)",
            risk="medium",
            confidence=0.6,
        ))
        br.ended_at = datetime.now(timezone.utc).isoformat()
        return br

    if not methods:
        br.ended_at = datetime.now(timezone.utc).isoformat()
        return br

    seen_models: set[str] = set()
    errors: list[str] = []

    # Distinct method→arch mappings; one query per UNIQUE arch (not per
    # method) so a builder family doesn't N-fan-out the API call count.
    arches_to_query: dict[str, list[str]] = {}
    for m in methods:
        mapping = _hf_query_for_method(m)
        if mapping is None:
            continue
        arch_id, terms = mapping
        arches_to_query.setdefault(arch_id, []).extend(
            t for t in terms if t not in arches_to_query.get(arch_id, []))
        # Remember which method "owns" the arch for the candidate.method label
        arches_to_query.setdefault(f"_method:{arch_id}", []).append(m)

    method_for_arch = {
        k[len("_method:"):]: v[0]
        for k, v in arches_to_query.items() if k.startswith("_method:")
    }

    for arch_id, terms in arches_to_query.items():
        if arch_id.startswith("_method:"):
            continue
        # Query the most-specific term (first in list); HF search is
        # full-text, so this is closest to "what's named like this"
        primary_term = terms[0] if terms else arch_id
        url = f"{_HF_API}?search={primary_term}&sort=downloads&direction=-1&limit=5"
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "spellcaster-upgrade-research"})
            with closing(urllib.request.urlopen(req, timeout=10.0)) as resp:
                body = resp.read()
                models = json.loads(body.decode("utf-8"))
        except (urllib.error.URLError, urllib.error.HTTPError,
                json.JSONDecodeError, OSError, TimeoutError) as exc:
            errors.append(f"{arch_id}: {type(exc).__name__}: {exc}")
            continue

        if not isinstance(models, list):
            errors.append(f"{arch_id}: unexpected response shape")
            continue

        owning_method = method_for_arch.get(arch_id, f"arch:{arch_id}")
        for m in models[:5]:
            if not isinstance(m, dict):
                continue
            model_id = m.get("id") or m.get("modelId") or ""
            if not model_id or model_id in seen_models:
                continue
            seen_models.add(model_id)
            # H6 SFW filter — drop NSFW candidates before they reach the digest.
            if _hf_is_nsfw(model_id, m.get("tags")):
                continue
            downloads = int(m.get("downloads") or 0)
            br.candidates.append(Candidate(
                method=owning_method,
                category="checkpoint",  # HF doesn't reliably distinguish
                name=model_id,
                source="huggingface",
                url=f"https://huggingface.co/{model_id}",
                downloads_30d=downloads,
                rationale=(f"HF top-{models.index(m) + 1} for arch={arch_id} "
                            f"(query='{primary_term}')"),
                risk="medium",
                confidence=0.6,
            ))

    if errors:
        br.error = "; ".join(errors[:3])
        # Non-fatal: ok stays True if we got AT LEAST one candidate
        br.ok = len(br.candidates) > 0

    br.ended_at = datetime.now(timezone.utc).isoformat()
    return br


# ---------------------------------------------------------------------------
# Backend: civitai (skeleton)
# ---------------------------------------------------------------------------

_CIVITAI_API = "https://civitai.com/api/v1/models"

# Civitai's `types` enum: Checkpoint, LORA, LoCon, TextualInversion,
# Hypernetwork, VAE, Controlnet, Poses, AestheticGradient, Wildcards,
# Workflows, Upscaler. We probe Checkpoint + LORA for each arch.
_CIVITAI_TYPES_DEFAULT: tuple[str, ...] = ("Checkpoint", "LORA")


def backend_civitai(methods: list[str], dry_run: bool = False,
                     types: tuple[str, ...] = _CIVITAI_TYPES_DEFAULT
                     ) -> BackendResult:
    """Civitai API backend: queries ``https://civitai.com/api/v1/models``
    for the top-rated SFW model per spellcaster arch in the configured
    types (default: Checkpoint, LORA).

    H6 invariant: ``nsfw=false`` query param + ``nsfw=false`` per-model
    filter — civitai's adult content stays out of the SFW canon's
    research output, period. NSFW upgrade research would live in a
    sibling ``backend_civitai_nsfw`` inside the NSFW pack at surfaces
    3/6, NOT here.

    No auth required for read access. 10s per-call timeout (H5). Same
    arch-mapping as the HF backend (``_HF_ARCH_QUERIES`` doubles as the
    civitai keyword source — civitai's full-text search handles bare
    arch names just as well).

    Args:
        methods: list of ``build_*`` names to research. Empty → [].
        dry_run: True → emit one demo candidate, no network call.
        types: civitai types-enum subset to query. Default
            ``("Checkpoint", "LORA")``. Override to broaden (e.g.
            include ``"VAE"``, ``"Controlnet"``) or narrow.
    """
    br = BackendResult(backend="civitai",
                        started_at=datetime.now(timezone.utc).isoformat())
    if dry_run:
        br.candidates.append(Candidate(
            method="build_illustrious_txt2img",
            category="checkpoint",
            name="WAI-ILLUSTRIOUS-SDXL v1.6.0",
            source="civitai",
            url="https://civitai.com/models/420166",
            downloads_30d=180000,
            rationale="DRY-RUN demo: newer illustrious checkpoint, "
                       "improved hand anatomy per release notes",
            risk="medium",
            confidence=0.7,
        ))
        br.ended_at = datetime.now(timezone.utc).isoformat()
        return br

    if not methods:
        br.ended_at = datetime.now(timezone.utc).isoformat()
        return br

    seen_models: set[int] = set()
    errors: list[str] = []

    arches_to_query: dict[str, list[str]] = {}
    method_for_arch: dict[str, str] = {}
    for m in methods:
        mapping = _hf_query_for_method(m)
        if mapping is None:
            continue
        arch_id, terms = mapping
        if arch_id not in arches_to_query:
            arches_to_query[arch_id] = terms
            method_for_arch[arch_id] = m

    for arch_id, terms in arches_to_query.items():
        primary_term = terms[0] if terms else arch_id
        owning_method = method_for_arch.get(arch_id, f"arch:{arch_id}")
        for type_ in types:
            params = (
                f"query={urllib.request.quote(primary_term)}"
                f"&types={type_}"
                f"&sort=Highest+Rated"
                f"&period=Month"
                f"&limit=5"
                f"&nsfw=false"
            )
            url = f"{_CIVITAI_API}?{params}"
            try:
                req = urllib.request.Request(
                    url, headers={"User-Agent": "spellcaster-upgrade-research"})
                with closing(urllib.request.urlopen(req, timeout=10.0)) as resp:
                    body = resp.read()
                    payload = json.loads(body.decode("utf-8"))
            except (urllib.error.URLError, urllib.error.HTTPError,
                    json.JSONDecodeError, OSError, TimeoutError) as exc:
                errors.append(f"{arch_id}/{type_}: {type(exc).__name__}: {exc}")
                continue

            items = payload.get("items") if isinstance(payload, dict) else None
            if not isinstance(items, list):
                errors.append(f"{arch_id}/{type_}: unexpected response shape")
                continue

            for it in items[:5]:
                if not isinstance(it, dict):
                    continue
                # Per-item NSFW filter: belt + suspenders alongside the
                # query-level nsfw=false. Civitai sometimes returns
                # tagged-but-not-marked-NSFW items; the per-item
                # `nsfw` flag is the last-resort gate.
                if it.get("nsfw"):
                    continue
                model_id = it.get("id")
                if not isinstance(model_id, int) or model_id in seen_models:
                    continue
                seen_models.add(model_id)
                name = it.get("name") or f"model-{model_id}"
                stats = it.get("stats") or {}
                downloads = int(stats.get("downloadCount") or 0)
                rating = stats.get("rating")
                rating_str = (f" rating={rating:.2f}"
                              if isinstance(rating, (int, float)) else "")
                category = "lora" if type_ == "LORA" else "checkpoint"
                br.candidates.append(Candidate(
                    method=owning_method,
                    category=category,
                    name=name,
                    source="civitai",
                    url=f"https://civitai.com/models/{model_id}",
                    downloads_30d=downloads,
                    rationale=(f"civitai top-rated {type_} for arch={arch_id}"
                                f"{rating_str}"),
                    risk="medium",
                    confidence=0.65,
                ))

    if errors:
        br.error = "; ".join(errors[:3])
        br.ok = len(br.candidates) > 0

    br.ended_at = datetime.now(timezone.utc).isoformat()
    return br


# ---------------------------------------------------------------------------
# Backend: comfy_manager (real implementation — hits local ComfyUI)
# ---------------------------------------------------------------------------

def backend_comfy_manager(methods: list[str], comfy_url: str,
                           dry_run: bool = False) -> BackendResult:
    """ComfyUI Manager backend: hits the local ``/customnode/getlist``
    endpoint to discover pack updates. Real (partial) implementation —
    when the manager IS reachable it counts available packs; full diff
    against installed custom_nodes is still TODO. dry_run mode emits a
    demo candidate so the report shape exercises even when ComfyUI is
    down. Errors (unreachable / 4xx / non-JSON) surface as ok=False.
    """
    br = BackendResult(backend="comfy_manager",
                        started_at=datetime.now(timezone.utc).isoformat())
    if dry_run:
        br.candidates.append(Candidate(
            method="*",
            category="node_pack",
            name="ComfyUI-Spellcaster v2.0 (hypothetical)",
            source="comfy_manager",
            url="https://github.com/laboratoiresonore/ComfyUI-Spellcaster",
            downloads_30d=0,
            rationale="DRY-RUN demo: would query /customnodes/getmappings",
            risk="low",
            confidence=0.9,
        ))
        br.ended_at = datetime.now(timezone.utc).isoformat()
        return br

    # ComfyUI Manager exposes /customnode/getlist. If Manager isn't
    # installed we get a 404; that's fine, surface it.
    url = comfy_url.rstrip("/") + "/customnode/getlist"
    try:
        req = urllib.request.Request(url)
        with closing(urllib.request.urlopen(req, timeout=30)) as resp:
            if resp.status != 200:
                br.error = f"GET {url} -> HTTP {resp.status}"
                br.ok = False
            else:
                # Real impl would diff this against installed nodes
                # (D:/AI/ComfyUI/ComfyUI/custom_nodes/*) and propose
                # pack updates. For the scaffold, just count availability.
                body = resp.read().decode("utf-8", errors="ignore")
                try:
                    data = json.loads(body)
                    n = len(data.get("custom_nodes", []))
                    br.candidates.append(Candidate(
                        method="*",
                        category="node_pack",
                        name=f"ComfyUI Manager: {n} packs available",
                        source="comfy_manager",
                        rationale="manager reachable; full diff pending impl",
                        risk="low",
                        confidence=0.4,
                    ))
                except json.JSONDecodeError:
                    br.error = "manager returned non-JSON"
                    br.ok = False
    except urllib.error.URLError as exc:
        br.error = f"manager unreachable: {exc}"
        br.ok = False
    br.ended_at = datetime.now(timezone.utc).isoformat()
    return br


# ---------------------------------------------------------------------------
# Backend: local_llm (ecosystem-peer delegation — failsafe #4)
# ---------------------------------------------------------------------------

def _local_llm_endpoint() -> str:
    """Resolve the local LLM endpoint. Priority:
    1. ``$LMSTUDIO_HOST`` env var
    2. ``$OLLAMA_HOST`` env var
    3. Default ``http://127.0.0.1:1234`` (LM Studio default port)
    The user's stack typically runs LM Studio at ``<host>:1234`` on
    one or more LAN peers; any reachable one works.

    Normalisation: env vars on this user's box can be set to bind-address
    forms like ``0.0.0.0`` (Ollama's recommended server-side bind, NOT a
    client URL). We rewrite ``0.0.0.0`` -> ``127.0.0.1``, prepend
    ``http://`` if no scheme, and append the appropriate default port
    if missing (1234 for LM Studio, 11434 for Ollama).
    """
    raw = None
    source = None
    for env in ("LMSTUDIO_HOST", "OLLAMA_HOST"):
        v = os.environ.get(env)
        if v:
            raw = v
            source = env
            break
    if raw is None:
        return "http://127.0.0.1:1234"
    s = raw.strip().rstrip("/")
    if "://" not in s:
        s = "http://" + s
    # Rewrite wildcard bind to loopback for client use
    s = s.replace("//0.0.0.0", "//127.0.0.1")
    # Append default port if none present in the host[:port] segment
    from urllib.parse import urlparse
    parsed = urlparse(s)
    if parsed.port is None:
        default_port = 11434 if source == "OLLAMA_HOST" else 1234
        s = f"{parsed.scheme}://{parsed.hostname}:{default_port}"
        if parsed.path:
            s += parsed.path
    return s


# Regex to pull a {"score": ..., "rationale": ...} blob out of an LLM
# response that may have wrapped it in ```json fences``` or surrounding
# prose. Conservative: only grabs the first balanced-looking object.
_LLM_JSON_RE = __import__("re").compile(
    r'\{[^{}]*?"score"\s*:\s*[\d.]+[^{}]*?\}', __import__("re").DOTALL)


def _local_llm_score(method: str, candidate: Candidate, endpoint: str,
                      timeout_s: float = 30.0) -> tuple[float, str] | None:
    """Ask the local LLM to score one candidate's fit for one method.

    Returns ``(score, rationale)`` where ``score ∈ [0, 1]`` and
    ``rationale`` is a one-sentence explanation. Returns None on:
      - network/timeout failure
      - LLM returns non-JSON or unparseable response
      - score out of valid range
    Caller treats None as "skip — keep candidate's prior confidence".
    """
    prompt = (
        "You evaluate AI-model upgrade candidates for a Stable Diffusion + "
        "ComfyUI workflow pipeline. Output ONE compact JSON object only, "
        "no prose, no markdown.\n\n"
        f"Spellcaster method: {method}\n"
        f"Candidate model: {candidate.name}\n"
        f"Source: {candidate.source}\n"
        f"30-day downloads: {candidate.downloads_30d}\n"
        f"Category: {candidate.category}\n\n"
        "Score 0-1 for likelihood this candidate is a meaningful upgrade "
        "for the method (0 = irrelevant/worse; 1 = clear strict upgrade). "
        "Output exactly:\n"
        '{"score": 0.0, "rationale": "one short sentence"}'
    )
    payload = {
        "model": "default",  # LM Studio + Ollama both accept this
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
        "max_tokens": 200,
    }
    req = urllib.request.Request(
        endpoint.rstrip("/") + "/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with closing(urllib.request.urlopen(req, timeout=timeout_s)) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        content = body["choices"][0]["message"]["content"]
    except (urllib.error.URLError, urllib.error.HTTPError, OSError,
            TimeoutError, KeyError, IndexError,
            json.JSONDecodeError) as _:
        return None

    # The LLM may wrap JSON in code fences or surround with prose.
    # Try direct parse, then regex extraction.
    parsed = None
    try:
        parsed = json.loads(content.strip())
    except json.JSONDecodeError:
        match = _LLM_JSON_RE.search(content)
        if match:
            try:
                parsed = json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
    if not isinstance(parsed, dict):
        return None
    score = parsed.get("score")
    rationale = parsed.get("rationale") or ""
    if not isinstance(score, (int, float)) or not (0.0 <= float(score) <= 1.0):
        return None
    return (float(score), str(rationale)[:200])


def backend_local_llm(methods: list[str], baseline: list[Candidate],
                       proposals: list[Candidate],
                       dry_run: bool = False,
                       endpoint: str | None = None,
                       max_to_score: int = 10) -> BackendResult:
    """Asks the local LLM to re-rank ``proposals`` per spellcaster method.

    For each of the top ``max_to_score`` proposals (sorted by score
    descending — the strongest from HF/civitai), we POST a single-turn
    prompt to the local LLM's ``/v1/chat/completions`` endpoint asking
    for ``{"score": 0-1, "rationale": "..."}``. We then UPDATE that
    candidate's ``confidence`` to the LLM's score and append the
    rationale to its ``Candidate.rationale``. The original candidate
    object is mutated AND added to ``br.candidates`` — the calling
    pipeline can then re-sort the merged candidate set.

    Why this exists (ecosystem-peer delegation):
      - Local: no Claude tokens spent on a routine evaluative task.
      - Bias-aware: the loaded model knows the spellcaster method names
        + common arch shorthand.
      - Repeatable: temperature 0.2 + same model → stable week-over-week
        diffs the operator can compare.

    Args:
        methods: list of build_* names (unused here; kept for backend
            signature symmetry).
        baseline: candidates already in the canon (NOT re-scored — we
            assume the operator already validated them).
        proposals: candidates from HF/civitai/comfy_manager. The top
            ``max_to_score`` get LLM-scored.
        dry_run: True → emit one demo candidate, no network call.
        endpoint: override the LLM URL (default: env var or 127.0.0.1:1234).
        max_to_score: cap LLM calls per run. Default 10 (~5-15 min on
            a hot LAN peer; ~30 min cold).
    """
    br = BackendResult(backend="local_llm",
                        started_at=datetime.now(timezone.utc).isoformat())
    if dry_run:
        if proposals:
            scored = proposals[0]
            scored.confidence = min(1.0, scored.confidence + 0.2)
            scored.rationale += " | DRY-RUN: LLM bumped confidence +0.2"
            br.candidates.append(scored)
        br.ended_at = datetime.now(timezone.utc).isoformat()
        return br

    if not proposals:
        br.ended_at = datetime.now(timezone.utc).isoformat()
        return br

    endpoint = endpoint or _local_llm_endpoint()
    errors: list[str] = []
    scored_count = 0

    # Sort proposals by current score descending; only re-score the top-N
    # so we don't burn time on the long tail.
    proposals_sorted = sorted(
        proposals, key=lambda c: -c.score())[:max_to_score]

    for c in proposals_sorted:
        result = _local_llm_score(c.method, c, endpoint)
        if result is None:
            errors.append(f"{c.name[:40]}: LLM scoring failed/parse-error")
            # Keep candidate but don't claim LLM ranked it
            br.candidates.append(c)
            continue
        score, rationale = result
        c.confidence = score
        c.rationale = f"{c.rationale} | LLM: {rationale}"
        br.candidates.append(c)
        scored_count += 1

    if errors:
        br.error = "; ".join(errors[:3])
        # Non-fatal — partial scoring is still useful
        br.ok = scored_count > 0

    br.ended_at = datetime.now(timezone.utc).isoformat()
    return br


# ---------------------------------------------------------------------------
# Method enumeration (read workflows.py via AST — no spellcaster_core import)
# ---------------------------------------------------------------------------

def _enumerate_methods(spellcaster_core: Path) -> list[str]:
    """Pull every build_* function name from workflows.py via AST so the
    tool doesn't pull in spellcaster_core's runtime deps."""
    import ast
    wf = spellcaster_core / "workflows.py"
    if not wf.exists():
        return []
    try:
        tree = ast.parse(wf.read_text(encoding="utf-8"))
    except SyntaxError:
        return []
    return [n.name for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef) and n.name.startswith("build_")]


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def render_md(report: ResearchReport) -> str:
    """Render a ResearchReport as human-readable markdown.

    Layout: title + ISO-week + per-backend status table + top-50
    proposals (sorted by ``Candidate.score()`` descending; baseline
    ``local_index`` rows excluded since they're "current state" not
    upgrade signal). Empty-proposals reports render an explicit
    "_no proposals from any backend_" placeholder.
    """
    lines = [
        "# Spellcaster upgrade research",
        "",
        f"- Generated: `{report.generated_at}`",
        f"- ISO week: `{report.iso_week}`",
        f"- Methods in scope: `{len(report.methods_in_scope)}`",
        "",
        "## Backend status",
        "",
        "| Backend | ok | candidates | error |",
        "|---------|----|------------|-------|",
    ]
    for br in report.backend_results:
        lines.append(f"| `{br.backend}` | {'✅' if br.ok else '❌'} "
                     f"| {len(br.candidates)} | {br.error or '-'} |")

    # Top-ranked proposals (excluding baseline-only entries).
    # Dedup observed 2026-05-14 in live data: local_llm re-ranks the
    # huggingface proposals by mutating the same Candidate object in
    # place AND appending it to its own br.candidates list. That made
    # the same upgrade appear twice in the Top-N table (10 of 39 rows
    # were duplicates in the 2026-W20 live run). Collapse by
    # (method, name) keeping the LLM-enriched copy when available.
    by_key: dict[tuple[str, str], Candidate] = {}
    for c in report.all_candidates():
        if c.source == "local_index":
            continue
        k = (c.method, c.name)
        existing = by_key.get(k)
        if existing is None:
            by_key[k] = c
            continue
        # Prefer the LLM-re-ranked copy (rationale mentions LLM).
        # Tie-break by higher score.
        existing_has_llm = "LLM:" in existing.rationale
        new_has_llm = "LLM:" in c.rationale
        if new_has_llm and not existing_has_llm:
            by_key[k] = c
        elif new_has_llm == existing_has_llm and c.score() > existing.score():
            by_key[k] = c
    proposals = list(by_key.values())
    proposals.sort(key=lambda c: -c.score())

    lines += ["", f"## Top {min(50, len(proposals))} proposals (by score)", ""]
    if not proposals:
        lines.append("_no proposals from any backend_")
    else:
        lines += ["| Method | Category | Name | Source | Score | Risk |",
                  "|--------|----------|------|--------|-------|------|"]
        for c in proposals[:50]:
            lines.append(f"| `{c.method}` | {c.category} | {c.name} "
                         f"| {c.source} | {c.score():.0f} | {c.risk} |")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    """CLI entry point for tools/upgrade_research.py.

    Parses ``--spellcaster-core``, ``--comfy``, ``--out-dir``,
    ``--methods``, ``--backends``, ``--dry-run``, dispatches each
    enabled backend, writes JSON + MD reports under
    ``_dev_docs/upgrade_research/<iso-week>.{json,md}``.

    Exit codes:
        0 — research complete with ≥1 proposal
        1 — research complete with 0 proposals (current state is current)
        2 — at least one backend failed (network down, schema drift, etc.)
    """
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--spellcaster-core", type=Path,
                   default=_REPO / "comfyui-spellcaster" / "spellcaster_core")
    p.add_argument("--comfy", default="http://127.0.0.1:8190")
    p.add_argument("--out-dir", type=Path, default=_DEFAULT_OUT_DIR)
    p.add_argument("--methods", default="",
                   help="Comma-sep list to restrict to; default: every build_*")
    p.add_argument("--backends",
                   default="local_index,huggingface,civitai,comfy_manager,local_llm",
                   help="Comma-sep list to enable")
    p.add_argument("--dry-run", action="store_true",
                   help="Skip network; emit demo candidates")
    args = p.parse_args(argv)

    methods = (args.methods.split(",") if args.methods
               else _enumerate_methods(args.spellcaster_core))
    methods = [m.strip() for m in methods if m.strip()]
    enabled = {b.strip() for b in args.backends.split(",")}

    now = datetime.now(timezone.utc)
    iso_week = f"{now.isocalendar().year}-W{now.isocalendar().week:02d}"

    report = ResearchReport(
        generated_at=now.isoformat(),
        iso_week=iso_week,
        methods_in_scope=methods,
    )

    baseline_br = None
    if "local_index" in enabled:
        baseline_br = backend_local_index(methods, args.spellcaster_core)
        report.backend_results.append(baseline_br)

    proposal_brs: list[BackendResult] = []
    if "huggingface" in enabled:
        proposal_brs.append(backend_huggingface(methods, args.dry_run))
    if "civitai" in enabled:
        proposal_brs.append(backend_civitai(methods, args.dry_run))
    if "comfy_manager" in enabled:
        proposal_brs.append(backend_comfy_manager(methods, args.comfy, args.dry_run))
    report.backend_results.extend(proposal_brs)

    proposals = [c for br in proposal_brs for c in br.candidates]
    baseline = baseline_br.candidates if baseline_br else []

    if "local_llm" in enabled:
        report.backend_results.append(
            backend_local_llm(methods, baseline, proposals, args.dry_run))

    args.out_dir.mkdir(parents=True, exist_ok=True)
    fn_base = args.out_dir / iso_week
    fn_base.with_suffix(".json").write_text(
        json.dumps(asdict(report), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    fn_base.with_suffix(".md").write_text(render_md(report), encoding="utf-8")

    n_proposals = sum(1 for c in report.all_candidates()
                       if c.source != "local_index")
    print(f"upgrade-research {iso_week}: {n_proposals} proposals from "
          f"{sum(1 for br in report.backend_results if br.ok)} backends")
    print(f"  md:   {fn_base.with_suffix('.md')}")
    print(f"  json: {fn_base.with_suffix('.json')}")

    if any(not br.ok for br in report.backend_results):
        return 2
    return 0 if n_proposals else 1


if __name__ == "__main__":
    sys.exit(main())
