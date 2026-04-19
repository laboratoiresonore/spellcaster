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
    python guild_launcher.py --comfyui http://127.0.0.1:8188

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

# ── Shared constants & helpers (single source of truth) ──────────────
from guild_common import (
    DEFAULT_GUILD_PORT, DEFAULT_COMFYUI_URL, DEFAULT_KOBOLD_URL,
    DEFAULT_HORDE_URL, HORDE_ANONYMOUS_KEY,
    is_port_in_use, test_endpoint,
)

# ═══════════════════════════════════════════════════════════════════════
#  Auto-Update Configuration
# ═══════════════════════════════════════════════════════════════════════
# These are patched by build_nsfw.py for the NSFW edition.
# SFW defaults are the public repo; NSFW overrides point to the private
# repo with an embedded auth token.

_GUILD_REPO = "laboratoiresonore/spellcaster"
_GUILD_BRANCH = "main"
_GUILD_AUTH_TOKEN = ""  # empty for SFW (public); PAT for NSFW (private)

# ── Runtime NSFW detection ──
# If running from source (not a patched build), check for nsfw/.github_token
# which indicates the NSFW build artifacts are installed alongside the source.
if not _GUILD_AUTH_TOKEN:
    _nsfw_token_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                     '..', 'nsfw', '.github_token')
    if os.path.isfile(_nsfw_token_path):
        try:
            with open(_nsfw_token_path, 'r') as _tf:
                _runtime_token = _tf.read().strip()
            if _runtime_token:
                _GUILD_AUTH_TOKEN = _runtime_token
                _GUILD_REPO = "laboratoiresonore/spellcaster_NSFW"
                print(f"  [Guild] NSFW token detected from nsfw/.github_token — switching to NSFW edition")
        except Exception:
            pass

# Prefixes within the repo that belong to the Guild
_TAVERN_PREFIX = "tavern/"
_SCAFFOLD_PREFIX = "scaffold/"

# GitHub API URLs (constructed from repo — re-computed after NSFW detection)
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
    "guild_port": DEFAULT_GUILD_PORT,
    "comfyui_url": DEFAULT_COMFYUI_URL,
    "kobold_url": DEFAULT_KOBOLD_URL,
    "sillytavern_dir": "",
    "koboldcpp_dir": "",
    "kobold_model": "",
    "auto_open_browser": True,
    "auto_update": True,
    "auto_launch_st": True,
    "auto_launch_kobold": False,
    "privacy_cleanup": True,
    "llm_mode": "local",           # "local" (KoboldAI) or "horde" (AI Horde)
    "horde_api_key": "",           # AI Horde API key (empty = anonymous)
    "horde_model": "",             # Preferred Horde model (empty = any)
    "prompt_enhance": True,        # LLM-based prompt enhancement before ComfyUI
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


_test_endpoint = test_endpoint  # alias — canonical def in guild_common


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

    # ── 3. LLM Backend ──────────────────────────────────────────────
    print()
    print("  ── LLM Backend (for wizard chat) ────────────────")
    print("    Choose how wizards talk:")
    print()
    print("    [1] Local LLM  — KoboldCPP, Ollama, text-gen-webui, etc.")
    print("                     Fast, private, runs on YOUR machine.")
    print()
    print("    [2] AI Horde   — Free cloud LLM via crowdsourced workers.")
    print("                     No GPU needed.  ZERO privacy (see below).")
    print()
    llm_choice = ""
    while llm_choice not in ("1", "2"):
        llm_choice = input("    Choose [1/2]: ").strip()

    if llm_choice == "2":
        # ── AI Horde ──
        config["llm_mode"] = "horde"
        print()
        print("  " + "=" * 56)
        print("  ⚠  WARNING — AI HORDE HAS ZERO PRIVACY  ⚠")
        print("  " + "=" * 56)
        print("  Your prompts are sent to VOLUNTEER worker machines.")
        print("  Volunteers can see every prompt and every response.")
        print("  There is NO encryption, NO anonymity, NO guarantees.")
        print("  Do NOT send personal data, passwords, or secrets.")
        print("  " + "=" * 56)
        print()
        confirm = input("    Type YES to accept the risk: ").strip()
        if confirm.upper() != "YES":
            print("    Aborting — switching to local LLM mode.")
            config["llm_mode"] = "local"
        else:
            print()
            print("    API key (press Enter for anonymous / no account):")
            horde_key = input("    Horde API key: ").strip()
            config["horde_api_key"] = horde_key
            print("    AI Horde configured.  Wizard chat will use the Horde.")

    if config.get("llm_mode") != "horde":
        # ── Local LLM (original flow) ──
        config["llm_mode"] = "local"
        print()
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
    config["privacy_cleanup"] = _input_yes_no(
        "Privacy mode? (auto-delete inputs & outputs from ComfyUI after delivery)",
        config.get("privacy_cleanup", True))

    # ── Create creations/ folder for all generated outputs ────────────
    creations_dir = os.path.join(APP_DIR, "creations")
    os.makedirs(creations_dir, exist_ok=True)

    # ── Save ──────────────────────────────────────────────────────────
    print()
    save_config(config)
    print(f"  Configuration saved to: {_CONFIG_FILE}")
    print(f"  Creations folder: {creations_dir}")
    print("  All generated images and videos will be saved in creations/")
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


def _apply_staged_updates(verbose=True):
    """Apply any .update files staged by a previous auto-update.

    On Windows, a running .py file cannot be replaced while the process has it
    loaded. The auto-updater writes the new version as 'filename.update' instead.
    This function (called before the updater runs) detects those staged files
    and performs the replacement before the old code is imported.
    """
    if getattr(sys, 'frozen', False):
        write_base = APP_DIR
    else:
        write_base = os.path.dirname(BUNDLE_DIR)
    applied = 0
    for prefix in (_TAVERN_PREFIX, _SCAFFOLD_PREFIX):
        prefix_dir = os.path.join(write_base, prefix)
        if not os.path.isdir(prefix_dir):
            continue
        for dirpath, _dirs, filenames in os.walk(prefix_dir):
            for fn in filenames:
                if fn.endswith('.update'):
                    staged = os.path.join(dirpath, fn)
                    target = staged[:-7]  # strip .update suffix
                    try:
                        if os.path.exists(target):
                            os.remove(target)
                        os.rename(staged, target)
                        applied += 1
                    except Exception:
                        # Retry with copy+delete (more robust on Windows)
                        try:
                            import shutil
                            shutil.copy2(staged, target)
                            os.remove(staged)
                            applied += 1
                        except Exception:
                            pass
    if applied and verbose:
        print(f"  [update] Applied {applied} staged update(s) from previous run")
    # Purge __pycache__ so Python uses fresh bytecode
    if applied:
        for prefix in (_TAVERN_PREFIX, _SCAFFOLD_PREFIX):
            prefix_dir = os.path.join(write_base, prefix)
            if not os.path.isdir(prefix_dir):
                continue
            for dirpath, dirs, _files in os.walk(prefix_dir):
                if "__pycache__" in dirs:
                    import shutil
                    try:
                        shutil.rmtree(os.path.join(dirpath, "__pycache__"))
                    except Exception:
                        pass


def check_for_updates(verbose=True):
    """Check GitHub for a newer commit and apply updates if available.

    Returns True if an update was applied (caller should restart).
    Returns False if already up to date or if the check failed.

    Shared primitives (SHA fetch, SHA compare, tree walk) live in
    spellcaster_core.auto_updater. This function keeps the Guild-specific
    logic: tavern/scaffold filter, frozen-vs-source write base, live
    replace with PermissionError fallback.
    """
    try:
        from spellcaster_core import auto_updater as _au
    except ImportError:
        _au = None

    hdrs = _guild_headers()
    local_sha = _read_local_sha()

    if verbose:
        edition = "NSFW" if _GUILD_AUTH_TOKEN else "SFW"
        print(f"  [update] Checking for updates ({edition} edition)...")
        if local_sha:
            print(f"  [update] Local version: {local_sha[:7]}")

    # Step 1: Get latest commit SHA (shared primitive)
    try:
        if _au is not None:
            latest_sha = _au.fetch_latest_sha(_GUILD_COMMITS_URL, hdrs, timeout=10)
        else:
            req = urllib.request.Request(_GUILD_COMMITS_URL, headers=hdrs)
            with urllib.request.urlopen(req, timeout=10) as r:
                commits = json.loads(r.read())
                latest_sha = commits[0]["sha"]
    except Exception as e:
        if verbose:
            print(f"  [update] Could not reach GitHub: {e}")
        return False

    # Step 2: Compare (shared primitive)
    if _au is not None:
        if _au.shas_match(latest_sha, local_sha):
            if verbose:
                print(f"  [update] Already up to date ({latest_sha[:7]})")
            return False
    else:
        if latest_sha == local_sha or latest_sha[:7] == local_sha[:7]:
            if verbose:
                print(f"  [update] Already up to date ({latest_sha[:7]})")
            return False

    if verbose:
        print(f"  [update] New version available: {latest_sha[:7]}")

    # Step 3: Fetch full repo tree (shared primitive)
    try:
        if _au is not None:
            tree = {"tree": _au.fetch_tree(_GUILD_TREE_URL, hdrs, timeout=20)}
        else:
            req = urllib.request.Request(_GUILD_TREE_URL, headers=hdrs)
            with urllib.request.urlopen(req, timeout=20) as r:
                tree = json.loads(r.read())
    except Exception as e:
        if verbose:
            print(f"  [update] Could not fetch file tree: {e}")
        return False

    # Step 4: Filter for tavern/ and scaffold/ files
    # Protected files: user config and self — everything else auto-updates.
    # Frontend files (app.js, style.css, index.html) MUST auto-update to
    # receive bug fixes. The launcher and config are the only truly local files.
    _PROTECTED_FILES = {
        "tavern/guild_launcher.py",      # This file — never overwrite self
        "tavern/guild_config.json",      # User configuration
        "tavern/guild_common.py",        # Local arch rules & user customisations
    }
    remote_files = []  # list of (path, expected_size)
    skipped = 0
    for item in tree.get("tree", []):
        if item["type"] != "blob":
            continue
        path = item["path"]
        if path in _PROTECTED_FILES:
            skipped += 1
            continue
        if path.startswith(_TAVERN_PREFIX) or path.startswith(_SCAFFOLD_PREFIX):
            remote_files.append((path, item.get("size", 0)))
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

    for rel_path, expected_size in remote_files:
        try:
            url = f"{_GUILD_RAW_BASE}/{rel_path}"
            dest = os.path.join(write_base, rel_path)
            os.makedirs(os.path.dirname(dest), exist_ok=True)

            req = urllib.request.Request(url, headers=hdrs)
            with urllib.request.urlopen(req, timeout=30) as r2:
                blob = r2.read()

            # ── Integrity check: reject incomplete downloads ──
            # GitHub tree API provides exact blob sizes.  If the
            # download is short the connection was likely dropped.
            if expected_size > 0 and len(blob) != expected_size:
                raise IOError(
                    f"Incomplete download: got {len(blob)} bytes, "
                    f"expected {expected_size}")

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

    # Step 5b: Remove local files that no longer exist in the repo
    remote_rel_set = {rp for rp, _ in remote_files}
    remote_rel_set.update(_PROTECTED_FILES)
    stale_removed = 0
    for prefix in (_TAVERN_PREFIX, _SCAFFOLD_PREFIX):
        prefix_dir = os.path.join(write_base, prefix)
        if not os.path.isdir(prefix_dir):
            continue
        for dirpath, _dirs, filenames in os.walk(prefix_dir):
            for fn in filenames:
                if fn.endswith(('.pyc', '.update', '.tmp')):
                    continue
                full = os.path.join(dirpath, fn)
                rel = os.path.relpath(full, write_base).replace("\\", "/")
                if rel not in remote_rel_set:
                    try:
                        os.remove(full)
                        stale_removed += 1
                    except Exception:
                        pass
    if stale_removed and verbose:
        print(f"  [update] Removed {stale_removed} stale file(s)")

    # Step 5c: Purge __pycache__ to prevent stale bytecode
    for prefix in (_TAVERN_PREFIX, _SCAFFOLD_PREFIX):
        prefix_dir = os.path.join(write_base, prefix)
        if not os.path.isdir(prefix_dir):
            continue
        for dirpath, dirs, _files in os.walk(prefix_dir):
            if "__pycache__" in dirs:
                import shutil
                try:
                    shutil.rmtree(os.path.join(dirpath, "__pycache__"))
                except Exception:
                    pass

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


_is_port_in_use = is_port_in_use  # alias — canonical def in guild_common


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

# Search paths: relatives of this file, then common user install locations
_home = os.path.expanduser("~")
_ST_SEARCH_PATHS = [
    # ── Relative to this file (tavern/) — whimweaver project layout ──
    os.path.join(BUNDLE_DIR, '..', '..', 'whimweaver-st'),        # spellcaster sibling
    os.path.join(BUNDLE_DIR, '..', '..', '..', 'whimweaver-st'),  # parent sibling
    os.path.join(BUNDLE_DIR, '..', 'sillytavern'),                 # inside spellcaster
    os.path.join(BUNDLE_DIR, 'sillytavern'),                       # inside tavern
    # ── Common user install locations ──
    os.path.join(_home, "SillyTavern"),
    os.path.join(_home, "Documents", "SillyTavern"),
    os.path.join(_home, "Documents", "GitHub", "SillyTavern"),     # GitHub Desktop default
    os.path.join(_home, "Desktop", "SillyTavern"),
    os.path.join(_home, "Documents", "AI", "SillyTavern"),
    # ── SillyTavern-Launcher puts ST inside its own dir ──
    os.path.join(_home, "SillyTavern-Launcher", "SillyTavern"),
    os.path.join(_home, "Documents", "SillyTavern-Launcher", "SillyTavern"),
    os.path.join(_home, "Desktop", "SillyTavern-Launcher", "SillyTavern"),
]
# Windows-specific paths (C:\AI\SillyTavern is the community convention)
if os.name == "nt":
    for _drv in ["C:\\", "D:\\", "E:\\"]:
        _ST_SEARCH_PATHS += [
            os.path.join(_drv, "AI", "SillyTavern"),
            os.path.join(_drv, "AI", "SillyTavern-Launcher", "SillyTavern"),
            os.path.join(_drv, "SillyTavern"),
        ]
    # Also check Downloads (users sometimes clone there)
    _ST_SEARCH_PATHS.append(os.path.join(_home, "Downloads", "SillyTavern"))

_st_process = None  # Global ref so we can clean up on exit


def _repair_gimp_plugin():
    """Sync the GIMP plugin from this repo into GIMP's plug-ins directory.

    Copies all .py files from plugins/gimp/comfyui-connector/ into
    %APPDATA%/GIMP/<version>/plug-ins/comfyui-connector/.
    Also invalidates GIMP's pluginrc cache so it re-scans on next launch.

    Safe to call every startup — only copies if files differ.
    """
    import platform
    plugin_src = os.path.join(os.path.dirname(BUNDLE_DIR),
                              'plugins', 'gimp', 'comfyui-connector')
    if not os.path.isdir(plugin_src):
        return  # No plugin source available (packaged build uses different path)

    # Find GIMP plug-ins directory
    if platform.system() == "Windows":
        appdata = os.environ.get("APPDATA", "")
        gimp_base = os.path.join(appdata, "GIMP")
    elif platform.system() == "Darwin":
        gimp_base = os.path.expanduser("~/Library/Application Support/GIMP")
    else:
        gimp_base = os.path.expanduser("~/.config/GIMP")

    if not os.path.isdir(gimp_base):
        return  # GIMP not installed

    # Find the highest GIMP version directory (3.2 > 3.0 > 2.10)
    gimp_dirs = []
    try:
        for d in sorted(os.listdir(gimp_base), reverse=True):
            plug_dir = os.path.join(gimp_base, d, "plug-ins")
            if os.path.isdir(plug_dir):
                gimp_dirs.append(plug_dir)
    except OSError:
        return

    if not gimp_dirs:
        return

    # Also locate spellcaster_core/ (canonical source for shim imports)
    core_src = os.path.join(os.path.dirname(BUNDLE_DIR),
                            'comfyui-spellcaster', 'spellcaster_core')
    if not os.path.isdir(core_src):
        # Fallback: might be bundled alongside plugins
        core_src = os.path.join(plugin_src, 'spellcaster_core')

    import shutil

    # Sync files to each GIMP version that has a plug-ins directory
    for plug_dir in gimp_dirs:
        dest_dir = os.path.join(plug_dir, "comfyui-connector")
        os.makedirs(dest_dir, exist_ok=True)

        updated = 0
        for fname in os.listdir(plugin_src):
            src_path = os.path.join(plugin_src, fname)
            if not os.path.isfile(src_path):
                continue
            if fname in ("config.json", "session_state.json"):
                continue
            dest_path = os.path.join(dest_dir, fname)

            try:
                if os.path.isfile(dest_path):
                    src_size = os.path.getsize(src_path)
                    dest_size = os.path.getsize(dest_path)
                    if src_size == dest_size:
                        continue
            except OSError:
                pass

            try:
                shutil.copy2(src_path, dest_path)
                updated += 1
            except Exception as e:
                print(f"  [gimp] WARNING: Failed to copy {fname}: {e}")

        # Sync spellcaster_core/ directory (required by shim imports)
        # GIMP holds Windows file locks on plug-in files while it's running,
        # so a wholesale rmtree+copytree fails with WinError 5. Try a few
        # gentler strategies before giving up:
        #   1. per-file copy (skip locked individual files; leaves the
        #      rest of the package fresh enough for the user to keep going)
        #   2. retry with a short backoff (catches transient AV scans)
        #   3. final fallback: print a friendly notice telling the user
        #      to close GIMP and rerun the launcher.
        if os.path.isdir(core_src):
            dest_core = os.path.join(dest_dir, "spellcaster_core")
            copied_core = False
            try:
                if os.path.isdir(dest_core):
                    try:
                        shutil.rmtree(dest_core)
                    except Exception:
                        pass  # fall through to per-file copy
                shutil.copytree(core_src, dest_core)
                copied_core = True
                updated += 1
            except Exception:
                # Per-file fallback — skip whichever files GIMP has locked.
                try:
                    os.makedirs(dest_core, exist_ok=True)
                    locked = 0
                    copied = 0
                    for root, dirs, files in os.walk(core_src):
                        rel = os.path.relpath(root, core_src)
                        out_dir = (os.path.join(dest_core, rel)
                                   if rel != "." else dest_core)
                        os.makedirs(out_dir, exist_ok=True)
                        for fn in files:
                            sp = os.path.join(root, fn)
                            dp = os.path.join(out_dir, fn)
                            try:
                                shutil.copy2(sp, dp)
                                copied += 1
                            except Exception:
                                locked += 1
                    if copied > 0:
                        copied_core = True
                        updated += 1
                    if locked > 0:
                        print(f"  [gimp] spellcaster_core: copied {copied} file(s), "
                              f"{locked} locked by running GIMP — close GIMP and "
                              f"rerun the launcher to update them.")
                except Exception as e2:
                    print(f"  [gimp] spellcaster_core update failed: {e2}")
                    print(f"  [gimp]   Close GIMP and rerun the launcher to retry.")
            if not copied_core:
                pass  # message already printed above

        if updated > 0:
            print(f"  [gimp] Updated {updated} file(s) in {dest_dir}")
            # Invalidate pluginrc cache so GIMP re-scans procedures
            _invalidate_gimp_pluginrc(os.path.dirname(os.path.dirname(dest_dir)))


def _invalidate_gimp_pluginrc(gimp_version_dir):
    """Delete GIMP's pluginrc cache to force procedure re-scan."""
    for name in ("pluginrc", "pluginrc.d"):
        rc = os.path.join(gimp_version_dir, name)
        try:
            if os.path.isfile(rc):
                os.unlink(rc)
                print(f"  [gimp] Deleted {name} cache (GIMP will re-scan)")
            elif os.path.isdir(rc):
                import shutil
                shutil.rmtree(rc)
                print(f"  [gimp] Deleted {name} cache dir (GIMP will re-scan)")
        except Exception:
            pass


def _patch_st_with_spellcaster(st_dir):
    """Install Spellcaster plugin into a SillyTavern directory.

    Copies server plugin + UI extension. Safe to call multiple times.
    """
    st_path = os.path.abspath(st_dir)
    print(f"  [st] Installing Spellcaster plugin into SillyTavern...")

    # Find plugin source
    plugin_src = os.path.join(BUNDLE_DIR, '..', 'plugins', 'sillytavern', 'spellcaster-st')
    if not os.path.isdir(plugin_src):
        # Try relative to tavern/
        plugin_src = os.path.join(os.path.dirname(BUNDLE_DIR), 'plugins', 'sillytavern', 'spellcaster-st')
    if not os.path.isdir(plugin_src):
        print(f"  [st] WARNING: Spellcaster ST plugin source not found, skipping patch")
        return

    import shutil

    # Server plugin -> ST/plugins/spellcaster/
    server_dest = os.path.join(st_path, 'plugins', 'spellcaster')
    os.makedirs(server_dest, exist_ok=True)
    src_js = os.path.join(plugin_src, 'server-plugin.js')
    if os.path.isfile(src_js):
        shutil.copy2(src_js, os.path.join(server_dest, 'index.js'))
    # Package.json for ESM
    pkg = {
        "name": "spellcaster", "version": "2.0.0",
        "main": "index.js", "type": "module",
        "description": "Spellcaster ComfyUI integration",
        "author": "Laboratoire Sonore", "license": "GPL-2.0",
    }
    with open(os.path.join(server_dest, 'package.json'), 'w') as f:
        json.dump(pkg, f, indent=4)

    # UI extension -> ST/data/default-user/extensions/spellcaster-st/
    ui_dest = os.path.join(st_path, 'data', 'default-user', 'extensions', 'spellcaster-st')
    os.makedirs(ui_dest, exist_ok=True)
    for fname in ['index.js', 'manifest.json', 'styles.css']:
        src = os.path.join(plugin_src, fname)
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(ui_dest, fname))

    # Ensure server plugins are enabled in config.yaml
    config_path = os.path.join(st_path, 'config.yaml')
    if os.path.isfile(config_path):
        content = open(config_path, 'r', encoding='utf-8').read()
        if 'enableServerPlugins: false' in content:
            content = content.replace('enableServerPlugins: false', 'enableServerPlugins: true')
            open(config_path, 'w', encoding='utf-8').write(content)
            print(f"  [st] Enabled server plugins in config.yaml")

    # Auto-import character cards (13 Spellcaster wizards)
    chars_src = os.path.join(BUNDLE_DIR, 'characters')
    if not os.path.isdir(chars_src):
        chars_src = os.path.join(os.path.dirname(BUNDLE_DIR), 'tavern', 'characters')
    chars_dest = os.path.join(st_path, 'data', 'default-user', 'characters')
    if os.path.isdir(chars_src) and os.path.isdir(chars_dest):
        imported = 0
        for fname in os.listdir(chars_src):
            # Copy both JSON cards and PNG avatars
            if not (fname.endswith('.json') or fname.endswith('.png')):
                continue
            src = os.path.join(chars_src, fname)
            dest = os.path.join(chars_dest, fname)
            if not os.path.isfile(dest):
                shutil.copy2(src, dest)
                if fname.endswith('.json'):
                    imported += 1
        if imported:
            print(f"  [st] Imported {imported} Spellcaster character card(s)")
    else:
        if not os.path.isdir(chars_src):
            print(f"  [st] Character cards source not found, skipping import")

    print(f"  [st] Spellcaster plugin installed into SillyTavern")


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
        # Auto-install Spellcaster plugin into the fresh ST
        _patch_st_with_spellcaster(install_dir)
        return install_dir
    except subprocess.CalledProcessError as e:
        print(f"  [st] ERROR: git clone failed: {e}")
        return None


def _find_node():
    """Find Node.js executable path, auto-installing if missing.

    Returns the path to 'node' (or 'node.exe') or None.
    """
    # 1) Already on PATH?
    node = 'node'
    try:
        r = subprocess.run([node, '--version'], capture_output=True, check=True)
        print(f"  [deps] Node.js found: {r.stdout.decode().strip()}")
        return node
    except (FileNotFoundError, subprocess.CalledProcessError):
        pass

    # 2) Windows: check common install locations
    if sys.platform == 'win32':
        for candidate in [
            os.path.expandvars(r'%ProgramFiles%\nodejs\node.exe'),
            os.path.expandvars(r'%ProgramFiles(x86)%\nodejs\node.exe'),
            os.path.expandvars(r'%APPDATA%\..\Local\Programs\nodejs\node.exe'),
            os.path.expandvars(r'%LOCALAPPDATA%\Programs\nodejs\node.exe'),
        ]:
            if os.path.isfile(candidate):
                print(f"  [deps] Node.js found at {candidate}")
                return candidate

    # 3) Try to auto-install
    print("  [deps] Node.js not found — attempting auto-install...")
    if sys.platform == 'win32':
        return _install_node_windows()
    else:
        return _install_node_unix()


def _install_node_windows():
    """Install Node.js on Windows via winget, then fallback to direct download."""
    # Try winget first (available on Windows 10 1709+)
    try:
        print("  [deps] Trying: winget install OpenJS.NodeJS.LTS ...")
        subprocess.run(
            ['winget', 'install', '--id', 'OpenJS.NodeJS.LTS',
             '--accept-source-agreements', '--accept-package-agreements',
             '-e', '--silent'],
            check=True, timeout=300)
        # winget installs to PATH but current process doesn't see it yet
        # Check the standard location
        prog = os.path.expandvars(r'%ProgramFiles%\nodejs\node.exe')
        if os.path.isfile(prog):
            print(f"  [deps] Node.js installed via winget at {prog}")
            return prog
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        print(f"  [deps] winget install failed ({e}), trying direct download...")

    # Fallback: download the MSI and run it silently
    import tempfile
    node_ver = 'v22.15.0'
    arch = 'x64' if sys.maxsize > 2**32 else 'x86'
    msi_url = f'https://nodejs.org/dist/{node_ver}/node-{node_ver}-{arch}.msi'
    msi_path = os.path.join(tempfile.gettempdir(), f'node-{node_ver}-{arch}.msi')

    try:
        print(f"  [deps] Downloading Node.js {node_ver} from nodejs.org ...")
        urllib.request.urlretrieve(msi_url, msi_path)
        print(f"  [deps] Installing Node.js (silent MSI) ...")
        subprocess.run(
            ['msiexec', '/i', msi_path, '/qn', '/norestart'],
            check=True, timeout=300)
        prog = os.path.expandvars(r'%ProgramFiles%\nodejs\node.exe')
        if os.path.isfile(prog):
            print(f"  [deps] Node.js installed at {prog}")
            return prog
    except Exception as e:
        print(f"  [deps] MSI install failed: {e}")

    print("  [deps] Could not auto-install Node.js.")
    print("  [deps] Please install manually from https://nodejs.org/")
    return None


def _install_node_unix():
    """Install Node.js on Linux/macOS via package manager."""
    managers = [
        # Ubuntu/Debian
        (['sudo', 'apt-get', 'install', '-y', 'nodejs', 'npm'], 'apt'),
        # macOS Homebrew
        (['brew', 'install', 'node'], 'brew'),
        # Fedora/RHEL
        (['sudo', 'dnf', 'install', '-y', 'nodejs'], 'dnf'),
    ]
    for cmd, name in managers:
        try:
            # Check if the package manager exists first
            subprocess.run([cmd[0] if name != 'apt' else 'apt-get',
                            '--version'],
                           capture_output=True, check=True)
        except (FileNotFoundError, subprocess.CalledProcessError):
            continue

        try:
            print(f"  [deps] Installing Node.js via {name}...")
            subprocess.run(cmd, check=True, timeout=120)
            # Verify
            r = subprocess.run(['node', '--version'], capture_output=True)
            if r.returncode == 0:
                print(f"  [deps] Node.js installed: {r.stdout.decode().strip()}")
                return 'node'
        except Exception as e:
            print(f"  [deps] {name} install failed: {e}")

    print("  [deps] Could not auto-install Node.js.")
    print("  [deps] Please install manually from https://nodejs.org/")
    return None


def _ensure_npm_install(st_dir, node='node', verbose=True):
    """Run npm install in the SillyTavern directory if node_modules is missing or stale."""
    nm_dir = os.path.join(st_dir, 'node_modules')
    pkg_json = os.path.join(st_dir, 'package.json')
    pkg_lock = os.path.join(st_dir, 'package-lock.json')

    need_install = False
    if not os.path.isdir(nm_dir):
        if verbose:
            print("  [st] node_modules not found — running npm install...")
        need_install = True
    elif os.path.isfile(pkg_lock):
        # Re-install if package-lock.json is newer than node_modules
        lock_mtime = os.path.getmtime(pkg_lock)
        nm_mtime = os.path.getmtime(nm_dir)
        if lock_mtime > nm_mtime:
            if verbose:
                print("  [st] package-lock.json updated — running npm install...")
            need_install = True

    if not need_install:
        return True

    # Determine npm path — on Windows, npm might be a .cmd next to node
    npm = 'npm'
    if sys.platform == 'win32' and node != 'node':
        node_dir = os.path.dirname(node)
        npm_cmd = os.path.join(node_dir, 'npm.cmd')
        if os.path.isfile(npm_cmd):
            npm = npm_cmd

    try:
        if verbose:
            print(f"  [st] Running npm install in {st_dir} ...")
        subprocess.run(
            [npm, 'install', '--no-audit', '--no-fund'],
            cwd=st_dir, check=True, timeout=300)
        if verbose:
            print("  [st] npm install completed successfully")
        return True
    except subprocess.TimeoutExpired:
        if verbose:
            print("  [st] npm install timed out (5 min) — try running it manually")
        return False
    except Exception as e:
        if verbose:
            print(f"  [st] npm install failed: {e}")
        return False


def launch_sillytavern(st_dir, verbose=True):
    """Launch SillyTavern in the background.

    Auto-installs Node.js if missing, runs npm install if needed.
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

    # Find or install Node.js
    node = _find_node()
    if not node:
        return None

    # Ensure npm dependencies are installed
    if not _ensure_npm_install(st_dir, node=node, verbose=verbose):
        if verbose:
            print("  [st] WARNING: npm install failed, trying to launch anyway...")

    try:
        kwargs = {}
        if sys.platform == 'win32':
            kwargs['creationflags'] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs['start_new_session'] = True

        env = os.environ.copy()
        env['DISABLE_AUTORUN'] = 'true'  # Prevent ST from opening its own browser tab
        _st_process = subprocess.Popen(
            [node, 'server.js', '--autorun', 'false'],
            cwd=st_dir,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env,
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

# Asset tracking — uses the SAME file as server.py's _ASSETS_PATH
# so both launcher and server agree on whether assets exist.
_ASSETS_VERSION_FILE_LEGACY = os.path.join(APP_DIR, ".guild_assets_version")
_STATE_DIR = os.path.join(APP_DIR, ".guild_state")
_ASSETS_VERSION_FILE = os.path.join(_STATE_DIR, "generated_assets.json")


def _assets_need_generation():
    """Check if asset generation has already been completed.

    Returns True if EITHER:
      - no marker file exists (fresh install), OR
      - the marker file exists but at least one wizard in CHARS_CACHE
        is still missing an avatar (restart-after-interrupt recovery).

    The second case fires when the user closed the server mid-setup:
    the persistent marker says "done" but generated_assets.json is
    missing entries. We trigger setup again and the background worker's
    skip_existing flag ensures only the missing wizards get generated.
    """
    if not os.path.exists(_ASSETS_VERSION_FILE) and not os.path.exists(_ASSETS_VERSION_FILE_LEGACY):
        return True  # fresh install
    # Marker exists — peek into the persistent generated-assets store
    # and see if any wizard in CHARS_CACHE lacks an avatar.
    try:
        import server  # already imported in main(), this is a re-import
        chars = getattr(server, "CHARS_CACHE", []) or []
        gen_assets = getattr(server, "_GENERATED_ASSETS", {}) or {}
        if not chars:
            return False  # nothing to compare against, trust the marker
        for c in chars:
            cid = c.get("id")
            if cid and not gen_assets.get(cid, {}).get("avatar_url"):
                return True  # missing portrait — re-trigger setup
    except Exception:
        pass
    return False


def _mark_assets_generated(count):
    """Mark asset generation as complete (in the shared .guild_state/ dir)."""
    try:
        os.makedirs(_STATE_DIR, exist_ok=True)
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
    print("  [assets] Generating wizard names via LLM...")
    for char in characters:
        if char.get("name", "") in ("", "Unnamed Wizard"):
            _generate_wizard_name(char, comfyui_url, kobold_url)

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


def _generate_wizard_name(char, comfyui_url, kobold_url=""):
    """Generate a wizard name for a character via the shared LLM stack.

    Uses guild_llm.chat() which tries ComfyUI LLM nodes first, then
    KoboldCpp, then Ollama.

    In NSFW mode, uses a flirtier, more suggestive naming prompt
    (populated by build_nsfw.py into server._NSFW_NAME_GEN_PROMPT).
    """
    import server as _srv
    if getattr(_srv, 'NSFW_MODE', False) and getattr(_srv, '_NSFW_NAME_GEN_PROMPT', ''):
        prompt = _srv._NSFW_NAME_GEN_PROMPT.format(
            subtext=char.get('subtext', 'magic'))
        system = ""
    else:
        system = (
            "You name magical avatars. Reply with ONLY a single short "
            "creative fantasy name (e.g. Zephyr). No titles, no explanation."
        )
        prompt = f"Invent a name for a wizard specializing in: {char.get('subtext', 'magic')}"

    try:
        from spellcaster_core.guild_llm import chat
        result = chat(
            prompt, system_prompt=system,
            server=comfyui_url,
            kobold_url=kobold_url or None,
            max_tokens=15, temperature=0.8)
        if result:
            name = result.strip().split("\n")[0].strip().replace('"', '').replace("'", "")
            if name and len(name) < 40:
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
                        help="Override ComfyUI URL (e.g. http://127.0.0.1:8188)")
    parser.add_argument("--kobold", type=str, default=None,
                        help="Override KoboldAI/LLM URL")
    parser.add_argument("--no-browser", action="store_true",
                        help="Don't auto-open browser")
    parser.add_argument("--no-update", action="store_true",
                        help="Skip auto-update check")
    parser.add_argument("--no-assets", action="store_true",
                        help="Skip first-run asset generation")
    parser.add_argument("--no-tray", action="store_true",
                        help="Run in console mode instead of spawning a "
                              "tray icon (Ctrl-C exits the server).")
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

    # ── Apply staged updates from previous run ────────────────────────
    try:
        _apply_staged_updates(verbose=True)
    except Exception:
        pass  # never block startup

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
            # Ensure Spellcaster plugin is installed (idempotent)
            plugin_check = os.path.join(st_dir, 'plugins', 'spellcaster', 'index.js')
            if not os.path.isfile(plugin_check):
                _patch_st_with_spellcaster(st_dir)
            launch_sillytavern(st_dir, verbose=True)
        else:
            print("  [st] SillyTavern not found, skipping auto-launch")

    # ── Repair GIMP plugin (sync from repo) ───────────────────────────
    try:
        _repair_gimp_plugin()
    except Exception as e:
        print(f"  [gimp] WARNING: Plugin repair failed: {e}")

    # ── Configure and start server module ────────────────────────────
    import server
    server.PORT = port
    server.COMFYUI_URL = comfyui_url
    server.KOBOLD_URL = kobold_url
    server.PRIVACY_CLEANUP = config.get("privacy_cleanup", True)
    server.LLM_MODE = config.get("llm_mode", "local")
    server.HORDE_API_KEY = config.get("horde_api_key", "")
    server.HORDE_MODEL = config.get("horde_model", "")
    server.PROMPT_ENHANCE = config.get("prompt_enhance", True)
    server.NSFW_MODE = bool(_GUILD_AUTH_TOKEN)

    # ── Setup mode — drives /static/setup.html + /api/setup/* endpoints ──
    server.SETUP_MODE = bool(config.get("setup_mode", False))
    server.GUILD_CONFIG_PATH = _CONFIG_FILE
    # Best-effort: locate installer/install.py so setup endpoints can shell to it
    _guild_dir = os.path.dirname(os.path.abspath(__file__))
    for candidate in (
        os.path.join(_guild_dir, "..", "installer", "install.py"),
        os.path.join(_guild_dir, "..", "..", "installer", "install.py"),
    ):
        if os.path.exists(candidate):
            server.INSTALLER_PATH = os.path.abspath(candidate)
            break

    # ── Runtime NSFW content injection ──────────────────────────────
    # When running from source with nsfw/.github_token present, the server
    # module's NSFW variables are still empty (not file-patched). Load them
    # from build_nsfw.get_nsfw_runtime_content() and inject into server module.
    if server.NSFW_MODE and not server._NSFW_APPEARANCE_CORE:
        try:
            nsfw_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                     '..', 'nsfw')
            import importlib.util
            spec = importlib.util.spec_from_file_location(
                "build_nsfw", os.path.join(nsfw_dir, "build_nsfw.py"))
            _bn = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(_bn)
            nsfw_content = _bn.get_nsfw_runtime_content()
            for key, val in nsfw_content.items():
                setattr(server, key, val)
            print(f"  [Guild] NSFW content injected: {len(nsfw_content)} variables loaded")
        except Exception as e:
            print(f"  [Guild] WARNING: Failed to load NSFW runtime content: {e}")

    # ── Initialize server (model detection, LoRA scan) ───────────────
    # Pass URL explicitly to avoid any global-timing issues
    server._server_init(comfy_url=comfyui_url)

    guild_url = f"http://127.0.0.1:{port}"

    # ── Check ComfyUI connectivity ───────────────────────────────────
    comfy_alive = _test_endpoint(comfyui_url, "system_stats")
    if comfy_alive:
        print(f"  [server] ComfyUI connected at {comfyui_url}")
    else:
        print(f"  [server] ComfyUI not reachable at {comfyui_url}")
        print(f"  [server] (Assets will be generated when ComfyUI comes online)")

    # ── Start the HTTP server in a background thread ─────────────────
    # ThreadingHTTPServer spawns a worker thread per request. With the
    # single-threaded HTTPServer a long-running handler (SSE stream at
    # /api/events/stream, slow ComfyUI probe, shootout poll) blocked
    # every other client; the default listen backlog of 5 filled up
    # and new connects got RST'd — only the existing browser tab
    # with its SSE keep-alive could talk to the Guild, curl and every
    # other probe got "connection refused".
    print(f"  [server] Starting Wizard Guild on port {port}...")
    httpd = server.ThreadingHTTPServer(('0.0.0.0', port), server.GuildHandler)
    httpd.daemon_threads = True
    httpd.directory = os.path.join(APP_DIR, 'static')

    server_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    server_thread.start()

    # Wait for server to accept connections
    if not _wait_for_server(guild_url, timeout=10):
        print("  [server] WARNING: Server may not have started correctly")
    else:
        print(f"  [server] Wizard Guild is live at {guild_url}")

    # ── First-run asset generation ────────────────────────────────────
    # Used to be a blocking 16-minute wait that kept the browser closed
    # until every wizard's portrait was rendered. New flow: kick off
    # avatar generation in a server-side BACKGROUND thread, open the
    # browser immediately, and let the frontend's setup-mode UI lock the
    # chat input + stream wizards in as their portraits arrive.
    if (comfy_alive and _assets_need_generation()
            and not args.no_assets):
        try:
            payload = json.dumps({"comfy_url": comfyui_url}).encode("utf-8")
            req = urllib.request.Request(
                f"{guild_url}/api/setup/start",
                data=payload,
                headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                resp.read()
            print("  [assets] Background setup started — browser will open immediately,")
            print("           wizards will appear in chat as their portraits render.")
            _mark_assets_generated(0)  # marker file so we don't restart this every launch
        except Exception as e:
            print(f"  [assets] Could not start background setup: {e}")
            print("           Falling back to blocking generation.")
            asset_count = _generate_all_assets(guild_url, comfyui_url, kobold_url)
            if asset_count > 0:
                _mark_assets_generated(asset_count)
    elif not _assets_need_generation():
        print("  [assets] Assets already generated (delete .guild_assets_version to regenerate)")

    # ── Open browser ─────────────────────────────────────────────────
    if config.get("auto_open_browser", True) and not args.no_browser:
        import webbrowser
        print(f"  [server] Opening browser: {guild_url}")
        webbrowser.open(guild_url)

    # ── Tray icon + idle wait ────────────────────────────────────────
    # When pystray is available we run a system-tray icon that blocks
    # this thread in place of the old Ctrl-C sleep loop. The tray
    # surfaces boot / quit events as toasts, opens the browser on
    # demand, and offers a Quit menu item that calls the same shutdown
    # path as Ctrl-C. If pystray isn't installed the old console mode
    # kicks in unchanged.
    def _shutdown_all():
        print("\n  [server] Shutting down...")
        try:
            httpd.shutdown()
        except Exception:
            pass
        if _kobold_process and _kobold_process.poll() is None:
            print("  [kobold] Stopping KoboldCPP...")
            try: _kobold_process.terminate()
            except Exception: pass
        if _st_process and _st_process.poll() is None:
            print("  [st] Stopping SillyTavern...")
            try: _st_process.terminate()
            except Exception: pass
        print("  [server] Goodbye!")

    tray_started = False
    if not getattr(args, "no_tray", False):
        try:
            from . import guild_tray  # when run as module
        except Exception:
            try:
                import guild_tray  # when run as plain script
            except Exception as e:
                guild_tray = None
                print(f"  [tray] could not import guild_tray: {e}")
        if 'guild_tray' in locals() and guild_tray is not None:
            try:
                tray_started = guild_tray.run_tray(guild_url, _shutdown_all)
            except Exception as e:
                print(f"  [tray] failed to start: {e}")

    if not tray_started:
        print()
        print("  Press Ctrl+C to stop the server.")
        print()
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            _shutdown_all()


if __name__ == '__main__':
    main()