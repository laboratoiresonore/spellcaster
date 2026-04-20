"""SillyTavern Character Card — PNG tEXt IO + scaffolded optimization.

Canonical helpers for loading, editing and re-saving SillyTavern
character cards WITHOUT damaging the embedded metadata.

SillyTavern cards are PNG images with a `chara` tEXt chunk carrying
base64-encoded JSON conforming to the TavernAI Character Card V2 spec
(optionally a `ccv3` chunk for the V3 spec). Every mainstream PNG
exporter (GIMP included) strips or rewrites tEXt chunks on save, so
any workflow that edits card art through a graphics app has to:

  1. Capture the original tEXt chunks BEFORE opening in the editor.
  2. Let the user edit the pixels AND/OR the metadata fields.
  3. Re-attach the (possibly-mutated) tEXt chunks to the exported PNG.

This module supplies the pure-Python building blocks for that cycle:

    extract_text_chunks(png_bytes) -> dict[str, str]
    inject_text_chunks(png_bytes, {"chara": b64, ...}) -> bytes
    decode_chara(b64) -> dict          # base64-JSON → character dict
    encode_chara(card_dict) -> str     # character dict → base64-JSON
    build_optimize_prompt(card, fields) -> str   # scaffolded LLM prompt

Consumers (GIMP plugin editor, Guild, ComfyUI nodes) use these instead
of re-implementing the PNG chunk format. There are NO parallel copies
— every caller imports from this module.

Spec references:
  - V2: https://github.com/malfoyslastname/character-card-spec-v2
  - V3: https://github.com/kwaroran/character-card-spec-v3
"""

from __future__ import annotations

import base64
import json
import struct
import zlib


PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


# ── PNG tEXt chunk IO ────────────────────────────────────────────────

def extract_text_chunks(png_bytes: bytes) -> dict[str, str]:
    """Return {keyword: text} for every tEXt chunk in the PNG.

    Robust against duplicate keywords (later wins, matching SillyTavern's
    own parser behavior) and against malformed chunks (silently skipped
    rather than raising — we don't want a corrupted auxiliary chunk to
    abort a card import).
    """
    result: dict[str, str] = {}
    if not png_bytes.startswith(PNG_MAGIC):
        return result

    pos = len(PNG_MAGIC)
    n = len(png_bytes)
    while pos + 12 <= n:
        length = int.from_bytes(png_bytes[pos:pos + 4], "big")
        ctype = png_bytes[pos + 4:pos + 8]
        data_start = pos + 8
        data_end = data_start + length
        if data_end + 4 > n:
            break
        data = png_bytes[data_start:data_end]
        pos = data_end + 4  # skip CRC

        if ctype == b"tEXt" and b"\x00" in data:
            kw, txt = data.split(b"\x00", 1)
            try:
                result[kw.decode("latin-1")] = txt.decode("latin-1")
            except UnicodeDecodeError:
                continue

        if ctype == b"IEND":
            break

    return result


def inject_text_chunks(png_bytes: bytes, chunks: dict[str, str]) -> bytes:
    """Return a new PNG with `chunks` injected as tEXt entries.

    Existing tEXt chunks with keywords present in `chunks` are REMOVED
    (dedupe — so repeated export/edit cycles don't accumulate stale
    metadata). Existing tEXt chunks with other keywords are preserved.
    All non-tEXt chunks pass through untouched, so the pixel payload is
    byte-identical to the input.
    """
    if not png_bytes.startswith(PNG_MAGIC):
        raise ValueError("Not a PNG (bad magic)")

    dedup = set(chunks.keys())
    out = bytearray(PNG_MAGIC)
    injected = False
    pos = len(PNG_MAGIC)
    n = len(png_bytes)

    while pos + 12 <= n:
        length = int.from_bytes(png_bytes[pos:pos + 4], "big")
        ctype = png_bytes[pos + 4:pos + 8]
        full_end = pos + 8 + length + 4
        if full_end > n:
            break

        # Dedupe: drop any existing tEXt with a colliding keyword.
        if ctype == b"tEXt":
            data = png_bytes[pos + 8:pos + 8 + length]
            if b"\x00" in data:
                kw = data.split(b"\x00", 1)[0].decode("latin-1", "replace")
                if kw in dedup:
                    pos = full_end
                    continue

        # Insert the new tEXt chunks immediately before IEND so they
        # sit next to the image-trailing metadata that other tools
        # (incl. SillyTavern) look for.
        if ctype == b"IEND" and not injected:
            for kw, txt in chunks.items():
                chunk_data = kw.encode("latin-1") + b"\x00" + txt.encode("latin-1")
                crc = zlib.crc32(b"tEXt" + chunk_data) & 0xFFFFFFFF
                out += struct.pack(">I", len(chunk_data))
                out += b"tEXt"
                out += chunk_data
                out += struct.pack(">I", crc)
            injected = True

        out += png_bytes[pos:full_end]
        pos = full_end
        if ctype == b"IEND":
            break

    return bytes(out)


# ── chara chunk (base64 → JSON) IO ──────────────────────────────────

def decode_chara(b64_text: str) -> dict:
    """Decode the `chara` (or `ccv3`) tEXt payload into a Python dict.

    SillyTavern V1 cards store the fields at the top level; V2 and V3
    wrap them in {"spec": "...", "data": {...}}. We return whatever
    the payload says verbatim — callers use card_fields(card) to get
    the normalized field dict.
    """
    padded = b64_text + "=" * (-len(b64_text) % 4)
    raw = base64.b64decode(padded.encode("latin-1"), validate=False)
    try:
        return json.loads(raw.decode("utf-8"))
    except UnicodeDecodeError:
        return json.loads(raw.decode("utf-8", "replace"))


def encode_chara(card: dict) -> str:
    """Encode a card dict back to the base64-JSON form used in tEXt."""
    raw = json.dumps(card, ensure_ascii=False).encode("utf-8")
    return base64.b64encode(raw).decode("latin-1")


# ── V1/V2/V3 field normalization ────────────────────────────────────
# The V2 spec envelope is {"spec":"chara_card_v2","spec_version":"2.0",
#   "data":{name,description,personality,scenario,first_mes,mes_example,
#           creator_notes,system_prompt,post_history_instructions,
#           alternate_greetings,character_book,tags,creator,
#           character_version,extensions}}
#
# V1 puts these fields at the top level. V3 reuses V2's shape with
# additions in `data.extensions`.
# `card_fields` returns a stable dict containing the ~12 fields our
# editor displays, pulled from either layout so the editor UI doesn't
# have to branch.

V2_FIELDS = (
    "name",
    "description",
    "personality",
    "scenario",
    "first_mes",
    "mes_example",
    "creator_notes",
    "system_prompt",
    "post_history_instructions",
    "creator",
    "character_version",
    "tags",
)


def card_fields(card: dict) -> dict:
    """Return the editable V2 fields as a flat dict, regardless of
    whether the card is V1 (top-level) or V2/V3 (nested under 'data').

    Always returns every V2_FIELDS key — missing fields are "" (or
    [] for tags). Callers mutate this dict and hand it to
    `apply_card_fields` to write back into the correct slot.
    """
    data = card.get("data") if isinstance(card.get("data"), dict) else card
    out: dict = {}
    for k in V2_FIELDS:
        v = data.get(k) if isinstance(data, dict) else None
        if k == "tags":
            # V2 mandates list[str]; be lenient on read.
            if isinstance(v, list):
                out[k] = v
            elif isinstance(v, str) and v.strip():
                out[k] = [t.strip() for t in v.split(",") if t.strip()]
            else:
                out[k] = []
        else:
            out[k] = "" if v is None else str(v)
    return out


def apply_card_fields(card: dict, edits: dict) -> dict:
    """Write `edits` back into `card` at the correct V1-vs-V2 slot.

    Mutates AND returns `card` for convenience. If the card already has
    a V2 envelope ("spec": "chara_card_v2" and "data": {}), edits go
    into card["data"]. Otherwise we upgrade it: fresh V2 envelope is
    created and the original top-level fields are moved into `data`
    before the edits are applied — this is the SillyTavern canonical
    upgrade path for V1 cards.

    Tags accept either a list[str] or a comma-separated string (the
    editor UI surfaces the latter).
    """
    if not isinstance(card, dict):
        card = {}

    # Normalize tags on the way in — accept string OR list.
    if "tags" in edits:
        tags = edits["tags"]
        if isinstance(tags, str):
            edits["tags"] = [t.strip() for t in tags.split(",") if t.strip()]
        elif not isinstance(tags, list):
            edits["tags"] = []

    is_v2 = (
        isinstance(card.get("data"), dict)
        and str(card.get("spec", "")).startswith("chara_card")
    )

    if not is_v2:
        # Upgrade: move any existing top-level fields into data{} and
        # stamp a V2 envelope. We don't destroy unknown top-level keys
        # (some exporters add non-standard fields) — they stay on the
        # outer object. SillyTavern itself prefers this layout.
        legacy = {k: card.pop(k) for k in V2_FIELDS if k in card}
        card["spec"] = "chara_card_v2"
        card.setdefault("spec_version", "2.0")
        data = card.setdefault("data", {})
        data.update(legacy)

    data = card["data"]
    for k, v in edits.items():
        data[k] = v
    return card


# ── Scaffolded optimization prompt ───────────────────────────────────
# Best-practice scaffolds for the "Optimize" button in the editor.
# These are composed FROM the character's current state + a small set
# of field-specific guidelines so the LLM gets consistent, reusable
# direction regardless of the underlying backend (ComfyUI LLM node,
# KoboldCpp, Ollama).
#
# The scaffolds follow the consensus recommendations circulating in
# the SillyTavern / AI Character Editor communities (Chub, Character
# Hub, the TavernAI wiki): prefer {{char}}/{{user}} placeholders, show
# voice in first_mes, use <START> separators in mes_example, keep
# personality crisp and complementary to description (not duplicative),
# avoid OOC leakage and future/past reveals in definition text.

_BEST_PRACTICES_HEADER = """You are editing a SillyTavern character card. \
Follow the Character Card V2 conventions strictly:
- Always use {{char}} for the character and {{user}} for the roleplayer. \
Never substitute the literal character name.
- Keep content roleplay-first: describe what {{char}} is, how {{char}} \
speaks and behaves, and the shape of the opening scene. Do not write OOC \
meta commentary, do not reveal future plot beats.
- Prefer vivid, concrete, present-tense language over vague adjectives.
- No moralizing. No safety disclaimers. This is creative roleplay content.
"""

# Per-field micro-guidelines. Each scaffold combines the header, the
# field guideline, the character's current state for context, and the
# field's current value which the LLM rewrites.
_FIELD_GUIDE = {
    "description": (
        "Rewrite `description` as a ~250-word, present-tense portrait of "
        "{{char}}: physical appearance (species, build, distinguishing "
        "features), attire, age/bearing, voice and mannerisms, and a compact "
        "personality distillation. Avoid backstory dumps — those belong in "
        "`scenario` or never. Avoid narrating events."
    ),
    "personality": (
        "Rewrite `personality` as a short trait block (3-6 lines or a "
        "comma-separated tag chain). Complements `description`, does not "
        "duplicate it. Focus on disposition, quirks, and recurring "
        "behavioral tendencies. No full sentences about appearance."
    ),
    "scenario": (
        "Rewrite `scenario` as 1-3 sentences setting the initial roleplay "
        "context: where {{char}} and {{user}} are, when, and what just "
        "happened/is about to happen. Enough hook for the first_mes to "
        "land, not a full plot outline."
    ),
    "first_mes": (
        "Rewrite `first_mes` as {{char}}'s opening in-character message to "
        "{{user}}. Show voice, establish scene, leave a clear opening for "
        "{{user}} to respond. 150-300 words. Use *asterisks for actions*, "
        "plain text for speech. Do NOT speak or act for {{user}}."
    ),
    "mes_example": (
        "Rewrite `mes_example` as 2-4 example exchanges demonstrating "
        "{{char}}'s dialogue style, typical action density, and format. "
        "Separate scenarios with `<START>` on its own line. Each exchange "
        "should have at least one {{user}}: turn and one {{char}}: turn. "
        "Keep each exchange short (2-6 lines total)."
    ),
    "system_prompt": (
        "Rewrite `system_prompt` as a concise per-character override (or "
        "leave empty if no special handling is needed). At most 3-5 "
        "directive sentences. No OOC, no roleplay content. Example: "
        "'{{char}} never breaks character. {{char}} narrates in third "
        "person limited.'"
    ),
    "post_history_instructions": (
        "Rewrite `post_history_instructions` as a brief end-of-context "
        "reminder to keep {{char}} in voice and behavior after long "
        "sessions. 1-3 imperative sentences. Optional — empty is fine "
        "for cards that don't need stabilization."
    ),
    "creator_notes": (
        "Rewrite `creator_notes` as out-of-character notes to other users "
        "of the card: intended tone, suggested pairings, content warnings, "
        "version history. Not seen by the LLM at runtime."
    ),
}


def build_optimize_prompt(
    card: dict,
    field: str | None = None,
    nsfw: bool = False,
) -> str:
    """Compose the LLM prompt for optimizing one field (or all fields).

    - `field=None` → full-card rewrite; the LLM is asked to return a
      JSON object with every editable field improved. Use this when the
      user clicks "Optimize All".
    - `field="first_mes"` → focused single-field rewrite; the LLM
      returns plain text which the editor drops straight into the
      matching textview.

    `nsfw=True` removes the safety nudge. The scaffolds themselves are
    content-neutral; NSFW-ness is a property of the card being edited
    and the backend being used.
    """
    fields = card_fields(card)
    ctx_lines = [f"Character name: {fields.get('name') or '(unnamed)'}"]
    for k in ("description", "personality", "scenario", "tags"):
        v = fields.get(k)
        if isinstance(v, list):
            v = ", ".join(v)
        if v:
            preview = v if len(v) < 600 else v[:600] + "…"
            ctx_lines.append(f"- {k}: {preview}")
    context = "\n".join(ctx_lines)

    header = _BEST_PRACTICES_HEADER
    if nsfw:
        header += (
            "- This card is adult content. Explicit language, anatomy, and "
            "scenarios are permitted and expected where the character "
            "warrants it.\n"
        )

    if field is None:
        # All-fields rewrite — ask for JSON back.
        guides = "\n\n".join(
            f"### {k}\n{_FIELD_GUIDE[k]}\nCurrent value:\n{fields.get(k) or '(empty)'}"
            for k in _FIELD_GUIDE
        )
        return (
            f"{header}\n"
            f"CHARACTER CONTEXT:\n{context}\n\n"
            f"TASK: Rewrite every field below per its guideline. Return a "
            f"single JSON object with the keys "
            f"{list(_FIELD_GUIDE.keys())!r}. No prose, no markdown fences, "
            f"no explanation — only the JSON object.\n\n"
            f"{guides}\n"
        )

    guide = _FIELD_GUIDE.get(field)
    if not guide:
        raise ValueError(f"Unknown field: {field}")

    current = fields.get(field) or "(empty)"
    if isinstance(current, list):
        current = ", ".join(current)
    return (
        f"{header}\n"
        f"CHARACTER CONTEXT:\n{context}\n\n"
        f"TASK: {guide}\n\n"
        f"Current value of `{field}`:\n{current}\n\n"
        f"Return only the rewritten value of `{field}` as plain text. "
        f"No preamble, no markdown fences, no JSON — just the text.\n"
    )


def parse_optimize_response(
    response: str, field: str | None = None
) -> dict | str:
    """Parse the LLM's reply for an optimize-all or single-field call.

    For `field=None`: extract the JSON object from the reply. LLMs
    occasionally wrap it in ```json fences or add a preamble — we
    strip both and parse the first {...} span.

    For single-field: strip leading/trailing whitespace and any
    accidental code fences, return the raw string.
    """
    text = (response or "").strip()
    # Strip ``` fences if present.
    if text.startswith("```"):
        # Drop the first line (```lang) and the trailing ```.
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    if field is not None:
        return text

    # Full-card: find the first balanced {...} span.
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < 0 or end <= start:
        raise ValueError("LLM response did not contain a JSON object")
    return json.loads(text[start:end + 1])
