# `.githooks/` — credential-leak pre-commit guard

A defensive pre-commit hook that blocks staged commits whose diff matches a
configured leak-pattern regex (internal IPs, identity strings, auth tokens).

The leak pattern is loaded from an external config file so the public source
in this repo contains no embedded PII.

## Activate

After clone (one-time, per-clone, not committed because `core.hookspath` is a
local config):

```sh
git config --local core.hookspath .githooks
```

Then provide a leak pattern via one of (first match wins):

1. `SPELLCASTER_LEAK_PATTERN` — env var with the literal regex
2. `SPELLCASTER_LEAK_PATTERN_FILE` — env var pointing at a file
3. `$HOME/.config/spellcaster/leak-pattern` — default file location

If none of these resolves, the hook is a silent no-op.

To verify activation:

```sh
git config --get core.hookspath          # → .githooks
ls -la .githooks/pre-commit              # executable
```

## What it blocks

Any **staged** add/copy/modify/rename whose contents match your configured
regex. A reasonable starter pattern, kept in your local
`~/.config/spellcaster/leak-pattern`, would cover the internal IPs, identity
strings, and token prefixes you want to keep out of public commits.

## Override (sparingly)

```sh
SKIP_LEAK_CHECK=1 git commit ...
```

Audit override commits afterwards. Real intent: sanitize the file, don't
override.
