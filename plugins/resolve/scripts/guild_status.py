"""Guild Status → at-a-glance snapshot of what's happening on the Guild

One-shot modal showing shot counts by status, queue state, recent
renders, and the Guild URL. Useful when the Bridge panel isn't
already open on the Fusion page and the editor just wants a quick
"how's the queue?" check from Edit / Color / Deliver.

Menu: Workspace > Scripts > Spellcaster > Guild Status
"""
from __future__ import annotations

import os
import sys
import time
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
    from resolve_helpers import show_message

    # Shot counts
    counts = {"draft": 0, "queued": 0, "running": 0,
               "ready": 0, "failed": 0, "other": 0}
    latest_ready = []
    try:
        shots = guild.list_shots()
    except Exception:
        shots = []
    for s in shots:
        st = (s.get("status") or "").lower()
        if st in counts:
            counts[st] += 1
        else:
            counts["other"] += 1
        if st == "ready":
            latest_ready.append(s)

    # Queue state
    try:
        qs = guild.queue_status()
    except Exception:
        qs = {}

    # Video health
    try:
        health = guild.video_health()
    except Exception:
        health = {}

    # Backends
    wangp_ok = health.get("wangp", {}).get("reachable", False) \
                if isinstance(health.get("wangp"), dict) \
                else bool(health.get("wangp_reachable"))
    comfy_ok = health.get("comfyui", {}).get("reachable", False) \
                if isinstance(health.get("comfyui"), dict) \
                else bool(health.get("comfyui_reachable"))

    paused = bool(qs.get("paused", False))
    running_now = int(qs.get("running", counts["running"]) or 0)
    queued_now = int(qs.get("queued", counts["queued"]) or 0)

    # Sort ready shots by recency using last_updated; keep top 5
    latest_ready.sort(key=lambda s: s.get("last_updated", 0), reverse=True)
    latest_ready = latest_ready[:5]

    lines = [
        f"Guild @ {guild.base_url}",
        "",
        f"Queue: {'⏸ paused' if paused else '▶ running'}   "
        f"({running_now} running, {queued_now} queued)",
        "",
        "Shots:",
        f"  draft   {counts['draft']:>3}     ready   {counts['ready']:>3}",
        f"  queued  {counts['queued']:>3}     failed  {counts['failed']:>3}",
        f"  running {counts['running']:>3}     other   {counts['other']:>3}",
        "",
        f"Backends: "
        f"WanGP {'✓' if wangp_ok else '✗'}   "
        f"ComfyUI {'✓' if comfy_ok else '✗'}",
    ]
    if latest_ready:
        lines.append("")
        lines.append("Recent renders:")
        now = time.time()
        for s in latest_ready:
            title = (s.get("title") or s.get("id", "?"))[:40]
            age_s = now - float(s.get("last_updated") or 0)
            if age_s < 60:
                age = f"{int(age_s)}s ago"
            elif age_s < 3600:
                age = f"{int(age_s / 60)}m ago"
            else:
                age = f"{int(age_s / 3600)}h ago"
            lines.append(f"  • {title}  ({age})")

    show_message("Spellcaster — Guild Status", "\n".join(lines))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception:
        traceback.print_exc()
        sys.exit(1)
