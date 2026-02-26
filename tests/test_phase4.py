# tests/test_phase4.py
# Phase 4 tests — VS Code HTTP server, file context injection
# Run with: pytest tests/test_phase4.py -v

import pytest
import os
import sys
import json
import threading
import urllib.request
import urllib.error
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ─────────────────────────────────────────
# FILE CONTEXT BUILDER TESTS
# ─────────────────────────────────────────

class TestBuildMessageWithFileContext:
    def test_no_context_returns_original(self):
        """With no file info, the message should come back unchanged."""
        from orchestrator import build_message_with_file_context
        result = build_message_with_file_context("what is flexbox?")
        assert result == "what is flexbox?"

    def test_empty_strings_return_original(self):
        """Explicit empty strings should be treated as no context."""
        from orchestrator import build_message_with_file_context
        result = build_message_with_file_context("hello", file_path="", file_content="", selection="")
        assert result == "hello"

    def test_file_path_injected(self):
        """When file_content is provided, the file path should appear in output."""
        from orchestrator import build_message_with_file_context
        result = build_message_with_file_context(
            "fix the bug",
            file_path="src/app.component.ts",
            file_content="export class AppComponent {}"
        )
        assert "src/app.component.ts" in result
        assert "fix the bug" in result

    def test_file_content_injected(self):
        """File content should be included in the output."""
        from orchestrator import build_message_with_file_context
        result = build_message_with_file_context(
            "explain this",
            file_content="function hello() { return 42; }"
        )
        assert "function hello()" in result

    def test_selection_takes_priority_over_content(self):
        """When both selection and file_content are given, selection wins."""
        from orchestrator import build_message_with_file_context
        result = build_message_with_file_context(
            "what does this do?",
            file_content="full file content here",
            selection="selected snippet"
        )
        assert "selected snippet" in result
        assert "full file content here" not in result

    def test_selection_only(self):
        """Selection alone (no file_content) should be injected."""
        from orchestrator import build_message_with_file_context
        result = build_message_with_file_context(
            "explain",
            selection="const x = 42;"
        )
        assert "const x = 42;" in result

    def test_long_content_is_truncated(self):
        """File content over 2000 chars should be truncated to avoid token bloat."""
        from orchestrator import build_message_with_file_context
        long_content = "x" * 5000
        result = build_message_with_file_context("review this", file_content=long_content)
        assert "x" * 5000 not in result  # full content should not appear
        assert "x" * 2000 in result       # first 2000 chars should be there


# ─────────────────────────────────────────
# HTTP SERVER TESTS
# ─────────────────────────────────────────

class TestJarvisHTTPServer:
    """Start the real HTTP server on a random port, hit it with urllib."""

    @classmethod
    def setup_class(cls):
        from server import JarvisHTTPHandler
        from http.server import HTTPServer
        # port=0 lets the OS pick a free port
        cls.server = HTTPServer(("localhost", 0), JarvisHTTPHandler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def teardown_class(cls):
        cls.server.shutdown()

    def _get(self, path):
        url = f"http://localhost:{self.port}{path}"
        with urllib.request.urlopen(url) as r:
            return r.status, json.loads(r.read())

    def _post(self, path, data, mock_fn=None):
        url = f"http://localhost:{self.port}{path}"
        body = json.dumps(data).encode()
        req = urllib.request.Request(
            url, data=body,
            headers={"Content-Type": "application/json"}
        )
        if mock_fn:
            with patch("server.process_for_vscode", return_value=mock_fn):
                with urllib.request.urlopen(req) as r:
                    return r.status, json.loads(r.read())
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())

    def test_status_endpoint_returns_200(self):
        """GET /status should return 200 with status=running."""
        status, data = self._get("/status")
        assert status == 200
        assert data["status"] == "running"

    def test_status_endpoint_has_version(self):
        """GET /status should include a version field."""
        _, data = self._get("/status")
        assert "version" in data

    def test_unknown_get_returns_404(self):
        """Unknown GET path should return 404."""
        with pytest.raises(urllib.error.HTTPError) as exc:
            self._get("/unknown")
        assert exc.value.code == 404

    def test_chat_endpoint_returns_response(self):
        """POST /chat should return JSON with a response field."""
        status, data = self._post(
            "/chat",
            {"message": "hello"},
            mock_fn="Hello from Jarvis!"
        )
        assert status == 200
        assert "response" in data
        assert data["response"] == "Hello from Jarvis!"

    def test_chat_missing_message_returns_400(self):
        """POST /chat without message should return 400."""
        with pytest.raises(urllib.error.HTTPError) as exc:
            self._post("/chat", {}, mock_fn="should not get here")
        assert exc.value.code == 400
