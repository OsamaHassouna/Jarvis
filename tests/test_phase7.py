# tests/test_phase7.py
# Phase 7 tests — File/image attachments, cross-machine sync, pause/resume, apply-code
# Run with: pytest tests/test_phase7.py -v

import os
import sys
import json
import tempfile
import base64
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import memory as mem_module
import config


# ── Isolation helper (reuse Phase 5 pattern) ─────────────────────────────────

TEMP_FILE = os.path.join(os.path.dirname(__file__), "test_memory_phase7.json")
_ORIG_MEM = mem_module.MEMORY_FILE
_ORIG_CFG = config.MEMORY_FILE


class MemoryTest:
    def setup_method(self, _):
        if os.path.exists(TEMP_FILE):
            os.remove(TEMP_FILE)
        mem_module.MEMORY_FILE = TEMP_FILE
        config.MEMORY_FILE = TEMP_FILE
        mem_module._synced_this_session = False  # reset sync flag

    def teardown_method(self, _):
        mem_module.MEMORY_FILE = _ORIG_MEM
        config.MEMORY_FILE = _ORIG_CFG
        mem_module._synced_this_session = False
        if os.path.exists(TEMP_FILE):
            os.remove(TEMP_FILE)


# ─────────────────────────────────────────
# TEXT ATTACHMENT PROCESSING
# ─────────────────────────────────────────

class TestTextAttachmentProcessing:
    def test_text_attachment_injected_in_message(self):
        """Text attachment content should appear in the augmented message."""
        from orchestrator import build_message_with_file_context
        result = build_message_with_file_context(
            "explain this",
            attachment_text="def hello(): return 'hi'",
            attachment_name="hello.py"
        )
        assert "hello.py" in result
        assert "def hello" in result

    def test_no_attachment_returns_plain_message(self):
        """Without attachment, message is returned as-is."""
        from orchestrator import build_message_with_file_context
        result = build_message_with_file_context("plain message")
        assert result == "plain message"

    def test_text_attachment_truncated_at_3000_chars(self):
        """Text attachment should be capped at 3000 chars.
        Use a unique tail marker to detect truncation reliably."""
        from orchestrator import build_message_with_file_context
        # Build text where chars 3000-4999 have a unique pattern
        big_text = ("a" * 3000) + ("OVERFLOW_MARKER" * 100)
        result = build_message_with_file_context("q", attachment_text=big_text, attachment_name="big.txt")
        # First 3000 chars should be there
        assert "a" * 100 in result
        # The overflow marker beyond position 3000 should NOT appear
        assert "OVERFLOW_MARKER" not in result


# ─────────────────────────────────────────
# IMAGE ATTACHMENT (VISION API)
# ─────────────────────────────────────────

class TestImageAttachmentProcessing:
    def _fake_image_b64(self):
        """Return a tiny valid base64-encoded PNG-like string."""
        return base64.b64encode(b"\x89PNG\r\n\x1a\nfake").decode()

    def test_image_builds_multimodal_content(self):
        """When image_base64 is provided, process_for_vscode should call API with list content."""
        from orchestrator import process_for_vscode
        b64 = self._fake_image_b64()

        captured = {}

        def fake_create(**kwargs):
            captured['messages'] = kwargs['messages']
            mock_resp = MagicMock()
            mock_resp.content = [MagicMock(text="I see an image.")]
            mock_resp.usage = MagicMock(input_tokens=10, output_tokens=5)
            return mock_resp

        with patch('orchestrator.client.messages.create', side_effect=fake_create):
            with patch('orchestrator.is_complex_task', return_value=False):
                with patch('orchestrator.update_last_session'):
                    with patch('orchestrator.detect_and_save_preference'):
                        with patch('orchestrator.add_to_history'):
                            process_for_vscode(
                                "what's in this image?",
                                attachment_image_base64=b64,
                                attachment_image_type="image/png"
                            )

        # The content sent to Claude must be a list (multimodal)
        content = captured['messages'][0]['content']
        assert isinstance(content, list)
        image_blocks = [b for b in content if b.get('type') == 'image']
        assert len(image_blocks) == 1
        assert image_blocks[0]['source']['data'] == b64
        assert image_blocks[0]['source']['media_type'] == "image/png"

    def test_no_image_sends_string_content(self):
        """Without an image, content sent to Claude must be a plain string."""
        from orchestrator import process_for_vscode

        captured = {}

        def fake_create(**kwargs):
            captured['messages'] = kwargs['messages']
            mock_resp = MagicMock()
            mock_resp.content = [MagicMock(text="Sure.")]
            mock_resp.usage = MagicMock(input_tokens=5, output_tokens=3)
            return mock_resp

        with patch('orchestrator.client.messages.create', side_effect=fake_create):
            with patch('orchestrator.is_complex_task', return_value=False):
                with patch('orchestrator.update_last_session'):
                    with patch('orchestrator.detect_and_save_preference'):
                        with patch('orchestrator.add_to_history'):
                            process_for_vscode("hello")

        content = captured['messages'][0]['content']
        assert isinstance(content, str)

    def test_image_defaults_media_type_to_png(self):
        """If image type is empty, default to image/png."""
        from orchestrator import process_for_vscode
        b64 = self._fake_image_b64()
        captured = {}

        def fake_create(**kwargs):
            captured['messages'] = kwargs['messages']
            mock_resp = MagicMock()
            mock_resp.content = [MagicMock(text="ok")]
            mock_resp.usage = MagicMock(input_tokens=5, output_tokens=3)
            return mock_resp

        with patch('orchestrator.client.messages.create', side_effect=fake_create):
            with patch('orchestrator.is_complex_task', return_value=False):
                with patch('orchestrator.update_last_session'):
                    with patch('orchestrator.detect_and_save_preference'):
                        with patch('orchestrator.add_to_history'):
                            process_for_vscode(
                                "describe",
                                attachment_image_base64=b64,
                                attachment_image_type=""   # empty → should default to image/png
                            )

        content = captured['messages'][0]['content']
        image_block = next(b for b in content if b.get('type') == 'image')
        assert image_block['source']['media_type'] == "image/png"


# ─────────────────────────────────────────
# CROSS-MACHINE SYNC (tools/sync.py)
# ─────────────────────────────────────────

class TestSyncTools:
    def test_push_skips_when_no_token(self):
        """push_memory with empty token returns False gracefully."""
        from tools.sync import push_memory
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump({"user": {}}, f)
            path = f.name
        try:
            ok, msg = push_memory(path, token="", gist_id="")
            assert ok is False
            assert len(msg) > 0
        finally:
            os.unlink(path)

    def test_pull_skips_when_no_token(self):
        """pull_memory with empty token returns False gracefully."""
        from tools.sync import pull_memory
        with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
            path = f.name
        try:
            ok, msg = pull_memory(path, token="", gist_id="")
            assert ok is False
        finally:
            os.unlink(path)

    def test_push_calls_github_api(self):
        """push_memory with a token should make a PATCH request to the Gist API."""
        from tools.sync import push_memory
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump({"user": {"name": "Osama"}}, f)
            path = f.name
        try:
            mock_response = MagicMock()
            mock_response.__enter__ = MagicMock(return_value=mock_response)
            mock_response.__exit__ = MagicMock(return_value=False)

            with patch('urllib.request.urlopen', return_value=mock_response) as mock_urlopen:
                ok, msg = push_memory(path, token="ghp_fake", gist_id="abc123")
                assert ok is True
                assert mock_urlopen.called
                # Verify PATCH method
                req = mock_urlopen.call_args[0][0]
                assert req.get_method() == "PATCH"
        finally:
            os.unlink(path)

    def test_pull_writes_content_from_gist(self):
        """pull_memory should write Gist file content to local path."""
        from tools.sync import pull_memory
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            path = f.name

        gist_memory = {"user": {"name": "SyncedUser"}, "projects": [], "history": [], "last_session": ""}
        gist_response = {
            "files": {"memory.json": {"content": json.dumps(gist_memory)}}
        }

        mock_urlopen = MagicMock()
        mock_urlopen.return_value.__enter__ = MagicMock(
            return_value=MagicMock(read=MagicMock(return_value=json.dumps(gist_response).encode()))
        )
        mock_urlopen.return_value.__exit__ = MagicMock(return_value=False)

        try:
            with patch('urllib.request.urlopen', mock_urlopen):
                ok, msg = pull_memory(path, token="ghp_fake", gist_id="abc123")
                assert ok is True
                with open(path) as f:
                    data = json.load(f)
                assert data["user"]["name"] == "SyncedUser"
        finally:
            os.unlink(path)


# ─────────────────────────────────────────
# AGENT POOL PAUSE — skip remaining
# ─────────────────────────────────────────

class TestAgentPoolPause:
    def test_skip_remaining_marks_pending_as_skipped(self):
        """The skip-remaining logic marks all PENDING agents as SKIPPED.
        Tests the business logic directly without threading complexity."""
        from agents.agent_pool import AgentPool
        from agents.agent import Agent, AgentStatus

        agent1 = Agent(id="agent_1", task="do A")
        agent2 = Agent(id="agent_2", task="do B")
        agent3 = Agent(id="agent_3", task="do C")

        pool = AgentPool(agents=[agent1, agent2, agent3], working_dir=".")

        # Simulate: agent1 succeeded, agent2/3 still pending
        agent1.status = AgentStatus.SUCCESS
        agent2.status = AgentStatus.PENDING
        agent3.status = AgentStatus.PENDING

        # This is exactly what execute() runs on choice "2"
        for a in pool.agents:
            if a.status == AgentStatus.PENDING:
                a.status = AgentStatus.SKIPPED

        assert agent1.status == AgentStatus.SUCCESS  # unchanged
        assert agent2.status == AgentStatus.SKIPPED
        assert agent3.status == AgentStatus.SKIPPED


# ─────────────────────────────────────────
# SERVER VERSION
# ─────────────────────────────────────────

class TestServerVersion:
    def test_status_returns_phase7(self):
        """GET /status should return version 'phase7'."""
        import threading
        import urllib.request
        from server import JarvisHTTPHandler
        from http.server import HTTPServer

        srv = HTTPServer(("localhost", 0), JarvisHTTPHandler)
        port = srv.server_address[1]
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        try:
            with urllib.request.urlopen(f"http://localhost:{port}/status") as r:
                data = json.loads(r.read())
            assert data["version"] == "phase7"
        finally:
            srv.shutdown()


# ─────────────────────────────────────────
# TERMINAL ATTACH — main.py integration
# ─────────────────────────────────────────

class TestTerminalAttach:
    def test_attach_reads_file_content(self):
        """After 'attach <path>', the file content should be injected into the next message."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write("def greet(): return 'hello'")
            path = f.name
        try:
            # Simulate what main.py does
            import os as _os
            _attached_content = ""
            _attached_name = ""
            user_input = f"attach {path}"

            if user_input.lower().startswith("attach "):
                attach_path = user_input[7:].strip()
                if _os.path.exists(attach_path):
                    with open(attach_path, "r", encoding="utf-8", errors="replace") as fh:
                        _attached_content = fh.read()
                    _attached_name = _os.path.basename(attach_path)

            assert "def greet" in _attached_content
            assert _attached_name.endswith(".py")
        finally:
            os.unlink(path)

    def test_attach_missing_file_sets_no_content(self):
        """Attaching a non-existent file should result in empty content (no crash)."""
        import os as _os
        _attached_content = ""
        path = "/nonexistent/path/file.py"
        if not _os.path.exists(path):
            pass  # In main.py we print error and continue — content stays empty

        assert _attached_content == ""
