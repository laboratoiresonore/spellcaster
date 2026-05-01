"""Typed event schema — canonical wire format for the cross-interface bus.

Why this module exists
----------------------

Until now the bus was stringly-typed: `publish("gimp.generation.finished",
data={...})` with an implicit payload contract no one wrote down. New plugin
authors had to guess which fields a given kind carried, and drift between
publisher and subscriber went undetected until runtime.

This module makes every event shape explicit via a dataclass-per-kind
registry. Publishers can either call the dataclass constructor (type
checker catches missing fields) or continue publishing dicts — the
validator exposed here lets subscribers fail fast with a useful error
instead of quietly reading `None`.

Usage
-----

Publisher (preferred, typed path)::

    from .events import GenerationFinished, publish_event
    publish_event(bus, GenerationFinished(
        prompt=prompt, model=ckpt, arch="sdxl",
        image_url=url, seed=seed))

Publisher (loose path, unchanged from before)::

    bus.publish("gimp.generation.finished", origin="gimp", data={...})

Subscriber (typed view on a raw event dict)::

    from .events import parse_event
    evt = parse_event(kind, data_dict)        # returns a dataclass or None
    if isinstance(evt, GenerationFinished):
        use(evt.prompt, evt.image_url)

Subscriber (defensive, known-kinds catalog)::

    from .events import EVENT_SCHEMAS
    schema = EVENT_SCHEMAS.get(kind)
    if schema is not None and not schema.validate(data):
        print("skipping malformed", kind)

Rules
-----

1. One dataclass per kind. Field names match the wire format verbatim;
   no renaming at the schema boundary. This keeps the dataclass readable
   and means a simple ``asdict(evt)`` gives a valid payload.
2. Add new kinds by appending to the registry at the bottom, then
   running the mirror (CLAUDE.md §3). Do NOT rename an existing kind —
   emit a new one and deprecate the old with a module-level alias, so
   older plugins that still publish the old name keep working.
3. Field types are the minimum contract: subscribers may ignore extras
   (the bus doesn't strip them) but MUST tolerate absence of any field
   marked with a default. Required fields (no default) are the only
   ones a subscriber can rely on existing.
4. Never embed raw bytes. Assets flow via ``/api/assets/<hash>`` URLs
   (Guild) or ``/spellcaster/blob/<hash>`` URLs (ComfyUI blob bus) —
   ``image_url`` / ``asset_url`` / ``video_url`` point at those.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields, asdict
from typing import Any, Optional


# ── base ────────────────────────────────────────────────────────────

@dataclass
class _EventBase:
    """Common ancestor. Never instantiated directly."""

    #: Wire kind — e.g. ``"gimp.generation.finished"``. Subclasses
    #: override this as a class var via :func:`dataclass` default.
    KIND: str = field(default="", init=False, repr=False)

    @classmethod
    def validate(cls, data: dict) -> bool:
        """Cheap structural check: every field without a default must
        be present in ``data``. Doesn't verify types — the bus is
        best-effort and subscribers tolerate string-for-int etc.
        """
        if not isinstance(data, dict):
            return False
        for f in fields(cls):
            if f.name in ("KIND",):
                continue
            if (f.default is _MISSING and f.default_factory is _MISSING  # type: ignore[arg-type]
                    and f.name not in data):
                return False
        return True

    def to_payload(self) -> dict:
        """Strip KIND; the bus envelope carries it separately."""
        d = asdict(self)
        d.pop("KIND", None)
        return d


# dataclasses.MISSING sentinel (not exported by the stdlib publicly
# but needed for the default-check above).
from dataclasses import MISSING as _MISSING  # noqa: E402


# ── asset-creation / generation events ─────────────────────────────

@dataclass
class AssetCreated(_EventBase):
    """Emitted by the Guild after every successful generation is
    persisted via AssetGallery.put. Wire kind is
    ``"<origin>.asset.created"`` where origin is the plugin name.
    """

    KIND: str = field(default="*.asset.created", init=False, repr=False)
    asset_hash: str = ""
    origin: str = "unknown"
    kind: str = "generation"            # "generation" | "avatar" | "upscale" | ...
    url: str = ""                       # "/api/assets/<hash>"
    prompt: Optional[str] = None
    model: Optional[str] = None
    arch: Optional[str] = None
    seed: Optional[int] = None
    title: Optional[str] = None
    tags: list = field(default_factory=list)


@dataclass
class GenerationFinished(_EventBase):
    """Plugin finished a generation. Published when a plugin wants
    OTHER plugins to know (e.g. the Resolve Bridge watching for
    GIMP-generated frames to auto-import). Kind is
    ``"<origin>.generation.finished"``.

    Distinct from AssetCreated — this is plugin-scoped intent
    (“I finished something worth reacting to”), AssetCreated is
    Guild-scoped storage notification.
    """

    KIND: str = field(default="*.generation.finished", init=False, repr=False)
    prompt: str = ""
    model: str = ""
    arch: str = ""
    image_url: str = ""
    image_path: Optional[str] = None
    seed: Optional[int] = None


# ── directed-send events (plugin → plugin via Guild/mailbox) ───────

@dataclass
class AssetSend(_EventBase):
    """Publish when one plugin wants a specific OTHER plugin to ingest
    an asset. Kind is ``"<target>.asset.send"``. The target plugin's
    subscriber (or its mailbox puller) fetches the bytes via
    ``image_url`` and imports them into its native format. Used by
    Send-to-Resolve / Send-to-GIMP / Send-to-Darktable /
    Send-to-SillyTavern handlers across every plugin.
    """

    KIND: str = field(default="*.asset.send", init=False, repr=False)
    image_url: str = ""
    hash: str = ""
    source: str = "unknown"             # publisher's origin key
    kind: str = "generation"
    title: Optional[str] = None


@dataclass
class ClipImport(_EventBase):
    """Video-specific variant of AssetSend for Resolve — tells the
    Bridge to pull the URL into the Media Pool. Kind:
    ``"resolve.clip.import"``.
    """

    KIND: str = field(default="resolve.clip.import", init=False, repr=False)
    video_url: str = ""
    hash: Optional[str] = None
    title: Optional[str] = None
    prompt: Optional[str] = None
    preset: Optional[str] = None


# ── Resolve bus requests (Guild → Resolve) ─────────────────────────

@dataclass
class PlayheadGrab(_EventBase):
    """R122: Cinematographer wizard asks Resolve for the current
    playhead frame + turns it into a new Shot. ``want`` tells Resolve
    what to treat the grab as — ``"reference_still"`` (Cinematographer
    flow, the Guild fills the shot's reference slot) or ``"raw_frame"``
    (direct import, no shot wiring).
    """

    KIND: str = field(default="resolve.playhead.grab", init=False, repr=False)
    want: Optional[str] = None


@dataclass
class PlayheadSendToPeer(_EventBase):
    """Audit tier-1: ask Resolve to capture the playhead + push it to
    a specific peer plugin's inbox. Target MUST be a known peer key
    from the InterfaceRegistry (gimp / darktable / sillytavern).
    """

    KIND: str = field(default="resolve.playhead.send_to_peer",
                      init=False, repr=False)
    target: str = ""                    # "gimp" | "darktable" | "sillytavern"
    title: Optional[str] = None


@dataclass
class TimelineImport(_EventBase):
    """R122: ask Resolve to fetch the Guild's shotboard as an EDL +
    import it as a new timeline. ``source`` tags which Guild surface
    fired the request (``"cinematographer"``, ``"shotboard"``, …) so
    Resolve can branch on UX (e.g. auto-select the new timeline only
    for Cinematographer). Resolve queries the Guild for the EDL directly.
    """

    KIND: str = field(default="resolve.timeline.import",
                      init=False, repr=False)
    source: Optional[str] = None


# ── Resolve bus responses (Resolve → Guild) ────────────────────────

@dataclass
class PlayheadReady(_EventBase):
    """Resolve finished a PlayheadGrab. Payload varies between success
    and error paths — always include `ok` if known.
    """

    KIND: str = field(default="resolve.playhead.ready", init=False, repr=False)
    ok: Optional[bool] = None
    shot_id: Optional[str] = None
    size_bytes: Optional[int] = None
    error: Optional[str] = None


@dataclass
class TimelineImported(_EventBase):
    """Resolve finished a TimelineImport."""

    KIND: str = field(default="resolve.timeline.imported",
                      init=False, repr=False)
    ok: Optional[bool] = None
    timeline_name: Optional[str] = None
    edl_path: Optional[str] = None
    error: Optional[str] = None


@dataclass
class SendToPeerDone(_EventBase):
    """Resolve finished a PlayheadSendToPeer — echoes the outcome so
    UI chips can flip from "sending…" to done/failed.
    """

    KIND: str = field(default="resolve.send_to_peer.done",
                      init=False, repr=False)
    ok: Optional[bool] = None
    target: Optional[str] = None
    hash: Optional[str] = None
    size_bytes: Optional[int] = None
    error: Optional[str] = None


# ── upload + presence + Guild lifecycle ────────────────────────────

@dataclass
class AssetUploaded(_EventBase):
    """Emitted after ``POST /api/assets`` persists externally-supplied
    bytes (a plugin pushing a finished render into the gallery). Kind
    is ``"<origin>.asset.uploaded"``. Distinct from ``AssetCreated``:
    the Created event fires for ANY gallery insertion (including the
    Guild's own ComfyUI downloads); Uploaded fires only for the
    plugin-initiated push path. Subscribers that want “someone gave us
    a new file to look at” listen for Uploaded; subscribers that want
    “anything new in the gallery” listen for Created.
    """

    KIND: str = field(default="*.asset.uploaded", init=False, repr=False)
    hash: str = ""
    kind: str = "generation"
    title: Optional[str] = None
    model: Optional[str] = None


@dataclass
class PresenceHeartbeat(_EventBase):
    """Published by the Guild on every ``POST /api/interfaces/heartbeat``
    receipt. ``meta`` carries whatever the plugin sent (version, uptime,
    remote flag, …) — subscribers use it to update UI presence chips
    without re-polling the registry.
    """

    KIND: str = field(default="*.presence.heartbeat", init=False, repr=False)
    meta: dict = field(default_factory=dict)


@dataclass
class GuildSelfUpdateResult(_EventBase):
    """Guild self-updater finished a run. ``applied=True`` means new
    code was pulled + staged for the next restart. Listeners typically
    toast the user and offer a one-click restart.
    """

    KIND: str = field(default="guild.self_update.result",
                      init=False, repr=False)
    applied: bool = False


@dataclass
class GuildSelfUpdateError(_EventBase):
    """Guild self-updater crashed. Payload carries a human-readable
    error string for the UI toast.
    """

    KIND: str = field(default="guild.self_update.error",
                      init=False, repr=False)
    error: str = ""


# ── SpeedCoach + telemetry events ──────────────────────────────────

@dataclass
class DispatchPredicted(_EventBase):
    """Emitted when SpeedCoach shows a predicted elapsed time in a UI
    banner. Pairs with ``DispatchCompleted`` so the retrospective can
    compare actual vs predicted. ``<origin>.dispatch.predicted``."""

    KIND: str = field(default="*.dispatch.predicted", init=False, repr=False)
    job_id: str = ""
    handler: str = ""
    arch: str = ""
    median_s: float = 0.0
    p95_s: float = 0.0
    sample_size: int = 0


@dataclass
class DispatchCompleted(_EventBase):
    """Emitted after every successful (or failed) dispatch. Fires
    AFTER the AssetCreated event so subscribers ordering on ts see
    the asset first, then the telemetry. ``<origin>.dispatch.completed``."""

    KIND: str = field(default="*.dispatch.completed", init=False, repr=False)
    job_id: str = ""
    handler: str = ""
    arch: str = ""
    elapsed: float = 0.0
    predicted_elapsed: float = 0.0
    failed: bool = False
    warnings: list = field(default_factory=list)


@dataclass
class SpeedCoachSuggestion(_EventBase):
    """Emitted by SpeedCoach-aware UIs whenever a suggestion is shown,
    accepted, or dismissed. ``action`` is one of ``shown`` / ``accepted``
    / ``dismissed``. Enables the Insights tab to compute acceptance
    rates without each client publishing separately.
    ``<origin>.speedcoach.suggestion``."""

    KIND: str = field(default="*.speedcoach.suggestion",
                      init=False, repr=False)
    action: str = ""                    # "shown" | "accepted" | "dismissed"
    kind: str = ""                      # "arch_swap" | "param_trim" | "deferred_compute"
    speedup_pct: int = 0
    sample_size: int = 0
    job_id: Optional[str] = None


@dataclass
class DriftDetected(_EventBase):
    """ComfyUI node catalogue changed since the last recorded snapshot.
    Published once per session. Listeners: GIMP banner, Guild hero
    card. ``spellcaster.drift.detected``."""

    KIND: str = field(default="spellcaster.drift.detected",
                      init=False, repr=False)
    added_count: int = 0
    removed_count: int = 0
    changed_count: int = 0
    previous_hash: str = ""
    current_hash: str = ""


@dataclass
class RatingSubmitted(_EventBase):
    """User thumbs-up/down on a rendered asset. ``<origin>.rating.submitted``.

    ``verdict`` is a normalised string (``"up"`` / ``"down"`` /
    numeric score). The Insights tab uses these to compute per-handler
    thumbs rates."""

    KIND: str = field(default="*.rating.submitted", init=False, repr=False)
    asset_hash: str = ""
    verdict: str = ""
    char_id: Optional[str] = None
    handler: Optional[str] = None
    arch: Optional[str] = None


# ── registry + helpers ─────────────────────────────────────────────

#: Every kind mapped to its dataclass. Wildcard patterns ("*.X.Y")
#: are keyed separately in _WILDCARD_SCHEMAS because multiple origins
#: publish the same shape.
EVENT_SCHEMAS: dict[str, type[_EventBase]] = {
    "resolve.clip.import":           ClipImport,
    "resolve.playhead.grab":         PlayheadGrab,
    "resolve.playhead.send_to_peer": PlayheadSendToPeer,
    "resolve.playhead.ready":        PlayheadReady,
    "resolve.timeline.import":       TimelineImport,
    "resolve.timeline.imported":     TimelineImported,
    "resolve.send_to_peer.done":     SendToPeerDone,
    "guild.self_update.result":      GuildSelfUpdateResult,
    "guild.self_update.error":       GuildSelfUpdateError,
    "spellcaster.drift.detected":    DriftDetected,
}

#: Suffixes that map to a shared schema regardless of origin prefix.
#: Extended like ``{"asset.created": AssetCreated}`` — any kind ending
#: with ``.asset.created`` resolves to the same dataclass.
_WILDCARD_SCHEMAS: dict[str, type[_EventBase]] = {
    "asset.created":         AssetCreated,
    "asset.uploaded":        AssetUploaded,
    "generation.finished":   GenerationFinished,
    "asset.send":            AssetSend,
    "presence.heartbeat":    PresenceHeartbeat,
    "dispatch.predicted":    DispatchPredicted,
    "dispatch.completed":    DispatchCompleted,
    "speedcoach.suggestion": SpeedCoachSuggestion,
    "rating.submitted":      RatingSubmitted,
}


def _resolve_schema(kind: str) -> Optional[type[_EventBase]]:
    """Look up the schema class for a wire kind. Exact match first,
    then wildcard-suffix fallback. Returns None for unknown kinds —
    the bus still delivers them; subscribers just don't get a typed
    view."""
    if not isinstance(kind, str) or not kind:
        return None
    exact = EVENT_SCHEMAS.get(kind)
    if exact is not None:
        return exact
    # Match on suffix after the origin prefix: "foo.asset.created".
    for suffix, cls in _WILDCARD_SCHEMAS.items():
        if kind.endswith("." + suffix):
            return cls
    return None


def parse_event(kind: str, data: Any) -> Optional[_EventBase]:
    """Try to construct the typed event for ``kind`` from a raw
    payload dict. Returns None if the kind is unknown or the payload
    is malformed. Never raises — this is subscriber-side and must be
    robust against stale publishers."""
    cls = _resolve_schema(kind)
    if cls is None:
        return None
    if not isinstance(data, dict):
        return None
    if not cls.validate(data):
        return None
    # Build kwargs that the dataclass accepts; silently drop unknowns.
    allowed = {f.name for f in fields(cls) if f.name != "KIND"}
    kwargs = {k: v for k, v in data.items() if k in allowed}
    try:
        return cls(**kwargs)
    except Exception:
        return None


def publish_event(bus, event: _EventBase, *, origin: str) -> None:
    """Helper that normalises the kind (expanding wildcard schemas to
    ``{origin}.{suffix}``) and publishes via the bus. ``bus`` is
    anything with a ``publish(kind, origin=..., data=...)`` call —
    ``EventBus`` on the Guild side or ``CrossInterfaceClient`` on the
    plugin side."""
    kind = event.KIND
    if kind.startswith("*."):
        kind = f"{origin}.{kind[2:]}"
    bus.publish(kind, origin=origin, data=event.to_payload())


__all__ = [
    # base
    "_EventBase",
    "parse_event", "publish_event",
    "EVENT_SCHEMAS",
    # asset
    "AssetCreated", "AssetUploaded", "GenerationFinished",
    "AssetSend", "ClipImport",
    # presence + Guild lifecycle
    "PresenceHeartbeat",
    "GuildSelfUpdateResult", "GuildSelfUpdateError",
    # resolve request
    "PlayheadGrab", "PlayheadSendToPeer", "TimelineImport",
    # resolve response
    "PlayheadReady", "TimelineImported", "SendToPeerDone",
    # speedcoach + telemetry
    "DispatchPredicted", "DispatchCompleted",
    "SpeedCoachSuggestion", "DriftDetected", "RatingSubmitted",
]
