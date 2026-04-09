"""
guild_common.py — Shared constants, helpers, and architecture profiles
for The Wizard Guild.  Imported by both server.py and guild_launcher.py
to eliminate duplicated definitions.
"""

import socket
import urllib.request


# ═══════════════════════════════════════════════════════════════════════
#  Default URLs & Ports
# ═══════════════════════════════════════════════════════════════════════

DEFAULT_GUILD_PORT = 7777
DEFAULT_COMFYUI_URL = "http://127.0.0.1:8188"
DEFAULT_KOBOLD_URL = "http://127.0.0.1:5001"


# ═══════════════════════════════════════════════════════════════════════
#  Architecture / Model-Name → Arch-Key Mapping
# ═══════════════════════════════════════════════════════════════════════
#
# Single source of truth for "what substring in a model name implies
# which architecture key".  Referenced by:
#   - _fetch_comfyui_models()   (detect all models)
#   - _detect_best_model()      (pick best model for avatar gen)
#   - _build_lora_registry()    (infer LoRA architecture)
#   - _FAMILY_MODEL_KEYWORDS    (wizard gating)
#
# Order within each list matters for priority: first match wins.

# UNET model-name keywords → arch key
UNET_ARCH_RULES = [
    # (substring, arch_key)
    ("klein",   "flux2klein"),
    ("flux",    "flux1dev"),
    ("wan",     "wan"),
    ("ltx",     "ltx"),
    ("seedvr",  "seedvr"),
]

# Checkpoint model-name keywords → arch key   (order = priority)
CKPT_ARCH_RULES = [
    ("sdxl",    "sdxl"),
    ("xl",      "sdxl"),
    ("illu",    "illustrious"),
    ("pony",    "pony"),
    ("flux",    "flux1dev"),
    # fallthrough → "sd15"
]

# ── Best-model priority (highest first) ──
# Each entry: (match_pool, substring_test, arch_key)
#   match_pool: "unet" or "ckpt"
BEST_MODEL_PRIORITY = [
    ("unet",  lambda ml: "klein" in ml and "9b" in ml,  "flux2klein"),
    ("unet",  lambda ml: "klein" in ml and "4b" in ml,  "flux2klein"),
    ("unet",  lambda ml: "flux" in ml and "dev" in ml,  "flux1dev"),
    ("unet",  lambda ml: "flux" in ml,                  "flux1dev"),
    ("ckpt",  lambda ml: "xl" in ml,                    "sdxl"),
]

# ── Model-family → keyword map for wizard-gating ──
# If at least one installed model name contains any of these substrings,
# the corresponding model_wizard family is shown.
FAMILY_MODEL_KEYWORDS = {
    "ltx2":        ["ltx"],
    "seedvr2":     ["seedvr"],
    "wan":         ["wan"],
    "video_tools": ["wan", "ltx", "seedvr", "svd", "animate", "rife",
                    "video_upscale", "reactor"],
}

# ── LoRA prefix → arch mapping ──
# Maps architecture keys to the subfolder prefixes used in ComfyUI's
# LoRA directory layout.  Cross-platform: callers check both / and \.
LORA_ARCH_PREFIXES = {
    "sd15":         [],
    "sdxl":         ["SDXL\\", "Illustrious\\", "Illustrious-Pony\\", "Pony\\"],
    "illustrious":  ["Illustrious\\", "Illustrious-Pony\\"],
    "pony":         ["Pony\\", "Illustrious-Pony\\"],
    "flux2klein":   ["Flux-2-Klein\\"],
    "flux1dev":     ["Flux-1-Dev\\"],
    "flux_kontext": ["Flux-1-Dev\\"],
}

# LoRA name keyword → arch (fallback when prefix matching fails)
LORA_NAME_ARCH_HINTS = [
    ("sdxl",  "sdxl"),
    ("xl",    "sdxl"),
    ("flux",  "flux1dev"),
    ("klein", "flux2klein"),
    ("illu",  "illustrious"),
    ("pony",  "pony"),
]


# ═══════════════════════════════════════════════════════════════════════
#  Shared Helpers
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


def classify_unet_model(name):
    """Return arch key for a UNET model name, or 'unknown'."""
    ml = name.lower()
    for substring, arch_key in UNET_ARCH_RULES:
        if substring in ml:
            return arch_key
    return "unknown"


def classify_ckpt_model(name):
    """Return arch key for a checkpoint model name, or 'sd15' (default)."""
    ml = name.lower()
    for substring, arch_key in CKPT_ARCH_RULES:
        if substring in ml:
            return arch_key
    return "sd15"
