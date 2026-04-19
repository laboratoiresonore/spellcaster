"""R84: tiny helper shared by all standalone scripts.

Every script needs the same two things: a way to find ``shared/``
when Resolve strips ``__file__``, and a reachable GuildClient. This
module centralises both so individual scripts can be tiny.

Keep this file dependency-free beyond the stdlib so it works inside
Resolve's bundled Python without ``requests`` or ``urllib3``.
"""
from __future__ import annotations

import os
import sys


def script_dir() -> str:
    """Best-effort lookup of the script's directory. Mirrors
    _script_dir in each main script — duplicated here so
    _spellcaster_common stays self-contained even if imported before
    shared/ is on sys.path."""
    try:
        return os.path.dirname(os.path.abspath(__file__))
    except NameError:
        pass
    if os.name == "nt":
        appdata = os.environ.get("APPDATA", "")
        if appdata:
            return os.path.join(
                appdata, "Blackmagic Design", "DaVinci Resolve",
                "Support", "Fusion", "Scripts", "Utility", "Spellcaster")
    elif sys.platform == "darwin":
        return os.path.expanduser(
            "~/Library/Application Support/Blackmagic Design/DaVinci Resolve"
            "/Fusion/Scripts/Utility/Spellcaster")
    else:
        return os.path.expanduser(
            "~/.local/share/DaVinciResolve/Fusion/Scripts/Utility/Spellcaster")
    return ""


def add_shared_to_path() -> bool:
    here = script_dir()
    if not here:
        return False
    for cand in (
        os.path.join(here, "shared"),
        os.path.normpath(os.path.join(here, "..", "shared")),
        os.path.normpath(os.path.join(here, "..", "..", "shared")),
    ):
        if os.path.isdir(cand) and cand not in sys.path:
            sys.path.insert(0, cand)
            return True
    return False


def guild_or_die():
    """Return a reachable GuildClient, or show a modal + raise SystemExit(1).

    Factors out the "find Guild, show error if not reachable" pattern
    that every script needs.
    """
    add_shared_to_path()
    try:
        from spellcaster_api import GuildClient, discover_guild_url
        from resolve_helpers import show_message
    except ImportError as e:
        print(f"[Spellcaster] Plugin not fully installed: {e}")
        raise SystemExit(1)
    guild = GuildClient(discover_guild_url())
    if not guild.is_reachable():
        show_message("Spellcaster",
                     "Can't reach the Wizard Guild.\n\n"
                     "Start the Guild (Wizard Guild.bat / .sh) and try again.")
        raise SystemExit(1)
    return guild


def enhance_prompt(guild, raw: str, *, max_tokens: int = 180,
                    temperature: float = 0.7) -> str:
    """R96: send a terse prompt to the Guild's LLM and get back a
    verbose, visually-rich expansion suitable for video generation.

    Uses /api/llm_generate (the Guild's unified LLM proxy — ComfyUI
    LLM nodes first, KoboldCpp fallback, Ollama last, per
    spellcaster_core.guild_llm). The system prompt is tuned for the
    "short-to-rich visual description" task: preserves the core
    subject, adds lighting / camera / material / mood details, stays
    under ~60 tokens of prose.

    Returns the enhanced prompt (or the raw input on failure, so
    callers never get an empty string).
    """
    raw = (raw or "").strip()
    if not raw:
        return raw
    try:
        from spellcaster_api import GuildError  # noqa: F401
    except ImportError:
        return raw

    system = (
        "You are a cinematographer writing prompts for a video "
        "diffusion model. Rewrite the user's brief prompt as a vivid, "
        "2-4 sentence shot description. Include: camera movement, "
        "lighting quality, key materials/textures, and mood. Keep the "
        "SUBJECT unchanged. Do not add narrative, dialogue, or "
        "characters that weren't in the original. Output ONLY the "
        "rewritten prompt — no preamble, no quotes."
    )
    full = f"{system}\n\nUSER PROMPT: {raw}\n\nREWRITTEN:"
    try:
        result = guild._post_json("/api/llm_generate", {
            "prompt": full,
            "max_length": max_tokens,
            "temperature": temperature,
            "stop_sequence": ["\n\n", "USER PROMPT:"],
        }, timeout=60.0)
    except Exception:
        return raw
    # Kobold-style envelope
    texts = result.get("results") or []
    if not texts:
        return raw
    enhanced = (texts[0].get("text") or "").strip()
    # Strip any lingering system-leaked prefix
    for prefix in ("REWRITTEN:", "Rewritten:", "PROMPT:"):
        if enhanced.startswith(prefix):
            enhanced = enhanced[len(prefix):].strip()
    return enhanced or raw
