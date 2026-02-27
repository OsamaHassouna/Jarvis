# tests/test_phase10.py
# Phase 10 — Session persistence tests.
# Run with: pytest tests/test_phase10.py -v

import os
import sys
import json
import shutil
import tempfile
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import tools.sessions as sess


class SessionsTest:
    """Base class: redirects sessions_dir() to a temp directory."""

    def setup_method(self, _):
        self.tmpdir = tempfile.mkdtemp()
        # Point MEMORY_FILE into tmpdir so sessions_dir() picks it up
        self._orig_memory_file = config.MEMORY_FILE
        config.MEMORY_FILE = os.path.join(self.tmpdir, "memory.json")
        # Reload the module-level _JARVIS_ROOT in sessions.py
        sess._JARVIS_ROOT = os.path.dirname(os.path.abspath(config.MEMORY_FILE))

    def teardown_method(self, _):
        config.MEMORY_FILE = self._orig_memory_file
        sess._JARVIS_ROOT = os.path.dirname(os.path.abspath(config.MEMORY_FILE))
        shutil.rmtree(self.tmpdir, ignore_errors=True)


# ─────────────────────────────────────────────────────────────────────────────
class TestUtilities(SessionsTest):

    def test_workspace_hash_is_stable(self):
        root = "D:/Projects/MyApp"
        assert sess.workspace_hash(root) == sess.workspace_hash(root)

    def test_workspace_hash_case_insensitive(self):
        assert sess.workspace_hash("D:/Projects/App") == sess.workspace_hash("d:/projects/app")

    def test_generate_session_id_format(self):
        sid = sess.generate_session_id()
        assert sid.startswith("sess_")
        assert len(sid) >= 10


# ─────────────────────────────────────────────────────────────────────────────
class TestCreateSession(SessionsTest):

    def test_project_session_creates_file(self):
        workspace = self.tmpdir + "/MyApp"
        session = sess.create_session(workspace, is_global=False)
        path = sess._session_path(session["id"], workspace, False)
        assert os.path.isfile(path)

    def test_global_session_creates_file(self):
        session = sess.create_session("", is_global=True)
        path = sess._session_path(session["id"], "", True)
        assert os.path.isfile(path)

    def test_returns_expected_shape(self):
        session = sess.create_session(self.tmpdir + "/Proj", is_global=False)
        for key in ("id", "name", "messages", "is_global", "created_at", "token_total"):
            assert key in session

    def test_messages_empty(self):
        session = sess.create_session(self.tmpdir + "/Proj", is_global=False)
        assert session["messages"] == []


# ─────────────────────────────────────────────────────────────────────────────
class TestAppendMessage(SessionsTest):

    def _new(self):
        workspace = self.tmpdir + "/Proj"
        return sess.create_session(workspace, is_global=False), workspace

    def test_appends_user_message(self):
        session, workspace = self._new()
        sess.append_message(session["id"], workspace, False, "user", "hello")
        updated = sess.get_session(session["id"], workspace, False)
        assert len(updated["messages"]) == 1
        assert updated["messages"][0]["role"] == "user"
        assert updated["messages"][0]["content"] == "hello"

    def test_increments_token_total(self):
        session, workspace = self._new()
        sess.append_message(session["id"], workspace, False, "user", "hi", token_count=100)
        updated = sess.get_session(session["id"], workspace, False)
        assert updated["token_total"] == 100

    def test_updates_timestamp(self):
        session, workspace = self._new()
        old_ts = session["updated_at"]
        import time; time.sleep(1)
        sess.append_message(session["id"], workspace, False, "assistant", "reply")
        updated = sess.get_session(session["id"], workspace, False)
        assert updated["updated_at"] >= old_ts


# ─────────────────────────────────────────────────────────────────────────────
class TestSessionNaming(SessionsTest):

    def test_auto_name_truncates(self):
        long_content = "x" * 100
        name = sess.auto_name_from_first_message(long_content)
        assert len(name) <= 50

    def test_update_name_persists(self):
        workspace = self.tmpdir + "/Proj"
        session = sess.create_session(workspace, is_global=False)
        sess.update_session_name(session["id"], workspace, False, "My Test Session")
        updated = sess.get_session(session["id"], workspace, False)
        assert updated["name"] == "My Test Session"


# ─────────────────────────────────────────────────────────────────────────────
class TestActiveSessions(SessionsTest):

    def test_set_get_active_project(self):
        workspace = self.tmpdir + "/Proj"
        session = sess.create_session(workspace, is_global=False)
        sess.set_active_session(session["id"], workspace, False)
        assert sess.get_active_session_id(workspace, False) == session["id"]

    def test_set_get_active_global(self):
        session = sess.create_session("", is_global=True)
        sess.set_active_session(session["id"], "", True)
        assert sess.get_active_session_id("", True) == session["id"]


# ─────────────────────────────────────────────────────────────────────────────
class TestListSessions(SessionsTest):

    def test_list_project_sessions_empty(self):
        workspace = self.tmpdir + "/NewProj"
        assert sess.list_project_sessions(workspace) == []

    def test_list_project_sessions_returns_created(self):
        workspace = self.tmpdir + "/Proj"
        sess.create_session(workspace, is_global=False)
        sess.create_session(workspace, is_global=False)
        result = sess.list_project_sessions(workspace)
        assert len(result) == 2

    def test_list_all_sessions_structure(self):
        workspace = self.tmpdir + "/Proj"
        sess.create_session(workspace, is_global=False)
        sess.create_session("", is_global=True)
        result = sess.list_all_sessions()
        assert "global" in result
        assert "projects" in result
        assert len(result["global"]) == 1
        assert len(result["projects"]) == 1


# ─────────────────────────────────────────────────────────────────────────────
class TestProjectSummary(SessionsTest):

    def test_text_empty_no_file(self):
        workspace = self.tmpdir + "/Proj"
        assert sess.get_project_summary_text(workspace) == ""

    def test_text_returns_cumulative(self):
        workspace = self.tmpdir + "/Proj"
        summary_path = sess._project_summary_path(workspace)
        os.makedirs(os.path.dirname(summary_path), exist_ok=True)
        with open(summary_path, "w") as f:
            json.dump({"cumulative_summary": "Angular app for tasks."}, f)
        assert sess.get_project_summary_text(workspace) == "Angular app for tasks."

    def test_update_project_summary_creates_file(self):
        workspace = self.tmpdir + "/Proj"
        fake_session = {
            "id": "sess_test01",
            "name": "Test Session",
            "summary": "Fixed a bug.",
            "created_at": "2026-02-27T14:00:00",
            "updated_at": "2026-02-27T15:00:00",
        }
        mock_resp = MagicMock()
        mock_resp.content = [MagicMock(text="Updated project summary.")]
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_resp

        with patch("anthropic.Anthropic", return_value=mock_client):
            sess.update_project_summary(workspace, fake_session)

        summary_path = sess._project_summary_path(workspace)
        assert os.path.isfile(summary_path)
        data = json.load(open(summary_path))
        assert len(data["sessions"]) == 1
        assert data["sessions"][0]["id"] == "sess_test01"


# ─────────────────────────────────────────────────────────────────────────────
class TestCloseSession(SessionsTest):

    def test_close_session_stores_summary(self):
        workspace = self.tmpdir + "/Proj"
        session = sess.create_session(workspace, is_global=False)
        sess.append_message(session["id"], workspace, False, "user", "How do I fix CORS?")
        sess.append_message(session["id"], workspace, False, "assistant", "Add the CORS headers.")

        mock_resp = MagicMock()
        mock_resp.content = [MagicMock(text="User asked about CORS. Jarvis explained headers.")]
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_resp

        with patch("anthropic.Anthropic", return_value=mock_client):
            summary = sess.close_session(session["id"], workspace, False)

        assert summary != ""
        updated = sess.get_session(session["id"], workspace, False)
        assert updated["summary"] != ""
