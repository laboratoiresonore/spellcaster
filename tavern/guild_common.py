"""
guild_common.py — Shared constants and helpers for The Wizard Guild.

All model/architecture detection is imported from the canonical
spellcaster_core.model_detect (ONE SOURCE OF TRUTH).
Guild-specific helpers (network tests, default ports) live here.
"""

import os
import sys
import socket
import urllib.request

# ═══════════════════════════════════════════════════════════════════════
#  Path setup: Find canonical spellcaster_core
# ═══════════════════════════════════════════════════════════════════════

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_THIS_DIR)

# Try multiple locations for spellcaster_core
for _candidate in [
    os.path.join(_REPO_ROOT, "comfyui-spellcaster"),          # dev checkout
    os.path.join(_REPO_ROOT, "plugins", "gimp", "comfyui-connector"),  # bundled in GIMP plugin
    _THIS_DIR,  # might be alongside server.py in packaged build
]:
    if os.path.isdir(os.path.join(_candidate, "spellcaster_core")):
        if _candidate not in sys.path:
            sys.path.insert(0, _candidate)
        break


# ═══════════════════════════════════════════════════════════════════════
#  Default URLs & Ports
# ═══════════════════════════════════════════════════════════════════════

DEFAULT_GUILD_PORT = 7777
DEFAULT_COMFYUI_URL = "http://127.0.0.1:8188"
DEFAULT_KOBOLD_URL = "http://127.0.0.1:5001"
DEFAULT_HORDE_URL = "https://aihorde.net/api/v2"
HORDE_ANONYMOUS_KEY = "0000000000"


# ═══════════════════════════════════════════════════════════════════════
#  Architecture / Model Detection (from canonical spellcaster_core)
# ═══════════════════════════════════════════════════════════════════════

from spellcaster_core.model_detect import (
    UNET_ARCH_RULES,
    CKPT_ARCH_RULES,
    BEST_MODEL_PRIORITY,
    FAMILY_MODEL_KEYWORDS,
    LORA_ARCH_PREFIXES,
    LORA_NAME_ARCH_HINTS,
    classify_unet_model,
    classify_ckpt_model,
)


# ═══════════════════════════════════════════════════════════════════════
#  Shared Helpers (Guild-specific)
# ═══════════════════════════════════════════════════════════════════════

def is_port_in_use(port: int) -> bool:
    """Check if a TCP port is already bound on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        return s.connect_ex(('127.0.0.1', port)) == 0


def test_endpoint(url, path="", timeout=3):
    """Quick HTTP connectivity check.  Returns True if reachable (200)."""
    try:
        req = urllib.request.Request(
            f"{url.rstrip('/')}/{path.lstrip('/')}",
            headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False
