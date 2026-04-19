"""Issue cue — the Spellcaster's one-thing-at-a-time queue of unresolved work.

The temptation when scaffolding a complex install is to enumerate every
open question at once — "which LoRAs are duplicates? what scaffold is
broken? which models are unactivated? what's your intent? antenna on
which host?" Fire all five at the user simultaneously and the flow
collapses: they answer one, forget three, and the wizard spiraling
trying to keep track.

The fix is a discipline baked into both the data layer and the system
prompt: **one issue at a time**, with a persistent cue of the rest. The
user gets asked ONE question, they answer, we resolve it, we pull the
next. The system prompt reads the cue and surfaces only the head of the
queue plus a count ("3 more after this one").

Issue record:

    {
      "id":         "lshoot:sdxl:feet_fix",    # stable, dedup-able
      "kind":       "lora_shootout"
                    | "model_activation"
                    | "scaffold_broken"
                    | "antenna_unreachable"
                    | "demo_rating"
                    | "feature_install"
                    | "custom",
      "title":      "Pick a winner among 5 feet LoRAs",
      "detail":     "...context that helps the LLM explain it...",
      "priority":   int   # 0=urgent, 1=normal, 2=later
      "context":    dict  # {arch, purpose_group, candidates, ...}
      "action":     dict  # optional suggested ACTION block for the resolver
      "created":    ts,
      "status":     "open" | "deferred" | "resolved",
      "resolved_ts": ts | null,
    }

Queue discipline:
  - `enqueue(issue)` is idempotent on `id` — same id updates in place.
  - `head()` returns the highest-priority open issue (ties broken by
    FIFO / oldest-first). Returns None when nothing is open.
  - `resolve(id, note="")` marks resolved. `defer(id)` keeps it in the
    queue but flagged so head() skips it until the user explicitly
    asks about deferred items.
  - Persistence: tavern/.guild_state/issue_cue.json (atomic write).

The scaffold's system prompt reads the cue via get_cue_state() and is
told to present ONLY the head, never enumerate the rest unless the
user asks "what else is queued?".
"""
from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass, field, asdict
from typing import Optional


_CUE_LOCK = threading.Lock()


def _cue_path() -> str:
    try:
        import tavern.server as _gs  # type: ignore
        sd = getattr(_gs, "_STATE_DIR", None)
        if sd:
            return os.path.join(sd, "issue_cue.json")
    except Exception:
        pass
    return os.path.join(os.path.dirname(__file__), "issue_cue.json")


def _load() -> dict:
    p = _cue_path()
    if not os.path.isfile(p):
        return {"version": 1, "issues": []}
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {"version": 1, "issues": []}
        data.setdefault("issues", [])
        return data
    except Exception:
        return {"version": 1, "issues": []}


def _save(data: dict) -> None:
    p = _cue_path()
    os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, p)


# ── Public API ───────────────────────────────────────────────────────────

def enqueue(issue: dict) -> dict:
    """Insert or update an issue by `id`. Returns the persisted record.

    Issues without an `id` get rejected (the point of the cue is
    idempotency — callers should compute a stable id from the subject,
    e.g. `lshoot:<arch>:<purpose_group>` or `model:<name>`).
    """
    if not isinstance(issue, dict) or not issue.get("id"):
        raise ValueError("issue must be a dict with a non-empty `id`")
    now = time.time()
    entry = {
        "id":          str(issue["id"]),
        "kind":        str(issue.get("kind", "custom")),
        "title":       str(issue.get("title", "")),
        "detail":      str(issue.get("detail", "")),
        "priority":    int(issue.get("priority", 1)),
        "context":     issue.get("context") or {},
        "action":      issue.get("action")  or {},
        "created":     float(issue.get("created", now)),
        "updated":     now,
        "status":      str(issue.get("status", "open")),
        "resolved_ts": issue.get("resolved_ts"),
    }
    with _CUE_LOCK:
        data = _load()
        issues = data.get("issues", [])
        existing_idx = None
        for i, it in enumerate(issues):
            if it.get("id") == entry["id"]:
                existing_idx = i
                break
        if existing_idx is not None:
            # Preserve `created`; update everything else. Preserve status
            # `resolved` so we don't silently re-open something the user
            # already handled.
            prev = issues[existing_idx]
            entry["created"] = prev.get("created", entry["created"])
            if prev.get("status") == "resolved":
                entry["status"] = "resolved"
                entry["resolved_ts"] = prev.get("resolved_ts", now)
            issues[existing_idx] = entry
        else:
            issues.append(entry)
        data["issues"] = issues
        _save(data)
    return entry


def resolve(issue_id: str, note: str = "") -> Optional[dict]:
    with _CUE_LOCK:
        data = _load()
        for it in data.get("issues", []):
            if it.get("id") == issue_id:
                it["status"] = "resolved"
                it["resolved_ts"] = time.time()
                if note:
                    it["resolution_note"] = note[:500]
                _save(data)
                return it
    return None


def defer(issue_id: str, note: str = "") -> Optional[dict]:
    with _CUE_LOCK:
        data = _load()
        for it in data.get("issues", []):
            if it.get("id") == issue_id:
                it["status"] = "deferred"
                it["updated"] = time.time()
                if note:
                    it["defer_note"] = note[:500]
                _save(data)
                return it
    return None


def clear_resolved(older_than_s: int = 86400) -> int:
    """Drop resolved issues older than `older_than_s` seconds.

    Default: 24h. Keeps the cue file bounded without losing recent
    history. Returns the number of issues dropped.
    """
    cutoff = time.time() - older_than_s
    removed = 0
    with _CUE_LOCK:
        data = _load()
        kept = []
        for it in data.get("issues", []):
            if it.get("status") == "resolved" and \
               float(it.get("resolved_ts", 0) or 0) < cutoff:
                removed += 1
                continue
            kept.append(it)
        data["issues"] = kept
        _save(data)
    return removed


def head() -> Optional[dict]:
    """Return the highest-priority OPEN issue, or None.

    Sort key: (priority asc — lower = more urgent, then created asc —
    oldest first). Deferred items are skipped here; the user has to
    explicitly ask for them.
    """
    with _CUE_LOCK:
        data = _load()
    open_issues = [it for it in data.get("issues", [])
                   if it.get("status") == "open"]
    if not open_issues:
        return None
    open_issues.sort(key=lambda it: (it.get("priority", 1),
                                      it.get("created", 0)))
    return open_issues[0]


def counts() -> dict:
    with _CUE_LOCK:
        data = _load()
    open_n = deferred_n = resolved_n = 0
    for it in data.get("issues", []):
        status = it.get("status", "open")
        if   status == "open":     open_n += 1
        elif status == "deferred": deferred_n += 1
        elif status == "resolved": resolved_n += 1
    return {"open": open_n, "deferred": deferred_n, "resolved": resolved_n}


def list_issues(status: str = "open", limit: int = 50) -> list[dict]:
    with _CUE_LOCK:
        data = _load()
    issues = [it for it in data.get("issues", [])
              if (status == "*" or it.get("status") == status)]
    issues.sort(key=lambda it: (it.get("priority", 1),
                                 it.get("created", 0)))
    return issues[:max(1, int(limit or 50))]


def get_cue_state() -> dict:
    """One-call snapshot for the Spellcaster system prompt.

    Shape:
      {
        "head": {issue dict} | None,
        "counts": {open, deferred, resolved},
        "next_preview": [next 2 issue titles, for "and X more after this"],
      }
    """
    h = head()
    c = counts()
    # Peek at the next few so the Spellcaster can say "one more after this".
    next_preview = []
    if h:
        with _CUE_LOCK:
            data = _load()
        open_issues = [it for it in data.get("issues", [])
                       if it.get("status") == "open"
                       and it.get("id") != h.get("id")]
        open_issues.sort(key=lambda it: (it.get("priority", 1),
                                          it.get("created", 0)))
        next_preview = [{"id": it["id"], "title": it.get("title", "")}
                        for it in open_issues[:2]]
    return {
        "head":         h,
        "counts":       c,
        "next_preview": next_preview,
    }


# ── Well-known issue id shapes (callers produce these) ──────────────────

def issue_id_for_shootout(arch: str, purpose_group: str) -> str:
    return f"lshoot:{arch}:{purpose_group}"

def issue_id_for_model_activation(model_name: str) -> str:
    return f"activate:{model_name}"

def issue_id_for_antenna(host: str) -> str:
    return f"antenna:{host}"

def issue_id_for_scaffold_broken(model_name: str, scenario: str) -> str:
    return f"scaffold:{model_name}:{scenario}"


__all__ = [
    "enqueue", "resolve", "defer", "clear_resolved",
    "head", "counts", "list_issues", "get_cue_state",
    "issue_id_for_shootout", "issue_id_for_model_activation",
    "issue_id_for_antenna", "issue_id_for_scaffold_broken",
]
