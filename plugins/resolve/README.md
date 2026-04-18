# Spellcaster × DaVinci Resolve

MVP plugin suite connecting Spellcaster's Wizard Guild video stack to DaVinci Resolve 18+ (free or Studio).

## What you get (MVP)

| Plugin | What it does |
|--------|--------------|
| **Spellcaster Bridge** (always-on) | Subscribes to the Guild's event stream. Every shot rendered on the Guild side auto-imports into Resolve's Media Pool under a `Spellcaster/<date>/` bin with full shot metadata attached as clip metadata. Optional mirror timeline. Dockable status panel. |
| **Generate from Playhead** | Place your playhead on any frame → run the script → type a prompt → a new shot queues on the Guild using that frame as reference. The generated clip auto-appears in your Media Pool when ready. |
| **Smart Fill Gap** | Put the playhead inside a gap between two clips → run the script → type what should happen → the Guild renders a clip of the exact gap duration using the left clip's last frame + the right clip's first frame as references. |

Everything else from the plan (Shotboard Sync, in-Resolve shotboard panel, Marker Round-Trip, Color-Graded Reference, etc.) ships in later tiers.

## Install

### Prerequisites
- DaVinci Resolve 18 or later (Free works, Studio optional)
- Spellcaster 2.2+ with a running Wizard Guild server (default `http://127.0.0.1:7777`)

### Automatic (after Spellcaster installer supports the checkbox)
Check the **"DaVinci Resolve integration"** box during install. The installer detects Resolve's plugin folders and copies files in place.

### Manual (right now)

Copy the files to Resolve's plugin directories.

**Workflow Integration (the always-on Bridge):**

| OS | Destination |
|----|-------------|
| macOS | `~/Library/Application Support/Blackmagic Design/DaVinci Resolve/Workflow Integration Plugins/` |
| Windows | `%APPDATA%\Blackmagic Design\DaVinci Resolve\Support\Workflow Integration Plugins\` |
| Linux | `~/.local/share/DaVinciResolve/Workflow Integration Plugins/` |

Copy the whole `spellcaster_bridge/` folder **and** the `shared/` folder into the Workflow Integration Plugins folder. Result:
```
Workflow Integration Plugins/
├── spellcaster_bridge/
│   ├── __init__.py
│   ├── bridge.py
│   ├── config.py
│   ├── media_pool_sync.py
│   ├── sse_client.py
│   └── ui_panel.py
└── shared/
    ├── spellcaster_api.py
    └── resolve_helpers.py
```

**Scripts (per-action utilities):**

| OS | Destination |
|----|-------------|
| macOS | `~/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts/Utility/Spellcaster/` |
| Windows | `%APPDATA%\Blackmagic Design\DaVinci Resolve\Support\Fusion\Scripts\Utility\Spellcaster\` |
| Linux | `~/.local/share/DaVinciResolve/Fusion/Scripts/Utility/Spellcaster/` |

Copy the contents of `scripts/` into the `Spellcaster/` folder you just created.

Restart Resolve.

## Use

### Bridge (always-on)
Runs in the background as soon as Resolve launches. Open the status panel anytime via **Workspace → Scripts → Utility → Spellcaster → Open Bridge Panel**.

The panel shows: Guild connection state (green=live SSE, yellow=polling fallback, red=offline), queue counts, recent activity, and two toggles (auto-import on/off, mirror-to-Spellcaster-Live-timeline on/off).

### Generate from Playhead
1. Position your playhead on a frame you want to animate (any page — Media, Edit, Color, Fusion).
2. **Workspace → Scripts → Utility → Spellcaster → Generate from Playhead**.
   - Recommended: bind to `Ctrl+Alt+G` via Resolve's Keyboard Customization.
3. A prompt box appears. Type what you want (or leave blank to just animate the frame). Click OK.
4. The shot renders in the background. When ready, it auto-appears in your Media Pool.

### Smart Fill Gap
1. Create or find a gap between two clips on video track 1.
2. Position the playhead inside the gap.
3. **Workspace → Scripts → Utility → Spellcaster → Smart Fill Gap**.
4. Type what should happen (optional). Click OK.
5. Wait for the render. When the clip lands in your Media Pool, drag it onto the gap — it's exactly the right duration.

## Configuration

All settings live in `~/.spellcaster/resolve_bridge.json`:

```json
{
  "guild_url": "http://127.0.0.1:7777",
  "auto_import": true,
  "target_bin": "Spellcaster",
  "bin_date_subfolder": true,
  "live_timeline": false,
  "live_timeline_name": "Spellcaster Live",
  "poll_interval_s": 2.0,
  "max_events_log": 20
}
```

The Bridge panel's checkboxes write directly to this file.

## How the connection works

```
Resolve ── HTTP ───► Guild (tavern/server.py) ───► VideoBridge / Shotboard
   ▲                      │
   │                      ▼
   │                dispatch_workflow() ──► ComfyUI / WanGP
   │                      │
   └── SSE events ────────┘
        /api/video/events
```

Everything runs locally. No cloud. No account. No telemetry.

When the Guild's `/api/video/events` SSE endpoint is unreachable, the Bridge silently falls back to polling `/api/video/shots` every 2 seconds. When SSE comes back, it re-subscribes.

## Troubleshooting

**"Can't reach the Wizard Guild"**
- Start the Guild: run `Wizard Guild.bat` (Windows) or `start_guild.sh` (macOS/Linux)
- Check the Bridge panel — if it says "guild offline" and your Guild is on a non-default port, edit `~/.spellcaster/resolve_bridge.json` and set `guild_url`

**Bridge panel opens but shows "polling fallback" permanently**
- The Guild is reachable but its SSE endpoint is blocked. Not a critical problem — polling works fine, just with slightly more latency. If you want to fix it, restart the Guild.

**"Couldn't grab a still at the playhead"**
- The Grab Still API is flaky on some Resolve builds when the timeline is on the Edit page. Switch to the Color page and retry.
- On the Color page, ensure a still album is selected (`Gallery → User`).

**Generate from Playhead produces weird clips**
- The default preset (`wan22_i2v_lightning`) is fast but noisy. Open the Guild's Video tab after queuing the shot and change the preset to `wan22_i2v_hq` for better quality (slower).

## Roadmap (Tiers 1–3)

See the plan document in the project's `.claude/plans/` folder for the full roadmap. Shipping order:

- **Tier 1**: Shotboard Sync (round-trip timeline ↔ shotboard), in-Resolve Shotboard Panel (full editor).
- **Tier 2**: Color-Graded Reference, Marker Round-Trip (re-render without leaving the timeline).
- **Tier 3**: Prompt from Transcript (Studio only), Smart Proxy Swap, DCTL Palette Lock.

## License
Same as Spellcaster (GPL-2.0).
