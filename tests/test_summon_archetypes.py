"""Tests for the Summon-wizard archetype branch.

Covers:
  * Per-kind config validation (Chimera 2-5 models, Oracle llm_model,
    Scalpel base_model required; Forensic / Lore-keeper accept empty).
  * The `_ARCHETYPE_CATALOGUE` has every kind the UI exposes plus a
    non-empty system_prompt.
  * Forensic extract handler — PNG with embedded `workflow` tEXt
    chunk gets parsed; a plain PNG returns `forensic: null` with a
    clear note instead of an error.
  * Chimera router — keyword matching picks the right head; unknown
    prompts fall back cleanly.
  * Lore-keeper query — substring match over registry names and
    trigger words; calibrated entries sort first.
  * Scalpel planner — verb detection differentiates erase / replace
    / add and the plan references the configured base model.

Run:
    PYTHONPATH=. python tests/test_summon_archetypes.py
"""
from __future__ import annotations

import base64
import io
import json
import os
import struct
import sys
import tempfile
import traceback
import zlib

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
# tavern/server.py imports sibling modules (guild_common, etc.) without
# the tavern. prefix, so tavern/ must be on sys.path BEFORE we import.
for p in (os.path.join(_REPO, "tavern"),
          os.path.join(_REPO, "comfyui-spellcaster"),
          _REPO):
    if p not in sys.path:
        sys.path.insert(0, p)

import server as srv   # noqa: E402   (tavern/server.py as a top-level module)


# ── _ARCHETYPE_CATALOGUE sanity ────────────────────────────────────────

def case_catalogue_has_every_ui_archetype():
    expected = {"forensic", "chimera", "oracle", "lore_keeper", "scalpel"}
    assert expected.issubset(set(srv._ARCHETYPE_CATALOGUE.keys()))
    for kind, meta in srv._ARCHETYPE_CATALOGUE.items():
        assert meta.get("system_prompt"), f"{kind} has empty system_prompt"
        assert meta.get("icon"), f"{kind} has no icon"
        assert isinstance(meta.get("hue"), int)


# ── Config validation ─────────────────────────────────────────────────

def case_validate_forensic_empty_ok():
    assert srv._validate_archetype_config("forensic", {}) == []


def case_validate_lore_keeper_empty_ok():
    assert srv._validate_archetype_config("lore_keeper", {}) == []


def case_validate_chimera_needs_2_to_5_models():
    # too few
    errs = srv._validate_archetype_config("chimera", {"models": []})
    assert any("2–5" in e or "2-5" in e for e in errs)
    errs = srv._validate_archetype_config("chimera", {"models": [{"name": "m1"}]})
    assert any("2–5" in e or "2-5" in e for e in errs)
    # too many
    too_many = [{"name": f"m{i}"} for i in range(6)]
    errs = srv._validate_archetype_config("chimera", {"models": too_many})
    assert any("2–5" in e or "2-5" in e for e in errs)
    # just right
    ok = [{"name": "m1", "arch": "sdxl"},
          {"name": "m2", "arch": "flux1dev"}]
    assert srv._validate_archetype_config("chimera", {"models": ok}) == []


def case_validate_chimera_model_must_have_name():
    errs = srv._validate_archetype_config(
        "chimera", {"models": [{"name": "ok"}, {"arch": "sdxl"}]})
    assert errs and "name" in errs[0]


def case_validate_oracle_needs_llm_model():
    assert srv._validate_archetype_config("oracle", {}) != []
    assert srv._validate_archetype_config("oracle", {"llm_model": ""}) != []
    assert srv._validate_archetype_config("oracle", {"llm_model": "gemma3:4b"}) == []


def case_validate_scalpel_needs_base_model():
    assert srv._validate_archetype_config("scalpel", {}) != []
    assert srv._validate_archetype_config(
        "scalpel", {"base_model": {"arch": "sdxl"}}) != []  # missing name
    assert srv._validate_archetype_config(
        "scalpel", {"base_model": {"name": "m1", "arch": "sdxl"}}) == []


# ── Forensic PNG extraction ───────────────────────────────────────────

def _build_png_with_text_chunks(chunks: dict) -> bytes:
    """Minimal valid PNG with tEXt chunks for each (key, value). Good
    enough for reverse_engineer_image to parse."""
    sig = b'\x89PNG\r\n\x1a\n'
    def _chunk(kind: bytes, body: bytes) -> bytes:
        length = struct.pack(">I", len(body))
        crc = struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)
        return length + kind + body + crc
    # 1×1 IHDR (gray, bit depth 1)
    ihdr = struct.pack(">IIBBBBB", 1, 1, 1, 0, 0, 0, 0)
    png = sig + _chunk(b"IHDR", ihdr)
    for key, value in chunks.items():
        body = key.encode("latin-1") + b"\x00" + value.encode("latin-1")
        png += _chunk(b"tEXt", body)
    # Empty IDAT + IEND
    png += _chunk(b"IDAT", zlib.compress(b"\x00\x00\x00"))
    png += _chunk(b"IEND", b"")
    return png


def case_forensic_extract_parses_workflow_chunk():
    fake_workflow = {"1": {"class_type": "CheckpointLoaderSimple"},
                     "2": {"class_type": "KSampler"}}
    png = _build_png_with_text_chunks({
        "workflow": json.dumps(fake_workflow),
    })
    b64 = base64.b64encode(png).decode("ascii")
    status, body = srv._spellcaster_forensic_extract(b64)
    assert status == 200, body
    assert body.get("ok") is True
    assert body["forensic"]["workflow"] == fake_workflow


def case_forensic_extract_plain_png_returns_clean_none():
    """A PNG with no workflow metadata should NOT error; the Forensic
    wizard wants a clean 'no metadata found' answer it can relay."""
    png = _build_png_with_text_chunks({})
    b64 = base64.b64encode(png).decode("ascii")
    status, body = srv._spellcaster_forensic_extract(b64)
    assert status == 200
    assert body.get("ok") is True
    assert body.get("forensic") is None
    assert "No ComfyUI" in body.get("note", "")


def case_forensic_extract_rejects_missing_image():
    status, body = srv._spellcaster_forensic_extract("")
    assert status == 400
    assert "image_b64" in body["error"]


def case_forensic_extract_rejects_bad_base64():
    status, body = srv._spellcaster_forensic_extract("not!!base64!!")
    assert status == 400
    assert "base64" in body["error"]


# ── Chimera router ────────────────────────────────────────────────────

def _seed_chimera_wizard(models: list) -> str:
    """Register a test Chimera wizard in CHARS_CACHE. Returns its id."""
    char_id = "archetype_chimera_testwiz"
    # Remove any prior seed from previous tests to keep cases isolated.
    srv.CHARS_CACHE[:] = [c for c in srv.CHARS_CACHE if c.get("id") != char_id]
    srv.CHARS_CACHE.append({
        "id": char_id,
        "type": "archetype",
        "archetype_kind": "chimera",
        "archetype_config": {"models": models},
        "name": "TestChimera",
    })
    return char_id


def case_chimera_routes_portrait_prompt_to_portrait_model():
    char_id = _seed_chimera_wizard([
        {"name": "m_portrait.safetensors", "arch": "sdxl", "domain": "portraits"},
        {"name": "m_landscape.safetensors", "arch": "flux1dev", "domain": "landscapes"},
    ])
    status, body = srv._spellcaster_chimera_route(
        "close-up portrait of a woman", char_id)
    assert status == 200
    assert body["picked_domain"] == "portraits"
    assert body["picked_model"]["name"] == "m_portrait.safetensors"


def case_chimera_falls_back_when_no_domain_match():
    char_id = _seed_chimera_wizard([
        {"name": "m1.safetensors", "arch": "sdxl", "domain": "auto"},
        {"name": "m2.safetensors", "arch": "flux1dev", "domain": "auto"},
    ])
    status, body = srv._spellcaster_chimera_route(
        "a shape in the void", char_id)
    assert status == 200
    assert body["picked_domain"] == "auto"
    assert body["picked_model"]["name"] == "m1.safetensors"


def case_chimera_route_unknown_wizard_404s():
    status, body = srv._spellcaster_chimera_route("hi", "nope_not_a_wizard")
    assert status == 404


def case_chimera_route_empty_models_409s():
    char_id = _seed_chimera_wizard([])
    status, body = srv._spellcaster_chimera_route("hi", char_id)
    assert status == 409


# ── Lore-keeper query ─────────────────────────────────────────────────

def case_lore_keeper_substring_match():
    # Seed the in-memory registry with a couple of LoRAs so the query
    # has something to find. We don't persist — the test runs against
    # whatever CHARS_CACHE / _LORA_REGISTRY the server has at import
    # time plus these adds, and we clean up after.
    backup = dict(srv._LORA_REGISTRY)
    srv._LORA_REGISTRY["Sinozick_Style.safetensors"] = {
        "archs": ["sdxl"], "trigger_words": ["sinozick style", "bold colors"],
    }
    srv._LORA_REGISTRY["feet_detail_v2.safetensors"] = {
        "archs": ["sdxl"], "trigger_words": ["detailed feet"],
    }
    try:
        status, body = srv._spellcaster_lore_keeper_query("sinozick", 5)
        assert status == 200
        names = [h["name"] for h in body["hits"]]
        assert "Sinozick_Style.safetensors" in names
        assert "feet_detail_v2.safetensors" not in names
    finally:
        srv._LORA_REGISTRY.clear()
        srv._LORA_REGISTRY.update(backup)


def case_lore_keeper_empty_query_returns_limit():
    backup = dict(srv._LORA_REGISTRY)
    srv._LORA_REGISTRY["a.safetensors"] = {"archs": ["sdxl"]}
    srv._LORA_REGISTRY["b.safetensors"] = {"archs": ["sdxl"]}
    srv._LORA_REGISTRY["c.safetensors"] = {"archs": ["sdxl"]}
    try:
        status, body = srv._spellcaster_lore_keeper_query("", 2)
        assert status == 200
        assert len(body["hits"]) == 2
    finally:
        srv._LORA_REGISTRY.clear()
        srv._LORA_REGISTRY.update(backup)


# ── Scalpel plan ──────────────────────────────────────────────────────

def _seed_scalpel_wizard(base_name: str = "sdxl_base.safetensors") -> str:
    char_id = "archetype_scalpel_testwiz"
    srv.CHARS_CACHE[:] = [c for c in srv.CHARS_CACHE if c.get("id") != char_id]
    srv.CHARS_CACHE.append({
        "id": char_id,
        "type": "archetype",
        "archetype_kind": "scalpel",
        "archetype_config": {"base_model": {"name": base_name, "arch": "sdxl"}},
        "name": "TestScalpel",
    })
    return char_id


def case_scalpel_plan_detects_erase():
    char_id = _seed_scalpel_wizard()
    status, body = srv._spellcaster_scalpel_plan(char_id, "erase the red car")
    assert status == 200
    assert body["plan"]["verb"] == "erase"
    assert any(s["step"] == "magic_eraser" for s in body["plan"]["steps"])


def case_scalpel_plan_detects_replace_and_references_base_model():
    char_id = _seed_scalpel_wizard("flux_klein.safetensors")
    status, body = srv._spellcaster_scalpel_plan(
        char_id, "change her dress to red")
    assert status == 200
    assert body["plan"]["verb"] == "replace"
    inpaint_step = next(s for s in body["plan"]["steps"]
                         if s["step"] == "klein_sam3_inpaint")
    assert "flux_klein.safetensors" in inpaint_step["note"]


def case_scalpel_plan_rejects_empty_instruction():
    char_id = _seed_scalpel_wizard()
    status, body = srv._spellcaster_scalpel_plan(char_id, "")
    assert status == 400


def case_scalpel_plan_rejects_non_scalpel_wizard():
    # Shove a non-Scalpel wizard with the same id pattern and confirm
    # the handler refuses it.
    char_id = "archetype_other_wizard"
    srv.CHARS_CACHE[:] = [c for c in srv.CHARS_CACHE if c.get("id") != char_id]
    srv.CHARS_CACHE.append({
        "id": char_id, "type": "archetype",
        "archetype_kind": "forensic", "name": "NotScalpel",
    })
    status, body = srv._spellcaster_scalpel_plan(char_id, "erase this")
    assert status == 404


# ── Archetype create (end-to-end validation + record shape) ──────────

def case_summon_archetype_forensic_creates_distinct_record():
    pre_count = len(srv.CHARS_CACHE)
    status, body = srv._spellcaster_summon_archetype(
        kind="forensic", name="DetectiveDusk",
        personality="Hard-boiled style.", subtext="", config={},
    )
    assert status == 200, body
    assert body["character"]["type"] == "archetype"
    assert body["character"]["archetype_kind"] == "forensic"
    assert body["character"]["system_prompt"]   # non-empty
    assert len(srv.CHARS_CACHE) == pre_count + 1
    # Cleanup
    srv.CHARS_CACHE[:] = [c for c in srv.CHARS_CACHE
                          if c.get("id") != body["character"]["id"]]


def case_summon_archetype_chimera_rejects_bad_config():
    status, body = srv._spellcaster_summon_archetype(
        kind="chimera", name="T", personality="", subtext="",
        config={"models": [{"name": "solo"}]},   # only 1 model
    )
    assert status == 400
    assert "2" in body["error"] or "invalid" in body["error"]


def case_summon_archetype_unknown_kind_400s():
    status, body = srv._spellcaster_summon_archetype(
        kind="wizard_of_nothing", name="x", personality="", subtext="",
        config={},
    )
    assert status == 400
    assert "unknown" in body["error"]


# ── Runner ─────────────────────────────────────────────────────────────

CASES = [
    ("catalogue: every UI archetype present",     case_catalogue_has_every_ui_archetype),

    ("validate: forensic empty config ok",        case_validate_forensic_empty_ok),
    ("validate: lore_keeper empty config ok",     case_validate_lore_keeper_empty_ok),
    ("validate: chimera enforces 2-5 models",     case_validate_chimera_needs_2_to_5_models),
    ("validate: chimera model must have name",    case_validate_chimera_model_must_have_name),
    ("validate: oracle requires llm_model",       case_validate_oracle_needs_llm_model),
    ("validate: scalpel requires base_model",     case_validate_scalpel_needs_base_model),

    ("forensic: parses workflow chunk from PNG",  case_forensic_extract_parses_workflow_chunk),
    ("forensic: plain PNG returns clean none",    case_forensic_extract_plain_png_returns_clean_none),
    ("forensic: rejects missing image",           case_forensic_extract_rejects_missing_image),
    ("forensic: rejects invalid base64",          case_forensic_extract_rejects_bad_base64),

    ("chimera: routes portrait prompt",           case_chimera_routes_portrait_prompt_to_portrait_model),
    ("chimera: falls back when no domain match",  case_chimera_falls_back_when_no_domain_match),
    ("chimera: unknown wizard 404s",              case_chimera_route_unknown_wizard_404s),
    ("chimera: empty models list 409s",           case_chimera_route_empty_models_409s),

    ("lore_keeper: substring match on triggers",  case_lore_keeper_substring_match),
    ("lore_keeper: empty query returns limit",    case_lore_keeper_empty_query_returns_limit),

    ("scalpel: plan detects erase",               case_scalpel_plan_detects_erase),
    ("scalpel: plan detects replace + base",      case_scalpel_plan_detects_replace_and_references_base_model),
    ("scalpel: rejects empty instruction",        case_scalpel_plan_rejects_empty_instruction),
    ("scalpel: rejects non-scalpel wizard",       case_scalpel_plan_rejects_non_scalpel_wizard),

    ("summon: forensic creates archetype record", case_summon_archetype_forensic_creates_distinct_record),
    ("summon: chimera rejects bad config",        case_summon_archetype_chimera_rejects_bad_config),
    ("summon: unknown kind 400s",                 case_summon_archetype_unknown_kind_400s),
]


def main():
    print("summon-wizard archetype tests")
    print("=" * 60)
    failures = []
    for label, fn in CASES:
        try:
            fn()
            print(f"  [OK]   {label}")
        except AssertionError as e:
            print(f"  [FAIL] {label}: {e}")
            failures.append(label)
        except Exception as e:  # noqa: BLE001
            print(f"  [ERR]  {label}: {type(e).__name__}: {e}")
            traceback.print_exc()
            failures.append(label)
    print("=" * 60)
    if failures:
        print(f"FAILED ({len(failures)}/{len(CASES)}):")
        for f in failures:
            print(f"  - {f}")
        return 1
    print(f"PASSED ({len(CASES)}/{len(CASES)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
