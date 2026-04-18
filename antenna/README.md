# Spellcaster Antenna

A lightweight HTTPS agent that runs on the machine hosting ComfyUI.
It accepts authenticated commands from Spellcaster clients (GIMP plugin,
Wizard Guild, installer) to install custom nodes, download models,
self-update, and report status — so everyday users don't have to SSH
into the ComfyUI box to maintain it.

## Why this exists

Before: Spellcaster's "antenna" was just a probe-only client installer.
If a client saw that a required node was missing on the remote ComfyUI,
the only option was "log into that machine and install it manually."

After: the antenna agent runs alongside ComfyUI. Clients POST to
`/install-node` or `/install-model` and the agent handles it. Users who
have one powerful AI box on their network (e.g. at `192.168.x.x`) and
several thin clients (laptop with GIMP) never need to touch the server.

## Architecture

The antenna is designed for **distributed LAN setups** — one agent per
server machine, each advertising the services it hosts. A client talks
to whichever antennas it needs:

```
┌──────────────────────────┐   ┌──────────────────────────┐   ┌──────────────────────────┐
│  Machine A — LLM server  │   │  Machine B — ComfyUI     │   │  Machine C — Resolve     │
│                          │   │                          │   │                          │
│  • KoboldCpp/Ollama      │   │  • ComfyUI :8188         │   │  • DaVinci Resolve       │
│  • spellcaster_antenna   │   │  • spellcaster_antenna   │   │  • spellcaster_antenna   │
│    agent :7334           │   │    agent :7334           │   │    agent :7334           │
│    services: [llm]       │   │    services: [comfyui]   │   │    services: [resolve]   │
└──────────▲───────────────┘   └──────────▲───────────────┘   └──────────▲───────────────┘
           │                              │                              │
           └──────────────────────────────┼──────────────────────────────┘
                                          │  HTTPS + bearer token
                                ┌─────────┴──────────┐
                                │  Client machine    │
                                │  • GIMP plugin     │
                                │  • Wizard Guild    │
                                │  • install_remote  │
                                └────────────────────┘
```

Each antenna:

- Runs ONE Python process with zero non-stdlib dependencies
- Runs as a service / startup task / bat file — user chooses
- Does NOT patch the service it manages (ComfyUI stays pristine, Kobold
  stays pristine, etc.)
- Declares its `services` array in `antenna_config.json`. A single box
  can host multiple services (e.g. LLM + ComfyUI on one beefy machine)

The client reads each antenna's `/status`, composes a unified picture
of what's available on the LAN, and routes requests to the right
machine. Think of it as a DHT of AI services, keyed by capability.

## Service types (Phase 1 = comfyui; others follow)

| Service    | What the agent manages                           | Phase  |
|------------|--------------------------------------------------|--------|
| `comfyui`  | Install/update custom nodes + download models    | 1      |
| `llm`      | KoboldCpp/Ollama/llama.cpp lifecycle + models    | 2      |
| `resolve`  | DaVinci Resolve scripting bridge (clips, LUTs)   | 4      |
| `self`     | Agent self-update, token rotation, audit log     | 1      |

Services are defined in `antenna/services/<name>.py` — one file each,
each exposing a tiny interface (`name`, `status()`, `install()`, etc.).
Adding a new service means dropping in a new file, not touching the
core agent.

## Endpoints (Phase 1)

All endpoints require `Authorization: Bearer <token>` except `/`.

| Method | Path             | Purpose                                         |
|--------|------------------|-------------------------------------------------|
| GET    | `/`              | Liveness check (unauthenticated, returns `ok`)  |
| GET    | `/status`        | Version, uptime, ComfyUI reachability, VRAM     |
| POST   | `/install-node`  | Git-clone a custom node pack into ComfyUI       |
| POST   | `/install-model` | Download a model file into ComfyUI's models/    |
| POST   | `/self-update`   | Fetch latest agent code from GitHub and restart |

Planned for later phases: `/uninstall-node`, `/heartbeat`, `/logs`,
`/resolve/*` (DaVinci bridge).

## Security model

LAN-only, but treated as hostile. Assume someone on the same Wi-Fi
could reach port 7334.

- **TLS with self-signed cert.** Generated on first launch into
  `~/.spellcaster/antenna.key` + `~/.spellcaster/antenna.crt`. All
  traffic is encrypted; clients pin the cert on first connect.
- **Bearer token.** 32 random bytes, base64-encoded, stored in
  `~/.spellcaster/antenna_token`. Generated on first launch. Rotatable
  via `antenna rotate-token`.
- **Constant-time comparison** of the bearer token via `hmac.compare_digest`.
- **Rate limiting** per client IP: 30 requests / minute, sliding window.
- **Audit log** of every authenticated request to `~/.spellcaster/antenna.log`
  (timestamp, client IP, method, path, result code).
- **Input validation.** Node/model names are validated against a
  regex allowlist. Path traversal attempts (`..`, absolute paths) are
  rejected at the middleware layer.
- **No arbitrary code execution.** `/install-node` only accepts entries
  from the Spellcaster `manifest.json` — you can't trick the agent into
  cloning an arbitrary malicious repo.

## Configuration

First-launch auto-generates everything. User never edits config by hand
unless they want to.

File: `~/.spellcaster/antenna_config.json`

```json
{
  "port": 7334,
  "bind": "0.0.0.0",
  "comfyui_root": "auto",
  "comfyui_url": "http://127.0.0.1:8188",
  "token_path": "~/.spellcaster/antenna_token",
  "tls_cert_path": "~/.spellcaster/antenna.crt",
  "tls_key_path": "~/.spellcaster/antenna.key",
  "log_path": "~/.spellcaster/antenna.log",
  "rate_limit_rpm": 30,
  "manifest_url": "https://raw.githubusercontent.com/laboratoiresonore/spellcaster/main/installer/manifest.json"
}
```

## Launching

Windows (user double-clicks):
```
antenna\start_antenna.bat
```

Linux/macOS:
```
bash antenna/start_antenna.sh
```

As a Windows service (persistent, survives logout) — Phase 1.5 via nssm.
As a systemd unit — Phase 1.5 via `antenna.service`.

## First-use flow for the client

1. Client runs `install_remote.py http://192.168.x.x:8188`
2. Client probes `:7334` — if the antenna is running, client sees the TLS
   cert and prompts the user: "Accept cert fingerprint `ab:cd:...`?"
3. Client runs an unauthenticated `GET /` to confirm liveness
4. Client asks the user for the one-time bootstrap token (the user
   fetches it from the server via `antenna show-token` or reads it
   from `~/.spellcaster/antenna_token` on the server once)
5. Client stores the cert fingerprint + token in `spellcaster_settings.json`
6. All subsequent calls use the stored pair.

## Status codes

- `200` — success
- `202` — accepted, long-running (install-model etc. return this with a job ID)
- `401` — missing/invalid token
- `403` — request not signed correctly
- `404` — unknown endpoint
- `429` — rate-limited
- `500` — agent error (traceback goes to audit log, not to client)
- `503` — ComfyUI unreachable

## File layout

```
antenna/
├── README.md               # this file
├── __init__.py             # version metadata
├── config.py               # load/save antenna_config.json + token/cert bootstrap
├── auth.py                 # token compare + TLS cert generation
├── rate_limit.py           # sliding-window per-IP limiter
├── agent.py                # HTTPS server + routing
├── endpoints/
│   ├── __init__.py
│   ├── status.py           # GET /, GET /status
│   ├── install_node.py     # POST /install-node
│   ├── install_model.py    # POST /install-model
│   └── self_update.py      # POST /self-update
├── cli.py                  # argparse entry: start / status / gen-token / rotate-token
├── start_antenna.bat       # Windows launcher
└── start_antenna.sh        # Unix launcher
```
