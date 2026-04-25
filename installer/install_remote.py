#!/usr/bin/env python3
"""
Spellcaster Remote Installer
=============================
Autonomous installer for users with ComfyUI running on a separate machine
in their local network.  Installs **everything except ComfyUI itself**:
  - Probes the remote ComfyUI server to detect installed components
  - Installs GIMP plugin, Darktable plugin, and Wizard Guild locally
  - Writes spellcaster_settings.json with the remote server URL
  - Creates desktop shortcuts pointing at the remote ComfyUI
  - Completely headless — no interactive prompts (unless --interactive)

Usage:
    python install_remote.py http://<SERVER-IP>:8188
    python install_remote.py http://<SERVER-IP>:8188 --dry-run
    python install_remote.py http://<SERVER-IP>:8188 --llm-url http://<SERVER-IP>:5001
    python install_remote.py --scan                     # Auto-discover via network scan
    python install_remote.py --interactive               # Fall back to guided prompts
    python install_remote.py --help

https://github.com/laboratoiresonore/spellcaster
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import textwrap
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

# Canonical helpers live in install.py — we re-export the ones we need below
# (after SCRIPT_DIR is set up so install.py's module-level resolution agrees).
import install  # noqa: E402

# ─── Constants ────────────────────────────────────────────────────────────────

if getattr(sys, 'frozen', False):
    SCRIPT_DIR = Path(sys._MEIPASS)
else:
    SCRIPT_DIR = Path(__file__).resolve().parent
MANIFEST_PATH = SCRIPT_DIR / "manifest.json"
VERSION = "1.0"
_BOX_LINE = "═" * 50

# ─── SFW / NSFW detection ────────────────────────────────────────────────────
# Known NSFW LoRA name patterns (case-insensitive substring match).
# If ANY of these appear in the server's LoRA list, the server is NSFW.
NSFW_LORA_PATTERNS = [
    "nicegirls",      # NiceGirls UltraReal — Flux2 Klein NSFW unlock
    "aidmansfw",      # aidmaNSFWunlock — Flux Dev
    "nsfw_unlock",    # Generic NSFW unlock LoRAs
]
# Known NSFW model name patterns (unet / checkpoint names)
NSFW_MODEL_PATTERNS = [
    "nsfw",
    "phr00t",         # phr00t NSFW merge models (e.g. ltx2-phr00tmerge-nsfw)
    "uncensored",
]
# GitHub repos per edition
SFW_REPO  = "laboratoiresonore/spellcaster"
NSFW_REPO = "laboratoiresonore/spellcaster_NSFW"

# ANSI colors
if sys.stdout and sys.stdout.isatty() and (os.name != "nt" or os.environ.get("WT_SESSION")):
    C_BOLD   = "\033[1m"
    C_GREEN  = "\033[92m"
    C_YELLOW = "\033[93m"
    C_RED    = "\033[91m"
    C_CYAN   = "\033[96m"
    C_DIM    = "\033[2m"
    C_RESET  = "\033[0m"
else:
    C_BOLD = C_GREEN = C_YELLOW = C_RED = C_CYAN = C_DIM = C_RESET = ""


# ─── Utility functions ────────────────────────────────────────────────────────

def banner():
    print(f"""
{C_BOLD}{C_CYAN}╔══════════════════════════════════════════════════╗
║   ✦  SPELLCASTER REMOTE INSTALLER  v{VERSION}  ✦   ║
║                                                  ║
║  For users with ComfyUI on another machine       ║
║  Installs plugins + shortcuts, zero interaction  ║
╚══════════════════════════════════════════════════╝{C_RESET}
""")


def log_ok(msg: str):
    print(f"  {C_GREEN}✓{C_RESET} {msg}")


def log_warn(msg: str):
    print(f"  {C_YELLOW}⚠{C_RESET} {msg}")


def log_err(msg: str):
    print(f"  {C_RED}✗{C_RESET} {msg}")


def log_info(msg: str):
    print(f"  {C_CYAN}→{C_RESET} {msg}")


def log_dim(msg: str):
    print(f"  {C_DIM}{msg}{C_RESET}")


def section(title: str):
    print(f"\n{C_BOLD}{_BOX_LINE}{C_RESET}")
    print(f"{C_BOLD}  {title}{C_RESET}")
    print(f"{C_BOLD}{_BOX_LINE}{C_RESET}\n")


# ─── Manifest ─────────────────────────────────────────────────────────────────

def load_manifest() -> dict:
    if not MANIFEST_PATH.exists():
        log_err(f"manifest.json not found at {MANIFEST_PATH}")
        sys.exit(1)
    with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


# ─── Network discovery ───────────────────────────────────────────────────────

def scan_network_for_comfyui(port: int = 8188, timeout: float = 0.5) -> list[str]:
    """Scan the local /24 subnet for ComfyUI servers.

    Determines the local IP, then probes every address in the same /24 range
    for a ComfyUI /system_stats endpoint on the given port.
    """
    section("Network Scan")
    log_info("Scanning local network for ComfyUI servers...")

    # Get local IP
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
    except Exception:
        log_warn("Could not determine local IP — trying 192.168.1.0/24")
        local_ip = "192.168.1.1"

    prefix = ".".join(local_ip.split(".")[:3])
    log_dim(f"Local IP: {local_ip}  —  Scanning {prefix}.1-254:{port}")

    found: list[str] = []
    for i in range(1, 255):
        ip = f"{prefix}.{i}"
        if ip == local_ip:
            continue
        url = f"http://{ip}:{port}"
        try:
            req = urllib.request.Request(f"{url}/system_stats")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if "system" in data or "devices" in data:
                    vram = data.get("devices", [{}])[0].get("vram_total", 0)
                    vram_gb = vram / (1024**3) if vram else 0
                    label = f"  GPU VRAM: {vram_gb:.1f} GB" if vram_gb > 0 else ""
                    log_ok(f"Found ComfyUI at {C_CYAN}{url}{C_RESET}{label}")
                    found.append(url)
        except Exception:
            pass
        # Progress indicator every 50 hosts
        if i % 50 == 0:
            print(f"  {C_DIM}  ...scanned {i}/254{C_RESET}", end="\r")

    print("                                          ", end="\r")  # clear line
    if not found:
        log_warn("No ComfyUI servers found on the local network.")
    else:
        log_ok(f"Found {len(found)} ComfyUI server(s)")
    return found


def probe_server(server_url: str) -> dict:
    """Probe a ComfyUI server — mirrors install.py step_probe_server()."""
    section("Probing Remote ComfyUI")

    result: dict[str, Any] = {
        "available_nodes": set(),
        "checkpoints": [],
        "unet_models": [],
        "loras": [],
        "vaes": [],
        "clip_models": [],
        "controlnets": [],
        "reachable": False,
        "vram_total": 0,
        "gpu_name": "",
    }

    log_info(f"Connecting to {C_CYAN}{server_url}{C_RESET}...")

    # Test connectivity via /system_stats
    try:
        req = urllib.request.Request(f"{server_url}/system_stats")
        with urllib.request.urlopen(req, timeout=10) as resp:
            stats = json.loads(resp.read().decode("utf-8"))
            device = stats.get("devices", [{}])[0]
            vram_total = device.get("vram_total", 0)
            gpu_name = device.get("name", "Unknown GPU")
            vram_gb = vram_total / (1024**3) if vram_total else 0
            result["vram_total"] = vram_total
            result["gpu_name"] = gpu_name
            log_ok(f"Server reachable")
            if vram_gb > 0:
                log_info(f"Remote GPU: {gpu_name} — {vram_gb:.1f} GB VRAM")
        result["reachable"] = True
    except Exception as e:
        log_err(f"Cannot reach ComfyUI at {server_url}: {e}")
        return result

    # Fetch installed nodes
    try:
        req = urllib.request.Request(f"{server_url}/object_info")
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            result["available_nodes"] = set(data.keys())
            log_ok(f"Installed nodes: {len(result['available_nodes'])}")
    except Exception as e:
        log_warn(f"Could not fetch node info: {e}")

    # Fetch model lists
    MODEL_QUERIES = {
        "checkpoints": ("CheckpointLoaderSimple", "ckpt_name"),
        "loras":       ("LoraLoader", "lora_name"),
        "vaes":        ("VAELoader", "vae_name"),
        "controlnets": ("ControlNetLoader", "control_net_name"),
    }
    for key, (node_type, param_name) in MODEL_QUERIES.items():
        try:
            req = urllib.request.Request(f"{server_url}/object_info/{node_type}")
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                items = (data.get(node_type, {})
                         .get("input", {}).get("required", {})
                         .get(param_name, [None])[0])
                if isinstance(items, list):
                    result[key] = items
                    log_ok(f"{key}: {len(items)}")
        except Exception:
            pass

    # Fetch UNET/diffusion models
    for node_type in ["UNETLoader", "UnetLoaderGGUF"]:
        if node_type in result["available_nodes"]:
            try:
                req = urllib.request.Request(f"{server_url}/object_info/{node_type}")
                with urllib.request.urlopen(req, timeout=10) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    items = (data.get(node_type, {})
                             .get("input", {}).get("required", {})
                             .get("unet_name", [None])[0])
                    if isinstance(items, list):
                        result["unet_models"] = items
                        log_ok(f"unet_models: {len(items)}")
            except Exception:
                pass
            break

    # Fetch CLIP models
    for node_type in ["CLIPLoader", "DualCLIPLoader"]:
        if node_type in result["available_nodes"]:
            try:
                req = urllib.request.Request(f"{server_url}/object_info/{node_type}")
                with urllib.request.urlopen(req, timeout=10) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    for pname in ["clip_name", "clip_name1"]:
                        items = (data.get(node_type, {})
                                 .get("input", {}).get("required", {})
                                 .get(pname, [None])[0])
                        if isinstance(items, list):
                            result["clip_models"] = items
                            log_ok(f"clip_models: {len(items)}")
                            break
            except Exception:
                pass
            break

    return result


# ─── Feature detection ────────────────────────────────────────────────────────

def detect_available_features(manifest: dict, server_info: dict) -> list[str]:
    """Cross-reference server capabilities against manifest features.

    Returns a list of feature keys whose required nodes + models are present
    on the remote server.
    """
    section("Feature Detection")

    available_nodes = server_info.get("available_nodes", set())
    if not available_nodes:
        log_warn("No node data — cannot detect features.")
        return list(manifest.get("features", {}).keys())

    # Build a flat set of server model basenames for loose matching
    server_models: set[str] = set()
    for key in ("checkpoints", "unet_models", "loras", "vaes",
                "clip_models", "controlnets"):
        for m in server_info.get(key, []):
            server_models.add(m.lower())
            basename = m.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
            server_models.add(basename.lower())

    available: list[str] = []
    missing: list[str] = []

    for feat_key, feat in manifest.get("features", {}).items():
        # Check nodes
        nodes_ok = True
        for pack_name in feat.get("custom_nodes", []):
            pack_def = manifest.get("custom_nodes", {}).get(pack_name, {})
            provides = pack_def.get("provides", [])
            if provides and not any(p in available_nodes for p in provides):
                nodes_ok = False
                break

        if nodes_ok:
            available.append(feat_key)
            log_ok(f"{feat['label']}")
        else:
            missing.append(feat_key)
            log_dim(f"{feat['label']}  — missing nodes")

    log_info(f"{len(available)} feature(s) available, "
             f"{len(missing)} missing nodes on server")
    return available


def detect_nsfw_mode(server_info: dict) -> bool:
    """Detect whether the remote ComfyUI server is running the NSFW edition.

    Checks the server's LoRA and model lists for known NSFW-specific patterns.
    Returns True if NSFW content is detected, False for SFW.
    """
    section("Edition Detection (SFW / NSFW)")

    # Flatten all LoRA names to lowercase for pattern matching
    loras_lower = [l.lower().replace("\\", "/")
                   for l in server_info.get("loras", [])]

    # Check LoRAs for NSFW patterns
    nsfw_loras_found: list[str] = []
    for lora in loras_lower:
        for pattern in NSFW_LORA_PATTERNS:
            if pattern in lora:
                # Get the original (un-lowered) name for display
                idx = loras_lower.index(lora)
                original = server_info.get("loras", [])[idx]
                nsfw_loras_found.append(original)
                break

    # Check unet/checkpoint models for NSFW patterns
    nsfw_models_found: list[str] = []
    all_models = (server_info.get("unet_models", [])
                  + server_info.get("checkpoints", []))
    for model in all_models:
        model_lower = model.lower().replace("\\", "/")
        for pattern in NSFW_MODEL_PATTERNS:
            if pattern in model_lower:
                nsfw_models_found.append(model)
                break

    is_nsfw = bool(nsfw_loras_found or nsfw_models_found)

    if is_nsfw:
        log_ok(f"{C_BOLD}NSFW edition detected{C_RESET}")
        if nsfw_loras_found:
            log_dim(f"NSFW LoRAs: {', '.join(nsfw_loras_found[:5])}")
        if nsfw_models_found:
            log_dim(f"NSFW models: {', '.join(nsfw_models_found[:5])}")
    else:
        log_ok(f"{C_BOLD}SFW edition detected{C_RESET} (no NSFW content on server)")

    return is_nsfw


# ─── Shared helpers (re-exported from install.py) ─────────────────────────────
#
# install.py is the canonical source for path detection, plugin-source lookup,
# and LoRA classification. Re-binding here keeps existing call sites working
# while ensuring both installers stay in lockstep on these helpers.

_scan_gimp_versions       = install._scan_gimp_versions
_win_registry_gimp        = install._win_registry_gimp
find_default_gimp         = install.find_default_gimp
find_default_darktable    = install.find_default_darktable
_find_gimp_plugin_src     = install._find_gimp_plugin_src
_find_darktable_plugin_src = install._find_darktable_plugin_src
_find_tavern_src          = install._find_tavern_src
_find_scaffold_src        = install._find_scaffold_src
_classify_server_loras    = install._classify_server_loras


# ─── Settings writer ─────────────────────────────────────────────────────────

def write_settings(paths: dict, server_url: str, llm_url: str,
                   server_info: dict, nsfw_mode: bool = False,
                   dry_run: bool = False) -> dict:
    """Write spellcaster_settings.json — shared config all plugins read."""
    section("Writing Settings")

    lora_archs = {}
    if server_info.get("loras"):
        try:
            lora_archs = _classify_server_loras(server_info["loras"])
        except Exception as e:
            log_warn(f"LoRA classification failed: {e}")

    settings = {
        "version": VERSION,
        "comfyui_url": server_url,
        "llm_url": llm_url,
        "server_reachable": server_info.get("reachable", False),
        "remote_install": True,
        "nsfw_mode": nsfw_mode,
        "available_nodes": sorted(server_info.get("available_nodes", set())),
        "models": {
            "checkpoints": server_info.get("checkpoints", []),
            "unet_models": server_info.get("unet_models", []),
            "loras": server_info.get("loras", []),
            "vaes": server_info.get("vaes", []),
            "clip_models": server_info.get("clip_models", []),
            "controlnets": server_info.get("controlnets", []),
        },
        "lora_architectures": lora_archs,
    }

    if dry_run:
        log_dim("[dry-run] Would write spellcaster_settings.json")
        return settings

    # Master copy next to installer
    master_path = SCRIPT_DIR / "spellcaster_settings.json"
    try:
        master_path.write_text(json.dumps(settings, indent=2), encoding="utf-8")
        log_ok(f"Master settings: {master_path}")
    except Exception as e:
        log_warn(f"Failed to write master settings: {e}")

    # Copy into GIMP plugin dir
    if paths.get("gimp"):
        gimp_settings = paths["gimp"] / "comfyui-connector" / "spellcaster_settings.json"
        try:
            gimp_settings.parent.mkdir(parents=True, exist_ok=True)
            gimp_settings.write_text(json.dumps(settings, indent=2), encoding="utf-8")
        except Exception:
            pass

    return settings


# ─── Plugin installation ─────────────────────────────────────────────────────

def install_gimp_plugin(gimp_path: Path, server_url: str, dry_run: bool = False):
    """Copy the GIMP plugin and write its config.json."""
    gimp_src = _find_gimp_plugin_src()
    if not gimp_src:
        log_warn("GIMP plugin source not found — skipping.")
        return

    if dry_run:
        log_dim(f"[dry-run] Would install GIMP plugin to {gimp_path}")
        return

    gimp_path.mkdir(parents=True, exist_ok=True)
    dest = gimp_path / gimp_src.name

    # Full copy (rmtree + copytree to replace stale files)
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(gimp_src, dest)
    log_ok(f"GIMP plugin → {dest}")

    # Write config.json with remote server URL
    config_path = dest / "config.json"
    config_path.write_text(json.dumps({"server_url": server_url}, indent=4),
                           encoding="utf-8")
    log_ok("Wrote config.json")

    # Unix: make executable
    if os.name != "nt":
        py_file = dest / "comfyui-connector.py"
        if py_file.exists():
            py_file.chmod(0o755)

    # Delete GIMP pluginrc cache so GIMP re-scans
    _delete_gimp_pluginrc()


# Re-export — single source of truth in install.py
_delete_gimp_pluginrc = install._delete_gimp_pluginrc


def install_darktable_plugin(dt_path: Path, server_url: str, dry_run: bool = False):
    """Copy the Darktable Lua plugin."""
    dt_src = _find_darktable_plugin_src()
    if not dt_src:
        log_warn("Darktable plugin source not found — skipping.")
        return

    if dry_run:
        log_dim(f"[dry-run] Would install Darktable plugin to {dt_path}")
        return

    dt_path.mkdir(parents=True, exist_ok=True)
    dest = dt_path / dt_src.name

    # If the server URL differs from localhost default, patch before copying
    DEFAULT_SERVER = "http://127.0.0.1:8188"
    if server_url != DEFAULT_SERVER:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            tmp_file = Path(tmp) / dt_src.name
            shutil.copy2(dt_src, tmp_file)
            content = tmp_file.read_text(encoding="utf-8")
            content = content.replace(DEFAULT_SERVER, server_url)
            tmp_file.write_text(content, encoding="utf-8")
            shutil.copy2(tmp_file, dest)
    else:
        shutil.copy2(dt_src, dest)

    log_ok(f"Darktable plugin → {dest}")

    # Check luarc
    dt_config_dir = dt_path.parent.parent
    luarc = dt_config_dir / "luarc"
    if luarc.exists():
        content = luarc.read_text(encoding="utf-8")
        if "comfyui_connector" not in content:
            log_warn(f"Add to your luarc ({luarc}):")
            log_dim(f'  require "contrib/comfyui_connector"')
        else:
            log_ok("comfyui_connector already in luarc")
    else:
        log_warn(f"Create luarc at: {dt_config_dir}/luarc")
        log_dim(f'  Content: require "contrib/comfyui_connector"')


# ─── Wizard Guild (Tavern) installation ───────────────────────────────────────

def _get_tavern_install_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return base / "Spellcaster" / "tavern"
    elif sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Spellcaster" / "tavern"
    else:
        return Path.home() / ".local" / "share" / "spellcaster" / "tavern"


def install_wizard_guild(server_url: str, llm_url: str,
                         nsfw_mode: bool = False, nsfw_token: str = "",
                         dry_run: bool = False):
    """Deploy the Wizard Guild standalone interface.

    When nsfw_mode is True:
    - Writes nsfw/.github_token so the Guild auto-updates from the NSFW repo
    - Sets NSFW_MODE in the guild config
    """
    tavern_src = _find_tavern_src()
    scaffold_src = _find_scaffold_src()

    if not tavern_src:
        log_warn("Tavern source not found — skipping Wizard Guild.")
        return

    dest = _get_tavern_install_dir()
    scaffold_dest = dest.parent / "scaffold"

    if dry_run:
        log_dim(f"[dry-run] Would install Wizard Guild to {dest}")
        if nsfw_mode:
            log_dim(f"[dry-run] Would configure NSFW edition")
        return

    log_info(f"Installing Wizard Guild → {dest}")
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "static").mkdir(parents=True, exist_ok=True)

    # Copy tavern files
    copied = 0
    for item in tavern_src.rglob("*"):
        if item.is_file() and "__pycache__" not in str(item) and "build" not in item.parts:
            rel = item.relative_to(tavern_src)
            target = dest / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)
            copied += 1
    log_ok(f"Copied {copied} tavern files")

    # Copy scaffold files
    if scaffold_src:
        scaffold_dest.mkdir(parents=True, exist_ok=True)
        sc_copied = 0
        for item in scaffold_src.rglob("*"):
            if item.is_file() and "__pycache__" not in str(item):
                rel = item.relative_to(scaffold_src)
                target = scaffold_dest / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, target)
                sc_copied += 1
        log_ok(f"Copied {sc_copied} scaffold files")

    # ── NSFW edition setup ──
    # The Wizard Guild detects NSFW mode at runtime by checking for
    # nsfw/.github_token adjacent to the tavern directory.  When present,
    # guild_launcher.py switches to the NSFW repo for auto-updates and
    # sets server.NSFW_MODE = True for content pools.
    if nsfw_mode and nsfw_token:
        nsfw_dir = dest.parent / "nsfw"
        nsfw_dir.mkdir(parents=True, exist_ok=True)
        token_path = nsfw_dir / ".github_token"
        token_path.write_text(nsfw_token, encoding="utf-8")
        # Lock the token file to the owner. Without this it inherits
        # the process umask (often 0o644) and any other user on the
        # box can read the private-repo PAT.
        try:
            os.chmod(token_path, 0o600)
        except OSError:
            # Windows NTFS doesn't honor POSIX bits the same way; the
            # ACL is already owner-restricted by default. Don't fail
            # the install just because chmod is a no-op here.
            pass
        log_ok(f"NSFW token written → {token_path}")
        log_info("Guild will auto-update from NSFW repo")
    elif nsfw_mode and not nsfw_token:
        log_warn("NSFW mode detected but no --nsfw-token provided.")
        log_dim("Wizard Guild will run in SFW mode without the token.")
        log_dim("Use --nsfw-token <PAT> to enable NSFW auto-updates.")

    # Write guild config
    guild_config = dest / "guild_config.json"
    config_data = {
        "comfyui_url": server_url,
        "kobold_url": llm_url or "http://127.0.0.1:5001",
        "prompt_enhance": bool(llm_url),
        "auto_update": True,
    }
    if not guild_config.exists():
        guild_config.write_text(json.dumps(config_data, indent=2),
                                encoding="utf-8")
        log_ok(f"Wrote guild_config.json (ComfyUI: {server_url})")
    else:
        log_ok("guild_config.json preserved (existing)")

    # Unix: make executable
    if os.name != "nt":
        for py in dest.glob("*.py"):
            py.chmod(0o755)

    # Create launcher script
    launcher_path = dest / "guild_launcher.py"
    if sys.platform == "win32":
        bat_path = dest.parent / "wizard-guild.bat"
        bat_path.write_text(
            f'@echo off\r\npython "{launcher_path}" --comfyui {server_url} %*\r\n',
            encoding="utf-8"
        )
        log_ok(f"Launcher: {bat_path}")
    else:
        sh_path = dest.parent / "wizard-guild"
        sh_path.write_text(
            f'#!/bin/sh\npython3 "{launcher_path}" --comfyui {server_url} "$@"\n',
            encoding="utf-8"
        )
        sh_path.chmod(0o755)
        log_ok(f"Launcher: {sh_path}")

    return dest, launcher_path


# ─── Desktop shortcuts ────────────────────────────────────────────────────────

def create_shortcuts(launcher_path: Path, server_url: str, dry_run: bool = False):
    """Create desktop shortcuts pointing at the remote ComfyUI."""
    if not launcher_path or not launcher_path.exists():
        return

    section("Desktop Shortcuts")

    if dry_run:
        log_dim("[dry-run] Would create desktop shortcuts")
        return

    icon_path = launcher_path.parent / "static" / "favicon.ico"
    if not icon_path.exists():
        icon_path = None

    # Desktop shortcut
    if sys.platform == "win32":
        desktop = Path(os.environ.get("USERPROFILE", Path.home())) / "Desktop"
    else:
        desktop = Path.home() / "Desktop"

    if desktop.is_dir():
        if sys.platform == "win32":
            _create_shortcut_windows(launcher_path, "Wizard Guild", desktop,
                                     server_url, icon_path)
        else:
            _create_shortcut_unix(launcher_path, "Wizard Guild", desktop,
                                  server_url)
        log_ok("Desktop shortcut created")

    # Start Menu (Windows) / App menu (Linux)
    if sys.platform == "win32":
        start_menu = (Path(os.environ.get("APPDATA", ""))
                      / "Microsoft" / "Windows" / "Start Menu"
                      / "Programs" / "Spellcaster")
        try:
            start_menu.mkdir(parents=True, exist_ok=True)
            _create_shortcut_windows(launcher_path, "Wizard Guild",
                                     start_menu, server_url, icon_path)
            log_ok("Start Menu shortcut created")
        except Exception as e:
            log_warn(f"Start Menu shortcut failed: {e}")
    elif sys.platform == "linux":
        apps_dir = Path.home() / ".local" / "share" / "applications"
        try:
            apps_dir.mkdir(parents=True, exist_ok=True)
            _create_shortcut_unix(launcher_path, "Wizard Guild",
                                  apps_dir, server_url)
            log_ok("App menu entry created")
        except Exception as e:
            log_warn(f"App menu entry failed: {e}")


def _create_shortcut_windows(target_script: Path, shortcut_name: str,
                             shortcut_dir: Path, server_url: str,
                             icon_path: Path | None = None):
    shortcut_path = shortcut_dir / f"{shortcut_name}.lnk"
    ps_script = (
        f'$ws = New-Object -ComObject WScript.Shell; '
        f'$s = $ws.CreateShortcut("{shortcut_path}"); '
        f'$s.TargetPath = "pythonw.exe"; '
        f'$s.Arguments = """{target_script}"" --comfyui {server_url}"; '
        f'$s.WorkingDirectory = "{target_script.parent}"; '
        f'$s.Description = "Launch Spellcaster Wizard Guild"; '
    )
    if icon_path and icon_path.exists():
        ps_script += f'$s.IconLocation = "{icon_path}"; '
    ps_script += '$s.Save()'
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_script],
            capture_output=True, timeout=10
        )
        if shortcut_path.exists():
            return shortcut_path
    except Exception:
        pass
    # Fallback: .bat
    bat_path = shortcut_dir / f"{shortcut_name}.bat"
    bat_path.write_text(
        f'@echo off\r\npython "{target_script}" --comfyui {server_url} %*\r\n',
        encoding="utf-8"
    )
    return bat_path


def _create_shortcut_unix(target_script: Path, shortcut_name: str,
                          shortcut_dir: Path, server_url: str):
    if sys.platform == "darwin":
        app_path = shortcut_dir / f"{shortcut_name}.command"
        app_path.write_text(
            f'#!/bin/sh\ncd "{target_script.parent}"\n'
            f'python3 "{target_script}" --comfyui {server_url} "$@"\n',
            encoding="utf-8"
        )
        app_path.chmod(0o755)
        return app_path
    else:
        desktop_path = (shortcut_dir /
                        f"{shortcut_name.lower().replace(' ', '-')}.desktop")
        desktop_path.write_text(
            f'[Desktop Entry]\n'
            f'Type=Application\n'
            f'Name={shortcut_name}\n'
            f'Comment=Launch Spellcaster Wizard Guild\n'
            f'Exec=python3 "{target_script}" --comfyui {server_url}\n'
            f'Path={target_script.parent}\n'
            f'Terminal=true\n'
            f'Categories=Graphics;Utility;\n',
            encoding="utf-8"
        )
        desktop_path.chmod(0o755)
        return desktop_path


# ─── Summary ──────────────────────────────────────────────────────────────────

def print_summary(server_url: str, llm_url: str, paths: dict,
                  features: list[str], manifest: dict,
                  nsfw_mode: bool = False):
    section("INSTALLATION COMPLETE")

    edition = f"{C_RED}NSFW{C_RESET}" if nsfw_mode else f"{C_GREEN}SFW{C_RESET}"
    print(f"  {C_BOLD}Edition:{C_RESET}        {edition}")
    print(f"  {C_BOLD}Remote ComfyUI:{C_RESET} {server_url}")
    if llm_url:
        print(f"  {C_BOLD}LLM server:{C_RESET}     {llm_url}")

    print(f"\n  {C_BOLD}Installed locally:{C_RESET}")
    if paths.get("gimp"):
        log_ok(f"GIMP plugin      → {paths['gimp']}")
    if paths.get("darktable"):
        log_ok(f"Darktable plugin → {paths['darktable']}")
    if paths.get("tavern"):
        log_ok(f"Wizard Guild     → {paths['tavern']}")

    if features:
        print(f"\n  {C_BOLD}Features detected on server ({len(features)}):{C_RESET}")
        for fk in features[:15]:
            feat = manifest.get("features", {}).get(fk, {})
            print(f"    {C_GREEN}✓{C_RESET} {feat.get('label', fk)}")
        if len(features) > 15:
            print(f"    {C_DIM}... and {len(features) - 15} more{C_RESET}")

    print(f"\n  {C_BOLD}Next steps:{C_RESET}")
    print(f"    1. Make sure ComfyUI is running on {server_url}")
    if paths.get("gimp"):
        print(f"    2. Open GIMP 3 → Filters → Spellcaster")
    if paths.get("darktable"):
        print(f"    3. Open Darktable — Spellcaster panel in lighttable")
    if paths.get("tavern"):
        print(f"    4. Launch Wizard Guild from your Desktop shortcut")

    print(f"\n  {C_BOLD}Troubleshooting:{C_RESET}")
    print(f"    • 'Cannot connect' — verify the remote machine is running ComfyUI")
    print(f"    • Check firewall rules allow port access from this machine")
    print(f"    • Report issues: https://github.com/laboratoiresonore/spellcaster/issues")
    print()


# ─── Entry point ──────────────────────────────────────────────────────────────

def build_arg_parser():
    parser = argparse.ArgumentParser(
        description="Spellcaster Remote Installer — autonomous setup for remote ComfyUI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Examples:
              python install_remote.py http://<SERVER-IP>:8188
              python install_remote.py --scan
              python install_remote.py http://<SERVER-IP>:8188 --llm-url http://<LLM-IP>:5001
              python install_remote.py http://<SERVER-IP>:8188 --dry-run
        """)
    )
    parser.add_argument("server_url", nargs="?", default="",
                        help="ComfyUI server URL (e.g. http://<SERVER-IP>:8188)")
    parser.add_argument("--scan", action="store_true",
                        help="Auto-discover ComfyUI servers on the local network")
    parser.add_argument("--port", type=int, default=8188,
                        help="Port to scan for ComfyUI servers (default: 8188)")
    parser.add_argument("--llm-url", default="",
                        help="LLM server URL for prompt enhancement (e.g. http://<SERVER-IP>:5001)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview what would be done without making changes")
    parser.add_argument("--skip-gimp", action="store_true",
                        help="Skip GIMP plugin installation")
    parser.add_argument("--skip-darktable", action="store_true",
                        help="Skip Darktable plugin installation")
    parser.add_argument("--skip-guild", action="store_true",
                        help="Skip Wizard Guild installation")
    parser.add_argument("--skip-shortcuts", action="store_true",
                        help="Skip desktop shortcut creation")
    parser.add_argument("--gimp", metavar="PATH",
                        help="Override GIMP plug-ins directory")
    parser.add_argument("--darktable", metavar="PATH",
                        help="Override Darktable lua/contrib directory")
    parser.add_argument("--nsfw-token", metavar="PAT", default="",
                        help="GitHub PAT for NSFW repo auto-updates. "
                             "Enables Wizard Guild NSFW edition with auto-update support.")
    parser.add_argument("--force-sfw", action="store_true",
                        help="Force SFW mode even if NSFW content is detected on server")
    parser.add_argument("--interactive", action="store_true",
                        help="Use interactive prompts instead of auto-detection")
    parser.add_argument("--version", action="version",
                        version=f"Spellcaster Remote Installer v{VERSION}")
    return parser


def main():
    args = build_arg_parser().parse_args()

    banner()

    if args.dry_run:
        print(f"  {C_YELLOW}DRY RUN MODE — no changes will be made{C_RESET}\n")

    manifest = load_manifest()

    # ── Determine server URL ──────────────────────────────────────────
    server_url = args.server_url.rstrip("/") if args.server_url else ""

    if args.scan or not server_url:
        found = scan_network_for_comfyui(port=args.port)
        if found:
            if len(found) == 1:
                server_url = found[0]
                log_ok(f"Using discovered server: {server_url}")
            else:
                # Multiple servers — pick the first, or ask in interactive mode
                if args.interactive:
                    print(f"\n  Found {len(found)} servers:")
                    for i, url in enumerate(found):
                        print(f"    {i+1}) {url}")
                    while True:
                        raw = input(f"\n  {C_BOLD}Choose server [1-{len(found)}]:{C_RESET} ").strip()
                        try:
                            idx = int(raw) - 1
                            if 0 <= idx < len(found):
                                server_url = found[idx]
                                break
                        except ValueError:
                            pass
                else:
                    server_url = found[0]
                    log_info(f"Multiple servers found — using first: {server_url}")
        elif not server_url:
            if args.interactive:
                server_url = input(
                    f"\n  {C_BOLD}Enter ComfyUI server URL:{C_RESET} ").strip().rstrip("/")
            else:
                log_err("No server URL provided and network scan found nothing.")
                print(f"\n  Usage: python install_remote.py http://<SERVER-IP>:8188")
                print(f"         python install_remote.py --scan")
                sys.exit(1)

    # Normalize URL
    if not server_url.startswith("http"):
        server_url = "http://" + server_url

    llm_url = args.llm_url.rstrip("/") if args.llm_url else ""

    # ── Probe remote server ───────────────────────────────────────────
    server_info = probe_server(server_url)
    if not server_info["reachable"]:
        log_err("Server unreachable — cannot continue.")
        log_dim("Check that ComfyUI is running and accessible from this machine.")
        sys.exit(1)

    # ── Detect available features ─────────────────────────────────────
    available_features = detect_available_features(manifest, server_info)

    # ── Detect SFW / NSFW edition ─────────────────────────────────────
    if args.force_sfw:
        nsfw_mode = False
        log_info("SFW mode forced via --force-sfw")
    else:
        nsfw_mode = detect_nsfw_mode(server_info)

    nsfw_token = args.nsfw_token

    # ── Detect local application paths ────────────────────────────────
    section("Local Application Detection")

    paths: dict[str, Any] = {"gimp": None, "darktable": None, "tavern": None}

    # GIMP
    if not args.skip_gimp:
        if args.gimp:
            gimp_path = Path(args.gimp).expanduser().resolve()
            if gimp_path.is_dir() or not gimp_path.exists():
                paths["gimp"] = gimp_path
                log_ok(f"GIMP (from args): {gimp_path}")
        else:
            default_gimp = find_default_gimp()
            if default_gimp:
                paths["gimp"] = Path(default_gimp)
                log_ok(f"GIMP detected: {default_gimp}")
            else:
                log_warn("GIMP 3 not detected — skipping GIMP plugin.")
                if args.interactive:
                    raw = input(f"    Enter GIMP plug-ins path (or Enter to skip): ").strip()
                    if raw:
                        paths["gimp"] = Path(raw).expanduser().resolve()
    else:
        log_dim("GIMP plugin: skipped (--skip-gimp)")

    # Darktable
    if not args.skip_darktable:
        if args.darktable:
            dt_path = Path(args.darktable).expanduser().resolve()
            if dt_path.is_dir() or not dt_path.exists():
                paths["darktable"] = dt_path
                log_ok(f"Darktable (from args): {dt_path}")
        else:
            default_dt = find_default_darktable()
            if default_dt:
                paths["darktable"] = Path(default_dt)
                log_ok(f"Darktable detected: {default_dt}")
            else:
                log_dim("Darktable not detected — skipping.")
    else:
        log_dim("Darktable plugin: skipped (--skip-darktable)")

    # ── Install plugins ───────────────────────────────────────────────
    section("Installing Plugins")

    if paths["gimp"]:
        install_gimp_plugin(paths["gimp"], server_url, args.dry_run)

    if paths["darktable"]:
        install_darktable_plugin(paths["darktable"], server_url, args.dry_run)

    if not paths["gimp"] and not paths["darktable"]:
        log_warn("No host application detected — no plugins installed.")

    # ── Install Wizard Guild ──────────────────────────────────────────
    if not args.skip_guild:
        section("Installing Wizard Guild")
        result = install_wizard_guild(server_url, llm_url,
                                      nsfw_mode=nsfw_mode,
                                      nsfw_token=nsfw_token,
                                      dry_run=args.dry_run)
        if result:
            dest, launcher_path = result
            paths["tavern"] = dest

            # Desktop shortcuts
            if not args.skip_shortcuts:
                create_shortcuts(launcher_path, server_url, args.dry_run)
    else:
        log_dim("Wizard Guild: skipped (--skip-guild)")

    # ── Write shared settings ─────────────────────────────────────────
    write_settings(paths, server_url, llm_url, server_info,
                   nsfw_mode=nsfw_mode, dry_run=args.dry_run)

    # ── Summary ───────────────────────────────────────────────────────
    print_summary(server_url, llm_url, paths, available_features, manifest,
                  nsfw_mode=nsfw_mode)


if __name__ == "__main__":
    main()
