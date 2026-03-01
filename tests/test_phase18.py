"""
tests/test_phase18.py — Phase 18: Session Intelligence

Tests for:
  A. search_sessions() in tools/sessions.py
  B. export_session_markdown() in tools/sessions.py
  C. /sessions/search and /sessions/export server endpoints
"""

import json
import os
import threading
import tempfile
import pytest

import tools.sessions as sessions_mod


# ── helpers ───────────────────────────────────────────────────────────────────

def _setup_sessions_dir(tmp_path):
    """Redirect the sessions module to use a temp directory."""
    sessions_mod._JARVIS_ROOT = str(tmp_path)
    # Clear any cached state
    return sessions_mod


def _make_session(tmp_path, *, name="", summary="", messages=None, is_global=False, workspace=""):
    """Create a real session file in the temp sessions dir."""
    _setup_sessions_dir(tmp_path)
    sess = sessions_mod.create_session(workspace, is_global=is_global)
    if name:
        sess["name"] = name
    if summary:
        sess["summary"] = summary
    if messages:
        sess["messages"] = messages
    sessions_mod.save_session(sess)
    return sess


def _start_server_once():
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


# ═══════════════════════════════════════════════════════════════════
# A. search_sessions()
# ═══════════════════════════════════════════════════════════════════

class TestSearchSessions:
    def test_search_matches_session_name(self, tmp_path):
        _setup_sessions_dir(tmp_path)
        _make_session(tmp_path, name="CORS auth refactor", is_global=True)
        results = sessions_mod.search_sessions("cors", "")
        assert len(results) == 1
        assert results[0]["match_field"] == "name"

    def test_search_matches_session_summary(self, tmp_path):
        _setup_sessions_dir(tmp_path)
        _make_session(tmp_path, name="random", summary="Fixed the login redirect bug", is_global=True)
        results = sessions_mod.search_sessions("redirect", "")
        assert len(results) == 1
        assert results[0]["match_field"] == "summary"

    def test_search_matches_message_content(self, tmp_path):
        _setup_sessions_dir(tmp_path)
        msgs = [
            {"role": "user", "content": "How do I configure OAuth2?", "ts": "2026-01-01T00:00:00"},
            {"role": "assistant", "content": "You need to set up the provider", "ts": "2026-01-01T00:01:00"},
        ]
        _make_session(tmp_path, name="no match here", messages=msgs, is_global=True)
        results = sessions_mod.search_sessions("oauth2", "")
        assert len(results) == 1
        assert results[0]["match_field"] == "message"

    def test_search_returns_snippet(self, tmp_path):
        _setup_sessions_dir(tmp_path)
        _make_session(tmp_path, summary="Database migration for users table", is_global=True)
        results = sessions_mod.search_sessions("migration", "")
        assert len(results) == 1
        assert results[0]["snippet"]

    def test_search_empty_query_returns_empty_list(self, tmp_path):
        _setup_sessions_dir(tmp_path)
        _make_session(tmp_path, name="something", is_global=True)
        results = sessions_mod.search_sessions("", "")
        assert results == []

    def test_search_no_matches_returns_empty_list(self, tmp_path):
        _setup_sessions_dir(tmp_path)
        _make_session(tmp_path, name="totally unrelated", is_global=True)
        results = sessions_mod.search_sessions("zzznomatch999", "")
        assert results == []

    def test_search_case_insensitive(self, tmp_path):
        _setup_sessions_dir(tmp_path)
        _make_session(tmp_path, name="Fix the WEBPACK config", is_global=True)
        results = sessions_mod.search_sessions("webpack", "")
        assert len(results) == 1


# ═══════════════════════════════════════════════════════════════════
# B. export_session_markdown()
# ═══════════════════════════════════════════════════════════════════

class TestExportSessionMarkdown:
    def test_export_includes_session_title(self, tmp_path):
        _setup_sessions_dir(tmp_path)
        sess = _make_session(tmp_path, name="My Test Session", is_global=True)
        md = sessions_mod.export_session_markdown(sess)
        assert "# My Test Session" in md

    def test_export_includes_user_messages(self, tmp_path):
        _setup_sessions_dir(tmp_path)
        msgs = [{"role": "user", "content": "Hello Jarvis!", "ts": "2026-01-01T00:00:00"}]
        sess = _make_session(tmp_path, messages=msgs, is_global=True)
        md = sessions_mod.export_session_markdown(sess)
        assert "Hello Jarvis!" in md
        assert "**You:**" in md

    def test_export_includes_assistant_messages(self, tmp_path):
        _setup_sessions_dir(tmp_path)
        msgs = [{"role": "assistant", "content": "Here is the fix.", "ts": "2026-01-01T00:01:00"}]
        sess = _make_session(tmp_path, messages=msgs, is_global=True)
        md = sessions_mod.export_session_markdown(sess)
        assert "Here is the fix." in md
        assert "**Jarvis:**" in md

    def test_export_summary_is_blockquote(self, tmp_path):
        _setup_sessions_dir(tmp_path)
        sess = _make_session(tmp_path, summary="Discussed auth.", is_global=True)
        md = sessions_mod.export_session_markdown(sess)
        assert "> Discussed auth." in md


# ═══════════════════════════════════════════════════════════════════
# C. /sessions/search and /sessions/export endpoints
# ═══════════════════════════════════════════════════════════════════

class TestSearchAndExportEndpoints:
    def test_search_endpoint_requires_q(self, tmp_path):
        import urllib.request, urllib.error
        _setup_sessions_dir(tmp_path)
        httpd, port = _start_server_once()
        try:
            with pytest.raises(urllib.error.HTTPError) as exc_info:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/sessions/search")
            assert exc_info.value.code == 400
        finally:
            httpd.server_close()

    def test_search_endpoint_returns_results(self, tmp_path):
        _setup_sessions_dir(tmp_path)
        _make_session(tmp_path, name="My CORS debugging session", is_global=True)
        httpd, port = _start_server_once()
        try:
            import urllib.parse
            q = urllib.parse.quote("cors")
            status, data = _get(port, f"/sessions/search?q={q}")
            assert status == 200
            assert "results" in data
            # At least 1 result found
            assert len(data["results"]) >= 1
            r = data["results"][0]
            assert "id" in r
            assert "snippet" in r
            assert "match_field" in r
        finally:
            httpd.server_close()

    def test_export_endpoint_returns_markdown(self, tmp_path):
        _setup_sessions_dir(tmp_path)
        msgs = [{"role": "user", "content": "Hello!", "ts": "2026-01-01T00:00:00"}]
        sess = _make_session(tmp_path, name="Export Me", messages=msgs, is_global=True)

        httpd, port = _start_server_once()
        try:
            import urllib.parse
            sid = urllib.parse.quote(sess["id"])
            status, data = _get(port, f"/sessions/export?session_id={sid}&is_global=1&format=markdown")
            assert status == 200
            assert "markdown" in data
            assert "Export Me" in data["markdown"]
            assert "Hello!" in data["markdown"]
        finally:
            httpd.server_close()
