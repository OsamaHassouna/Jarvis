"""
tests/test_phase19.py — Phase 19: Configurable Watcher & Smart Notifications.

Tests:
  - config.load_workspace_config: defaults, merging, hot reload, invalid JSON
  - tools/watcher.py: config-driven thresholds, branch filtering, multi-framework detection
  - tools/notifications.py: expire_hours parameter
"""
import json
import os
import time

import pytest


# ── helpers ────────────────────────────────────────────────────────────────────

def _clear_all(tmp_path=None):
    import config
    import tools.notifications as notif_mod
    import tools.watcher as watcher
    config._workspace_configs.clear()
    notif_mod._notifications.clear()
    watcher._notified_keys.clear()


# ── config.load_workspace_config ───────────────────────────────────────────────

def test_load_workspace_config_returns_defaults(tmp_path):
    """No config file → all defaults returned."""
    import config
    config._workspace_configs.clear()
    cfg = config.load_workspace_config(str(tmp_path))
    assert cfg["watcher"]["stale_test_gap_hours"] == 24
    assert cfg["watcher"]["long_branch_days"] == 5
    assert cfg["watcher"]["many_files_count"] == 8
    assert "main" in cfg["watcher"]["ignore_branches"]
    assert cfg["notifications"]["expire_hours"] == 168


def test_load_workspace_config_merges_custom(tmp_path):
    """Partial config overrides specified keys; rest stay as defaults."""
    import config
    config._workspace_configs.clear()
    (tmp_path / "jarvis.config.json").write_text(json.dumps({
        "watcher": {"stale_test_gap_hours": 48, "many_files_count": 12},
        "notifications": {"expire_hours": 72},
    }))
    cfg = config.load_workspace_config(str(tmp_path))
    assert cfg["watcher"]["stale_test_gap_hours"] == 48
    assert cfg["watcher"]["many_files_count"] == 12
    assert cfg["watcher"]["long_branch_days"] == 5   # default preserved
    assert cfg["notifications"]["expire_hours"] == 72


def test_load_workspace_config_hot_reloads(tmp_path):
    """Changing jarvis.config.json is picked up on next call (no restart)."""
    import config
    config._workspace_configs.clear()
    cfg_file = tmp_path / "jarvis.config.json"
    cfg_file.write_text(json.dumps({"watcher": {"many_files_count": 5}}))

    cfg1 = config.load_workspace_config(str(tmp_path))
    assert cfg1["watcher"]["many_files_count"] == 5

    # Overwrite and touch so mtime differs
    cfg_file.write_text(json.dumps({"watcher": {"many_files_count": 15}}))
    future = time.time() + 2
    os.utime(cfg_file, (future, future))

    cfg2 = config.load_workspace_config(str(tmp_path))
    assert cfg2["watcher"]["many_files_count"] == 15


def test_load_workspace_config_invalid_json(tmp_path):
    """Invalid JSON → returns defaults without raising."""
    import config
    config._workspace_configs.clear()
    (tmp_path / "jarvis.config.json").write_text("not valid json {{{")
    cfg = config.load_workspace_config(str(tmp_path))
    assert cfg["watcher"]["stale_test_gap_hours"] == 24
    assert cfg["notifications"]["expire_hours"] == 168


# ── watcher: config-driven thresholds ─────────────────────────────────────────

def test_watcher_respects_stale_test_gap_hours(tmp_path):
    """Custom stale_test_gap_hours=1 fires for a 1.5h gap that default (24h) would ignore."""
    _clear_all()
    import tools.notifications as notif_mod
    import tools.watcher as watcher

    (tmp_path / "jarvis.config.json").write_text(json.dumps({
        "watcher": {"stale_test_gap_hours": 1}
    }))

    now = time.time()
    src = tmp_path / "button.ts"
    spec = tmp_path / "button.spec.ts"
    src.write_text("// src")
    spec.write_text("// spec")

    # src 30 min ago, spec 2h ago → 1.5h gap > 1h threshold → notification
    os.utime(src, (now - 1800, now - 1800))
    os.utime(spec, (now - 7200, now - 7200))

    watcher.run_checks_once(str(tmp_path))

    notifications = notif_mod.get_notifications()
    assert len(notifications) == 1
    assert "button.ts" in notifications[0]["message"]


def test_watcher_respects_many_files_count(tmp_path, monkeypatch):
    """Custom many_files_count=3 fires when 4 files are uncommitted (default=8 would not)."""
    _clear_all()
    import tools.notifications as notif_mod
    import tools.watcher as watcher

    (tmp_path / "jarvis.config.json").write_text(json.dumps({
        "watcher": {"many_files_count": 3, "ignore_branches": []}
    }))

    monkeypatch.setattr(watcher, "_git_changed_count", lambda ws: 4)
    monkeypatch.setattr(watcher, "_git_last_commit_ts", lambda ws: time.time() - 108000)  # 30h
    monkeypatch.setattr(watcher, "_git_branch", lambda ws: "feature/test")

    watcher.run_checks_once(str(tmp_path))

    assert any(n["type"] == "many_uncommitted" for n in notif_mod.get_notifications())


def test_watcher_respects_long_branch_days(tmp_path, monkeypatch):
    """Custom long_branch_days=2 fires after 3 days (default=5 would not)."""
    _clear_all()
    import tools.notifications as notif_mod
    import tools.watcher as watcher

    (tmp_path / "jarvis.config.json").write_text(json.dumps({
        "watcher": {"long_branch_days": 2, "ignore_branches": []}
    }))

    monkeypatch.setattr(watcher, "_git_changed_count", lambda ws: 1)
    monkeypatch.setattr(watcher, "_git_last_commit_ts", lambda ws: time.time() - (3 * 86400))
    monkeypatch.setattr(watcher, "_git_branch", lambda ws: "feature/something")

    watcher.run_checks_once(str(tmp_path))

    assert any(n["type"] == "long_running_branch" for n in notif_mod.get_notifications())


# ── watcher: branch filtering ──────────────────────────────────────────────────

def test_watcher_branch_filtering_suppresses_long_branch(tmp_path, monkeypatch):
    """Branches in ignore_branches suppress long_running_branch notification."""
    _clear_all()
    import tools.notifications as notif_mod
    import tools.watcher as watcher

    monkeypatch.setattr(watcher, "_git_changed_count", lambda ws: 3)
    monkeypatch.setattr(watcher, "_git_last_commit_ts", lambda ws: time.time() - (2 * 86400))
    monkeypatch.setattr(watcher, "_git_branch", lambda ws: "main")

    watcher._check_long_running_branch(str(tmp_path), {
        "long_branch_days": 1,
        "ignore_branches": ["main", "master"],
    })

    assert notif_mod.get_notifications() == []


def test_watcher_branch_filtering_suppresses_many_uncommitted(tmp_path, monkeypatch):
    """Branches in ignore_branches suppress many_uncommitted notification."""
    _clear_all()
    import tools.notifications as notif_mod
    import tools.watcher as watcher

    monkeypatch.setattr(watcher, "_git_changed_count", lambda ws: 20)
    monkeypatch.setattr(watcher, "_git_last_commit_ts", lambda ws: time.time() - 108000)
    monkeypatch.setattr(watcher, "_git_branch", lambda ws: "develop")

    watcher._check_many_uncommitted(str(tmp_path), {
        "many_files_count": 5,
        "ignore_branches": ["main", "master", "develop"],
    })

    assert notif_mod.get_notifications() == []


# ── watcher: multi-framework spec detection ────────────────────────────────────

def test_get_spec_names_returns_both_ts_patterns():
    """_get_spec_names returns both .spec.ts and .test.ts for TypeScript sources."""
    from tools.watcher import _get_spec_names
    names = _get_spec_names("auth.service.ts")
    assert "auth.service.spec.ts" in names
    assert "auth.service.test.ts" in names


def test_get_spec_names_detects_js_patterns():
    """_get_spec_names returns .spec.js and .test.js for JavaScript sources."""
    from tools.watcher import _get_spec_names
    names = _get_spec_names("utils.js")
    assert "utils.spec.js" in names
    assert "utils.test.js" in names


def test_stale_test_detector_finds_test_ts_pattern(tmp_path):
    """Stale detector fires when .test.ts (jest style) is outdated."""
    _clear_all()
    import tools.notifications as notif_mod
    import tools.watcher as watcher

    now = time.time()
    src = tmp_path / "user.service.ts"
    test_file = tmp_path / "user.service.test.ts"
    src.write_text("export class UserService {}")
    test_file.write_text("test('user', () => {})")

    os.utime(src, (now - 3600, now - 3600))              # 1h ago
    os.utime(test_file, (now - (2 * 86400), now - (2 * 86400)))  # 2 days ago

    watcher.run_checks_once(str(tmp_path))

    notifications = notif_mod.get_notifications()
    assert any("user.service.ts" in n["message"] for n in notifications)


# ── notifications: expire_hours parameter ─────────────────────────────────────

def test_get_notifications_custom_expire_hours():
    """expire_hours=1 drops notifications older than 1h but keeps fresh ones."""
    import tools.notifications as mod
    mod._notifications.clear()

    old_ts = time.time() - 7200  # 2h ago
    mod._notifications.append({
        "id": "notif_old",
        "type": "stale_test",
        "message": "old",
        "workspace": "",
        "severity": "info",
        "created_at": old_ts,
    })
    mod.add_notification("stale_test", "fresh", workspace="")

    result = mod.get_notifications(expire_hours=1)
    assert len(result) == 1
    assert result[0]["message"] == "fresh"


def test_get_notifications_default_expire_keeps_recent():
    """Default expire (7 days) keeps notifications less than 7 days old."""
    import tools.notifications as mod
    mod._notifications.clear()

    ts = time.time() - (3 * 86400)  # 3 days ago
    mod._notifications.append({
        "id": "notif_3d",
        "type": "long_branch",
        "message": "3 days old",
        "workspace": "",
        "severity": "warning",
        "created_at": ts,
    })

    result = mod.get_notifications()
    assert len(result) == 1
    assert result[0]["id"] == "notif_3d"
