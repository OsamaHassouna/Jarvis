# tests/test_phase6.py
# Phase 6 tests — Git integration, self-testing agents, browser preview
# Run with: pytest tests/test_phase6.py -v

import os
import sys
import json
import tempfile
import subprocess
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.git_tools import is_git_repo, git_auto_commit
from tools.test_runner import detect_test_command, run_tests
from tools.browser import detect_dev_server_url, open_browser_preview


# ─────────────────────────────────────────
# 6.1 — GIT INTEGRATION
# ─────────────────────────────────────────

class TestIsGitRepo:
    def test_temp_dir_is_not_git_repo(self):
        """A plain temp directory should not be a git repo."""
        with tempfile.TemporaryDirectory() as d:
            assert is_git_repo(d) is False

    def test_returns_false_on_invalid_path(self):
        """Non-existent path should return False gracefully."""
        result = is_git_repo("/path/that/does/not/exist/12345")
        assert result is False


class TestGitAutoCommit:
    def test_skips_gracefully_when_not_git_repo(self):
        """git_auto_commit should return (False, message) for non-git dirs."""
        with tempfile.TemporaryDirectory() as d:
            ok, msg = git_auto_commit(d, "some task")
            assert ok is False
            assert "not a git" in msg.lower() or "skip" in msg.lower()

    def test_returns_tuple(self):
        """git_auto_commit always returns a (bool, str) tuple."""
        with tempfile.TemporaryDirectory() as d:
            result = git_auto_commit(d, "test task")
            assert isinstance(result, tuple)
            assert len(result) == 2
            assert isinstance(result[0], bool)
            assert isinstance(result[1], str)

    def test_nothing_to_commit_when_clean(self):
        """If git repo has no changes, reports nothing to commit."""
        with tempfile.TemporaryDirectory() as d:
            # Init a real git repo
            subprocess.run(["git", "init"], cwd=d, capture_output=True)
            subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=d, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=d, capture_output=True)
            # Make an initial commit so the repo is clean
            dummy = os.path.join(d, "README.md")
            with open(dummy, "w") as f:
                f.write("init")
            subprocess.run(["git", "add", "."], cwd=d, capture_output=True)
            subprocess.run(["git", "commit", "-m", "init"], cwd=d, capture_output=True)

            ok, msg = git_auto_commit(d, "some task")
            assert ok is True
            assert "nothing" in msg.lower() or "clean" in msg.lower()


# ─────────────────────────────────────────
# 6.2 — SELF-TESTING AGENTS
# ─────────────────────────────────────────

class TestDetectTestCommand:
    def test_angular_project(self):
        """angular.json in dir → ng test command."""
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "angular.json"), "w") as f:
                json.dump({}, f)
            cmd = detect_test_command(d)
            assert cmd is not None
            assert "ng test" in cmd

    def test_dotnet_project(self):
        """.csproj file in dir → dotnet test command."""
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "MyApp.csproj"), "w") as f:
                f.write("<Project></Project>")
            cmd = detect_test_command(d)
            assert cmd is not None
            assert "dotnet test" in cmd

    def test_react_project(self):
        """package.json with react dep → npm test command."""
        with tempfile.TemporaryDirectory() as d:
            pkg = {"dependencies": {"react": "^18.0.0", "react-dom": "^18.0.0"}}
            with open(os.path.join(d, "package.json"), "w") as f:
                json.dump(pkg, f)
            cmd = detect_test_command(d)
            assert cmd is not None
            assert "npm test" in cmd or "jest" in cmd.lower()

    def test_unknown_project_returns_none(self):
        """Empty dir with no known project files → None."""
        with tempfile.TemporaryDirectory() as d:
            assert detect_test_command(d) is None


class TestRunTests:
    def test_passing_command_returns_true(self):
        """A command that exits 0 should return (True, output)."""
        ok, output = run_tests(".", "echo tests_passed", timeout=10)
        assert ok is True
        assert "tests_passed" in output

    def test_failing_command_returns_false(self):
        """A command that exits non-zero should return (False, output)."""
        # Use a cross-platform failing command
        ok, output = run_tests(".", "python -c \"raise SystemExit(1)\"", timeout=10)
        assert ok is False


# ─────────────────────────────────────────
# 6.3 — BROWSER PREVIEW
# ─────────────────────────────────────────

class TestDetectDevServerUrl:
    def test_angular_json_returns_4200(self):
        """angular.json present → localhost:4200."""
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "angular.json"), "w") as f:
                json.dump({}, f)
            url = detect_dev_server_url(d)
            assert url == "http://localhost:4200"

    def test_react_package_json_returns_3000(self):
        """package.json with react → localhost:3000."""
        with tempfile.TemporaryDirectory() as d:
            pkg = {"dependencies": {"react": "^18.0.0"}}
            with open(os.path.join(d, "package.json"), "w") as f:
                json.dump(pkg, f)
            url = detect_dev_server_url(d)
            assert url == "http://localhost:3000"

    def test_vue_package_json_returns_5173(self):
        """package.json with vue → localhost:5173."""
        with tempfile.TemporaryDirectory() as d:
            pkg = {"dependencies": {"vue": "^3.0.0"}}
            with open(os.path.join(d, "package.json"), "w") as f:
                json.dump(pkg, f)
            url = detect_dev_server_url(d)
            assert url == "http://localhost:5173"

    def test_unknown_project_returns_none(self):
        """Empty dir → None."""
        with tempfile.TemporaryDirectory() as d:
            assert detect_dev_server_url(d) is None


class TestOpenBrowserPreview:
    def test_no_frontend_returns_false(self):
        """Non-frontend dir → (False, error message)."""
        with tempfile.TemporaryDirectory() as d:
            ok, msg = open_browser_preview(d)
            assert ok is False
            assert len(msg) > 0

    def test_frontend_dir_opens_browser(self):
        """Frontend dir with angular.json → calls webbrowser.open and returns True."""
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "angular.json"), "w") as f:
                json.dump({}, f)
            with patch("tools.browser.webbrowser.open", return_value=True) as mock_open:
                ok, msg = open_browser_preview(d)
                assert ok is True
                mock_open.assert_called_once_with("http://localhost:4200")
