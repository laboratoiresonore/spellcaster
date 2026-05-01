# `.githooks/` — credential-leak pre-commit guard

Mirrors the regex in `.claude/settings.json`'s `PreToolUse`/`Bash(git commit *)`
hook so that **plain `git commit` from any terminal is also blocked**, not just
commits initiated through Claude Code.

## Activate

After clone (one-time, per-clone, not committed because `core.hookspath` is a
local config):

```sh
git config --local core.hookspath .githooks
```

To verify:

```sh
git config --get core.hookspath          # → .githooks
ls -la .githooks/pre-commit              # executable
```

## What it blocks

Files matching this regex in any **staged** add/copy/modify/rename:

```
192\.168\.86\.(31|23|77|219)|redacted|redacted|@gmail\.com|ghp_[A-Za-z0-9]
```

These are the same identity / Theo-network markers Spellcaster's Claude hook
catches. See internal roadmap §F.6.2 Wk 1 Thu / §10.7 for the lattice rationale.

## Override (sparingly)

```sh
SKIP_LEAK_CHECK=1 git commit ...
```

Audit override commits afterwards. Real intent: sanitize the file, don't
override.

## Source

Canonical script vendored from `internal-core/hooks/pre-commit` (internal roadmap §C
once internal-core ships at week 5–19; until then, vendored verbatim per repo).
