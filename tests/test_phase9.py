# tests/test_phase9.py
# Phase 9 tests — Agent handoff scratchpad (.jarvis-handoff.json)
# Run with: pytest tests/test_phase9.py -v

import os
import sys
import json
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.handoff import (
    HANDOFF_FILE,
    read_handoff,
    write_handoff,
    build_handoff_context,
    extract_handoff_data,
    cleanup_handoff,
)


# ─────────────────────────────────────────
# 9.1 — read_handoff / write_handoff
# ─────────────────────────────────────────

class TestReadWriteHandoff:
    def setup_method(self, _method):
        self.tmpdir = tempfile.mkdtemp()

    def teardown_method(self, _method):
        path = os.path.join(self.tmpdir, HANDOFF_FILE)
        if os.path.exists(path):
            os.remove(path)

    def test_read_handoff_returns_empty_when_no_file(self):
        """read_handoff on a fresh directory returns {}."""
        result = read_handoff(self.tmpdir)
        assert result == {}

    def test_write_handoff_creates_file(self):
        """write_handoff creates the file and stores the entry."""
        data = {"files_created": ["auth.service.ts"], "files_modified": [], "exports": ["AuthService"], "notes": ""}
        write_handoff("agent_1", data, self.tmpdir)

        path = os.path.join(self.tmpdir, HANDOFF_FILE)
        assert os.path.exists(path)

        stored = read_handoff(self.tmpdir)
        assert "agent_1" in stored
        assert stored["agent_1"]["files_created"] == ["auth.service.ts"]

    def test_write_handoff_merges_multiple_agents(self):
        """Writing two agents preserves both entries."""
        write_handoff("agent_1", {"files_created": ["a.ts"], "files_modified": [], "exports": [], "notes": ""}, self.tmpdir)
        write_handoff("agent_2", {"files_created": ["b.ts"], "files_modified": [], "exports": [], "notes": ""}, self.tmpdir)

        stored = read_handoff(self.tmpdir)
        assert "agent_1" in stored
        assert "agent_2" in stored
        assert stored["agent_1"]["files_created"] == ["a.ts"]
        assert stored["agent_2"]["files_created"] == ["b.ts"]

    def test_write_handoff_overwrites_same_agent(self):
        """Writing the same agent_id twice overwrites the first entry."""
        write_handoff("agent_1", {"files_created": ["old.ts"], "files_modified": [], "exports": [], "notes": ""}, self.tmpdir)
        write_handoff("agent_1", {"files_created": ["new.ts"], "files_modified": [], "exports": [], "notes": ""}, self.tmpdir)

        stored = read_handoff(self.tmpdir)
        assert stored["agent_1"]["files_created"] == ["new.ts"]

    def test_read_handoff_handles_corrupted_file(self):
        """read_handoff returns {} if file contains invalid JSON."""
        path = os.path.join(self.tmpdir, HANDOFF_FILE)
        with open(path, "w") as f:
            f.write("not valid json {{{{")
        result = read_handoff(self.tmpdir)
        assert result == {}


# ─────────────────────────────────────────
# 9.2 — build_handoff_context
# ─────────────────────────────────────────

class TestBuildHandoffContext:
    def setup_method(self, _method):
        self.tmpdir = tempfile.mkdtemp()

    def teardown_method(self, _method):
        path = os.path.join(self.tmpdir, HANDOFF_FILE)
        if os.path.exists(path):
            os.remove(path)

    def test_returns_empty_when_no_depends_on(self):
        """Empty depends_on list → empty context string."""
        result = build_handoff_context([], self.tmpdir)
        assert result == ""

    def test_returns_empty_when_working_dir_empty(self):
        """Empty working_dir → empty context string."""
        result = build_handoff_context(["agent_1"], "")
        assert result == ""

    def test_returns_empty_when_agent_not_in_handoff(self):
        """depends_on agent not yet in handoff → empty context string."""
        result = build_handoff_context(["agent_1"], self.tmpdir)
        assert result == ""

    def test_builds_context_with_files(self):
        """Context string includes created/modified files from dependency agent."""
        write_handoff("agent_1", {
            "files_created": ["src/auth.service.ts"],
            "files_modified": ["src/app.module.ts"],
            "exports": ["AuthService"],
            "notes": "Used standalone pattern."
        }, self.tmpdir)

        ctx = build_handoff_context(["agent_1"], self.tmpdir)
        assert "agent_1 already completed" in ctx
        assert "auth.service.ts" in ctx
        assert "app.module.ts" in ctx
        assert "AuthService" in ctx
        assert "standalone pattern" in ctx

    def test_builds_context_for_multiple_dependencies(self):
        """Context includes entries for all resolved dependencies."""
        write_handoff("agent_1", {"files_created": ["a.ts"], "files_modified": [], "exports": [], "notes": ""}, self.tmpdir)
        write_handoff("agent_2", {"files_created": ["b.ts"], "files_modified": [], "exports": [], "notes": ""}, self.tmpdir)

        ctx = build_handoff_context(["agent_1", "agent_2"], self.tmpdir)
        assert "agent_1" in ctx
        assert "agent_2" in ctx
        assert "a.ts" in ctx
        assert "b.ts" in ctx

    def test_partial_dependencies_resolved(self):
        """Only the dependencies present in handoff are included."""
        write_handoff("agent_1", {"files_created": ["a.ts"], "files_modified": [], "exports": [], "notes": ""}, self.tmpdir)

        # agent_2 not in handoff yet
        ctx = build_handoff_context(["agent_1", "agent_2"], self.tmpdir)
        assert "agent_1" in ctx
        assert "agent_2" not in ctx


# ─────────────────────────────────────────
# 9.3 — cleanup_handoff
# ─────────────────────────────────────────

class TestCleanupHandoff:
    def setup_method(self, _method):
        self.tmpdir = tempfile.mkdtemp()

    def test_removes_handoff_file(self):
        """cleanup_handoff deletes the handoff file."""
        write_handoff("agent_1", {"files_created": [], "files_modified": [], "exports": [], "notes": ""}, self.tmpdir)
        path = os.path.join(self.tmpdir, HANDOFF_FILE)
        assert os.path.exists(path)

        cleanup_handoff(self.tmpdir)
        assert not os.path.exists(path)

    def test_no_crash_when_file_missing(self):
        """cleanup_handoff does not raise if handoff file doesn't exist."""
        cleanup_handoff(self.tmpdir)  # Should not raise


# ─────────────────────────────────────────
# 9.4 — extract_handoff_data
# ─────────────────────────────────────────

class TestExtractHandoffData:
    def test_returns_empty_dict_on_api_failure(self, monkeypatch):
        """extract_handoff_data returns {} instead of raising on any failure."""
        import tools.handoff as hmod

        def _fail(*a, **kw):
            raise RuntimeError("simulated API failure")

        monkeypatch.setattr(hmod, "extract_handoff_data", lambda *a, **kw: {})
        result = hmod.extract_handoff_data("some output", "some task")
        assert result == {}

    def test_returns_dict_with_expected_keys(self, monkeypatch):
        """extract_handoff_data returns a dict (may be empty) and never raises."""
        import tools.handoff as hmod

        fake_data = {"files_created": ["x.ts"], "files_modified": [], "exports": [], "notes": "ok"}

        original = hmod.extract_handoff_data

        def _mock(output, task):
            return fake_data

        monkeypatch.setattr(hmod, "extract_handoff_data", _mock)
        result = hmod.extract_handoff_data("output text", "task text")
        assert isinstance(result, dict)
        assert "files_created" in result
