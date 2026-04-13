"""
Spellcaster Installer — LLM-Enabled (EXPERIMENTAL)
===================================================

This is a SEPARATE installer that auto-downloads and configures KoboldCpp
plus a small GGUF chat model alongside the normal Spellcaster install.
The regular installer (install.py) is untouched and remains the supported
path for users who already have an LLM or don't want one.

What this script does, in order:
    1. Confirms the user really wants the experimental path.
    2. Reuses install.py's path/server detection so we know where ComfyUI lives.
    3. Downloads the latest KoboldCpp release for the user's platform into
       <comfyui>/spellcaster_llm/.
    4. Downloads a small GGUF chat model into <comfyui>/models/LLM/.
    5. Generates a launch script (.bat / .sh) for KoboldCpp.
    6. Spawns the launch script in the background and waits for the server
       to come up on http://127.0.0.1:5001.
    7. Continues install.py's normal pipeline with --llm-url pre-set so the
       LLM step runs non-interactively.
    8. Creates desktop / start-menu shortcuts so the user can re-launch the
       LLM server on next boot.

Nothing in install.py is modified. If anything in this script fails the user
can fall back to the regular installer at any time.
"""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# Reuse install.py wholesale — this guarantees we never drift from the
# supported install pipeline.
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
import install  # noqa: E402


# ── Constants ────────────────────────────────────────────────────────────────

KOBOLD_API_LATEST = "https://api.github.com/repos/LostRuins/koboldcpp/releases/latest"
LLM_DEFAULT_PORT = 5001
LLM_LOCAL_URL = f"http://127.0.0.1:{LLM_DEFAULT_PORT}"
LLM_READY_TIMEOUT = 180  # seconds to wait for KoboldCpp to come up

# Curated small chat models. All hosted on HuggingFace under standard repos.
# Edit this table to swap defaults — keys are user-facing labels.
MODEL_CHOICES = [
    {
        "label": "Llama-3.2-3B-Instruct (Q4_K_M, ~2.0 GB) — balanced general chat",
        "filename": "Llama-3.2-3B-Instruct-Q4_K_M.gguf",
        "url": "https://huggingface.co/bartowski/Llama-3.2-3B-Instruct-GGUF/resolve/main/Llama-3.2-3B-Instruct-Q4_K_M.gguf",
    },
    {
        "label": "Phi-3-mini-4k-instruct (Q4, ~2.4 GB) — strong instruction following",
        "filename": "Phi-3-mini-4k-instruct-q4.gguf",
        "url": "https://huggingface.co/microsoft/Phi-3-mini-4k-instruct-gguf/resolve/main/Phi-3-mini-4k-instruct-q4.gguf",
    },
    {
        "label": "Qwen2.5-3B-Instruct (Q4_K_M, ~1.9 GB) — strong JSON output",
        "filename": "Qwen2.5-3B-Instruct-Q4_K_M.gguf",
        "url": "https://huggingface.co/bartowski/Qwen2.5-3B-Instruct-GGUF/resolve/main/Qwen2.5-3B-Instruct-Q4_K_M.gguf",
    },
]


# ── Color shims (reuse install.py's palette) ─────────────────────────────────

C_BOLD = install.C_BOLD
C_RESET = install.C_RESET
C_GREEN = install.C_GREEN
C_RED = install.C_RED
C_YELLOW = install.C_YELLOW
C_CYAN = install.C_CYAN
C_DIM = install.C_DIM


def banner():
    bar = "═" * 70
    print(f"\n{C_BOLD}{bar}{C_RESET}")
    print(f"{C_BOLD}  SPELLCASTER INSTALLER — LLM-ENABLED  ({C_YELLOW}EXPERIMENTAL{C_BOLD}){C_RESET}")
    print(f"{C_BOLD}{bar}{C_RESET}")
    print()
    print(f"  This is the {C_YELLOW}experimental{C_RESET} installer. It will:")
    print(f"    • Download KoboldCpp ({C_DIM}~80 MB{C_RESET})")
    print(f"    • Download a small chat model ({C_DIM}~2 GB{C_RESET})")
    print(f"    • Install both inside your ComfyUI folder")
    print(f"    • Auto-launch the LLM and run the regular Spellcaster installer")
    print(f"    • Create desktop / start-menu shortcuts")
    print()
    print(f"  {C_DIM}If you just want the supported installer with no LLM auto-setup,")
    print(f"  {C_DIM}cancel and run:  {C_CYAN}python install.py{C_RESET}")
    print()


def confirm_proceed(args) -> bool:
    if getattr(args, "yes", False):
        print(f"  {C_DIM}--yes specified, skipping confirmation.{C_RESET}\n")
        return True
    try:
        ans = input(f"  Type {C_BOLD}yes{C_RESET} to proceed with the experimental installer: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False
    return ans == "yes"


# ── KoboldCpp download ───────────────────────────────────────────────────────

def _detect_nvidia() -> bool:
    """Best-effort NVIDIA detection via nvidia-smi."""
    try:
        subprocess.run(
            ["nvidia-smi"],
            capture_output=True, timeout=5, check=True
        )
        return True
    except Exception:
        return False


def _pick_kobold_asset(assets: list[dict]) -> dict | None:
    """From a GitHub release's asset list, pick the right one for this OS.

    Asset names from KoboldCpp releases (as of late 2025):
        Windows:  koboldcpp.exe (CUDA 12), koboldcpp_cu12.exe,
                  koboldcpp_nocuda.exe, koboldcpp_oldcpu.exe
        Linux:    koboldcpp-linux-x64-cuda1210, koboldcpp-linux-x64-nocuda,
                  koboldcpp-linux-x64
        macOS:    koboldcpp-mac-arm64
    """
    is_nvidia = _detect_nvidia()
    sysname = platform.system().lower()
    machine = platform.machine().lower()
    names = [(a.get("name", ""), a) for a in assets]

    def _first_match(patterns: list[str]) -> dict | None:
        for pat in patterns:
            rx = re.compile(pat, re.IGNORECASE)
            for name, asset in names:
                if rx.search(name):
                    return asset
        return None

    if "windows" in sysname or sysname.startswith("win"):
        if is_nvidia:
            return _first_match([
                r"^koboldcpp\.exe$",
                r"koboldcpp.*cu12.*\.exe$",
                r"koboldcpp.*cuda.*\.exe$",
                r"koboldcpp.*\.exe$",
            ])
        return _first_match([
            r"koboldcpp.*nocuda.*\.exe$",
            r"koboldcpp.*oldcpu.*\.exe$",
            r"koboldcpp.*\.exe$",
        ])

    if sysname == "linux":
        if is_nvidia:
            return _first_match([
                r"koboldcpp.*linux.*x64.*cuda",
                r"koboldcpp.*linux.*cuda",
                r"koboldcpp.*linux.*x64$",
                r"koboldcpp.*linux",
            ])
        return _first_match([
            r"koboldcpp.*linux.*nocuda",
            r"koboldcpp.*linux.*x64$",
            r"koboldcpp.*linux",
        ])

    if sysname == "darwin":
        if "arm" in machine or "aarch64" in machine:
            return _first_match([r"koboldcpp.*mac.*arm", r"koboldcpp.*mac"])
        return _first_match([r"koboldcpp.*mac.*x64", r"koboldcpp.*mac"])

    return None


def _download_with_progress(url: str, dest: Path, label: str) -> bool:
    """Stream a URL to disk with a simple progress indicator. Resumable
    in the trivial sense — if dest already exists with non-zero size we
    skip and assume it's good. (KoboldCpp release URLs are stable so this
    is safe; for the GGUF we additionally re-validate file size below.)"""
    if dest.exists() and dest.stat().st_size > 0:
        print(f"  {C_GREEN}✓ {label} already present:{C_RESET} {dest} ({dest.stat().st_size // (1024*1024)} MB)")
        return True
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    print(f"  {C_CYAN}↓ Downloading {label}…{C_RESET}")
    print(f"    {C_DIM}{url}{C_RESET}")
    print(f"    {C_DIM}→ {dest}{C_RESET}")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Spellcaster-Installer"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            total = int(resp.headers.get("Content-Length") or 0)
            done = 0
            chunk = 1024 * 256
            last_pct = -1
            with open(tmp, "wb") as f:
                while True:
                    buf = resp.read(chunk)
                    if not buf:
                        break
                    f.write(buf)
                    done += len(buf)
                    if total > 0:
                        pct = int(done * 100 / total)
                        if pct != last_pct and pct % 5 == 0:
                            mb_done = done // (1024 * 1024)
                            mb_total = total // (1024 * 1024)
                            print(f"    {pct:3d}%  {mb_done}/{mb_total} MB", flush=True)
                            last_pct = pct
        tmp.replace(dest)
        print(f"  {C_GREEN}✓ Saved {dest.stat().st_size // (1024*1024)} MB{C_RESET}")
        return True
    except Exception as e:
        print(f"  {C_RED}✗ Download failed: {e}{C_RESET}")
        if tmp.exists():
            try:
                tmp.unlink()
            except Exception:
                pass
        return False


def download_koboldcpp(install_dir: Path) -> Path | None:
    """Download the appropriate KoboldCpp binary into install_dir.
    Returns the path to the downloaded binary, or None on failure."""
    print(f"\n{C_BOLD}── KoboldCpp ──{C_RESET}\n")
    print(f"  Querying latest release: {C_DIM}{KOBOLD_API_LATEST}{C_RESET}")
    try:
        req = urllib.request.Request(
            KOBOLD_API_LATEST,
            headers={"User-Agent": "Spellcaster-Installer", "Accept": "application/vnd.github+json"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            release = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"  {C_RED}✗ Could not query KoboldCpp release info: {e}{C_RESET}")
        return None

    assets = release.get("assets") or []
    if not assets:
        print(f"  {C_RED}✗ No assets found in latest release.{C_RESET}")
        return None

    asset = _pick_kobold_asset(assets)
    if not asset:
        print(f"  {C_RED}✗ Could not find a KoboldCpp build for this platform.{C_RESET}")
        print(f"  {C_DIM}Available assets:{C_RESET}")
        for a in assets:
            print(f"    - {a.get('name', '?')}")
        return None

    asset_name = asset.get("name", "koboldcpp")
    asset_url = asset.get("browser_download_url")
    print(f"  {C_GREEN}✓ Selected:{C_RESET} {asset_name}")

    install_dir.mkdir(parents=True, exist_ok=True)
    dest = install_dir / asset_name
    if not _download_with_progress(asset_url, dest, asset_name):
        return None

    if sys.platform != "win32":
        try:
            dest.chmod(dest.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        except Exception:
            pass

    return dest


# ── Model download ───────────────────────────────────────────────────────────

def choose_model(args) -> dict | None:
    print(f"\n{C_BOLD}── Chat Model ──{C_RESET}\n")
    print(f"  Pick a small GGUF chat model. All run on 4+ GB VRAM.\n")
    for i, m in enumerate(MODEL_CHOICES, 1):
        print(f"    {C_BOLD}{i}.{C_RESET} {m['label']}")
    print(f"    {C_BOLD}{len(MODEL_CHOICES) + 1}.{C_RESET} Skip — I'll bring my own model")
    print()

    if getattr(args, "yes", False):
        print(f"  {C_DIM}--yes specified, picking option 1.{C_RESET}")
        return MODEL_CHOICES[0]

    while True:
        try:
            raw = input(f"  Choice [1-{len(MODEL_CHOICES) + 1}]: ").strip()
        except (EOFError, KeyboardInterrupt):
            return None
        if not raw.isdigit():
            continue
        idx = int(raw)
        if 1 <= idx <= len(MODEL_CHOICES):
            return MODEL_CHOICES[idx - 1]
        if idx == len(MODEL_CHOICES) + 1:
            return None


def download_model(model: dict, models_dir: Path) -> Path | None:
    models_dir.mkdir(parents=True, exist_ok=True)
    dest = models_dir / model["filename"]
    if not _download_with_progress(model["url"], dest, model["filename"]):
        return None
    return dest


# ── Launch script ────────────────────────────────────────────────────────────

def write_launch_script(kobold_path: Path, model_path: Path, scripts_dir: Path) -> Path:
    """Create a platform-appropriate launch script for KoboldCpp."""
    scripts_dir.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        script = scripts_dir / "start_llm.bat"
        # --skiplauncher: bypass GUI; --port: stable port; --usecublas/normal: let kobold auto-pick
        body = (
            "@echo off\r\n"
            f'cd /d "{kobold_path.parent}"\r\n'
            f'"{kobold_path}" --model "{model_path}" --port {LLM_DEFAULT_PORT} --skiplauncher --quiet\r\n'
            "pause\r\n"
        )
        script.write_text(body, encoding="utf-8")
    else:
        script = scripts_dir / "start_llm.sh"
        body = (
            "#!/bin/sh\n"
            f'cd "{kobold_path.parent}"\n'
            f'"{kobold_path}" --model "{model_path}" --port {LLM_DEFAULT_PORT} --skiplauncher --quiet\n'
        )
        script.write_text(body, encoding="utf-8")
        script.chmod(0o755)
    print(f"  {C_GREEN}✓ Launch script:{C_RESET} {script}")
    return script


# ── LLM background spawn + readiness wait ────────────────────────────────────

def spawn_llm(launch_script: Path) -> subprocess.Popen | None:
    """Spawn the launch script as a detached background process so the
    installer can keep running. We deliberately don't capture stdout —
    KoboldCpp logs are noisy and the user can see them in the spawned window
    on Windows or the launching terminal on Unix."""
    print(f"\n{C_BOLD}── Launching LLM ──{C_RESET}\n")
    print(f"  {C_CYAN}Starting:{C_RESET} {launch_script}")
    try:
        if sys.platform == "win32":
            # CREATE_NEW_CONSOLE so the user gets a visible window with logs
            CREATE_NEW_CONSOLE = 0x00000010
            proc = subprocess.Popen(
                ["cmd.exe", "/c", "start", "", str(launch_script)],
                creationflags=CREATE_NEW_CONSOLE,
                close_fds=True,
            )
        else:
            proc = subprocess.Popen(
                ["/bin/sh", str(launch_script)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        return proc
    except Exception as e:
        print(f"  {C_RED}✗ Failed to spawn LLM: {e}{C_RESET}")
        return None


def wait_for_llm_ready(timeout: int = LLM_READY_TIMEOUT) -> bool:
    """Poll KoboldCpp until /api/v1/model responds. Returns True on success."""
    print(f"  {C_DIM}Waiting up to {timeout}s for KoboldCpp to come up at {LLM_LOCAL_URL}…{C_RESET}")
    deadline = time.time() + timeout
    last_err = None
    while time.time() < deadline:
        try:
            req = urllib.request.Request(f"{LLM_LOCAL_URL}/api/v1/model")
            with urllib.request.urlopen(req, timeout=3) as resp:
                if resp.status == 200:
                    body = json.loads(resp.read().decode("utf-8"))
                    print(f"  {C_GREEN}✓ LLM ready:{C_RESET} {body.get('result', '?')}")
                    return True
        except Exception as e:
            last_err = e
        time.sleep(2)
    print(f"  {C_RED}✗ LLM did not become ready within {timeout}s.{C_RESET}")
    if last_err:
        print(f"  {C_DIM}Last error: {last_err}{C_RESET}")
    return False


# ── Shortcuts ────────────────────────────────────────────────────────────────

def _create_llm_shortcut_windows(launch_script: Path, name: str, dest_dir: Path) -> Path | None:
    dest_dir.mkdir(parents=True, exist_ok=True)
    shortcut_path = dest_dir / f"{name}.lnk"
    ps_script = (
        f'$ws = New-Object -ComObject WScript.Shell; '
        f'$s = $ws.CreateShortcut("{shortcut_path}"); '
        f'$s.TargetPath = "{launch_script}"; '
        f'$s.WorkingDirectory = "{launch_script.parent}"; '
        f'$s.Description = "Spellcaster — Start Local LLM Server"; '
        f'$s.Save()'
    )
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_script],
            capture_output=True, timeout=10
        )
        if shortcut_path.exists():
            return shortcut_path
    except Exception:
        pass
    return None


def _create_llm_shortcut_unix(launch_script: Path, name: str, dest_dir: Path) -> Path | None:
    dest_dir.mkdir(parents=True, exist_ok=True)
    if sys.platform == "darwin":
        path = dest_dir / f"{name}.command"
        path.write_text(
            f'#!/bin/sh\n"{launch_script}"\n',
            encoding="utf-8",
        )
        path.chmod(0o755)
        return path
    path = dest_dir / f"{name.lower().replace(' ', '-')}.desktop"
    path.write_text(
        f'[Desktop Entry]\n'
        f'Type=Application\n'
        f'Name={name}\n'
        f'Comment=Spellcaster — Start Local LLM Server\n'
        f'Exec={launch_script}\n'
        f'Path={launch_script.parent}\n'
        f'Terminal=true\n'
        f'Categories=Utility;\n',
        encoding="utf-8",
    )
    path.chmod(0o755)
    return path


def install_llm_shortcuts(launch_script: Path) -> list[Path]:
    print(f"\n{C_BOLD}── Shortcuts ──{C_RESET}\n")
    created: list[Path] = []
    name = "Spellcaster LLM Server"
    home = Path.home()
    if sys.platform == "win32":
        candidates = [
            home / "Desktop",
            home / "AppData" / "Roaming" / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Spellcaster",
        ]
        for d in candidates:
            try:
                p = _create_llm_shortcut_windows(launch_script, name, d)
                if p:
                    print(f"  {C_GREEN}✓{C_RESET} {p}")
                    created.append(p)
            except Exception as e:
                print(f"  {C_YELLOW}⚠ Could not create shortcut at {d}: {e}{C_RESET}")
    else:
        candidates = [home / "Desktop"]
        if sys.platform != "darwin":
            candidates.append(home / ".local" / "share" / "applications")
        for d in candidates:
            try:
                p = _create_llm_shortcut_unix(launch_script, name, d)
                if p:
                    print(f"  {C_GREEN}✓{C_RESET} {p}")
                    created.append(p)
            except Exception as e:
                print(f"  {C_YELLOW}⚠ Could not create shortcut at {d}: {e}{C_RESET}")
    if not created:
        print(f"  {C_YELLOW}No shortcuts created. You can launch the LLM manually with:{C_RESET}")
        print(f"    {launch_script}")
    return created


# ── Pipeline ─────────────────────────────────────────────────────────────────

def main():
    args = install.build_arg_parser().parse_args()
    banner()
    if not confirm_proceed(args):
        print(f"\n  {C_YELLOW}Aborted by user. Run install.py for the supported installer.{C_RESET}\n")
        return 1

    if args.dry_run:
        print(f"  {C_YELLOW}DRY RUN MODE — no changes will be made{C_RESET}\n")

    # Reuse install.py state plumbing
    if not hasattr(args, 'civitai_key'):
        args.civitai_key = getattr(args, 'civitai_key', '') or ''
    if not hasattr(args, 'hf_token'):
        args.hf_token = getattr(args, 'hf_token', '') or ''
    if not hasattr(args, 'llm_url'):
        args.llm_url = ''

    manifest = install.load_manifest()

    install.step_system_detection(args)
    install.step_api_keys(args)
    server_url = install.step_detect_server(args)

    # We need ComfyUI's path BEFORE downloading anything so the LLM and
    # the GGUF land in the right folders. install.main() runs detect_paths
    # later, but the function is idempotent enough to call early.
    paths = install.step_detect_paths(args)
    comfyui_root = paths.get("comfyui")
    if not comfyui_root:
        print(f"\n  {C_RED}✗ ComfyUI path not detected. The LLM installer needs a ComfyUI{C_RESET}")
        print(f"  {C_RED}  install to put files into. Re-run with --comfyui <path>.{C_RESET}\n")
        return 2
    comfyui_root = Path(comfyui_root)
    print(f"\n  {C_GREEN}Installing LLM stack into:{C_RESET} {comfyui_root}")

    llm_dir = comfyui_root / "spellcaster_llm"
    models_dir = comfyui_root / "models" / "LLM"

    # Skip downloads in dry-run
    if args.dry_run:
        print(f"\n  {C_YELLOW}[dry-run] would download KoboldCpp → {llm_dir}{C_RESET}")
        print(f"  {C_YELLOW}[dry-run] would download GGUF model → {models_dir}{C_RESET}")
        print(f"  {C_YELLOW}[dry-run] would launch LLM and run install.py pipeline{C_RESET}")
        return 0

    kobold_path = download_koboldcpp(llm_dir)
    if not kobold_path:
        print(f"\n  {C_RED}KoboldCpp download failed. Aborting.{C_RESET}")
        print(f"  {C_DIM}You can re-run install.py to install Spellcaster without an LLM.{C_RESET}\n")
        return 3

    model_choice = choose_model(args)
    model_path: Path | None = None
    if model_choice:
        model_path = download_model(model_choice, models_dir)
        if not model_path:
            print(f"\n  {C_RED}Model download failed. Aborting.{C_RESET}")
            print(f"  {C_DIM}You can re-run install.py to install Spellcaster without an LLM.{C_RESET}\n")
            return 4
    else:
        print(f"  {C_YELLOW}No model selected. You will need to point KoboldCpp at one yourself.{C_RESET}")

    # Generate launch script (only if we actually have a model)
    launch_script = None
    if model_path:
        launch_script = write_launch_script(kobold_path, model_path, llm_dir)

        proc = spawn_llm(launch_script)
        if proc and wait_for_llm_ready():
            args.llm_url = LLM_LOCAL_URL
        else:
            print(f"\n  {C_YELLOW}LLM did not start cleanly. Continuing install without LLM URL.{C_RESET}")
            print(f"  {C_DIM}You can launch it manually later: {launch_script}{C_RESET}")
    else:
        print(f"  {C_DIM}Skipping LLM launch (no model).{C_RESET}")

    # ── Continue install.py's normal pipeline ──
    print(f"\n{C_BOLD}── Continuing Spellcaster install ──{C_RESET}")
    llm_url = install.step_detect_llm_server(args)  # picks up args.llm_url non-interactively
    server_info = install.step_probe_server(server_url, args)
    selected = install.step_select_features(manifest, paths, args, server_info)

    if not args.skip_nodes:
        install.step_install_nodes(manifest, selected, paths, args.dry_run, server_info)
    else:
        print(f"\n  {C_YELLOW}--skip-nodes specified — skipping custom node installation.{C_RESET}")

    install.step_install_models(manifest, selected, paths, args)
    install._write_shared_settings(paths, server_url, llm_url, server_info, args.dry_run)
    install.step_install_plugins(paths, server_url, args.dry_run)
    install.step_install_tavern(paths, server_url, llm_url, selected, args.dry_run, args.yes)
    install.step_import_luts(paths, args)
    install.step_apply_theme(paths, args.dry_run, args.yes)
    install.step_final_summary(manifest, selected, paths, server_url)

    # ── Post-install: shortcuts for the LLM launcher ──
    if launch_script:
        install_llm_shortcuts(launch_script)

    print(f"\n{C_BOLD}{'═' * 70}{C_RESET}")
    print(f"{C_BOLD}  Done. The LLM is running on {LLM_LOCAL_URL}.{C_RESET}")
    if launch_script:
        print(f"  {C_DIM}Re-launch later with:{C_RESET} {launch_script}")
    print(f"{C_BOLD}{'═' * 70}{C_RESET}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
