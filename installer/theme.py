"""Spellcaster installer/updater theme tokens.

Single source of truth for colours, fonts, and tk dialog helpers across:

* installer/installer_gui.py  — customtkinter wizard (source)
* installer/bootstrap.py      — Tk crash dialog
* installer/manual_update.py  — console banner (ANSI equivalents here)

The palette mirrors the Wizard Guild CSS tokens so every Spellcaster
surface — browser app, GIMP plugin, Darktable splash, antenna tray —
feels like the same product.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# ── Palette ──────────────────────────────────────────────────────────
# Mirrors :root in tavern/static/style.css so the installer looks like
# the same product as the Wizard Guild. Swap hex values here and
# every Spellcaster surface that reads from theme.py follows.
BG              = "#12101d"  # Guild --bg-main (deep violet)
BG_SIDEBAR      = "#1a1730"  # Guild --bg-panel (indigo panel)
BG_CARD         = "#161228"  # Between bg + panel (card inner)
BG_ELEVATED     = "#281D45"  # Guild --user-bubble (elevated / hover)

# GOLD is now the primary interactive accent — matches the Guild's
# gold focus rings + active pill highlights. The previous magenta
# #D122E3 clashed with the Guild's identity.
ACCENT          = "#ffd700"  # Guild --accent (gold)
ACCENT_HOVER    = "#ffea00"  # Guild --accent-hover
ACCENT_SECONDARY = "#B246F2"  # Guild --primary-purple (frames, chips)
ACCENT_GOLD     = "#ffd700"  # alias for back-compat; matches ACCENT

OK              = "#00E676"  # success / running
WARN            = "#FFB300"  # amber / starting
ERROR           = "#FF5252"  # red / failure
INFO            = "#6BB6FF"  # info / hint

TEXT            = "#FFFFFF"
TEXT_MUTED      = "#c4b8e3"  # Guild --text-muted (soft lavender)
TEXT_SUBTLE     = "#8a7eaf"  # hairline / runic muted
BORDER          = "#3A2863"  # card borders (kept — still fits)

# Tray state ring colours — slightly desaturated so the 64px icon
# stays legible on light + dark taskbars.
TRAY_OK         = (80, 200, 120, 255)
TRAY_WARN       = (240, 170, 70, 255)
TRAY_ERROR      = (220, 60, 60, 255)
TRAY_STOPPED    = (160, 160, 160, 255)
TRAY_ACCENT     = (255, 215, 0, 255)  # ACCENT as RGBA — pairing state (gold)

# ── Typography ────────────────────────────────────────────────────────
# Segoe UI on Windows, Inter elsewhere if installed, fallbacks Tk always
# knows. Passed as a single string so `font="family 11 bold"` works too.
FONT_FAMILY     = "Segoe UI"
FONT_FAMILY_FALLBACK = "Inter Cantarell Arial"
FONT_MONO       = "Consolas"

def font(size: int = 10, *, bold: bool = False, mono: bool = False) -> tuple:
    """Return a tk `font` tuple using the project font family."""
    family = FONT_MONO if mono else FONT_FAMILY
    return (family, size, "bold" if bold else "normal")

# ── ANSI equivalents for console banners (manual_update.py) ──────────
# Kept here so any CLI surface uses the same identity.
# ANSI_ACCENT is bright yellow now that the GUI accent is gold (was
# bright magenta when the GUI accent was #D122E3). Keeps CLI and GUI
# banners colour-coordinated.
ANSI_ACCENT = "\033[93m"   # bright yellow (gold-ish)
ANSI_PURPLE = "\033[95m"   # bright magenta — secondary arcane accent
ANSI_OK     = "\033[92m"
ANSI_WARN   = "\033[93m"
ANSI_ERR    = "\033[91m"
ANSI_DIM    = "\033[90m"
ANSI_RESET  = "\033[0m"


# ── Asset discovery ──────────────────────────────────────────────────
# PyInstaller bundles our branded images under `_MEIPASS`; in dev we
# read from the repo `assets/` dir directly. Always returns `None` on
# miss — callers must tolerate headless / asset-less fallbacks.

_ASSET_NAMES = {
    "hero":       ["spellcaster_hero.png", "readme_banner.png"],
    "banner":     ["readme_banner.png", "spellcaster_hero.png"],
    "installer_bg": ["installer_background.png"],
    "antenna":    ["antenna_logo.png", "30_antenna_logo.png"],
    "wizard_ico": ["wizard_guild.ico"],
    "spinner":    ["wizard_banner.gif", "spinner.gif"],

    # Generated installer artwork (tools/generate_installer_assets.py).
    # All live under assets/installer/ — _candidate_roots() walks both
    # assets/ AND assets/installer/ so plain filenames resolve.
    "installer_hero":       ["installer/hero_welcome.png"],
    "installer_completion": ["installer/completion_celebration.png"],
    "installer_companion":  ["installer/sidebar_companion.png"],
    "installer_error":      ["installer/error_sigil.png"],
}


def installer_asset(kind: str, key: str) -> Path | None:
    """Resolve a generated installer asset by category and key.

    Examples:
      installer_asset("feature", "generation")        → assets/installer/feature_generation.png
      installer_asset("arch", "klein")                → assets/installer/arch_klein.png
      installer_asset("bg", "welcome")                → assets/installer/bg_welcome.png
      installer_asset("usecase", "img2img")           → assets/installer/usecase_img2img.png
      installer_asset("loading", "pulse_03")          → assets/installer/loading_pulse_03.png

    Singletons in the catalog use a key that already includes the category
    (hero_welcome, completion_celebration, sidebar_companion, error_sigil),
    so we avoid doubling the prefix when the caller passes them through:
      installer_asset("hero", "hero_welcome")         → assets/installer/hero_welcome.png
      installer_asset("completion", "completion_celebration")
                                                      → assets/installer/completion_celebration.png
    """
    # Try in order: key-as-stem, then kind_key, then key alone — robust to
    # both catalog naming conventions (sidebar_companion.png vs
    # companion_sidebar.png).
    for fname in (
        f"installer/{key}.png" if key.startswith(f"{kind}_") else None,
        f"installer/{kind}_{key}.png",
        f"installer/{key}.png",
    ):
        if not fname:
            continue
        p = asset(fname)
        if p:
            return p
    return None


def installer_loading_frames(seq: str = "pulse") -> list[Path]:
    """Return all 8 loading frames for a sequence in order. Empty if missing.

    seq: 'pulse' or 'spin' (matching tools/generate_installer_assets.py).
    """
    frames: list[Path] = []
    for i in range(8):
        p = installer_asset("loading", f"{seq}_{i:02d}")
        if p:
            frames.append(p)
    return frames


def _candidate_roots() -> list[Path]:
    roots: list[Path] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        roots.extend([
            Path(meipass),
            Path(meipass) / "assets",
            Path(meipass) / "installer",
        ])
    here = Path(__file__).resolve().parent
    roots.extend([
        here,
        here.parent / "assets",
        here.parent / "tavern" / "static" / "assets",
        here.parent / "tavern" / "static" / "icons",
        here.parent / "antenna" / "assets",
    ])
    return roots


def asset(name: str) -> Path | None:
    """Return a Path to a named asset, or None if missing.

    Use short semantic names (``hero``, ``antenna``, ``wizard_ico``)
    — the resolver walks a list of candidates per kind so the same
    call works across dev / frozen / patched layouts.
    """
    candidates = _ASSET_NAMES.get(name, [name])
    for root in _candidate_roots():
        for fname in candidates:
            p = root / fname
            try:
                if p.is_file():
                    return p
            except OSError:
                continue
    return None


# ── Tk dialog helpers ────────────────────────────────────────────────

def apply_tk_theme(root) -> None:
    """Paint a plain tkinter root in the Spellcaster palette.

    Safe to call multiple times; idempotent. Only touches bg/fg so
    individual widgets can still override.
    """
    try:
        root.configure(bg=BG)
    except Exception:  # noqa: BLE001
        pass
    try:
        root.option_add("*Background", BG)
        root.option_add("*Foreground", TEXT)
        root.option_add("*Font", f"{FONT_FAMILY} 10")
        root.option_add("*Label.Background", BG)
        root.option_add("*Label.Foreground", TEXT)
        root.option_add("*Button.Background", BG_ELEVATED)
        root.option_add("*Button.Foreground", TEXT)
        root.option_add("*Button.ActiveBackground", ACCENT)
        root.option_add("*Button.ActiveForeground", TEXT)
        root.option_add("*Entry.Background", BG_CARD)
        root.option_add("*Entry.Foreground", TEXT)
        root.option_add("*Entry.InsertBackground", ACCENT)
        root.option_add("*Text.Background", BG_CARD)
        root.option_add("*Text.Foreground", TEXT)
    except Exception:  # noqa: BLE001
        pass


def try_set_window_icon(root) -> None:
    """Set the taskbar / title-bar icon to the wizard .ico when available.

    Silent on failure. Windows is the primary target — .ico is honoured
    by Tk on Linux/macOS too but ignored by some window managers.
    """
    ico = asset("wizard_ico")
    if not ico:
        return
    try:
        root.iconbitmap(default=str(ico))
    except Exception:  # noqa: BLE001
        try:
            from PIL import Image, ImageTk  # type: ignore
            img = ImageTk.PhotoImage(Image.open(str(ico)))
            root._icon_ref = img  # keep a ref
            root.wm_iconphoto(True, img)
        except Exception:
            pass


def styled_button(master, text: str, command, *, primary: bool = False, width: int = 12):
    """Return a palette-consistent Tk button for plain tkinter dialogs."""
    import tkinter as tk
    return tk.Button(
        master, text=text, command=command, width=width,
        relief="flat", bd=0, padx=16, pady=8,
        bg=ACCENT if primary else BG_ELEVATED,
        fg=TEXT,
        activebackground=ACCENT_HOVER if primary else BG_CARD,
        activeforeground=TEXT,
        font=(FONT_FAMILY, 10, "bold" if primary else "normal"),
        cursor="hand2",
        highlightthickness=0,
    )
