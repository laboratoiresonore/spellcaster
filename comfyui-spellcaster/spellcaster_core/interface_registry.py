"""Interface Registry — which frontends are installed + online right now.

Central truth table the UI reads before deciding what chips, menus,
buttons, or "Send to X" options to render. The rule is simple:

    If an interface hasn't heartbeat'd the Guild recently (or never
    registered itself at install time), NOTHING about it appears in
    the UI. No dead buttons, no greyed-out menus, no placeholder
    chips. The feature just doesn't exist until the interface is
    actually there.

Three states per interface:

    installed → component folder / plugin files present on disk
    enabled   → user opted in during install (config flag set)
    online    → heartbeat within the last `online_ttl_s` seconds

An interface must be **installed AND enabled AND online** for its
features to appear in the UI. Any of the three being false means the
UI renders as if the interface doesn't exist.

The registry is in-process and fed by three sources:
    1. Static detection at Guild start (filesystem + config probe)
    2. Runtime heartbeats via POST /api/interfaces/heartbeat
    3. Automatic bus events (publish `<iface>.presence.online`)

Usage:

    from spellcaster_core.interface_registry import registry

    # At Guild startup (one-shot probe):
    registry.detect_all()

    # When a plugin pings in:
    registry.heartbeat("resolve")

    # Before rendering UI:
    if registry.is_active("resolve"):
        render_resolve_chip()

    # For chip generators:
    for iface in registry.active_interfaces():
        yield build_send_to_chip(iface)
"""

from __future__ import annotations

import os
import shutil
import threading
import time
from dataclasses import dataclass, field
from typing import Optional


# ── Interface definitions ────────────────────────────────────────────


@dataclass
class InterfaceSpec:
    """Static description of a frontend interface.

    `detector_paths` — if any of these exist, the interface is
    considered installed. Keep the list liberal so we catch all
    platform layouts; the first match wins.

    `ui_label` / `icon` — how this interface should be referred to
    in any UI chips or menus.

    `config_flag` — key in guild_config.json that must be True for
    the interface to be enabled. `None` means always-enabled if
    installed.
    """
    key: str
    ui_label: str
    icon: str = "🔌"
    detector_paths: list[str] = field(default_factory=list)
    config_flag: Optional[str] = None
    capabilities: list[str] = field(default_factory=list)  # e.g., ["receive_image", "timeline"]


# The canonical list of frontends Spellcaster supports.
# Paths use $HOME / $APPDATA substitutions that _expand_path resolves.
KNOWN_INTERFACES: dict[str, InterfaceSpec] = {
    "guild": InterfaceSpec(
        key="guild",
        ui_label="Wizard Guild",
        icon="💬",
        detector_paths=[],  # Always installed if the server is running
        capabilities=["chat", "send_image", "receive_image", "event_bus"],
    ),
    "gimp": InterfaceSpec(
        key="gimp",
        ui_label="GIMP",
        icon="🖼️",
        detector_paths=[
            "$APPDATA/GIMP/3.2/plug-ins/comfyui-connector/comfyui-connector.py",
            "$HOME/.config/GIMP/3.2/plug-ins/comfyui-connector/comfyui-connector.py",
            "$HOME/Library/Application Support/GIMP/3.2/plug-ins/comfyui-connector/comfyui-connector.py",
        ],
        capabilities=["send_image", "receive_image", "pixel_edit"],
    ),
    "darktable": InterfaceSpec(
        key="darktable",
        ui_label="Darktable",
        icon="📷",
        detector_paths=[
            "$HOME/.config/darktable/lua/comfyui_connector.lua",
            "$APPDATA/darktable/lua/comfyui_connector.lua",
            "$HOME/Library/Application Support/darktable/lua/comfyui_connector.lua",
        ],
        capabilities=["send_image", "raw_edit"],
    ),
    "resolve": InterfaceSpec(
        key="resolve",
        ui_label="DaVinci Resolve",
        icon="🎬",
        detector_paths=[
            "$APPDATA/Blackmagic Design/DaVinci Resolve/Support/Workflow Integration Plugins/spellcaster_bridge",
            "$HOME/Library/Application Support/Blackmagic Design/DaVinci Resolve/Workflow Integration Plugins/spellcaster_bridge",
            "$HOME/.local/share/DaVinciResolve/Workflow Integration Plugins/spellcaster_bridge",
        ],
        capabilities=["receive_image", "receive_video", "timeline", "playhead_capture", "gap_fill"],
    ),
    "sillytavern": InterfaceSpec(
        key="sillytavern",
        ui_label="SillyTavern",
        icon="🎭",
        # SillyTavern's presence is detected via reachable sillytavern_url
        # (its own /api/settings endpoint) rather than a filesystem path.
        config_flag="sillytavern_enabled",
        capabilities=["chat", "send_image", "roleplay"],
    ),
    "signal": InterfaceSpec(
        key="signal",
        ui_label="Signal Bridge",
        icon="📱",
        config_flag="signal_enabled",
        capabilities=["notify", "receive_text", "send_text"],
    ),
}


# ── Registry ─────────────────────────────────────────────────────────


@dataclass
class InterfaceState:
    installed: bool = False
    enabled: bool = True
    last_heartbeat: float = 0.0
    last_meta: dict = field(default_factory=dict)  # free-form data from the interface

    def is_online(self, ttl_s: float) -> bool:
        return (time.time() - self.last_heartbeat) < ttl_s


class InterfaceRegistry:
    """Process-wide registry. Read-mostly, small locks."""

    def __init__(self, online_ttl_s: float = 30.0):
        self._lock = threading.Lock()
        self._state: dict[str, InterfaceState] = {
            key: InterfaceState() for key in KNOWN_INTERFACES
        }
        self._config: dict = {}
        self.online_ttl_s = online_ttl_s

    # ── Detection ────────────────────────────────────────────────────

    def detect_all(self, config: dict | None = None):
        """Run a one-shot filesystem + config probe for every interface.

        Call this at Guild start and whenever settings change (e.g.,
        after the user toggles a component checkbox in the installer).
        """
        self._config = dict(config or {})
        with self._lock:
            for key, spec in KNOWN_INTERFACES.items():
                st = self._state[key]
                if spec.key == "guild":
                    # Guild is always installed+enabled+online when this
                    # registry runs (it's hosted by the Guild itself).
                    st.installed = True
                    st.enabled = True
                    st.last_heartbeat = time.time()
                    continue
                st.installed = self._probe_installed(spec)
                if spec.config_flag:
                    st.enabled = bool(self._config.get(spec.config_flag, False))
                else:
                    st.enabled = True

    def _probe_installed(self, spec: InterfaceSpec) -> bool:
        if not spec.detector_paths:
            # Rely purely on config flag for interfaces without files
            return True
        for raw in spec.detector_paths:
            p = _expand_path(raw)
            if p and (os.path.exists(p) or _executable_on_path(p)):
                return True
        return False

    # ── Heartbeat (from plugins) ─────────────────────────────────────

    def heartbeat(self, key: str, meta: dict | None = None) -> bool:
        """Record that an interface is alive *now*. Plugins call this
        every ~10 seconds while they're loaded."""
        if key not in KNOWN_INTERFACES:
            return False
        with self._lock:
            st = self._state[key]
            st.last_heartbeat = time.time()
            if meta:
                st.last_meta = dict(meta)
            # A heartbeat is proof-of-installation, even if the filesystem
            # probe missed the install location.
            st.installed = True
        return True

    def mark_enabled(self, key: str, enabled: bool) -> bool:
        if key not in KNOWN_INTERFACES:
            return False
        with self._lock:
            self._state[key].enabled = enabled
        return True

    # ── Query ────────────────────────────────────────────────────────

    def is_active(self, key: str) -> bool:
        """Installed AND enabled AND online. Use this as the single
        gate in every UI renderer. If False, render nothing."""
        with self._lock:
            if key not in self._state:
                return False
            st = self._state[key]
            return st.installed and st.enabled and st.is_online(self.online_ttl_s)

    def active_interfaces(self) -> list[str]:
        """List of keys that pass the `is_active` gate."""
        return [k for k in KNOWN_INTERFACES if self.is_active(k)]

    def snapshot(self) -> dict:
        """Serializable state for the /api/interfaces endpoint.

        Returns:
            {
              "guild": {"installed": True, "enabled": True, "online": True,
                        "ui_label": "Wizard Guild", "icon": "💬",
                        "capabilities": [...]},
              "gimp":  {"installed": True, "enabled": True, "online": False, ...},
              ...
            }
        """
        now = time.time()
        out = {}
        with self._lock:
            for key, spec in KNOWN_INTERFACES.items():
                st = self._state[key]
                out[key] = {
                    "ui_label": spec.ui_label,
                    "icon": spec.icon,
                    "capabilities": list(spec.capabilities),
                    "installed": st.installed,
                    "enabled": st.enabled,
                    "online": (now - st.last_heartbeat) < self.online_ttl_s,
                    "last_heartbeat": st.last_heartbeat,
                    "last_meta": dict(st.last_meta),
                }
        return out


# ── Helpers ──────────────────────────────────────────────────────────


def _expand_path(path: str) -> str:
    """Expand $HOME / $APPDATA / ~ on any OS."""
    if not path:
        return ""
    path = os.path.expandvars(path)
    path = os.path.expanduser(path)
    return path


def _executable_on_path(name: str) -> bool:
    """True if `name` (basename) is resolvable via $PATH."""
    if not name or os.sep in name or "/" in name:
        return False
    return shutil.which(name) is not None


# ── Module-level singleton ──────────────────────────────────────────


registry = InterfaceRegistry()
