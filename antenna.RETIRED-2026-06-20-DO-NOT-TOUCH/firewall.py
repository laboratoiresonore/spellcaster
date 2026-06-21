"""Windows Firewall rule management for the Spellcaster Antenna.

The antenna binds 0.0.0.0:7334 so Wizard Guild clients anywhere on
the LAN can reach it. Windows' default inbound policy blocks that
port until one of two things happens:

  1. The user clicks "Allow" on the UAC-ish "Windows Security Alert"
     popup Windows shows the FIRST time a program listens on a port
     with LAN reach. Users frequently miss this popup (it can be
     hidden behind the antenna splash), click Cancel by reflex, or
     never see it at all when the antenna starts from a login
     shortcut without being the foreground app.
  2. An explicit firewall rule whitelists TCP 7334 for the private
     + domain profiles.

Case 1 is unreliable. We handle case 2 on first launch.

netsh requires Administrator. We attempt:

  1. Run netsh directly — works if the antenna is already elevated
     (which happens for some Start Menu pinned-as-admin setups).
  2. Re-launch netsh via ShellExecuteW with the "runas" verb —
     surfaces a single UAC prompt. The elevated netsh adds the rule
     and exits immediately; we poll for the rule to appear as
     confirmation (ShellExecuteW doesn't block).
  3. Give up and report an error the caller can surface.

Idempotent: ensure_inbound_rule() checks for an existing rule by
name before doing anything. Repeat calls are cheap.

Public API
──────────
    APP_FIREWALL_NAME
        The rule name we use (literal string the user will see
        in Windows Defender Firewall → Advanced → Inbound Rules).

    rule_exists(name=...) → bool
    ensure_inbound_rule(port=7334, name=...) → dict
        {"existed": bool, "created": bool, "elevated": bool,
         "skipped": str | None, "error": str | None, "cmd_hint": str}
    remove_rule(name=...) → dict
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from typing import Optional


# ── Constants ─────────────────────────────────────────────────────

# The rule name the user sees in Windows Defender Firewall. Keep
# stable across versions — we look it up by name for idempotency and
# for removal. Changing this orphan-leaves old rules.
APP_FIREWALL_NAME = "Spellcaster Antenna"
DEFAULT_PORT = 7334

# CREATE_NO_WINDOW — suppress the flashing black netsh console that
# would otherwise appear every time we call it.
_CREATE_NO_WINDOW = 0x08000000


def _is_windows() -> bool:
    return os.name == "nt"


# ── netsh primitives ──────────────────────────────────────────────

def _run_netsh(args: list[str], timeout: float = 10.0) -> tuple[int, str]:
    """Run a netsh command, capture stdout+stderr. Returns
    (exit_code, combined_output). Non-fatal — callers are expected
    to interpret the exit code.
    """
    try:
        r = subprocess.run(
            ["netsh"] + args,
            capture_output=True, text=True, timeout=timeout,
            creationflags=_CREATE_NO_WINDOW if _is_windows() else 0,
        )
        out = ((r.stdout or "") + (r.stderr or "")).strip()
        return r.returncode, out
    except FileNotFoundError:
        return 127, "netsh not found on PATH"
    except subprocess.TimeoutExpired:
        return 124, "netsh timed out"
    except Exception as e:  # noqa: BLE001
        return 1, f"{type(e).__name__}: {e}"


def rule_exists(name: str = APP_FIREWALL_NAME) -> bool:
    """True if a firewall rule with the given name exists. `show rule`
    is a read-only query that works unprivileged."""
    if not _is_windows():
        return False
    code, out = _run_netsh(
        ["advfirewall", "firewall", "show", "rule", f"name={name}"])
    # netsh prints "No rules match the specified criteria" when absent.
    if code != 0:
        return False
    # A hit looks like a multi-line block with "Rule Name:" etc.
    return "rule name" in out.lower() and "no rules match" not in out.lower()


def _create_rule_direct(name: str, port: int) -> tuple[bool, str]:
    """Attempt to create the rule in the current security context.
    Works if the caller is already elevated; fails with an access-
    denied message otherwise. Returns (success, error_or_output)."""
    code, out = _run_netsh([
        "advfirewall", "firewall", "add", "rule",
        f"name={name}",
        "dir=in",
        "action=allow",
        "protocol=TCP",
        f"localport={port}",
        "profile=private,domain",
        "description=Allow Spellcaster Antenna LAN inbound (HTTPS).",
    ])
    if code == 0 and ("ok" in out.lower() or not out):
        return True, out or "ok"
    return False, out or f"netsh exit {code}"


def _create_rule_elevated(name: str, port: int) -> tuple[bool, str]:
    """Launch netsh via ShellExecuteW with the "runas" verb. This
    produces the UAC prompt. ShellExecuteW doesn't block — the
    elevated netsh runs asynchronously — so we poll for up to ~6s
    for the rule to appear, which is the honest way to detect
    whether the UAC prompt was accepted.

    Returns (success, error_or_info).
    """
    if not _is_windows():
        return False, "not-windows"
    try:
        import ctypes
    except Exception as e:  # noqa: BLE001
        return False, f"ctypes unavailable: {e}"

    # All-positional netsh arguments on a single command line.
    # Quotes around name= because we allow spaces in APP_FIREWALL_NAME.
    params = (
        'advfirewall firewall add rule '
        f'name="{name}" '
        'dir=in '
        'action=allow '
        'protocol=TCP '
        f'localport={port} '
        'profile=private,domain '
        'description="Allow Spellcaster Antenna LAN inbound (HTTPS)."'
    )

    SW_HIDE = 0
    try:
        # HINSTANCE ShellExecuteW(HWND, lpOperation, lpFile, lpParameters,
        #                         lpDirectory, nShowCmd). Return value >32
        # means success starting the process; <=32 is a Win32 error code.
        h = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", "netsh.exe", params, None, SW_HIDE)
    except Exception as e:  # noqa: BLE001
        return False, f"ShellExecuteW failed: {type(e).__name__}: {e}"

    if int(h) <= 32:
        # Typical codes: 5 = access denied (user clicked No on UAC),
        # 2 = file not found, 3 = path not found, 11 = bad format.
        mapping = {
            0: "out of memory",
            2: "netsh.exe not found",
            3: "path not found",
            5: "UAC declined or access denied",
            8: "out of memory",
            11: "bad executable format",
            26: "sharing violation",
            27: "bad association",
            28: "DDE timeout",
            29: "DDE transaction failed",
            30: "DDE busy",
            31: "no association",
            32: "DLL not found",
        }
        return False, f"ShellExecuteW code {int(h)} ({mapping.get(int(h), 'unknown')})"

    # Elevated netsh runs asynchronously. Poll for up to ~6s.
    deadline = time.monotonic() + 6.0
    while time.monotonic() < deadline:
        if rule_exists(name):
            return True, "created via elevated netsh"
        time.sleep(0.3)
    return False, "timed out waiting for rule to appear after elevation (user likely declined UAC)"


# ── Public API ────────────────────────────────────────────────────

def ensure_inbound_rule(port: int = DEFAULT_PORT,
                         name: str = APP_FIREWALL_NAME) -> dict:
    """Create the inbound TCP rule on Windows. Idempotent. Returns a
    result dict the caller can show in a dialog / log.

    Result keys:
      existed:  True if the rule already existed before the call.
      created:  True if we successfully added the rule this call.
      elevated: True if we needed (and got) UAC elevation to create.
      skipped:  Non-None reason string if we bailed (not-windows, etc.).
      error:    Non-None error string if creation failed.
      cmd_hint: Manual netsh command string the user can run themself
                if automation didn't work, for paste-into-admin-cmd.
    """
    result = {"existed": False, "created": False, "elevated": False,
              "skipped": None, "error": None,
              "cmd_hint": (
                  f'netsh advfirewall firewall add rule name="{name}" '
                  f'dir=in action=allow protocol=TCP localport={port} '
                  f'profile=private,domain'
              )}
    if not _is_windows():
        result["skipped"] = "not-windows — Windows Firewall is only present on Windows"
        return result

    if rule_exists(name):
        result["existed"] = True
        return result

    # Try non-elevated first — if the antenna is already running as
    # admin (pinned-as-admin shortcut, admin terminal install), this
    # succeeds without a UAC prompt.
    ok, out = _create_rule_direct(name, port)
    if ok:
        # Double-check — some netsh builds return 0 even when the rule
        # wasn't added (e.g. when the firewall service is stopped).
        if rule_exists(name):
            result["created"] = True
            return result
        # Silent success without rule → treat as failure, try elevated.

    # Elevated fallback — surfaces one UAC prompt.
    ok, info = _create_rule_elevated(name, port)
    if ok and rule_exists(name):
        result["created"] = True
        result["elevated"] = True
        return result

    result["error"] = info or out or "unknown failure"
    return result


def remove_rule(name: str = APP_FIREWALL_NAME) -> dict:
    """Delete the antenna's firewall rule. Used by uninstall flows."""
    result = {"removed": False, "skipped": None, "error": None}
    if not _is_windows():
        result["skipped"] = "not-windows"
        return result
    if not rule_exists(name):
        result["skipped"] = "not-present"
        return result
    # Try direct, fall back to elevated.
    code, out = _run_netsh(
        ["advfirewall", "firewall", "delete", "rule", f"name={name}"])
    if code == 0 and not rule_exists(name):
        result["removed"] = True
        return result
    # Elevate.
    try:
        import ctypes
        params = f'advfirewall firewall delete rule name="{name}"'
        h = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", "netsh.exe", params, None, 0)
        if int(h) > 32:
            deadline = time.monotonic() + 6.0
            while time.monotonic() < deadline:
                if not rule_exists(name):
                    result["removed"] = True
                    return result
                time.sleep(0.3)
            result["error"] = "elevation started but rule still present"
            return result
        result["error"] = f"ShellExecuteW code {int(h)}"
    except Exception as e:  # noqa: BLE001
        result["error"] = f"{type(e).__name__}: {e}"
    return result


__all__ = [
    "APP_FIREWALL_NAME",
    "DEFAULT_PORT",
    "rule_exists",
    "ensure_inbound_rule",
    "remove_rule",
]


if __name__ == "__main__":
    # Quick CLI for diagnostics: `python -m antenna.firewall [--remove]`
    import argparse
    import json
    p = argparse.ArgumentParser(description="Antenna firewall-rule manager")
    p.add_argument("--remove", action="store_true",
                    help="delete the rule instead of creating")
    p.add_argument("--port", type=int, default=DEFAULT_PORT)
    p.add_argument("--name", default=APP_FIREWALL_NAME)
    args = p.parse_args()
    if args.remove:
        r = remove_rule(name=args.name)
    else:
        r = ensure_inbound_rule(port=args.port, name=args.name)
    print(json.dumps(r, indent=2))
    sys.exit(0 if (r.get("created") or r.get("existed") or r.get("removed")) else 1)
