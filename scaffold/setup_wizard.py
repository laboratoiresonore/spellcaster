"""Setup Wizard — LLM-driven installer scaffold.

State machine that walks a user through the guided install flow in the
Wizard Guild. Each state is a conversational turn: the scaffold builds
a system prompt describing what's installed and what's possible, the
LLM replies with a suggestion + optional action, and the scaffold
posts to /api/setup/* to perform the action.

States
------
    GREETING        Welcome, explain what just happened (bootstrap).
    DETECT_USAGE    Ask what the user mainly wants to do (portraits,
                    fantasy art, video, NSFW, etc.)
    SUGGEST_STACK   Based on usage + VRAM, suggest a feature set.
    INSTALL_LOOP    Install one feature at a time, show progress.
    PLUGINS         Ask which plugins (GIMP/Darktable) to install.
    FINISH          Flip setup_mode off, redirect to chat UI.

Usage
-----
    from scaffold.setup_wizard import SetupWizard
    wizard = SetupWizard(llm_url="http://127.0.0.1:8188", comfyui_url="...")
    response = wizard.respond(user_message, state_snapshot)
    # response = {"text": "...", "action": "install_feature", "payload": {...}}

The wizard is stateless — all state lives in guild_config.json via the
/api/setup/* endpoints. This module only produces LLM prompts and parses
LLM responses into structured actions.
"""
from __future__ import annotations

import json
import re
from typing import Any

# Feature descriptions keyed by manifest feature key. Used to build the
# LLM system prompt so it can make informed suggestions without hitting
# /api/setup/state on every turn.
FEATURE_PERSONALITY: dict[str, str] = {
    "core_sdxl":         "SDXL base generation — general-purpose photoreal + anime",
    "core_flux":         "Flux Dev — best quality text-to-image, larger download",
    "core_flux2_klein":  "Flux 2 Klein — Elusarca's 6-in-1 pipeline, fastest Flux variant",
    "core_kontext":      "Flux Kontext — edit-by-instruction ('make sky orange')",
    "core_illustrious":  "Illustrious / Pony — anime and stylized art",
    "core_chroma":       "Chroma — uncensored artistic model",
    "core_zit":          "ZIT — experimental fast generation",
    "face_swap":         "ReActor + IPAdapter — face swap, identity transfer",
    "enhance_upscale":   "Upscalers (UltraSharp, SeedVR2) — make images bigger & sharper",
    "enhance_restore":   "SUPIR + CodeFormer — repair damaged photos, fix faces",
    "enhance_relight":   "IC-Light — change lighting direction after generation",
    "controlnet":        "ControlNet — spatial guidance (pose, depth, canny)",
    "segment":           "SAM3 + BiRefNet — AI selection by text ('select the hair')",
    "video":             "Wan 2.2 + LTX 2.3 — image-to-video, text-to-video",
    "wizard_guild":      "The Wizard Guild chat UI (already bootstrapped)",
}

# Suggested feature bundles keyed by use case. The LLM picks a bundle
# after DETECT_USAGE and the scaffold offers it in SUGGEST_STACK.
USAGE_BUNDLES: dict[str, list[str]] = {
    "portraits":   ["core_sdxl", "face_swap", "enhance_restore", "enhance_upscale"],
    "fantasy":     ["core_flux2_klein", "core_illustrious", "enhance_upscale", "controlnet"],
    "photo_edit": ["core_flux2_klein", "core_kontext", "enhance_relight", "segment"],
    "anime":       ["core_illustrious", "enhance_upscale", "face_swap"],
    "video":       ["core_sdxl", "video", "enhance_upscale"],
    "everything":  ["core_sdxl", "core_flux2_klein", "core_kontext", "face_swap",
                    "enhance_upscale", "enhance_restore", "segment", "controlnet"],
}


def build_system_prompt(state: dict[str, Any]) -> str:
    """Produce the system prompt the LLM uses to guide the user through setup.

    The LLM is told: what's installed, what's possible, what to ask next,
    and what action JSON to emit when the user agrees to an install.
    """
    installed = state.get("features_installed", [])
    available = state.get("features", [])
    avail_lines = []
    for f in available:
        key = f.get("key", "")
        personality = FEATURE_PERSONALITY.get(key, f.get("label", key))
        vram = f.get("vram_min_gb", 0)
        marker = "[installed]" if key in installed else "[available]"
        avail_lines.append(f"  {marker} {key}: {personality} (min {vram} GB VRAM)")
    avail_text = "\n".join(avail_lines) if avail_lines else "  (none — manifest empty)"

    llm_ok = "yes" if state.get("llm_available") else "no"
    comfy_ok = "yes" if state.get("comfyui_reachable") else "no"

    return f"""You are the Spellcaster Setup Wizard, the AI guide that helps a new user finish installing Spellcaster.

CURRENT STATE:
  ComfyUI reachable:    {comfy_ok}
  Local LLM installed:  {llm_ok}  (you — this is how you're talking)
  ComfyUI URL:          {state.get('comfyui_url', 'unknown')}

FEATURES (each is a one-click install):
{avail_text}

YOUR JOB:
  1. Ask the user what they mainly want to do with Spellcaster.
     Example prompts: portraits / fantasy art / photo editing / anime /
     video / NSFW / just exploring.
  2. Based on their answer, suggest 3-6 features they should install.
     Keep your suggestions small — they can always add more later.
  3. When they agree to install something, emit a JSON action block:
       <ACTION>{{"type": "install_feature", "feature": "core_sdxl"}}</ACTION>
     The UI will run the install and show the result. Never claim you
     already installed something — wait for the action to execute.
  4. When they're done picking features, ask about plugins:
       <ACTION>{{"type": "install_plugin", "plugin": "gimp"}}</ACTION>
  5. When everything is picked, emit:
       <ACTION>{{"type": "finish"}}</ACTION>

TONE:
  - Terse. Friendly but not saccharine.
  - No "Great question!" / "Absolutely!" filler.
  - Reference actual tools by their tool name, not the feature key.
  - If the user asks off-topic questions, briefly answer and steer back.

IMPORTANT:
  - Never promise features that aren't in the AVAILABLE list.
  - Respect VRAM limits — don't suggest a 20GB feature to an 8GB GPU.
  - The user already has the LLM (you). Don't re-pitch it.
"""


_ACTION_RE = re.compile(r"<ACTION>(.*?)</ACTION>", re.DOTALL)


def parse_action(llm_response: str) -> tuple[str, dict[str, Any] | None]:
    """Extract an <ACTION>{...}</ACTION> JSON block from the LLM reply.

    Returns (cleaned_text, action_dict). cleaned_text is the reply with
    the action tag stripped (so the UI doesn't show raw JSON to the user).
    action_dict is None if no valid action was emitted.
    """
    match = _ACTION_RE.search(llm_response)
    if not match:
        return (llm_response.strip(), None)
    raw = match.group(1).strip()
    try:
        action = json.loads(raw)
    except json.JSONDecodeError:
        return (llm_response.strip(), None)
    cleaned = _ACTION_RE.sub("", llm_response).strip()
    return (cleaned, action)


def action_to_endpoint(action: dict[str, Any]) -> tuple[str, str, dict[str, Any]] | None:
    """Translate an LLM action dict into (method, path, body).

    Returns None for unknown action types.
    """
    atype = action.get("type")
    if atype == "install_feature":
        return ("POST", "/api/setup/feature/install",
                {"feature": action.get("feature", "")})
    if atype == "install_plugin":
        return ("POST", "/api/setup/plugin/install",
                {"plugin": action.get("plugin", "")})
    if atype == "finish":
        return ("POST", "/api/setup/finish", {})
    return None


class SetupWizard:
    """Stateless setup-wizard client. Call respond() per user turn."""

    def __init__(self, llm_client=None):
        """llm_client: any callable(system_prompt, user_msg) -> str.
        If None, the caller must fetch LLM replies themselves and pass
        the raw response to parse_action().
        """
        self.llm_client = llm_client

    def system_prompt(self, state: dict[str, Any]) -> str:
        return build_system_prompt(state)

    def respond(self, user_message: str, state: dict[str, Any]) -> dict[str, Any]:
        """One conversational turn.

        Returns: {"text": str, "action": dict | None, "endpoint": (method, path, body) | None}
        """
        if not self.llm_client:
            raise RuntimeError("SetupWizard requires an llm_client callable")
        system = self.system_prompt(state)
        reply = self.llm_client(system, user_message)
        text, action = parse_action(reply)
        endpoint = action_to_endpoint(action) if action else None
        return {"text": text, "action": action, "endpoint": endpoint}
