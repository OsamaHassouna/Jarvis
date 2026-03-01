"""
tests/test_phase15.py — Phase 15: Proactive background watcher.

Tests:
  - tools/notifications.py  (add, get, dismiss, dismiss_all)
  - tools/watcher.py        (stale test detector, long-running branch, many uncommitted)
  - server.py               (/notifications GET, /notifications/dismiss POST)
"""
import os
import time
import json
import pytest
import threading
import importlib


# ── helpers ────────────────────────────────────────────────────────────────────

def _fresh_notifications():
    """Re-import notifications module with a clean list each time."""
    import tools.notifications as n
    # Reset internal list between tests
    import tools.notifications as mod
    mod._notifications.clear()
    return mod


# ── tools/notifications: add & get ────────────────────────────────────────────

def test_add_notification_stores_entry():
    mod = _fresh_notifications()
    nid = mod.add_notification("stale_test", "foo.ts stale", workspace="/proj", severity="info")
    entries = mod.get_notifications()
    assert len(entries) == 1
    assert entries[0]["id"] == nid
    assert entries[0]["type"] == "stale_test"
    assert entries[0]["message"] == "foo.ts stale"
    assert entries[0]["severity"] == "info"


def test_get_notifications_filters_by_workspace():
    mod = _fresh_notifications()
    mod.add_notification("stale_test", "for proj A", workspace="/projA")
    mod.add_notification("long_branch", "for proj B", workspace="/projB")
    assert len(mod.get_notifications(workspace="/projA")) == 1
    assert len(mod.get_notifications(workspace="/projB")) == 1
    assert len(mod.get_notifications()) == 2


def test_get_notifications_empty_workspace_shows_all():
    """Notifications with no workspace are shown everywhere."""
    mod = _fresh_notifications()
    mod.add_notification("x", "global msg", workspace="")
    assert len(mod.get_notifications(workspace="/any/path")) == 1


def test_dismiss_notification_removes_by_id():
    mod = _fresh_notifications()
    nid = mod.add_notification("many_uncommitted", "12 files", workspace="/p")
    assert mod.dismiss_notification(nid) is True
    assert mod.get_notifications() == []


def test_dismiss_notification_returns_false_for_unknown():
    mod = _fresh_notifications()
    assert mod.dismiss_notification("notif_doesnotexist") is False


def test_dismiss_all_removes_all():
    mod = _fresh_notifications()
    mod.add_notification("t", "a", workspace="/p")
    mod.add_notification("t", "b", workspace="/p")
    count = mod.dismiss_all()
    assert count == 2
    assert mod.get_notifications() == []


def test_dismiss_all_scoped_to_workspace():
    mod = _fresh_notifications()
    mod.add_notification("t", "a", workspace="/p1")
    mod.add_notification("t", "b", workspace="/p2")
    mod.dismiss_all(workspace="/p1")
    remaining = mod.get_notifications()
    assert len(remaining) == 1
    assert remaining[0]["workspace"] == "/p2"


# ── tools/watcher: stale test detector ────────────────────────────────────────

def test_stale_test_detector_fires_notification(tmp_path):
    """Source file updated 2 days ago, spec file updated 4 days ago → notification."""
    import tools.notifications as notif_mod
    notif_mod._notifications.clear()

    import tools.watcher as watcher
    watcher._notified_keys.clear()

    now = time.time()
    # Create source and spec files
    src = tmp_path / "auth.service.ts"
    spec = tmp_path / "auth.service.spec.ts"
    src.write_text("export class AuthService {}")
    spec.write_text("describe('AuthService', () => {});")

    # Set mtimes: src modified 1 day ago, spec modified 4 days ago
    src_mtime = now - 86400      # 1 day ago (within 48h threshold)
    spec_mtime = now - (4 * 86400)  # 4 days ago (gap > 24h threshold)
    os.utime(src, (src_mtime, src_mtime))
    os.utime(spec, (spec_mtime, spec_mtime))

    watcher._check_stale_tests(str(tmp_path))

    notifications = notif_mod.get_notifications()
    assert len(notifications) == 1
    assert "auth.service.ts" in notifications[0]["message"]
    assert notifications[0]["type"] == "stale_test"


def test_stale_test_detector_skips_up_to_date(tmp_path):
    """Source and spec both updated recently → no notification."""
    import tools.notifications as notif_mod
    notif_mod._notifications.clear()

    import tools.watcher as watcher
    watcher._notified_keys.clear()

    now = time.time()
    src = tmp_path / "app.component.ts"
    spec = tmp_path / "app.component.spec.ts"
    src.write_text("// src")
    spec.write_text("// spec")

    # Both modified 1 hour ago — gap is 0
    ts = now - 3600
    os.utime(src, (ts, ts))
    os.utime(spec, (ts, ts))

    watcher._check_stale_tests(str(tmp_path))
    assert notif_mod.get_notifications() == []


def test_stale_test_detector_skips_old_source(tmp_path):
    """Source modified 3 days ago (beyond 48h window) → no notification."""
    import tools.notifications as notif_mod
    notif_mod._notifications.clear()

    import tools.watcher as watcher
    watcher._notified_keys.clear()

    now = time.time()
    src = tmp_path / "foo.ts"
    spec = tmp_path / "foo.spec.ts"
    src.write_text("// src")
    spec.write_text("// spec")

    src_mtime = now - (3 * 86400)    # 3 days ago — outside 48h window
    spec_mtime = now - (5 * 86400)   # 5 days ago
    os.utime(src, (src_mtime, src_mtime))
    os.utime(spec, (spec_mtime, spec_mtime))

    watcher._check_stale_tests(str(tmp_path))
    assert notif_mod.get_notifications() == []


# ── tools/watcher: _get_spec_names ────────────────────────────────────────────

def test_get_spec_names_typescript():
    from tools.watcher import _get_spec_names
    names = _get_spec_names("auth.service.ts")
    assert "auth.service.spec.ts" in names
    assert "auth.service.test.ts" in names
    names2 = _get_spec_names("app.component.ts")
    assert "app.component.spec.ts" in names2


def test_get_spec_names_skips_spec_and_declaration():
    from tools.watcher import _get_spec_names
    assert _get_spec_names("auth.service.spec.ts") == []
    assert _get_spec_names("auth.service.test.ts") == []
    assert _get_spec_names("types.d.ts") == []


def test_get_spec_names_csharp():
    from tools.watcher import _get_spec_names
    names = _get_spec_names("AuthService.cs")
    assert "AuthServiceTests.cs" in names
    assert "AuthService.Test.cs" in names


def test_get_spec_names_skips_test_files():
    from tools.watcher import _get_spec_names
    assert _get_spec_names("AuthServiceTests.cs") == []
    assert _get_spec_names("LoginSpec.cs") == []


def test_get_spec_names_unknown_ext():
    from tools.watcher import _get_spec_names
    assert _get_spec_names("README.md") == []
    assert _get_spec_names("styles.css") == []


# ── tools/watcher: run_checks_once on non-existent path ───────────────────────

def test_run_checks_once_ignores_missing_dir():
    """Should not raise for a path that doesn't exist."""
    from tools.watcher import run_checks_once
    run_checks_once("/path/that/does/not/exist/at/all")  # must not raise


# ── server: /notifications GET ─────────────────────────────────────────────────

@pytest.fixture()
def test_server():
    """Start a JarvisHTTPServer on a free port for request tests."""
    import server as srv
    import tools.notifications as notif_mod
    notif_mod._notifications.clear()

    httpd = srv.JarvisHTTPServer(('127.0.0.1', 0), srv.JarvisHTTPHandler)
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.handle_request, daemon=True)
    t.start()
    yield httpd, port
    httpd.server_close()


def _get(port, path):
    import urllib.request
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}") as r:
        return r.status, json.loads(r.read())


def _post_json(port, path, body):
    import urllib.request
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req) as r:
        return r.status, json.loads(r.read())


def test_notifications_get_endpoint_returns_list():
    """GET /notifications returns {notifications: [...]}."""
    import tools.notifications as notif_mod
    notif_mod._notifications.clear()
    notif_mod.add_notification("stale_test", "some file stale")

    import server as srv
    httpd = srv.JarvisHTTPServer(('127.0.0.1', 0), srv.JarvisHTTPHandler)
    port = httpd.server_address[1]

    def handle():
        httpd.handle_request()

    t = threading.Thread(target=handle, daemon=True)
    t.start()

    status, data = _get(port, "/notifications")
    httpd.server_close()

    assert status == 200
    assert "notifications" in data
    assert len(data["notifications"]) == 1
    assert data["notifications"][0]["type"] == "stale_test"


def test_notifications_dismiss_endpoint():
    """POST /notifications/dismiss removes a notification by id."""
    import tools.notifications as notif_mod
    notif_mod._notifications.clear()
    nid = notif_mod.add_notification("long_branch", "old branch")

    import server as srv
    httpd = srv.JarvisHTTPServer(('127.0.0.1', 0), srv.JarvisHTTPHandler)
    port = httpd.server_address[1]

    # Need two handle_request calls: POST then GET
    calls = []

    def handle():
        for _ in range(2):
            httpd.handle_request()

    t = threading.Thread(target=handle, daemon=True)
    t.start()

    status, data = _post_json(port, "/notifications/dismiss", {"id": nid})
    assert status == 200
    assert data.get("dismissed") is True

    status2, data2 = _get(port, "/notifications")
    httpd.server_close()

    assert data2["notifications"] == []
