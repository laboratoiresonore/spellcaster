"""Generate Audio Track → Ovi text-to-audio-video

Text-prompt → short clip with synchronised audio (speech, effects,
ambient). Uses the Ovi preset (VRAM-minimal t2av model registered in
WANGP_PRESETS). Output is a 720p MP4 with built-in audio track that
auto-imports into the Media Pool via the Bridge.

Typical uses:
  • Quick ambient beds (the editor needs 5s of rain + wind at 30% opacity)
  • One-line scratch dialogue for temp mixes
  * Character VO pickup with a specific delivery

Menu: Workspace > Scripts > 💎 Spellcaster > 💎 generate_audio_track
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
    from spellcaster_api import GuildError
    from resolve_helpers import show_message, prompt_text

    # Confirm Ovi preset is actually available
    try:
        presets = guild.list_presets()
    except Exception:
        presets = []
    available = {p.get("key"): p for p in presets if p.get("key")}
    preset_key = None
    for pref in ("ovi_720p_audio", "ltx2_distilled"):
        if pref in available:
            preset_key = pref
            break
    if not preset_key:
        show_message("Spellcaster",
                     "No text-to-audio-video preset available on the "
                     "Guild. Looked for ovi_720p_audio and "
                     "ltx2_distilled. Install Ovi via the Guild's "
                     "model manager and retry.")
        return 1

    has_audio = "audio" in (available[preset_key].get("task") or "")

    prompt = prompt_text(
        "Generate Audio Track",
        "Describe what should happen (include audio cues — the preset "
        "renders both picture AND audio in sync):\n\n"
        "(e.g. 'a woman laughing warmly in a quiet library, soft turn "
        "of a page' — Ovi will generate matching video + audio)",
        default="",
    )
    if prompt is None:
        return 0
    prompt = (prompt or "").strip()
    if not prompt:
        show_message("Spellcaster",
                     "Ovi needs a prompt (it has no reference to seed from).")
        return 1

    title = (prompt.split(".")[0].split(",")[0][:50]
              or "audio track")
    try:
        shot = guild.create_shot(
            title=title,
            prompt=prompt,
            preset=preset_key,
            notes=f"R107: audio-enabled t2av via {preset_key}.",
        )
    except GuildError as e:
        show_message("Spellcaster", f"Guild rejected the shot:\n{e}")
        return 1

    shot_id = shot.get("id") or shot.get("shot_id") or ""
    if not shot_id:
        show_message("Spellcaster", "Shot created but no id returned.")
        return 1

    try:
        guild.render_shot(shot_id)
    except GuildError as e:
        show_message("Spellcaster",
                     f"Shot queued (id {shot_id[:8]}) but render failed "
                     f"to start:\n{e}")
        return 1

    show_message(
        "Spellcaster",
        f"Audio-track render queued — '{title}' (id {shot_id[:8]}).\n\n"
        f"  • Preset: {preset_key}\n"
        f"  • Audio synchronised: {'yes' if has_audio else 'maybe (check preset task)'}\n"
        f"  • Prompt: {prompt[:100]}{'…' if len(prompt) > 100 else ''}\n\n"
        f"Resulting MP4 auto-imports into the Media Pool with its "
        f"audio track attached. Drop onto A1 under the matching V1 "
        f"clip, or split the audio off via Link > Unlink > drag.",
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
