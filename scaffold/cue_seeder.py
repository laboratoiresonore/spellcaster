"""Cue auto-seeder — populates the issue cue from current system state.

Runs once at Guild startup and again on-demand via /api/spellcaster/cue/reseed.
Walks the persisted registries and enqueues one issue per unresolved item:

  - LoRA groups with >=2 candidates and no crowned winner     → lora_shootout
  - Detected models that aren't activated yet                  → model_activation
  - Declared-remote services whose antenna isn't reachable     → antenna_unreachable

`issue_cue.enqueue` is idempotent on `id`, so re-seeding is safe — existing
open issues update in place; already-resolved ones stay resolved. The
well-known id builders in issue_cue guarantee stable identifiers across
runs, so a LoRA-shootout issue for `sdxl:feet_fix` stays the same entry
whether you seed it fresh at boot or the Spellcaster enqueues it
mid-conversation.

Each seeder is wrapped so a failure in one bucket (e.g. LoRA registry
unreadable) doesn't poison the others. seed_all() returns a count dict
that the endpoint echoes back to the UI and the Spellcaster narrates.
"""
from __future__ import annotations

from typing import Optional


def seed_from_lora_groups(lora_registry: dict) -> int:
    """For each (arch, purpose_group) with >=2 candidates and no crowned
    winner, enqueue a lora_shootout issue.

    Idempotent: re-seeding updates the existing issue in place rather
    than stacking duplicates. Uses issue_cue.issue_id_for_shootout for
    stable ids.
    """
    try:
        from scaffold.lora_grouping import groups_needing_pick
        from scaffold.issue_cue import enqueue, issue_id_for_shootout
    except Exception as e:
        print(f"  [cue seeder] lora groups import failed: {e}")
        return 0
    added = 0
    try:
        for g in groups_needing_pick(lora_registry or {}):
            candidates_preview = [c.split("\\")[-1].split("/")[-1]
                                  for c in g["candidates"][:3]]
            extra = f" (+{g['count'] - 3} more)" if g["count"] > 3 else ""
            enqueue({
                "id":       issue_id_for_shootout(g["arch"], g["purpose_group"]),
                "kind":     "lora_shootout",
                "title":    f"Pick a winner among {g['count']} "
                            f"{g['purpose_group'].replace('_', ' ')} LoRAs ({g['arch']})",
                "detail":   f"Candidates: {', '.join(candidates_preview)}{extra}",
                "priority": 1,
                "context":  {"arch":          g["arch"],
                             "purpose_group": g["purpose_group"],
                             "candidates":    g["candidates"]},
                "action":   {"type":          "lora_shootout",
                             "arch":          g["arch"],
                             "purpose_group": g["purpose_group"]},
            })
            added += 1
    except Exception as e:
        print(f"  [cue seeder] lora groups failed: {e}")
    return added


def seed_from_unactivated_models(detected_models: list) -> int:
    """For each detected model without an `activated` flag, enqueue
    a model_activation issue.

    Priority 2 (later) — model activation is always user-initiated
    (they click an unactivated model in the sidebar). We surface it
    via the cue only when the user asks the Spellcaster directly.
    """
    try:
        from scaffold.model_activation import all_activation_statuses
        from scaffold.issue_cue import enqueue, issue_id_for_model_activation
    except Exception as e:
        print(f"  [cue seeder] model activation import failed: {e}")
        return 0
    added = 0
    try:
        statuses = all_activation_statuses(detected_models or [])
        for name, status in statuses.items():
            if status.get("activated"):
                continue
            enqueue({
                "id":       issue_id_for_model_activation(name),
                "kind":     "model_activation",
                "title":    f"Activate {name.split('/')[-1].split(chr(92))[-1]}",
                "detail":   ("Pre-configured from your arch profile — just "
                             "run the scaffold calibration then confirm."
                             if status.get("has_presettings")
                             else "No presettings yet — walk through the "
                             "test-gen battery to set this model up."),
                "priority": 2,
                "context":  {"model":           name,
                             "arch":            status.get("arch"),
                             "has_presettings": status.get("has_presettings")},
                "action":   {"type":  "scaffold_calibrate", "model": name},
            })
            added += 1
    except Exception as e:
        print(f"  [cue seeder] model activation failed: {e}")
    return added


def seed_from_unverified_antennas() -> int:
    """For every declared-remote service whose antenna isn't reachable,
    enqueue an antenna_unreachable issue at priority 0 (urgent — blocks
    anything that needs that service).
    """
    try:
        from scaffold.network_survey import load_survey
        from scaffold.issue_cue import enqueue, issue_id_for_antenna
    except Exception as e:
        print(f"  [cue seeder] network survey import failed: {e}")
        return 0
    added = 0
    try:
        for key, loc in load_survey().items():
            if loc.placement != "remote":
                continue
            if loc.verified:
                continue
            enqueue({
                "id":       issue_id_for_antenna(loc.host),
                "kind":     "antenna_unreachable",
                "title":    f"Antenna on {loc.host} is unreachable ({key})",
                "detail":   (loc.last_probe_error
                             or "no probe yet — ask the user to start the antenna"),
                "priority": 0,
                "context":  {"host":         loc.host,
                             "service":      key,
                             "port":         loc.port,
                             "antenna_port": loc.antenna_port},
                "action":   {"type": "antenna_test",
                             "host": loc.host,
                             "port": loc.antenna_port},
            })
            added += 1
    except Exception as e:
        print(f"  [cue seeder] antenna seed failed: {e}")
    return added


def seed_from_service_conflicts() -> int:
    """Detect the same service present on multiple hosts and enqueue one
    `service_conflict` issue per clash.

    Example: GIMP installed locally AND reported by the antenna on
    192.168.x.y — we don't know which one the user wants as the
    canonical target. The Spellcaster asks and re-declares the
    network_survey accordingly.

    Signals:
      - Local: antenna/detect.detect_installed_services() against the
        remote_services catalog, run on THIS host (the Guild's host).
      - Remote: for each survey entry placed "remote" with a verified
        antenna, fetch its /status and read services_detected.

    A conflict issue is created only when a service is `installed=True`
    on 2+ hosts AND the user hasn't already declared it clearly (skipped
    services, and services placed "not_installed" on the other host, are
    not conflicts).
    """
    try:
        from scaffold.issue_cue import enqueue
        from scaffold.network_survey import (
            load_survey, load_service_catalog, probe_antenna,
        )
    except Exception as e:
        print(f"  [cue seeder] conflicts: imports failed: {e}")
        return 0

    catalog = load_service_catalog()
    survey = load_survey()

    # ── Gather per-host inventories (host label -> {svc_key: installed}) ──
    inventories: dict[str, dict[str, bool]] = {}

    # Local host — detect directly here.
    try:
        import sys as _sys, os as _os
        _repo_root = _os.path.abspath(_os.path.join(
            _os.path.dirname(__file__), ".."))
        if _repo_root not in _sys.path:
            _sys.path.insert(0, _repo_root)
        from antenna import detect as _detect  # type: ignore
        local_probe = _detect.detect_installed_services(catalog) or {}
        inventories["Local"] = {
            k: bool((v or {}).get("installed"))
            for k, v in local_probe.items()
        }
    except Exception as e:
        print(f"  [cue seeder] conflicts: local detect failed: {e}")

    # Remote antennas declared by the user. We only probe one per unique
    # host even if multiple services share that host — /status returns
    # the full services_detected map so one call covers everything.
    remote_hosts_seen: set[str] = set()
    for key, loc in survey.items():
        if loc.placement != "remote" or not loc.host:
            continue
        if loc.host in remote_hosts_seen:
            continue
        remote_hosts_seen.add(loc.host)
        try:
            ok, _msg, status = probe_antenna(loc.host, loc.antenna_port)
            if not ok:
                continue
            services_detected = (status or {}).get("services_detected") or {}
            inventories[loc.host] = {
                k: bool((v or {}).get("installed"))
                for k, v in services_detected.items()
                if isinstance(v, dict)
            }
        except Exception as e:
            print(f"  [cue seeder] conflicts: antenna {loc.host} probe failed: {e}")

    if len(inventories) < 2:
        return 0          # can't have a conflict with only one host

    # ── Find conflicts: same service installed on 2+ hosts ─────────────
    # Build per-service host list.
    by_service: dict[str, list[str]] = {}
    for host_label, inv in inventories.items():
        for svc, installed in inv.items():
            if installed:
                by_service.setdefault(svc, []).append(host_label)

    added = 0
    for svc, hosts in by_service.items():
        if len(hosts) < 2:
            continue
        # Skip if the user already explicitly declared this service as
        # SKIP or NOT_INSTALLED on one side — they've resolved it implicitly.
        loc = survey.get(svc)
        if loc and loc.placement in ("skip", "not_installed"):
            continue
        svc_meta = next((s for s in catalog if s.get("key") == svc), {})
        label = svc_meta.get("label") or svc
        try:
            enqueue({
                "id":       f"conflict:{svc}",
                "kind":     "service_conflict",
                "title":    f"{label} detected on {len(hosts)} hosts — "
                            f"pick which is canonical",
                "detail":   f"Found on: {', '.join(hosts)}. Only one can be "
                            f"the default target — the others get skipped "
                            f"(still available via manual override later).",
                "priority": 1,
                "context":  {
                    "service": svc,
                    "label":   label,
                    "hosts":   hosts,
                },
                # The resolver re-declares the network_survey entry to
                # the user's pick; Spellcaster walks them through it
                # conversationally.
                "action":   {"type":    "network_declare",
                             "key":     svc,
                             "placement": "PICK_ONE"},   # placeholder
            })
            added += 1
        except Exception as e:
            print(f"  [cue seeder] conflicts: enqueue {svc} failed: {e}")
    return added


def auto_resolve_stale() -> int:
    """Mark issues resolved that no longer match reality.

    - lora_shootout issues whose group now has a crowned winner or
      fewer than 2 candidates.
    - model_activation issues whose model has been activated.
    - antenna_unreachable issues whose host now probes clean.

    Keeps the cue honest when state changes outside the Spellcaster
    (e.g. user activated a model via another surface, or fixed an
    antenna manually).
    """
    try:
        from scaffold.issue_cue import list_issues, resolve
    except Exception:
        return 0
    resolved_n = 0
    open_issues = list_issues(status="open", limit=500)

    # LoRA groups
    try:
        from scaffold.lora_grouping import enumerate_groups
        import tavern.server as _gs  # type: ignore
        lora_reg = getattr(_gs, "_LORA_REGISTRY", {}) or {}
        groups = enumerate_groups(lora_reg)
        for it in open_issues:
            if it.get("kind") != "lora_shootout":
                continue
            ctx = it.get("context", {}) or {}
            key = (ctx.get("arch", ""), ctx.get("purpose_group", ""))
            members = groups.get(key) or []
            if len(members) < 2 or any(m.get("preferred_for_purpose")
                                         for m in members):
                resolve(it["id"], note="auto-resolved: no longer duplicated")
                resolved_n += 1
    except Exception as e:
        print(f"  [cue seeder] auto-resolve lora failed: {e}")

    # Activations
    try:
        from scaffold.model_activation import is_activated
        for it in open_issues:
            if it.get("kind") != "model_activation":
                continue
            model = (it.get("context") or {}).get("model", "")
            if model and is_activated(model):
                resolve(it["id"], note="auto-resolved: model activated")
                resolved_n += 1
    except Exception as e:
        print(f"  [cue seeder] auto-resolve activation failed: {e}")

    # Antennas
    try:
        from scaffold.network_survey import load_survey
        survey = load_survey()
        for it in open_issues:
            if it.get("kind") != "antenna_unreachable":
                continue
            ctx = it.get("context") or {}
            host = ctx.get("host", "")
            svc = ctx.get("service", "")
            loc = survey.get(svc)
            if loc and loc.host == host and loc.verified:
                resolve(it["id"], note="auto-resolved: antenna reachable")
                resolved_n += 1
    except Exception as e:
        print(f"  [cue seeder] auto-resolve antenna failed: {e}")

    # Service conflicts — resolve once the user has declared a winning
    # host via network_declare (survey.placement=local OR remote with a
    # specific host). A conflict is STILL open only when we'd otherwise
    # detect the same service on 2+ hosts.
    try:
        from scaffold.network_survey import load_survey
        survey = load_survey()
        for it in open_issues:
            if it.get("kind") != "service_conflict":
                continue
            svc = (it.get("context") or {}).get("service", "")
            loc = survey.get(svc)
            # If the user declared a concrete placement (local / remote
            # with a chosen host / skip / not_installed), the conflict
            # is resolved — they picked.
            if loc and loc.placement in ("local", "remote", "skip",
                                           "not_installed"):
                if loc.placement != "remote" or loc.host:
                    resolve(it["id"],
                            note=f"auto-resolved: placement={loc.placement}")
                    resolved_n += 1
    except Exception as e:
        print(f"  [cue seeder] auto-resolve conflict failed: {e}")

    return resolved_n


def seed_all(lora_registry: Optional[dict] = None,
             detected_models: Optional[list] = None) -> dict:
    """Entry point. Call once at Guild startup, and again from
    /api/spellcaster/cue/reseed.

    Accepts the caller's already-loaded registries to avoid the network
    roundtrip of `preference_calibration.discover_models` at boot.
    Returns a count summary the endpoint can echo back.
    """
    out = {
        "lora":      0,
        "models":    0,
        "antennas":  0,
        "resolved":  0,
    }
    if lora_registry is None:
        try:
            import tavern.server as _gs  # type: ignore
            lora_registry = getattr(_gs, "_LORA_REGISTRY", {}) or {}
        except Exception:
            lora_registry = {}
    out["lora"] = seed_from_lora_groups(lora_registry)

    if detected_models is None:
        # Boot path can't always reach ComfyUI — pass [] rather than
        # blocking startup on a possibly-slow /object_info fetch.
        detected_models = []
        try:
            from spellcaster_core.preference_calibration import discover_models
            import tavern.server as _gs  # type: ignore
            url = getattr(_gs, "COMFYUI_URL", "")
            if url:
                detected_models = discover_models(url)
        except Exception:
            detected_models = []
    out["models"] = seed_from_unactivated_models(detected_models)

    out["antennas"] = seed_from_unverified_antennas()
    out["conflicts"] = seed_from_service_conflicts()
    out["resolved"] = auto_resolve_stale()
    return out


__all__ = [
    "seed_from_lora_groups",
    "seed_from_unactivated_models",
    "seed_from_unverified_antennas",
    "seed_from_service_conflicts",
    "auto_resolve_stale",
    "seed_all",
]
