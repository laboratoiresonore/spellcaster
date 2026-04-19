"""Spellcaster Help → quick reference for every script in the menu

Modal showing a categorised index of what each Spellcaster menu
entry does and when to use it. Useful for editors onboarding onto
the plugin — no docs hunt, no context switch.

Menu: Workspace > Scripts > Spellcaster > Spellcaster Help
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


_HELP_TEXT = """\
SPELLCASTER FOR RESOLVE — SCRIPT INDEX

All scripts live in Workspace > Scripts > Spellcaster (visible on
every page: Edit, Fusion, Color, Deliver, Utility).

─── PRODUCE (create new shots / clips) ───────────────────────────

• Capture Timeline
    Walk V1 of the active timeline, send every clip to the Guild as
    a draft shot. Good for "edit locked, now generate per-clip VFX".

• Markers → Shots
    Drop timeline markers with VFX descriptions as notes, run this
    to turn each marker into a shot. Marker colour → shot color
    label; marker duration → shot target duration.

• Generate from Playhead
    Grab the frame at the playhead, run Wan / LTX i2v with a prompt.

• Generate from Prompt
    Pure text-to-video — no clip needed. Picks the best t2v preset
    available.

• Send Clip to Spellcaster
    First frame + prompt → i2v. Quick "do X to this clip's look".

• Send Clip → VFX
    Whole clip → LTX-2.3 FlowEdit v2v. Restyle / transform while
    preserving the source motion.

• Send Clip → Masked VFX
    Clip + mask PNG → Wan 2.2 VACE v2v+mask. Localised edits; mask
    optional (blank = full-frame transform).

• Extend Clip from Last Frame
    Tail-extend a clip — last frame becomes seed for Wan i2v
    continuation.

• Animate Image File
    Point to a PNG/JPG on disk, animate via i2v. For concept art,
    storyboard panels, reference stills.

• Smart Fill Gap
    Playhead inside a gap between two clips → Wan FLF fills with an
    exact-duration inter-shot.

• Generate 3 Variations
    One prompt, one reference, three different seeds. Fastest
    "try again with different luck" iteration.

• Generate Prompt Variations
    One reference, N prompts (one per line), one shot per prompt.
    Compare different creative directions side-by-side.

• Upscale Selected Clip
    Send the V1 clip under the playhead through SeedVR2 for a 2-4x
    temporally-consistent upscale. VRAM-heavy.

─── CONTROL (manage the render queue + timeline) ────────────────

• Render All Drafts
    Queue every draft shot on the Guild.

• Refresh Ready Shots
    Walk ready shots, find their Media Pool clips, append to the
    active timeline in shotboard order.

• Import Guild Timeline
    Pull Guild's current shotboard as an EDL, import as a new
    timeline in Resolve.

• Toggle Render Queue
    Pause / resume the Guild's render queue.

• Retry Failed
    Re-queue every failed shot.

• Cancel All Renders
    Kill everything queued + running, pause the queue.

• Re-prompt Selected Shot
    Edit the prompt of the Spellcaster clip under the playhead
    (needs a [SC] marker), re-render.

─── UTILITY ─────────────────────────────────────────────────────

• Enhance Prompt
    Type a terse prompt → LLM expands to a vivid, cinematographer-
    grade description. Uses the Guild's unified LLM backend.

• Guild Status
    At-a-glance snapshot: shot counts, queue state, backend
    reachability, recent renders.

• Open Guild UI
    Open the Guild web UI in the default browser.

• Open Bridge Panel
    Live-updating status panel with queue control buttons (Render
    all / Pause / Retry / Cancel / Refresh Ready).

• Spellcaster Help
    This message.

─── TYPICAL FLOWS ───────────────────────────────────────────────

Quick VFX on an edit:
  Mark moments → Markers → Shots → edit prompts in Guild → Render
  All Drafts → Refresh Ready Shots / Import Guild Timeline.

Iterate a single shot:
  Send Clip to Spellcaster → 3 Variations → pick best → Re-prompt
  for fine-tuning.

Masked / localised VFX:
  Prepare mask PNG externally → Send Clip → Masked VFX → Render
  All Drafts.

Tail extension:
  Extend Clip from Last Frame → drop the generated MP4 after the
  source on the timeline.

For detailed preset info, bridge config, or troubleshooting, see
plugins/resolve/README.md in the Spellcaster repo.
"""


def main() -> int:
    from resolve_helpers import show_message
    # Enhance-common.guild_or_die NOT required here — help is the
    # one script that should work even with the Guild offline (the
    # editor might be reading it to learn how to get the Guild up).
    show_message("Spellcaster — Script Index", _HELP_TEXT)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception:
        traceback.print_exc()
        sys.exit(1)
