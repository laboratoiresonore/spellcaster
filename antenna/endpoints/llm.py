"""LLM install + status endpoints — remote KoboldCpp bootstrap over antenna.

Implements:

  POST /llm/install   — download KoboldCpp + a GGUF model onto the host
                        running this antenna; optionally spawn + wait.
  GET  /llm/status    — report whether an LLM is installed + reachable
                        on localhost here.

The wizard on the Guild side drives this when the user declared
ComfyUI (or the LLM specifically) as living on another machine. The
Guild's `_spellcaster_install_remote_llm` helper POSTs here; this
module shells out to the ALREADY-EXISTING `installer/install_with_llm.py`
primitives (download_koboldcpp, download_model, write_launch_script,
spawn_llm, wait_for_llm_ready). Zero duplicated install logic — this
module is a HTTP adapter.

Design mirrors `antenna/endpoints/comfyui.py`:
  - Lazy-import the installer primitives so an antenna that isn't
    configured for LLM service doesn't pay the import cost.
  - Bounded execution: the install call blocks for minutes (model
    download). Callers should set a generous timeout.
  - Never run code outside the known-good install_with_llm primitives.
  - Every response names the file paths written so the caller can
    verify + follow up with /service/start.

Install modes:
  "kobold"          — classic standalone KoboldCpp on port 5001.
                      Works even when no ComfyUI is running on this
                      host (the minimum viable LLM for a remote
                      Spellcaster setup).
  "comfyui_native"  — installs the ComfyUI-QwenVL-Mod pack + a Qwen3
                      GGUF into the remote ComfyUI's models/. Only
                      makes sense on a host that ALSO has ComfyUI.
                      Uses install_with_llm._install_comfyui_native.
"""
from __future__ import annotations

import os
import sys
import traceback
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


def _import_install_with_llm():
    """Lazy import of installer/install_with_llm.py + install.py."""
    try:
        _repo_root = os.path.abspath(os.path.join(
            os.path.dirname(__file__), "..", ".."))
        if _repo_root not in sys.path:
            sys.path.insert(0, _repo_root)
        from installer import install_with_llm as _iw  # type: ignore
        from installer import install as _inst  # type: ignore
        return _iw, _inst
    except Exception as e:
        raise ImportError(f"install_with_llm not importable: {e}") from e


# ── GET /llm/status ──────────────────────────────────────────────────────

def status(ctx: dict[str, Any]) -> tuple[int, dict]:
    """Report local-LLM reachability on this host.

    Probes the usual ports:
      - KoboldCpp       :5001  /v1/models
      - Ollama          :11434 /api/tags
      - ComfyUI QwenVL  via the ComfyUI /object_info registry

    Returns a dict with every probed backend's reachability, which
    Guild + wizard use to decide whether /llm/install is even needed.
    """
    out = {
        "host": "localhost",      # relative to this antenna
        "kobold":   {"reachable": False, "url": "http://127.0.0.1:5001",   "model": None},
        "ollama":   {"reachable": False, "url": "http://127.0.0.1:11434",  "model": None},
        "comfyui":  {"reachable": False, "qwen_node": False},
    }
    # Kobold
    try:
        req = urllib.request.Request("http://127.0.0.1:5001/v1/models",
                                      headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=2) as resp:
            if resp.status == 200:
                out["kobold"]["reachable"] = True
    except Exception:
        pass
    # Ollama
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=2) as resp:
            if resp.status == 200:
                out["ollama"]["reachable"] = True
    except Exception:
        pass
    # ComfyUI Qwen node — only meaningful if ComfyUI is on this box
    cfg = ctx.get("config") or {}
    comfy_port = int(cfg.get("comfyui_port", 8188))
    try:
        url = f"http://127.0.0.1:{comfy_port}/object_info/AILab_QwenVL_GGUF_PromptEnhancer"
        with urllib.request.urlopen(url, timeout=2) as resp:
            if resp.status == 200:
                out["comfyui"]["reachable"] = True
                out["comfyui"]["qwen_node"] = True
    except Exception:
        pass
    return 200, out


# ── POST /llm/install ────────────────────────────────────────────────────

def install_llm(ctx: dict[str, Any]) -> tuple[int, dict]:
    """POST /llm/install
    Body:
      {
        "mode":          "kobold" | "comfyui_native",   # default "kobold"
        "model":         "<filename or civitai/hf key>" # optional; defaults
                                                          # to the first
                                                          # suggested model.
        "spawn":         true,  # start it after install; default true
        "install_dir":   "<absolute path>",  # optional override
      }

    Returns:
      {
        "ok":        bool,
        "mode":      "kobold" | "comfyui_native",
        "paths":     {kobold_exe, model_file, launch_script, install_dir},
        "spawned":   bool,
        "url":       "http://127.0.0.1:5001",   # Kobold port if spawned
        "error":     "..."                       # on failure
      }

    Bounded execution — can block for minutes during model download.
    """
    body = ctx.get("body") or {}
    mode = str(body.get("mode") or "kobold").lower()
    if mode not in ("kobold", "comfyui_native"):
        return 400, {"error": f"mode must be kobold|comfyui_native, got {mode!r}"}

    try:
        iw, _inst = _import_install_with_llm()
    except ImportError as e:
        return 500, {"error": str(e)}

    if mode == "kobold":
        return _install_kobold(iw, body)
    return _install_comfyui_native(iw, body, ctx)


def _install_kobold(iw, body: dict[str, Any]) -> tuple[int, dict]:
    """Download KoboldCpp + a GGUF + launch."""
    # Pick install root
    install_dir = body.get("install_dir") \
        or os.path.expanduser("~/.spellcaster/kobold")
    install_dir_p = Path(install_dir)
    install_dir_p.mkdir(parents=True, exist_ok=True)

    paths: dict[str, str] = {"install_dir": str(install_dir_p)}

    try:
        # 1. KoboldCpp binary
        kobold_path = iw.download_koboldcpp(install_dir_p)
        if not kobold_path:
            return 500, {"ok": False, "error": "koboldcpp download failed",
                         "paths": paths}
        paths["kobold_exe"] = str(kobold_path)

        # 2. Model. Let install_with_llm pick a sensible default from
        #    its internal list (Qwen3 4B, Mistral 7B, etc.) — if the
        #    body specifies one, we forward it via a minimal args stub.
        class _Args:
            model = body.get("model") or ""
            yes   = True   # non-interactive
        model = iw.choose_model(_Args())
        if not model:
            return 500, {"ok": False, "error": "no model could be chosen",
                         "paths": paths}

        models_dir = install_dir_p / "models"
        models_dir.mkdir(parents=True, exist_ok=True)
        model_path = iw.download_model(model, models_dir)
        if not model_path:
            return 500, {"ok": False, "error": "model download failed",
                         "paths": paths, "model": model}
        paths["model_file"] = str(model_path)

        # 3. Launch script
        scripts_dir = install_dir_p / "scripts"
        scripts_dir.mkdir(parents=True, exist_ok=True)
        launch = iw.write_launch_script(kobold_path, model_path, scripts_dir)
        paths["launch_script"] = str(launch)

        # 4. Spawn (optional; default true)
        if body.get("spawn", True):
            proc = iw.spawn_llm(launch)
            if proc is None:
                return 500, {"ok": False, "paths": paths,
                             "error": "launched but spawn() returned None"}
            if not iw.wait_for_llm_ready():
                return 500, {"ok": False, "paths": paths,
                             "error": "kobold started but not reachable "
                                      "within timeout"}
            return 200, {"ok": True, "mode": "kobold", "paths": paths,
                         "spawned": True, "url": "http://127.0.0.1:5001"}
        return 200, {"ok": True, "mode": "kobold", "paths": paths,
                     "spawned": False}
    except Exception as e:
        tb = traceback.format_exc(limit=3)
        return 500, {"ok": False, "mode": "kobold", "paths": paths,
                     "error": f"{type(e).__name__}: {e}",
                     "traceback": tb[-1500:]}


def _install_comfyui_native(iw, body: dict[str, Any],
                             ctx: dict[str, Any]) -> tuple[int, dict]:
    """Install the Qwen node pack + GGUF into the local ComfyUI.

    Requires ComfyUI already installed on this antenna's host. Uses
    install_with_llm._install_comfyui_native which talks to the local
    ComfyUI /object_info + clones the node pack + downloads the GGUF.
    """
    cfg = ctx.get("config") or {}
    comfy_root = body.get("comfy_root") or cfg.get("comfyui_root")
    server_url = body.get("server_url") or cfg.get("comfyui_url") \
        or f"http://127.0.0.1:{cfg.get('comfyui_port', 8188)}"
    if not comfy_root:
        return 400, {"ok": False, "error": "comfy_root required for "
                                           "comfyui_native mode"}

    class _Args:
        yes   = True
        force = False
        hf_token = body.get("hf_token") or ""

    # Mirror the shape install_with_llm._install_comfyui_native expects.
    paths = {"comfyui_root": comfy_root}
    try:
        rc = iw._install_comfyui_native(_Args(), Path(comfy_root),
                                         paths, server_url)
        ok = (rc == 0)
        return (200 if ok else 500), {"ok": ok, "mode": "comfyui_native",
                                       "paths": paths,
                                       "returncode": rc,
                                       "server_url": server_url}
    except Exception as e:
        tb = traceback.format_exc(limit=3)
        return 500, {"ok": False, "mode": "comfyui_native",
                     "error": f"{type(e).__name__}: {e}",
                     "traceback": tb[-1500:]}
