"""Trivial marker for /self-update end-to-end testing.

Changes to this file don't affect agent behaviour — they exist only to
prove that pushing to main + curling /self-update successfully reloads
the remote agent. Bump DEPLOY_STAMP to force a reload.
"""

DEPLOY_STAMP = "round1-2026-04-18"
