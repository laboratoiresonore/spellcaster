#!/usr/bin/env python3
"""
Upload dist/*.exe binaries to a GitHub Release.

Called by rebuild.bat when gh CLI is not available.
Reads the GitHub PAT from the git remote URL.

Usage:
    python release_upload.py --tag v2.2 --dist dist --repo laboratoiresonore/spellcaster
"""

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request


def get_token():
    """Extract GitHub PAT from git remote URL (https://TOKEN@github.com/...)."""
    try:
        remote = subprocess.check_output(
            ["git", "remote", "get-url", "origin"],
            text=True, stderr=subprocess.DEVNULL
        ).strip()
        if "@" in remote and "github.com" in remote:
            return remote.split("//")[1].split("@")[0]
    except Exception:
        pass
    # Fallback: GITHUB_TOKEN env var
    return os.environ.get("GITHUB_TOKEN", "")


def api_request(url, token, method="GET", data=None, content_type="application/json"):
    """Make a GitHub API request."""
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
    }
    if content_type:
        headers["Content-Type"] = content_type

    body = None
    if data is not None:
        if isinstance(data, bytes):
            body = data
        else:
            body = json.dumps(data).encode("utf-8")

    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if method == "DELETE" and e.code == 204:
            return {}
        err_body = ""
        try:
            err_body = e.read().decode("utf-8")
        except Exception:
            pass
        print(f"  API error {e.code}: {err_body[:200]}")
        raise


def main():
    parser = argparse.ArgumentParser(description="Upload binaries to GitHub Release")
    parser.add_argument("--tag", required=True, help="Release tag (e.g. v2.2)")
    parser.add_argument("--dist", default="dist", help="Directory containing .exe files")
    parser.add_argument("--repo", default="laboratoiresonore/spellcaster",
                        help="GitHub repo (owner/name)")
    args = parser.parse_args()

    token = get_token()
    if not token:
        print("  ERROR: No GitHub token found.")
        print("  Set GITHUB_TOKEN env var or embed token in git remote URL.")
        sys.exit(1)

    api = "https://api.github.com"
    tag = args.tag
    repo = args.repo

    # Get or create release
    try:
        release = api_request(f"{api}/repos/{repo}/releases/tags/{tag}", token)
        print(f"  Found existing release: {tag}")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            print(f"  Creating release {tag}...")
            release = api_request(
                f"{api}/repos/{repo}/releases", token, method="POST",
                data={
                    "tag_name": tag,
                    "name": tag,
                    "body": "Rebuilt Windows executables.",
                    "draft": False,
                },
            )
            print(f"  Created release: {tag}")
        else:
            raise

    release_id = release["id"]
    upload_url = release["upload_url"].split("{")[0]

    # Map existing assets for clobber
    existing = {}
    try:
        assets = api_request(
            f"{api}/repos/{repo}/releases/{release_id}/assets", token
        )
        for a in assets:
            existing[a["name"]] = a["id"]
    except Exception:
        pass

    # Upload each binary
    exe_files = [
        "spellcaster-installer.exe",
        "spellcaster-manual-update.exe",
        "Wizard_Guild.exe",
    ]

    uploaded = 0
    for exe in exe_files:
        fpath = os.path.join(args.dist, exe)
        if not os.path.exists(fpath):
            continue

        # Delete old asset if it exists (clobber)
        if exe in existing:
            try:
                api_request(
                    f"{api}/repos/{repo}/releases/assets/{existing[exe]}",
                    token, method="DELETE",
                )
                print(f"  Replaced old {exe}")
            except Exception:
                pass

        fsize = os.path.getsize(fpath)
        print(f"  Uploading {exe} ({fsize:,} bytes)...")

        with open(fpath, "rb") as f:
            data = f.read()

        try:
            result = api_request(
                f"{upload_url}?name={exe}", token, method="POST",
                data=data, content_type="application/octet-stream",
            )
            dl_url = result.get("browser_download_url", "ok")
            print(f"  Uploaded {exe} -> {dl_url}")
            uploaded += 1
        except Exception as ex:
            print(f"  FAILED to upload {exe}: {ex}")

    if uploaded == 0:
        print("  No .exe files found in dist/ to upload.")
    else:
        print(f"  Done — {uploaded} file(s) uploaded to {tag}")
        print(f"  https://github.com/{repo}/releases/tag/{tag}")


if __name__ == "__main__":
    main()
