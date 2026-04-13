"""Wizard Memory — persistent preference learning from user feedback.

Every generation gets a thumbs up/down. The system learns:
  - Which models the user prefers per intent (portrait, anime, etc.)
  - Which LoRA combos produce good results
  - Preferred resolution, steps, CFG ranges
  - Named presets for workflows the user repeatedly approves

Storage: .guild_state/wizard_memory.json

Usage:
    from spellcaster_core.memory import WizardMemory

    mem = WizardMemory.load("path/to/wizard_memory.json")

    # Record a generation + feedback
    mem.record(generation_id, {
        "prompt": "anime girl in garden",
        "arch": "illustrious",
        "model": "ilustreal.safetensors",
        "loras": [{"name": "detail.safetensors", "strength": 0.5}],
        "width": 1024, "height": 1024,
        "steps": 28, "cfg": 5.5,
        "seed": 42,
    }, thumbs_up=True)

    # Get learned preferences for a new prompt
    prefs = mem.suggest("anime portrait")
    # {"arch": "illustrious", "model": "ilustreal...", "cfg": 5.5, ...}

    # Save a named preset from a generation the user loved
    mem.save_preset("My Anime Style", generation_id)
"""

import json
import os
import time
from collections import defaultdict


class GenerationRecord:
    """A single generation + user feedback."""
    __slots__ = ("id", "timestamp", "params", "thumbs_up", "tags")

    def __init__(self, gen_id, params, thumbs_up=None):
        self.id = gen_id
        self.timestamp = time.time()
        self.params = params  # full workflow settings
        self.thumbs_up = thumbs_up  # True/False/None
        self.tags = []  # auto-detected: ["anime", "portrait", "lora:detail"]

    def to_dict(self):
        return {
            "id": self.id,
            "timestamp": self.timestamp,
            "params": self.params,
            "thumbs_up": self.thumbs_up,
            "tags": self.tags,
        }

    @classmethod
    def from_dict(cls, d):
        r = cls(d["id"], d["params"], d.get("thumbs_up"))
        r.timestamp = d.get("timestamp", 0)
        r.tags = d.get("tags", [])
        return r


class NamedPreset:
    """A user-saved Spell — complete workflow preset with ALL settings."""

    # Animated spell icons (GIF filenames in assets/spells/)
    SPELL_ICONS = ["blue", "globe", "green", "red", "spheres", "stars"]

    def __init__(self, name, params, source_gen_id=""):
        self.name = name
        self.params = params  # complete workflow settings
        self.source_gen_id = source_gen_id
        self.created = time.time()
        self.use_count = 0
        self.last_used = 0
        self.spell_icon = ""     # GIF name from SPELL_ICONS (e.g., "blue", "red", "stars")
        self.icon = ""           # optional emoji prefix
        self.wizard_id = ""      # which wizard this spell belongs to
        self.shortcut = ""       # keyboard shortcut (e.g., "1", "2", "a")
        self.tags = []           # user tags for filtering
        # Auto-assign random spell icon if not set
        if not self.spell_icon:
            import random as _r
            self.spell_icon = _r.choice(self.SPELL_ICONS)

    def to_dict(self):
        return {
            "name": self.name,
            "params": self.params,
            "source_gen_id": self.source_gen_id,
            "created": self.created,
            "use_count": self.use_count,
            "last_used": self.last_used,
            "spell_icon": self.spell_icon,
            "icon": self.icon,
            "wizard_id": self.wizard_id,
            "shortcut": self.shortcut,
            "tags": self.tags,
        }

    @classmethod
    def from_dict(cls, d):
        p = cls(d["name"], d["params"], d.get("source_gen_id", ""))
        p.created = d.get("created", 0)
        p.use_count = d.get("use_count", 0)
        p.last_used = d.get("last_used", 0)
        p.spell_icon = d.get("spell_icon", d.get("color", "blue"))  # migrate from old "color" field
        if p.spell_icon.startswith("#"):
            # Old hex color — map to closest icon
            p.spell_icon = {"#EF4444": "red", "#3B82F6": "blue", "#10B981": "green"}.get(
                p.spell_icon, p.SPELL_ICONS[hash(p.name) % len(p.SPELL_ICONS)])
        p.icon = d.get("icon", "")
        p.wizard_id = d.get("wizard_id", "")
        p.shortcut = d.get("shortcut", "")
        p.tags = d.get("tags", [])
        return p


class WizardMemory:
    """Persistent preference learning from generation feedback."""

    def __init__(self):
        self.generations = []         # list of GenerationRecord
        self.presets = {}             # name -> NamedPreset
        self.preferences = {}         # learned preferences per intent
        self._max_history = 500       # keep last N generations

    # ── Recording ────────────────────────────────────────────────

    def record(self, gen_id, params, thumbs_up=None):
        """Record a generation. Called after every ComfyUI completion."""
        rec = GenerationRecord(gen_id, params, thumbs_up)
        rec.tags = self._auto_tag(params)
        self.generations.append(rec)

        # Trim old history
        if len(self.generations) > self._max_history:
            self.generations = self.generations[-self._max_history:]

        # If feedback given, update preferences
        if thumbs_up is not None:
            self._update_preferences(rec)

        return rec

    def set_feedback(self, gen_id, thumbs_up):
        """Set thumbs up/down for a generation after the fact."""
        for rec in reversed(self.generations):
            if rec.id == gen_id:
                rec.thumbs_up = thumbs_up
                self._update_preferences(rec)
                return True
        return False

    # ── Presets ──────────────────────────────────────────────────

    def save_preset(self, name, gen_id=None, params=None,
                    spell_icon="", wizard_id="", icon="", tags=None):
        """Save a named Spell from a generation or raw params.

        The Spell contains ALL workflow settings — model, arch, LoRAs,
        resolution, steps, CFG, sampler, scheduler, prompt template.
        """
        if gen_id:
            rec = next((r for r in reversed(self.generations) if r.id == gen_id), None)
            if not rec:
                return None
            params = dict(rec.params)

        if not params:
            return None

        preset = NamedPreset(name, params, gen_id or "")
        if spell_icon:
            preset.spell_icon = spell_icon
        preset.wizard_id = wizard_id
        preset.icon = icon
        preset.tags = tags or []
        self.presets[name] = preset
        return preset

    def update_spell_icon(self, name, spell_icon):
        """Change a Spell's animated icon (GIF name)."""
        p = self.presets.get(name)
        if p:
            p.spell_icon = spell_icon
            return True
        return False

    def spells_for_wizard(self, wizard_id):
        """Get all Spells associated with a specific wizard."""
        return [p for p in self.presets.values() if p.wizard_id == wizard_id]

    def use_preset(self, name):
        """Get a preset's params and increment its use counter."""
        p = self.presets.get(name)
        if p:
            p.use_count += 1
            p.last_used = time.time()
            return dict(p.params)
        return None

    def list_presets(self):
        """List all presets sorted by most recently used."""
        return sorted(self.presets.values(),
                      key=lambda p: p.last_used, reverse=True)

    def delete_preset(self, name):
        """Delete a named preset."""
        return self.presets.pop(name, None) is not None

    # ── Suggestions ─────────────────────────────────────────────

    def suggest(self, prompt="", intent=""):
        """Suggest settings based on learned preferences.

        Looks at the user's history of thumbs-up generations to find
        patterns per intent (anime, portrait, landscape, etc.).

        Returns dict of suggested overrides (only fields with strong signal).
        """
        if not intent:
            intent = self._detect_intent(prompt)

        prefs = self.preferences.get(intent, {})
        if not prefs:
            # Fall back to global preferences
            prefs = self.preferences.get("_global", {})

        return prefs

    def detect_new_method(self, params):
        """Check if these params represent a novel workflow the user might want to save.

        Returns None if routine, or a suggested name + description if novel.
        """
        # Check if this combo of model + LoRAs is new
        key = self._params_signature(params)
        similar = [r for r in self.generations if self._params_signature(r.params) == key]

        if len(similar) < 2:
            # First or second time using this exact combo
            parts = []
            arch = params.get("arch", "")
            if arch:
                parts.append(arch.replace("flux2klein", "Klein").replace("flux1dev", "Flux")
                             .replace("illustrious", "Illustrious").replace("sdxl", "SDXL")
                             .replace("sd15", "SD15"))
            loras = params.get("loras", [])
            if loras:
                for l in loras[:2]:
                    name = l.get("name", "").split("\\")[-1].split("/")[-1]
                    name = name.replace(".safetensors", "").replace("_", " ")
                    parts.append(name)
                    strength = l.get("strength_model", 1.0)
                    if strength != 1.0:
                        parts.append(f"@{strength:.1f}")

            if len(similar) == 0:
                suggested_name = " + ".join(parts) if parts else "Custom Method"
                return {
                    "is_new": True,
                    "suggested_name": suggested_name,
                    "description": f"New workflow: {suggested_name}",
                    "params": params,
                }

        return None

    # ── Internal ────────────────────────────────────────────────

    def _auto_tag(self, params):
        """Auto-tag a generation based on its parameters."""
        tags = []
        prompt = params.get("prompt", "").lower()

        # Intent tags
        if any(w in prompt for w in ["anime", "manga", "1girl", "1boy"]):
            tags.append("anime")
        if any(w in prompt for w in ["photo", "realistic", "portrait"]):
            tags.append("portrait")
        if any(w in prompt for w in ["landscape", "scenery", "nature"]):
            tags.append("landscape")
        if any(w in prompt for w in ["video", "animate", "motion"]):
            tags.append("video")

        # Architecture tag
        arch = params.get("arch", "")
        if arch:
            tags.append(f"arch:{arch}")

        # LoRA tags
        for lora in params.get("loras", []):
            name = lora.get("name", "").split("\\")[-1].split("/")[-1]
            tags.append(f"lora:{name}")

        return tags

    def _detect_intent(self, prompt):
        """Detect intent from prompt for preference lookup."""
        pl = prompt.lower()
        if any(w in pl for w in ["anime", "manga", "1girl"]):
            return "anime"
        if any(w in pl for w in ["photo", "realistic", "portrait"]):
            return "portrait"
        if any(w in pl for w in ["landscape", "scenery"]):
            return "landscape"
        if any(w in pl for w in ["video", "animate"]):
            return "video"
        return "_global"

    def _update_preferences(self, rec):
        """Update learned preferences from a feedback record."""
        if rec.thumbs_up is None:
            return

        for tag in rec.tags:
            if tag.startswith("arch:") or tag.startswith("lora:"):
                continue
            intent = tag
            if intent not in self.preferences:
                self.preferences[intent] = {"_votes": defaultdict(lambda: [0, 0])}

            prefs = self.preferences[intent]
            vote_idx = 0 if rec.thumbs_up else 1

            # Track arch preference
            arch = rec.params.get("arch", "")
            if arch:
                key = f"arch:{arch}"
                if "_votes" not in prefs:
                    prefs["_votes"] = {}
                if key not in prefs["_votes"]:
                    prefs["_votes"][key] = [0, 0]
                prefs["_votes"][key][vote_idx] += 1

                # If strong signal (3+ thumbs up, ratio > 2:1), set as preferred
                ups, downs = prefs["_votes"][key]
                if ups >= 3 and ups > downs * 2:
                    prefs["arch"] = arch

            # Track model preference
            model = rec.params.get("model", rec.params.get("ckpt", ""))
            if model:
                key = f"model:{model}"
                if key not in prefs.get("_votes", {}):
                    prefs.setdefault("_votes", {})[key] = [0, 0]
                prefs["_votes"][key][vote_idx] += 1
                ups, downs = prefs["_votes"][key]
                if ups >= 3 and ups > downs * 2:
                    prefs["model"] = model

            # Track numeric preferences (running average of thumbs-up values)
            if rec.thumbs_up:
                for param in ("steps", "cfg", "width", "height"):
                    val = rec.params.get(param)
                    if val and isinstance(val, (int, float)):
                        avg_key = f"_avg_{param}"
                        count_key = f"_count_{param}"
                        old_avg = prefs.get(avg_key, val)
                        old_count = prefs.get(count_key, 0)
                        new_count = old_count + 1
                        new_avg = (old_avg * old_count + val) / new_count
                        prefs[avg_key] = new_avg
                        prefs[count_key] = new_count
                        # Set as preference if enough data
                        if new_count >= 3:
                            prefs[param] = round(new_avg)

        # Also update global preferences
        self._update_global(rec)

    def _update_global(self, rec):
        """Update global (intent-independent) preferences."""
        if rec.thumbs_up is None:
            return
        if "_global" not in self.preferences:
            self.preferences["_global"] = {}
        prefs = self.preferences["_global"]
        if rec.thumbs_up:
            arch = rec.params.get("arch", "")
            if arch:
                prefs.setdefault("_arch_counts", {})
                prefs["_arch_counts"][arch] = prefs["_arch_counts"].get(arch, 0) + 1

    def _params_signature(self, params):
        """Create a hashable signature for a workflow's key settings."""
        parts = [
            params.get("arch", ""),
            params.get("model", params.get("ckpt", "")),
        ]
        for lora in sorted(params.get("loras", []), key=lambda l: l.get("name", "")):
            parts.append(f"{lora.get('name', '')}@{lora.get('strength_model', 1.0)}")
        return "|".join(parts)

    # ── Persistence ─────────────────────────────────────────────

    def save(self, filepath):
        """Save to JSON file."""
        data = {
            "generations": [r.to_dict() for r in self.generations[-self._max_history:]],
            "presets": {n: p.to_dict() for n, p in self.presets.items()},
            "preferences": {},
        }
        # Serialize preferences (convert defaultdicts)
        for intent, prefs in self.preferences.items():
            data["preferences"][intent] = {}
            for k, v in prefs.items():
                if isinstance(v, defaultdict):
                    data["preferences"][intent][k] = dict(v)
                else:
                    data["preferences"][intent][k] = v

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    @classmethod
    def load(cls, filepath):
        """Load from JSON file."""
        mem = cls()
        if not os.path.exists(filepath):
            return mem
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            mem.generations = [GenerationRecord.from_dict(d) for d in data.get("generations", [])]
            mem.presets = {n: NamedPreset.from_dict(d) for n, d in data.get("presets", {}).items()}
            mem.preferences = data.get("preferences", {})
        except Exception:
            pass
        return mem
