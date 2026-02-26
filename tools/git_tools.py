# tools/git_tools.py
# Phase 6.1 — Git integration for agents.
# After an agent succeeds, auto-commit the work with a meaningful message.

import subprocess
import os


def is_git_repo(directory: str) -> bool:
    """Return True if the directory is inside a git repository."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            cwd=directory,
            capture_output=True,
            text=True,
            timeout=5
        )
        return result.returncode == 0
    except Exception:
        return False


def git_add_all(directory: str) -> tuple[bool, str]:
    """Stage all changes in the directory. Returns (success, output)."""
    try:
        result = subprocess.run(
            ["git", "add", "."],
            cwd=directory,
            capture_output=True,
            text=True,
            timeout=30
        )
        return result.returncode == 0, result.stdout + result.stderr
    except Exception as e:
        return False, str(e)


def git_commit(directory: str, message: str) -> tuple[bool, str]:
    """Commit staged changes with a message. Returns (success, output)."""
    try:
        result = subprocess.run(
            ["git", "commit", "-m", message],
            cwd=directory,
            capture_output=True,
            text=True,
            timeout=30
        )
        return result.returncode == 0, result.stdout + result.stderr
    except Exception as e:
        return False, str(e)


def git_auto_commit(directory: str, task: str) -> tuple[bool, str]:
    """
    Stage all changes and commit with a message derived from the task.
    Skips gracefully if not a git repo or if nothing changed.
    Returns (success, message).
    """
    if not is_git_repo(directory):
        return False, "Not a git repository — skipping auto-commit."

    # Check if there are any changes to commit
    try:
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=directory,
            capture_output=True,
            text=True,
            timeout=5
        )
        if not status.stdout.strip():
            return True, "Nothing to commit — working tree clean."
    except Exception as e:
        return False, f"git status failed: {e}"

    ok, msg = git_add_all(directory)
    if not ok:
        return False, f"git add failed: {msg}"

    commit_msg = f"feat: {task[:72].strip()}"
    ok, msg = git_commit(directory, commit_msg)
    if not ok:
        return False, f"git commit failed: {msg}"

    return True, f"Committed: {commit_msg}"
