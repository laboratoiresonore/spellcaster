"""Generate Prompt Variations → N prompts, same reference frame

Fan out creative exploration along the PROMPT axis (R98 varies seeds
for the same prompt; this varies prompts for the same reference).
Editor types a newline-separated list of prompts, script creates one
draft shot per prompt using the first frame of the V1 clip under the
playhead as a shared reference.

Editor example input (one prompt per line):
    moody film noir lighting
    warm golden-hour color grade
    high-key summer cinematography
    cyberpunk teal-and-magenta

Script creates 4 shots, all from the same reference frame, and kicks
off the renders. Compare the MP4s as they land.

Menu: Workspace > Scripts > Spellcaster > Generate Prompt Variations
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


def _prompt_multiline(title: str, label: str) -> str | None:
    """Multiline text input via Fusion UI. Falls back to prompt_text
    (single-line) if UIDispatcher is unavailable — editor can still
    paste a ~200-char newline-joined string there."""
    from resolve_helpers import get_fusion, prompt_text
    fu = get_fusion()
    try:
        if not fu:
            raise RuntimeError("no fusion")
        ui = fu.UIManager
        disp_factory = getattr(fu, "UIDispatcher", None)
        if ui is None or disp_factory is None:
            raise RuntimeError("no dispatcher")
        disp = disp_factory(ui)
        result: dict = {"value": None}
        win = disp.AddWindow({"WindowTitle": title,
                              "Geometry": [800, 400, 520, 360]}, [
            ui.VGroup([
                ui.Label({"Text": label, "WordWrap": True}),
                ui.TextEdit({"ID": "input", "PlaceholderText":
                              "One prompt per line…"}),
                ui.HGroup([
                    ui.Button({"ID": "cancel", "Text": "Cancel"}),
                    ui.Button({"ID": "ok", "Text": "Generate"}),
                ]),
            ]),
        ])

        def _ok(ev):
            result["value"] = win.Find("input").PlainText
            disp.ExitLoop()

        def _cancel(ev):
            disp.ExitLoop()

        win.On.ok.Clicked = _ok
        win.On.cancel.Clicked = _cancel
        win.On.Window.Close = _cancel
        win.Show()
        disp.RunLoop()
        win.Hide()
        return result["value"]
    except Exception:
        # Single-line fallback — editor can paste \n-separated string
        return prompt_text(title, label, default="")


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
        get_current_timeline, capture_frame_at_playhead,
        show_message,
    )

    if not get_current_timeline():
        show_message("Spellcaster", "No timeline is active. Open one first.")
        return 1

    item = _find_clip_under_playhead()
    if not item:
        show_message("Spellcaster",
                     "Position the playhead over a clip on V1 first.")
        return 1

    try:
        clip_name = item.GetName() or "clip"
    except Exception:
        clip_name = "clip"

    raw = _prompt_multiline(
        "Prompt Variations",
        f"Type one prompt per line. Each becomes a shot using the "
        f"first frame of '{clip_name}' as reference.\n"
        f"(e.g. 4-6 alternate descriptions)",
    )
    if raw is None:
        return 0
    raw = (raw or "").strip()
    if not raw:
        show_message("Spellcaster", "No prompts provided.")
        return 0

    prompts = [p.strip() for p in raw.splitlines() if p.strip()]
    if not prompts:
        show_message("Spellcaster", "No non-empty prompt lines found.")
        return 0
    if len(prompts) > 12:
        prompts = prompts[:12]  # cap at 12 variations per run

    # Grab shared reference frame
    png_path = capture_frame_at_playhead()
    if not png_path or not os.path.exists(png_path):
        show_message("Spellcaster",
                     "Couldn't grab the reference frame. "
                     "Switch to the Color page and retry.")
        return 1
    try:
        with open(png_path, "rb") as f:
            png_bytes = f.read()
    except Exception as e:
        show_message("Spellcaster", f"Couldn't read the still:\n{e}")
        return 1

    # Pick an i2v preset
    try:
        presets = guild.list_presets()
    except Exception:
        presets = []
    available = {p.get("key"): p for p in presets if p.get("key")}
    preset_key = "wan22_i2v_lightning"
    for preferred in ("wan22_i2v_lightning", "wan22_i2v_hq",
                      "ltx2_image_to_video"):
        if preferred in available:
            preset_key = preferred
            break

    created: list[tuple[str, str]] = []
    failures: list[str] = []
    for idx, prompt in enumerate(prompts, start=1):
        title = (f"v{idx}: " + (prompt.split(".")[0].split(",")[0][:40]
                                 or clip_name[:40]))
        try:
            shot = guild.create_shot(
                title=title,
                prompt=prompt,
                preset=preset_key,
                reference_png=png_bytes,
                notes=f"R100: prompt variation {idx}/{len(prompts)} "
                       f"from '{clip_name}'",
            )
            shot_id = shot.get("id") or shot.get("shot_id") or ""
            if shot_id:
                created.append((shot_id, prompt))
        except GuildError as e:
            failures.append(f"v{idx}: {e}")

    # Kick all queued renders in parallel
    for shot_id, _ in created:
        try:
            guild.render_shot(shot_id)
        except Exception:
            pass

    try:
        os.unlink(png_path)
    except Exception:
        pass

    lines = [
        f"Queued {len(created)}/{len(prompts)} prompt variations.",
        f"Reference: first frame of '{clip_name}'.",
        f"Preset: {preset_key}.",
        "",
    ]
    for idx, (sid, prompt) in enumerate(created, start=1):
        snippet = prompt[:56] + ("…" if len(prompt) > 56 else "")
        lines.append(f"  v{idx} ({sid[:8]}): {snippet}")
    for f in failures:
        lines.append(f"  ✗ {f}")
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
