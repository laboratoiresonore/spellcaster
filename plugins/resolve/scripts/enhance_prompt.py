"""Enhance Prompt → LLM-powered prompt expansion

Type a short, terse prompt. Get back a vivid, cinematographer-grade
rewrite with lighting, camera, and material detail — tuned for video
diffusion models. Copy the output into the next VFX script or paste
into the Guild UI.

Editor example:
  Input:  "dragon fire"
  Output: "A massive crimson dragon exhales a roiling torrent of
           golden-orange flame across a misty highland valley. Low-
           angle wide shot, slow dolly push, volumetric god-rays
           cutting through the smoke, ember-lit rocks in foreground.
           Cinematic, 35mm, shallow depth."

Routes through the Guild's unified LLM proxy, so it picks up whatever
backend is configured (ComfyUI Qwen GGUF, KoboldCpp, Ollama).

Menu: Workspace > Scripts > Spellcaster > Enhance Prompt
"""
from __future__ import annotations

import os
import sys
import traceback

def _boot():
    try:
        d = os.path.dirname(os.path.abspath(__file__))
    except NameError:
        if os.name == "nt":
            d = os.path.join(os.environ.get("APPDATA", ""),
                              "Blackmagic Design", "DaVinci Resolve",
                              "Support", "Fusion", "Scripts",
                              "Utility", "💎 Spellcaster")
        elif sys.platform == "darwin":
            d = os.path.expanduser(
                "~/Library/Application Support/Blackmagic Design/DaVinci Resolve"
                "/Fusion/Scripts/Utility/💎 Spellcaster")
        else:
            d = os.path.expanduser(
                "~/.local/share/DaVinciResolve/Fusion/Scripts/Utility/💎 Spellcaster")
    if d and d not in sys.path:
        sys.path.insert(0, d)
_boot()

import _spellcaster_common as _sc  # noqa: E402


def main() -> int:
    guild = _sc.guild_or_die()
    from resolve_helpers import show_message, prompt_text

    raw = prompt_text(
        "Enhance Prompt",
        "Type a short prompt to expand:",
        default="",
    )
    if raw is None:
        return 0
    raw = (raw or "").strip()
    if not raw:
        show_message("Spellcaster", "No prompt to enhance.")
        return 0

    enhanced = _sc.enhance_prompt(guild, raw)
    if enhanced == raw:
        show_message(
            "Spellcaster",
            "LLM enhancement failed or returned empty. Check that the "
            "Guild has a reachable LLM backend "
            "(ComfyUI Qwen node, KoboldCpp, or Ollama).",
        )
        return 1

    show_message(
        "Spellcaster",
        f"Enhanced prompt:\n\n{enhanced}\n\n"
        f"— — — — —\n\n"
        f"Original: {raw}\n\n"
        f"Copy the enhanced text and paste it into the next "
        f"VFX / generation script, or into the Guild UI prompt field.",
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception:
        traceback.print_exc()
        sys.exit(1)
