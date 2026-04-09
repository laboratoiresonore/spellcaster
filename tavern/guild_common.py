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
DEFAULT_HORDE_URL = "https://aihorde.net/api/v2"
HORDE_ANONYMOUS_KEY = "0000000000"


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
    # (substring, arch_key)  — order = priority, first match wins
    ("klein",     "flux2klein"),
    ("kontext",   "flux_kontext"),
    ("chroma",    "chroma"),        # Chroma v1/v2 — single CLIPLoader type="chroma"
    ("flux",      "flux1dev"),
    ("wan",       "wan"),
    ("ltx",       "ltx"),
    ("seedvr",    "seedvr"),
    ("pixart",    "pixart"),
    ("auraflow",  "auraflow"),
    ("aura_flow", "auraflow"),
    ("hunyuan_dit", "hunyuan_dit"),
    ("hunyuandit",  "hunyuan_dit"),
    ("sd3.5_large_turbo", "sd3_turbo"),
    ("sd3_turbo",   "sd3_turbo"),
    ("sd3.5",       "sd3"),
    ("sd3_",        "sd3"),
    ("sd3medium",   "sd3"),
]

# Checkpoint model-name keywords → arch key   (order = priority)
CKPT_ARCH_RULES = [
    ("playground",  "playground"),
    ("sdxl_turbo",  "sdxl_turbo"),
    ("sdxl_lightning", "sdxl_turbo"),
    ("lcm",         "sdxl_turbo"),
    ("turbo",       "sdxl_turbo"),     # generic turbo → sdxl_turbo (unless caught above)
    ("kolors",      "kolors"),
    ("sd3.5_large_turbo", "sd3_turbo"),
    ("sd3_turbo",   "sd3_turbo"),
    ("sd3.5",       "sd3"),
    ("sd3_",        "sd3"),
    ("sd3medium",   "sd3"),
    ("hunyuan_dit", "hunyuan_dit"),
    ("hunyuandit",  "hunyuan_dit"),
    ("chroma",      "chroma"),         # Chroma v1/v2 — single CLIPLoader type="chroma"
    ("sdxl",        "sdxl"),
    ("xl",          "sdxl"),
    ("illu",        "illustrious"),
    ("pony",        "pony"),
    ("flux",        "flux1dev"),
    # fallthrough → "sd15"
]

# ── Best-model priority (highest first) ──
# Each entry: (match_pool, substring_test, arch_key)
#   match_pool: "unet" or "ckpt"
BEST_MODEL_PRIORITY = [
    ("unet",  lambda ml: "klein" in ml and "9b" in ml,  "flux2klein"),
    ("unet",  lambda ml: "klein" in ml and "4b" in ml,  "flux2klein"),
    ("unet",  lambda ml: "chroma" in ml,                "chroma"),
    ("unet",  lambda ml: "flux" in ml and "dev" in ml,  "flux1dev"),
    ("unet",  lambda ml: "flux" in ml,                  "flux1dev"),
    ("unet",  lambda ml: "sd3.5" in ml and "turbo" not in ml, "sd3"),
    ("unet",  lambda ml: "sd3" in ml,                   "sd3"),
    ("unet",  lambda ml: "pixart" in ml,                "pixart"),
    ("unet",  lambda ml: "auraflow" in ml or "aura_flow" in ml, "auraflow"),
    ("ckpt",  lambda ml: "chroma" in ml,                "chroma"),
    ("ckpt",  lambda ml: "sd3.5" in ml and "turbo" not in ml, "sd3"),
    ("ckpt",  lambda ml: "playground" in ml,            "playground"),
    ("ckpt",  lambda ml: "kolors" in ml,                "kolors"),
    ("ckpt",  lambda ml: "illu" in ml,                  "illustrious"),
    ("ckpt",  lambda ml: "xl" in ml and "turbo" not in ml, "sdxl"),
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
    "flux1dev":     ["Flux-1-Dev\\", "Flux\\"],
    "flux_kontext": ["Flux-1-Dev\\"],
    "ltx":          ["ltxv\\", "LTX\\"],
    "wan":          ["Wan\\", "WAN\\"],
    "seedvr":       ["SeedVR\\", "seedvr\\"],
}

# LoRA name keyword → arch (fallback when prefix matching fails)
LORA_NAME_ARCH_HINTS = [
    ("sdxl",      "sdxl"),
    ("xl",        "sdxl"),
    ("flux",      "flux1dev"),
    ("klein",     "flux2klein"),
    ("illu",      "illustrious"),
    ("pony",      "pony"),
    ("sd3",       "sd3"),
    ("sd35",      "sd3"),
    ("hunyuan",   "hunyuan_dit"),
    ("pixart",    "pixart"),
    ("auraflow",  "auraflow"),
    ("kolors",    "kolors"),
    ("playground", "playground"),
    ("ltx",       "ltx"),
    ("ltxv",      "ltx"),
    ("wan",       "wan"),
    ("seedvr",    "seedvr"),
    ("cogvideo",  "cogvideo"),
    ("svd",       "svd"),
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
