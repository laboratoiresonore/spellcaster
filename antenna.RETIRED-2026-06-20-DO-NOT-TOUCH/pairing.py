"""Simple pair-code handshake so humans don't have to shuttle a 43-char
bearer token between machines.

How it works
────────────
On the antenna box (running `python -m antenna`), the tray (or a CLI
command) calls `start_pairing()`. That:

  1. Generates a random 6-digit code the user sees on screen.
  2. Generates (or reads) the real bearer token.
  3. Writes the (code → token) mapping into memory with a 5-minute TTL.

On the Guild box (running tavern/server.py), the "Pair new antenna"
dialog prompts the user for the antenna's IP and the 6-digit code.
The Guild then calls:

    POST https://<antenna_ip>:7334/pair/claim   { "code": "123456" }

The antenna verifies the code, marks it consumed, and responds with:

    { "token": "<the real 43-char bearer>" }

The Guild stores that token in its antenna registry the same way it
would a token entered by hand. Subsequent calls use the bearer token
as they always have — the HTTPS + bearer-auth machinery underneath is
unchanged. The pair code is ONLY the handoff vehicle; it's never used
for anything except the one-shot token exchange.

Security notes
──────────────
  - Pair code expires after 5 min OR one successful claim, whichever
    comes first. No replay.
  - Pair code is short (6 digits) on purpose — the user has to type it
    by hand. That's fine because it lives for 5 min on the LAN and is
    consumed in one try. After that, the real token takes over.
  - The /pair/claim endpoint is the ONLY antenna route that doesn't
    require bearer auth (it's how you get the bearer). Rate-limited
    in agent._build_routes(). Wrong codes count against the limit.
  - The returned token IS the same bearer that ~/.spellcaster/antenna_token
    holds on this box. We never generate a separate "pair token";
    pairing just hands out the existing one.

The module is pure stdlib + 80 lines. No external deps.
"""

from __future__ import annotations

import secrets
import threading
import time
from pathlib import Path
from typing import Any, Optional

from . import config

# ── Lifecycle ──────────────────────────────────────────────────────────

_PAIR_LOCK = threading.Lock()
# Single-entry table: we only allow ONE outstanding pair code at a time
# because there's only one antenna per machine and one token per antenna.
# Starting a new pairing invalidates any prior un-claimed code.
_PAIR_STATE: dict[str, Any] = {
    "code": None,       # "123456"
    "expires_at": 0.0,  # unix epoch
    "consumed": False,
}

DEFAULT_TTL_SECONDS = 300  # 5 minutes


def _generate_code() -> str:
    """6-digit zero-padded numeric code. Numeric so users can type it
    on any keyboard layout / phone. secrets for uniformity.
    """
    return f"{secrets.randbelow(10**6):06d}"


def start_pairing(ttl_seconds: int = DEFAULT_TTL_SECONDS) -> dict:
    """Generate a new pair code. Returns the code + metadata the tray
    should display. Called from the tray's "Pair with Guild" menu
    item (and from POST /pair/start for programmatic pairing).
    """
    with _PAIR_LOCK:
        code = _generate_code()
        _PAIR_STATE["code"] = code
        _PAIR_STATE["expires_at"] = time.time() + max(30, int(ttl_seconds))
        _PAIR_STATE["consumed"] = False
    return {
        "code": code,
        "expires_in": int(ttl_seconds),
        "instructions": (
            "Open the Wizard Guild on your other machine, go to "
            "Antennas → Pair new, and type this 6-digit code."
        ),
    }


def get_pairing_state() -> dict:
    """Public-safe snapshot — does NOT reveal the code. Tells the tray
    whether a pairing is currently active so it can hide its menu item.
    """
    with _PAIR_LOCK:
        now = time.time()
        expires_at = _PAIR_STATE["expires_at"]
        active = (_PAIR_STATE["code"] is not None
                  and not _PAIR_STATE["consumed"]
                  and expires_at > now)
        return {
            "active": active,
            "consumed": bool(_PAIR_STATE["consumed"]),
            "expires_in": max(0, int(expires_at - now)) if active else 0,
        }


def cancel_pairing() -> bool:
    """Invalidate any outstanding code (user clicks "Cancel pairing")."""
    with _PAIR_LOCK:
        had_one = _PAIR_STATE["code"] is not None
        _PAIR_STATE["code"] = None
        _PAIR_STATE["expires_at"] = 0.0
        _PAIR_STATE["consumed"] = False
        return had_one


def _load_token(cfg: dict) -> Optional[str]:
    """Read the antenna's current bearer token from disk.

    Same path the agent's auth layer uses. We re-read each claim so that
    rotating the token file (`~/.spellcaster/antenna_token`) invalidates
    in-flight pair codes the same way.
    """
    path = Path(cfg.get("token_path") or "").expanduser()
    if not path.is_file():
        # Try the bootstrap default when config hasn't been loaded
        path = (Path.home() / ".spellcaster" / "antenna_token")
    if not path.is_file():
        return None
    try:
        return path.read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


# ── Claim endpoint ─────────────────────────────────────────────────────

def claim(code: str, cfg: Optional[dict] = None) -> tuple[int, dict]:
    """Validate a pair code and return the bearer token on success.

    Returns (status_code, body):
      200 → {"token": "..."}            happy path, code consumed
      400 → {"error": "missing code"}   empty / non-string input
      404 → {"error": "no active pairing"} no start_pairing() call recently
      410 → {"error": "pair code expired"} TTL elapsed
      403 → {"error": "wrong code"}     code mismatch (counts against rate limit)
      409 → {"error": "already consumed"} someone claimed it first
      500 → {"error": "no token on this antenna"} token file missing
    """
    if cfg is None:
        try: cfg = config.load_config()
        except Exception: cfg = {}
    if not isinstance(code, str) or not code:
        return 400, {"error": "missing code"}
    # Normalise: tolerate surrounding whitespace / dashes.
    submitted = code.strip().replace("-", "").replace(" ", "")

    with _PAIR_LOCK:
        stored = _PAIR_STATE["code"]
        expires_at = _PAIR_STATE["expires_at"]
        consumed = _PAIR_STATE["consumed"]
        now = time.time()

        if stored is None:
            return 404, {"error": "no active pairing — run start_pairing on "
                          "the antenna first"}
        if consumed:
            return 409, {"error": "pair code already consumed"}
        if now > expires_at:
            # Clear so a subsequent start_pairing has a clean slate
            _PAIR_STATE["code"] = None
            return 410, {"error": "pair code expired"}
        # Constant-time compare even though the code is short — habit.
        if not secrets.compare_digest(submitted, stored):
            return 403, {"error": "wrong code"}

        # Good — mark consumed BEFORE reading the token so a crash between
        # the two can't leave a live code behind.
        _PAIR_STATE["consumed"] = True

    token = _load_token(cfg or {})
    if not token:
        return 500, {"error": "this antenna has no token on disk yet — "
                      "re-run the antenna_for_<ip>.bat bootstrap once"}
    return 200, {
        "token": token,
        "hint": ("Store this as the antenna token on the Guild box. "
                 "The pair code is now invalid — this response is the "
                 "only place the real token appears."),
    }
