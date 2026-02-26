# tools/sync.py
# Phase 5.4 — Cross-machine memory sync via GitHub Gist.
# Pushes memory.json to a private Gist on save; pulls on first load per session.
# Uses only stdlib (urllib) — no extra dependencies.

import json
import urllib.request
import urllib.error


def push_memory(memory_path: str, token: str, gist_id: str) -> tuple[bool, str]:
    """
    Upload memory.json content to a GitHub Gist.
    Returns (success, message).
    """
    if not token or not gist_id:
        return False, "GitHub token or Gist ID not configured."

    try:
        with open(memory_path, "r", encoding="utf-8") as f:
            content = f.read()

        payload = json.dumps({
            "files": {"memory.json": {"content": content}}
        }).encode("utf-8")

        req = urllib.request.Request(
            f"https://api.github.com/gists/{gist_id}",
            data=payload,
            method="PATCH",
            headers={
                "Authorization": f"token {token}",
                "Content-Type": "application/json",
                "Accept": "application/vnd.github+json",
                "User-Agent": "Jarvis-Sync/1.0"
            }
        )
        with urllib.request.urlopen(req, timeout=10):
            pass
        return True, "Memory synced to GitHub Gist."

    except urllib.error.HTTPError as e:
        return False, f"GitHub API error {e.code}: {e.reason}"
    except Exception as e:
        return False, f"Sync push failed: {e}"


def pull_memory(memory_path: str, token: str, gist_id: str) -> tuple[bool, str]:
    """
    Download memory.json from a GitHub Gist and write it locally.
    Returns (success, message).
    """
    if not token or not gist_id:
        return False, "GitHub token or Gist ID not configured."

    try:
        req = urllib.request.Request(
            f"https://api.github.com/gists/{gist_id}",
            headers={
                "Authorization": f"token {token}",
                "Accept": "application/vnd.github+json",
                "User-Agent": "Jarvis-Sync/1.0"
            }
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode("utf-8"))

        files = data.get("files", {})
        if "memory.json" not in files:
            return False, "memory.json not found in Gist."

        content = files["memory.json"].get("content", "")
        if not content:
            return False, "Gist memory.json is empty."

        # Validate it's real JSON before writing
        json.loads(content)

        with open(memory_path, "w", encoding="utf-8") as f:
            f.write(content)

        return True, "Memory pulled from GitHub Gist."

    except urllib.error.HTTPError as e:
        return False, f"GitHub API error {e.code}: {e.reason}"
    except json.JSONDecodeError:
        return False, "Gist content is not valid JSON — skipping pull."
    except Exception as e:
        return False, f"Sync pull failed: {e}"
