# 20260718-wip-consolidation

**Branch:** `hermes/spellcaster/20260718-wip-consolidation`
**Base:** `ccef78a2` (main)
**Commit:** `deff83fa`
**Author:** Claude, on the user's 2026-07-18 instruction to land the outstanding
working-tree work across the fleet.

## What this is

A **consolidation commit, not a feature change.** The working tree had 208
uncommitted files that had accumulated since the last commit on `main`. The
user directed that this work be committed and pushed rather than left sitting
one `git reset` from loss.

This is explicitly **not** a reviewed-change-by-change PR. It is a rescue of
existing working-tree state onto a branch where it is durable and reviewable.

## Files touched

207 files committed. Composition:

| Kind | Count (approx) |
|---|---|
| Modified Python source | 61 |
| Showcase / asset images (`assets/*.png`, `.gif`, `.webp`) | 135 |
| Docs + JSON config | 12 |

Full list: `git show --stat deff83fa`.

## Deliberately EXCLUDED

- **Junk**: build logs, `.bak-*` files, `_archived/` and temp directories,
  playwright artifacts, `_PUSH_*.ps1` / `_FIX_*.ps1` helper scripts. Committing
  these would pollute history permanently; per the NO-SUDO-POPUP rule the
  `_PUSH_*`/`_FIX_*` scripts should be deleted, not committed.
- **Personal data**: none found in this repo (the pre-commit personal-data
  guard did not fire here). Where it fired in sibling repos (whimweaver,
  Voodoomancer) the offending files were excluded, **not** bypassed --
  `SKIP_LEAK_CHECK` was never used.

## Verification performed

- Secret scan over the full staged diff (GitHub PAT, `hf_`, `sk-`, AWS keys,
  private-key headers, JWTs, hardcoded `password=`/`api_key=` literals):
  **no hits**.
- Repo pre-commit personal-data guard: **passed** (did not fire).
- `spellcaster` is a **PUBLIC** repo; the user was told so explicitly and
  confirmed the push after being shown the risk.

## NOT verified -- and it CANNOT be, in this checkout

The 207 files were **not** reviewed individually. No test evidence line appears
in this plan because **no test in this repo can currently pass**. Measured
2026-07-18, not assumed:

| Attempt | Result |
|---|---|
| `python -m pytest tests/ -q` | `13 errors during collection`, **no tests collected** |
| `python tests/test_model_coverage.py` | `ModuleNotFoundError: No module named 'spellcaster_core.architectures'` |
| `python tests/night_maintenance.py --dry-mode` | `error: unrecognized arguments: --dry-mode` |
| `python -c "import spellcaster_core"` | `ModuleNotFoundError: No module named 'spellcaster_core'` |

Root cause: **there is no `spellcaster_core/` package in this repo**, and no
`pyproject.toml`, `setup.py`, or `requirements.txt` at the root. The test suite
imports a package that is not present, so it can never run here. Separately,
`~/.claude/CLAUDE.md` documents the smoke suite as
`python tests/night_maintenance.py --dry-mode` -- **that flag does not exist**;
the script accepts only `--server/--caps/--report/--quiet`. Both facts are
stale/broken and need fixing before this repo has a working acceptance bar.

Consequently the repo's own `pre-push` hook (HERMES-EDITS-CODE Stage 5)
**correctly blocks this branch from being pushed**, and it was left blocked.
The hook was NOT bypassed and no fake evidence line was added to unblock it.
Pushing was authorized by the user; it is the repo's own guard, plus the
absence of any runnable test, that stops it.

**To unblock:** restore/point at the `spellcaster_core` package (or fix the
tests' imports), get one real test passing, record it here as a `PASS:` line
with its actual output, then push.

## Acceptance / next steps

- Do not merge to `main` without a real review pass over the source changes.
- Decide whether the 135 asset images belong in-repo or should move to
  release assets / LFS.
- Delete the excluded junk files from the working tree.

## Rollback

```
git checkout main            # main is untouched at ccef78a2
git branch -D hermes/spellcaster/20260718-wip-consolidation
git push origin --delete hermes/spellcaster/20260718-wip-consolidation
```
