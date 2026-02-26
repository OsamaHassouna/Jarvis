# tools/test_runner.py
# Phase 6.2 — Self-testing agents.
# Detects the test command for a project and runs it after code changes.

import json
import os
import subprocess


def detect_test_command(working_dir: str) -> str | None:
    """
    Detect the appropriate test command for the project in working_dir.
    Returns a command string or None if the project type is unknown.
    """
    # Angular — angular.json is definitive
    if os.path.exists(os.path.join(working_dir, "angular.json")):
        return "ng test --watch=false --browsers=ChromeHeadless"

    # .NET — any .csproj file
    try:
        csproj_files = [f for f in os.listdir(working_dir) if f.endswith(".csproj")]
        if csproj_files:
            return "dotnet test"
    except OSError:
        pass

    # React / Next.js / generic npm project with a test script
    pkg_json_path = os.path.join(working_dir, "package.json")
    if os.path.exists(pkg_json_path):
        try:
            with open(pkg_json_path) as f:
                pkg = json.load(f)
            deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
            scripts = pkg.get("scripts", {})
            if "react" in deps or "next" in deps:
                return "npm test -- --watchAll=false"
            if "vue" in deps or "@vue/core" in deps:
                return "npm run test"
            if "test" in scripts:
                return "npm test -- --watchAll=false"
        except Exception:
            pass

    return None


def run_tests(working_dir: str, command: str, timeout: int = 120) -> tuple[bool, str]:
    """
    Run the test command in working_dir.
    Returns (success, combined_output).
    """
    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=working_dir,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        output = result.stdout + result.stderr
        return result.returncode == 0, output
    except subprocess.TimeoutExpired:
        return False, f"Tests timed out after {timeout}s"
    except Exception as e:
        return False, str(e)
