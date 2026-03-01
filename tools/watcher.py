"""
tools/watcher.py — Phase 15: Proactive background watcher.
Phase 19: Config-driven thresholds, branch filtering, multi-framework spec detection.

Runs periodic checks every 5 minutes on registered project directories.
Adds notifications to tools/notifications.py when patterns are detected.

No external dependencies — uses os.walk, subprocess (for git), and threading.

Detectors:
  1. Stale tests      — source file modified but spec/test file not updated (gap > threshold)
  2. Long-running branch — no git commit for N+ days with uncommitted changes
  3. Many uncommitted  — N+ uncommitted files with no commit for 24+ hours
"""

import os
import subprocess
import threading
import time

from tools.notifications import add_notification

# ── Constants ──────────────────────────────────────────────────────────────────

_CHECK_INTERVAL = 300          # seconds between full check cycles (5 minutes)
_SOURCE_RECENT = 172800        # source must have been modified within 48h

# Default thresholds (overridable via jarvis.config.json)
_STALE_TEST_GAP = 86400        # spec must be > 24h older than source
_LONG_BRANCH_DAYS = 5          # no commit for this many days = long-running
_MANY_FILES_COUNT = 8          # uncommitted file threshold
_MANY_FILES_HOURS = 24         # hours since last commit for "many uncommitted" check

_SKIP_DIRS = frozenset({
    "node_modules", ".git", "bin", "obj", "dist", "__pycache__",
    ".angular", ".next", "coverage", "out",
})

# ── State ──────────────────────────────────────────────────────────────────────

_active_workspaces: set = set()
_notified_keys: set = set()     # prevent duplicate notifications in same session
_watcher_thread = None
_ws_lock = threading.Lock()


# ── Public API ─────────────────────────────────────────────────────────────────

def register_workspace(workspace_root: str) -> None:
    """Tell the watcher to monitor this directory."""
    with _ws_lock:
        _active_workspaces.add(os.path.normpath(workspace_root))


def start_watcher() -> None:
    """Start the background watcher thread (idempotent — safe to call multiple times)."""
    global _watcher_thread
    if _watcher_thread and _watcher_thread.is_alive():
        return
    _watcher_thread = threading.Thread(target=_watcher_loop, daemon=True,
                                       name="jarvis-watcher")
    _watcher_thread.start()


def run_checks_once(workspace_root: str) -> None:
    """Run all detectors on a single workspace immediately (also used in tests)."""
    if not os.path.isdir(workspace_root):
        return
    # Phase 19: hot-reload config on each cycle
    from config import load_workspace_config
    cfg = load_workspace_config(workspace_root)
    wcfg = cfg["watcher"]
    _check_stale_tests(workspace_root, wcfg)
    _check_long_running_branch(workspace_root, wcfg)
    _check_many_uncommitted(workspace_root, wcfg)


# ── Internal loop ──────────────────────────────────────────────────────────────

def _watcher_loop() -> None:
    while True:
        time.sleep(_CHECK_INTERVAL)
        with _ws_lock:
            workspaces = set(_active_workspaces)
        for ws in workspaces:
            try:
                run_checks_once(ws)
            except Exception:
                pass


# ── Detector 1: Stale test files ──────────────────────────────────────────────

def _check_stale_tests(workspace_root: str, cfg: dict | None = None) -> None:
    """
    Walk source files modified in the last 48h.
    If any matching spec/test file exists but is > threshold older, notify.
    Covers TypeScript (.ts / .spec.ts / .test.ts), JavaScript (.js),
    and C# (.cs / Tests.cs / .Test.cs).
    """
    if cfg is None:
        cfg = {}
    stale_gap = cfg.get("stale_test_gap_hours", 24) * 3600
    now = time.time()

    for dirpath, dirnames, filenames in os.walk(workspace_root):
        # Prune directories we never want to descend into
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]

        for fname in filenames:
            spec_names = _get_spec_names(fname)
            if not spec_names:
                continue

            fpath = os.path.join(dirpath, fname)

            try:
                src_mtime = os.path.getmtime(fpath)
            except OSError:
                continue

            # Only care about recently modified sources
            if now - src_mtime > _SOURCE_RECENT:
                continue

            for spec_name in spec_names:
                spec_path = os.path.join(dirpath, spec_name)
                if not os.path.exists(spec_path):
                    continue

                try:
                    spec_mtime = os.path.getmtime(spec_path)
                except OSError:
                    continue

                gap = src_mtime - spec_mtime
                if gap <= stale_gap:
                    continue

                key = f"stale_test:{fpath}:{int(src_mtime)}"
                if key in _notified_keys:
                    break
                _notified_keys.add(key)

                rel = os.path.relpath(fpath, workspace_root)
                days = max(1, int(gap // 86400))
                add_notification(
                    type_="stale_test",
                    message=(
                        f"{rel} was modified but {spec_name} "
                        f"hasn't been updated in {days} day{'s' if days != 1 else ''}"
                    ),
                    workspace=workspace_root,
                    severity="info",
                )
                break  # one notification per source file


def _get_spec_names(fname: str) -> list[str]:
    """Return expected spec filenames for a source file. Empty list if not applicable."""
    # TypeScript: foo.ts → foo.spec.ts + foo.test.ts
    if fname.endswith(".ts") and not (
        fname.endswith(".spec.ts") or fname.endswith(".test.ts") or fname.endswith(".d.ts")
    ):
        stem = fname[:-3]
        return [stem + ".spec.ts", stem + ".test.ts"]
    # JavaScript: foo.js → foo.spec.js + foo.test.js
    if fname.endswith(".js") and not (
        fname.endswith(".spec.js") or fname.endswith(".test.js")
    ):
        stem = fname[:-3]
        return [stem + ".spec.js", stem + ".test.js"]
    # C#: FooService.cs → FooServiceTests.cs + FooService.Test.cs
    if fname.endswith(".cs") and not (
        fname.endswith("Tests.cs") or fname.endswith("Spec.cs") or fname.endswith(".Test.cs")
    ):
        stem = fname[:-3]
        return [stem + "Tests.cs", stem + ".Test.cs"]
    return []


# ── Detector 2: Long-running branch ───────────────────────────────────────────

def _check_long_running_branch(workspace_root: str, cfg: dict | None = None) -> None:
    """Notify if last commit > N days ago AND there are uncommitted changes."""
    if cfg is None:
        cfg = {}
    ignore_branches = cfg.get("ignore_branches", [])
    days_threshold = cfg.get("long_branch_days", _LONG_BRANCH_DAYS)
    try:
        branch = _git_branch(workspace_root)
        if branch and branch in ignore_branches:
            return

        last_ts = _git_last_commit_ts(workspace_root)
        if last_ts is None:
            return
        days_since = (time.time() - last_ts) / 86400
        if days_since < days_threshold:
            return

        changed = _git_changed_count(workspace_root)
        if changed == 0:
            return

        key = f"long_branch:{workspace_root}:{int(last_ts)}"
        if key in _notified_keys:
            return
        _notified_keys.add(key)

        branch_name = branch or "current branch"
        add_notification(
            type_="long_running_branch",
            message=(
                f"{branch_name}: {changed} uncommitted file(s), "
                f"no commit in {int(days_since)} days"
            ),
            workspace=workspace_root,
            severity="warning",
        )
    except Exception:
        pass


# ── Detector 3: Many uncommitted files ────────────────────────────────────────

def _check_many_uncommitted(workspace_root: str, cfg: dict | None = None) -> None:
    """Notify if N+ files are uncommitted and last commit was > 24h ago."""
    if cfg is None:
        cfg = {}
    ignore_branches = cfg.get("ignore_branches", [])
    count_threshold = cfg.get("many_files_count", _MANY_FILES_COUNT)
    try:
        branch = _git_branch(workspace_root)
        if branch and branch in ignore_branches:
            return

        changed = _git_changed_count(workspace_root)
        if changed < count_threshold:
            return

        last_ts = _git_last_commit_ts(workspace_root)
        if last_ts is None:
            return
        hours_since = (time.time() - last_ts) / 3600
        if hours_since < _MANY_FILES_HOURS:
            return

        key = f"uncommitted:{workspace_root}"
        if key in _notified_keys:
            return
        _notified_keys.add(key)

        add_notification(
            type_="many_uncommitted",
            message=(
                f"{changed} uncommitted files with no commit "
                f"in {int(hours_since)}h — consider committing your work"
            ),
            workspace=workspace_root,
            severity="warning",
        )
    except Exception:
        pass


# ── Git helpers ────────────────────────────────────────────────────────────────

def _git_last_commit_ts(workspace_root: str) -> float | None:
    result = subprocess.run(
        ["git", "log", "-1", "--format=%ct"],
        cwd=workspace_root, capture_output=True, text=True, timeout=5,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return None
    try:
        return float(result.stdout.strip())
    except ValueError:
        return None


def _git_changed_count(workspace_root: str) -> int:
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=workspace_root, capture_output=True, text=True, timeout=5,
    )
    if result.returncode != 0:
        return 0
    return len([l for l in result.stdout.splitlines() if l.strip()])


def _git_branch(workspace_root: str) -> str | None:
    result = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=workspace_root, capture_output=True, text=True, timeout=5,
    )
    return result.stdout.strip() if result.returncode == 0 else None
