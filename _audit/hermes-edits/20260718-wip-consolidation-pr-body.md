## Consolidate outstanding working-tree changes (2026-07-18)

**This is a rescue commit, not a feature PR.** 208 files had accumulated
uncommitted in the working tree since `ccef78a2`. Per the user's 2026-07-18
instruction, that work is now committed to a branch where it is durable and
reviewable instead of sitting one `git reset` from loss.

### What landed

207 files (`git show --stat deff83fa`):

- ~61 modified Python source files
- ~135 showcase / asset images (`assets/*.png`, `.gif`, `.webp`)
- ~12 docs and JSON config files
- plus this plan doc + PR body (`e7783388`)

### What was deliberately left out

- **Junk**: build logs, `.bak-*` files, `_archived/` and temp dirs, playwright
  artifacts, and `_PUSH_*.ps1` / `_FIX_*.ps1` helpers. Committing build logs
  pollutes history irreversibly, and the `_PUSH_*`/`_FIX_*` scripts are
  scheduled for deletion under the NO-SUDO-POPUP rule.
- **Personal data**: the repo's pre-commit personal-data guard did not fire
  here. Where it fired in sibling repos, offending files were excluded --
  `SKIP_LEAK_CHECK` was never used anywhere in this operation.

### Verification

- [x] Secret scan across the full staged diff (GitHub PAT, `hf_`, `sk-`, AWS,
      private-key headers, JWT, hardcoded `password=`/`api_key=`): **no hits**
- [x] Pre-commit personal-data guard: passed
- [x] `main` untouched at `ccef78a2`
- [ ] **Files NOT reviewed individually**
- [ ] **No test suite run against this branch**

### Reviewer notes -- please do not rubber-stamp

This branch asserts only that the working-tree state is *preserved*, not that
it is *correct*. Before merging:

1. Review the ~61 Python changes on their own merits.
2. Decide whether 135 asset images belong in-repo, in LFS, or as release
   assets. This is a **public** repository.
3. Confirm nothing in the assets is unintended for public distribution.

### Rollback

```
git checkout main
git push origin --delete hermes/spellcaster/20260718-wip-consolidation
```

🤖 Generated with [Claude Code](https://claude.com/claude-code)
