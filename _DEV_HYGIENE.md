# _DEV_HYGIENE.md — shared developer-hygiene rules

> **Canonical** version of the rules below. Each repo in the
> Laboratoire Sonore ecosystem (Voodoomancer / spellcaster /
> spellcaster_NSFW / Laborantin / Whimweaver) keeps a byte-identical
> copy of this file at its repo root. Drift between copies is a bug —
> match the version that has the most-recent modification date and
> open a PR re-syncing the others.
>
> **Why a shared file rather than a per-repo §2 enumeration:** every
> rule below was previously copied across 3-4 repos with different
> R-numbers. A single typo or rule update meant a 4-file edit, and
> cross-references like "(R6 from Voodoomancer)" silently broke when
> any one repo renumbered. Vendoring the common floor here means
> per-repo §2 sections only need to enumerate rules that are
> genuinely repo-local.
>
> **Future:** this file becomes a shipped artifact under `voodoo-core`
> (which the consumers already vendor at `vendor/voodoo-core/`).
> Until that lands, byte-identical copies + a CI drift check are the
> mechanism.

---

## H1. `git add -A` and `git add .` are forbidden

Stage explicit paths only. Most repos enforce this with a PreToolUse
hook on `Bash(git add *)` that blocks the offending forms.

**Why:** ten thousand committed `.pyc`, an accidentally-staged
`signal_bridge_config.json`, a `~/.cache/...` blob — once. Never
again. The hook is the floor; this rule is what tells future-you why
the hook is there.

## H2. NEVER commit personal data

The forbidden set:

- LAN / Tailscale IP addresses (use `${THEO_HOST}` / `${WORKSTATION_HOST}` placeholders in docs)
- Personal usernames (use `${USER}` / `<user>`)
- Personal email addresses
- GitHub Personal Access Tokens, OAuth client secrets, license tokens
- API keys (Brave, Wolfram, Reddit, Google OAuth `credentials.json`)

Each repo's PreToolUse hook on `Bash(git commit *)` blocks staged
files matching the canonical leak regex.

**Why:** repos have GitHub remotes. Even on a private repo, treating
personal data as committable corrodes the discipline that keeps
secrets *out*. The placeholder convention also makes `_dev_docs/`
markdown safe to share between sibling Claude instances.

## H3. `datetime.now(timezone.utc)`, never `datetime.utcnow()`

Deprecated in Python 3.12+. Returns a naive datetime that breaks
ICS export, Jordan-clock computation, audit-log timestamps, and any
cross-process state with timezone semantics.

**Why:** a timezone-naive timestamp 7 hours off the actual filing
time is the difference between a Jordan stay and a trial. The fix
is one import + one method swap; the cost of the bug is everything.

## H4. ComfyUI node names verified via `/object_info` — never hallucinated

Before any workflow change ships, hit `${COMFYUI_HOST}:8188/object_info`
(or wherever ComfyUI is bound) and confirm the node exists with the
expected inputs.

**Why:** ComfyUI's custom-node ecosystem renames nodes regularly. A
hallucinated name fails silently — the workflow returns a blank
tensor, the error surfaces downstream as "tensor shape mismatch",
and the actual cause is buried two layers down.

## H5. Resource hygiene — `closing()`, `with`, `timeout=`

- `with closing(sqlite3.connect(...)) as conn:` — never bare `connect()` without close
- `with open(...)` — never bare `open()` without close
- `timeout=` on EVERY network call (urllib, requests, httpx, aiohttp)

**Why:** ecosystem code lives in long-running processes
(signal_bridge.py, NSSM services, voodoomaster.exe, the FastAPI
matrix UI). A leaked SQLite connection corrupts WAL an hour later;
a network call without timeout blocks the whole process for the
user. These three patterns are the floor.

## H6. SFW / NSFW separation is editorial — never bypass

The Laboratoire Sonore stack ships TWO source repos for the
Spellcaster engine:

- `laboratoiresonore/spellcaster` — public, SFW, the auto-patch
  source. Commit history must be safe for public auditing.
- `laboratoiresonore/spellcaster_NSFW` — private, NSFW = SFW +
  adult-mode extensions. End-user Voodoomancer clients
  auto-update FROM this repo.

Cross-cutting concerns:

- The downstream `nsfw/` directory in the NSFW repo is gitignored
  hard. Never force-add (`git add -f`) into it.
- An auto-patch bot pulls every SFW commit forward into NSFW,
  preserving NSFW-only files. NSFW additions never flow back to
  SFW.
- Voodoomancer-distro edits live in `voodoomancer-distro/` AND
  `spellcaster/nsfw/` — never in the public `spellcaster/` paths.

**Why:** solicitor / employer / public-search auditability. A leak
in the wrong direction corrodes the entire distribution model.

## H7. Cross-references by name, not by number

When one CLAUDE.md references a rule in another, use the rule's
title, never its R-number:

  GOOD: `(see Voodoomancer §2 — "Repo-boundary rule")`
  BAD:  `(R2 from Voodoomancer)`

**Why:** R-numbers shift when a rule is added/removed/reordered.
Title-based references survive renumbering. The voodoomaster/CLAUDE.md
2026-05-06 audit found three R-number cross-refs that had silently
gone stale; this rule prevents the next round.

---

*This file is repo-local but byte-identical across consumers.
If you see drift, it's a bug — sync to the most-recent version.*
