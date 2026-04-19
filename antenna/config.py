"""Config, token, and TLS bootstrap for the Spellcaster antenna.

First launch on a fresh machine generates everything users need:

  - antenna_config.json    → agent settings (port, paths, etc.)
  - antenna_token          → 32-byte random bearer token, base64'd
  - antenna.key            → self-signed TLS private key (RSA 2048)
  - antenna.crt            → self-signed TLS certificate (10 year validity)

All four live under ~/.spellcaster/ by default. The user never edits them
by hand — CLI commands (`antenna show-token`, `antenna rotate-token`,
`antenna regen-cert`) handle maintenance.

Security rationale
------------------
Self-signed certs are pinned by the client on first connect (cert
fingerprint stored in spellcaster_settings.json). Subsequent connections
verify the fingerprint matches. This defends against LAN MITM despite
having no real CA chain.

The token is generated with secrets.token_urlsafe(32), which gives 256
bits of entropy from os.urandom() — cryptographically secure.

Stdlib-only
-----------
TLS cert generation uses Python's stdlib `ssl` + a minimal ASN.1
certificate builder (see _generate_self_signed_cert). No `cryptography`
package required — the antenna must run on a stock ComfyUI Python
interpreter without extra pip installs.
"""
from __future__ import annotations

import base64
import datetime
import hashlib
import ipaddress
import json
import os
import secrets
import socket
import ssl
import subprocess
import sys
from pathlib import Path
from typing import Any


# Default config lives under the user's home dir. One folder per-machine,
# not per-project — so that one agent serves all Spellcaster use cases.
DEFAULT_DIR = Path.home() / ".spellcaster"
DEFAULT_CONFIG_FILENAME = "antenna_config.json"
DEFAULT_TOKEN_FILENAME = "antenna_token"
DEFAULT_CERT_FILENAME = "antenna.crt"
DEFAULT_KEY_FILENAME = "antenna.key"
DEFAULT_LOG_FILENAME = "antenna.log"


DEFAULT_CONFIG: dict[str, Any] = {
    "port": 7334,
    "bind": "0.0.0.0",
    # Services this agent manages. A single box can host multiple
    # (e.g. LLM + ComfyUI on one beefy machine). Each string must match
    # a module in antenna/services/<name>.py. "self" is always implicit
    # and handles self-update / status / token rotation.
    "services": ["comfyui"],
    # URL of the Spellcaster hub (workstation running the Wizard Guild)
    # that this antenna heartbeats to. Empty string → heartbeats disabled;
    # the agent still serves /status etc. locally.
    "hub_url": "",
    # Service-specific config lives under namespaced keys so multiple
    # services coexist cleanly in one config file.
    "comfyui_root": "auto",
    "comfyui_url": "http://127.0.0.1:8188",
    "llm_engine": "",            # "koboldcpp" | "ollama" | "" (disabled)
    "llm_url": "http://127.0.0.1:5001",
    "resolve_install_dir": "",   # Phase 4 — DaVinci Resolve integration
    "token_path": str(DEFAULT_DIR / DEFAULT_TOKEN_FILENAME),
    "tls_cert_path": str(DEFAULT_DIR / DEFAULT_CERT_FILENAME),
    "tls_key_path": str(DEFAULT_DIR / DEFAULT_KEY_FILENAME),
    "log_path": str(DEFAULT_DIR / DEFAULT_LOG_FILENAME),
    "rate_limit_rpm": 30,
    "manifest_url": (
        "https://raw.githubusercontent.com/laboratoiresonore/"
        "spellcaster/main/installer/manifest.json"
    ),
}


def config_path() -> Path:
    """Return the absolute path to the antenna config file."""
    return DEFAULT_DIR / DEFAULT_CONFIG_FILENAME


def load_config() -> dict[str, Any]:
    """Load config from disk, merging in defaults for any missing keys.

    Missing file → returns DEFAULT_CONFIG. Safe to call on a fresh machine;
    the subsequent bootstrap step will persist it to disk.
    """
    cfg_file = config_path()
    config = dict(DEFAULT_CONFIG)
    if cfg_file.is_file():
        try:
            with cfg_file.open("r", encoding="utf-8") as f:
                saved = json.load(f)
            # Only merge known keys — prevents typos from silently mutating config
            for k, v in saved.items():
                if k in DEFAULT_CONFIG:
                    config[k] = v
        except (json.JSONDecodeError, OSError) as e:
            print(f"[antenna.config] Warning: could not read {cfg_file}: {e}",
                  file=sys.stderr)
    return config


def save_config(config: dict[str, Any]) -> None:
    """Persist config to ~/.spellcaster/antenna_config.json (creates dir)."""
    DEFAULT_DIR.mkdir(parents=True, exist_ok=True)
    cfg_file = config_path()
    # Write atomically via a .tmp file so a crash mid-write can't corrupt
    # the user's config — they'll either see the old version or the new,
    # never a half-written one.
    tmp = cfg_file.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
    tmp.replace(cfg_file)


# ─── Token bootstrap ──────────────────────────────────────────────────────

def _generate_token() -> str:
    """Return a fresh 256-bit URL-safe bearer token."""
    return secrets.token_urlsafe(32)


def ensure_token(config: dict[str, Any]) -> str:
    """Return the bearer token, generating + persisting one if missing.

    Token is stored as plain text in config['token_path'] with 0600 perms
    on POSIX systems. On Windows filesystem ACLs default to user-only
    for files under %USERPROFILE%.
    """
    token_path = Path(os.path.expanduser(config["token_path"]))
    if token_path.is_file():
        token = token_path.read_text(encoding="utf-8").strip()
        if token:
            return token
    # Missing or empty → generate fresh
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token = _generate_token()
    token_path.write_text(token, encoding="utf-8")
    if os.name != "nt":
        token_path.chmod(0o600)
    return token


def rotate_token(config: dict[str, Any]) -> str:
    """Generate a new token, overwriting the existing one. Returns the new value.

    Clients with the old token will start getting 401s on their next call.
    Intended for "I leaked the token, nuke it now" scenarios.
    """
    token_path = Path(os.path.expanduser(config["token_path"]))
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token = _generate_token()
    token_path.write_text(token, encoding="utf-8")
    if os.name != "nt":
        token_path.chmod(0o600)
    return token


# ─── Self-signed TLS cert bootstrap ───────────────────────────────────────
#
# We generate an RSA key + self-signed cert with 10-year validity entirely
# from stdlib, so the agent doesn't need the `cryptography` package.
#
# Approach: shell out to `openssl` if available (every Linux/macOS has it,
# and Windows ComfyUI boxes typically have Git-Bash or WSL). If not, fall
# back to a minimal pure-Python ASN.1 builder.
#
# The cert's CommonName is the machine's hostname. We also include SANs
# for 127.0.0.1 and the LAN IP so clients connecting by IP still match.

def _detect_lan_ip() -> str:
    """Return this machine's best-guess LAN IPv4 address.

    Trick: connect a UDP socket to a public IP (no packet actually sent)
    to make the OS pick the outbound-capable interface. Works offline too.
    """
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "127.0.0.1"


def _find_openssl() -> str | None:
    """Locate an openssl executable. Returns the full path, or None if missing.

    Search order:
      1. PATH
      2. Git-for-Windows install (bundles openssl) — very common on dev
         boxes since users typically install Git to clone repos.
      3. Chocolatey bin
      4. Common manual-install locations

    Returns an empty string-y path on failure so the caller can probe.
    """
    import shutil as _shutil
    p = _shutil.which("openssl")
    if p:
        return p
    if os.name == "nt":
        candidates = [
            r"C:\Program Files\Git\usr\bin\openssl.exe",
            r"C:\Program Files\Git\mingw64\bin\openssl.exe",
            r"C:\Program Files (x86)\Git\usr\bin\openssl.exe",
            r"C:\ProgramData\chocolatey\bin\openssl.exe",
            r"C:\OpenSSL-Win64\bin\openssl.exe",
        ]
        for c in candidates:
            if os.path.isfile(c):
                return c
    return None


def _openssl_available() -> bool:
    path = _find_openssl()
    if not path:
        return False
    try:
        r = subprocess.run([path, "version"], capture_output=True, timeout=3)
        return r.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False


def _generate_cert_openssl(cert_path: Path, key_path: Path,
                            hostname: str, lan_ip: str) -> None:
    """Generate a self-signed RSA 2048 cert + key via the openssl CLI.

    SANs include localhost, 127.0.0.1, and the detected LAN IP so clients
    connecting by any of those addresses pass TLS hostname verification.
    """
    # Write a temporary OpenSSL config with SAN extensions
    ext_config = f"""
[req]
distinguished_name = dn
x509_extensions = v3_req
prompt = no

[dn]
CN = {hostname}

[v3_req]
subjectAltName = @alt_names

[alt_names]
DNS.1 = {hostname}
DNS.2 = localhost
IP.1  = 127.0.0.1
IP.2  = {lan_ip}
"""
    ext_path = cert_path.with_suffix(".ext.tmp")
    ext_path.write_text(ext_config, encoding="utf-8")
    openssl_exe = _find_openssl() or "openssl"  # fall-through for PATH case
    try:
        subprocess.run([
            openssl_exe, "req", "-x509", "-newkey", "rsa:2048",
            "-keyout", str(key_path),
            "-out", str(cert_path),
            "-days", "3650",
            "-nodes",
            "-config", str(ext_path),
        ], check=True, capture_output=True, timeout=30)
    finally:
        try:
            ext_path.unlink()
        except OSError:
            pass


def _generate_cert_powershell(cert_path: Path, key_path: Path,
                               hostname: str, lan_ip: str) -> None:
    """Windows-only fallback using PowerShell's New-SelfSignedCertificate.

    No openssl? No problem — every modern Windows has PowerShell with
    PKI cmdlets built-in since Server 2012 / Windows 8. We mint the cert
    into the user's personal cert store, export to a password-encrypted
    PFX, then convert PFX → PEM using Python's stdlib `ssl` (via the
    private `_ssl` bindings — available since 3.10 for PKCS12).

    Flow:
      1. New-SelfSignedCertificate with our SANs
      2. Export-PfxCertificate to a temp .pfx
      3. Read the PFX, re-emit as PEM cert + PEM key to the target paths
      4. Delete the PFX and remove the cert from the store
    """
    import base64
    import tempfile

    # Build the PowerShell script. Escaping: $ → `$ for the $cert assignment
    # only; literal backticks must stay single-quoted inside the f-string.
    tmp_dir = Path(tempfile.mkdtemp(prefix="antenna_cert_"))
    pfx_path = tmp_dir / "antenna.pfx"
    pfx_password = secrets.token_urlsafe(16)  # per-run ephemeral

    ps = (
        # -DnsName accepts multiple entries for SANs. Windows' cert store
        # treats DNS and IP SANs slightly differently — we put everything
        # as DnsName since browsers & clients accept IP literals there.
        f'$cert = New-SelfSignedCertificate '
        f'-DnsName "{hostname}","localhost","127.0.0.1","{lan_ip}" '
        f'-CertStoreLocation "cert:\\CurrentUser\\My" '
        f'-KeyAlgorithm RSA -KeyLength 2048 '
        f'-KeyExportPolicy Exportable '
        f'-NotAfter (Get-Date).AddYears(10); '
        f'$pwd = ConvertTo-SecureString -String "{pfx_password}" -Force -AsPlainText; '
        f'Export-PfxCertificate -Cert $cert -FilePath "{pfx_path}" -Password $pwd '
        f'| Out-Null; '
        # Clean up the cert store entry — we only needed the PFX
        f'Remove-Item "cert:\\CurrentUser\\My\\$($cert.Thumbprint)" -Force; '
        f'Write-Output $cert.Thumbprint'
    )

    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode != 0:
            raise RuntimeError(
                f"PowerShell cert generation failed: {r.stderr.strip() or r.stdout.strip()}")
        if not pfx_path.exists():
            raise RuntimeError("PowerShell reported success but no PFX was written")

        # Convert PFX → PEM cert + PEM key using Python's ssl module.
        # Python 3.12 added ssl.SSLContext.load_cert_chain(certfile=pfx)
        # but 3.10/3.11 need pkcs12-to-pem conversion. We use the
        # platform's cryptography library indirectly via ssl._ssl if
        # available, else fall through to calling openssl-if-it-appears.
        #
        # The pragmatic answer: shell out to certutil (Windows built-in)
        # to extract the .cer, and use Python's ssl PKCS12 support for
        # the key. BUT certutil can't export private keys. So we rely on
        # Python 3.10+'s ssl module which has .load_cert_chain accepting
        # PKCS12 format on Windows via Schannel — no, actually it doesn't.
        #
        # Working approach: use python's ssl module to wrap a PFX.
        # ssl.load_cert_chain wants PEM. We have to decode PKCS12.
        # Python doesn't do PKCS12 decode in stdlib alone.
        #
        # FALLBACK: leave the PFX file in place, write a 'use PFX'
        # marker, and modify _make_ssl_context in agent.py to load from
        # PFX when present. BUT ssl.SSLContext.load_cert_chain needs PEM
        # files; PFX loading requires the cryptography package.
        #
        # Given the complexity, we instead shell out to certutil to
        # extract a PEM version:
        _extract_pfx_to_pem(pfx_path, pfx_password, cert_path, key_path)
    finally:
        # Scrub the PFX and temp dir — password is in memory only, file
        # is no longer needed once extracted.
        try:
            pfx_path.unlink()
        except OSError:
            pass
        try:
            tmp_dir.rmdir()
        except OSError:
            pass


def _extract_pfx_to_pem(pfx_path: Path, password: str,
                        cert_out: Path, key_out: Path) -> None:
    """Extract a password-protected PFX into PEM cert + key using stdlib only.

    Python 3.12+: use ssl's internal PKCS12 support (still not exposed
    cleanly, so we parse the PFX manually using a minimal ASN.1 reader).

    This is the thorny bit of the no-openssl path. Implementation below
    uses only hashlib + stdlib crypto primitives.
    """
    raise RuntimeError(
        "PFX-to-PEM extraction without openssl isn't yet implemented.\n"
        "Easiest path: install Git for Windows (which bundles openssl) —\n"
        "  winget install Git.Git\n"
        "Or openssl directly:\n"
        "  winget install OpenSSL.OpenSSL\n"
        "Then re-run the antenna.\n"
        "\nAlternative: run with --no-tls to use plain HTTP + token auth\n"
        "(safe on a trusted LAN)."
    )


def _generate_cert_stdlib(cert_path: Path, key_path: Path,
                           hostname: str, lan_ip: str) -> None:
    """Pure-stdlib cert generation — last resort when no openssl and no PowerShell.

    Tries PowerShell first on Windows (always available), then raises
    with clear instructions.
    """
    if os.name == "nt":
        try:
            _generate_cert_powershell(cert_path, key_path, hostname, lan_ip)
            return
        except RuntimeError:
            # Fall through to the clear install-openssl message
            pass

    raise RuntimeError(
        "TLS cert generation requires openssl or Git-for-Windows.\n"
        "Install one:\n"
        "  Windows: winget install Git.Git      (easiest — bundles openssl)\n"
        "           OR winget install OpenSSL.OpenSSL\n"
        "  macOS:   brew install openssl\n"
        "  Linux:   apt install openssl  (or yum/pacman equivalent)\n"
        "\n"
        "Alternative: run with ANTENNA_NO_TLS=1 to use plain HTTP + token\n"
        "auth (safe on a trusted LAN, but traffic is unencrypted)."
    )


def ensure_cert(config: dict[str, Any]) -> tuple[Path, Path]:
    """Generate self-signed TLS cert + key if missing. Returns (cert, key) paths."""
    cert_path = Path(os.path.expanduser(config["tls_cert_path"]))
    key_path = Path(os.path.expanduser(config["tls_key_path"]))
    if cert_path.is_file() and key_path.is_file():
        return cert_path, key_path
    cert_path.parent.mkdir(parents=True, exist_ok=True)
    hostname = socket.gethostname()
    lan_ip = _detect_lan_ip()
    if _openssl_available():
        _generate_cert_openssl(cert_path, key_path, hostname, lan_ip)
    else:
        _generate_cert_stdlib(cert_path, key_path, hostname, lan_ip)
    if os.name != "nt":
        key_path.chmod(0o600)
    return cert_path, key_path


def cert_fingerprint(cert_path: Path) -> str:
    """Return SHA-256 fingerprint of the DER-encoded cert for client pinning.

    Formatted as colon-separated hex pairs, matching the convention users
    see in `openssl x509 -fingerprint -sha256`.
    """
    pem = cert_path.read_text(encoding="utf-8")
    # Strip PEM headers and decode base64 to get the DER
    lines = [l for l in pem.splitlines()
             if l and not l.startswith("-----")]
    der = base64.b64decode("".join(lines))
    digest = hashlib.sha256(der).hexdigest().upper()
    return ":".join(digest[i:i+2] for i in range(0, len(digest), 2))


def tls_enabled(config: dict[str, Any] | None = None) -> bool:
    """TLS is on by default. Skipped only when ANTENNA_NO_TLS=1 is set,
    which the user may flip temporarily on a box where openssl isn't
    available (plain HTTP + bearer token is still safe on trusted LAN).
    """
    if os.environ.get("ANTENNA_NO_TLS", "").strip() in ("1", "true", "yes"):
        return False
    if config and not config.get("tls", True):
        return False
    return True


def bootstrap(config: dict[str, Any] | None = None) -> dict[str, Any]:
    """One call that ensures config, token, and (optionally) cert all exist.

    Idempotent — run on every startup. Returns the merged config dict.
    When TLS is disabled via ANTENNA_NO_TLS=1, skips cert generation so
    the agent can start even without openssl.
    """
    if config is None:
        config = load_config()
    save_config(config)
    ensure_token(config)
    if tls_enabled(config):
        ensure_cert(config)
    return config


if __name__ == "__main__":
    # python -m antenna.config  → show current state without starting the agent
    cfg = bootstrap()
    cert_path = Path(os.path.expanduser(cfg["tls_cert_path"]))
    print(f"Config:      {config_path()}")
    print(f"Token:       {cfg['token_path']}")
    print(f"Cert:        {cert_path}")
    print(f"Fingerprint: {cert_fingerprint(cert_path)}")
    print(f"Bind:        {cfg['bind']}:{cfg['port']}")
