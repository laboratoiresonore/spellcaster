#!/usr/bin/env python3
"""LLM-augmented morning briefing for Claude.

Built per the 2026-05-13 user directive: "have the local LLM
automatically run cycles that will augment app knowledge for Claude
and otherwise do as much as it can dependably to enhance Claude's
intervention for debugging and maintenance, on any app in the
ecosystem."

Workflow
--------
1. Collect *facts* about the ecosystem since the last briefing:
   - Last night_maintenance.py report (~/.voodoomaster/night_report_*.md)
   - Recent git commits across spellcaster + distro-runtime
   - Open PR list (gh CLI if available)
   - Live caps server snapshot (node_count, flags, backend state)
   - Active claude_session.py sessions + their tasks
   - Recent unresolved log errors (filtered for recovered crashes)

2. Hand the fact-dump to the local LLM with a system prompt asking
   for a structured briefing:
   - What changed overnight
   - What's still broken or in flight
   - Where Claude's attention is needed
   - Open questions worth asking

3. Write the result to ``<repo>/_dev_docs/morning_briefing.md`` so
   the next Claude session can read it at start (per CLAUDE.md §2).

Designed for unattended nightly execution (Windows Task Scheduler /
NSSM / cron). All sub-checks are best-effort: a failure in any one
section degrades to a "section unavailable" note rather than
aborting the whole briefing — Claude needs SOMETHING in the morning
even if the LLM is down or git is unreachable.

Usage
-----
    python tools/llm_morning_briefing.py
    python tools/llm_morning_briefing.py --output _dev_docs/morning_briefing.md
    python tools/llm_morning_briefing.py --model qwen3-30b-a3b
    python tools/llm_morning_briefing.py --no-llm  # raw facts only

Exit codes: 0 normal; 1 if --no-llm and any fact-collector failed.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

REPO = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = REPO / "_dev_docs" / "morning_briefing.md"
# Defaults pulled from environment to avoid baking a LAN IP into
# tracked code (H2 hygiene). Override with --llm-endpoint / --caps.
_HOST = os.environ.get("COMFYUI_HOST", "127.0.0.1")
DEFAULT_LLM_ENDPOINT = os.environ.get(
    "LLM_ENDPOINT_URL",
    f"http://{_HOST}:1234/v1/chat/completions")
DEFAULT_LLM_MODEL = os.environ.get("LLM_BRIEFING_MODEL",
                                    "qwen3-30b-a3b")
DEFAULT_CAPS = os.environ.get("COMFYUI_CAPS_URL",
                               f"http://{_HOST}:8191")


# ─── Fact collectors ──────────────────────────────────────────────────────────

def _safe(fn, label):
    """Call a fact-collector; on any exception return a placeholder block."""
    try:
        return fn()
    except Exception as e:  # noqa: BLE001 — every collector is best-effort
        return f"_({label} collector failed: {type(e).__name__}: {e})_"


def collect_night_report() -> str:
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    path = Path.home() / ".voodoomaster" / f"night_report_{today}.md"
    if not path.is_file():
        # Try yesterday's
        from datetime import timedelta
        yest = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y%m%d")
        path = Path.home() / ".voodoomaster" / f"night_report_{yest}.md"
    if not path.is_file():
        return "_(no night_maintenance report found in ~/.voodoomaster/)_"
    text = path.read_text(encoding="utf-8")
    return f"_Source: `{path}` — last modified {datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat(timespec='seconds')}_\n\n```\n{text[:4000]}\n```"


def collect_recent_commits() -> str:
    """Recent commits in the last 36 h across all sibling repos.

    Tighter than the previous 'last 15 commits' window because the
    LLM was reading old PRs as 'overnight changes' — fact dump was
    factually right (top 15 commits) but the briefing system prompt
    asks for OVERNIGHT, and the LLM had no way to distinguish
    'today' from 'last week' without dates.

    36 h covers a full work-day overnight while still trimming
    historical noise. Repos with zero commits in the window get a
    'no overnight commits' line so the LLM can correctly report
    health=green-and-quiet.
    """
    # Sibling-repo names come from env so they aren't baked into
    # tracked code (the leak-check regex blocks the distro-runtime
    # name; per-dev override via DISTRO_REPO_NAME).
    distro_name = os.environ.get("DISTRO_REPO_NAME", "")
    out_lines = []
    targets = [("spellcaster", REPO),
               ("spellcaster_NSFW", Path.home() / "spellcaster_NSFW")]
    if distro_name:
        targets.insert(1, ("distro-runtime", Path.home() / distro_name))
    for repo_label, repo_path in targets:
        if not (repo_path / ".git").is_dir():
            continue
        try:
            p = subprocess.run(
                ["git", "-C", str(repo_path), "log", "--oneline",
                 "--since=36 hours ago", "-30"],
                capture_output=True, text=True, timeout=10, check=True)
            body = p.stdout.strip() or "(no commits in last 36 h)"
            out_lines.append(f"### {repo_label} ({repo_path}) — last 36 h\n```\n{body}\n```")
        except subprocess.CalledProcessError as e:
            out_lines.append(f"### {repo_label}: git failed\n```\n{e.stderr}\n```")
    return "\n\n".join(out_lines) if out_lines else "_(no git repos resolvable)_"


def collect_open_prs() -> str:
    org = os.environ.get("GITHUB_ORG", "laboratoiresonore")
    distro_name = os.environ.get("DISTRO_REPO_NAME", "")
    out_lines = []
    targets = [(f"{org}/spellcaster", "spellcaster"),
               (f"{org}/spellcaster_NSFW", "spellcaster_NSFW")]
    if distro_name:
        targets.insert(1, (f"{org}/{distro_name}", "distro-runtime"))
    for repo_slug, label in targets:
        try:
            p = subprocess.run(
                ["gh", "-R", repo_slug, "pr", "list", "--state", "open",
                 "--json", "number,title,headRefName,mergeStateStatus",
                 "--limit", "10"],
                capture_output=True, text=True, timeout=15, check=True)
            data = json.loads(p.stdout or "[]")
        except (subprocess.CalledProcessError, json.JSONDecodeError, FileNotFoundError):
            continue
        if not data:
            out_lines.append(f"- **{label}**: no open PRs")
            continue
        rows = [f"  - #{pr['number']} `{pr['headRefName']}` — {pr['title']}  ({pr['mergeStateStatus']})"
                for pr in data]
        out_lines.append(f"- **{label}** ({len(data)} open):\n" + "\n".join(rows))
    return "\n".join(out_lines) if out_lines else "_(gh CLI unavailable or all repos clean)_"


def collect_capabilities(caps_url: str) -> str:
    try:
        req = urllib.request.Request(
            f"{caps_url}/healthz",
            headers={"Connection": "close",
                     "User-Agent": "spellcaster-morning-briefing"})
        with urllib.request.urlopen(req, timeout=5) as r:
            healthz = json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        return f"_(caps server at {caps_url} unreachable)_"
    try:
        req = urllib.request.Request(
            f"{caps_url}/v1/capabilities",
            headers={"Connection": "close",
                     "User-Agent": "spellcaster-morning-briefing"})
        with urllib.request.urlopen(req, timeout=30) as r:
            caps = json.loads(r.read().decode("utf-8"))
    except Exception:
        return f"_(caps payload fetch failed)_"
    server = caps.get("server", {})
    backend = caps.get("backend", {})
    flags = caps.get("feature_flags", {})
    license_info = caps.get("license", {})
    lines = [
        f"- ComfyUI: `{server.get('comfyui_version')}` on `{server.get('host')}:{server.get('port')}`",
        f"- backend state: **{backend.get('state')}**",
        f"- node_count: {caps.get('node_count')}",
        f"- feature flags ON: {sum(1 for v in flags.values() if v)}/{len(flags)}",
        f"- license: {license_info.get('tier','?')} / {license_info.get('channel','?')}",
        f"- caps cache: {'fresh' if healthz.get('caps_cache',{}).get('fresh') else 'stale'} "
        f"(age {healthz.get('caps_cache',{}).get('age_sec','?')}s)",
    ]
    return "\n".join(lines)


def collect_active_sessions() -> str:
    coord = REPO / "tools" / "claude_session.py"
    if not coord.is_file():
        return "_(tools/claude_session.py not present)_"
    try:
        p = subprocess.run(
            [sys.executable, str(coord), "list"],
            capture_output=True, text=True, timeout=5)
        return f"```\n{p.stdout.strip()}\n```"
    except subprocess.CalledProcessError as e:
        return f"_(session list failed: {e.stderr})_"


def collect_log_tail() -> str:
    """Collect log slices for the LLM, filtering pre-recovered errors.

    Same logic as ``night_maintenance.check_log_errors``: only show
    entries AFTER the latest ``restart-ok`` / ``boot start`` —
    everything before that has been resolved by the watchdog and
    just confuses the LLM into worrying about historical crashes
    that already self-healed.
    """
    out_lines = []
    log_dir = Path.home() / ".voodoomaster"
    for name in ("launcher.log", "comfyui.log"):
        path = log_dir / name
        if not path.is_file():
            continue
        try:
            full = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        # Find the latest recovery marker. Anything before it is resolved.
        last_ok_idx = -1
        scan_window = full[-500:]  # bound the scan
        for i, ln in enumerate(scan_window):
            if "restart-ok" in ln or "boot start" in ln:
                last_ok_idx = i
        unresolved = scan_window[last_ok_idx + 1:] if last_ok_idx >= 0 else scan_window
        # Cap the slice the LLM sees
        slice_ = unresolved[-20:] if unresolved else []
        if not slice_:
            out_lines.append(f"### {name}\n_(no unresolved entries since last recovery)_")
        else:
            label = (f"### {name} (last 20 unresolved lines since "
                     f"{'recovery' if last_ok_idx >= 0 else 'log start'})")
            out_lines.append(f"{label}\n```\n" + "\n".join(slice_) + "\n```")
    return "\n\n".join(out_lines) if out_lines else "_(no log files in ~/.voodoomaster/)_"


# ─── Briefing builder ─────────────────────────────────────────────────────────

def build_facts(args) -> dict:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "night_report": _safe(collect_night_report, "night_report"),
        "recent_commits": _safe(collect_recent_commits, "recent_commits"),
        "open_prs": _safe(collect_open_prs, "open_prs"),
        "capabilities": _safe(lambda: collect_capabilities(args.caps), "capabilities"),
        "active_sessions": _safe(collect_active_sessions, "active_sessions"),
        "log_tail": _safe(collect_log_tail, "log_tail"),
    }


def facts_to_markdown(facts: dict) -> str:
    return "\n\n".join([
        f"# Morning briefing — {facts['generated_at']}",
        "## Night maintenance report",
        facts["night_report"],
        "## Recent commits",
        facts["recent_commits"],
        "## Open PRs",
        facts["open_prs"],
        "## Live capabilities",
        facts["capabilities"],
        "## Active Claude sessions",
        facts["active_sessions"],
        "## Recent logs",
        facts["log_tail"],
    ])


def llm_summarize(facts_md: str, endpoint: str, model: str) -> str:
    system = (
        "You are a senior engineer producing a morning briefing for a "
        "Claude Code session that is about to start. Read the fact "
        "dump and produce a STRUCTURED briefing under these headings:\n\n"
        "**HEALTH**: green / yellow / red across the stack (Voodoomaster, "
        "distro-runtime, spellcaster).\n\n"
        "**OVERNIGHT CHANGES (last 36 h)**: 3-7 bullets summarizing what "
        "happened. The 'Recent commits' section in the fact dump is "
        "already date-filtered to the last 36 h — if a repo shows '(no "
        "commits in last 36 h)' just say 'quiet'. Do NOT list every "
        "commit ID; aggregate (e.g. '5 sync PRs landed', "
        "'auto-patch tool added').\n\n"
        "**STILL BROKEN OR IN FLIGHT**: open PRs (from the fact dump's "
        "'Open PRs' section — those are CURRENT, regardless of age), "
        "failing tests, unresolved log errors — be specific about which "
        "file / which PR / which timestamp.\n\n"
        "**WHERE CLAUDE'S ATTENTION IS NEEDED**: 2-5 concrete tasks the "
        "incoming Claude session should consider taking. Prefer "
        "specifics over generalities.\n\n"
        "**OPEN QUESTIONS**: things only a human can answer — flag "
        "them so Claude knows to ask.\n\n"
        "Be concise (under 500 words total). Use file paths verbatim. "
        "Do NOT speculate or pad. Do NOT list raw commit IDs unless "
        "they're actually referenced elsewhere in the briefing."
    )
    user = f"FACT DUMP\n\n{facts_md}"
    body = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "max_tokens": 2048,
        "temperature": 0.2,
        "stream": False,
    }).encode("utf-8")
    req = urllib.request.Request(
        endpoint, data=body,
        headers={"Content-Type": "application/json",
                 "User-Agent": "spellcaster-morning-briefing",
                 "Connection": "close"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=300) as r:
        payload = json.loads(r.read().decode("utf-8"))
    return payload["choices"][0]["message"]["content"]


# ─── Main ─────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--output", default=str(DEFAULT_OUTPUT))
    ap.add_argument("--llm-endpoint", default=DEFAULT_LLM_ENDPOINT)
    ap.add_argument("--model", default=DEFAULT_LLM_MODEL)
    ap.add_argument("--caps", default=DEFAULT_CAPS)
    ap.add_argument("--no-llm", action="store_true",
                    help="Skip LLM summarization; write raw facts only.")
    args = ap.parse_args()

    print(f"Morning briefing — {datetime.now(timezone.utc).isoformat(timespec='seconds')}")
    facts = build_facts(args)
    facts_md = facts_to_markdown(facts)

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)

    if args.no_llm:
        out.write_text(facts_md, encoding="utf-8")
        print(f"Wrote raw facts → {out}")
        return 0

    print(f"Sending {len(facts_md)} chars to LLM at {args.llm_endpoint} ({args.model})…")
    try:
        summary = llm_summarize(facts_md, args.llm_endpoint, args.model)
    except (urllib.error.URLError, OSError, KeyError) as e:
        print(f"LLM call failed ({type(e).__name__}: {e}); writing raw facts.",
              file=sys.stderr)
        out.write_text(facts_md, encoding="utf-8")
        return 1

    final = "\n\n".join([
        f"# Morning briefing — {facts['generated_at']}",
        f"_Generated by `tools/llm_morning_briefing.py` (LLM: `{args.model}`)._",
        "",
        "## LLM summary",
        "",
        summary,
        "",
        "---",
        "",
        "## Source facts (for reference)",
        "",
        facts_md,
    ])
    out.write_text(final, encoding="utf-8")
    print(f"Wrote briefing → {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
