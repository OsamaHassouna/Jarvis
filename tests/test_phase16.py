"""
tests/test_phase16.py — Phase 16: Smart Context Management.

Tests:
  - tools/sessions.py  (compression trigger, summary block, compressed_count)
  - orchestrator.py    (scan_workspace_files caching, build_vscode_system_prompt summary rendering)
  - server.py          (/status with session params, /chat session_token_total field)
"""
import os
import sys
import json
import shutil
import tempfile
import threading
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import tools.sessions as sess
from tools.sessions import _COMPRESSION_THRESHOLD, _COMPRESSION_BATCH


# ── Base fixture ─────────────────────────────────────────────────────────────

class SessionsTest:
    """Base: redirects sessions_dir() to a temp directory."""

    def setup_method(self, _):
        self.tmpdir = tempfile.mkdtemp()
        self._orig_memory_file = config.MEMORY_FILE
        config.MEMORY_FILE = os.path.join(self.tmpdir, "memory.json")
        sess._JARVIS_ROOT = os.path.dirname(os.path.abspath(config.MEMORY_FILE))

    def teardown_method(self, _):
        config.MEMORY_FILE = self._orig_memory_file
        sess._JARVIS_ROOT = os.path.dirname(os.path.abspath(config.MEMORY_FILE))
        shutil.rmtree(self.tmpdir, ignore_errors=True)


# ── A. Session compression ────────────────────────────────────────────────────

class TestSessionCompression(SessionsTest):

    def _make_session_with_n_messages(self, n: int):
        """Create a session and fill it with n messages (no Haiku calls)."""
        workspace = self.tmpdir + "/TestApp"
        session = sess.create_session(workspace, is_global=False)
        sid = session["id"]
        # Add messages directly to avoid triggering real compression
        session["messages"] = [
            {"role": "user" if i % 2 == 0 else "assistant",
             "content": f"message {i}", "ts": "2026-01-01T00:00:00"}
            for i in range(n)
        ]
        sess.save_session(session)
        return sid, workspace

    def test_no_compression_below_threshold(self):
        """Sessions under 80 messages are never compressed."""
        sid, workspace = self._make_session_with_n_messages(_COMPRESSION_THRESHOLD - 1)
        with patch("tools.sessions._summarize_for_compression") as mock_summary:
            sess.append_message(sid, workspace, False, "user", "new message")
        mock_summary.assert_not_called()
        updated = sess.get_session(sid, workspace, False)
        assert "compressed_count" not in updated or updated.get("compressed_count", 0) == 0

    def test_compression_triggers_at_threshold(self):
        """Adding a message that pushes count to 81 triggers compression of oldest 40."""
        sid, workspace = self._make_session_with_n_messages(_COMPRESSION_THRESHOLD)
        with patch("tools.sessions._summarize_for_compression", return_value="Earlier context summary."):
            sess.append_message(sid, workspace, False, "user", "new message")
        updated = sess.get_session(sid, workspace, False)
        # After compression: 1 summary + (81 - 40) = 42 messages
        assert updated["messages"][0]["role"] == "summary"
        assert updated["messages"][0]["content"] == "Earlier context summary."
        assert updated["messages"][0]["compressed_count"] == _COMPRESSION_BATCH

    def test_compressed_count_tracked_on_session(self):
        """session.compressed_count is updated after compression."""
        sid, workspace = self._make_session_with_n_messages(_COMPRESSION_THRESHOLD)
        with patch("tools.sessions._summarize_for_compression", return_value="summary"):
            sess.append_message(sid, workspace, False, "user", "trigger")
        updated = sess.get_session(sid, workspace, False)
        assert updated.get("compressed_count") == _COMPRESSION_BATCH

    def test_compression_fallback_when_haiku_fails(self):
        """When Haiku returns empty string, a fallback text is stored."""
        sid, workspace = self._make_session_with_n_messages(_COMPRESSION_THRESHOLD)
        with patch("tools.sessions._summarize_for_compression", return_value=""):
            sess.append_message(sid, workspace, False, "user", "trigger")
        updated = sess.get_session(sid, workspace, False)
        assert updated["messages"][0]["role"] == "summary"
        assert "unavailable" in updated["messages"][0]["content"].lower() or \
               str(_COMPRESSION_BATCH) in updated["messages"][0]["content"]

    def test_message_count_after_compression(self):
        """After compression, message count = 1 summary + (threshold + 1 - batch) remaining."""
        n = _COMPRESSION_THRESHOLD
        sid, workspace = self._make_session_with_n_messages(n)
        with patch("tools.sessions._summarize_for_compression", return_value="summary"):
            sess.append_message(sid, workspace, False, "user", "new")
        updated = sess.get_session(sid, workspace, False)
        expected = 1 + (n + 1 - _COMPRESSION_BATCH)
        assert len(updated["messages"]) == expected

    def test_token_total_still_tracked_after_compression(self):
        """token_total accumulates even when compression fires."""
        sid, workspace = self._make_session_with_n_messages(_COMPRESSION_THRESHOLD)
        with patch("tools.sessions._summarize_for_compression", return_value="summary"):
            sess.append_message(sid, workspace, False, "assistant", "reply", token_count=500)
        updated = sess.get_session(sid, workspace, False)
        assert updated["token_total"] == 500


# ── B. Workspace scan cache ───────────────────────────────────────────────────

class TestWorkspaceScanCache:

    def setup_method(self, _):
        self.tmpdir = tempfile.mkdtemp()
        # Clear the module-level cache before each test
        import orchestrator
        orchestrator._scan_cache.clear()
        self.orch = orchestrator

    def teardown_method(self, _):
        shutil.rmtree(self.tmpdir, ignore_errors=True)
        self.orch._scan_cache.clear()

    def test_scan_returns_result_for_valid_dir(self):
        result = self.orch.scan_workspace_files(self.tmpdir)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_scan_empty_for_nonexistent_dir(self):
        result = self.orch.scan_workspace_files("/this/does/not/exist/12345")
        assert result == ""

    def test_second_call_hits_cache(self):
        """Second call to same path should use cached result (no re-walk)."""
        self.orch.scan_workspace_files(self.tmpdir)
        assert self.tmpdir in self.orch._scan_cache
        cached_result = self.orch._scan_cache[self.tmpdir]["result"]
        # Patch os.scandir to verify it's NOT called on second call
        with patch("os.scandir") as mock_scan:
            result = self.orch.scan_workspace_files(self.tmpdir)
        mock_scan.assert_not_called()
        assert result == cached_result

    def test_cache_invalidated_on_mtime_change(self):
        """When directory mtime changes, the scan runs again."""
        self.orch.scan_workspace_files(self.tmpdir)
        cached = self.orch._scan_cache[self.tmpdir]
        # Force a different mtime in cache to simulate staleness
        self.orch._scan_cache[self.tmpdir]["mtime"] = cached["mtime"] - 1.0
        # Next call should re-scan
        with patch("os.scandir", wraps=os.scandir) as mock_scan:
            self.orch.scan_workspace_files(self.tmpdir)
        mock_scan.assert_called()


# ── C. build_vscode_system_prompt — summary block rendering ──────────────────

class TestBuildVscodeSystemPromptSummary:

    def _make_memory(self):
        return {
            "user": {"name": "Osama", "experience_level": "senior",
                     "preferences": {}, "rules": []},
            "projects": [],
            "history": [],
            "task_ratings": [],
        }

    def test_summary_block_rendered_as_earlier_context(self):
        """role=summary messages appear as [Earlier context...] in the prompt."""
        from orchestrator import build_vscode_system_prompt
        messages = [
            {"role": "summary", "content": "User discussed auth refactoring.", "compressed_count": 40},
            {"role": "user", "content": "What's next?"},
            {"role": "assistant", "content": "Add the new endpoint."},
        ]
        with patch("orchestrator.load_memory", return_value=self._make_memory()), \
             patch("orchestrator.get_project_summary_text", return_value=""), \
             patch("orchestrator.list_project_sessions", return_value=[]), \
             patch("orchestrator.get_project_rules", return_value=[]):
            prompt = build_vscode_system_prompt("/proj", False, messages)
        assert "[Earlier context (40 messages):" in prompt
        assert "auth refactoring" in prompt

    def test_regular_messages_still_rendered_after_summary(self):
        """Regular messages after a summary block still appear in the prompt."""
        from orchestrator import build_vscode_system_prompt
        messages = [
            {"role": "summary", "content": "Earlier summary.", "compressed_count": 40},
            {"role": "user", "content": "Show me the login component."},
            {"role": "assistant", "content": "Here it is."},
        ]
        with patch("orchestrator.load_memory", return_value=self._make_memory()), \
             patch("orchestrator.get_project_summary_text", return_value=""), \
             patch("orchestrator.list_project_sessions", return_value=[]), \
             patch("orchestrator.get_project_rules", return_value=[]):
            prompt = build_vscode_system_prompt("/proj", False, messages)
        assert "login component" in prompt

    def test_no_summary_blocks_unchanged_behavior(self):
        """Without any summary blocks, history renders the same as before."""
        from orchestrator import build_vscode_system_prompt
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
        ]
        with patch("orchestrator.load_memory", return_value=self._make_memory()), \
             patch("orchestrator.get_project_summary_text", return_value=""), \
             patch("orchestrator.list_project_sessions", return_value=[]), \
             patch("orchestrator.get_project_rules", return_value=[]):
            prompt = build_vscode_system_prompt("/proj", False, messages)
        assert "Hello" in prompt
        assert "Hi there" in prompt


# ── D. Server endpoints ───────────────────────────────────────────────────────

def _start_server():
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


def test_status_endpoint_includes_version_phase16():
    """/status returns version=phase16."""
    httpd, port = _start_server()
    try:
        status, data = _get(port, "/status")
        assert status == 200
        assert data.get("version") == "phase16"
    finally:
        httpd.server_close()


def test_status_endpoint_with_session_params_returns_token_data():
    """/status?session_id=...&workspace_root=... returns session token info."""
    import tools.sessions as s
    import config

    tmp = tempfile.mkdtemp()
    orig = config.MEMORY_FILE
    config.MEMORY_FILE = os.path.join(tmp, "memory.json")
    s._JARVIS_ROOT = os.path.dirname(os.path.abspath(config.MEMORY_FILE))

    try:
        workspace = tmp + "/Proj"
        session = s.create_session(workspace, is_global=False)
        # Give it some tokens
        session["token_total"] = 1234
        session["compressed_count"] = 40
        s.save_session(session)

        import server as srv
        httpd = srv.JarvisHTTPServer(('127.0.0.1', 0), srv.JarvisHTTPHandler)
        port = httpd.server_address[1]
        t = threading.Thread(target=httpd.handle_request, daemon=True)
        t.start()

        import urllib.parse
        params = urllib.parse.urlencode({
            "session_id": session["id"],
            "workspace_root": workspace,
            "is_global": "0",
        })
        status, data = _get(port, f"/status?{params}")
        httpd.server_close()

        assert status == 200
        assert data.get("session_tokens_used") == 1234
        assert data.get("session_compressed_count") == 40
    finally:
        config.MEMORY_FILE = orig
        s._JARVIS_ROOT = os.path.dirname(os.path.abspath(orig))
        shutil.rmtree(tmp, ignore_errors=True)
