"""Re-prompt Selected Shot → change prompt, re-render

Picks the Spellcaster-generated clip under the playhead (identified
by its [SC] marker — the round-trip metadata the Bridge attached on
auto-import), asks for a new prompt with the current one prefilled,
POSTs the update to the Guild, and triggers a re-render.

Use when a shot almost works but needs a prompt tweak — faster than
opening the web UI to edit.

Menu: Workspace > Scripts > Spellcaster > Re-prompt Selected Shot
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
                              "Utility", "Spellcaster")
        elif sys.platform == "darwin":
            d = os.path.expanduser(
                "~/Library/Application Support/Blackmagic Design/DaVinci Resolve"
                "/Fusion/Scripts/Utility/Spellcaster")
        else:
            d = os.path.expanduser(
                "~/.local/share/DaVinciResolve/Fusion/Scripts/Utility/Spellcaster")
    if d and d not in sys.path:
        sys.path.insert(0, d)
_boot()

import _spellcaster_common as _sc  # noqa: E402


def _find_clip_under_playhead():
    from resolve_helpers import (
        get_current_project, get_current_timeline, _parse_timecode,
    )
    timeline = get_current_timeline()
    project = get_current_project()
    if not (timeline and project):
        return None
    try:
        fps = float(project.GetSetting("timelineFrameRate") or 24.0)
        tc = timeline.GetCurrentTimecode()
    except Exception:
        return None
    if not tc:
        return None
    hh, mm, ss, ff = _parse_timecode(tc)
    playhead = int(round(((hh * 3600 + mm * 60 + ss) * fps) + ff))
    try:
        items = timeline.GetItemListInTrack("video", 1) or []
    except Exception:
        return None
    for it in items:
        try:
            if int(it.GetStart()) <= playhead < int(it.GetEnd()):
                return it
        except Exception:
            continue
    return None


def main() -> int:
    guild = _sc.guild_or_die()
    from spellcaster_api import GuildError
    from resolve_helpers import (
        get_current_timeline, read_spellcaster_marker,
        show_message, prompt_text,
    )

    if not get_current_timeline():
        show_message("Spellcaster", "No timeline is active.")
        return 1

    item = _find_clip_under_playhead()
    if not item:
        show_message("Spellcaster",
                     "Position the playhead over a clip on V1 first.")
        return 1

    # Must be a Spellcaster-generated clip with the [SC] marker
    meta = read_spellcaster_marker(item)
    if not meta or not meta.get("shot_id"):
        show_message("Spellcaster",
                     "This clip isn't tagged as Spellcaster-generated "
                     "(no [SC] marker). Use Send Clip → VFX on real "
                     "footage, or Capture Timeline to re-link existing "
                     "Spellcaster output to shots on the Guild.")
        return 1

    shot_id = meta.get("shot_id") or ""

    # Fetch current prompt from Guild (marker note has a snapshot, but
    # the Guild is the source of truth — prompt may have been edited
    # in the UI since the render)
    try:
        shot = guild.get_shot(shot_id)
    except GuildError as e:
        show_message("Spellcaster", f"Guild lookup failed:\n{e}")
        return 1
    if not shot:
        show_message("Spellcaster",
                     f"Shot {shot_id[:8]} not found on the Guild "
                     "(it may have been deleted). The marker references "
                     "an orphaned id.")
        return 1

    current = shot.get("prompt", "")
    title = shot.get("title", "")[:60]

    new_prompt = prompt_text(
        "Re-prompt Shot",
        f"Edit the prompt for '{title}':\n"
        f"(current prompt is prefilled — change and click OK)",
        default=current,
    )
    if new_prompt is None:
        return 0
    new_prompt = (new_prompt or "").strip()
    if not new_prompt:
        show_message("Spellcaster", "Empty prompt — nothing to update.")
        return 0
    if new_prompt == current:
        show_message("Spellcaster",
                     "Prompt unchanged. Nothing to do.\n"
                     "(To re-render with the same prompt but a new "
                     "seed, use Generate 3 Variations.)")
        return 0

    # Update + re-queue
    try:
        guild.update_shot(shot_id, prompt=new_prompt, status="queued")
    except GuildError as e:
        show_message("Spellcaster", f"Update failed:\n{e}")
        return 1
    try:
        guild.render_all_drafts()  # sweep picks up the just-queued shot
    except Exception:
        pass

    show_message(
        "Spellcaster",
        f"Re-queued '{title}' (id {shot_id[:8]}).\n\n"
        f"Old prompt: {current[:80]}{'…' if len(current) > 80 else ''}\n\n"
        f"New prompt: {new_prompt[:80]}{'…' if len(new_prompt) > 80 else ''}\n\n"
        f"The new render replaces the current Media Pool clip once it "
        f"finishes.",
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
