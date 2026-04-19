"""Capture Timeline — push the current Resolve timeline into the Shotboard.

R83. Reverse direction of the existing generate_from_playhead flow:
instead of "make a shot here", this walks every clip on the current
timeline and hands them to the Guild as a batch. Clips that already
carry a Spellcaster [SC] marker are matched to their existing shot
(no duplicate create); clips without get a fresh draft shot titled
after the Resolve clip name.

Typical use: an editor has been assembling rushes in Resolve, wants
Spellcaster to generate fill / transitions / re-renders. Run this once
and the whole timeline materialises as shots on the board.

Menu: Workspace > Scripts > Spellcaster > Capture Timeline
Shortcut: bindable via DaVinci Resolve > Preferences > Keyboard Customization.
"""

from __future__ import annotations

import os
import sys
import base64
import traceback


def _script_dir():
    """Best-effort lookup of the directory this script lives in.

    DaVinci Resolve's Workspace > Scripts menu exec()'s scripts in a
    context where ``__file__`` is NOT defined (NameError). We probe a
    few fallbacks before giving up:
      1. ``__file__`` when it works (dev runs, REPL).
      2. Standard Resolve Scripts location for each OS.
    """
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


def _locate_shared():
    """Add the shared/ dir to sys.path.

    Tries, in order, the installed layout (shared/ next to the script
    file), then the dev layout (shared/ at plugins/resolve/shared/
    relative to plugins/resolve/scripts/), then the legacy fallback.
    """
    here = _script_dir()
    if not here:
        return False
    for cand in (
        os.path.join(here, "shared"),                    # installed layout
        os.path.normpath(os.path.join(here, "..", "shared")),        # dev layout
        os.path.normpath(os.path.join(here, "..", "..", "shared")),  # legacy
    ):
        if os.path.isdir(cand) and cand not in sys.path:
            sys.path.insert(0, cand)
            return True
    return False


def _confirm(title: str, message: str) -> bool:
    """Tiny confirm dialog using the Fusion UI.

    Returns True on OK, False on cancel. When the UI API isn't
    available (common when the script runs from the Utility menu
    outside the Fusion page — fu.UIDispatcher comes back as None
    rather than raising), the summary is printed to the Console and
    the script proceeds as if the editor confirmed. Rationale: they
    already clicked the menu entry; a silent abort would be worse
    than a silent proceed.
    """
    from resolve_helpers import get_fusion
    try:
        fu = get_fusion()
        if not fu:
            print(f"[{title}] {message}\n  (proceeding — no Fusion UI)")
            return True
        ui = fu.UIManager
        disp_factory = getattr(fu, "UIDispatcher", None)
        if ui is None or disp_factory is None:
            print(f"[{title}] {message}\n"
                   f"  (proceeding — UIManager/UIDispatcher unavailable "
                   f"outside the Fusion page)")
            return True
        disp = disp_factory(ui)
        result = {"ok": False}
        win = disp.AddWindow({"WindowTitle": title,
                              "Geometry": [800, 500, 500, 200]}, [
            ui.VGroup([
                ui.Label({"Text": message, "WordWrap": True,
                           "Alignment": {"AlignHCenter": True}}),
                ui.HGap(0, 1.0),
                ui.HGroup([
                    ui.Button({"ID": "cancel", "Text": "Cancel"}),
                    ui.Button({"ID": "ok", "Text": "Capture"}),
                ]),
            ]),
        ])

        def _ok(ev):
            result["ok"] = True
            disp.ExitLoop()

        def _cancel(ev):
            disp.ExitLoop()

        win.On.ok.Clicked = _ok
        win.On.cancel.Clicked = _cancel
        win.On.Window.Close = _cancel
        win.Show()
        disp.RunLoop()
        win.Hide()
        return result["ok"]
    except Exception as e:  # noqa: BLE001
        print(f"[{title}] {message}\n  (confirm dialog failed: {e}; proceeding)")
        return True


def main() -> int:
    _locate_shared()
    try:
        from spellcaster_api import GuildClient, discover_guild_url, GuildError
        from resolve_helpers import (
            get_current_project, get_current_timeline,
            walk_timeline_clips, grab_first_frame_of_clip,
            show_message,
        )
    except ImportError as e:
        print(f"[Capture Timeline] Plugin not fully installed: {e}")
        return 1

    project = get_current_project()
    timeline = get_current_timeline()
    if not (project and timeline):
        show_message("Spellcaster",
                     "No timeline is active.\n\n"
                     "Open a project and switch to the Edit page first.")
        return 1

    try:
        timeline_name = timeline.GetName() or "Untitled timeline"
    except Exception:
        timeline_name = "Untitled timeline"
    try:
        fps = float(project.GetSetting("timelineFrameRate") or 24.0)
    except Exception:
        fps = 24.0

    clips = walk_timeline_clips(timeline=timeline, tracks="V1")
    if not clips:
        show_message("Spellcaster",
                     "V1 is empty. Capture Timeline only walks the first "
                     "video track — drag some clips onto V1 and try again.")
        return 1

    # Confirm with the editor — pulling N clips into Spellcaster is not
    # destructive but it's still worth a modal.
    already_tied = sum(1 for c in clips if c.get("spellcaster_shot_id"))
    fresh = len(clips) - already_tied
    msg = (f"Timeline: {timeline_name}\n"
            f"Found {len(clips)} clip(s) on V1.\n\n"
            f"  • {already_tied} already tied to Spellcaster (will re-group)\n"
            f"  • {fresh} new (will be drafted as shots)\n\n"
            f"Proceed?")
    if not _confirm("Capture Timeline → Spellcaster", msg):
        return 0

    # Grab a first-frame PNG for each new clip — slow-ish (one still per
    # clip) but makes the resulting shot usable as an i2v seed. Cap at 30
    # references per run so a 300-clip timeline doesn't hang Resolve for
    # ten minutes; the rest get ingested without reference images and
    # the editor can attach them manually later.
    _REF_LIMIT = 30
    refs_captured = 0
    for clip in clips:
        if clip.get("spellcaster_shot_id"):
            # Already a Spellcaster shot — don't burn stills on it.
            continue
        if refs_captured >= _REF_LIMIT:
            break
        try:
            png_path = grab_first_frame_of_clip(_lookup_item(timeline, clip))
            if png_path and os.path.isfile(png_path):
                with open(png_path, "rb") as f:
                    clip["reference_b64"] = base64.b64encode(
                        f.read()).decode("ascii")
                refs_captured += 1
                try:
                    os.unlink(png_path)
                except Exception:
                    pass
        except Exception:
            # Per-clip failures aren't fatal — we just import without a ref.
            continue

    # Send to the Guild
    guild = GuildClient(discover_guild_url())
    if not guild.is_reachable():
        show_message("Spellcaster",
                     "Can't reach the Wizard Guild.\n\n"
                     "Start the Guild (Wizard Guild.bat / .sh) and try again.")
        return 1

    try:
        result = guild.import_timeline(
            timeline_name=timeline_name, fps=fps, clips=clips)
    except GuildError as e:
        show_message("Spellcaster", f"Guild rejected the import:\n{e}")
        return 1

    created = int(result.get("created") or 0)
    matched = int(result.get("matched") or 0)
    failed = int(result.get("failed") or 0)
    scene_id = result.get("scene_id") or ""

    show_message(
        "Spellcaster",
        f"✨ Timeline captured — '{timeline_name}'\n\n"
        f"  • {created} new shot(s) drafted\n"
        f"  • {matched} existing shot(s) re-grouped\n"
        f"  • {failed} failed\n"
        f"  • references grabbed: {refs_captured}\n\n"
        f"They're bundled under the scene 'Resolve: {timeline_name}' "
        f"in the Guild.",
    )
    return 0


def _lookup_item(timeline, clip_dict):
    """Find the TimelineItem that matches a walk_timeline_clips dict.

    walk_timeline_clips returned dicts — not TimelineItem references —
    so we re-resolve the item here to grab its first-frame still. We
    match on start_frame + track which uniquely identifies a clip on V1.
    """
    track = int(clip_dict.get("track") or 1)
    start = int(clip_dict.get("start_frame") or 0)
    try:
        items = timeline.GetItemListInTrack("video", track) or []
    except Exception:
        return None
    for it in items:
        try:
            if int(it.GetStart()) == start:
                return it
        except Exception:
            continue
    return None


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(1)
