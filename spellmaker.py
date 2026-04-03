#!/usr/bin/env python3
"""
Spellmaker -- Preset & Workflow Editor for Spellcaster
======================================================
Standalone customtkinter GUI that lets users create, edit, clone, import,
and export presets for the Spellcaster ecosystem (GIMP + Darktable plugins).

All presets are stored in a local ``spellbook.json`` alongside this script.
Presets can be injected into the GIMP and/or Darktable plugin source files,
or imported from raw ComfyUI API-format workflow JSON.

Launch:
    python spellmaker.py
"""

from __future__ import annotations

import copy
import json
import os
import re
import sys
import textwrap
import threading
import tkinter as tk
import traceback
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Auto-install customtkinter if missing
# ---------------------------------------------------------------------------

def _ensure_deps():
    try:
        import customtkinter  # noqa: F401
    except ImportError:
        import subprocess
        subprocess.check_call([sys.executable, "-m", "pip", "install", "--user", "customtkinter"])

_ensure_deps()

import customtkinter as ctk

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).resolve().parent
SPELLBOOK_PATH = SCRIPT_DIR / "spellbook.json"
GIMP_PLUGIN_PATH = SCRIPT_DIR / "plugins" / "gimp" / "comfyui-connector" / "comfyui-connector.py"
DARKTABLE_PLUGIN_PATH = SCRIPT_DIR / "plugins" / "darktable" / "comfyui_connector.lua"

# ---------------------------------------------------------------------------
# Theme constants (matches installer_gui.py)
# ---------------------------------------------------------------------------

BG = "#0B0715"
BG_SIDEBAR = "#150D26"
BG_CARD = "#110A20"
BG_CARD_HOVER = "#1A1230"
BG_ENTRY = "#150D26"
BG_BUTTON = "#3A2863"
BG_BUTTON_HOVER = "#D122E3"
ACCENT = "#D122E3"
ACCENT_DIM = "#8B3AAF"
TEXT = "#E2DFEB"
TEXT_DIM = "#8B7CA8"
BORDER = "#21153B"
BORDER_FOCUS = "#D122E3"
DANGER = "#E04060"
SUCCESS = "#40C080"
FONT_FAMILY = "Segoe UI"

# ---------------------------------------------------------------------------
# Preset type definitions
# ---------------------------------------------------------------------------

PRESET_TYPES = [
    "model_preset",
    "inpaint_preset",
    "scene_preset",
    "video_preset",
    "wan_model",
    "klein_model",
    "iclight_preset",
    "custom_workflow",
]

PRESET_TYPE_LABELS = {
    "model_preset": "Model Presets",
    "inpaint_preset": "Inpaint Presets",
    "scene_preset": "Scene Presets",
    "video_preset": "Video Presets",
    "wan_model": "Wan I2V Models",
    "klein_model": "Klein Models",
    "iclight_preset": "IC-Light Presets",
    "custom_workflow": "Custom Workflows",
}

ARCH_OPTIONS = ["sd15", "sdxl", "zit", "illustrious", "flux"]
SAMPLER_OPTIONS = [
    "euler", "euler_ancestral", "heun", "heunpp2", "dpm_2", "dpm_2_ancestral",
    "lms", "dpm_fast", "dpm_adaptive", "dpmpp_2s_ancestral", "dpmpp_sde",
    "dpmpp_sde_gpu", "dpmpp_2m", "dpmpp_2m_sde", "dpmpp_2m_sde_gpu",
    "dpmpp_3m_sde", "dpmpp_3m_sde_gpu", "ddpm", "lcm", "ddim", "uni_pc",
    "uni_pc_bh2",
]
SCHEDULER_OPTIONS = [
    "normal", "karras", "exponential", "sgm_uniform", "simple", "ddim_uniform",
    "beta",
]
SCENE_ARCH_TABS = ["sd15", "sdxl", "flux", "anime", "cartoon", "kontext"]

# ---------------------------------------------------------------------------
# Default preset templates
# ---------------------------------------------------------------------------

def _default_preset(ptype: str) -> dict:
    """Return a blank preset dict for the given type."""
    base = {"type": ptype, "label": "New Preset", "enabled": True, "source": "user"}
    if ptype == "model_preset":
        base["data"] = {
            "arch": "sdxl", "ckpt": "", "width": 1024, "height": 1024,
            "steps": 25, "cfg": 7.0, "denoise": 0.62,
            "sampler": "dpmpp_2m_sde", "scheduler": "karras",
            "prompt_hint": "", "negative_hint": "",
        }
    elif ptype == "inpaint_preset":
        base["data"] = {
            "prompt": "", "negative": "", "denoise": 0.65,
            "cfg_boost": 0.0, "steps_override": 25,
            "loras": {},
        }
    elif ptype == "scene_preset":
        base["data"] = {"prompts": {a: ("", "") for a in SCENE_ARCH_TABS}}
    elif ptype == "video_preset":
        base["data"] = {
            "prompt": "", "negative": "", "cfg_override": 5.0,
            "steps_override": 30, "length_override": 81,
            "pingpong": False, "loras": [],
        }
    elif ptype == "wan_model":
        base["data"] = {
            "high_model": "", "low_model": "", "clip": "", "vae": "",
            "steps": 30, "second_step": 20, "cfg": 5.0, "shift": 8.0,
            "lora_prefix": "Wan/",
        }
    elif ptype == "klein_model":
        base["data"] = {
            "unet": "", "clip": "",
            "steps": 4, "cfg": 1.0, "denoise": 0.65,
            "sampler": "euler", "scheduler": "simple",
            "guidance": 1.0,
            "enhancer_magnitude": 1.0, "enhancer_contrast": 0.0,
            "text_ref_balance": 0.5,
        }
    elif ptype == "iclight_preset":
        base["data"] = {"prompt": ""}
    elif ptype == "custom_workflow":
        base["data"] = {"workflow_json": "{}"}
    return base


# ---------------------------------------------------------------------------
# Lightweight tooltip (copied from installer_gui.py)
# ---------------------------------------------------------------------------

class _ToolTip:
    """Lightweight tooltip for customtkinter widgets using only tkinter builtins."""

    def __init__(self, widget, text, delay=400):
        self.widget = widget
        self.text = text
        self.delay = delay
        self._tip = None
        self._id = None
        widget.bind("<Enter>", self._on_enter)
        widget.bind("<Leave>", self._on_leave)

    def _on_enter(self, event=None):
        self._id = self.widget.after(self.delay, self._show)

    def _on_leave(self, event=None):
        if self._id:
            self.widget.after_cancel(self._id)
            self._id = None
        if self._tip:
            self._tip.destroy()
            self._tip = None

    def _show(self):
        x = self.widget.winfo_rootx() + 20
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 5
        self._tip = tk.Toplevel(self.widget)
        self._tip.wm_overrideredirect(True)
        self._tip.wm_geometry(f"+{x}+{y}")
        label = tk.Label(
            self._tip, text=self.text, background="#1a1a2e", foreground=TEXT,
            relief="solid", borderwidth=1, font=(FONT_FAMILY, 12),
            wraplength=500, justify="left", padx=12, pady=8,
        )
        label.pack()


# ---------------------------------------------------------------------------
# ComfyUI server helper
# ---------------------------------------------------------------------------

class ComfyUIClient:
    """Thin wrapper around ComfyUI's REST API using stdlib urllib."""

    def __init__(self, base_url: str = "http://127.0.0.1:8188"):
        self.base_url = base_url.rstrip("/")
        self._object_info: dict | None = None
        self._loras: list[str] | None = None
        self._checkpoints: list[str] | None = None

    # -- low-level --------------------------------------------------------

    def _get(self, path: str, timeout: float = 8) -> Any:
        url = f"{self.base_url}{path}"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())

    def _post(self, path: str, data: dict, timeout: float = 30) -> Any:
        url = f"{self.base_url}{path}"
        body = json.dumps(data).encode()
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())

    # -- public API -------------------------------------------------------

    def ping(self) -> bool:
        try:
            self._get("/system_stats", timeout=3)
            return True
        except Exception:
            return False

    def fetch_object_info(self) -> dict:
        if self._object_info is None:
            self._object_info = self._get("/object_info", timeout=15)
        return self._object_info

    def list_loras(self) -> list[str]:
        if self._loras is None:
            info = self.fetch_object_info()
            lora_node = info.get("LoraLoader") or info.get("LoraLoaderModelOnly") or {}
            inp = lora_node.get("input", {}).get("required", {})
            self._loras = sorted(inp.get("lora_name", [[]])[0]) if "lora_name" in inp else []
        return self._loras

    def list_checkpoints(self) -> list[str]:
        if self._checkpoints is None:
            info = self.fetch_object_info()
            ckpt_node = info.get("CheckpointLoaderSimple", {})
            inp = ckpt_node.get("input", {}).get("required", {})
            self._checkpoints = sorted(inp.get("ckpt_name", [[]])[0]) if "ckpt_name" in inp else []
        return self._checkpoints

    def list_samplers(self) -> list[str]:
        info = self.fetch_object_info()
        ks = info.get("KSampler", {})
        inp = ks.get("input", {}).get("required", {})
        return sorted(inp.get("sampler_name", [[]])[0]) if "sampler_name" in inp else SAMPLER_OPTIONS

    def list_schedulers(self) -> list[str]:
        info = self.fetch_object_info()
        ks = info.get("KSampler", {})
        inp = ks.get("input", {}).get("required", {})
        return sorted(inp.get("scheduler", [[]])[0]) if "scheduler" in inp else SCHEDULER_OPTIONS

    def queue_prompt(self, workflow: dict) -> dict:
        return self._post("/prompt", {"prompt": workflow})

    def invalidate(self):
        self._object_info = None
        self._loras = None
        self._checkpoints = None


# ---------------------------------------------------------------------------
# Spellbook (data store)
# ---------------------------------------------------------------------------

class Spellbook:
    """Load/save the spellbook.json file and manage presets in memory."""

    def __init__(self, path: Path = SPELLBOOK_PATH):
        self.path = path
        self.presets: list[dict] = []
        self.load()

    def load(self):
        if self.path.exists():
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.presets = data if isinstance(data, list) else data.get("presets", [])
            except Exception:
                self.presets = []
        else:
            self.presets = []

    def save(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.presets, f, indent=2, ensure_ascii=False)

    def by_type(self, ptype: str) -> list[dict]:
        return [p for p in self.presets if p.get("type") == ptype]

    def add(self, preset: dict):
        self.presets.append(preset)

    def remove(self, preset: dict):
        try:
            self.presets.remove(preset)
        except ValueError:
            pass

    def clone(self, preset: dict) -> dict:
        new = copy.deepcopy(preset)
        new["label"] = new.get("label", "Preset") + " (copy)"
        new["source"] = "user"
        self.presets.append(new)
        return new


# ---------------------------------------------------------------------------
# ComfyUI workflow parser
# ---------------------------------------------------------------------------

def parse_comfyui_workflow(wf: dict) -> dict:
    """Parse a ComfyUI API-format workflow JSON and extract key parameters.

    Returns a dict suitable for creating a model_preset or custom_workflow.
    """
    result = {
        "ckpt": "", "sampler": "", "scheduler": "", "steps": 20,
        "cfg": 7.0, "denoise": 1.0, "prompt": "", "negative": "",
        "width": 512, "height": 512, "loras": [], "workflow_type": "unknown",
    }

    for nid, node in wf.items():
        ct = node.get("class_type", "")
        inputs = node.get("inputs", {})

        # Checkpoint
        if ct in ("CheckpointLoaderSimple", "CheckpointLoader"):
            result["ckpt"] = inputs.get("ckpt_name", "")

        # KSampler
        if ct in ("KSampler", "KSamplerAdvanced"):
            result["sampler"] = inputs.get("sampler_name", "")
            result["scheduler"] = inputs.get("scheduler", "")
            result["steps"] = inputs.get("steps", 20)
            result["cfg"] = inputs.get("cfg", 7.0)
            result["denoise"] = inputs.get("denoise", 1.0)
            if inputs.get("seed") is not None:
                pass  # seed is per-run, not stored

        # CLIP text encode (positive / negative heuristic)
        if ct == "CLIPTextEncode":
            text = inputs.get("text", "")
            if isinstance(text, str) and text.strip():
                # Heuristic: if it looks negative, treat as negative
                neg_markers = ["worst quality", "bad anatomy", "deformed", "lowres",
                               "blurry", "ugly", "low quality", "nsfw"]
                is_neg = any(m in text.lower() for m in neg_markers)
                if is_neg and not result["negative"]:
                    result["negative"] = text
                elif not is_neg and not result["prompt"]:
                    result["prompt"] = text

        # Empty latent image (dimensions)
        if ct in ("EmptyLatentImage", "EmptySD3LatentImage"):
            result["width"] = inputs.get("width", 512)
            result["height"] = inputs.get("height", 512)

        # LoRA
        if ct in ("LoraLoader", "LoraLoaderModelOnly"):
            lora_name = inputs.get("lora_name", "")
            ms = inputs.get("strength_model", 1.0)
            cs = inputs.get("strength_clip", 1.0)
            if lora_name:
                result["loras"].append({"name": lora_name, "model_strength": ms, "clip_strength": cs})

    # Detect workflow type
    class_types = {n.get("class_type", "") for n in wf.values()}
    if "SetLatentNoiseMask" in class_types or "InpaintModelConditioning" in class_types:
        result["workflow_type"] = "inpaint"
    elif "EmptyLatentImage" in class_types:
        result["workflow_type"] = "txt2img"
    elif "VAEEncode" in class_types:
        result["workflow_type"] = "img2img"
    elif "UNETLoader" in class_types:
        result["workflow_type"] = "flux/klein"
    elif any("Wan" in ct for ct in class_types):
        result["workflow_type"] = "wan_video"

    return result


def workflow_to_preset(parsed: dict) -> dict:
    """Convert parsed workflow data into a spellbook preset dict."""
    wt = parsed.get("workflow_type", "unknown")

    if wt in ("txt2img", "img2img"):
        arch = "sdxl"
        w, h = parsed.get("width", 1024), parsed.get("height", 1024)
        if w <= 768 and h <= 768:
            arch = "sd15"
        return {
            "type": "model_preset",
            "label": f"Imported {wt} Preset",
            "enabled": True,
            "source": "user",
            "data": {
                "arch": arch,
                "ckpt": parsed.get("ckpt", ""),
                "width": w, "height": h,
                "steps": parsed.get("steps", 25),
                "cfg": parsed.get("cfg", 7.0),
                "denoise": parsed.get("denoise", 0.65),
                "sampler": parsed.get("sampler", "dpmpp_2m_sde"),
                "scheduler": parsed.get("scheduler", "karras"),
                "prompt_hint": parsed.get("prompt", ""),
                "negative_hint": parsed.get("negative", ""),
            },
        }
    elif wt == "inpaint":
        return {
            "type": "inpaint_preset",
            "label": "Imported Inpaint Preset",
            "enabled": True,
            "source": "user",
            "data": {
                "prompt": parsed.get("prompt", ""),
                "negative": parsed.get("negative", ""),
                "denoise": parsed.get("denoise", 0.65),
                "cfg_boost": 0.0,
                "steps_override": parsed.get("steps", 25),
                "loras": {},
            },
        }
    else:
        # Fall back to custom workflow
        return {
            "type": "custom_workflow",
            "label": f"Imported Workflow ({wt})",
            "enabled": True,
            "source": "user",
            "data": {"workflow_json": json.dumps(parsed, indent=2)},
        }


# ---------------------------------------------------------------------------
# Injection helpers
# ---------------------------------------------------------------------------

def _inject_into_gimp(presets: list[dict]) -> str:
    """Append user presets to the GIMP plugin's preset arrays.

    Returns a status message.
    """
    if not GIMP_PLUGIN_PATH.exists():
        return f"GIMP plugin not found at {GIMP_PLUGIN_PATH}"

    text = GIMP_PLUGIN_PATH.read_text(encoding="utf-8")
    marker = "# ── Spellmaker injected presets ──"
    injected_count = 0

    for p in presets:
        if not p.get("enabled", True):
            continue
        ptype = p.get("type", "")
        data = p.get("data", {})
        label = p.get("label", "User Preset")

        if ptype == "model_preset":
            entry = (
                f"    {{\n"
                f"        \"label\": {json.dumps(label)},\n"
                f"        \"arch\": {json.dumps(data.get('arch', 'sdxl'))},\n"
                f"        \"ckpt\": {json.dumps(data.get('ckpt', ''))},\n"
                f"        \"width\": {data.get('width', 1024)}, \"height\": {data.get('height', 1024)},\n"
                f"        \"steps\": {data.get('steps', 25)}, \"cfg\": {data.get('cfg', 7.0)}, "
                f"\"denoise\": {data.get('denoise', 0.62)},\n"
                f"        \"sampler\": {json.dumps(data.get('sampler', 'dpmpp_2m_sde'))}, "
                f"\"scheduler\": {json.dumps(data.get('scheduler', 'karras'))},\n"
                f"        \"prompt_hint\": {json.dumps(data.get('prompt_hint', ''))},\n"
                f"        \"negative_hint\": {json.dumps(data.get('negative_hint', ''))},\n"
                f"    }},\n"
            )
            # Find the end of MODEL_PRESETS array
            pattern = r"(MODEL_PRESETS\s*=\s*\[.*?)(^\])"
            match = re.search(pattern, text, re.DOTALL | re.MULTILINE)
            if match:
                insert_pos = match.start(2)
                inject_block = f"    {marker}\n{entry}"
                if marker not in text[match.start(1):match.end(2)]:
                    text = text[:insert_pos] + inject_block + text[insert_pos:]
                    injected_count += 1

        elif ptype == "inpaint_preset":
            loras_str = json.dumps(data.get("loras", {}), indent=8)
            entry = (
                f"    {{\n"
                f"        \"label\": {json.dumps(label)},\n"
                f"        \"prompt\": {json.dumps(data.get('prompt', ''))},\n"
                f"        \"negative\": {json.dumps(data.get('negative', ''))},\n"
                f"        \"denoise\": {data.get('denoise', 0.65)},\n"
                f"        \"cfg_boost\": {data.get('cfg_boost', 0.0)},\n"
                f"        \"steps_override\": {data.get('steps_override', 25)},\n"
                f"        \"loras\": {loras_str},\n"
                f"    }},\n"
            )
            pattern = r"(INPAINT_REFINEMENTS\s*=\s*\[.*?)(^\])"
            match = re.search(pattern, text, re.DOTALL | re.MULTILINE)
            if match:
                insert_pos = match.start(2)
                inject_block = f"    {marker}\n{entry}"
                if marker not in text[match.start(1):match.end(2)]:
                    text = text[:insert_pos] + inject_block + text[insert_pos:]
                    injected_count += 1

        elif ptype == "scene_preset":
            prompts = data.get("prompts", {})
            prompts_str = json.dumps(prompts, indent=12)
            entry = (
                f"    {{\n"
                f"        \"label\": {json.dumps(label)},\n"
                f"        \"prompts\": {prompts_str},\n"
                f"    }},\n"
            )
            pattern = r"(SCENE_PRESETS\s*=\s*\[.*?)(^\])"
            match = re.search(pattern, text, re.DOTALL | re.MULTILINE)
            if match:
                insert_pos = match.start(2)
                inject_block = f"    {marker}\n{entry}"
                if marker not in text[match.start(1):match.end(2)]:
                    text = text[:insert_pos] + inject_block + text[insert_pos:]
                    injected_count += 1

        elif ptype == "video_preset":
            entry = (
                f"    {{\n"
                f"        \"label\": {json.dumps(label)},\n"
                f"        \"prompt\": {json.dumps(data.get('prompt', ''))},\n"
                f"        \"negative\": {json.dumps(data.get('negative', ''))},\n"
                f"        \"cfg_override\": {data.get('cfg_override')},\n"
                f"        \"steps_override\": {data.get('steps_override')},\n"
                f"        \"length_override\": {data.get('length_override')},\n"
                f"        \"pingpong\": {str(data.get('pingpong', False))},\n"
                f"        \"loras\": {json.dumps(data.get('loras', []))},\n"
                f"    }},\n"
            )
            pattern = r"(WAN_VIDEO_PRESETS\s*=\s*\[.*?)(^\])"
            match = re.search(pattern, text, re.DOTALL | re.MULTILINE)
            if match:
                insert_pos = match.start(2)
                inject_block = f"    {marker}\n{entry}"
                if marker not in text[match.start(1):match.end(2)]:
                    text = text[:insert_pos] + inject_block + text[insert_pos:]
                    injected_count += 1

        elif ptype == "iclight_preset":
            key = label.replace('"', '\\"')
            entry = f'    "{key}": {json.dumps(data.get("prompt", ""))},\n'
            pattern = r"(ICLIGHT_PRESETS\s*=\s*\{.*?)(^\})"
            match = re.search(pattern, text, re.DOTALL | re.MULTILINE)
            if match:
                insert_pos = match.start(2)
                inject_block = f"    {marker}\n{entry}"
                if marker not in text[match.start(1):match.end(2)]:
                    text = text[:insert_pos] + inject_block + text[insert_pos:]
                    injected_count += 1

    if injected_count > 0:
        GIMP_PLUGIN_PATH.write_text(text, encoding="utf-8")
    return f"Injected {injected_count} preset(s) into GIMP plugin."


def _inject_into_darktable(presets: list[dict]) -> str:
    """Append user presets to the Darktable Lua plugin.

    The Lua plugin defines its presets as Lua tables. We append new entries
    using a marker comment.
    """
    if not DARKTABLE_PLUGIN_PATH.exists():
        return f"Darktable plugin not found at {DARKTABLE_PLUGIN_PATH}"

    text = DARKTABLE_PLUGIN_PATH.read_text(encoding="utf-8")
    marker = "-- Spellmaker injected presets --"
    if marker in text:
        return "Darktable plugin already has injected presets. Remove them first to re-inject."

    inject_lines = [f"\n{marker}"]
    count = 0

    for p in presets:
        if not p.get("enabled", True):
            continue
        ptype = p.get("type", "")
        data = p.get("data", {})
        label = p.get("label", "User Preset")

        if ptype == "model_preset":
            lua_entry = textwrap.dedent(f"""\
                -- Spellmaker: {label}
                table.insert(model_presets, {{
                    label = "{label}",
                    arch = "{data.get('arch', 'sdxl')}",
                    ckpt = "{data.get('ckpt', '')}",
                    width = {data.get('width', 1024)}, height = {data.get('height', 1024)},
                    steps = {data.get('steps', 25)}, cfg = {data.get('cfg', 7.0)},
                    denoise = {data.get('denoise', 0.62)},
                    sampler = "{data.get('sampler', 'dpmpp_2m_sde')}",
                    scheduler = "{data.get('scheduler', 'karras')}",
                    prompt_hint = {json.dumps(data.get('prompt_hint', ''))},
                    negative_hint = {json.dumps(data.get('negative_hint', ''))},
                }})
            """)
            inject_lines.append(lua_entry)
            count += 1

    if count > 0:
        # Insert before the final return script_data line
        ret_pattern = r"(return\s+script_data)"
        match = re.search(ret_pattern, text)
        if match:
            text = text[:match.start()] + "\n".join(inject_lines) + "\n\n" + text[match.start():]
        else:
            text += "\n".join(inject_lines)
        DARKTABLE_PLUGIN_PATH.write_text(text, encoding="utf-8")

    return f"Injected {count} preset(s) into Darktable plugin."


# =========================================================================
# GUI components
# =========================================================================

class LoraPickerDialog(ctk.CTkToplevel):
    """Modal dialog for picking a LoRA from the server or entering a path manually."""

    def __init__(self, parent, client: ComfyUIClient | None = None):
        super().__init__(parent)
        self.title("Add LoRA")
        self.geometry("500x550")
        self.configure(fg_color=BG)
        self.transient(parent)
        self.grab_set()
        self.result: dict | None = None

        self._loras: list[str] = []

        # Search
        search_frame = ctk.CTkFrame(self, fg_color=BG)
        search_frame.pack(fill="x", padx=12, pady=(12, 4))
        ctk.CTkLabel(search_frame, text="Search LoRAs:", text_color=TEXT,
                      font=(FONT_FAMILY, 13)).pack(side="left")
        self._search_var = ctk.StringVar()
        self._search_var.trace_add("write", lambda *_: self._filter())
        ctk.CTkEntry(search_frame, textvariable=self._search_var, width=300,
                      fg_color=BG_ENTRY, text_color=TEXT, border_color=BORDER
                      ).pack(side="left", padx=(8, 0), fill="x", expand=True)

        # List
        self._listbox_frame = ctk.CTkScrollableFrame(self, fg_color=BG_CARD, height=300)
        self._listbox_frame.pack(fill="both", expand=True, padx=12, pady=4)
        self._lora_buttons: list[ctk.CTkButton] = []

        # Manual entry
        manual_frame = ctk.CTkFrame(self, fg_color=BG)
        manual_frame.pack(fill="x", padx=12, pady=4)
        ctk.CTkLabel(manual_frame, text="Or enter path:", text_color=TEXT_DIM,
                      font=(FONT_FAMILY, 12)).pack(side="left")
        self._manual_var = ctk.StringVar()
        ctk.CTkEntry(manual_frame, textvariable=self._manual_var, width=300,
                      fg_color=BG_ENTRY, text_color=TEXT, border_color=BORDER
                      ).pack(side="left", padx=(8, 0), fill="x", expand=True)

        # Strengths
        str_frame = ctk.CTkFrame(self, fg_color=BG)
        str_frame.pack(fill="x", padx=12, pady=4)

        ctk.CTkLabel(str_frame, text="Model strength:", text_color=TEXT,
                      font=(FONT_FAMILY, 12)).grid(row=0, column=0, sticky="w")
        self._model_str = ctk.CTkSlider(str_frame, from_=0.0, to=2.0, number_of_steps=40,
                                          fg_color=BORDER, progress_color=ACCENT, width=200)
        self._model_str.set(1.0)
        self._model_str.grid(row=0, column=1, padx=8)
        self._model_str_label = ctk.CTkLabel(str_frame, text="1.00", text_color=TEXT,
                                               font=(FONT_FAMILY, 12), width=40)
        self._model_str_label.grid(row=0, column=2)
        self._model_str.configure(command=lambda v: self._model_str_label.configure(text=f"{v:.2f}"))

        ctk.CTkLabel(str_frame, text="CLIP strength:", text_color=TEXT,
                      font=(FONT_FAMILY, 12)).grid(row=1, column=0, sticky="w")
        self._clip_str = ctk.CTkSlider(str_frame, from_=0.0, to=2.0, number_of_steps=40,
                                         fg_color=BORDER, progress_color=ACCENT, width=200)
        self._clip_str.set(1.0)
        self._clip_str.grid(row=1, column=1, padx=8)
        self._clip_str_label = ctk.CTkLabel(str_frame, text="1.00", text_color=TEXT,
                                              font=(FONT_FAMILY, 12), width=40)
        self._clip_str_label.grid(row=1, column=2)
        self._clip_str.configure(command=lambda v: self._clip_str_label.configure(text=f"{v:.2f}"))

        # Buttons
        btn_frame = ctk.CTkFrame(self, fg_color=BG)
        btn_frame.pack(fill="x", padx=12, pady=12)
        ctk.CTkButton(btn_frame, text="Cancel", fg_color=BG_BUTTON, hover_color=BG_CARD_HOVER,
                       text_color=TEXT, command=self.destroy).pack(side="right", padx=4)
        ctk.CTkButton(btn_frame, text="Add LoRA", fg_color=ACCENT, hover_color=ACCENT_DIM,
                       text_color="white", command=self._on_add).pack(side="right", padx=4)

        # Load LoRAs
        if client:
            try:
                self._loras = client.list_loras()
            except Exception:
                self._loras = []
        self._populate()

    def _populate(self, filter_text: str = ""):
        for btn in self._lora_buttons:
            btn.destroy()
        self._lora_buttons.clear()

        ft = filter_text.lower()
        for lora in self._loras:
            if ft and ft not in lora.lower():
                continue
            btn = ctk.CTkButton(
                self._listbox_frame, text=lora, anchor="w",
                fg_color=BG_CARD, hover_color=BG_CARD_HOVER, text_color=TEXT,
                font=(FONT_FAMILY, 11), height=28,
                command=lambda l=lora: self._select_lora(l),
            )
            btn.pack(fill="x", pady=1)
            self._lora_buttons.append(btn)

        if not self._loras:
            ctk.CTkLabel(self._listbox_frame, text="No LoRAs found. Enter path manually.",
                          text_color=TEXT_DIM, font=(FONT_FAMILY, 11)).pack(pady=10)

    def _filter(self):
        self._populate(self._search_var.get())

    def _select_lora(self, name: str):
        self._manual_var.set(name)

    def _on_add(self):
        name = self._manual_var.get().strip()
        if not name:
            return
        self.result = {
            "name": name,
            "model_strength": round(self._model_str.get(), 2),
            "clip_strength": round(self._clip_str.get(), 2),
        }
        self.destroy()


class WorkflowPreviewDialog(ctk.CTkToplevel):
    """Shows parsed workflow data before importing."""

    def __init__(self, parent, parsed: dict):
        super().__init__(parent)
        self.title("Workflow Preview")
        self.geometry("600x500")
        self.configure(fg_color=BG)
        self.transient(parent)
        self.grab_set()
        self.accepted = False

        scroll = ctk.CTkScrollableFrame(self, fg_color=BG_CARD)
        scroll.pack(fill="both", expand=True, padx=12, pady=12)

        fields = [
            ("Workflow type", parsed.get("workflow_type", "unknown")),
            ("Checkpoint", parsed.get("ckpt", "")),
            ("Sampler", parsed.get("sampler", "")),
            ("Scheduler", parsed.get("scheduler", "")),
            ("Steps", str(parsed.get("steps", ""))),
            ("CFG", str(parsed.get("cfg", ""))),
            ("Denoise", str(parsed.get("denoise", ""))),
            ("Width", str(parsed.get("width", ""))),
            ("Height", str(parsed.get("height", ""))),
            ("Prompt", parsed.get("prompt", "")[:200]),
            ("Negative", parsed.get("negative", "")[:200]),
        ]
        loras = parsed.get("loras", [])
        if loras:
            fields.append(("LoRAs", ", ".join(l.get("name", "") for l in loras)))

        for label, value in fields:
            row = ctk.CTkFrame(scroll, fg_color=BG_CARD)
            row.pack(fill="x", pady=2)
            ctk.CTkLabel(row, text=f"{label}:", text_color=ACCENT,
                          font=(FONT_FAMILY, 12, "bold"), width=120, anchor="e").pack(side="left", padx=(4, 8))
            ctk.CTkLabel(row, text=str(value) if value else "(empty)", text_color=TEXT,
                          font=(FONT_FAMILY, 12), wraplength=400, anchor="w").pack(side="left", fill="x")

        btn_frame = ctk.CTkFrame(self, fg_color=BG)
        btn_frame.pack(fill="x", padx=12, pady=12)
        ctk.CTkButton(btn_frame, text="Cancel", fg_color=BG_BUTTON, hover_color=BG_CARD_HOVER,
                       text_color=TEXT, command=self.destroy).pack(side="right", padx=4)
        ctk.CTkButton(btn_frame, text="Import as Preset", fg_color=ACCENT, hover_color=ACCENT_DIM,
                       text_color="white", command=self._accept).pack(side="right", padx=4)

    def _accept(self):
        self.accepted = True
        self.destroy()


# =========================================================================
# Editor panels (one per preset type)
# =========================================================================

class BaseEditor(ctk.CTkFrame):
    """Base class for all preset type editors."""

    def __init__(self, parent, **kwargs):
        super().__init__(parent, fg_color=BG, **kwargs)
        self._preset: dict | None = None
        self._fields: dict[str, Any] = {}

    def load_preset(self, preset: dict):
        self._preset = preset

    def save_to_preset(self) -> bool:
        """Write field values back into self._preset['data']. Returns True on success."""
        return False

    def _make_label(self, parent, text, row=0, col=0):
        lbl = ctk.CTkLabel(parent, text=text, text_color=TEXT, font=(FONT_FAMILY, 12),
                            anchor="e", width=130)
        lbl.grid(row=row, column=col, sticky="e", padx=(4, 8), pady=3)
        return lbl

    def _make_entry(self, parent, key, row, default="", width=300):
        self._make_label(parent, key.replace("_", " ").title() + ":", row=row)
        var = ctk.StringVar(value=str(default))
        entry = ctk.CTkEntry(parent, textvariable=var, width=width,
                              fg_color=BG_ENTRY, text_color=TEXT, border_color=BORDER)
        entry.grid(row=row, column=1, sticky="ew", padx=4, pady=3)
        self._fields[key] = var
        return entry

    def _make_spinner(self, parent, key, row, default=0, from_=0, to=9999, step=1):
        self._make_label(parent, key.replace("_", " ").title() + ":", row=row)
        var = ctk.DoubleVar(value=float(default))
        frame = ctk.CTkFrame(parent, fg_color=BG)
        frame.grid(row=row, column=1, sticky="w", padx=4, pady=3)

        entry = ctk.CTkEntry(frame, textvariable=var, width=80,
                              fg_color=BG_ENTRY, text_color=TEXT, border_color=BORDER)
        entry.pack(side="left")

        def inc():
            try:
                v = var.get() + step
                if v <= to:
                    var.set(round(v, 4))
            except Exception:
                pass

        def dec():
            try:
                v = var.get() - step
                if v >= from_:
                    var.set(round(v, 4))
            except Exception:
                pass

        ctk.CTkButton(frame, text="-", width=28, height=28, fg_color=BG_BUTTON,
                       hover_color=BG_CARD_HOVER, text_color=TEXT, command=dec).pack(side="left", padx=2)
        ctk.CTkButton(frame, text="+", width=28, height=28, fg_color=BG_BUTTON,
                       hover_color=BG_CARD_HOVER, text_color=TEXT, command=inc).pack(side="left", padx=2)

        self._fields[key] = var
        return frame

    def _make_dropdown(self, parent, key, row, options, default=""):
        self._make_label(parent, key.replace("_", " ").title() + ":", row=row)
        var = ctk.StringVar(value=default)
        combo = ctk.CTkComboBox(parent, variable=var, values=options, width=300,
                                 fg_color=BG_ENTRY, text_color=TEXT, border_color=BORDER,
                                 button_color=BG_BUTTON, button_hover_color=ACCENT,
                                 dropdown_fg_color=BG_CARD, dropdown_text_color=TEXT,
                                 dropdown_hover_color=BG_CARD_HOVER)
        combo.grid(row=row, column=1, sticky="ew", padx=4, pady=3)
        self._fields[key] = var
        return combo

    def _make_checkbox(self, parent, key, row, default=False):
        self._make_label(parent, key.replace("_", " ").title() + ":", row=row)
        var = ctk.BooleanVar(value=default)
        cb = ctk.CTkCheckBox(parent, text="", variable=var,
                              fg_color=BG_BUTTON, hover_color=ACCENT,
                              checkmark_color="white", border_color=BORDER)
        cb.grid(row=row, column=1, sticky="w", padx=4, pady=3)
        self._fields[key] = var
        return cb

    def _make_text(self, parent, key, row, default="", height=80):
        self._make_label(parent, key.replace("_", " ").title() + ":", row=row)
        textbox = ctk.CTkTextbox(parent, width=300, height=height,
                                  fg_color=BG_ENTRY, text_color=TEXT, border_color=BORDER,
                                  font=(FONT_FAMILY, 12))
        textbox.grid(row=row, column=1, sticky="ew", padx=4, pady=3)
        textbox.insert("1.0", default)
        self._fields[key] = textbox
        return textbox


class ModelPresetEditor(BaseEditor):
    """Editor for model_preset type."""

    def __init__(self, parent, **kwargs):
        super().__init__(parent, **kwargs)
        self.grid_columnconfigure(1, weight=1)

        self._make_entry(self, "label", 0)
        self._make_dropdown(self, "arch", 1, ARCH_OPTIONS)
        self._make_entry(self, "ckpt", 2)
        self._make_spinner(self, "width", 3, 1024, 64, 4096, 64)
        self._make_spinner(self, "height", 4, 1024, 64, 4096, 64)
        self._make_spinner(self, "steps", 5, 25, 1, 150, 1)
        self._make_spinner(self, "cfg", 6, 7.0, 0.0, 30.0, 0.5)
        self._make_spinner(self, "denoise", 7, 0.62, 0.0, 1.0, 0.01)
        self._make_dropdown(self, "sampler", 8, SAMPLER_OPTIONS)
        self._make_dropdown(self, "scheduler", 9, SCHEDULER_OPTIONS)
        self._make_entry(self, "prompt_hint", 10)
        self._make_entry(self, "negative_hint", 11)

    def load_preset(self, preset: dict):
        super().load_preset(preset)
        d = preset.get("data", {})
        self._fields["label"].set(preset.get("label", ""))
        self._fields["arch"].set(d.get("arch", "sdxl"))
        self._fields["ckpt"].set(d.get("ckpt", ""))
        self._fields["width"].set(d.get("width", 1024))
        self._fields["height"].set(d.get("height", 1024))
        self._fields["steps"].set(d.get("steps", 25))
        self._fields["cfg"].set(d.get("cfg", 7.0))
        self._fields["denoise"].set(d.get("denoise", 0.62))
        self._fields["sampler"].set(d.get("sampler", "dpmpp_2m_sde"))
        self._fields["scheduler"].set(d.get("scheduler", "karras"))
        self._fields["prompt_hint"].set(d.get("prompt_hint", ""))
        self._fields["negative_hint"].set(d.get("negative_hint", ""))

    def save_to_preset(self) -> bool:
        if not self._preset:
            return False
        self._preset["label"] = self._fields["label"].get()
        d = self._preset.setdefault("data", {})
        d["arch"] = self._fields["arch"].get()
        d["ckpt"] = self._fields["ckpt"].get()
        try:
            d["width"] = int(self._fields["width"].get())
            d["height"] = int(self._fields["height"].get())
            d["steps"] = int(self._fields["steps"].get())
            d["cfg"] = float(self._fields["cfg"].get())
            d["denoise"] = float(self._fields["denoise"].get())
        except ValueError:
            return False
        d["sampler"] = self._fields["sampler"].get()
        d["scheduler"] = self._fields["scheduler"].get()
        d["prompt_hint"] = self._fields["prompt_hint"].get()
        d["negative_hint"] = self._fields["negative_hint"].get()
        return True


class InpaintPresetEditor(BaseEditor):
    """Editor for inpaint_preset type."""

    def __init__(self, parent, client: ComfyUIClient | None = None, **kwargs):
        super().__init__(parent, **kwargs)
        self._client = client
        self.grid_columnconfigure(1, weight=1)

        self._make_entry(self, "label", 0)
        self._make_text(self, "prompt", 1, height=60)
        self._make_text(self, "negative", 2, height=60)
        self._make_spinner(self, "denoise", 3, 0.65, 0.0, 1.0, 0.01)
        self._make_spinner(self, "cfg_boost", 4, 0.0, 0.0, 5.0, 0.5)
        self._make_spinner(self, "steps_override", 5, 25, 1, 150, 1)

        # LoRA section
        lora_label = ctk.CTkLabel(self, text="LoRAs (per-arch):", text_color=ACCENT,
                                   font=(FONT_FAMILY, 13, "bold"))
        lora_label.grid(row=6, column=0, columnspan=2, sticky="w", padx=8, pady=(12, 4))

        self._lora_frame = ctk.CTkScrollableFrame(self, fg_color=BG_CARD, height=150)
        self._lora_frame.grid(row=7, column=0, columnspan=2, sticky="ew", padx=8, pady=4)

        btn_row = ctk.CTkFrame(self, fg_color=BG)
        btn_row.grid(row=8, column=0, columnspan=2, sticky="w", padx=8, pady=4)
        ctk.CTkButton(btn_row, text="+ Add LoRA", fg_color=ACCENT, hover_color=ACCENT_DIM,
                       text_color="white", width=120, command=self._add_lora).pack(side="left")

        self._lora_data: dict[str, list] = {}  # arch -> [(name, ms, cs), ...]

    def _add_lora(self):
        dialog = LoraPickerDialog(self.winfo_toplevel(), self._client)
        self.wait_window(dialog)
        if dialog.result:
            # Ask which arch this LoRA is for
            arch_dialog = ctk.CTkInputDialog(text="Architecture for this LoRA\n(sdxl, sd15, flux2klein, flux1dev, flux_kontext):",
                                              title="Select Architecture")
            arch = arch_dialog.get_input()
            if not arch:
                arch = "sdxl"
            arch = arch.strip().lower()
            if arch not in self._lora_data:
                self._lora_data[arch] = []
            self._lora_data[arch].append(
                (dialog.result["name"], dialog.result["model_strength"], dialog.result["clip_strength"])
            )
            self._refresh_lora_display()

    def _refresh_lora_display(self):
        for w in self._lora_frame.winfo_children():
            w.destroy()

        for arch, loras in self._lora_data.items():
            ctk.CTkLabel(self._lora_frame, text=f"  {arch}:", text_color=ACCENT,
                          font=(FONT_FAMILY, 11, "bold")).pack(anchor="w", pady=(4, 0))
            for i, (name, ms, cs) in enumerate(loras):
                row = ctk.CTkFrame(self._lora_frame, fg_color=BG_CARD)
                row.pack(fill="x", pady=1, padx=8)
                ctk.CTkLabel(row, text=f"  {name}  (m={ms}, c={cs})", text_color=TEXT,
                              font=(FONT_FAMILY, 11)).pack(side="left", fill="x")
                arch_ref, idx_ref = arch, i
                ctk.CTkButton(row, text="X", width=24, height=24, fg_color=DANGER,
                               hover_color="#C03050", text_color="white",
                               command=lambda a=arch_ref, ix=idx_ref: self._remove_lora(a, ix)
                               ).pack(side="right", padx=4)

    def _remove_lora(self, arch: str, idx: int):
        if arch in self._lora_data and idx < len(self._lora_data[arch]):
            self._lora_data[arch].pop(idx)
            if not self._lora_data[arch]:
                del self._lora_data[arch]
            self._refresh_lora_display()

    def load_preset(self, preset: dict):
        super().load_preset(preset)
        d = preset.get("data", {})
        self._fields["label"].set(preset.get("label", ""))
        self._fields["prompt"].delete("1.0", "end")
        self._fields["prompt"].insert("1.0", d.get("prompt", ""))
        self._fields["negative"].delete("1.0", "end")
        self._fields["negative"].insert("1.0", d.get("negative", ""))
        self._fields["denoise"].set(d.get("denoise", 0.65) or 0.65)
        self._fields["cfg_boost"].set(d.get("cfg_boost", 0.0) or 0.0)
        self._fields["steps_override"].set(d.get("steps_override", 25) or 25)

        # Load LoRAs
        self._lora_data = {}
        raw_loras = d.get("loras", {})
        if isinstance(raw_loras, dict):
            for arch, entries in raw_loras.items():
                if entries:
                    self._lora_data[arch] = [(e[0], e[1], e[2]) if isinstance(e, (list, tuple)) else
                                              (e.get("name", ""), e.get("model_strength", 1.0),
                                               e.get("clip_strength", 1.0)) for e in entries]
        self._refresh_lora_display()

    def save_to_preset(self) -> bool:
        if not self._preset:
            return False
        self._preset["label"] = self._fields["label"].get()
        d = self._preset.setdefault("data", {})
        d["prompt"] = self._fields["prompt"].get("1.0", "end").strip()
        d["negative"] = self._fields["negative"].get("1.0", "end").strip()
        try:
            d["denoise"] = float(self._fields["denoise"].get())
            d["cfg_boost"] = float(self._fields["cfg_boost"].get())
            d["steps_override"] = int(self._fields["steps_override"].get())
        except ValueError:
            return False
        # Convert lora data to the tuple format used by the GIMP plugin
        d["loras"] = {}
        for arch, entries in self._lora_data.items():
            d["loras"][arch] = [[name, ms, cs] for name, ms, cs in entries]
        return True


class ScenePresetEditor(BaseEditor):
    """Editor for scene_preset type with tabbed architecture prompts."""

    def __init__(self, parent, **kwargs):
        super().__init__(parent, **kwargs)
        self.grid_columnconfigure(0, weight=1)

        top = ctk.CTkFrame(self, fg_color=BG)
        top.grid(row=0, column=0, sticky="ew", padx=4, pady=4)
        top.grid_columnconfigure(1, weight=1)
        self._make_label(top, "Label:", row=0)
        self._label_var = ctk.StringVar()
        ctk.CTkEntry(top, textvariable=self._label_var, width=300,
                      fg_color=BG_ENTRY, text_color=TEXT, border_color=BORDER
                      ).grid(row=0, column=1, sticky="ew", padx=4, pady=3)

        # Tabview for architectures
        self._tabview = ctk.CTkTabview(self, fg_color=BG_CARD, segmented_button_fg_color=BG_SIDEBAR,
                                        segmented_button_selected_color=ACCENT,
                                        segmented_button_unselected_color=BG_BUTTON,
                                        segmented_button_selected_hover_color=ACCENT_DIM)
        self._tabview.grid(row=1, column=0, sticky="nsew", padx=4, pady=4)
        self.grid_rowconfigure(1, weight=1)

        self._prompt_fields: dict[str, ctk.CTkTextbox] = {}
        self._negative_fields: dict[str, ctk.CTkTextbox] = {}

        for arch in SCENE_ARCH_TABS:
            tab = self._tabview.add(arch)
            tab.grid_columnconfigure(0, weight=1)

            ctk.CTkLabel(tab, text="Positive prompt:", text_color=ACCENT,
                          font=(FONT_FAMILY, 12)).grid(row=0, column=0, sticky="w", padx=4)
            pt = ctk.CTkTextbox(tab, height=100, fg_color=BG_ENTRY, text_color=TEXT,
                                 border_color=BORDER, font=(FONT_FAMILY, 12))
            pt.grid(row=1, column=0, sticky="nsew", padx=4, pady=2)
            self._prompt_fields[arch] = pt

            ctk.CTkLabel(tab, text="Negative prompt:", text_color=TEXT_DIM,
                          font=(FONT_FAMILY, 12)).grid(row=2, column=0, sticky="w", padx=4, pady=(8, 0))
            nt = ctk.CTkTextbox(tab, height=80, fg_color=BG_ENTRY, text_color=TEXT,
                                 border_color=BORDER, font=(FONT_FAMILY, 12))
            nt.grid(row=3, column=0, sticky="nsew", padx=4, pady=2)
            self._negative_fields[arch] = nt

            tab.grid_rowconfigure(1, weight=1)
            tab.grid_rowconfigure(3, weight=1)

    def load_preset(self, preset: dict):
        super().load_preset(preset)
        self._label_var.set(preset.get("label", ""))
        prompts = preset.get("data", {}).get("prompts", {})
        for arch in SCENE_ARCH_TABS:
            pair = prompts.get(arch, ("", ""))
            pos = pair[0] if isinstance(pair, (list, tuple)) and len(pair) > 0 else ""
            neg = pair[1] if isinstance(pair, (list, tuple)) and len(pair) > 1 else ""
            self._prompt_fields[arch].delete("1.0", "end")
            self._prompt_fields[arch].insert("1.0", pos)
            self._negative_fields[arch].delete("1.0", "end")
            self._negative_fields[arch].insert("1.0", neg)

    def save_to_preset(self) -> bool:
        if not self._preset:
            return False
        self._preset["label"] = self._label_var.get()
        d = self._preset.setdefault("data", {})
        prompts = {}
        for arch in SCENE_ARCH_TABS:
            pos = self._prompt_fields[arch].get("1.0", "end").strip()
            neg = self._negative_fields[arch].get("1.0", "end").strip()
            prompts[arch] = (pos, neg)
        d["prompts"] = prompts
        return True


class VideoPresetEditor(BaseEditor):
    """Editor for video_preset type."""

    def __init__(self, parent, client: ComfyUIClient | None = None, **kwargs):
        super().__init__(parent, **kwargs)
        self._client = client
        self.grid_columnconfigure(1, weight=1)

        self._make_entry(self, "label", 0)
        self._make_text(self, "prompt", 1, height=60)
        self._make_text(self, "negative", 2, height=60)
        self._make_spinner(self, "cfg_override", 3, 5.0, 0.0, 30.0, 0.5)
        self._make_spinner(self, "steps_override", 4, 30, 1, 150, 1)
        self._make_spinner(self, "length_override", 5, 81, 1, 500, 1)
        self._make_checkbox(self, "pingpong", 6)

        # LoRA section
        lora_label = ctk.CTkLabel(self, text="LoRAs:", text_color=ACCENT,
                                   font=(FONT_FAMILY, 13, "bold"))
        lora_label.grid(row=7, column=0, columnspan=2, sticky="w", padx=8, pady=(12, 4))

        self._lora_frame = ctk.CTkScrollableFrame(self, fg_color=BG_CARD, height=100)
        self._lora_frame.grid(row=8, column=0, columnspan=2, sticky="ew", padx=8, pady=4)

        btn_row = ctk.CTkFrame(self, fg_color=BG)
        btn_row.grid(row=9, column=0, columnspan=2, sticky="w", padx=8, pady=4)
        ctk.CTkButton(btn_row, text="+ Add LoRA", fg_color=ACCENT, hover_color=ACCENT_DIM,
                       text_color="white", width=120, command=self._add_lora).pack(side="left")

        self._lora_list: list[dict] = []

    def _add_lora(self):
        dialog = LoraPickerDialog(self.winfo_toplevel(), self._client)
        self.wait_window(dialog)
        if dialog.result:
            self._lora_list.append(dialog.result)
            self._refresh_loras()

    def _refresh_loras(self):
        for w in self._lora_frame.winfo_children():
            w.destroy()
        for i, lora in enumerate(self._lora_list):
            row = ctk.CTkFrame(self._lora_frame, fg_color=BG_CARD)
            row.pack(fill="x", pady=1)
            ctk.CTkLabel(row, text=f"  {lora['name']}  (m={lora['model_strength']}, c={lora['clip_strength']})",
                          text_color=TEXT, font=(FONT_FAMILY, 11)).pack(side="left", fill="x")
            idx = i
            ctk.CTkButton(row, text="X", width=24, height=24, fg_color=DANGER,
                           hover_color="#C03050", text_color="white",
                           command=lambda ix=idx: self._remove_lora(ix)).pack(side="right", padx=4)

    def _remove_lora(self, idx: int):
        if idx < len(self._lora_list):
            self._lora_list.pop(idx)
            self._refresh_loras()

    def load_preset(self, preset: dict):
        super().load_preset(preset)
        d = preset.get("data", {})
        self._fields["label"].set(preset.get("label", ""))
        self._fields["prompt"].delete("1.0", "end")
        self._fields["prompt"].insert("1.0", d.get("prompt", ""))
        self._fields["negative"].delete("1.0", "end")
        self._fields["negative"].insert("1.0", d.get("negative", ""))
        self._fields["cfg_override"].set(d.get("cfg_override") or 5.0)
        self._fields["steps_override"].set(d.get("steps_override") or 30)
        self._fields["length_override"].set(d.get("length_override") or 81)
        self._fields["pingpong"].set(d.get("pingpong", False))

        self._lora_list = []
        for l in d.get("loras", []):
            if isinstance(l, dict):
                self._lora_list.append(l)
            elif isinstance(l, (list, tuple)) and len(l) >= 1:
                self._lora_list.append({"name": l[0],
                                         "model_strength": l[1] if len(l) > 1 else 1.0,
                                         "clip_strength": l[2] if len(l) > 2 else 1.0})
        self._refresh_loras()

    def save_to_preset(self) -> bool:
        if not self._preset:
            return False
        self._preset["label"] = self._fields["label"].get()
        d = self._preset.setdefault("data", {})
        d["prompt"] = self._fields["prompt"].get("1.0", "end").strip()
        d["negative"] = self._fields["negative"].get("1.0", "end").strip()
        try:
            d["cfg_override"] = float(self._fields["cfg_override"].get())
            d["steps_override"] = int(self._fields["steps_override"].get())
            d["length_override"] = int(self._fields["length_override"].get())
        except ValueError:
            return False
        d["pingpong"] = self._fields["pingpong"].get()
        d["loras"] = self._lora_list
        return True


class WanModelEditor(BaseEditor):
    """Editor for wan_model (Wan I2V model configuration)."""

    def __init__(self, parent, **kwargs):
        super().__init__(parent, **kwargs)
        self.grid_columnconfigure(1, weight=1)

        self._make_entry(self, "label", 0)
        self._make_entry(self, "high_model", 1)
        self._make_entry(self, "low_model", 2)
        self._make_entry(self, "clip", 3)
        self._make_entry(self, "vae", 4)
        self._make_spinner(self, "steps", 5, 30, 1, 150, 1)
        self._make_spinner(self, "second_step", 6, 20, 1, 150, 1)
        self._make_spinner(self, "cfg", 7, 5.0, 0.0, 30.0, 0.5)
        self._make_spinner(self, "shift", 8, 8.0, 0.0, 20.0, 0.5)
        self._make_entry(self, "lora_prefix", 9)

    def load_preset(self, preset: dict):
        super().load_preset(preset)
        d = preset.get("data", {})
        self._fields["label"].set(preset.get("label", ""))
        for key in ["high_model", "low_model", "clip", "vae", "lora_prefix"]:
            self._fields[key].set(d.get(key, ""))
        for key in ["steps", "second_step", "cfg", "shift"]:
            self._fields[key].set(d.get(key, 0))

    def save_to_preset(self) -> bool:
        if not self._preset:
            return False
        self._preset["label"] = self._fields["label"].get()
        d = self._preset.setdefault("data", {})
        for key in ["high_model", "low_model", "clip", "vae", "lora_prefix"]:
            d[key] = self._fields[key].get()
        try:
            d["steps"] = int(self._fields["steps"].get())
            d["second_step"] = int(self._fields["second_step"].get())
            d["cfg"] = float(self._fields["cfg"].get())
            d["shift"] = float(self._fields["shift"].get())
        except ValueError:
            return False
        return True


class KleinModelEditor(BaseEditor):
    """Editor for klein_model type."""

    def __init__(self, parent, **kwargs):
        super().__init__(parent, **kwargs)
        self.grid_columnconfigure(1, weight=1)

        self._make_entry(self, "label", 0)
        self._make_entry(self, "unet", 1)
        self._make_entry(self, "clip", 2)
        self._make_spinner(self, "steps", 3, 4, 1, 50, 1)
        self._make_spinner(self, "cfg", 4, 1.0, 0.0, 30.0, 0.5)
        self._make_spinner(self, "denoise", 5, 0.65, 0.0, 1.0, 0.01)
        self._make_dropdown(self, "sampler", 6, SAMPLER_OPTIONS, "euler")
        self._make_dropdown(self, "scheduler", 7, SCHEDULER_OPTIONS, "simple")
        self._make_spinner(self, "guidance", 8, 1.0, 0.0, 10.0, 0.1)
        self._make_spinner(self, "enhancer_magnitude", 9, 1.0, 0.0, 5.0, 0.1)
        self._make_spinner(self, "enhancer_contrast", 10, 0.0, 0.0, 5.0, 0.1)
        self._make_spinner(self, "text_ref_balance", 11, 0.5, 0.0, 1.0, 0.05)

    def load_preset(self, preset: dict):
        super().load_preset(preset)
        d = preset.get("data", {})
        self._fields["label"].set(preset.get("label", ""))
        for key in ["unet", "clip"]:
            self._fields[key].set(d.get(key, ""))
        for key in ["steps", "cfg", "denoise", "guidance", "enhancer_magnitude",
                     "enhancer_contrast", "text_ref_balance"]:
            self._fields[key].set(d.get(key, 0))
        self._fields["sampler"].set(d.get("sampler", "euler"))
        self._fields["scheduler"].set(d.get("scheduler", "simple"))

    def save_to_preset(self) -> bool:
        if not self._preset:
            return False
        self._preset["label"] = self._fields["label"].get()
        d = self._preset.setdefault("data", {})
        for key in ["unet", "clip"]:
            d[key] = self._fields[key].get()
        d["sampler"] = self._fields["sampler"].get()
        d["scheduler"] = self._fields["scheduler"].get()
        try:
            d["steps"] = int(self._fields["steps"].get())
            d["cfg"] = float(self._fields["cfg"].get())
            d["denoise"] = float(self._fields["denoise"].get())
            d["guidance"] = float(self._fields["guidance"].get())
            d["enhancer_magnitude"] = float(self._fields["enhancer_magnitude"].get())
            d["enhancer_contrast"] = float(self._fields["enhancer_contrast"].get())
            d["text_ref_balance"] = float(self._fields["text_ref_balance"].get())
        except ValueError:
            return False
        return True


class ICLightPresetEditor(BaseEditor):
    """Editor for iclight_preset type."""

    def __init__(self, parent, **kwargs):
        super().__init__(parent, **kwargs)
        self.grid_columnconfigure(1, weight=1)

        self._make_entry(self, "label", 0)
        self._make_text(self, "prompt", 1, height=120)

    def load_preset(self, preset: dict):
        super().load_preset(preset)
        d = preset.get("data", {})
        self._fields["label"].set(preset.get("label", ""))
        self._fields["prompt"].delete("1.0", "end")
        self._fields["prompt"].insert("1.0", d.get("prompt", ""))

    def save_to_preset(self) -> bool:
        if not self._preset:
            return False
        self._preset["label"] = self._fields["label"].get()
        d = self._preset.setdefault("data", {})
        d["prompt"] = self._fields["prompt"].get("1.0", "end").strip()
        return True


class CustomWorkflowEditor(BaseEditor):
    """Editor for custom_workflow type with a raw JSON editor."""

    def __init__(self, parent, **kwargs):
        super().__init__(parent, **kwargs)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(2, weight=1)

        self._make_entry(self, "label", 0)

        ctk.CTkLabel(self, text="Workflow JSON:", text_color=ACCENT,
                      font=(FONT_FAMILY, 12)).grid(row=1, column=0, columnspan=2, sticky="w", padx=8, pady=(8, 2))

        self._json_editor = ctk.CTkTextbox(self, fg_color=BG_ENTRY, text_color=TEXT,
                                             border_color=BORDER, font=("Consolas", 11))
        self._json_editor.grid(row=2, column=0, columnspan=2, sticky="nsew", padx=8, pady=4)

        btn_row = ctk.CTkFrame(self, fg_color=BG)
        btn_row.grid(row=3, column=0, columnspan=2, sticky="w", padx=8, pady=4)
        ctk.CTkButton(btn_row, text="Load from File", fg_color=BG_BUTTON, hover_color=ACCENT,
                       text_color=TEXT, command=self._load_file).pack(side="left", padx=4)
        ctk.CTkButton(btn_row, text="Format JSON", fg_color=BG_BUTTON, hover_color=ACCENT,
                       text_color=TEXT, command=self._format_json).pack(side="left", padx=4)
        ctk.CTkButton(btn_row, text="Validate JSON", fg_color=BG_BUTTON, hover_color=ACCENT,
                       text_color=TEXT, command=self._validate_json).pack(side="left", padx=4)

    def _load_file(self):
        from tkinter import filedialog
        path = filedialog.askopenfilename(
            title="Load ComfyUI Workflow JSON",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if path:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = f.read()
                # Try to parse and re-format
                parsed = json.loads(data)
                data = json.dumps(parsed, indent=2)
                self._json_editor.delete("1.0", "end")
                self._json_editor.insert("1.0", data)
            except Exception as e:
                self._show_toast(f"Error: {e}")

    def _format_json(self):
        raw = self._json_editor.get("1.0", "end").strip()
        try:
            parsed = json.loads(raw)
            formatted = json.dumps(parsed, indent=2)
            self._json_editor.delete("1.0", "end")
            self._json_editor.insert("1.0", formatted)
        except json.JSONDecodeError as e:
            self._show_toast(f"Invalid JSON: {e}")

    def _validate_json(self):
        raw = self._json_editor.get("1.0", "end").strip()
        try:
            json.loads(raw)
            self._show_toast("JSON is valid!")
        except json.JSONDecodeError as e:
            self._show_toast(f"Invalid JSON at line {e.lineno}: {e.msg}")

    def _show_toast(self, msg: str):
        toast = ctk.CTkToplevel(self)
        toast.overrideredirect(True)
        toast.attributes("-topmost", True)
        toast.configure(fg_color=BG_CARD)
        x = self.winfo_rootx() + 50
        y = self.winfo_rooty() + 50
        toast.geometry(f"+{x}+{y}")
        ctk.CTkLabel(toast, text=msg, text_color=TEXT, font=(FONT_FAMILY, 12),
                      wraplength=400).pack(padx=16, pady=12)
        toast.after(3000, toast.destroy)

    def load_preset(self, preset: dict):
        super().load_preset(preset)
        d = preset.get("data", {})
        self._fields["label"].set(preset.get("label", ""))
        self._json_editor.delete("1.0", "end")
        raw = d.get("workflow_json", "{}")
        if isinstance(raw, dict):
            raw = json.dumps(raw, indent=2)
        self._json_editor.insert("1.0", raw)

    def save_to_preset(self) -> bool:
        if not self._preset:
            return False
        self._preset["label"] = self._fields["label"].get()
        d = self._preset.setdefault("data", {})
        d["workflow_json"] = self._json_editor.get("1.0", "end").strip()
        return True


# =========================================================================
# Main Application
# =========================================================================

class SpellmakerApp(ctk.CTk):
    """Main Spellmaker window with sidebar, preset list, and editor panel."""

    def __init__(self):
        super().__init__()
        self.title("Spellmaker -- Preset Editor for Spellcaster")
        self.geometry("1280x800")
        self.minsize(960, 600)
        self.configure(fg_color=BG)

        # Data
        self.spellbook = Spellbook()
        self.client = ComfyUIClient()
        self._selected_type: str = "model_preset"
        self._selected_preset: dict | None = None
        self._current_editor: BaseEditor | None = None
        self._preset_buttons: list[ctk.CTkFrame] = []
        self._server_connected = False

        # Layout: 3-column
        self.grid_columnconfigure(0, weight=0, minsize=200)  # sidebar
        self.grid_columnconfigure(1, weight=1, minsize=280)  # preset list
        self.grid_columnconfigure(2, weight=2, minsize=400)  # editor
        self.grid_rowconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=0)  # bottom toolbar

        self._build_sidebar()
        self._build_preset_list()
        self._build_editor_panel()
        self._build_bottom_toolbar()

        # Load initial view
        self._on_category_select("model_preset")

    # ── Sidebar ─────────────────────────────────────────────────────────

    def _build_sidebar(self):
        sidebar = ctk.CTkFrame(self, fg_color=BG_SIDEBAR, width=200, corner_radius=0)
        sidebar.grid(row=0, column=0, sticky="ns", rowspan=2)
        sidebar.grid_propagate(False)

        # Title
        title_frame = ctk.CTkFrame(sidebar, fg_color=BG_SIDEBAR)
        title_frame.pack(fill="x", padx=12, pady=(16, 4))
        ctk.CTkLabel(title_frame, text="Spellmaker", text_color=ACCENT,
                      font=(FONT_FAMILY, 20, "bold")).pack(anchor="w")
        ctk.CTkLabel(title_frame, text="Preset & Workflow Editor", text_color=TEXT_DIM,
                      font=(FONT_FAMILY, 11)).pack(anchor="w")

        # Separator
        ctk.CTkFrame(sidebar, fg_color=BORDER, height=1).pack(fill="x", padx=12, pady=12)

        # Category buttons
        self._cat_buttons: dict[str, ctk.CTkButton] = {}
        for ptype in PRESET_TYPES:
            label = PRESET_TYPE_LABELS[ptype]
            btn = ctk.CTkButton(
                sidebar, text=f"  {label}", anchor="w", height=36,
                fg_color="transparent", hover_color=BG_CARD_HOVER,
                text_color=TEXT, font=(FONT_FAMILY, 13),
                command=lambda t=ptype: self._on_category_select(t),
            )
            btn.pack(fill="x", padx=8, pady=1)
            self._cat_buttons[ptype] = btn

        # Spacer
        ctk.CTkFrame(sidebar, fg_color=BG_SIDEBAR).pack(fill="both", expand=True)

        # Stats
        self._stats_label = ctk.CTkLabel(sidebar, text="0 presets", text_color=TEXT_DIM,
                                           font=(FONT_FAMILY, 11))
        self._stats_label.pack(padx=12, pady=(4, 12), anchor="w")

    def _on_category_select(self, ptype: str):
        self._selected_type = ptype
        # Highlight active category
        for t, btn in self._cat_buttons.items():
            if t == ptype:
                btn.configure(fg_color=ACCENT, text_color="white")
            else:
                btn.configure(fg_color="transparent", text_color=TEXT)
        self._refresh_preset_list()
        self._clear_editor()
        self._update_stats()

    # ── Preset List (center panel) ──────────────────────────────────────

    def _build_preset_list(self):
        self._list_frame = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        self._list_frame.grid(row=0, column=1, sticky="nsew")
        self._list_frame.grid_columnconfigure(0, weight=1)
        self._list_frame.grid_rowconfigure(1, weight=1)

        # Header row
        header = ctk.CTkFrame(self._list_frame, fg_color=BG)
        header.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 4))
        self._list_title = ctk.CTkLabel(header, text="Model Presets", text_color=TEXT,
                                          font=(FONT_FAMILY, 16, "bold"))
        self._list_title.pack(side="left")
        ctk.CTkButton(header, text="+ New", width=80, fg_color=ACCENT, hover_color=ACCENT_DIM,
                       text_color="white", font=(FONT_FAMILY, 12), command=self._new_preset
                       ).pack(side="right", padx=4)

        # Scrollable list
        self._preset_scroll = ctk.CTkScrollableFrame(self._list_frame, fg_color=BG)
        self._preset_scroll.grid(row=1, column=0, sticky="nsew", padx=4, pady=4)

    def _refresh_preset_list(self):
        # Clear old
        for w in self._preset_scroll.winfo_children():
            w.destroy()
        self._preset_buttons.clear()

        self._list_title.configure(text=PRESET_TYPE_LABELS.get(self._selected_type, "Presets"))

        presets = self.spellbook.by_type(self._selected_type)
        if not presets:
            ctk.CTkLabel(self._preset_scroll, text="No presets yet.\nClick '+ New' to create one.",
                          text_color=TEXT_DIM, font=(FONT_FAMILY, 13)).pack(pady=30)
            return

        for preset in presets:
            card = self._make_preset_card(preset)
            card.pack(fill="x", pady=2, padx=4)
            self._preset_buttons.append(card)

    def _make_preset_card(self, preset: dict) -> ctk.CTkFrame:
        card = ctk.CTkFrame(self._preset_scroll, fg_color=BG_CARD, corner_radius=6, height=50)
        card.pack_propagate(False)

        # Left: label + type badge
        left = ctk.CTkFrame(card, fg_color="transparent")
        left.pack(side="left", fill="both", expand=True, padx=8, pady=6)

        label = preset.get("label", "Untitled")
        lbl = ctk.CTkLabel(left, text=label, text_color=TEXT,
                            font=(FONT_FAMILY, 13, "bold"), anchor="w")
        lbl.pack(anchor="w")

        source = preset.get("source", "user")
        badge_color = ACCENT_DIM if source == "builtin" else BG_BUTTON
        badge_text = source
        enabled = preset.get("enabled", True)
        if not enabled:
            badge_text += " (disabled)"
            badge_color = "#4A3060"

        badge = ctk.CTkLabel(left, text=badge_text, text_color=TEXT_DIM,
                              font=(FONT_FAMILY, 10), fg_color=badge_color,
                              corner_radius=4, width=60, height=18)
        badge.pack(anchor="w", pady=(1, 0))

        # Right: action buttons
        right = ctk.CTkFrame(card, fg_color="transparent")
        right.pack(side="right", padx=8, pady=6)

        ctk.CTkButton(right, text="Edit", width=50, height=26,
                       fg_color=BG_BUTTON, hover_color=ACCENT,
                       text_color=TEXT, font=(FONT_FAMILY, 11),
                       command=lambda p=preset: self._edit_preset(p)).pack(side="left", padx=2)
        ctk.CTkButton(right, text="Clone", width=50, height=26,
                       fg_color=BG_BUTTON, hover_color=ACCENT,
                       text_color=TEXT, font=(FONT_FAMILY, 11),
                       command=lambda p=preset: self._clone_preset(p)).pack(side="left", padx=2)
        ctk.CTkButton(right, text="Del", width=40, height=26,
                       fg_color="#3A1530", hover_color=DANGER,
                       text_color="#E08090", font=(FONT_FAMILY, 11),
                       command=lambda p=preset: self._delete_preset(p)).pack(side="left", padx=2)

        # Enable toggle
        en_var = ctk.BooleanVar(value=preset.get("enabled", True))

        def toggle_enabled(p=preset, v=en_var):
            p["enabled"] = v.get()

        ctk.CTkCheckBox(right, text="", variable=en_var, width=24,
                         fg_color=BG_BUTTON, hover_color=ACCENT,
                         checkmark_color="white", border_color=BORDER,
                         command=lambda: toggle_enabled()).pack(side="left", padx=4)

        # Click card to edit
        for widget in [card, left, lbl]:
            widget.bind("<Button-1>", lambda e, p=preset: self._edit_preset(p))

        return card

    def _new_preset(self):
        preset = _default_preset(self._selected_type)
        preset["label"] = f"New {PRESET_TYPE_LABELS.get(self._selected_type, 'Preset')}"
        self.spellbook.add(preset)
        self._refresh_preset_list()
        self._edit_preset(preset)

    def _clone_preset(self, preset: dict):
        new = self.spellbook.clone(preset)
        self._refresh_preset_list()
        self._edit_preset(new)

    def _delete_preset(self, preset: dict):
        self.spellbook.remove(preset)
        if self._selected_preset is preset:
            self._selected_preset = None
            self._clear_editor()
        self._refresh_preset_list()
        self._update_stats()

    # ── Editor Panel (right) ────────────────────────────────────────────

    def _build_editor_panel(self):
        self._editor_container = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        self._editor_container.grid(row=0, column=2, sticky="nsew")
        self._editor_container.grid_columnconfigure(0, weight=1)
        self._editor_container.grid_rowconfigure(1, weight=1)

        # Header
        self._editor_header = ctk.CTkFrame(self._editor_container, fg_color=BG)
        self._editor_header.grid(row=0, column=0, sticky="ew", padx=12, pady=(8, 0))
        self._editor_title = ctk.CTkLabel(self._editor_header, text="Select a preset to edit",
                                            text_color=TEXT_DIM, font=(FONT_FAMILY, 14))
        self._editor_title.pack(side="left")

        # Save button
        self._save_btn = ctk.CTkButton(self._editor_header, text="Save", width=80,
                                         fg_color=ACCENT, hover_color=ACCENT_DIM,
                                         text_color="white", font=(FONT_FAMILY, 13, "bold"),
                                         command=self._save_current)
        self._save_btn.pack(side="right", padx=4)
        self._save_btn.pack_forget()  # hidden until editing

        # Test button
        self._test_btn = ctk.CTkButton(self._editor_header, text="Test on ComfyUI", width=120,
                                         fg_color=BG_BUTTON, hover_color=ACCENT,
                                         text_color=TEXT, font=(FONT_FAMILY, 12),
                                         command=self._test_workflow)
        self._test_btn.pack(side="right", padx=4)
        self._test_btn.pack_forget()

        # Editor placeholder
        self._editor_inner = ctk.CTkFrame(self._editor_container, fg_color=BG)
        self._editor_inner.grid(row=1, column=0, sticky="nsew", padx=8, pady=8)

        self._placeholder = ctk.CTkLabel(self._editor_inner,
                                           text="Select a preset from the list\nor create a new one.",
                                           text_color=TEXT_DIM, font=(FONT_FAMILY, 14),
                                           justify="center")
        self._placeholder.pack(expand=True)

    def _clear_editor(self):
        self._selected_preset = None
        if self._current_editor:
            self._current_editor.destroy()
            self._current_editor = None
        self._editor_title.configure(text="Select a preset to edit")
        self._save_btn.pack_forget()
        self._test_btn.pack_forget()
        # Show placeholder
        for w in self._editor_inner.winfo_children():
            w.destroy()
        self._placeholder = ctk.CTkLabel(self._editor_inner,
                                           text="Select a preset from the list\nor create a new one.",
                                           text_color=TEXT_DIM, font=(FONT_FAMILY, 14),
                                           justify="center")
        self._placeholder.pack(expand=True)

    def _edit_preset(self, preset: dict):
        # Save current first if there is one
        if self._current_editor and self._selected_preset:
            self._current_editor.save_to_preset()

        self._selected_preset = preset
        ptype = preset.get("type", "")

        # Clear old editor
        for w in self._editor_inner.winfo_children():
            w.destroy()
        self._current_editor = None

        # Title
        self._editor_title.configure(text=f"Editing: {preset.get('label', 'Preset')}")
        self._save_btn.pack(side="right", padx=4)
        self._test_btn.pack(side="right", padx=4)

        # Create appropriate editor
        editor_map = {
            "model_preset": lambda: ModelPresetEditor(self._editor_inner),
            "inpaint_preset": lambda: InpaintPresetEditor(self._editor_inner, client=self.client),
            "scene_preset": lambda: ScenePresetEditor(self._editor_inner),
            "video_preset": lambda: VideoPresetEditor(self._editor_inner, client=self.client),
            "wan_model": lambda: WanModelEditor(self._editor_inner),
            "klein_model": lambda: KleinModelEditor(self._editor_inner),
            "iclight_preset": lambda: ICLightPresetEditor(self._editor_inner),
            "custom_workflow": lambda: CustomWorkflowEditor(self._editor_inner),
        }

        factory = editor_map.get(ptype)
        if factory:
            editor = factory()
            editor.pack(fill="both", expand=True)
            editor.load_preset(preset)
            self._current_editor = editor
        else:
            ctk.CTkLabel(self._editor_inner, text=f"Unknown preset type: {ptype}",
                          text_color=DANGER, font=(FONT_FAMILY, 13)).pack(pady=20)

    def _save_current(self):
        if self._current_editor and self._selected_preset:
            ok = self._current_editor.save_to_preset()
            if ok:
                self._refresh_preset_list()
                self._editor_title.configure(
                    text=f"Editing: {self._selected_preset.get('label', 'Preset')}")
                self._show_toast("Preset saved to memory. Use 'Export Spellbook' to write to disk.")
            else:
                self._show_toast("Error: invalid field values. Check numbers.", error=True)

    def _test_workflow(self):
        """Send a test prompt to the ComfyUI server if connected."""
        if not self._server_connected:
            self._show_toast("Not connected to ComfyUI. Connect first.", error=True)
            return
        if not self._selected_preset:
            return

        ptype = self._selected_preset.get("type", "")
        data = self._selected_preset.get("data", {})

        # Build a minimal test workflow based on type
        if ptype == "model_preset":
            wf = {
                "1": {"class_type": "CheckpointLoaderSimple",
                      "inputs": {"ckpt_name": data.get("ckpt", "")}},
                "2": {"class_type": "CLIPTextEncode",
                      "inputs": {"text": data.get("prompt_hint", "test"), "clip": ["1", 1]}},
                "3": {"class_type": "CLIPTextEncode",
                      "inputs": {"text": data.get("negative_hint", ""), "clip": ["1", 1]}},
                "4": {"class_type": "EmptyLatentImage",
                      "inputs": {"width": data.get("width", 512),
                                 "height": data.get("height", 512), "batch_size": 1}},
                "5": {"class_type": "KSampler",
                      "inputs": {
                          "model": ["1", 0], "positive": ["2", 0], "negative": ["3", 0],
                          "latent_image": ["4", 0],
                          "seed": 42, "steps": data.get("steps", 20),
                          "cfg": data.get("cfg", 7.0), "denoise": 1.0,
                          "sampler_name": data.get("sampler", "euler"),
                          "scheduler": data.get("scheduler", "normal"),
                      }},
                "6": {"class_type": "VAEDecode",
                      "inputs": {"samples": ["5", 0], "vae": ["1", 2]}},
                "7": {"class_type": "SaveImage",
                      "inputs": {"images": ["6", 0], "filename_prefix": "spellmaker_test"}},
            }
        elif ptype == "custom_workflow":
            raw = data.get("workflow_json", "{}")
            try:
                wf = json.loads(raw) if isinstance(raw, str) else raw
            except json.JSONDecodeError:
                self._show_toast("Invalid workflow JSON.", error=True)
                return
        else:
            self._show_toast("Test only available for model_preset and custom_workflow.", error=True)
            return

        def do_queue():
            try:
                result = self.client.queue_prompt(wf)
                prompt_id = result.get("prompt_id", "unknown")
                self.after(0, lambda: self._show_toast(f"Queued! Prompt ID: {prompt_id}"))
            except Exception as e:
                self.after(0, lambda: self._show_toast(f"Queue error: {e}", error=True))

        threading.Thread(target=do_queue, daemon=True).start()
        self._show_toast("Sending to ComfyUI...")

    # ── Bottom Toolbar ──────────────────────────────────────────────────

    def _build_bottom_toolbar(self):
        toolbar = ctk.CTkFrame(self, fg_color=BG_SIDEBAR, height=56, corner_radius=0)
        toolbar.grid(row=1, column=1, columnspan=2, sticky="ew")
        toolbar.pack_propagate(False)

        inner = ctk.CTkFrame(toolbar, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=8, pady=8)

        # Left buttons
        ctk.CTkButton(inner, text="Import Workflow", width=130,
                       fg_color=BG_BUTTON, hover_color=ACCENT, text_color=TEXT,
                       font=(FONT_FAMILY, 12), command=self._import_workflow
                       ).pack(side="left", padx=4)

        ctk.CTkButton(inner, text="Export Spellbook", width=130,
                       fg_color=BG_BUTTON, hover_color=ACCENT, text_color=TEXT,
                       font=(FONT_FAMILY, 12), command=self._export_spellbook
                       ).pack(side="left", padx=4)

        ctk.CTkButton(inner, text="Inject into GIMP", width=120,
                       fg_color=BG_BUTTON, hover_color=ACCENT, text_color=TEXT,
                       font=(FONT_FAMILY, 12), command=self._inject_gimp
                       ).pack(side="left", padx=4)

        ctk.CTkButton(inner, text="Inject into Darktable", width=140,
                       fg_color=BG_BUTTON, hover_color=ACCENT, text_color=TEXT,
                       font=(FONT_FAMILY, 12), command=self._inject_darktable
                       ).pack(side="left", padx=4)

        # Right side: ComfyUI connection
        right = ctk.CTkFrame(inner, fg_color="transparent")
        right.pack(side="right")

        self._status_dot = ctk.CTkLabel(right, text="", width=12, height=12,
                                          fg_color="#804040", corner_radius=6)
        self._status_dot.pack(side="right", padx=(8, 0))
        _ToolTip(self._status_dot, "ComfyUI connection status")

        ctk.CTkButton(right, text="Connect", width=80,
                       fg_color=BG_BUTTON, hover_color=ACCENT, text_color=TEXT,
                       font=(FONT_FAMILY, 12), command=self._connect_server
                       ).pack(side="right", padx=4)

        self._server_url_var = ctk.StringVar(value="http://127.0.0.1:8188")
        server_entry = ctk.CTkEntry(right, textvariable=self._server_url_var, width=220,
                                      fg_color=BG_ENTRY, text_color=TEXT, border_color=BORDER,
                                      font=(FONT_FAMILY, 12), placeholder_text="ComfyUI URL")
        server_entry.pack(side="right", padx=4)
        _ToolTip(server_entry, "ComfyUI server URL (e.g., http://127.0.0.1:8188)")

        ctk.CTkLabel(right, text="Server:", text_color=TEXT_DIM,
                      font=(FONT_FAMILY, 12)).pack(side="right", padx=(4, 0))

    # ── Toolbar actions ─────────────────────────────────────────────────

    def _connect_server(self):
        url = self._server_url_var.get().strip()
        if not url:
            return
        self.client = ComfyUIClient(url)

        def do_connect():
            ok = self.client.ping()
            if ok:
                try:
                    self.client.fetch_object_info()
                except Exception:
                    pass
            self.after(0, lambda: self._on_connect_result(ok))

        self._show_toast("Connecting...")
        threading.Thread(target=do_connect, daemon=True).start()

    def _on_connect_result(self, ok: bool):
        self._server_connected = ok
        if ok:
            self._status_dot.configure(fg_color=SUCCESS)
            n_loras = len(self.client.list_loras())
            n_ckpts = len(self.client.list_checkpoints())
            self._show_toast(f"Connected! Found {n_ckpts} checkpoints, {n_loras} LoRAs.")
        else:
            self._status_dot.configure(fg_color=DANGER)
            self._show_toast("Could not connect to ComfyUI server.", error=True)

    def _import_workflow(self):
        from tkinter import filedialog
        path = filedialog.askopenfilename(
            title="Import ComfyUI Workflow",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except Exception as e:
            self._show_toast(f"Error reading file: {e}", error=True)
            return

        # If the JSON has a "prompt" key (full API format), unwrap it
        if "prompt" in raw and isinstance(raw["prompt"], dict):
            raw = raw["prompt"]

        parsed = parse_comfyui_workflow(raw)

        # Show preview dialog
        preview = WorkflowPreviewDialog(self, parsed)
        self.wait_window(preview)

        if preview.accepted:
            preset = workflow_to_preset(parsed)
            # If the user imported a workflow that has the raw JSON too, store it
            if preset["type"] == "custom_workflow":
                preset["data"]["workflow_json"] = json.dumps(raw, indent=2)
            self.spellbook.add(preset)
            self._selected_type = preset["type"]
            self._on_category_select(self._selected_type)
            self._edit_preset(preset)
            self._show_toast(f"Imported as {PRESET_TYPE_LABELS.get(preset['type'], preset['type'])}")

    def _export_spellbook(self):
        # Save current editor state first
        if self._current_editor and self._selected_preset:
            self._current_editor.save_to_preset()
        self.spellbook.save()
        self._show_toast(f"Spellbook saved to {SPELLBOOK_PATH}")

    def _inject_gimp(self):
        if self._current_editor and self._selected_preset:
            self._current_editor.save_to_preset()
        result = _inject_into_gimp(self.spellbook.presets)
        self._show_toast(result)

    def _inject_darktable(self):
        if self._current_editor and self._selected_preset:
            self._current_editor.save_to_preset()
        result = _inject_into_darktable(self.spellbook.presets)
        self._show_toast(result)

    # ── Helpers ─────────────────────────────────────────────────────────

    def _update_stats(self):
        total = len(self.spellbook.presets)
        enabled = sum(1 for p in self.spellbook.presets if p.get("enabled", True))
        self._stats_label.configure(text=f"{total} presets ({enabled} enabled)")

    def _show_toast(self, msg: str, error: bool = False):
        toast = ctk.CTkToplevel(self)
        toast.overrideredirect(True)
        toast.attributes("-topmost", True)
        bg_col = "#2A0A1A" if error else BG_CARD
        toast.configure(fg_color=bg_col)

        # Position near bottom-center of main window
        self.update_idletasks()
        wx = self.winfo_rootx()
        wy = self.winfo_rooty()
        ww = self.winfo_width()
        wh = self.winfo_height()
        toast_w = min(len(msg) * 8 + 40, 600)
        toast_h = 44
        x = wx + (ww - toast_w) // 2
        y = wy + wh - 100

        toast.geometry(f"{toast_w}x{toast_h}+{x}+{y}")

        text_color = DANGER if error else TEXT
        ctk.CTkLabel(toast, text=msg, text_color=text_color,
                      font=(FONT_FAMILY, 12), wraplength=toast_w - 24).pack(expand=True, padx=12)

        toast.after(3500, toast.destroy)


# =========================================================================
# Entry point
# =========================================================================

def main():
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("dark-blue")
    app = SpellmakerApp()
    app.mainloop()


if __name__ == "__main__":
    main()
