"""Generate from Playhead — grab the current frame and create a Spellcaster shot.

The kill feature. Editor places the playhead on any clip, runs this
script (via menu or keyboard shortcut), types a one-line prompt, and
a new shot is queued on the Guild using that frame as reference.

Assign a keyboard shortcut in Resolve via DaVinci Resolve >
Preferences > User > Keyboard Customization — look up "Generate from
Playhead" under the Fusion/Edit context and bind it to Ctrl+Alt+G.
"""

from __future__ import annotations

import os
import sys
import traceback


def _locate_shared():
    """Add shared/ to sys.path so we can import spellcaster_api + resolve_helpers."""
    here = os.path.dirname(os.path.abspath(__file__))
    shared = os.path.normpath(os.path.join(here, "..", "shared"))
    if os.path.isdir(shared) and shared not in sys.path:
        sys.path.insert(0, shared)
        return True
    # Installed location fallback (scripts dir ships alongside shared)
    installed_shared = os.path.normpath(os.path.join(here, "..", "..", "shared"))
    if os.path.isdir(installed_shared) and installed_shared not in sys.path:
        sys.path.insert(0, installed_shared)
        return True
    return False


def main():
    _locate_shared()
    try:
        from spellcaster_api import GuildClient, discover_guild_url
        from resolve_helpers import (
            get_current_timeline, capture_frame_at_playhead,
            show_message, prompt_text,
        )
    except ImportError as e:
        print(f"[Generate from Playhead] Plugin not fully installed: {e}")
        return 1

    timeline = get_current_timeline()
    if not timeline:
        show_message("Spellcaster", "No timeline is active.\n\nOpen a timeline first.")
        return 1

    # 1. Grab frame
    png_path = capture_frame_at_playhead()
    if not png_path or not os.path.exists(png_path):
        show_message("Spellcaster",
                     "Couldn't grab a still at the playhead.\n\n"
                     "Tip: the Color page's 'Grab Still' works best. "
                     "Try switching to the Color page and re-running.")
        return 1

    # 2. Ask for a prompt
    prompt = prompt_text(
        "Generate with Spellcaster",
        "Describe what you want (leave blank to just animate this frame):",
        default="",
    )
    if prompt is None:
        # Cancelled
        try:
            os.unlink(png_path)
        except Exception:
            pass
        return 0

    # 3. POST the frame + prompt to Guild
    guild = GuildClient(discover_guild_url())
    if not guild.is_reachable():
        show_message("Spellcaster",
                     "Can't reach the Wizard Guild.\n\n"
                     "Start the Guild (Wizard Guild.bat / .sh) and try again.")
        return 1

    try:
        with open(png_path, "rb") as f:
            png_bytes = f.read()
    except Exception as e:
        show_message("Spellcaster", f"Couldn't read the captured still:\n{e}")
        return 1

    # Pick a sensible default preset — the Guild's 'wan22_i2v_lightning' is
    # fastest for ref-image + short prompt. Fall back to any preset that
    # accepts image input.
    preset = _pick_preset_for_i2v(guild)

    title = _title_from_prompt(prompt) or "playhead shot"
    try:
        shot = guild.create_shot(
            title=title,
            prompt=prompt or "subtle gentle motion",
            preset=preset,
            reference_png=png_bytes,
            notes="From Resolve playhead",
        )
    except Exception as e:
        show_message("Spellcaster", f"Guild rejected the shot:\n{e}")
        return 1

    shot_id = shot.get("id") or shot.get("shot_id")
    if not shot_id:
        show_message("Spellcaster", "Shot created but Guild didn't return an ID.")
        return 1

    # 4. Kick off the render
    try:
        guild.render_shot(shot_id)
    except Exception as e:
        show_message("Spellcaster", f"Shot queued but render failed to start:\n{e}")
        return 1

    show_message(
        "Spellcaster",
        f"✨ Shot queued — '{title}'\n\n"
        f"Rendering in the background. The Bridge panel will tell you when "
        f"it's ready, and the clip will auto-appear in the Spellcaster bin "
        f"in your Media Pool.",
    )

    # Cleanup temp still
    try:
        os.unlink(png_path)
    except Exception:
        pass

    return 0


def _pick_preset_for_i2v(guild):
    """Pick the best image-to-video preset on the Guild.

    Current catalog (audited April 2026):
      wan22_i2v_lightning (fast draft), wan22_i2v_hq (quality),
      wan22_t2v, ltx2_distilled, ltx2_dev, wan_move_i2v,
      scail_preview, ovi_720p_audio

    Priority: lightning > hq > ltx2_distilled (all pure i2v from a
    single ref frame). Then any task='i2v'. Fall back to lightning.
    """
    try:
        presets = guild.list_presets()
    except Exception:
        return "wan22_i2v_lightning"
    available = {p.get("key"): p for p in presets if p.get("key")}
    for preferred in ("wan22_i2v_lightning", "wan22_i2v_hq",
                      "ltx2_distilled", "ltx2_dev"):
        if preferred in available:
            return preferred
    for p in presets:
        if (p.get("task") or "").lower() == "i2v":
            return p.get("key")
    return "wan22_i2v_lightning"


def _title_from_prompt(prompt: str) -> str:
    if not prompt:
        return ""
    t = prompt.strip().split(".")[0].split(",")[0]
    return t[:50]


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(1)
