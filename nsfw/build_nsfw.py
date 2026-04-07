#!/usr/bin/env python3
"""
Spellcaster NSFW Builder - Multi-stage pipeline to create NSFW-enabled distributions.

ARCHITECTURE:
=============

The NSFW builder implements a patching architecture that transforms the public
Spellcaster distribution into NSFW editions by injecting adult-themed content
(LoRAs, presets, prompts, models, visual assets) into key plugin files and
configurations. The process is deterministic and reversible (NSFW content only
affects specific injection points in plugin code and JSON files).

PIPELINE STAGES:

1. STAGING (_create_staging):
   - Copy entire spellcaster/ directory to nsfw/staging/
   - Staging dir becomes the build artifact that will be patched

2. PATCHING (_apply_all_patches):
   A. patch_manifest(dest_dir):
      - Inject NSFW LoRA entries into manifest.json features.inpaint.models
      - Add Wan NSFW unet models and LoRAs
      - Makes NSFW content discoverable by the installer

   B. patch_gimp_plugin(dest_dir):
      - Inject NSFW inpaint presets into INPAINT_REFINEMENTS list
      - Inject NSFW Wan video presets into WAN_VIDEO_PRESETS list
      - Inject NSFW Director and Director Duo scripts into DIRECTOR_SCRIPTS
      - Uses regex to find list boundaries and insert before closing brackets

   C. patch_darktable_plugin(dest_dir):
      - Inject NSFW inpaint presets into Lua INPAINT_REFINEMENTS table
      - Inject NSFW Wan video presets into Lua WAN_VIDEO_PRESETS table
      - Lua syntax matching (tables, field notation)

   D. patch_klein_nsfw(dest_dir):
      - Inject Klein Inpaint NSFW task presets into INPAINT_PRESETS dict
      - Inject Klein Re-poser NSFW poses into POSE_PRESETS dict
      - Inject Klein Re-poser NSFW interactions into MULTI_CHAR_PRESETS dict
      - Inject Klein Outpaint NSFW presets into KLEIN_OUTPAINT_PRESETS dict
      - Inject NSFW LoRA metadata into LORA_METADATA dict
      - Uses string anchors to locate injection points

   E. patch_version(dest_dir):
      - Update VERSION from "1.0" to "1.0-NSFW" in install.py, manual_update.py
      - Update manifest.json version field

   F. patch_nsfw_assets(dest_dir):
      - Replace visual assets (splash GIFs, banners, icons, headers)
      - Sources: nsfw_splash.gif, nsfw_splash.png, nsfw_icon.png, nsfw_header.png
      - Targets include GIFs, PNGs, JPEGs across GIMP, Darktable, and asset dirs
      - Uses PIL for resizing (RGBA for icons, RGB for JPEGs)

   G. patch_auth_auto_update(dest_dir):
      - Redirect auto-update URLs from public repo to private NSFW repo
      - Inject GitHub PAT token into HTTP requests for private repo access
      - Updates custom check functions and auto-update subroutines

   H. patch_force_all_on(dest_dir):
      - Patch installer to mark all NSFW features as "required" (force-enable)
      - Modifies install.py installation logic

   I. patch_wan_nsfw_preset(dest_dir):
      - Add "Wan Enhanced NSFW SVI" preset to the GIMP plugin
      - Configures Wan model with NSFW-tuned settings

3. VALIDATION (validate_patches):
   - Check for injection markers in patched files
   - Verify NSFW repo redirect in auto-update code
   - Verify NSFW version strings in manifest
   - Verify visual asset replacement by comparing file sizes

4. EXECUTABLE BUILD (build_exe):
   - Use PyInstaller to package staging dir into .exe
   - Output: nsfw/dist/spellcaster-nsfw-installer.exe

5. GITHUB PUSH (push_to_nsfw_repo):
   - Clone private NSFW repo (with GitHub token auth)
   - Copy patched files into clone
   - Commit and push to private repository

CONTENT INJECTION PATTERNS:

The patching uses three main injection strategies:

A. REGEX BOUNDARY MATCHING (Python/Lua lists):
   - Pattern: Find 'NAME = [ ... ]' and insert before closing bracket
   - Example: INPAINT_REFINEMENTS list in Python plugins
   - Uses re.search with re.DOTALL to match across newlines
   - Locates '^\]' (bracket on own line) and inserts injection before it

B. STRING ANCHOR MATCHING (dict entries):
   - Pattern: Find known entry and inject after its closing comma
   - Example: Find '"Prone / face down":' and inject after next newline
   - Works for both Python dicts and Lua tables
   - More robust than regex for complex nested structures

C. MARKER REPLACEMENT (pre-placed hooks):
   - Pattern: Find special marker comment and replace it with content
   - Example: Replace '# -- NSFW_INJECTION_POINT --' with actual presets
   - Assumes hooks are pre-placed in base code
   - Safest method but requires coordination with base plugin code

OUTPUT:
-------
    nsfw/dist/spellcaster-nsfw-installer.exe    (PyInstaller artifact)
    nsfw/staging/                                  (patched working dir)
    + private NSFW repo updated with patched files

USAGE:
------
    python nsfw/build_nsfw.py                 # Full pipeline: staging → patch → validate → build exe
    python nsfw/build_nsfw.py --patch         # Patch only (no exe build)
    python nsfw/build_nsfw.py --no-push       # Build exe but don't push to private repo

DEPENDENCIES:
   - PIL/Pillow (for image resizing/conversion)
   - PyInstaller (for exe building, if --patch not specified)
   - git (for repo operations)
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent          # nsfw/
ROOT = HERE.parent                               # spellcaster/
NSFW_DIST = HERE / "dist"

# ─── NSFW content to inject ─────────────────────────────────────────────

def load_nsfw_data():
    """Load all NSFW content preset files from nsfw/ directory.

    Loads three JSON files defining NSFW content for injection:
      - nsfw_loras.json: LoRA model entries for various architectures
      - nsfw_presets_inpaint.json: Inpaint refinement presets (prompts, denoise, etc.)
      - nsfw_presets_video.json: Wan video generation presets and Director scripts

    Returns:
        tuple: (loras_dict, inpaint_dict, video_dict)
    """
    with open(HERE / "nsfw_loras.json", encoding="utf-8") as f:
        loras = json.load(f)
    with open(HERE / "nsfw_presets_inpaint.json", encoding="utf-8") as f:
        inpaint = json.load(f)
    with open(HERE / "nsfw_presets_video.json", encoding="utf-8") as f:
        video = json.load(f)
    return loras, inpaint, video


def load_klein_nsfw_data():
    """Load NSFW Klein preset files for inpaint, re-poser, and outpaint tools.

    Loads nsfw_klein_presets.json containing task presets, poses, interactions,
    outpaint presets, and LoRA metadata for Klein-specific workflows.

    Returns:
        dict: Klein NSFW presets organized by tool (inpaint, repose, outpaint, loras)
    """
    with open(HERE / "nsfw_klein_presets.json", encoding="utf-8") as f:
        return json.load(f)


# ─── Patch manifest.json ────────────────────────────────────────────────

def patch_manifest(dest_dir):
    """Inject NSFW LoRA and model entries into manifest.json.

    Modifies manifest.json to add NSFW content discoverable by installer:
      1. Add NSFW LoRAs to features.inpaint.models (each architecture category)
      2. Add Wan NSFW unet models to features.wan_i2v.models.unet
      3. Add Wan NSFW LoRAs to features.wan_i2v.models.loras

    Each entry is marked optional=true and tagged with "NSFW: ..." note.

    Args:
        dest_dir (Path): Root of staging directory to patch
    """
    loras, _, _ = load_nsfw_data()
    manifest_path = dest_dir / "installer" / "manifest.json"
    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)

    # Add NSFW LoRAs to the inpaint feature's loras_klein section
    inpaint = manifest["features"]["inpaint"]
    nsfw_models = loras["nsfw_loras"]

    # Add NSFW lora entries to existing categories
    for arch_key in ["sdxl", "flux1dev", "flux2klein", "illustrious_pony"]:
        if arch_key in nsfw_models:
            manifest_key = f"loras_{arch_key}" if arch_key != "illustrious_pony" else "loras_illustrious_pony"
            if manifest_key not in inpaint.get("models", {}):
                # Create the category if it doesn't exist
                if "models" not in inpaint:
                    inpaint["models"] = {}
                inpaint["models"][manifest_key] = []
            for lora in nsfw_models[arch_key]:
                entry = {
                    "path": lora["path"],
                    "url": None,
                    "page_url": "",
                    "size_mb": 144,
                    "optional": True,
                    "note": f"NSFW: {lora['note']}"
                }
                inpaint["models"][manifest_key].append(entry)

    # Add NSFW Wan models to wan_i2v feature
    wan = manifest["features"].get("wan_i2v", {})
    if "models" not in wan:
        wan["models"] = {}
    if "unet" not in wan["models"]:
        wan["models"]["unet"] = []
    for model in nsfw_models.get("wan_nsfw_models", []):
        wan["models"]["unet"].append({
            "path": model["path"],
            "url": None,
            "page_url": "",
            "size_mb": 8200,
            "optional": True,
            "note": f"NSFW: {model['note']}"
        })

    # Add NSFW Wan LoRAs
    if "loras" not in wan["models"]:
        wan["models"]["loras"] = []
    for lora in nsfw_models.get("wan_i2v", []):
        wan["models"]["loras"].append({
            "path": lora["path"],
            "url": None,
            "page_url": "",
            "size_mb": 80,
            "optional": True,
            "note": f"NSFW: {lora['note']}"
        })

    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    print(f"  Patched manifest: added NSFW LoRAs + Wan models")


# ─── Patch GIMP plugin ──────────────────────────────────────────────────

def patch_gimp_plugin(dest_dir):
    """Inject NSFW presets into the GIMP ComfyUI connector plugin.

    Injects three types of NSFW content into comfyui-connector.py:

    1. NSFW INPAINT PRESETS:
       - Formats preset dicts for Python list syntax
       - Locates INPAINT_REFINEMENTS list using regex (matches 'INPAINT_REFINEMENTS = [ ... ]')
       - Inserts before closing bracket, marked with comment

    2. NSFW WAN VIDEO PRESETS:
       - Formats Wan video preset dicts (label, prompt, negative, loras, strength)
       - Locates WAN_VIDEO_PRESETS list using regex
       - Inserts before closing bracket

    3. NSFW DIRECTOR & DUO SCRIPTS:
       - Formats director script dicts with step sequences
       - Uses marker-based injection: replaces '# -- NSFW_DIRECTOR_INJECTION_POINT --'
       - Uses marker for Duo scripts similarly

    Args:
        dest_dir (Path): Root of staging directory to patch
    """
    _, inpaint, video = load_nsfw_data()
    gimp_path = dest_dir / "plugins" / "gimp" / "comfyui-connector" / "comfyui-connector.py"

    with open(gimp_path, encoding="utf-8") as f:
        content = f.read()

    # Build NSFW inpaint preset Python code
    presets_code = "\n    # ── NSFW Inpaint Presets (auto-injected) ──────────────────────\n"
    for p in inpaint["nsfw_inpaint_presets"]:
        loras_dict = {}
        for arch, lora_list in p.get("loras", {}).items():
            loras_dict[arch] = [(l[0], l[1], l[2]) for l in lora_list]
        # Fill missing architectures with empty lists
        for arch in ["sdxl", "sd15", "zit", "flux1dev", "flux2klein", "flux_kontext", "illustrious"]:
            if arch not in loras_dict:
                loras_dict[arch] = []
        presets_code += f"""    {{
        "label": {repr(p["label"])},
        "prompt": {repr(p["prompt"])},
        "negative": {repr(p["negative"])},
        "denoise": {p["denoise"]},
        "cfg_boost": {p["cfg_boost"]},
        "steps_override": {p["steps_override"]},
        "loras": {repr(loras_dict)},
    }},
"""

    # Find the end of INPAINT_REFINEMENTS list and inject before the closing ]
    marker = "# ── NSFW_INJECTION_POINT ──"
    if marker in content:
        print("  GIMP plugin already patched (marker found)")
    else:
        import re
        # The list is INPAINT_REFINEMENTS = [ ... ] (Python list of dicts)
        # Find the closing ] that ends the list — it's on its own line after the last entry
        match = re.search(r'(INPAINT_REFINEMENTS\s*=\s*\[.*?)(^\])', content, re.DOTALL | re.MULTILINE)
        if match:
            insert_pos = match.start(2)
            injection = f"\n    {marker}\n{presets_code}\n"
            content = content[:insert_pos] + injection + content[insert_pos:]
            print(f"  Injected {len(inpaint['nsfw_inpaint_presets'])} NSFW inpaint presets into GIMP plugin")
        else:
            print("  WARNING: Could not find INPAINT_REFINEMENTS list in GIMP plugin")

    # Inject NSFW Wan video presets into WAN_VIDEO_PRESETS
    wan_presets_code = "\n    # ── NSFW Wan Video Presets (auto-injected) ────────────────────\n"
    for p in video["nsfw_wan_presets"]:
        wan_presets_code += f"""    {{
        "label": "NSFW: {p["label"]}",
        "prompt": {repr(p["prompt"])},
        "negative": {repr(p["negative"])},
        "high_lora": {repr(p["high_lora"])},
        "low_lora": {repr(p["low_lora"])},
        "strength": {p["strength"]},
    }},
"""

    wan_marker = "# ── NSFW_WAN_INJECTION_POINT ──"
    if wan_marker not in content:
        match = re.search(r'(WAN_VIDEO_PRESETS\s*=\s*\[.*?)(^\])', content, re.DOTALL | re.MULTILINE)
        if match:
            insert_pos = match.start(2)
            injection = f"\n    {wan_marker}\n{wan_presets_code}\n"
            content = content[:insert_pos] + injection + content[insert_pos:]
            print(f"  Injected {len(video['nsfw_wan_presets'])} NSFW Wan video presets into GIMP plugin")

    # Inject NSFW Director scripts into DIRECTOR_SCRIPTS dict
    nsfw_director = video.get("nsfw_director_scripts", {})
    if nsfw_director:
        director_code = "\n            # ── NSFW Director Scripts (auto-injected) ──\n"
        for label, script in nsfw_director.items():
            steps_code = "[\n"
            for step in script["steps"]:
                steps_code += (
                    f'                    {{"mode": {repr(step["mode"])}, '
                    f'"prompt": {repr(step["prompt"])}, '
                    f'"negative": {repr(step["negative"])}, '
                    f'"shift": {step["shift"]}, "cfg": {step["cfg"]}, "length": {step["length"]}}},\n'
                )
            steps_code += "                ]"
            director_code += (
                f'            {repr(label)}: {{\n'
                f'                "description": {repr(script["description"])},\n'
                f'                "num_steps": {script["num_steps"]}, "variations": {script["variations"]}, '
                f'"loop_count": {script["loop_count"]},\n'
                f'                "face_reinject": {repr(script.get("face_reinject", True))},\n'
                f'                "steps": {steps_code},\n'
                f'            }},\n'
            )

        # Inject before the closing } of DIRECTOR_SCRIPTS dict.
        # Find the dict by locating "DIRECTOR_SCRIPTS = {" and matching braces.
        ds_start = content.find("DIRECTOR_SCRIPTS = {")
        if ds_start >= 0:
            depth = 0
            ds_end = ds_start
            for ci in range(ds_start, len(content)):
                if content[ci] == '{':
                    depth += 1
                elif content[ci] == '}':
                    depth -= 1
                    if depth == 0:
                        ds_end = ci
                        break
            # Insert before the closing }
            content = content[:ds_end] + director_code + content[ds_end:]
            print(f"  Injected {len(nsfw_director)} NSFW Director scripts into GIMP plugin")
        else:
            print("  WARNING: DIRECTOR_SCRIPTS dict not found in GIMP plugin")

    # Inject NSFW Director DUO scripts into DUO_SCRIPTS dict
    nsfw_duo = video.get("nsfw_director_duo_scripts", {})
    if nsfw_duo:
        duo_code = "\n            # ── NSFW Director Duo Scripts (auto-injected) ──\n"
        for label, script in nsfw_duo.items():
            steps_code = "[\n"
            for step in script["steps"]:
                steps_code += (
                    f'                    {{"mode": {repr(step["mode"])}, '
                    f'"prompt": {repr(step["prompt"])}, '
                    f'"negative": {repr(step["negative"])}, '
                    f'"shift": {step["shift"]}, "cfg": {step["cfg"]}, "length": {step["length"]}}},\n'
                )
            steps_code += "                ]"
            duo_code += (
                f'            {repr(label)}: {{\n'
                f'                "description": {repr(script["description"])},\n'
                f'                "num_steps": {script["num_steps"]}, "variations": {script["variations"]}, '
                f'"loop_count": {script["loop_count"]},\n'
                f'                "steps": {steps_code},\n'
                f'            }},\n'
            )

        # Inject before the closing } of DUO_SCRIPTS dict.
        duo_start = content.find("DUO_SCRIPTS = {")
        if duo_start >= 0:
            depth = 0
            duo_end = duo_start
            for ci in range(duo_start, len(content)):
                if content[ci] == '{':
                    depth += 1
                elif content[ci] == '}':
                    depth -= 1
                    if depth == 0:
                        duo_end = ci
                        break
            content = content[:duo_end] + duo_code + content[duo_end:]
            print(f"  Injected {len(nsfw_duo)} NSFW Director Duo scripts into GIMP plugin")

    with open(gimp_path, "w", encoding="utf-8") as f:
        f.write(content)


# ─── Patch Darktable plugin ─────────────────────────────────────────────

def patch_darktable_plugin(dest_dir):
    """Inject NSFW presets into the Darktable ComfyUI Lua plugin.

    Similar to patch_gimp_plugin but generates Lua syntax instead of Python.
    Injects two types of presets:

    1. NSFW INPAINT PRESETS:
       - Formats preset table entries with Lua syntax
       - Escapes quotes and builds loras subtable
       - Locates INPAINT_REFINEMENTS table using regex
       - Inserts before closing brace, marked with comment

    2. NSFW WAN VIDEO PRESETS:
       - Formats Wan preset table entries (Lua syntax)
       - Escapes quotes and paths
       - Locates WAN_VIDEO_PRESETS table using regex
       - Inserts before closing brace

    Args:
        dest_dir (Path): Root of staging directory to patch
    """
    _, inpaint, video = load_nsfw_data()
    lua_path = dest_dir / "plugins" / "darktable" / "comfyui_connector.lua"

    with open(lua_path, encoding="utf-8") as f:
        content = f.read()

    # Build NSFW inpaint preset Lua code
    presets_lua = "\n  -- NSFW Inpaint Presets (auto-injected)\n"
    for p in inpaint["nsfw_inpaint_presets"]:
        loras_lua_parts = []
        for arch, lora_list in p.get("loras", {}).items():
            if lora_list:
                lora_entries = ", ".join(
                    f'{{"{l[0]}", {l[1]}, {l[2]}}}'
                    for l in lora_list
                )
                loras_lua_parts.append(f'{arch} = {{ {lora_entries} }}')
        loras_lua = "{ " + ", ".join(loras_lua_parts) + " }" if loras_lua_parts else "{}"

        label = p["label"].replace('"', '\\"')
        prompt = p["prompt"].replace('"', '\\"')
        negative = p["negative"].replace('"', '\\"')

        presets_lua += f"""  {{ label = "{label}",
    prompt = "{prompt}",
    negative = "{negative}",
    denoise = {p["denoise"]}, cfg_boost = {p["cfg_boost"]}, steps_override = {p["steps_override"]},
    loras = {loras_lua} }},
"""

    # Find the INPAINT_PRESETS table end
    import re
    marker = "-- NSFW_INJECTION_POINT --"
    if marker not in content:
        match = re.search(r'(local\s+INPAINT_REFINEMENTS\s*=\s*\{.*?)(^\})', content, re.DOTALL | re.MULTILINE)
        if match:
            insert_pos = match.start(2)
            injection = f"\n  {marker}\n{presets_lua}\n"
            content = content[:insert_pos] + injection + content[insert_pos:]
            print(f"  Injected {len(inpaint['nsfw_inpaint_presets'])} NSFW inpaint presets into Darktable plugin")
        else:
            print("  WARNING: Could not find INPAINT_REFINEMENTS table in Darktable plugin")

    # Inject NSFW Wan video presets
    wan_presets_lua = "\n  -- NSFW Wan Video Presets (auto-injected)\n"
    for p in video["nsfw_wan_presets"]:
        label = f"NSFW: {p['label']}".replace('"', '\\"')
        prompt = p["prompt"].replace('"', '\\"')
        negative = p["negative"].replace('"', '\\"')
        high = p["high_lora"].replace("\\", "\\\\")
        low = p["low_lora"].replace("\\", "\\\\")
        wan_presets_lua += f"""  {{ label = "{label}",
    prompt = "{prompt}", negative = "{negative}",
    high_lora = "{high}", low_lora = "{low}", strength = {p["strength"]} }},
"""

    wan_marker = "-- NSFW_WAN_INJECTION_POINT --"
    if wan_marker not in content:
        match = re.search(r'(local\s+WAN_VIDEO_PRESETS\s*=\s*\{.*?)(^\})', content, re.DOTALL | re.MULTILINE)
        if match:
            insert_pos = match.start(2)
            injection = f"\n  {wan_marker}\n{wan_presets_lua}\n"
            content = content[:insert_pos] + injection + content[insert_pos:]
            print(f"  Injected {len(video['nsfw_wan_presets'])} NSFW Wan video presets into Darktable plugin")

    with open(lua_path, "w", encoding="utf-8") as f:
        f.write(content)


# ─── Patch Klein tools with NSFW presets ─────────────────────────────────

def patch_klein_nsfw(dest_dir):
    """Inject NSFW presets into Klein AI tools within the GIMP plugin.

    Klein tools (Inpaint, Re-poser, Outpaint) have their own preset dictionaries
    within comfyui-connector.py. This function injects NSFW-specific presets and
    LoRA metadata using string anchor matching:

    1. KLEIN INPAINT PRESETS:
       - Injects into INPAINT_PRESETS dict
       - Locates anchor: '\"(custom \\u2014 manual settings)\"'
       - Inserts NSFW task presets before the custom entry

    2. KLEIN RE-POSER POSES:
       - Injects into POSE_PRESETS dict
       - Locates anchor: '\"Prone / face down\":'
       - Inserts NSFW poses after this line

    3. KLEIN RE-POSER INTERACTIONS:
       - Injects into MULTI_CHAR_PRESETS dict
       - Locates anchor: '\"Sitting together\":'
       - Inserts NSFW interactions after this line

    4. KLEIN OUTPAINT PRESETS:
       - Injects into KLEIN_OUTPAINT_PRESETS dict
       - Locates anchor: '\"Widen panorama\":'
       - Inserts NSFW outpaint presets after this line

    5. NSFW LORA METADATA:
       - Injects into LORA_METADATA dict
       - Locates anchor: '\"feet v2.1.safetensors\":'
       - Adds LoRA trigger phrases and strengths

    Args:
        dest_dir (Path): Root of staging directory to patch
    """
    import re
    klein = load_klein_nsfw_data()
    gimp_path = dest_dir / "plugins" / "gimp" / "comfyui-connector" / "comfyui-connector.py"
    if not gimp_path.exists():
        print("  WARNING: GIMP plugin not found for Klein NSFW patching")
        return

    content = gimp_path.read_text(encoding="utf-8")
    injected = 0

    # ── 1. Klein Inpaint Selection: inject NSFW task presets ──────────
    # The INPAINT_PRESETS dict inside _run_klein_inpaint uses:
    #   "label": { "prompt_hint": ..., "denoise": ..., "steps": ... }
    # We inject before the "(custom — manual settings)" entry.
    inpaint_presets = klein.get("klein_inpaint_presets", {})
    if inpaint_presets:
        nsfw_block = "\n            # ── NSFW Presets (auto-injected) ──\n"
        for label, data in inpaint_presets.items():
            nsfw_block += (
                f"            {repr(label)}: {{\n"
                f"                \"prompt_hint\": {repr(data['prompt_hint'])},\n"
                f"                \"denoise\": {data['denoise']}, \"steps\": {data['steps']},\n"
                f"            }},\n"
            )
        # Insert before the custom entry
        marker = '            "(custom \\u2014 manual settings)"'
        alt_marker = '            "(custom — manual settings)"'
        for m in [marker, alt_marker]:
            if m in content:
                content = content.replace(m, nsfw_block + m, 1)
                injected += len(inpaint_presets)
                print(f"  Injected {len(inpaint_presets)} NSFW presets into Klein Inpaint Selection")
                break

    # ── 2. Klein Re-poser: inject NSFW poses + interactions ──────────
    # POSE_PRESETS dict: "label": "prompt text"
    nsfw_poses = klein.get("klein_repose_poses", {})
    if nsfw_poses:
        nsfw_block = "            # ── NSFW Poses (auto-injected) ──\n"
        for label, prompt in nsfw_poses.items():
            nsfw_block += f"            {repr(label)}:{' ' * max(1, 30 - len(label))}{repr(prompt)},\n"
        # Insert before the closing } of POSE_PRESETS — find the "Prone / face down" entry
        # which is the last standard pose, and inject after it
        last_pose_marker = '"Prone / face down":'
        if last_pose_marker in content:
            # Find the line and its trailing content, inject after the next line
            idx = content.index(last_pose_marker)
            # Find end of that line's value (next newline after the comma)
            nl = content.index("\n", idx)
            content = content[:nl + 1] + nsfw_block + content[nl + 1:]
            injected += len(nsfw_poses)
            print(f"  Injected {len(nsfw_poses)} NSFW poses into Klein Re-poser")

    # MULTI_CHAR_PRESETS dict: "label": "prompt text"
    nsfw_interactions = klein.get("klein_repose_interactions", {})
    if nsfw_interactions:
        nsfw_block = "            # ── NSFW Interactions (auto-injected) ──\n"
        for label, prompt in nsfw_interactions.items():
            nsfw_block += f"            {repr(label)}:{' ' * max(1, 30 - len(label))}{repr(prompt)},\n"
        # Insert before the closing } of MULTI_CHAR_PRESETS — find "Sitting together"
        last_multi_marker = '"Sitting together":'
        if last_multi_marker in content:
            idx = content.index(last_multi_marker)
            nl = content.index("\n", idx)
            content = content[:nl + 1] + nsfw_block + content[nl + 1:]
            injected += len(nsfw_interactions)
            print(f"  Injected {len(nsfw_interactions)} NSFW interactions into Klein Re-poser")

    # ── 3. Klein Outpaint: inject NSFW purpose presets ────────────────
    # KLEIN_OUTPAINT_PRESETS dict: "label": "prompt text"
    nsfw_outpaint = klein.get("klein_outpaint_presets", {})
    if nsfw_outpaint:
        nsfw_block = "            # ── NSFW Outpaint Presets (auto-injected) ──\n"
        for label, prompt in nsfw_outpaint.items():
            nsfw_block += f"            {repr(label)}: {repr(prompt)},\n"
        # Insert before the closing } of KLEIN_OUTPAINT_PRESETS
        # Find "Widen panorama" which is the last standard preset
        last_outpaint_marker = '"Widen panorama":'
        if last_outpaint_marker in content:
            idx = content.index(last_outpaint_marker)
            nl = content.index("\n", idx)
            content = content[:nl + 1] + nsfw_block + content[nl + 1:]
            injected += len(nsfw_outpaint)
            print(f"  Injected {len(nsfw_outpaint)} NSFW presets into Klein Outpaint")

    # ── 4. Inject NSFW LoRA metadata into LORA_METADATA ──────────────
    nsfw_loras = klein.get("nsfw_loras", {})
    lora_entries = []
    for arch, loras in nsfw_loras.items():
        for lora in loras:
            fname = lora["path"].split("\\")[-1]
            lora_entries.append(
                f"    {repr(fname)}: "
                f"{{\"trigger\": {repr(lora['trigger'])}, "
                f"\"strength\": {lora['strength']}}},\n"
            )
    if lora_entries:
        lora_block = "    # ── NSFW LoRAs (auto-injected) ──\n" + "".join(lora_entries)
        # Find a known LoRA entry near the end of LORA_METADATA to inject after
        lora_anchor = '"feet v2.1.safetensors":'
        if lora_anchor in content:
            idx = content.index(lora_anchor)
            nl = content.index("\n", idx)
            content = content[:nl + 1] + lora_block + content[nl + 1:]
            print(f"  Injected {len(lora_entries)} NSFW LoRA metadata entries")

    gimp_path.write_text(content, encoding="utf-8")
    if injected > 0:
        print(f"  Total NSFW Klein injections: {injected} presets")
    else:
        print("  WARNING: No Klein NSFW presets were injected (markers not found)")


# ─── Patch install.py version ────────────────────────────────────────────

def patch_version(dest_dir):
    """Update version strings in files to indicate this is an NSFW build.

    Changes VERSION from "1.0" to "1.0-NSFW" in:
      - install.py
      - manual_update.py
      - manifest.json version field

    Allows users and logs to clearly identify NSFW vs. SFW builds.

    Args:
        dest_dir (Path): Root of staging directory to patch
    """
    for fname in ["installer/install.py", "installer/manual_update.py"]:
        fpath = dest_dir / fname
        if fpath.exists():
            content = fpath.read_text(encoding="utf-8")
            # Match any VERSION = "X.Y" and append -NSFW
            import re as _re
            content = _re.sub(r'VERSION = "(\d+\.\d+)"', r'VERSION = "\1-NSFW"', content)
            fpath.write_text(content, encoding="utf-8")
    # Manifest
    mpath = dest_dir / "installer" / "manifest.json"
    if mpath.exists():
        content = mpath.read_text(encoding="utf-8")
        content = _re.sub(r'"version": "(\d+\.\d+)"', r'"version": "\1-NSFW"', content)
        mpath.write_text(content, encoding="utf-8")
    print("  Version strings updated to NSFW")


# ─── Patch splash / banner / icon assets ─────────────────────────────────

def _nsfw_replace(src, dest, label, errors):
    """Copy src over dest, logging failures instead of silently swallowing."""
    try:
        shutil.copy2(src, dest)
        return True
    except (PermissionError, OSError) as e:
        errors.append(f"  ! Could not replace {label}: {e}")
        return False


def _nsfw_convert_jpeg(src_png, dest_jpg, label, errors):
    """Convert a PNG to JPEG for targets that need it."""
    try:
        from PIL import Image
        img = Image.open(src_png).convert("RGB")
        img.save(dest_jpg, "JPEG", quality=92)
        return True
    except ImportError:
        # Fallback: copy PNG bytes (darktable may still load it)
        return _nsfw_replace(src_png, dest_jpg, label, errors)
    except Exception as e:
        errors.append(f"  ! Could not convert {label} to JPEG: {e}")
        return False


def _nsfw_resize_png(src_png, dest_png, size, label, errors, mode="RGB"):
    """Resize a PNG to specific dimensions for icon/header targets."""
    try:
        from PIL import Image
        img = Image.open(src_png).convert(mode)
        img = img.resize(size, Image.LANCZOS)
        img.save(dest_png, "PNG")
        return True
    except ImportError:
        # No PIL — copy as-is (wrong size but better than nothing)
        return _nsfw_replace(src_png, dest_png, label, errors)
    except Exception as e:
        errors.append(f"  ! Could not resize {label}: {e}")
        return False


def patch_nsfw_assets(dest_dir):
    """Replace all visual assets with NSFW-themed versions across all plugins.

    This patch finds and replaces image assets used in dialogs, banners, installer,
    and app branding. It handles multiple image formats and resizing needs.

    SOURCES (in nsfw/ directory):
      nsfw_splash.gif    — animated splash (expected ~480×270, 12fps)
      nsfw_splash.png    — static PNG frame used as fallback/source for resizing
      nsfw_icon.png      — optional dedicated icon (optional, falls back to splash)
      nsfw_header.png    — optional dedicated header (optional, falls back to splash)

    TARGET ASSET LOCATIONS:
      GIF BANNERS:
        - plugins/gimp/comfyui-connector/wizard_banner.gif
        - plugins/gimp/comfyui-connector/gimp_banner.gif
        - plugins/gimp/gimp_banner.gif
        - assets/wizard_banner.gif

      PNG BANNERS (static fallbacks):
        - plugins/gimp/comfyui-connector/gimp_banner.png
        - plugins/gimp/comfyui-connector/readme_banner.png
        - plugins/gimp/gimp_banner.png
        - assets/readme_banner.png

      BACKGROUNDS (1920×1088 or 1024×1024):
        - plugins/gimp/comfyui-connector/installer_background.png
        - plugins/darktable/installer_background.png
        - assets/installer_background.png

      HERO IMAGE (1024×1024 RGBA, progress spinner character):
        - plugins/gimp/comfyui-connector/spellcaster_hero.png

      APP ICONS (1024×1024):
        - assets/spellcaster_gimp_icon.png
        - assets/spellcaster_darktable_icon.png
        - plugins/gimp/comfyui-connector/spellcaster_icon.png
        - plugins/darktable/spellcaster_icon.png

      HEADERS (1024×256):
        - assets/spellcaster_gimp_header.png
        - assets/spellcaster_darktable_header.png
        - plugins/gimp/comfyui-connector/spellcaster_header.png
        - plugins/darktable/spellcaster_header.png

      DARKTABLE SPLASH (JPEG format):
        - plugins/darktable/darktable_splash.jpg

    PROCESSING:
      - GIFs are copied directly (no resizing)
      - PNGs are copied directly (no resizing)
      - Icons are resized to 1024×1024 using PIL LANCZOS
      - Headers are resized to 1024×256 using PIL LANCZOS
      - Hero is resized to 1024×1024 with RGBA mode
      - Darktable JPEG is converted from PNG source using PIL

    Args:
        dest_dir (Path): Root of staging directory to patch
    """
    nsfw_gif = HERE / "nsfw_splash.gif"
    nsfw_png = HERE / "nsfw_splash.png"
    nsfw_icon = HERE / "nsfw_icon.png"        # optional dedicated icon
    nsfw_header = HERE / "nsfw_header.png"    # optional dedicated header

    if not nsfw_gif.exists() or not nsfw_png.exists():
        print("  WARNING: NSFW splash assets not found, skipping asset patch")
        return

    connector = dest_dir / "plugins" / "gimp" / "comfyui-connector"
    gimp_dir  = dest_dir / "plugins" / "gimp"
    dt_dir    = dest_dir / "plugins" / "darktable"
    assets    = dest_dir / "assets"

    replaced = 0
    errors = []

    # ── GIF banners (animated dialog/system splash) ──────────────────
    for gif_target in [
        connector / "wizard_banner.gif",
        connector / "gimp_banner.gif",
        gimp_dir / "gimp_banner.gif",
        assets / "wizard_banner.gif",
    ]:
        if gif_target.exists():
            if _nsfw_replace(nsfw_gif, gif_target, gif_target.name, errors):
                replaced += 1

    # ── PNG banners (static fallbacks) ───────────────────────────────
    for png_target in [
        connector / "gimp_banner.png",
        connector / "readme_banner.png",
        gimp_dir / "gimp_banner.png",
        assets / "readme_banner.png",
    ]:
        if png_target.exists():
            if _nsfw_replace(nsfw_png, png_target, png_target.name, errors):
                replaced += 1

    # ── Installer backgrounds (1920×1088 or 1024×1024) ───────────────
    for bg_target in [
        connector / "installer_background.png",
        dt_dir / "installer_background.png",
        assets / "installer_background.png",
    ]:
        if bg_target.exists():
            if _nsfw_replace(nsfw_png, bg_target, bg_target.name, errors):
                replaced += 1

    # ── Hero image (progress spinner character, 1024×1024 RGBA) ──────
    hero = connector / "spellcaster_hero.png"
    if hero.exists():
        if _nsfw_resize_png(nsfw_png, hero, (1024, 1024),
                            "spellcaster_hero.png", errors, mode="RGBA"):
            replaced += 1

    # ── App icons (1024×1024 square) ─────────────────────────────────
    icon_src = nsfw_icon if nsfw_icon.exists() else nsfw_png
    for icon_target in [
        assets / "spellcaster_gimp_icon.png",
        assets / "spellcaster_darktable_icon.png",
        # Also the deployed copies the installer creates in plugin dirs
        connector / "spellcaster_icon.png",
        dt_dir / "spellcaster_icon.png",
    ]:
        if icon_target.exists():
            if _nsfw_resize_png(icon_src, icon_target, (1024, 1024),
                                icon_target.name, errors):
                replaced += 1

    # ── Header decorations (1024×256) ────────────────────────────────
    header_src = nsfw_header if nsfw_header.exists() else nsfw_png
    for header_target in [
        assets / "spellcaster_gimp_header.png",
        assets / "spellcaster_darktable_header.png",
        connector / "spellcaster_header.png",
        dt_dir / "spellcaster_header.png",
    ]:
        if header_target.exists():
            if _nsfw_resize_png(header_src, header_target, (1024, 256),
                                header_target.name, errors):
                replaced += 1

    # ── Darktable splash (JPEG) ──────────────────────────────────────
    dt_splash = dt_dir / "darktable_splash.jpg"
    if dt_splash.exists():
        if _nsfw_convert_jpeg(nsfw_png, dt_splash, "darktable_splash.jpg", errors):
            replaced += 1

    # ── Report ───────────────────────────────────────────────────────
    print(f"  Replaced {replaced} visual assets with NSFW versions")
    for err in errors:
        print(err)


# ─── Patch theme colors + branding ───────────────────────────────────────

# Standard → NSFW color mapping.
# Deep purple theme → warm crimson/dark red theme.
_NSFW_COLOR_MAP = {
    # Accent colors
    "#D122E3": "#E32234",    # neon magenta → crimson red
    "#E84DF7": "#F74D5E",    # bright pink → bright red
    "#d122e3": "#e32234",
    "#e84df7": "#f74d5e",
    # Accent with alpha (CSS rgba)
    "rgba(209, 34, 227": "rgba(227, 34, 52",
    # Muted text
    "#8B7FA8": "#A88B7F",    # muted purple → muted warm brown
    "#8B7CA8": "#A87C7F",    # variant spelling
    "#8b7fa8": "#a88b7f",
    "#8b7ca8": "#a87c7f",
    "#8E889D": "#9D8E88",    # installer muted → warm muted
    # Background tones (purple-black → red-black)
    "#0B0715": "#150B07",    # deep purple-black → deep warm black
    "#150D26": "#261510",    # panels → dark warm brown
    "#1A1030": "#301A14",    # inputs/cards → warm charcoal
    "#3A2863": "#633A32",    # border purple → border warm
    "#21153B": "#3B2115",    # progress bar trough
    "#0b0715": "#150b07",
    "#150d26": "#261510",
    "#1a1030": "#301a14",
    "#3a2863": "#633a32",
    "#21153b": "#3b2115",
    # Text (keep readable — light lavender → light warm cream)
    "#E2DFEB": "#EBE2DF",
    "#e2dfeb": "#ebe2df",
}

# Branding swaps (only for text visible to users, not code identifiers)
_NSFW_BRANDING = {
    "AI Superpowers": "AI Superpowers \u2014 Uncensored",
    "AI superpowers": "AI superpowers \u2014 uncensored",
}

# Splash status messages
_NSFW_SPLASH_MESSAGES = {
    '"Processing with AI..."': '"Processing uncensored AI..."',
    '"Generating magic..."': '"Generating forbidden magic..."',
    '"Applying neural spells..."': '"Applying dark spells..."',
}


def patch_nsfw_theme(dest_dir):
    """Swap the color palette and branding in CSS themes, splash, and plugins.

    Replaces the purple/magenta palette with a warm crimson/red palette
    across all theme files and hardcoded color references.
    Does NOT touch code identifiers like class names or procedure IDs.
    """
    patched_files = 0

    # ── CSS theme files (bulk color swap) ────────────────────────────
    css_files = [
        dest_dir / "plugins" / "gimp" / "comfyui-connector" / "spellcaster-theme.css",
        dest_dir / "plugins" / "darktable" / "spellcaster-darktable.css",
    ]
    for css_path in css_files:
        if not css_path.exists():
            continue
        content = css_path.read_text(encoding="utf-8")
        for old, new in _NSFW_COLOR_MAP.items():
            content = content.replace(old, new)
        css_path.write_text(content, encoding="utf-8")
        patched_files += 1

    # ── Darktable splash.py (theme constants + pulse animation + messages)
    splash_path = dest_dir / "plugins" / "darktable" / "splash.py"
    if splash_path.exists():
        content = splash_path.read_text(encoding="utf-8")
        for old, new in _NSFW_COLOR_MAP.items():
            content = content.replace(old, new)
        for old, new in _NSFW_BRANDING.items():
            content = content.replace(old, new)
        for old, new in _NSFW_SPLASH_MESSAGES.items():
            content = content.replace(old, new)
        # Fix pulse animation color range to match new crimson accent
        # Original: r=140→209, g=20→34, b=160→227 (purple pulse)
        # New:      r=160→227, g=20→34, b=30→52 (red pulse)
        content = content.replace(
            "r = int(140 + t * (209 - 140))",
            "r = int(160 + t * (227 - 160))")
        content = content.replace(
            "b = int(160 + t * (227 - 160))",
            "b = int(30 + t * (52 - 30))")
        splash_path.write_text(content, encoding="utf-8")
        patched_files += 1

    # ── GIMP plugin (hardcoded colors + branded header + tagline) ────
    gimp_path = dest_dir / "plugins" / "gimp" / "comfyui-connector" / "comfyui-connector.py"
    if gimp_path.exists():
        content = gimp_path.read_text(encoding="utf-8")
        for old, new in _NSFW_COLOR_MAP.items():
            content = content.replace(old, new)
        for old, new in _NSFW_BRANDING.items():
            content = content.replace(old, new)
        gimp_path.write_text(content, encoding="utf-8")
        patched_files += 1

    # ── Installer GUI (color palette) ────────────────────────────────
    gui_path = dest_dir / "installer" / "installer_gui.py"
    if gui_path.exists():
        content = gui_path.read_text(encoding="utf-8")
        for old, new in _NSFW_COLOR_MAP.items():
            content = content.replace(old, new)
        for old, new in _NSFW_BRANDING.items():
            content = content.replace(old, new)
        gui_path.write_text(content, encoding="utf-8")
        patched_files += 1

    # ── CLI installer (branding only, no colors — it uses ANSI) ──────
    cli_path = dest_dir / "installer" / "install.py"
    if cli_path.exists():
        content = cli_path.read_text(encoding="utf-8")
        for old, new in _NSFW_BRANDING.items():
            content = content.replace(old, new)
        cli_path.write_text(content, encoding="utf-8")
        patched_files += 1

    # ── Darktable Lua plugin (branding tagline) ──────────────────────
    lua_path = dest_dir / "plugins" / "darktable" / "comfyui_connector.lua"
    if lua_path.exists():
        content = lua_path.read_text(encoding="utf-8")
        for old, new in _NSFW_BRANDING.items():
            content = content.replace(old, new)
        lua_path.write_text(content, encoding="utf-8")
        patched_files += 1

    print(f"  Patched theme colors + branding in {patched_files} files")


NSFW_REPO = "laboratoiresonore/spellcaster_NSFW"

def _load_nsfw_github_token():
    """Load the GitHub token for NSFW private repo access.

    Looks in nsfw/.github_token (one line, the PAT).
    If not found, prompts during build.
    """
    token_file = HERE / ".github_token"
    if token_file.exists():
        token = token_file.read_text().strip()
        if token:
            return token
    # Check environment variable
    token = os.environ.get("NSFW_GITHUB_TOKEN", "")
    if token:
        return token
    print(f"\n  WARNING: No GitHub token found for NSFW private repo.")
    print(f"  Create nsfw/.github_token with a GitHub PAT that has repo access,")
    print(f"  or set NSFW_GITHUB_TOKEN environment variable.")
    print(f"  Without it, the NSFW auto-updater cannot access the private repo.\n")
    return ""


def patch_auth_auto_update(dest_dir):
    """Redirect auto-update URLs to private NSFW repo and inject GitHub authentication token.

    The NSFW distribution is stored in a private GitHub repository that requires
    authentication. This patch modifies the auto-updater code in the GIMP and
    Darktable plugins to:

    1. Redirect public repo URLs to private NSFW repo (laboratoiresonore/spellcaster_NSFW)
    2. Inject a GitHub Personal Access Token (PAT) into HTTP request headers
    3. Update custom version check functions to read from private repo

    The token is loaded from:
      - nsfw/.github_token (preferred)
      - NSFW_GITHUB_TOKEN environment variable
      - Prompts user during build if neither found

    The token should be read-only with repo scope. It's baked into the compiled .exe,
    so the updater can fetch releases without user intervention.

    PATCH LOCATIONS:
      - plugins/gimp/comfyui-connector/comfyui-connector.py:
        * Check_for_updates() function
        * Auto-update HTTP request construction
        * Release fetch and download logic

      - plugins/darktable/comfyui_connector.lua:
        * check_for_updates() function
        * HTTP request with Authorization header

    Args:
        dest_dir (Path): Root of staging directory to patch
    """
    token = _load_nsfw_github_token()

    gimp_path = dest_dir / "plugins" / "gimp" / "comfyui-connector" / "comfyui-connector.py"
    if gimp_path.exists():
        content = gimp_path.read_text(encoding="utf-8")

        # Redirect URLs to NSFW repo
        content = content.replace(
            "laboratoiresonore/spellcaster/",
            f"{NSFW_REPO}/"
        )
        content = content.replace(
            "laboratoiresonore/spellcaster\"",
            f"{NSFW_REPO}\""
        )
        content = content.replace(
            "laboratoiresonore/spellcaster'",
            f"{NSFW_REPO}'"
        )

        # Inject auth token into the auto-updater's User-Agent line
        # The auto-updater builds requests with {"User-Agent": _ua}
        # We add an Authorization header alongside it
        # Inject auth token into _github_headers() — used by auto-updater AND repair button
        if token:
            content = content.replace(
                'def _github_headers():\n'
                '    """Return HTTP headers for GitHub API/raw requests."""\n'
                '    return {"User-Agent": "spellcaster-gimp/2.0"}',
                'def _github_headers():\n'
                '    """Return HTTP headers for GitHub API/raw requests (NSFW: with auth)."""\n'
                f'    return {{"User-Agent": "spellcaster-gimp/2.0", "Authorization": "token {token}"}}'
            )
            print(f"  GIMP auto-update + repair: redirected to {NSFW_REPO} + auth token injected")
        else:
            print(f"  GIMP auto-update: redirected to {NSFW_REPO} (NO AUTH — will 404!)")

        gimp_path.write_text(content, encoding="utf-8")

    # Darktable plugin
    lua_path = dest_dir / "plugins" / "darktable" / "comfyui_connector.lua"
    if lua_path.exists():
        content = lua_path.read_text(encoding="utf-8")
        content = content.replace(
            "laboratoiresonore/spellcaster/",
            f"{NSFW_REPO}/"
        )
        content = content.replace(
            'laboratoiresonore/spellcaster"',
            f'{NSFW_REPO}"'
        )
        # Inject auth into Darktable's curl commands
        if token:
            content = content.replace(
                'curl -sS',
                f'curl -sS -H "Authorization: token {token}"'
            )
            print(f"  Darktable auto-update: redirected + auth token injected")
        else:
            print(f"  Darktable auto-update: redirected (NO AUTH)")
        lua_path.write_text(content, encoding="utf-8")

    # Manual updater: inject auth into its GitHub requests
    updater_path = dest_dir / "installer" / "manual_update.py"
    if updater_path.exists():
        content = updater_path.read_text(encoding="utf-8")
        content = content.replace(
            "laboratoiresonore/spellcaster/",
            f"{NSFW_REPO}/"
        )
        content = content.replace(
            'laboratoiresonore/spellcaster"',
            f'{NSFW_REPO}"'
        )
        content = content.replace(
            "laboratoiresonore/spellcaster'",
            f"{NSFW_REPO}'"
        )
        if token:
            # Inject auth header into download_file and discover_remote_files
            content = content.replace(
                '"User-Agent": "spellcaster-updater/2.0"',
                f'"User-Agent": "spellcaster-updater/2.0", "Authorization": "token {token}"'
            )
            print(f"  Manual updater: redirected + auth token injected")
        else:
            print(f"  Manual updater: redirected (NO AUTH)")
        updater_path.write_text(content, encoding="utf-8")


def patch_force_all_on(dest_dir):
    """Patch installer GUI to force-enable all features by default (NSFW-only).

    For NSFW distributions, we want to ensure all features install without
    requiring user decisions. This patch modifies installer_gui.py to:

    1. Set _force_all_on = True in the GUI controller
    2. Bypass VRAM evaluation (don't auto-deselect features based on GPU memory)
    3. Mark all features as pre-selected during installation
    4. Skip feature selection prompts for streamlined deployment

    This ensures NSFW editions always include all LoRAs, models, and tools.

    Args:
        dest_dir (Path): Root of staging directory to patch
    """
    gui_path = dest_dir / "installer" / "installer_gui.py"
    if not gui_path.exists():
        return
    content = gui_path.read_text(encoding="utf-8")

    # Inject _force_all_on = True into __init__ right before select_frame
    content = content.replace(
        "        self.select_frame(\"welcome\")\n",
        "        self._force_all_on = True\n        self.select_frame(\"welcome\")\n",
        1  # only replace first occurrence
    )
    gui_path.write_text(content, encoding="utf-8")
    print("  NSFW force-all-on: every feature enabled by default, VRAM check bypassed")


# ─── Patch: re-inject Wan NSFW SVI preset (removed from public) ──────────

def patch_wan_nsfw_preset(dest_dir):
    """Re-add the "Wan Enhanced NSFW SVI" preset to the GIMP plugin.

    This preset was removed from the public Spellcaster repo but is included in
    the NSFW distribution. It configures Wan video generation with NSFW-tuned
    settings for smooth image-to-video synthesis with adult content.

    Injects a new preset entry into the WAN_I2V_PRESETS dict, positioned after
    the existing presets. Uses string anchor matching to locate insertion point:
    finds the last preset's "accel_strength": 1.0, line and inserts after it.

    Args:
        dest_dir (Path): Root of staging directory to patch
    """
    gimp_path = dest_dir / "plugins" / "gimp" / "comfyui-connector" / "comfyui-connector.py"
    if not gimp_path.exists():
        return
    content = gimp_path.read_text(encoding="utf-8")

    # Check if already present
    if "Wan Enhanced NSFW SVI" in content:
        print("  Wan NSFW SVI preset already present")
        return

    # Inject after the last preset in WAN_I2V_PRESETS — find the closing }
    # Look for the accel_strength line in the last preset
    wan_marker = '"accel_strength": 1.5,'
    # Find the LAST occurrence (the fp8 preset's accel_strength)
    last_idx = content.rfind(wan_marker)
    if last_idx < 0:
        # Fallback: try lora_prefix
        wan_marker = '"lora_prefix": "Wan",'
        last_idx = content.rfind(wan_marker)
    if last_idx < 0:
        print("  WARNING: Could not find Wan preset marker for NSFW SVI injection")
        return

    nsfw_wan_preset = '''
    "Wan Enhanced NSFW SVI (fp8)": {
        "high_model": "Wan\\\\wan22EnhancedNSFWSVICamera_nsfwV2FP8H.safetensors",
        "low_model": "Wan\\\\wan22EnhancedNSFWSVICamera_nsfwV2FP8L.safetensors",
        "clip": "umt5-xxl-encoder-Q8_0.gguf",
        "vae": "wan_2.1_vae.safetensors",
        "steps": 30, "second_step": 20, "cfg": 5.0, "shift": 8.0,
        "lora_prefix": "Wan",
        "high_accel_lora": "WAN\\\\SVI_v2_PRO_Wan2.2-I2V-A14B_HIGH_lora_rank_128_fp16.safetensors",
        "low_accel_lora": "WAN\\\\SVI_v2_PRO_Wan2.2-I2V-A14B_LOW_lora_rank_128_fp16.safetensors",
        "accel_strength": 1.0,
    },'''

    idx = last_idx
    # Find the next "}" that closes the preset dict, then the "}" that closes WAN_I2V_PRESETS
    close_brace = content.index("\n}", idx)
    # Insert after the closing of the last preset entry
    content = content[:close_brace] + nsfw_wan_preset + content[close_brace:]
    gimp_path.write_text(content, encoding="utf-8")
    print("  Injected Wan Enhanced NSFW SVI preset into GIMP plugin")

    # Also inject into Darktable
    lua_path = dest_dir / "plugins" / "darktable" / "comfyui_connector.lua"
    if lua_path.exists():
        lua_content = lua_path.read_text(encoding="utf-8")
        if "Wan Enhanced NSFW SVI" not in lua_content:
            # Find the last preset's accel_strength in Darktable Lua
            lua_marker = 'accel_strength  = 1.0,'
            lua_last = lua_content.rfind(lua_marker)
            if lua_last >= 0:
                nsfw_lua = '\n  {\n' \
                    '    label = "Wan Enhanced NSFW SVI (fp8)",\n' \
                    '    high_model = "Wan\\\\wan22EnhancedNSFWSVICamera_nsfwV2FP8H.safetensors",\n' \
                    '    low_model  = "Wan\\\\wan22EnhancedNSFWSVICamera_nsfwV2FP8L.safetensors",\n' \
                    '    clip       = "umt5-xxl-encoder-Q8_0.gguf",\n' \
                    '    vae        = "wan_2.1_vae.safetensors",\n' \
                    '    steps = 30, second_step = 20, cfg = 5.0, shift = 8.0,\n' \
                    '    lora_prefixes   = {"WAN\\\\", "Wan-2.2-I2V\\\\"},\n' \
                    '    high_accel_lora = "WAN\\\\SVI_v2_PRO_Wan2.2-I2V-A14B_HIGH_lora_rank_128_fp16.safetensors",\n' \
                    '    low_accel_lora  = "WAN\\\\SVI_v2_PRO_Wan2.2-I2V-A14B_LOW_lora_rank_128_fp16.safetensors",\n' \
                    '    accel_strength  = 1.0,\n' \
                    '  },'
                # Find the closing "}" of WAN_I2V_PRESETS table after the marker
                lua_close = lua_content.index("\n}", lua_last)
                lua_content = lua_content[:lua_close] + nsfw_lua + lua_content[lua_close:]
                lua_path.write_text(lua_content, encoding="utf-8")
                print("  Injected Wan NSFW SVI preset into Darktable plugin")


# ─── Push patched files to NSFW private repo ─────────────────────────────

def push_to_nsfw_repo(staging_dir):
    """Push the fully-patched staging files to the NSFW private GitHub repository.

    This function coordinates with GitHub to update the private repository with
    the freshly patched NSFW distribution. It requires a GitHub PAT with repo access.

    PROCESS:
      1. Clone the private NSFW repo locally
      2. Clean out old files (except .git)
      3. Copy all patched files from staging/ into the clone
      4. Stage all changes with 'git add -A'
      5. Commit with message indicating auto-patched build
      6. Push to origin/main

    The function checks if there are actual changes before committing (to avoid
    redundant empty commits).

    This is CRITICAL for the auto-updater to work. The NSFW auto-updater
    pulls from the private repo via GitHub Tree API - if the repo doesn't
    have the patched files, users get the SFW version on update.

    Args:
        staging_dir (Path): The patched staging directory to push

    Returns:
        bool: True if push succeeded, False if clone/commit/push failed
    """
    nsfw_clone = HERE / "nsfw_repo"
    repo_url = f"https://github.com/{NSFW_REPO}.git"

    print(f"\nPushing patched files to {NSFW_REPO}...")

    # Clone or pull the private repo
    if nsfw_clone.exists():
        print("  Updating existing NSFW repo clone...")
        result = subprocess.run(["git", "pull", "--ff-only"],
                                cwd=str(nsfw_clone), capture_output=True, text=True)
        if result.returncode != 0:
            print(f"  Pull failed, re-cloning: {result.stderr.strip()}")
            shutil.rmtree(nsfw_clone)

    if not nsfw_clone.exists():
        print(f"  Cloning {repo_url}...")
        result = subprocess.run(["git", "clone", "--depth", "1", repo_url, str(nsfw_clone)],
                                capture_output=True, text=True)
        if result.returncode != 0:
            print(f"  ERROR: Could not clone NSFW repo: {result.stderr.strip()}")
            print(f"  Make sure you have push access to {NSFW_REPO}")
            print("  and that gh auth / git credentials are configured.")
            return False

    # Clean out everything except .git
    for item in nsfw_clone.iterdir():
        if item.name in {".git"}:
            continue
        if item.is_dir():
            shutil.rmtree(item)
        else:
            item.unlink()

    # Copy all patched files from staging into the clone
    for item in staging_dir.iterdir():
        if item.name in {"__pycache__", ".ruff_cache"}:
            continue
        dest = nsfw_clone / item.name
        if item.is_dir():
            shutil.copytree(item, dest, ignore=shutil.ignore_patterns(
                "__pycache__", "*.pyc", ".git"))
        else:
            shutil.copy2(item, dest)

    # Check for changes, commit, push
    result = subprocess.run(["git", "status", "--porcelain"],
                            cwd=str(nsfw_clone), capture_output=True, text=True)
    if not result.stdout.strip():
        print("  No changes to push (NSFW repo already up to date)")
        return True

    subprocess.run(["git", "add", "-A"], cwd=str(nsfw_clone))
    result = subprocess.run(
        ["git", "commit", "-m",
         "NSFW build: auto-patched from public repo with all NSFW content"],
        cwd=str(nsfw_clone), capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  ERROR: Commit failed: {result.stderr.strip()}")
        return False

    result = subprocess.run(["git", "push"],
                            cwd=str(nsfw_clone), capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  ERROR: Push failed: {result.stderr.strip()}")
        return False

    print(f"  Successfully pushed patched files to {NSFW_REPO}")
    return True


# ─── Validation ────────────────────────────────────────────────────────────

def validate_patches(dest_dir):
    """Verify that all NSFW patches were applied correctly to the staging copy.

    Checks for the presence of key injection markers and content in the
    patched GIMP and Darktable plugins. Used by --validate and after --patch.

    Args:
        dest_dir (Path): The directory to validate (staging or ROOT)
    """
    gimp_path = dest_dir / "plugins" / "gimp" / "comfyui-connector" / "comfyui-connector.py"
    dt_path = dest_dir / "plugins" / "darktable" / "comfyui_connector.lua"

    errors = []

    if gimp_path.exists():
        content = gimp_path.read_text(encoding="utf-8")
        checks = [
            ("NSFW Presets (auto-injected)", "Klein Inpaint NSFW presets"),
            ("NSFW Poses (auto-injected)", "Klein Re-poser NSFW poses"),
            ("NSFW Interactions (auto-injected)", "Klein Re-poser NSFW interactions"),
            ("NSFW Outpaint Presets (auto-injected)", "Klein Outpaint NSFW presets"),
        ]
        for marker, label in checks:
            if marker not in content:
                errors.append(f"  MISSING: {label}")
            else:
                print(f"  OK: {label}")
    else:
        errors.append(f"  MISSING: GIMP plugin file ({gimp_path})")

    if dt_path.exists():
        dt_content = dt_path.read_text(encoding="utf-8")
        if "NSFW" in dt_content:
            print("  OK: Darktable NSFW patches present")
        else:
            errors.append("  MISSING: Darktable NSFW patches")
    else:
        errors.append(f"  MISSING: Darktable plugin file ({dt_path})")

    if errors:
        print("\nValidation FAILED:")
        for e in errors:
            print(e)
        return False
    else:
        print("\nValidation PASSED: all NSFW patches applied correctly")
        return True


# ─── Build .exe installers ────────────────────────────────────────────────

def build_exe(staging_dir):
    """Run PyInstaller from the staging directory.

    Builds two executables:
      1. spellcaster-nsfw-installer.exe — full installer with GUI
      2. spellcaster-nsfw-updater.exe — console updater for existing installs

    Both are placed in nsfw/dist/.

    Args:
        staging_dir (Path): The patched staging directory containing all source files
    """
    sep = os.pathsep
    NSFW_DIST.mkdir(parents=True, exist_ok=True)

    # Installer
    installer_dir = staging_dir / "installer"

    print("\nBuilding NSFW installer .exe...")
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--hidden-import", "tkinter",
        "--hidden-import", "tkinter.scrolledtext",
        "--hidden-import", "tkinter.ttk",
        "--hidden-import", "installer_gui",
        "--collect-all", "customtkinter",
        "--hidden-import", "darkdetect",
        "--hidden-import", "PIL",
        "--hidden-import", "requests",
        "--add-data", f"manifest.json{sep}.",
        "--add-data", f"installer_gui.py{sep}.",
        "--add-data", f"{staging_dir / 'plugins'}{sep}plugins",
        "--add-data", f"{staging_dir / 'assets'}{sep}assets",
        "--onefile",
        "--windowed",
        "--name", "spellcaster-nsfw-installer",
        "--distpath", str(staging_dir / "dist"),
        "--workpath", str(staging_dir / "build"),
        "install.py",
    ]
    icon = staging_dir / "assets" / "spellcaster.ico"
    if icon.exists():
        cmd += ["--icon", str(icon)]

    result = subprocess.run(cmd, cwd=str(installer_dir))
    if result.returncode == 0:
        src = staging_dir / "dist" / "spellcaster-nsfw-installer.exe"
        if src.exists():
            shutil.move(str(src), str(NSFW_DIST / "spellcaster-nsfw-installer.exe"))
            print(f"  Built: {NSFW_DIST / 'spellcaster-nsfw-installer.exe'}")
    else:
        print(f"  Installer build FAILED (exit {result.returncode})")

    # Updater
    print("\nBuilding NSFW updater .exe...")
    cmd2 = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--onefile",
        "--console",
        "--name", "spellcaster-nsfw-updater",
        "--distpath", str(staging_dir / "dist"),
        "--workpath", str(staging_dir / "build"),
        "manual_update.py",
    ]
    if icon.exists():
        cmd2 += ["--icon", str(icon)]

    result2 = subprocess.run(cmd2, cwd=str(installer_dir))
    if result2.returncode == 0:
        src2 = staging_dir / "dist" / "spellcaster-nsfw-updater.exe"
        if src2.exists():
            shutil.move(str(src2), str(NSFW_DIST / "spellcaster-nsfw-updater.exe"))
            print(f"  Built: {NSFW_DIST / 'spellcaster-nsfw-updater.exe'}")
    else:
        print(f"  Updater build FAILED (exit {result2.returncode})")


# ─── Main ────────────────────────────────────────────────────────────────

def _create_staging():
    """Create a clean staging copy of the project for patching.

    Copies the entire repo (minus .git, build artifacts, nsfw/, __pycache__)
    into nsfw/staging/. This isolated copy gets patched without touching
    the original source tree.

    Returns:
        Path: The staging directory path
    """
    staging = HERE / "staging"
    if staging.exists():
        shutil.rmtree(staging)

    print("\nCreating staging copy...")
    for item in ROOT.iterdir():
        if item.name in {".git", "build", "dist", "nsfw", "__pycache__",
                         ".ruff_cache", "temp.txt", "temp2.txt"}:
            continue
        dest = staging / item.name
        if item.is_dir():
            shutil.copytree(item, dest, ignore=shutil.ignore_patterns(
                "__pycache__", "*.pyc", ".git"))
        else:
            shutil.copy2(item, dest)
    print(f"  Staged to: {staging}")
    return staging


def _apply_all_patches(dest_dir):
    """Apply ALL NSFW patches to a directory. Used by both --patch and full build.

    Runs every patch function in order:
      1. patch_manifest     — add NSFW LoRAs + Wan models to manifest.json
      2. patch_gimp_plugin  — inject NSFW presets into GIMP plugin
      3. patch_darktable_plugin — inject NSFW presets into Darktable plugin
      4. patch_klein_nsfw   — inject NSFW Klein presets
      5. patch_wan_nsfw_preset — inject NSFW Wan presets
      6. patch_version      — stamp version string with NSFW tag
      7. patch_force_all_on — enable all features by default
      8. patch_auth_auto_update — configure auto-updater for NSFW repo

    Args:
        dest_dir (Path): Directory to patch (ROOT for --patch, staging/ for build)
    """
    patch_manifest(dest_dir)
    patch_gimp_plugin(dest_dir)
    patch_darktable_plugin(dest_dir)
    patch_klein_nsfw(dest_dir)
    patch_wan_nsfw_preset(dest_dir)
    patch_version(dest_dir)
    patch_force_all_on(dest_dir)
    patch_auth_auto_update(dest_dir)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Build Spellcaster NSFW edition")
    parser.add_argument("--patch", action="store_true",
                        help="Patch plugins in-place without building .exe (for testing)")
    parser.add_argument("--push", action="store_true",
                        help="Push patched files to the NSFW private GitHub repo (for auto-updater)")
    parser.add_argument("--push-only", action="store_true",
                        help="Stage, patch, push to NSFW repo — no .exe build")
    parser.add_argument("--validate", action="store_true",
                        help="Stage, patch, validate — no build, no push")
    args = parser.parse_args()

    print("=" * 56)
    print("  SPELLCASTER NSFW BUILDER")
    print("=" * 56)

    if args.patch:
        print("\nPatching plugins in-place (no .exe build)...")
        _apply_all_patches(ROOT)
        print("\nValidating patches...")
        validate_patches(ROOT)
        return

    # Full build: stage → patch → (optionally validate/push/build)
    staging = _create_staging()
    _apply_all_patches(staging)

    print("\nValidating patches...")
    if not validate_patches(staging):
        print("\nAborting build due to validation failure.")
        return

    if args.validate:
        print("\n--validate: stopping after validation (no build, no push)")
        return

    if args.push_only:
        push_to_nsfw_repo(staging)
        return

    if args.push:
        push_to_nsfw_repo(staging)

    build_exe(staging)
    print("\n" + "=" * 56)
    print("  NSFW BUILD COMPLETE")
    print("=" * 56)


if __name__ == "__main__":
    main()