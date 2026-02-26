# tests/test_phase5.py
# Phase 5 tests — Multi-project awareness, preferences learning, daily briefing
# Run with: pytest tests/test_phase5.py -v

import pytest
import os
import sys
import json
import threading
import urllib.request
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import memory as mem_module
import config

TEMP_FILE = os.path.join(os.path.dirname(__file__), "test_memory_phase5.json")
_ORIG_MEM  = mem_module.MEMORY_FILE
_ORIG_CFG  = config.MEMORY_FILE


class MemoryTest:
    """Base class that isolates every test method to a fresh temp memory file."""

    def setup_method(self, _method):
        if os.path.exists(TEMP_FILE):
            os.remove(TEMP_FILE)
        mem_module.MEMORY_FILE = TEMP_FILE
        config.MEMORY_FILE     = TEMP_FILE

    def teardown_method(self, _method):
        mem_module.MEMORY_FILE = _ORIG_MEM
        config.MEMORY_FILE     = _ORIG_CFG
        if os.path.exists(TEMP_FILE):
            os.remove(TEMP_FILE)


def _seed_project(name, path, stack=None, tasks=None, last_updated=None):
    """Add a project directly to the active temp memory file."""
    m = mem_module.load_memory()
    m["projects"].append({
        "name": name,
        "path": path,
        "stack": stack or [],
        "tasks_completed": tasks or [],
        "last_updated": last_updated or "",
    })
    mem_module.save_memory(m)


# ─────────────────────────────────────────
# 5.1 — MULTI-PROJECT AWARENESS
# ─────────────────────────────────────────

class TestGetProjectByName(MemoryTest):
    def test_exact_match(self):
        """Exact name match should return the project."""
        _seed_project("login-fullstack", "D:/projects/login-fullstack")
        result = mem_module.get_project_by_name("login-fullstack")
        assert result is not None
        assert result["name"] == "login-fullstack"

    def test_partial_match(self):
        """Partial name match should return the project."""
        _seed_project("login-fullstack", "D:/projects/login-fullstack")
        result = mem_module.get_project_by_name("login")
        assert result is not None
        assert result["name"] == "login-fullstack"

    def test_case_insensitive(self):
        """Name search should be case-insensitive."""
        _seed_project("MyAngularApp", "D:/projects/my-app")
        result = mem_module.get_project_by_name("myangular")
        assert result is not None

    def test_not_found_returns_none(self):
        """Unknown name should return None."""
        result = mem_module.get_project_by_name("nonexistent-project")
        assert result is None


class TestSearchProjects(MemoryTest):
    def test_search_by_name(self):
        """search_projects should match on project name."""
        _seed_project("angular-dashboard", "D:/projects/dashboard", stack=["Angular"])
        _seed_project("dotnet-api", "D:/projects/api", stack=[".NET"])
        results = mem_module.search_projects("dashboard")
        assert len(results) == 1
        assert results[0]["name"] == "angular-dashboard"

    def test_search_by_stack(self):
        """search_projects should match on stack technology."""
        _seed_project("project-a", "D:/a", stack=["Angular", "TypeScript"])
        _seed_project("project-b", "D:/b", stack=[".NET", "C#"])
        results = mem_module.search_projects("Angular")
        assert len(results) == 1
        assert results[0]["name"] == "project-a"

    def test_no_match_returns_empty(self):
        """No matching projects should return an empty list."""
        _seed_project("project-a", "D:/a", stack=["React"])
        results = mem_module.search_projects("Vue")
        assert results == []


class TestGetAllProjectsSummary(MemoryTest):
    def test_empty_returns_placeholder(self):
        """With no projects, summary should say so."""
        result = mem_module.get_all_projects_summary()
        assert "No projects" in result

    def test_summary_lists_project_names(self):
        """Summary should include each project's name."""
        _seed_project("alpha", "D:/alpha", stack=["Angular"],
                      last_updated="2026-02-01T10:00:00")
        _seed_project("beta", "D:/beta", stack=[".NET"],
                      last_updated="2026-02-02T10:00:00")
        result = mem_module.get_all_projects_summary()
        assert "alpha" in result
        assert "beta" in result


# ─────────────────────────────────────────
# 5.2 — PREFERENCES LEARNING
# ─────────────────────────────────────────

class TestLearnPreference(MemoryTest):
    def test_save_new_preference(self):
        """A new preference key/value should be saved to memory."""
        mem_module.learn_preference("css", "BEM methodology")
        m = mem_module.load_memory()
        assert m["user"]["preferences"]["css"] == "BEM methodology"

    def test_update_existing_preference(self):
        """Saving the same key twice should overwrite the old value."""
        mem_module.learn_preference("css", "BEM methodology")
        mem_module.learn_preference("css", "Tailwind CSS")
        m = mem_module.load_memory()
        assert m["user"]["preferences"]["css"] == "Tailwind CSS"

    def test_migrates_from_list_format(self):
        """Old list-format preferences should be migrated to dict silently."""
        m = mem_module.load_memory()
        m["user"]["preferences"] = ["some old pref"]
        mem_module.save_memory(m)
        mem_module.learn_preference("style", "standalone components")
        m2 = mem_module.load_memory()
        assert isinstance(m2["user"]["preferences"], dict)
        assert m2["user"]["preferences"]["style"] == "standalone components"

    def test_preferences_appear_in_context_summary(self):
        """Saved preferences should show up in the system context string."""
        mem_module.learn_preference("css", "BEM methodology")
        context = mem_module.get_context_summary()
        assert "BEM methodology" in context


class TestDetectAndSavePreference(MemoryTest):
    def test_detects_remember_pattern(self):
        """'remember: ...' in a message should save a preference and return it."""
        from orchestrator import detect_and_save_preference
        result = detect_and_save_preference("remember: I always use standalone components")
        assert result is not None
        assert "standalone" in result

    def test_no_match_returns_none(self):
        """A normal message with no 'remember' keyword should return None."""
        from orchestrator import detect_and_save_preference
        result = detect_and_save_preference("how do I use NgRx?")
        assert result is None

    def test_preference_persisted_after_detect(self):
        """Detected preference should be findable in memory afterwards."""
        from orchestrator import detect_and_save_preference
        detect_and_save_preference("remember: css BEM methodology")
        m = mem_module.load_memory()
        prefs = m["user"]["preferences"]
        assert isinstance(prefs, dict)
        assert len(prefs) >= 1


# ─────────────────────────────────────────
# 5.3 — DAILY BRIEFING
# ─────────────────────────────────────────

class TestUpdateLastSession(MemoryTest):
    def test_updates_timestamp(self):
        """update_last_session should set last_session to a non-empty string."""
        mem_module.update_last_session()
        m = mem_module.load_memory()
        assert m["last_session"] != ""
        assert "202" in m["last_session"]


class TestGetDailyBriefing(MemoryTest):
    def test_empty_memory_returns_dict_with_keys(self):
        """get_daily_briefing should always return a dict with expected keys."""
        result = mem_module.get_daily_briefing()
        for key in ("user_name", "last_session", "recent_project", "total_projects"):
            assert key in result

    def test_no_projects_recent_project_is_none(self):
        """With no projects, recent_project should be None."""
        result = mem_module.get_daily_briefing()
        assert result["recent_project"] is None
        assert result["total_projects"] == 0

    def test_with_project_shows_recent(self):
        """With a project in memory, recent_project should be its name."""
        _seed_project(
            "login-fullstack", "D:/login",
            stack=["Angular", ".NET"],
            tasks=[{"date": "2026-02-26", "task": "build auth",
                    "agents_succeeded": 2, "agents_total": 2}],
            last_updated="2026-02-26T10:00:00"
        )
        result = mem_module.get_daily_briefing()
        assert result["recent_project"] == "login-fullstack"
        assert result["last_task"] == "build auth"
        assert result["total_projects"] == 1


class TestProcessBriefing(MemoryTest):
    def test_briefing_text_contains_user_name(self):
        """process_briefing output should mention the user's name."""
        m = mem_module.load_memory()
        m["user"]["name"] = "Osama"
        mem_module.save_memory(m)
        from orchestrator import process_briefing
        text = process_briefing()
        assert "Osama" in text

    def test_briefing_shows_project_info(self):
        """process_briefing should include the last project when one exists."""
        _seed_project(
            "my-app", "D:/my-app",
            stack=["Angular"],
            tasks=[{"date": "2026-02-26", "task": "add login page",
                    "agents_succeeded": 1, "agents_total": 1}],
            last_updated="2026-02-26T09:00:00"
        )
        from orchestrator import process_briefing
        text = process_briefing()
        assert "my-app" in text

    def test_no_projects_shows_fallback(self):
        """process_briefing with no projects should show a helpful message."""
        from orchestrator import process_briefing
        text = process_briefing()
        assert "No projects" in text or "no projects" in text.lower()


# ─────────────────────────────────────────
# /briefing HTTP ENDPOINT
# ─────────────────────────────────────────

class TestBriefingEndpoint:
    @classmethod
    def setup_class(cls):
        from server import JarvisHTTPHandler
        from http.server import HTTPServer
        cls.server = HTTPServer(("localhost", 0), JarvisHTTPHandler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def teardown_class(cls):
        cls.server.shutdown()

    def test_briefing_endpoint_returns_200(self):
        """GET /briefing should return 200 with a briefing field."""
        url = f"http://localhost:{self.port}/briefing"
        with patch("server.process_briefing", return_value="Good to see you, Osama!"):
            with urllib.request.urlopen(url) as r:
                assert r.status == 200
                data = json.loads(r.read())
                assert "briefing" in data
                assert data["briefing"] == "Good to see you, Osama!"
