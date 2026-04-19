"""Generate from Prompt → text-to-video (no clip needed)

Pure generative shot. Editor types a description, the Guild renders
a fresh clip from scratch via the best available t2v preset (no
reference image, no source clip). The rendered MP4 auto-imports into
the Media Pool via the Bridge.

Use when the shot doesn't exist in footage yet — establishing shots,
concept visualisation, previs, or generative B-roll.

Menu: Workspace > Scripts > Spellcaster > Generate from Prompt
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


def _pick_t2v_preset(guild) -> tuple[str, str]:
    """Pick the best t2v preset available on the Guild.

    Preference order matches the "fast but good" sweet spot:
      1. ltx2_text_to_video_distilled (ComfyUI, ~8 steps, 24fps)
      2. wan22_t2v                    (WanGP, 20 steps, 16fps)
      3. ltx2_distilled               (WanGP, 8 steps, has audio)
      4. ltx2_dev                     (WanGP, HQ)
      5. First t2v preset that exists

    Returns (key, label) so the confirmation dialog tells the editor
    which preset actually fired.
    """
    try:
        presets = guild.list_presets()
    except Exception:
        return ("wan22_t2v", "Wan 2.2 Text-to-Video")
    available = {p.get("key"): p for p in presets if p.get("key")}
    for preferred in ("ltx2_text_to_video_distilled", "wan22_t2v",
                      "ltx2_distilled", "ltx2_dev",
                      "ltx2_text_to_video"):
        if preferred in available:
            return (preferred, available[preferred].get("label", preferred))
    for p in presets:
        if (p.get("task") or "").lower().startswith("t2v"):
            return (p.get("key"), p.get("label", p.get("key")))
    return ("wan22_t2v", "Wan 2.2 Text-to-Video")


def main() -> int:
    guild = _sc.guild_or_die()
    from spellcaster_api import GuildError
    from resolve_helpers import show_message, prompt_text

    prompt = prompt_text(
        "Text-to-Video",
        "Describe the shot you want to generate:\n\n"
        "(e.g. 'wide establishing shot of a foggy alpine lake at dawn, "
        "slow camera push-in, golden rim light on the pines')",
        default="",
    )
    if prompt is None:
        return 0
    prompt = (prompt or "").strip()
    if not prompt:
        show_message("Spellcaster",
                     "Need a prompt. t2v has no reference to fall back on.")
        return 1

    preset_key, preset_label = _pick_t2v_preset(guild)

    title = (prompt.split(".")[0].split(",")[0][:50]
              or "t2v shot")
    try:
        shot = guild.create_shot(
            title=title,
            prompt=prompt,
            preset=preset_key,
            notes=f"R95: t2v via {preset_key}.",
        )
    except GuildError as e:
        show_message("Spellcaster", f"Guild rejected the shot:\n{e}")
        return 1

    shot_id = shot.get("id") or shot.get("shot_id") or ""
    if not shot_id:
        show_message("Spellcaster", "Shot created but no id returned.")
        return 1

    # Trigger render immediately — t2v is typically fast and editors
    # usually want to see the result, not queue a batch.
    try:
        guild.render_shot(shot_id)
    except GuildError as e:
        show_message("Spellcaster",
                     f"Shot queued (id {shot_id[:8]}) but render failed "
                     f"to start:\n{e}")
        return 1

    show_message(
        "Spellcaster",
        f"t2v render queued — '{title}' (id {shot_id[:8]}).\n\n"
        f"  • Preset: {preset_label}\n"
        f"  • Prompt: {prompt[:120]}{'…' if len(prompt) > 120 else ''}\n\n"
        f"The clip auto-imports into the Media Pool when ready. "
        f"Open the Guild UI to tweak seed / duration / preset before "
        f"re-rendering variations.",
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
