"""Authentication and rate-limiting middleware for the antenna agent.

Threat model
------------
Assume the LAN is hostile — anyone on the same network can reach port
7334. Everything below guards against LAN-local adversaries without
relying on network isolation.

Defenses
--------
1. **TLS with pinned self-signed cert** (see config.py) — prevents
   eavesdropping / MITM even on open Wi-Fi.

2. **Bearer token** in the `Authorization: Bearer <tok>` header, compared
   via `hmac.compare_digest` to prevent timing-based token recovery.

3. **Sliding-window rate limiter** per source IP — 30 req/min default,
   configurable via antenna_config.json. Returns HTTP 429 with a
   Retry-After header on exceed. Bucket state is in-memory (lost on
   restart); that's deliberate, a reset = temporary amnesty, not a
   vulnerability.

4. **Audit log** — every authenticated request is logged (timestamp,
   source IP, method, path, result). Written by agent.py, which imports
   from here for the format constants.

What this module does NOT do
----------------------------
- Per-user accounts (single bearer token shared across all clients —
  that's enough for home-lab use; multi-user auth is out of scope).
- Request signing or replay protection. TLS + token is sufficient for
  the threat model; nonces would add complexity without much gain
  inside an encrypted tunnel.
- IP allowlisting. Easy to add (`config["allowed_ips"]`) if needed —
  for now, any IP that presents a valid token is accepted.
"""
from __future__ import annotations

import collections
import hmac
import os
import threading
import time
from pathlib import Path
from typing import Any


# ─── Token validation ────────────────────────────────────────────────────

def load_token(token_path: str) -> str:
    """Read the bearer token from disk. Raises FileNotFoundError if absent.

    The caller is responsible for caching this — we re-read on every
    call so `antenna rotate-token` takes effect without restarting the
    agent (the agent's request handler calls this on each request).
    """
    path = Path(os.path.expanduser(token_path))
    return path.read_text(encoding="utf-8").strip()


def extract_bearer(authorization_header: str | None) -> str | None:
    """Parse 'Bearer <token>' from an Authorization header. None if malformed."""
    if not authorization_header:
        return None
    parts = authorization_header.split(None, 1)
    if len(parts) != 2:
        return None
    scheme, value = parts
    if scheme.lower() != "bearer":
        return None
    return value.strip() or None


def verify_token(presented: str | None, expected: str) -> bool:
    """Constant-time comparison of the presented bearer against the stored one.

    Uses hmac.compare_digest to avoid leaking token contents via response-
    time differences. Treats a None or empty presented token as an
    unconditional False without reaching the compare (still no timing
    side channel — we're not branching on any token content).
    """
    if not presented or not expected:
        return False
    # hmac.compare_digest operates on bytes and is timing-safe
    return hmac.compare_digest(
        presented.encode("utf-8"), expected.encode("utf-8"))


# ─── Sliding-window rate limiter ─────────────────────────────────────────
#
# Per-IP deque of request timestamps within the last 60 seconds. On each
# request: evict old entries, check count against limit, optionally
# record the new one. The eviction is O(n) amortised O(1) via deque
# popleft, so 30-req/min buckets stay sub-microsecond to check.
#
# Why not a token bucket? Token buckets smooth bursts but let sustained
# attackers saturate at the refill rate. A sliding window is stricter:
# 30 req/min means no more than 30 in any rolling 60 s window, period.

class RateLimiter:
    """Thread-safe sliding-window rate limiter, keyed on arbitrary strings.

    Usage:
        rl = RateLimiter(limit_per_minute=30)
        allowed, retry_after = rl.check_and_record("192.168.1.50")
        if not allowed:
            return 429, {"Retry-After": str(int(retry_after))}

    Memory bound: one deque per distinct key ever seen. For LAN use with
    handful of clients that's fine; if scaling to many keys, add a
    periodic sweep of empty deques (not implemented — YAGNI for now).
    """

    WINDOW_SECONDS = 60

    def __init__(self, limit_per_minute: int = 30):
        self.limit = max(1, int(limit_per_minute))
        self._buckets: dict[str, collections.deque[float]] = {}
        self._lock = threading.Lock()

    def _prune(self, bucket: collections.deque[float], now: float) -> None:
        """Drop timestamps older than the 60-second window. Mutates bucket."""
        cutoff = now - self.WINDOW_SECONDS
        while bucket and bucket[0] < cutoff:
            bucket.popleft()

    def check_and_record(self, key: str) -> tuple[bool, float]:
        """Test if `key` may proceed; on success also record the hit.

        Returns (allowed, retry_after_seconds). When allowed=True,
        retry_after is 0.0. When allowed=False, retry_after is the
        seconds until the bucket's oldest entry ages out.
        """
        now = time.monotonic()
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                bucket = collections.deque()
                self._buckets[key] = bucket
            self._prune(bucket, now)
            if len(bucket) >= self.limit:
                retry_after = max(0.0, self.WINDOW_SECONDS - (now - bucket[0]))
                return False, retry_after
            bucket.append(now)
            return True, 0.0

    def peek(self, key: str) -> int:
        """Return the current request count in the window for a key. O(n) prune first."""
        now = time.monotonic()
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                return 0
            self._prune(bucket, now)
            return len(bucket)


# ─── Request authentication helper ───────────────────────────────────────

def authenticate_request(headers: dict[str, str],
                         token_path: str) -> tuple[bool, str | None]:
    """Validate an incoming request's Authorization header against the stored token.

    Returns (ok, error_message). error_message is None on success and a
    short human-readable string on failure that the agent can echo back
    in the JSON error body (the client can display it).

    Called by agent.py for every request except GET / (which is the
    unauthenticated liveness check).
    """
    bearer = extract_bearer(headers.get("Authorization") or headers.get("authorization"))
    if bearer is None:
        return False, "missing Authorization: Bearer <token> header"
    try:
        expected = load_token(token_path)
    except FileNotFoundError:
        return False, "agent has no token provisioned — run antenna bootstrap"
    except OSError as e:
        return False, f"token unreadable: {e}"
    if not verify_token(bearer, expected):
        return False, "invalid token"
    return True, None


if __name__ == "__main__":
    # python -m antenna.auth → quick sanity check
    import sys
    rl = RateLimiter(limit_per_minute=3)
    for i in range(5):
        ok, retry = rl.check_and_record("test-ip")
        print(f"req {i+1}: allowed={ok} retry_after={retry:.1f}s")
    # Constant-time compare sanity
    print(f"\nverify('x', 'x') = {verify_token('x', 'x')}")
    print(f"verify('x', 'y') = {verify_token('x', 'y')}")
    print(f"verify(None, 'x') = {verify_token(None, 'x')}")
    print(f"extract_bearer('Bearer abc') = {extract_bearer('Bearer abc')!r}")
    print(f"extract_bearer('Basic abc')  = {extract_bearer('Basic abc')!r}")
    print(f"extract_bearer(None)         = {extract_bearer(None)!r}")
