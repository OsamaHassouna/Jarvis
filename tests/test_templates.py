"""
tests/test_templates.py — Phase 11: Task Templates

Tests CRUD operations, trigger matching, and /template command interception.
"""
import json
import os
import tempfile
import pytest

# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def isolated_templates_dir(tmp_path, monkeypatch):
    """Redirect all template storage to a temporary directory for each test."""
    import tools.templates as tmod
    monkeypatch.setattr(tmod, "_JARVIS_ROOT", str(tmp_path))
    yield tmp_path


SAMPLE_AGENTS = [
    {"id": "component", "task": "Create the component", "depends_on": []},
    {"id": "tests",     "task": "Write unit tests",     "depends_on": ["component"]},
]


# ── CRUD ──────────────────────────────────────────────────────────────────────

def test_save_and_get_global_template():
    from tools.templates import save_template, get_template
    save_template("my-feature", SAMPLE_AGENTS, description="A test template")
    t = get_template("my-feature")
    assert t is not None
    assert t["name"] == "my-feature"
    assert t["description"] == "A test template"
    assert len(t["agents"]) == 2
    assert t["scope"] == "global"


def test_get_returns_none_for_missing_template():
    from tools.templates import get_template
    assert get_template("does-not-exist") is None


def test_list_templates_includes_global(tmp_path):
    from tools.templates import save_template, list_templates
    save_template("alpha", SAMPLE_AGENTS)
    save_template("beta",  SAMPLE_AGENTS)
    templates = list_templates()
    names = [t["name"] for t in templates]
    assert "alpha" in names
    assert "beta" in names


def test_list_templates_empty():
    from tools.templates import list_templates
    assert list_templates() == []


def test_delete_template():
    from tools.templates import save_template, delete_template, get_template
    save_template("to-delete", SAMPLE_AGENTS)
    assert get_template("to-delete") is not None
    assert delete_template("to-delete") is True
    assert get_template("to-delete") is None


def test_delete_missing_returns_false():
    from tools.templates import delete_template
    assert delete_template("ghost-template") is False


def test_project_scoped_template(tmp_path):
    from tools.templates import save_template, get_template, list_templates
    workspace = str(tmp_path / "my-project")
    save_template("proj-feature", SAMPLE_AGENTS, workspace_root=workspace)

    # get_template prefers project-scoped
    t = get_template("proj-feature", workspace_root=workspace)
    assert t is not None
    assert t["scope"] == "project"

    # global list does not include project template
    global_only = list_templates("")
    assert all(t["name"] != "proj-feature" for t in global_only)

    # workspace list includes both global (0) and project (1)
    all_templates = list_templates(workspace_root=workspace)
    proj_names = [t["name"] for t in all_templates if t["scope"] == "project"]
    assert "proj-feature" in proj_names


def test_increment_use_count():
    from tools.templates import save_template, get_template, increment_use_count
    save_template("counted", SAMPLE_AGENTS)
    increment_use_count("counted")
    increment_use_count("counted")
    t = get_template("counted")
    assert t["use_count"] == 2


# ── Trigger phrase matching ───────────────────────────────────────────────────

def test_find_by_trigger_matches():
    from tools.templates import save_template, find_by_trigger
    save_template("ng-feat", SAMPLE_AGENTS, trigger_phrases=["new angular feature"])
    match = find_by_trigger("I want to add a new angular feature to the app")
    assert match is not None
    assert match["name"] == "ng-feat"


def test_find_by_trigger_no_match():
    from tools.templates import save_template, find_by_trigger
    save_template("ng-feat", SAMPLE_AGENTS, trigger_phrases=["new angular feature"])
    assert find_by_trigger("something completely unrelated") is None


# ── Command interception ──────────────────────────────────────────────────────

def test_handle_template_list_empty():
    from orchestrator import handle_template_command
    result = handle_template_command("/template list")
    assert result is not None
    assert "No templates" in result


def test_handle_template_list_shows_templates():
    from tools.templates import save_template
    from orchestrator import handle_template_command
    save_template("show-me", SAMPLE_AGENTS, description="Demo template")
    result = handle_template_command("/template list")
    assert "show-me" in result
    assert "2 agents" in result


def test_handle_template_info():
    from tools.templates import save_template
    from orchestrator import handle_template_command
    save_template("info-test", SAMPLE_AGENTS, description="Info test template")
    result = handle_template_command("/template info info-test")
    assert "info-test" in result
    assert "component" in result
    assert "tests" in result


def test_handle_template_info_missing():
    from orchestrator import handle_template_command
    result = handle_template_command("/template info ghost")
    assert "not found" in result.lower()


def test_handle_template_use_redirects_in_vscode():
    from tools.templates import save_template
    from orchestrator import handle_template_command
    save_template("use-me", SAMPLE_AGENTS)
    result = handle_template_command("/template use use-me")
    assert result is not None
    # In VS Code context (no terminal) it shows the preview + redirect message
    assert "use-me" in result
    assert len(result) > 0


def test_handle_template_use_with_context():
    from tools.templates import save_template
    from orchestrator import handle_template_command, get_last_agent_defs
    save_template("ctx-test", SAMPLE_AGENTS)
    handle_template_command("/template use ctx-test for user-profile")
    defs = get_last_agent_defs()
    assert any("user-profile" in a["task"] for a in defs)


def test_handle_template_save_no_breakdown():
    from orchestrator import handle_template_command
    import orchestrator
    orchestrator._last_agent_defs = []          # ensure no prior breakdown
    result = handle_template_command("/template save my-new-template")
    assert "No recent agent breakdown" in result


def test_handle_template_delete():
    from tools.templates import save_template
    from orchestrator import handle_template_command
    save_template("bye-bye", SAMPLE_AGENTS)
    result = handle_template_command("/template delete bye-bye")
    assert "deleted" in result.lower()
    result2 = handle_template_command("/template delete bye-bye")
    assert "not found" in result2.lower()


def test_non_template_command_returns_none():
    from orchestrator import handle_template_command
    assert handle_template_command("what time is it") is None
    assert handle_template_command("/rules list") is None


# ── Built-in templates present ────────────────────────────────────────────────

def test_builtin_templates_exist(monkeypatch):
    """The 4 seeded global templates should load correctly."""
    import tools.templates as tmod
    import orchestrator as orch
    # Un-patch: use real _JARVIS_ROOT so we can check the actual files
    real_root = os.path.dirname(os.path.abspath(
        __import__("config").MEMORY_FILE
    ))
    monkeypatch.setattr(tmod, "_JARVIS_ROOT", real_root)

    templates = tmod.list_templates()
    names = {t["name"] for t in templates}
    assert "new-angular-feature" in names
    assert "dotnet-endpoint" in names
    assert "angular-auth-guard" in names
    assert "dotnet-ef-migration" in names
