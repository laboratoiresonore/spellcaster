#!/usr/bin/env python3
"""Fetch repository metadata and save to JSON file."""

import json
import urllib.request
import urllib.error
import ssl
import os

# Repository configuration - hard-coded as specified
# Using a known public repository for testing
REPO_OWNER = "golang"
REPO_NAME = "go"
GITHUB_API_BASE = "https://api.github.com"

def fetch_json(url):
    """Fetch JSON from GitHub API with error handling."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    
    try:
        req = urllib.request.Request(
            url,
            headers={
                "Accept": "application/vnd.github.v3+json",
                "User-Agent": "hermes-fetch-metadata/1.0"
            }
        )
        with urllib.request.urlopen(req, context=ctx, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise
    except Exception as e:
        raise


def fetch_license(license_url):
    """Fetch license details from license URL if available."""
    if not license_url:
        return {"key": None, "name": None, "spdx_id": None, "html_url": None}
    try:
        data = fetch_json(license_url)
        if data:
            return {
                "key": data.get("key"),
                "name": data.get("name"),
                "spdx_id": data.get("spdx_id"),
                "html_url": data.get("html_url")
            }
    except Exception:
        pass
    return {"key": None, "name": None, "spdx_id": None, "html_url": None}


def main():
    repo_url = f"{GITHUB_API_BASE}/repos/{REPO_OWNER}/{REPO_NAME}"
    
    result = {
        "description": None,
        "primary_language": None,
        "stars": 0,
        "forks": 0,
        "watchers": 0,
        "size_kb": 0,
        "size_mb": 0.0,
        "latest_commit_date": None,
        "license": {"key": None, "name": None, "spdx_id": None, "html_url": None},
        "tags": [],
        "releases": [],
        "accessibility_note": None,
        "html_url": None
    }
    
    # Fetch repository metadata
    try:
        repo_data = fetch_json(repo_url)
        if repo_data is None:
            result["accessibility_note"] = "Repository not found or inaccessible"
            print(f"Repository {REPO_OWNER}/{REPO_NAME} not found (404)")
            write_metadata(result)
            return
        
        result["description"] = repo_data.get("description")
        result["primary_language"] = repo_data.get("language")
        result["stars"] = repo_data.get("stargazers_count", 0)
        result["forks"] = repo_data.get("forks_count", 0)
        result["watchers"] = repo_data.get("subscribers_count", 0)
        result["html_url"] = repo_data.get("html_url")
        
        # Size is in KB, convert to MB with 2 decimals
        size_kb = repo_data.get("size", 0)
        result["size_kb"] = size_kb
        result["size_mb"] = round(size_kb / 1024, 2)
        
        # License info
        license_data = repo_data.get("license", {})
        if license_data:
            result["license"]["key"] = license_data.get("key")
            result["license"]["name"] = license_data.get("name")
            result["license"]["spdx_id"] = license_data.get("spdx_id")
            result["license"]["html_url"] = license_data.get("html_url")
        
    except Exception as e:
        result["accessibility_note"] = f"Error fetching repository metadata: {str(e)}"
        print(f"Error fetching repository: {e}")
    
    # Fetch default branch and latest commit
    try:
        repo_data = fetch_json(repo_url)
        if repo_data:
            default_branch = repo_data.get("default_branch", "main")
            commits_url = f"{repo_url}/commits/{default_branch}"
            commit_data = fetch_json(commits_url)
            if commit_data:
                result["latest_commit_date"] = commit_data.get("commit", {}).get("committer", {}).get("date")
    except Exception as e:
        print(f"Error fetching commit data: {e}")
    
    # Fetch tags
    try:
        tags_url = f"{repo_url}/tags"
        tags_data = fetch_json(tags_url)
        if tags_data:
            result["tags"] = [t.get("name") for t in tags_data if isinstance(t, dict)]
    except Exception as e:
        print(f"Error fetching tags: {e}")
    
    # Fetch releases
    try:
        releases_url = f"{repo_url}/releases"
        releases_data = fetch_json(releases_url)
        if releases_data:
            result["releases"] = [
                {
                    "tag_name": r.get("tag_name"),
                    "url": r.get("html_url")
                }
                for r in releases_data
                if isinstance(r, dict)
            ]
    except Exception as e:
        print(f"Error fetching releases: {e}")
    
    # Final accessibility note if not already set
    if result["accessibility_note"] is None:
        result["accessibility_note"] = "public"
    
    write_metadata(result)
    print("Metadata saved successfully")


def write_metadata(result):
    """Write metadata to JSON file."""
    # Determine output path - save to workspace directory
    script_dir = os.path.dirname(os.path.abspath(__file__))
    workspace_dir = os.path.dirname(script_dir) if os.path.basename(script_dir) == 'tests' else script_dir
    output_path = os.path.join(workspace_dir, 'metadata.json')
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, indent=2)
    
    print(f"Metadata saved to {output_path}")


if __name__ == "__main__":
    main()
