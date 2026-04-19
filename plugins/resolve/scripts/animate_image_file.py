"""Animate Image File → i2v from any PNG / JPG on disk

Editor types a path to a local image file (concept art, reference
still, sketch, storyboard panel, whatever). Script uploads the image
as a shot reference and runs Wan / LTX i2v against it. The animated
clip lands in the Media Pool via the Bridge auto-import.

Bridges the gap between "have a still idea on disk" and "have a
moving clip on the timeline" without needing to load the image into
Resolve's Media Pool first.

Menu: Workspace > Scripts > Spellcaster > Animate Image File
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

    img_path = prompt_text(
        "Animate Image File",
        "Path to an image file on this machine (PNG/JPG):\n"
        "(concept art, reference still, sketch — anything Wan can "
        "use as an i2v seed)",
        default="",
    )
    if img_path is None:
        return 0
    img_path = (img_path or "").strip().strip('"').strip("'")
    if not img_path:
        return 0
    if not os.path.isfile(img_path):
        show_message("Spellcaster",
                     f"File not found:\n{img_path}\n\n"
                     f"Make sure the path is accessible from the "
                     f"Resolve host.")
        return 1

    prompt = prompt_text(
        "Animate Image File",
        f"Describe the motion / camera move for '{os.path.basename(img_path)}':\n"
        f"(e.g. 'slow push-in, soft camera drift' or leave blank for "
        f"subtle idle motion)",
        default="",
    )
    if prompt is None:
        return 0

    # Read image bytes
    try:
        with open(img_path, "rb") as f:
            img_bytes = f.read()
    except Exception as e:
        show_message("Spellcaster", f"Couldn't read image:\n{e}")
        return 1

    # Pick best i2v preset available
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

    title_source = prompt.strip() or os.path.splitext(
        os.path.basename(img_path))[0]
    title = (title_source.split(".")[0].split(",")[0][:50]
              or "animated")

    try:
        shot = guild.create_shot(
            title=title,
            prompt=prompt or "subtle idle motion, gentle camera drift",
            preset=preset_key,
            reference_png=img_bytes,
            notes=f"R102: animated from '{os.path.basename(img_path)}'",
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

    size_mb = len(img_bytes) / 1048576.0
    show_message(
        "Spellcaster",
        f"Animation queued — '{title}' (id {shot_id[:8]}).\n\n"
        f"  • Source image: {os.path.basename(img_path)} ({size_mb:.2f} MB)\n"
        f"  • Preset: {preset_key}\n"
        f"  • Prompt: {(prompt or 'idle motion')[:80]}\n\n"
        f"The clip auto-imports into the Media Pool when ready.",
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
