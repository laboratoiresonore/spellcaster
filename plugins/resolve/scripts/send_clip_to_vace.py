"""Send Clip → Masked VFX (Wan 2.2 VACE)

Localised v2v: restyle or replace content in a masked region of real
footage while keeping the rest of the frame untouched. Use for object
re-texture, selective lighting effects, or partial scene replacements.

Workflow:
  1. Position the playhead over a clip on V1.
  2. Run this script.
  3. Type the target transformation (what should appear in the masked
     region).
  4. Optional: type the path to a mask PNG (alpha or luminance-based).
     Leave blank for a full-frame transform.
  5. Script stages both files on the antenna host, creates a draft
     shot with preset=wan22_v2v_vace_mask, and reports success.
  6. Render All Drafts (or Open Guild UI → tweak strength/steps, then
     render).

Menu: Workspace > Scripts > Spellcaster > Send Clip → Masked VFX
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
        return (None, None)
    try:
        fps = float(project.GetSetting("timelineFrameRate") or 24.0)
        tc = timeline.GetCurrentTimecode()
    except Exception:
        return (None, None)
    if not tc:
        return (None, None)
    hh, mm, ss, ff = _parse_timecode(tc)
    playhead = int(round(((hh * 3600 + mm * 60 + ss) * fps) + ff))
    try:
        items = timeline.GetItemListInTrack("video", 1) or []
    except Exception:
        return (None, None)
    for it in items:
        try:
            if int(it.GetStart()) <= playhead < int(it.GetEnd()):
                mp_item = it.GetMediaPoolItem()
                if not mp_item:
                    return (it, None)
                props = mp_item.GetClipProperty() or {}
                return (it, props.get("File Path", "") or "")
        except Exception:
            continue
    return (None, None)


def main() -> int:
    guild = _sc.guild_or_die()
    from spellcaster_api import GuildError
    from resolve_helpers import (
        get_current_timeline, show_message, prompt_text,
    )

    timeline = get_current_timeline()
    if not timeline:
        show_message("Spellcaster",
                     "No timeline is active. Open one first.")
        return 1

    item, media_path = _find_clip_under_playhead()
    if not item:
        show_message("Spellcaster",
                     "Position the playhead over a clip on V1 first.")
        return 1
    if not media_path or not os.path.isfile(media_path):
        show_message("Spellcaster",
                     "Couldn't resolve the clip's source file.\n"
                     f"Reported path: {media_path!r}")
        return 1

    try:
        clip_name = item.GetName() or os.path.basename(media_path)
    except Exception:
        clip_name = os.path.basename(media_path)

    prompt = prompt_text(
        "Masked VFX — Target Description",
        f"What should appear in the masked region of '{clip_name}'?\n"
        f"(e.g. 'replace the sky with a sunset nebula')",
        default="",
    )
    if prompt is None:
        return 0
    if not prompt.strip():
        show_message("Spellcaster", "Need a target description. Try again.")
        return 1

    mask_path = prompt_text(
        "Masked VFX — Mask PNG (optional)",
        "Path to a mask PNG on the Resolve host.\n"
        "Alpha channel or luminance defines the edit region.\n"
        "Leave blank for a full-frame transform.",
        default="",
    )
    mask_path = (mask_path or "").strip()
    if mask_path and not os.path.isfile(mask_path):
        show_message("Spellcaster",
                     f"Mask file not found: {mask_path}\n"
                     "Proceeding without a mask.")
        mask_path = ""

    # Create the shot
    title = (prompt.strip().split(".")[0].split(",")[0][:50]
              or clip_name[:50]
              or "VACE VFX")
    try:
        shot = guild.create_shot(
            title=title,
            prompt=prompt,
            preset="wan22_v2v_vace_mask",
            backend="comfyui",
            notes=(f"R91: Masked VFX on '{clip_name}'. "
                    f"Mask: {'yes' if mask_path else 'full-frame'}."),
        )
    except GuildError as e:
        show_message("Spellcaster", f"Guild rejected shot creation:\n{e}")
        return 1

    shot_id = shot.get("id") or shot.get("shot_id") or ""
    if not shot_id:
        show_message("Spellcaster", "Shot created but no id returned.")
        return 1

    # Stage input video
    try:
        video_staged = guild._post_json(
            f"/api/video/shots/{shot_id}/input-video",
            {"path": media_path},
            timeout=120.0,
        )
    except GuildError as e:
        show_message("Spellcaster",
                     f"Shot created (id {shot_id[:8]}) but couldn't stage "
                     f"the video:\n{e}")
        return 1

    # Stage optional mask
    mask_staged = {}
    if mask_path:
        try:
            mask_staged = guild._post_json(
                f"/api/video/shots/{shot_id}/mask-image",
                {"path": mask_path},
                timeout=30.0,
            )
        except GuildError as e:
            show_message("Spellcaster",
                         f"Video staged OK, but mask upload failed:\n{e}\n\n"
                         f"Shot will render full-frame (no mask).")

    # Report
    v_name = video_staged.get("staged_name", "")
    v_mb = (video_staged.get("size_bytes", 0) or 0) / 1048576.0
    lines = [
        f"VACE v2v shot queued — '{title}' (id {shot_id[:8]}).",
        "",
        f"  • Source: {os.path.basename(media_path)} ({v_mb:.1f} MB)",
        f"  • Staged video: {v_name}",
    ]
    if mask_staged.get("staged_name"):
        m_name = mask_staged["staged_name"]
        m_kb = (mask_staged.get("size_bytes", 0) or 0) / 1024.0
        lines.append(f"  • Staged mask: {m_name} ({m_kb:.0f} KB)")
    else:
        lines.append("  • No mask — will transform full frame.")
    lines.append("")
    lines.append("Run 'Render All Drafts' to start. Adjust strength in "
                  "the Guild UI (0.5 = loose, 1.0 = tight).")
    show_message("Spellcaster", "\n".join(lines))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception:
        traceback.print_exc()
        sys.exit(1)
