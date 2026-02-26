# tests/test_phase3.py
# Phase 3 tests — AI complexity detection, project scanner, agent result memory
# Run with: pytest tests/test_phase3.py -v

import pytest
import os
import sys
import json
import shutil
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ─────────────────────────────────────────
# AI COMPLEXITY DETECTION TESTS (Phase 3.1)
# ─────────────────────────────────────────

class TestAIComplexityDetection:
    def test_ai_classify_returns_required_keys(self):
        """ai_classify_task should always return is_complex, model, used_ai."""
        from orchestrator import ai_classify_task
        # Mock the API call to avoid real network requests in tests
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="SIMPLE")]
        with patch("orchestrator.client.messages.create", return_value=mock_response):
            result = ai_classify_task("what is flexbox?")
        assert "is_complex" in result
        assert "model" in result
        assert "used_ai" in result

    def test_ai_classify_simple_task(self):
        """AI should classify 'what is X' as SIMPLE."""
        from orchestrator import ai_classify_task
        from config import MODEL_SONNET
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="SIMPLE")]
        with patch("orchestrator.client.messages.create", return_value=mock_response):
            result = ai_classify_task("what is flexbox?")
        assert result["is_complex"] == False
        assert result["model"] == MODEL_SONNET
        assert result["used_ai"] == True

    def test_ai_classify_complex_task(self):
        """AI should classify 'build full auth system' as COMPLEX."""
        from orchestrator import ai_classify_task
        from config import MODEL_OPUS
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="COMPLEX")]
        with patch("orchestrator.client.messages.create", return_value=mock_response):
            result = ai_classify_task("build a full authentication system with JWT")
        assert result["is_complex"] == True
        assert result["model"] == MODEL_OPUS
        assert result["used_ai"] == True

    def test_ai_classify_falls_back_on_error(self):
        """When AI fails, should fall back to keyword detection gracefully."""
        from orchestrator import ai_classify_task
        with patch("orchestrator.client.messages.create", side_effect=Exception("API error")):
            result = ai_classify_task("build a full authentication system")
        # Should not raise, should fall back to keyword-based result
        assert "is_complex" in result
        assert "model" in result
        assert result["used_ai"] == False


# ─────────────────────────────────────────
# PROJECT SCANNER TESTS (Phase 3.2)
# ─────────────────────────────────────────

class TestProjectScanner:
    def setup_method(self):
        """Create a temp directory for each test."""
        self.test_dir = os.path.join(os.path.dirname(__file__), "temp_scan_test")
        os.makedirs(self.test_dir, exist_ok=True)

    def teardown_method(self):
        """Clean up temp directory after each test."""
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)

    def test_scanner_empty_directory(self):
        """Empty directory should return empty dict."""
        from tools.project_scanner import scan_project
        result = scan_project(self.test_dir)
        assert isinstance(result, dict)
        assert result.get("framework", "") == ""
        assert result.get("backend", "") == ""

    def test_scanner_detects_angular(self):
        """Should detect Angular version from package.json."""
        from tools.project_scanner import scan_project
        pkg = {
            "name": "my-app",
            "dependencies": {
                "@angular/core": "^18.0.0"
            }
        }
        with open(os.path.join(self.test_dir, "package.json"), "w") as f:
            json.dump(pkg, f)
        result = scan_project(self.test_dir)
        assert "Angular 18" in result.get("framework", "")
        assert "Angular 18" in result.get("stack", [])

    def test_scanner_detects_dotnet(self):
        """Should detect .NET version from .csproj file."""
        from tools.project_scanner import scan_project
        csproj_content = """<Project Sdk="Microsoft.NET.Sdk.Web">
  <PropertyGroup>
    <TargetFramework>net8.0</TargetFramework>
  </PropertyGroup>
</Project>"""
        with open(os.path.join(self.test_dir, "MyApp.csproj"), "w") as f:
            f.write(csproj_content)
        result = scan_project(self.test_dir)
        assert ".NET 8" in result.get("backend", "")
        assert ".NET 8" in result.get("stack", [])

    def test_scanner_invalid_directory(self):
        """Non-existent directory should return empty dict."""
        from tools.project_scanner import scan_project
        result = scan_project("/nonexistent/path/xyz")
        assert result == {}

    def test_get_context_string_empty(self):
        """Empty project info should return empty string."""
        from tools.project_scanner import get_context_string
        result = get_context_string({})
        assert result == ""

    def test_get_context_string_with_data(self):
        """Context string should include framework and backend info."""
        from tools.project_scanner import get_context_string
        info = {
            "framework": "Angular 18",
            "backend": ".NET 8",
            "description": "my-app",
            "notes": [],
            "stack": ["Angular 18", ".NET 8"]
        }
        result = get_context_string(info)
        assert "Angular 18" in result
        assert ".NET 8" in result


# ─────────────────────────────────────────
# AGENT RESULT MEMORY TESTS (Phase 3.3)
# ─────────────────────────────────────────

TEMP_MEMORY_FILE = os.path.join(os.path.dirname(__file__), "test_memory_phase3.json")


class TestAgentResultMemory:
    def setup_method(self):
        """Use isolated temp memory file — write a clean default state."""
        import config
        import memory as mem_module
        import copy
        self._original = config.MEMORY_FILE
        config.MEMORY_FILE = TEMP_MEMORY_FILE
        mem_module.MEMORY_FILE = TEMP_MEMORY_FILE
        # Write a guaranteed clean slate instead of relying on file deletion
        mem_module.save_memory(copy.deepcopy(mem_module.DEFAULT_MEMORY))

    def teardown_method(self):
        """Restore original memory file and clean up."""
        import config
        import memory as mem_module
        config.MEMORY_FILE = self._original
        mem_module.MEMORY_FILE = self._original
        if os.path.exists(TEMP_MEMORY_FILE):
            os.remove(TEMP_MEMORY_FILE)

    def test_save_task_creates_project(self):
        """save_task_to_project should create a project entry if it doesn't exist."""
        from memory import save_task_to_project, load_memory
        save_task_to_project(
            project_path="D:\\Personal\\my-app",
            task="Build a login form",
            agents_succeeded=2,
            agents_total=2,
            stack=["Angular 18"]
        )
        mem = load_memory()
        projects = mem["projects"]
        assert len(projects) == 1
        assert projects[0]["path"] == "D:\\Personal\\my-app"
        assert len(projects[0]["tasks_completed"]) == 1
        assert projects[0]["tasks_completed"][0]["agents_succeeded"] == 2

    def test_save_task_appends_to_existing_project(self):
        """Saving a second task to the same project should append, not replace."""
        from memory import save_task_to_project, load_memory
        save_task_to_project("D:\\Personal\\my-app", "Task 1", 1, 1)
        save_task_to_project("D:\\Personal\\my-app", "Task 2", 2, 2)
        mem = load_memory()
        assert len(mem["projects"][0]["tasks_completed"]) == 2

    def test_save_task_stores_stack(self):
        """Stack info should be saved to the project."""
        from memory import save_task_to_project, load_memory
        save_task_to_project(
            project_path="D:\\Personal\\my-app",
            task="Build API",
            agents_succeeded=1,
            agents_total=1,
            stack=["Angular 18", ".NET 8"]
        )
        mem = load_memory()
        stack = mem["projects"][0]["stack"]
        assert "Angular 18" in stack
        assert ".NET 8" in stack

    def test_context_summary_uses_dynamic_name(self):
        """Context summary should use the user's stored name, not hardcoded value."""
        from memory import load_memory, save_memory, get_context_summary
        mem = load_memory()
        mem["user"]["name"] = "TestUser"
        mem["history"] = [{"role": "user", "content": "hello"}]
        save_memory(mem)
        summary = get_context_summary()
        assert "TestUser" in summary
