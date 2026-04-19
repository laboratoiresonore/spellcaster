# Security Policy

Spellcaster runs entirely on the user's own machine and talks only to a
ComfyUI server the user controls — typically `localhost`. No telemetry,
no cloud API calls, no credential storage. That said, there are still
realistic attack surfaces worth flagging.

## In scope

- The GIMP plugin (`plugins/gimp/comfyui-connector/`) — arbitrary file read/
  write, path traversal, deserialization issues in custom workflow imports,
  code execution via `user_presets.json` or `session_state.json` parsing.
- The Wizard Guild server (`tavern/`) — any RCE, SSRF, or unauthenticated
  API misuse. The server binds to `localhost` by default but is sometimes
  exposed on a LAN.
- The Windows/macOS/Linux installer (`installer/`) — code execution via
  the auto-updater, tampered `manifest.json`, or the bootstrap fetch from
  `raw.githubusercontent.com`.
- The NSFW build path — leakage of NSFW content, tokens, or private-repo
  URLs into the public `spellcaster` repo.
- The shared library (`comfyui-spellcaster/spellcaster_core/`) and its
  three synced copies.

## Out of scope

- Vulnerabilities in ComfyUI itself — report at
  [comfyanonymous/ComfyUI](https://github.com/comfyanonymous/ComfyUI).
- Vulnerabilities in third-party ComfyUI custom node packs we depend on —
  report them upstream at their respective repos (see
  [DEPENDENCIES.md](../DEPENDENCIES.md)).
- Vulnerabilities in upstream model weights or training data.
- Prompt-injection of local LLMs that stays within the local machine.

## Reporting a vulnerability

Please **do not** open a public issue for security problems. Instead:

1. Open a private advisory via
   [GitHub Security Advisories](https://github.com/laboratoiresonore/spellcaster/security/advisories/new).
2. Include repro steps, impacted version/commit, and expected vs. observed
   behavior.

You can expect an acknowledgement within a few days. Critical issues will be
patched and released as soon as possible; fixes ship via the normal auto-update
flow that every Spellcaster installation already runs on launch.

## Supported versions

Spellcaster ships as a rolling release. Only the latest `main` + the latest
tagged release on the
[releases page](https://github.com/laboratoiresonore/spellcaster/releases)
receive security fixes. The auto-updater in every GIMP plugin install and
every Wizard Guild launch pulls from `main` on start, so users are rarely
more than one restart behind.
