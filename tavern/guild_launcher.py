#!/usr/bin/env python3
"""
Wizard Guild Launcher
=====================
Entry point for the standalone Wizard Guild application.

Features:
  - Persistent configuration file (guild_config.json)
  - Interactive first-run setup wizard
  - Kills any prior instance on the same port before binding
  - Auto-update from GitHub on startup (SFW or NSFW edition)
  - Opens browser automatically after server starts
  - SillyTavern auto-detection and background launch

Usage:
    python guild_launcher.py                    # Normal start (setup on first run)
    python guild_launcher.py --setup            # Force re-run the setup wizard
    python guild_launcher.py --port 9000        # Override port for this session
    python guild_launcher.py --no-browser       # Don't auto-open browser
    python guild_launcher.py --no-update        # Skip auto-update check
    python guild_launcher.py --comfyui http://192.168.x.x:8188

Auto-Update Architecture:
    SFW edition pulls from: laboratoiresonore/spellcaster  (public)
    NSFW edition pulls from: laboratoiresonore/spellcaster_NSFW (private)

    The NSFW version is the SFW version PLUS extra content injected
    by build_nsfw.py.  There is no conflict: NSFW extends SFW, never
    removes or replaces SFW-only content.

    On startup the launcher:
      1. Checks the latest commit SHA on the configured repo branch
      2. Compares with .guild_version in the app directory
      3. If different: downloads ALL files under tavern/ from the repo
      4. Also re-downloads scaffold/ files for node introspection
      5. Writes new SHA to .guild_version
      6. Restarts itself (exec) so the new code runs immediately
"""

import argparse
import json
import os
import subprocess
import sys
import threading
import time
import urllib.request
import urllib.error
import traceback
import socket

# ═══════════════════════════════════════════════════════════════════════
#  Auto-Update Configuration
# ═══════════════════════════════════════════════════════════════════════
# These are patched by build_nsfw.py for the NSFW edition.
# SFW defaults are the public repo; NSFW overrides point to the private
# repo with an embedded auth token.

_GUILD_REPO = "laboratoiresonore/spellcaster"
_GUILD_BRANCH = "main"
_GUILD_AUTH_TOKEN = ""  # empty for SFW (public); PAT for NSFW (private)

# Prefixes within the repo that belong to the Guild
_TAVERN_PREFIX = "tavern/"
_SCAFFOLD_PREFIX = "scaffold/"

# GitHub API URLs (constructed from repo)
_GUILD_COMMITS_URL = (
    f"https://api.github.com/repos/{_GUILD_REPO}"
    f"/commits?sha={_GUILD_BRANCH}&per_page=1"
)
_GUILD_TREE_URL = (
    f"https://api.github.com/repos/{_GUILD_REPO}"
    f"/git/trees/{_GUILD_BRANCH}?recursive=1"
)
_GUILD_RAW_BASE = (
    f"https://raw.githubusercontent.com/{_GUILD_REPO}/{_GUILD_BRANCH}"
)


# ═══════════════════════════════════════════════════════════════════════
#  Path Resolution
# ═══════════════════════════════════════════════════════════════════════

if getattr(sys, 'frozen', False):
    # Running as PyInstaller bundle
    BUNDLE_DIR = sys._MEIPASS
    sys.path.insert(0, BUNDLE_DIR)
    # App dir = where the exe lives (writable, for version file + updates)
    APP_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    # Running from source
    BUNDLE_DIR = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, os.path.dirname(BUNDLE_DIR))
    plugins_dir = os.path.join(
        os.path.dirname(BUNDLE_DIR), 'plugins', 'gimp', 'comfyui-connector')
    if os.path.isdir(plugins_dir):
        sys.path.insert(0, plugins_dir)
    APP_DIR = BUNDLE_DIR


# ═══════════════════════════════════════════════════════════════════════
#  Configuration System — persistent settings in guild_config.json
# ═══════════════════════════════════════════════════════════════════════

_CONFIG_FILE = os.path.join(APP_DIR, "guild_config.json")

_DEFAULT_CONFIG = {
    "guild_port": 7777,
    "comfyui_url": "http://127.0.0.1:8188",
    "kobold_url": "http://127.0.0.1:5001",
    "sillytavern_dir": "",
    "koboldcpp_dir": "",
    "kobold_model": "",
    "auto_open_browser": True,
    "auto_update": True,
    "auto_launch_st": True,
    "auto_launch_kobold": False,
}


def load_config():
    """Load configuration from guild_config.json, falling back to defaults."""
    config = dict(_DEFAULT_CONFIG)
    if os.path.exists(_CONFIG_FILE):
        try:
            with open(_CONFIG_FILE, 'r') as f:
                saved = json.load(f)
            config.update(saved)
        except Exception as e:
            print(f"  [config] Warning: Could not read {_CONFIG_FILE}: {e}")
    return config


def save_config(config):
    """Persist configuration to guild_config.json."""
    try:
        with open(_CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=2)
    except Exception as e:
        print(f"  [config] Warning: Could not save config: {e}")


def config_exists():
    """Check if a config file already exists."""
    return os.path.exists(_CONFIG_FILE)


# ═══════════════════════════════════════════════════════════════════════
#  Interactive Setup Wizard
# ═══════════════════════════════════════════════════════════════════════

def _input_with_default(prompt, default):
    """Prompt for input with a default value shown in brackets."""
    try:
        val = input(f"  {prompt} [{default}]: ").strip()
        return val if val else str(default)
    except (EOFError, KeyboardInterrupt):
        print()
        return str(default)


def _input_yes_no(prompt, default=True):
    """Prompt for yes/no with a default."""
    hint = "Y/n" if default else "y/N"
    try:
        val = input(f"  {prompt} [{hint}]: ").strip().lower()
        if not val:
            return default
        return val in ('y', 'yes')
    except (EOFError, KeyboardInterrupt):
        print()
        return default


def _test_endpoint(url, path="", timeout=3):
    """Quick connectivity test to a URL. Returns True if reachable."""
    try:
        req = urllib.request.Request(
            f"{url.rstrip('/')}/{path.lstrip('/')}",
            headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


def run_setup_wizard(existing_config=None):
    """Interactive setup wizard. Returns a config dict.

    If existing_config is provided, its values are used as defaults.
    """
    config = dict(existing_config or _DEFAULT_CONFIG)

    print()
    print("  +==========================================+")
    print("  |      WIZARD GUILD — SETUP WIZARD         |")
    print("  +==========================================+")
    print()
    print("  Configure your Wizard Guild installation.")
    print("  Press Enter to accept the default value shown in [brackets].")
    print()

    # ── 1. Guild Port ────────────────────────────────────────────────
    print("  ── Server ──────────────────────────────────────")
    port_str = _input_with_default(
        "Guild server port", config["guild_port"])
    try:
        config["guild_port"] = int(port_str)
    except ValueError:
        print(f"    Invalid port '{port_str}', using default 7777")
        config["guild_port"] = 7777

    # ── 2. ComfyUI ───────────────────────────────────────────────────
    print()
    print("  ── ComfyUI (image generation) ──────────────────")
    config["comfyui_url"] = _input_with_default(
        "ComfyUI URL", config["comfyui_url"]).rstrip('/')

    # Test ComfyUI connection
    print(f"    Testing ComfyUI at {config['comfyui_url']}...", end=" ", flush=True)
    if _test_endpoint(config["comfyui_url"], "system_stats"):
        print("Connected!")
    else:
        print("Not reachable (will retry when Guild starts)")

    # ── 3. KoboldAI / LLM Backend ──────────────────────────────────
    print()
    print("  ── LLM Backend (for chat) ──────────────────────")
    print("    The Guild uses a KoboldAI-compatible API for wizard chat.")
    print("    This can be KoboldCPP, text-generation-webui, Ollama, or any")
    print("    OpenAI-compatible server at /api/v1/generate.")
    config["kobold_url"] = _input_with_default(
        "LLM API URL", config["kobold_url"]).rstrip('/')

    # Test LLM connection
    print(f"    Testing LLM at {config['kobold_url']}...", end=" ", flush=True)
    llm_reachable = _test_endpoint(config["kobold_url"], "api/v1/model")
    if llm_reachable:
        print("Connected!")
    else:
        print("Not reachable.")
        # Offer to download KoboldCPP
        print()
        print("    No LLM backend detected. The Guild needs one for chat.")
        print("    KoboldCPP is the simplest option — single file, no install.")
        kobold_dir = _find_koboldcpp(config.get("koboldcpp_dir") or None)
        if kobold_dir:
            print(f"    Found KoboldCPP at: {kobold_dir}")
        else:
            kobold_dir = _download_koboldcpp(verbose=True)
        if kobold_dir:
            config["koboldcpp_dir"] = kobold_dir
            config["auto_launch_kobold"] = True
            # Offer model download
            model_path = config.get("kobold_model", "")
            if not model_path or not os.path.isfile(model_path):
                model_path = _select_and_download_model(kobold_dir)
            if model_path:
                config["kobold_model"] = model_path

    # ── 4. SillyTavern ───────────────────────────────────────────────
    print()
    print("  ── SillyTavern (chat backend) ──────────────────")
    config["auto_launch_st"] = _input_yes_no(
        "Auto-launch SillyTavern on startup?",
        config.get("auto_launch_st", True))

    if config["auto_launch_st"]:
        # Try to auto-detect
        detected = _find_sillytavern(
            config.get("sillytavern_dir") or None)
        if detected:
            print(f"    Found SillyTavern at: {detected}")
            use_detected = _input_yes_no("Use this location?", True)
            if use_detected:
                config["sillytavern_dir"] = detected
            else:
                config["sillytavern_dir"] = _input_with_default(
                    "Path to SillyTavern directory",
                    config.get("sillytavern_dir", ""))
        else:
            st_path = _input_with_default(
                "Path to SillyTavern directory (leave blank to auto-download)",
                config.get("sillytavern_dir", ""))
            config["sillytavern_dir"] = st_path

    # ── 5. Preferences ───────────────────────────────────────────────
    print()
    print("  ── Preferences ─────────────────────────────────")
    config["auto_open_browser"] = _input_yes_no(
        "Auto-open browser on startup?",
        config.get("auto_open_browser", True))
    config["auto_update"] = _input_yes_no(
        "Auto-update from GitHub on startup?",
        config.get("auto_update", True))

    # ── Save ──────────────────────────────────────────────────────────
    print()
    save_config(config)
    print(f"  Configuration saved to: {_CONFIG_FILE}")
    print("  Run with --setup to change these settings later.")
    print()

    return config


# ═══════════════════════════════════════════════════════════════════════
#  Auto-Update System
# ═══════════════════════════════════════════════════════════════════════

def _guild_headers():
    """Build HTTP headers for GitHub API requests."""
    hdrs = {
        "User-Agent": "WizardGuild/1.0",
        "Accept": "application/vnd.github.v3+json",
    }
    if _GUILD_AUTH_TOKEN:
        hdrs["Authorization"] = f"token {_GUILD_AUTH_TOKEN}"
    return hdrs


def _guild_version_file():
    """Path to the local version tracker."""
    return os.path.join(APP_DIR, ".guild_version")


def _read_local_sha():
    """Read the locally stored commit SHA (7 or 40 chars)."""
    vf = _guild_version_file()
    if os.path.exists(vf):
        try:
            return open(vf, "r").read().strip()
        except Exception:
            pass
    return ""


def _write_local_sha(sha):
    """Write the latest commit SHA to disk."""
    try:
        with open(_guild_version_file(), "w") as f:
            f.write(sha)
    except Exception as e:
        print(f"  [update] Could not write version file: {e}")


def check_for_updates(verbose=True):
    """Check GitHub for a newer commit and apply updates if available.

    Returns True if an update was applied (caller should restart).
    Returns False if already up to date or if the check failed.
    """
    hdrs = _guild_headers()
    local_sha = _read_local_sha()

    if verbose:
        edition = "NSFW" if _GUILD_AUTH_TOKEN else "SFW"
        print(f"  [update] Checking for updates ({edition} edition)...")
        if local_sha:
            print(f"  [update] Local version: {local_sha[:7]}")

    # Step 1: Get latest commit SHA
    try:
        req = urllib.request.Request(_GUILD_COMMITS_URL, headers=hdrs)
        with urllib.request.urlopen(req, timeout=10) as r:
            commits = json.loads(r.read())
            latest_sha = commits[0]["sha"]
    except Exception as e:
        if verbose:
            print(f"  [update] Could not reach GitHub: {e}")
        return False

    # Step 2: Compare
    if latest_sha == local_sha or latest_sha[:7] == local_sha[:7]:
        if verbose:
            print(f"  [update] Already up to date ({latest_sha[:7]})")
        return False

    if verbose:
        print(f"  [update] New version available: {latest_sha[:7]}")

    # Step 3: Fetch full repo tree
    try:
        req = urllib.request.Request(_GUILD_TREE_URL, headers=hdrs)
        with urllib.request.urlopen(req, timeout=20) as r:
            tree = json.loads(r.read())
    except Exception as e:
        if verbose:
            print(f"  [update] Could not fetch file tree: {e}")
        return False

    # Step 4: Filter for tavern/ and scaffold/ files
    # Protected files: heavily customized locally, do NOT overwrite
    _PROTECTED_FILES = {
        "tavern/server.py",              # Custom Guild server with local enhancements
        "tavern/guild_launcher.py",      # This file — never overwrite self
        "tavern/guild_config.json",      # User configuration
        "tavern/static/app.js",          # Customized frontend JS
        "tavern/static/style.css",       # Customized frontend CSS
        "tavern/static/index.html",      # Customized Guild chat HTML
        "tavern/static/guild.html",      # Scaffold editor HTML
    }
    remote_files = []
    skipped = 0
    for item in tree.get("tree", []):
        if item["type"] != "blob":
            continue
        path = item["path"]
        if path in _PROTECTED_FILES:
            skipped += 1
            continue
        if path.startswith(_TAVERN_PREFIX) or path.startswith(_SCAFFOLD_PREFIX):
            remote_files.append(path)
    if skipped and verbose:
        print(f"  [update] Skipped {skipped} protected file(s)")

    if not remote_files:
        if verbose:
            print("  [update] No files found in tree (API issue?)")
        return False

    if verbose:
        print(f"  [update] Downloading {len(remote_files)} files...")

    # Step 5: Download all files
    updated = 0
    failed = 0
    # Determine base dir for writing:
    #   - For source mode: write relative to spellcaster root
    #   - For frozen mode: write to APP_DIR
    if getattr(sys, 'frozen', False):
        write_base = APP_DIR
    else:
        write_base = os.path.dirname(BUNDLE_DIR)  # spellcaster root

    for rel_path in remote_files:
        try:
            url = f"{_GUILD_RAW_BASE}/{rel_path}"
            dest = os.path.join(write_base, rel_path)
            os.makedirs(os.path.dirname(dest), exist_ok=True)

            req = urllib.request.Request(url, headers=hdrs)
            with urllib.request.urlopen(req, timeout=30) as r2:
                blob = r2.read()
                # Scrub null bytes from text files (NTFS corruption guard)
                if rel_path.endswith(('.py', '.js', '.css', '.html',
                                      '.json', '.jsx', '.md', '.txt')):
                    blob = blob.replace(b'\x00', b'')

            # Write via temp file for atomic replacement
            tmp = dest + ".tmp"
            with open(tmp, 'wb') as f:
                f.write(blob)
            try:
                os.replace(tmp, dest)
            except PermissionError:
                # Windows: file might be locked
                try:
                    os.remove(dest)
                    os.rename(tmp, dest)
                except Exception:
                    os.rename(tmp, dest + ".update")
            updated += 1
        except Exception as e:
            failed += 1
            if verbose:
                print(f"    FAIL: {rel_path}: {e}")

    if verbose:
        print(f"  [update] Updated {updated}/{len(remote_files)} files"
              f"{f' ({failed} failed)' if failed else ''}")

    # Step 6: Write version
    if updated > 0:
        _write_local_sha(latest_sha)
        if verbose:
            print(f"  [update] Version updated to {latest_sha[:7]}")
        return True

    return False


def _is_port_in_use(port: int) -> bool:
    """Check if a TCP port is already bound."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        return s.connect_ex(('127.0.0.1', port)) == 0


def _restart_self():
    """Re-exec the current process with the same arguments.

    This ensures updated code is loaded fresh.
    """
    print("  [update] Restarting with updated code...")
    time.sleep(0.5)
    python = sys.executable
    if getattr(sys, 'frozen', False):
        os.execv(python, [python] + sys.argv[1:])
    else:
        os.execv(python, [python] + sys.argv)


# ═══════════════════════════════════════════════════════════════════════
#  SillyTavern Backend — Detect / Download / Launch
# ═══════════════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════════════
#  KoboldCPP Auto-Setup — download and configure local LLM engine
# ═══════════════════════════════════════════════════════════════════════

_KOBOLD_RELEASES_API = "https://api.github.com/repos/LostRuins/koboldcpp/releases/latest"

_KOBOLD_SEARCH_PATHS = [
    os.path.join(BUNDLE_DIR, '..', '..', 'koboldcpp'),
    os.path.join(BUNDLE_DIR, '..', 'koboldcpp'),
    os.path.join(BUNDLE_DIR, 'koboldcpp'),
]

# GPU VRAM → recommended GGUF chat model
_KOBOLD_MODEL_RECS = [
    (4,  "Phi-3-mini-4k-instruct-q4.gguf",
         "https://huggingface.co/microsoft/Phi-3-mini-4k-instruct-gguf/resolve/main/Phi-3-mini-4k-instruct-q4.gguf",
         2.3),
    (8,  "mistral-7b-instruct-v0.2.Q4_K_M.gguf",
         "https://huggingface.co/TheBloke/Mistral-7B-Instruct-v0.2-GGUF/resolve/main/mistral-7b-instruct-v0.2.Q4_K_M.gguf",
         4.1),
    (12, "Meta-Llama-3.1-8B-Instruct-Q5_K_M.gguf",
         "https://huggingface.co/bartowski/Meta-Llama-3.1-8B-Instruct-GGUF/resolve/main/Meta-Llama-3.1-8B-Instruct-Q5_K_M.gguf",
         5.7),
    (99, "Meta-Llama-3.1-8B-Instruct-Q8_0.gguf",
         "https://huggingface.co/bartowski/Meta-Llama-3.1-8B-Instruct-GGUF/resolve/main/Meta-Llama-3.1-8B-Instruct-Q8_0.gguf",
         8.5),
]

_kobold_process = None


def _find_koboldcpp(explicit_dir=None):
    """Locate a KoboldCPP installation directory.

    Returns:
        Absolute path to the directory containing koboldcpp executable, or None.
    """
    exe_names = (["koboldcpp.exe", "koboldcpp_nocuda.exe"]
                 if sys.platform == "win32"
                 else ["koboldcpp", "koboldcpp-linux-x64"])

    if explicit_dir:
        d = os.path.abspath(explicit_dir)
        for exe in exe_names:
            if os.path.isfile(os.path.join(d, exe)):
                return d
        if explicit_dir.strip():
            print(f"  [kobold] WARNING: '{explicit_dir}' has no koboldcpp executable")

    for candidate in _KOBOLD_SEARCH_PATHS:
        d = os.path.abspath(candidate)
        for exe in exe_names:
            if os.path.isfile(os.path.join(d, exe)):
                return d
    return None


def _download_koboldcpp(verbose=True):
    """Download KoboldCPP from GitHub releases.

    On Windows, downloads the .exe directly. On other platforms, clones and builds.
    Returns the install directory path, or None on failure.
    """
    install_dir = os.path.abspath(
        os.path.join(BUNDLE_DIR, '..', 'koboldcpp'))

    print()
    print("  +--------------------------------------------------+")
    print("  |  KoboldCPP not found on this system.              |")
    print("  |  KoboldCPP is a local AI chatbot engine that      |")
    print("  |  powers the Wizard Guild's conversational AI.     |")
    print("  +--------------------------------------------------+")
    print()
    print(f"  Install location: {install_dir}")
    print()

    try:
        answer = input("  Download and set up KoboldCPP now? [Y/n] ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return None

    if answer.lower() in ('n', 'no'):
        print("  [kobold] Skipping KoboldCPP setup.")
        print("  [kobold] You can download it manually from:")
        print("           https://github.com/LostRuins/koboldcpp/releases")
        return None

    os.makedirs(install_dir, exist_ok=True)

    if sys.platform == "win32":
        # Download the Windows .exe directly from latest release
        print("  [kobold] Fetching latest release info...")
        try:
            req = urllib.request.Request(_KOBOLD_RELEASES_API,
                                        headers={"User-Agent": "spellcaster-guild/1.0"})
            with urllib.request.urlopen(req, timeout=15) as r:
                release = json.loads(r.read())
            # Find the main koboldcpp.exe asset
            exe_url = None
            for asset in release.get("assets", []):
                name = asset["name"].lower()
                if name == "koboldcpp.exe":
                    exe_url = asset["browser_download_url"]
                    break
            if not exe_url:
                # Fallback: first .exe asset
                for asset in release.get("assets", []):
                    if asset["name"].endswith(".exe"):
                        exe_url = asset["browser_download_url"]
                        break
            if not exe_url:
                print("  [kobold] ERROR: Could not find .exe in latest release")
                return None

            dest = os.path.join(install_dir, "koboldcpp.exe")
            print(f"  [kobold] Downloading {os.path.basename(exe_url)}...")
            urllib.request.urlretrieve(exe_url, dest)
            print(f"  [kobold] Downloaded to {dest}")
        except Exception as e:
            print(f"  [kobold] ERROR downloading: {e}")
            return None
    else:
        # Linux/macOS: clone and build
        try:
            subprocess.run(['git', '--version'], capture_output=True, check=True)
        except (FileNotFoundError, subprocess.CalledProcessError):
            print("  [kobold] ERROR: git is not installed.")
            print("           Install it from https://git-scm.com/downloads")
            return None

        print("  [kobold] Cloning KoboldCPP...")
        try:
            subprocess.run(
                ['git', 'clone', '--depth', '1',
                 'https://github.com/LostRuins/koboldcpp.git', install_dir],
                check=True,
            )
        except subprocess.CalledProcessError as e:
            print(f"  [kobold] ERROR: git clone failed: {e}")
            return None

        print("  [kobold] Building (make)...")
        try:
            subprocess.run(['make'], cwd=install_dir, check=True)
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            print(f"  [kobold] WARNING: build had issues: {e}")
            print("  [kobold] You may need to build manually.")

    print(f"  [kobold] KoboldCPP installed to {install_dir}")
    return install_dir


def _select_and_download_model(kobold_dir, vram_gb=None):
    """Recommend and download a GGUF chat model based on GPU VRAM.

    Returns the model file path, or None.
    """
    models_dir = os.path.join(kobold_dir, "models")
    os.makedirs(models_dir, exist_ok=True)

    # Check for existing models
    existing = [f for f in os.listdir(models_dir) if f.endswith(".gguf")]
    if existing:
        print(f"  [kobold] Found existing model(s): {', '.join(existing[:3])}")
        use_existing = input("  Use existing model? [Y/n] ").strip()
        if use_existing.lower() not in ('n', 'no'):
            return os.path.join(models_dir, existing[0])

    # Determine VRAM
    if vram_gb is None:
        try:
            vram_str = input("  How much GPU VRAM do you have? (4/6/8/12/16+) [8]: ").strip()
            vram_gb = int(vram_str) if vram_str else 8
        except (ValueError, EOFError):
            vram_gb = 8

    # Pick best model for VRAM
    rec_name, rec_url, rec_size = None, None, 0
    for max_vram, name, url, size in _KOBOLD_MODEL_RECS:
        if vram_gb <= max_vram:
            rec_name, rec_url, rec_size = name, url, size
            break

    if not rec_name:
        rec_name, rec_url, rec_size = _KOBOLD_MODEL_RECS[-1][1:]

    print(f"\n  Recommended model for {vram_gb}GB VRAM:")
    print(f"    {rec_name} ({rec_size:.1f} GB)")
    print()

    try:
        answer = input("  Download this model? [Y/n] ").strip()
    except (EOFError, KeyboardInterrupt):
        return None

    if answer.lower() in ('n', 'no'):
        return None

    dest = os.path.join(models_dir, rec_name)
    print(f"  [kobold] Downloading {rec_name} ({rec_size:.1f} GB)...")
    print(f"           This may take a while...")
    try:
        urllib.request.urlretrieve(rec_url, dest)
        print(f"  [kobold] Model saved to {dest}")
        return dest
    except Exception as e:
        print(f"  [kobold] ERROR downloading model: {e}")
        return None


def launch_koboldcpp(kobold_dir, model_path, port=5001, verbose=True):
    """Launch KoboldCPP in a background subprocess.

    Returns the Popen object, or None if launch failed.
    """
    global _kobold_process
    if verbose:
        print(f"  [kobold] Launching KoboldCPP with {os.path.basename(model_path)}")

    # Find executable
    if sys.platform == "win32":
        exe_candidates = ["koboldcpp.exe", "koboldcpp_nocuda.exe"]
    else:
        exe_candidates = ["koboldcpp", "./koboldcpp", "python3", "python"]
    exe = None
    for c in exe_candidates:
        full = os.path.join(kobold_dir, c)
        if os.path.isfile(full):
            exe = full
            break

    if exe is None:
        if verbose:
            print("  [kobold] ERROR: could not find koboldcpp executable")
        return None

    cmd = [exe, "--model", model_path, "--port", str(port),
           "--contextsize", "4096", "--quiet"]
    # Add CUDA if available (Windows .exe has it built-in)
    if sys.platform != "win32":
        cmd.append("--usecublas")

    try:
        kwargs = {}
        if sys.platform == 'win32':
            kwargs['creationflags'] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs['start_new_session'] = True

        _kobold_process = subprocess.Popen(
            cmd,
            cwd=kobold_dir,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            **kwargs,
        )
        if verbose:
            print(f"  [kobold] KoboldCPP started (PID {_kobold_process.pid})")
        return _kobold_process
    except Exception as e:
        if verbose:
            print(f"  [kobold] ERROR launching: {e}")
        return None


# ═══════════════════════════════════════════════════════════════════════
#  SillyTavern Auto-Setup — download and launch chat frontend
# ═══════════════════════════════════════════════════════════════════════

_ST_REPO = "https://github.com/SillyTavern/SillyTavern.git"
_ST_BRANCH = "release"

# Search paths relative to this file (tavern/) to find spellcaster-st/
_ST_SEARCH_PATHS = [
    os.path.join(BUNDLE_DIR, '..', '..', 'spellcaster-st'),        # spellcaster sibling
    os.path.join(BUNDLE_DIR, '..', '..', '..', 'spellcaster-st'),  # parent sibling
    os.path.join(BUNDLE_DIR, '..', 'sillytavern'),                 # inside spellcaster
    os.path.join(BUNDLE_DIR, 'sillytavern'),                       # inside tavern
]

_st_process = None  # Global ref so we can clean up on exit


def _find_sillytavern(explicit_dir=None):
    """Locate the SillyTavern installation directory.

    Args:
        explicit_dir: User-supplied path via --st-dir flag or config.

    Returns:
        Absolute path to the directory containing server.js, or None.
    """
    if explicit_dir:
        d = os.path.abspath(explicit_dir)
        if os.path.isfile(os.path.join(d, 'server.js')):
            return d
        # Don't warn if it's just empty string from config
        if explicit_dir.strip():
            print(f"  [st] WARNING: '{explicit_dir}' has no server.js")
        # Fall through to search paths

    for candidate in _ST_SEARCH_PATHS:
        d = os.path.abspath(candidate)
        if os.path.isfile(os.path.join(d, 'server.js')):
            return d
    return None


def _download_sillytavern(verbose=True):
    """Offer to clone SillyTavern into the spellcaster directory.

    Returns the install path if successful, or None.
    """
    install_dir = os.path.abspath(
        os.path.join(BUNDLE_DIR, '..', 'sillytavern'))

    print()
    print("  +--------------------------------------------------+")
    print("  |  SillyTavern not found on this system.            |")
    print("  |  SillyTavern provides the chat backend for        |")
    print("  |  the Wizard Guild's advanced features.            |")
    print("  +--------------------------------------------------+")
    print()
    print(f"  Install location: {install_dir}")
    print()

    try:
        answer = input("  Clone SillyTavern now? [Y/n] ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return None

    if answer.lower() in ('n', 'no'):
        print("  [st] Skipping SillyTavern setup.")
        return None

    # Check for git
    try:
        subprocess.run(['git', '--version'], capture_output=True, check=True)
    except (FileNotFoundError, subprocess.CalledProcessError):
        print("  [st] ERROR: git is not installed.")
        return None

    print(f"  [st] Cloning SillyTavern ({_ST_BRANCH})...")
    try:
        subprocess.run(
            ['git', 'clone', '--depth', '1', '--branch', _ST_BRANCH,
             _ST_REPO, install_dir],
            check=True,
        )
        print(f"  [st] SillyTavern installed to {install_dir}")
        return install_dir
    except subprocess.CalledProcessError as e:
        print(f"  [st] ERROR: git clone failed: {e}")
        return None


def launch_sillytavern(st_dir, verbose=True):
    """Launch SillyTavern in the background.

    Returns the Popen object, or None if launch failed.
    """
    global _st_process
    if verbose:
        print(f"  [st] Launching SillyTavern from {st_dir}")

    server_js = os.path.join(st_dir, 'server.js')
    if not os.path.isfile(server_js):
        if verbose:
            print("  [st] ERROR: server.js not found")
        return None

    # Find Node.js
    node = 'node'
    try:
        subprocess.run([node, '--version'], capture_output=True, check=True)
    except (FileNotFoundError, subprocess.CalledProcessError):
        if verbose:
            print("  [st] ERROR: Node.js not found. Install from https://nodejs.org/")
        return None

    try:
        kwargs = {}
        if sys.platform == 'win32':
            kwargs['creationflags'] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs['start_new_session'] = True

        _st_process = subprocess.Popen(
            [node, 'server.js'],
            cwd=st_dir,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            **kwargs,
        )
        if verbose:
            print(f"  [st] SillyTavern started (PID {_st_process.pid})")
        return _st_process
    except Exception as e:
        if verbose:
            print(f"  [st] ERROR launching: {e}")
        return None


# ═══════════════════════════════════════════════════════════════════════
#  Asset Generation — generate wizard avatars, background, animations
#  during first-run setup when ComfyUI is available
# ═══════════════════════════════════════════════════════════════════════

_ASSETS_VERSION_FILE = os.path.join(APP_DIR, ".guild_assets_version")


def _assets_need_generation():
    """Check if asset generation has already been completed."""
    return not os.path.exists(_ASSETS_VERSION_FILE)


def _mark_assets_generated(count):
    """Mark asset generation as complete."""
    try:
        with open(_ASSETS_VERSION_FILE, "w") as f:
            f.write(json.dumps({
                "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "avatar_count": count,
            }))
    except Exception:
        pass


def _wait_for_server(url, timeout=15):
    """Wait for the Guild server to become reachable."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            req = urllib.request.Request(
                f"{url}/api/version",
                headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=3) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


def _generate_all_assets(guild_url, comfyui_url, kobold_url=""):
    """Generate all wizard assets via the Guild server's API.

    This is called during first-run setup AFTER the server has started.
    It performs the same work as the frontend's runFirstTimeSetup() but
    server-side, so assets are ready before the browser opens.

    Sequence:
      1. Fetch character list from Guild server
      2. For each character, generate a static avatar via ComfyUI
      3. Generate the guild background
      4. (Optional) If WAN models available, generate animated avatars

    Returns the number of successfully generated assets.
    """
    print()
    print("  ╔══════════════════════════════════════════════╗")
    print("  ║   GENERATING WIZARD ASSETS                   ║")
    print("  ║   (ComfyUI detected — this only runs once)   ║")
    print("  ╚══════════════════════════════════════════════╝")
    print()

    # 1. Fetch characters
    try:
        req = urllib.request.Request(
            f"{guild_url}/api/characters",
            headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            characters = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"  [assets] Could not fetch characters: {e}")
        return 0

    print(f"  [assets] Found {len(characters)} wizards")
    generated = 0

    # 2. Generate LLM names first (if LLM is available)
    if kobold_url:
        print("  [assets] Generating wizard names via LLM...")
        try:
            req = urllib.request.Request(
                f"{kobold_url}/api/v1/model",
                headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                if resp.status == 200:
                    print("  [assets] LLM connected — generating names...")
                    for char in characters:
                        if char.get("name", "") in ("", "Unnamed Wizard"):
                            _generate_wizard_name(char, kobold_url)
        except Exception:
            print("  [assets] LLM not available — using default names")

    # 3. Generate static avatars
    print()
    for i, char in enumerate(characters):
        name = char.get("name", char["id"])
        print(f"  [assets] Generating avatar {i+1}/{len(characters)}: {name}...",
              end=" ", flush=True)
        try:
            payload = json.dumps({
                "id": char["id"],
                "comfy_url": comfyui_url,
            }).encode("utf-8")
            req = urllib.request.Request(
                f"{guild_url}/api/avatar_generate",
                data=payload,
                headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if data.get("avatar_url"):
                    char["avatar_url"] = data["avatar_url"]
                    generated += 1
                    print("OK")
                else:
                    print(f"FAIL: {data.get('error', 'no URL')}")
        except Exception as e:
            print(f"FAIL: {e}")

    # 4. Generate guild background
    print()
    print("  [assets] Generating guild background...", end=" ", flush=True)
    try:
        payload = json.dumps({
            "style": "tavern",
            "comfy_url": comfyui_url,
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{guild_url}/api/background_generate",
            data=payload,
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data.get("bg_url"):
                generated += 1
                print("OK")
            else:
                print(f"FAIL: {data.get('error', 'no URL')}")
    except Exception as e:
        print(f"FAIL: {e}")

    # 5. Queue animated avatars via ComfyUI queue (non-blocking)
    print()
    print("  [assets] Queuing animated avatars to ComfyUI...")
    queued_count = 0
    for char in characters:
        if not char.get("avatar_url"):
            continue
        try:
            payload = json.dumps({
                "id": char["id"],
                "static_avatar_url": char["avatar_url"],
                "comfy_url": comfyui_url,
            }).encode("utf-8")
            req = urllib.request.Request(
                f"{guild_url}/api/animated_avatar_queue",
                data=payload,
                headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if data.get("status") == "queued":
                    queued_count += 1
                elif data.get("status") == "unavailable":
                    print(f"  [assets] WAN not available: {data.get('reason')}")
                    break
        except Exception as e:
            print(f"  [assets] Queue failed: {e}")
            break

    if queued_count > 0:
        print(f"  [assets] {queued_count} animated avatars queued to ComfyUI.")
        print(f"  [assets] They will render in the background and appear in the browser.")
    else:
        print("  [assets] No animated avatars queued (WAN models may not be available)")

    print()
    print(f"  [assets] Asset generation complete: {generated} static assets created")
    if queued_count > 0:
        print(f"  [assets] + {queued_count} animated avatars processing in background")
    return generated


def _generate_wizard_name(char, kobold_url):
    """Generate a wizard name for a character via the LLM."""
    context = (
        f"Context: We are naming magical avatars.\n"
        f"Command: Invent a single, very short, creative fantasy name "
        f"(e.g. Zephyr) for a wizard specializing in: {char.get('subtext', 'magic')}. "
        f"Do NOT use titles like 'Master of'.\nName:"
    )
    try:
        payload = json.dumps({
            "prompt": context,
            "max_length": 15,
            "temperature": 0.8,
            "stop_sequence": ["\n", "."],
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{kobold_url}/api/v1/generate",
            data=payload,
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            name = data["results"][0]["text"].strip().replace('"', '').replace("'", "")
            if name:
                char["name"] = name
                print(f"    Named: {name} ({char.get('subtext', '')[:40]})")
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════
#  Main Entry Point
# ═══════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Wizard Guild Launcher — start the magical ComfyUI interface")
    parser.add_argument("--setup", action="store_true",
                        help="Force re-run the setup wizard")
    parser.add_argument("--port", type=int, default=None,
                        help="Override Guild server port for this session")
    parser.add_argument("--comfyui", type=str, default=None,
                        help="Override ComfyUI URL (e.g. http://192.168.x.x:8188)")
    parser.add_argument("--kobold", type=str, default=None,
                        help="Override KoboldAI/LLM URL")
    parser.add_argument("--no-browser", action="store_true",
                        help="Don't auto-open browser")
    parser.add_argument("--no-update", action="store_true",
                        help="Skip auto-update check")
    parser.add_argument("--no-assets", action="store_true",
                        help="Skip first-run asset generation")
    args = parser.parse_args()

    print()
    print("  ==========================================")
    print("  The Wizard Guild")
    print("  ==========================================")
    print()

    # ── Load or create config ────────────────────────────────────────
    if args.setup or not config_exists():
        config = run_setup_wizard(
            load_config() if config_exists() else None)
    else:
        config = load_config()

    # ── Apply CLI overrides ──────────────────────────────────────────
    port = args.port or config["guild_port"]
    comfyui_url = (args.comfyui or config["comfyui_url"]).rstrip('/')
    kobold_url = (args.kobold or config["kobold_url"]).rstrip('/')

    # ── Auto-update ──────────────────────────────────────────────────
    if config.get("auto_update", True) and not args.no_update:
        try:
            updated = check_for_updates(verbose=True)
            if updated:
                _restart_self()
                return  # Won't reach here (exec replaces process)
        except Exception as e:
            print(f"  [update] Update check failed: {e}")
            traceback.print_exc()

    # ── Kill prior instances ─────────────────────────────────────────
    if _is_port_in_use(port):
        print(f"  [server] Port {port} is in use, killing prior instance...")
        from server import _kill_prior_instances
        _kill_prior_instances(port)
        time.sleep(1)

    # ── Launch KoboldCPP (if configured) ─────────────────────────────
    if config.get("auto_launch_kobold") and config.get("koboldcpp_dir"):
        model_path = config.get("kobold_model", "")
        if model_path and os.path.isfile(model_path):
            launch_koboldcpp(config["koboldcpp_dir"], model_path,
                             port=int(kobold_url.rsplit(':', 1)[-1]),
                             verbose=True)
            time.sleep(2)

    # ── Launch SillyTavern (if configured) ───────────────────────────
    if config.get("auto_launch_st"):
        st_dir = _find_sillytavern(config.get("sillytavern_dir"))
        if st_dir:
            launch_sillytavern(st_dir, verbose=True)
        else:
            print("  [st] SillyTavern not found, skipping auto-launch")

    # ── Configure and start server module ────────────────────────────
    import server
    server.PORT = port
    server.COMFYUI_URL = comfyui_url
    server.KOBOLD_URL = kobold_url

    guild_url = f"http://127.0.0.1:{port}"

    # ── Check ComfyUI connectivity ───────────────────────────────────
    comfy_alive = _test_endpoint(comfyui_url, "system_stats")
    if comfy_alive:
        print(f"  [server] ComfyUI connected at {comfyui_url}")
    else:
        print(f"  [server] ComfyUI not reachable at {comfyui_url}")
        print(f"  [server] (Assets will be generated when ComfyUI comes online)")

    # ── Start the HTTP server in a background thread ─────────────────
    print(f"  [server] Starting Wizard Guild on port {port}...")
    httpd = server.HTTPServer(('0.0.0.0', port), server.GuildHandler)
    httpd.directory = os.path.join(APP_DIR, 'static')

    server_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    server_thread.start()

    # Wait for server to accept connections
    if not _wait_for_server(guild_url, timeout=10):
        print("  [server] WARNING: Server may not have started correctly")
    else:
        print(f"  [server] Wizard Guild is live at {guild_url}")

    # ── First-run asset generation (ComfyUI + LLM detected) ─────────
    if (comfy_alive and _assets_need_generation()
            and not args.no_assets):
        asset_count = _generate_all_assets(guild_url, comfyui_url, kobold_url)
        if asset_count > 0:
            _mark_assets_generated(asset_count)
            print("  [assets] Assets saved. The browser will load them automatically.")
    elif not _assets_need_generation():
        print("  [assets] Assets already generated (delete .guild_assets_version to regenerate)")

    # ── Open browser ─────────────────────────────────────────────────
    if config.get("auto_open_browser", True) and not args.no_browser:
        import webbrowser
        print(f"  [server] Opening browser: {guild_url}")
        webbrowser.open(guild_url)

    # ── Keep running until Ctrl+C ────────────────────────────────────
    print()
    print("  Press Ctrl+C to stop the server.")
    print()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n  [server] Shutting down...")
        httpd.shutdown()
        # Cleanup child processes
        if _kobold_process and _kobold_process.poll() is None:
            print("  [kobold] Stopping KoboldCPP...")
            _kobold_process.terminate()
        if _st_process and _st_process.poll() is None:
            print("  [st] Stopping SillyTavern...")
            _st_process.terminate()
        print("  [server] Goodbye!")


if __name__ == "__main__":
    main()