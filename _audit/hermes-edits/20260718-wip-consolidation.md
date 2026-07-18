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

## NOT verified

- The 207 files were **not** reviewed individually, and no test suite was run
  against this branch. This branch records existing working-tree state; it does
  not assert that state is correct.

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
