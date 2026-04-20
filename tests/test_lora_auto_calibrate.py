"""Tests for the auto-calibration stack.

Covers the three new modules and their integration into the existing
shootout engine:

  * spellcaster_core.lora_knowledge      — aggregator + NSFW classifier
  * spellcaster_core.lora_calibration_store — SFW/NSFW JSON persistence
  * scaffold.lora_grouping.resolve_shootout_recipe_for_lora — per-LoRA recipe

The Civitai live API is NOT exercised here — network calls are force-
disabled (`use_network=False`) so the tests are deterministic on a
plane. The tests DO exercise the sidecar path by writing a fake
`.civitai.info` file to a tempdir.

Run:
    PYTHONPATH=comfyui-spellcaster:. python tests/test_lora_auto_calibrate.py
"""

from __future__ import annotations

import json
import os
import struct
import sys
import tempfile
import traceback

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
for p in (os.path.join(_REPO, "comfyui-spellcaster"), _REPO):
    if p not in sys.path:
        sys.path.insert(0, p)


from spellcaster_core.lora_knowledge import (  # noqa: E402,F401
    LoraKnowledge, get_knowledge, classify_nsfw,
    set_cache_path, clear_cache, _normalise_sampler,
)
from spellcaster_core import lora_calibration_store as store  # noqa: E402
from spellcaster_core import lora_scorer as scorer  # noqa: E402


# ── Fakes / helpers ────────────────────────────────────────────────────

def _write_fake_safetensors(path: str, metadata: dict) -> None:
    """Minimal valid safetensors: 8-byte little-endian header length
    followed by a JSON header whose `__metadata__` field carries our
    test metadata. No tensors — lora_knowledge only reads the header."""
    header = {"__metadata__": {k: str(v) for k, v in metadata.items()}}
    body = json.dumps(header).encode("utf-8")
    with open(path, "wb") as f:
        f.write(struct.pack("<Q", len(body)))
        f.write(body)


def _write_sidecar(path: str, data: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)


# ── Sampler normalisation ──────────────────────────────────────────────

def case_normalise_sampler_known():
    assert _normalise_sampler("Euler a") == "euler_ancestral"
    assert _normalise_sampler("DPM++ 2M Karras") == "dpmpp_2m"
    assert _normalise_sampler("DPM++ 2M SDE Karras") == "dpmpp_2m_sde"
    assert _normalise_sampler("Euler") == "euler"
    assert _normalise_sampler("DDIM") == "ddim"
    assert _normalise_sampler("LCM") == "lcm"


def case_normalise_sampler_unknown_returns_none():
    assert _normalise_sampler("") is None
    assert _normalise_sampler("ThisIsNotASampler") is None


# ── NSFW classifier ────────────────────────────────────────────────────

def case_nsfw_civitai_flag_wins():
    k = LoraKnowledge(name="innocent_puppy.safetensors", nsfw=True)
    assert classify_nsfw(k, filename="innocent_puppy.safetensors") is True


def case_nsfw_filename_keywords():
    k = LoraKnowledge(name="my_nsfw_pack.safetensors")
    assert classify_nsfw(k, filename="my_nsfw_pack.safetensors") is True


def case_nsfw_trigger_word_keywords():
    k = LoraKnowledge(name="style.safetensors", trigger_words=["explicit content", "cool vibes"])
    assert classify_nsfw(k, filename="style.safetensors") is True


def case_nsfw_sfw_default():
    k = LoraKnowledge(name="lighting_pro_xl.safetensors",
                      trigger_words=["cinematic lighting"])
    assert classify_nsfw(k, filename="lighting_pro_xl.safetensors") is False


def case_nsfw_adult_variants():
    # Edge cases: r-18, xxx, adult, 18+ — conservative list
    k = LoraKnowledge(name="r-18-pack.safetensors")
    assert classify_nsfw(k, filename="r-18-pack.safetensors") is True
    k2 = LoraKnowledge(name="xxx_style.safetensors")
    assert classify_nsfw(k2, filename="xxx_style.safetensors") is True


# ── get_knowledge: offline-only path ──────────────────────────────────

def case_knowledge_empty_no_sources_returns_skeleton():
    k = get_knowledge("mystery_lora.safetensors", path=None,
                      use_network=False, use_civitai=False)
    assert isinstance(k, LoraKnowledge)
    assert k.name == "mystery_lora.safetensors"
    assert k.trigger_words == []
    # With no sources at all, heuristic has no base_model to work from
    assert k.recommended_weight is None


def case_knowledge_reads_safetensors_triggers():
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "test.safetensors")
        _write_fake_safetensors(p, {"ss_trigger_word": "myTrigger, other_trigger"})
        k = get_knowledge("test.safetensors", path=p,
                          use_network=False, use_civitai=False)
        assert "myTrigger" in k.trigger_words
        assert "other_trigger" in k.trigger_words
        assert k.provenance.get("trigger_words") == "safetensors"


def case_knowledge_reads_sidecar_civitai_info():
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "mylora.safetensors")
        # Empty safetensors header (no metadata)
        _write_fake_safetensors(p, {})
        sidecar = p + ".civitai.info"
        _write_sidecar(sidecar, {
            "trainedWords": ["zpop style", "bold colors"],
            "baseModel": "SDXL 1.0",
            "model": {"nsfw": False, "id": 12345},
            "images": [{"meta": {
                "prompt": "a photo <lora:MyLora:0.85> of a castle",
                "sampler": "DPM++ 2M Karras",
                "cfgScale": 7.5,
            }}],
        })
        k = get_knowledge("mylora.safetensors", path=p,
                          use_network=False, use_civitai=False)
        # Sidecar beat the empty safetensors header
        assert k.trigger_words == ["zpop style", "bold colors"]
        assert k.base_model == "sdxl"
        assert k.recommended_sampler == "dpmpp_2m"
        assert k.recommended_cfg == 7.5
        assert k.recommended_weight == 0.85
        assert k.civitai_model_id == 12345
        # Provenance tags sidecar entries correctly
        assert k.provenance.get("trigger_words") == "civitai_sidecar"


def case_knowledge_sidecar_nsfw_flag_flows_through():
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "adult_pack.safetensors")
        _write_fake_safetensors(p, {})
        _write_sidecar(p + ".civitai.info", {
            "model": {"nsfw": True, "id": 99},
            "baseModel": "SDXL 1.0",
        })
        k = get_knowledge("adult_pack.safetensors", path=p,
                          use_network=False, use_civitai=False)
        assert k.nsfw is True
        assert k.provenance.get("nsfw") == "civitai_sidecar"


def case_knowledge_user_override_beats_all_sources():
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "x.safetensors")
        _write_fake_safetensors(p, {"ss_trigger_word": "auto_guess"})
        _write_sidecar(p + ".civitai.info", {
            "trainedWords": ["civitai_pick"],
            "baseModel": "SDXL 1.0",
        })
        user = {
            "recommended_weight": 0.6,
            "trigger_words": ["user_final"],
        }
        k = get_knowledge("x.safetensors", path=p, user_override=user,
                          use_network=False, use_civitai=False)
        assert k.recommended_weight == 0.6
        assert k.trigger_words == ["user_final"]
        assert k.provenance["recommended_weight"] == "user"
        assert k.provenance["trigger_words"] == "user"


def case_knowledge_heuristic_weight_fills_missing():
    """Heuristic path: no weight from any source, but we know the
    base model → apply the arch-keyed default weight."""
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "flux_klein_lora.safetensors")
        _write_fake_safetensors(p, {})
        _write_sidecar(p + ".civitai.info", {
            "baseModel": "Flux.2 Klein",
            "trainedWords": ["klein_style"],
            # No images / no weight info
        })
        k = get_knowledge("flux_klein_lora.safetensors", path=p,
                          use_network=False, use_civitai=False)
        assert k.base_model == "flux2klein"
        assert k.recommended_weight == 1.0
        assert k.provenance.get("recommended_weight") == "heuristic"


# ── Calibration store: write/read round-trips ─────────────────────────

def case_store_write_read_sfw():
    with tempfile.TemporaryDirectory() as tmp:
        # Redirect both store paths to tempdir for the duration of the test
        store_sfw_orig = store.sfw_path
        store_nsfw_orig = store.nsfw_path
        store.sfw_path = lambda: os.path.join(tmp, "sfw.json")
        store.nsfw_path = lambda: os.path.join(tmp, "nsfw.json")
        try:
            p = store.write_calibration(
                "style_lora.safetensors",
                nsfw=False,
                recommended_weight=0.85,
                recommended_sampler="euler",
                trigger_words=["style_trigger"],
                base_model="sdxl",
                source="test",
                confirmed_by_user=True,
            )
            assert p.endswith("sfw.json")
            got = store.get_calibration("style_lora.safetensors")
            assert got is not None
            assert got["recommended_weight"] == 0.85
            assert got["recommended_sampler"] == "euler"
            assert got["confirmed_by_user"] is True
            # NSFW store is untouched
            assert store.load_nsfw() == {}
        finally:
            store.sfw_path = store_sfw_orig
            store.nsfw_path = store_nsfw_orig


def case_store_write_nsfw_goes_to_nsfw_file():
    with tempfile.TemporaryDirectory() as tmp:
        store_sfw_orig = store.sfw_path
        store_nsfw_orig = store.nsfw_path
        store.sfw_path = lambda: os.path.join(tmp, "sfw.json")
        store.nsfw_path = lambda: os.path.join(tmp, "nsfw.json")
        try:
            p = store.write_calibration(
                "adult_pack.safetensors",
                nsfw=True,
                recommended_weight=0.7,
                trigger_words=["explicit trigger"],
            )
            assert p.endswith("nsfw.json")
            # Only the NSFW file exists in tmp
            assert os.path.exists(os.path.join(tmp, "nsfw.json"))
            assert not os.path.exists(os.path.join(tmp, "sfw.json"))
            assert "adult_pack.safetensors" in store.load_nsfw()
            assert store.load_sfw() == {}
        finally:
            store.sfw_path = store_sfw_orig
            store.nsfw_path = store_nsfw_orig


def case_store_merged_lookup_nsfw_wins_collision():
    with tempfile.TemporaryDirectory() as tmp:
        store_sfw_orig = store.sfw_path
        store_nsfw_orig = store.nsfw_path
        store.sfw_path = lambda: os.path.join(tmp, "sfw.json")
        store.nsfw_path = lambda: os.path.join(tmp, "nsfw.json")
        try:
            store.write_calibration("dup.safetensors", nsfw=False,
                                     recommended_weight=0.5, source="sfw")
            store.write_calibration("dup.safetensors", nsfw=True,
                                     recommended_weight=0.9, source="nsfw")
            merged = store.load_merged()
            assert merged["dup.safetensors"]["recommended_weight"] == 0.9
            assert merged["dup.safetensors"]["source"] == "nsfw"
        finally:
            store.sfw_path = store_sfw_orig
            store.nsfw_path = store_nsfw_orig


def case_store_stats_counts_correctly():
    with tempfile.TemporaryDirectory() as tmp:
        store_sfw_orig = store.sfw_path
        store_nsfw_orig = store.nsfw_path
        store.sfw_path = lambda: os.path.join(tmp, "sfw.json")
        store.nsfw_path = lambda: os.path.join(tmp, "nsfw.json")
        try:
            store.write_calibration("a.safetensors", nsfw=False,
                                     confirmed_by_user=True)
            store.write_calibration("b.safetensors", nsfw=False)
            store.write_calibration("c.safetensors", nsfw=True,
                                     confirmed_by_user=True)
            s = store.stats()
            assert s["sfw_count"] == 2
            assert s["nsfw_count"] == 1
            assert s["confirmed_count"] == 2
        finally:
            store.sfw_path = store_sfw_orig
            store.nsfw_path = store_nsfw_orig


def case_store_remove_calibration():
    with tempfile.TemporaryDirectory() as tmp:
        store_sfw_orig = store.sfw_path
        store_nsfw_orig = store.nsfw_path
        store.sfw_path = lambda: os.path.join(tmp, "sfw.json")
        store.nsfw_path = lambda: os.path.join(tmp, "nsfw.json")
        try:
            store.write_calibration("gone.safetensors", nsfw=False)
            assert store.get_calibration("gone.safetensors") is not None
            n = store.remove_calibration("gone.safetensors")
            assert n == 1
            assert store.get_calibration("gone.safetensors") is None
        finally:
            store.sfw_path = store_sfw_orig
            store.nsfw_path = store_nsfw_orig


# ── Integration: lora_grouping.resolve_shootout_recipe_for_lora ────────

def case_recipe_stitches_triggers_into_prompt():
    # Direct call of the exposed helper via the knowledge pipeline.
    # Here we feed a user_override that populates triggers; the recipe
    # should prepend them to the base template and clamp strength.
    from scaffold.lora_grouping import resolve_shootout_recipe_for_lora
    recipe = resolve_shootout_recipe_for_lora(
        "my_lora.safetensors",
        purpose_group="style_photoreal",
        arch="sdxl",
        user_override={
            "recommended_weight": 0.7,
            "trigger_words": ["test trigger"],
        },
        use_network=False,
    )
    assert "test trigger" in recipe["prompt"]
    assert recipe["strength"] == 0.7
    assert recipe["provenance"].get("recommended_weight") == "user"
    assert recipe["nsfw"] is False


def case_recipe_clamps_wild_strength():
    from scaffold.lora_grouping import resolve_shootout_recipe_for_lora
    # Out-of-band weight in user override should clamp to 1.5 max.
    recipe = resolve_shootout_recipe_for_lora(
        "weird.safetensors",
        purpose_group="other",
        arch="sdxl",
        user_override={"recommended_weight": 5.0},
        use_network=False,
    )
    assert recipe["strength"] == 1.5


def case_recipe_nsfw_flag_propagates():
    from scaffold.lora_grouping import resolve_shootout_recipe_for_lora
    recipe = resolve_shootout_recipe_for_lora(
        "my_nsfw_pack.safetensors",
        purpose_group="action_pose",
        arch="sdxl",
        use_network=False,
    )
    # Filename keyword fired the classifier
    assert recipe["nsfw"] is True


# ── Vision scorer (mocked Ollama) ──────────────────────────────────────

def case_scorer_extract_pure_json():
    got = scorer._extract_score_json('{"score": 8.5, "reason": "good"}')
    assert got == {"score": 8.5, "reason": "good"}


def case_scorer_extract_json_wrapped_in_markdown():
    raw = 'Here you go:\n```json\n{"score": 6, "reason": "ok"}\n```\n'
    got = scorer._extract_score_json(raw)
    assert got and got["score"] == 6


def case_scorer_extract_number_scrape_last_resort():
    raw = "I give it a score: 9 because it looks sharp"
    got = scorer._extract_score_json(raw)
    assert got and got["score"] == 9.0


def case_scorer_clamp_out_of_range():
    assert scorer._clamp_score(15) == 10.0       # clamped to max
    assert scorer._clamp_score(-3) == 0.0        # clamped to min
    assert scorer._clamp_score("7.8") == 7.8
    assert scorer._clamp_score(85) == 8.5        # 0-100 rescale
    assert scorer._clamp_score("bad") is None


def case_scorer_network_offline_returns_error():
    # Dead port — nothing should be listening here.
    r = scorer.score_image(
        image_b64="aGVsbG8=",   # base64 of "hello"
        prompt="a cat",
        ollama_url="http://127.0.0.1:59997",
        timeout=1.0,
    )
    assert r.ok is False
    assert r.score is None
    assert "network" in r.error or "HTTP" in r.error


def case_scorer_probe_offline_reports_reason():
    r = scorer.probe_available(
        ollama_url="http://127.0.0.1:59997",
        timeout=1.0,
    )
    assert r["ok"] is False
    assert "unreachable" in r["reason"] or "HTTP" in r["reason"]


def case_scorer_parses_mocked_good_response():
    """Hit a fake Ollama via stdlib HTTPServer. Verifies the whole
    request+response pipe — POST body shape, JSON extraction,
    ScoreResult population."""
    import json as _json, threading as _th
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a, **kw): pass
        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0"))
            self.rfile.read(length)
            resp = {"message": {"content": '{"score": 8.3, "reason": "on prompt"}'}}
            body = _json.dumps(resp).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    srv = HTTPServer(("127.0.0.1", 0), H)
    port = srv.server_address[1]
    t = _th.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        r = scorer.score_image(
            image_b64="aGVsbG8=",
            prompt="a cat in a field",
            ollama_url=f"http://127.0.0.1:{port}",
            timeout=3.0,
        )
        assert r.ok is True, f"got error: {r.error}"
        assert r.score == 8.3
        assert "on prompt" in r.reason
    finally:
        srv.shutdown()


def case_scorer_rejects_non_json_model_response():
    """The model went off-script. Scorer must NOT crash or return
    junk — it flags .ok=False with a diagnostic."""
    import json as _json, threading as _th
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a, **kw): pass
        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0"))
            self.rfile.read(length)
            resp = {"message": {"content": "Sure! The image looks pretty nice overall."}}
            body = _json.dumps(resp).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    srv = HTTPServer(("127.0.0.1", 0), H)
    port = srv.server_address[1]
    t = _th.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        r = scorer.score_image(
            image_b64="aGVsbG8=", prompt="cat",
            ollama_url=f"http://127.0.0.1:{port}", timeout=3.0,
        )
        assert r.ok is False
        assert r.score is None
        assert "bad content" in r.error or "unparseable" in r.error
    finally:
        srv.shutdown()


def case_recipe_graceful_fallback_on_knowledge_error():
    """Forcing a knowledge error should degrade cleanly, not crash."""
    from scaffold.lora_grouping import resolve_shootout_recipe_for_lora
    import spellcaster_core.lora_knowledge as lk
    orig = lk.get_knowledge
    try:
        lk.get_knowledge = lambda *a, **kw: (_ for _ in ()).throw(
            RuntimeError("boom"))
        recipe = resolve_shootout_recipe_for_lora(
            "any.safetensors",
            purpose_group="portrait_f" if False else "other",
            arch="sdxl",
            use_network=False,
        )
        # Fell back to group default — still rendering-ready.
        assert isinstance(recipe, dict)
        assert "prompt" in recipe
        assert recipe["strength"] > 0
        assert "error" in recipe["provenance"]
    finally:
        lk.get_knowledge = orig


# ── Runner ─────────────────────────────────────────────────────────────

CASES = [
    ("sampler: A1111 names normalise to ComfyUI",       case_normalise_sampler_known),
    ("sampler: unknown input returns None",             case_normalise_sampler_unknown_returns_none),

    ("nsfw: explicit civitai flag wins",                case_nsfw_civitai_flag_wins),
    ("nsfw: filename keyword detection",                case_nsfw_filename_keywords),
    ("nsfw: trigger word keyword detection",            case_nsfw_trigger_word_keywords),
    ("nsfw: default SFW for benign LoRA",               case_nsfw_sfw_default),
    ("nsfw: r-18 / xxx variants caught",                case_nsfw_adult_variants),

    ("knowledge: empty returns skeleton",               case_knowledge_empty_no_sources_returns_skeleton),
    ("knowledge: safetensors triggers parsed",          case_knowledge_reads_safetensors_triggers),
    ("knowledge: civitai sidecar maps fields",          case_knowledge_reads_sidecar_civitai_info),
    ("knowledge: sidecar NSFW flag propagates",         case_knowledge_sidecar_nsfw_flag_flows_through),
    ("knowledge: user override beats every source",     case_knowledge_user_override_beats_all_sources),
    ("knowledge: heuristic weight fills gaps",          case_knowledge_heuristic_weight_fills_missing),

    ("store: write/read SFW round-trip",                case_store_write_read_sfw),
    ("store: nsfw=True routes to NSFW file",            case_store_write_nsfw_goes_to_nsfw_file),
    ("store: merged view, NSFW wins collision",         case_store_merged_lookup_nsfw_wins_collision),
    ("store: stats counts confirmed correctly",         case_store_stats_counts_correctly),
    ("store: remove_calibration purges entry",          case_store_remove_calibration),

    ("recipe: stitches triggers into prompt",           case_recipe_stitches_triggers_into_prompt),
    ("recipe: clamps wild strength to 1.5",             case_recipe_clamps_wild_strength),
    ("recipe: NSFW flag propagates to recipe",          case_recipe_nsfw_flag_propagates),
    ("recipe: knowledge error degrades gracefully",     case_recipe_graceful_fallback_on_knowledge_error),

    ("scorer: extract pure JSON",                       case_scorer_extract_pure_json),
    ("scorer: extract JSON wrapped in markdown",        case_scorer_extract_json_wrapped_in_markdown),
    ("scorer: number scrape last resort",               case_scorer_extract_number_scrape_last_resort),
    ("scorer: clamp out-of-range scores",               case_scorer_clamp_out_of_range),
    ("scorer: offline Ollama returns error",            case_scorer_network_offline_returns_error),
    ("scorer: probe offline reports reason",            case_scorer_probe_offline_reports_reason),
    ("scorer: parses mocked good response",             case_scorer_parses_mocked_good_response),
    ("scorer: rejects non-JSON model response",         case_scorer_rejects_non_json_model_response),
]


def main():
    print("lora auto-calibrate stack tests")
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
