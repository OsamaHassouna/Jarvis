"""
tests/test_phase17.py — Phase 17: Persistence & History

Tests for:
  A. Notification persistence (tools/notifications.py)
  B. Agent job history (tools/agent_jobs.py)
  C. /agents/history server endpoint
"""

import json
import os
import threading
import time
import tempfile
import importlib
import pytest

# ── helpers ───────────────────────────────────────────────────────────────────

def _reload_notifications(tmp_path):
    """Import a fresh notifications module pointed at a temp file."""
    import tools.notifications as mod
    mod._notifications = []
    mod._NOTIFICATIONS_FILE = str(tmp_path / "notifications.json")
    return mod


def _reload_agent_jobs(tmp_path):
    """Import a fresh agent_jobs module pointed at a temp file."""
    import tools.agent_jobs as mod
    mod._jobs = {}
    mod._HISTORY_FILE = str(tmp_path / "agent_jobs_history.json")
    return mod


# ═══════════════════════════════════════════════════════════════════
# A. Notification persistence
# ═══════════════════════════════════════════════════════════════════

class TestNotificationPersistence:
    def test_add_notification_saves_to_disk(self, tmp_path):
        mod = _reload_notifications(tmp_path)
        mod.add_notification("test", "hello", severity="info")
        assert os.path.exists(mod._NOTIFICATIONS_FILE)
        with open(mod._NOTIFICATIONS_FILE) as f:
            data = json.load(f)
        assert len(data) == 1
        assert data[0]["message"] == "hello"

    def test_dismiss_notification_saves_to_disk(self, tmp_path):
        mod = _reload_notifications(tmp_path)
        nid = mod.add_notification("test", "msg1")
        mod.add_notification("test", "msg2")
        mod.dismiss_notification(nid)
        with open(mod._NOTIFICATIONS_FILE) as f:
            data = json.load(f)
        assert len(data) == 1
        assert data[0]["message"] == "msg2"

    def test_dismiss_all_saves_to_disk(self, tmp_path):
        mod = _reload_notifications(tmp_path)
        mod.add_notification("t", "a")
        mod.add_notification("t", "b")
        mod.dismiss_all()
        with open(mod._NOTIFICATIONS_FILE) as f:
            data = json.load(f)
        assert data == []

    def test_load_notifications_restores_from_disk(self, tmp_path):
        mod = _reload_notifications(tmp_path)
        mod.add_notification("test", "persisted")
        # Wipe in-memory list, then reload
        mod._notifications = []
        mod.load_notifications()
        result = mod.get_notifications()
        assert any(n["message"] == "persisted" for n in result)

    def test_load_notifications_drops_old_entries(self, tmp_path):
        mod = _reload_notifications(tmp_path)
        # Write a stale notification directly to disk
        stale = [{
            "id": "notif_stale",
            "type": "test",
            "message": "old",
            "workspace": "",
            "severity": "info",
            "created_at": time.time() - 8 * 24 * 3600,  # 8 days ago
        }]
        os.makedirs(tmp_path, exist_ok=True)
        with open(mod._NOTIFICATIONS_FILE, "w") as f:
            json.dump(stale, f)
        mod.load_notifications()
        result = mod.get_notifications()
        assert not any(n["id"] == "notif_stale" for n in result)

    def test_get_notifications_auto_expires(self, tmp_path):
        mod = _reload_notifications(tmp_path)
        # Manually inject an old notification into in-memory list
        mod._notifications = [{
            "id": "notif_old",
            "type": "test",
            "message": "expired",
            "workspace": "",
            "severity": "info",
            "created_at": time.time() - 8 * 24 * 3600,
        }]
        result = mod.get_notifications()
        assert not any(n["id"] == "notif_old" for n in result)
        # In-memory list should also be cleaned up
        assert not any(n["id"] == "notif_old" for n in mod._notifications)

    def test_cap_at_twenty_notifications(self, tmp_path):
        mod = _reload_notifications(tmp_path)
        for i in range(25):
            mod.add_notification("test", f"msg{i}")
        with open(mod._NOTIFICATIONS_FILE) as f:
            data = json.load(f)
        assert len(data) <= 20


# ═══════════════════════════════════════════════════════════════════
# B. Agent job history
# ═══════════════════════════════════════════════════════════════════

class TestAgentJobHistory:
    def test_task_stored_in_job(self, tmp_path):
        mod = _reload_agent_jobs(tmp_path)
        job = mod.create_job("job_001", "/ws", task="fix the login bug")
        assert job["task"] == "fix the login bug"

    def test_completed_job_written_to_history_file(self, tmp_path):
        mod = _reload_agent_jobs(tmp_path)
        mod.create_job("job_001", "/ws", task="add tests")
        mod.update_job_status("job_001", "done", summary={"succeeded": 1, "failed": 0, "skipped": 0})
        assert os.path.exists(mod._HISTORY_FILE)
        with open(mod._HISTORY_FILE) as f:
            history = json.load(f)
        assert len(history) == 1
        assert history[0]["job_id"] == "job_001"
        assert history[0]["outcome"] == "success"
        assert history[0]["task"] == "add tests"

    def test_failed_job_written_to_history_file(self, tmp_path):
        mod = _reload_agent_jobs(tmp_path)
        mod.create_job("job_002", "/ws", task="deploy")
        mod.update_job_status("job_002", "failed", error="timeout")
        with open(mod._HISTORY_FILE) as f:
            history = json.load(f)
        assert history[0]["outcome"] == "failed"

    def test_history_includes_agent_list(self, tmp_path):
        mod = _reload_agent_jobs(tmp_path)
        mod.create_job("job_003", "/ws", task="refactor")
        mod.register_agents("job_003", [
            {"id": "a1", "task": "update routes", "depends_on": []},
            {"id": "a2", "task": "update tests", "depends_on": ["a1"]},
        ])
        mod.update_job_status("job_003", "done")
        with open(mod._HISTORY_FILE) as f:
            history = json.load(f)
        agents = history[0]["agents"]
        assert len(agents) == 2

    def test_list_job_history_returns_newest_first(self, tmp_path):
        mod = _reload_agent_jobs(tmp_path)
        for i in range(3):
            jid = f"job_{i:03d}"
            mod.create_job(jid, "/ws", task=f"task{i}")
            mod.update_job_status(jid, "done")
            time.sleep(0.01)
        history = mod.list_job_history()
        assert history[0]["job_id"] == "job_002"  # newest first

    def test_history_trimmed_to_max(self, tmp_path):
        mod = _reload_agent_jobs(tmp_path)
        mod._MAX_HISTORY = 5
        for i in range(8):
            jid = f"job_{i:03d}"
            mod.create_job(jid, "/ws", task=f"task{i}")
            mod.update_job_status(jid, "done")
        with open(mod._HISTORY_FILE) as f:
            history = json.load(f)
        assert len(history) <= 5

    def test_list_job_history_empty_when_no_file(self, tmp_path):
        mod = _reload_agent_jobs(tmp_path)
        result = mod.list_job_history()
        assert result == []


# ═══════════════════════════════════════════════════════════════════
# C. /agents/history endpoint
# ═══════════════════════════════════════════════════════════════════

def _start_server_once():
    """Start a server that handles exactly one request (avoids watcher side effects)."""
    import server as srv
    httpd = srv.JarvisHTTPServer(('127.0.0.1', 0), srv.JarvisHTTPHandler)
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.handle_request, daemon=True)
    t.start()
    return httpd, port


def _get(port, path):
    import urllib.request
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}") as r:
        return r.status, json.loads(r.read())


class TestAgentsHistoryEndpoint:
    def test_agents_history_returns_empty_list(self, tmp_path):
        import tools.agent_jobs as aj
        aj._HISTORY_FILE = str(tmp_path / "agent_jobs_history.json")
        httpd, port = _start_server_once()
        try:
            status, data = _get(port, "/agents/history")
            assert status == 200
            assert "jobs" in data
            assert data["jobs"] == []
        finally:
            httpd.server_close()

    def test_agents_history_returns_completed_jobs(self, tmp_path):
        import tools.agent_jobs as aj
        aj._jobs = {}
        aj._HISTORY_FILE = str(tmp_path / "agent_jobs_history.json")
        aj.create_job("job_hist", "/ws", task="the task")
        aj.update_job_status("job_hist", "done")

        httpd, port = _start_server_once()
        try:
            status, data = _get(port, "/agents/history")
            assert status == 200
            assert len(data["jobs"]) >= 1
            assert data["jobs"][0]["task"] == "the task"
        finally:
            httpd.server_close()
