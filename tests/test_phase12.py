"""
tests/test_phase12.py — Phase 12: VS Code Agent Execution

Tests:
  - tools/agent_jobs module
  - handle_complex_task_vscode (mocked Claude + Claude Code)
  - server.py /run-agents + /agents/status endpoints
  - AgentPool.execute_vscode (mocked agents)
"""

import json
import time
import threading
import pytest
from unittest.mock import patch, MagicMock


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def clear_jobs():
    """Reset the job store before each test."""
    import tools.agent_jobs as aj
    aj._jobs.clear()
    yield
    aj._jobs.clear()


@pytest.fixture
def sample_agent_defs():
    return [
        {"id": "agent_1", "task": "Do something", "depends_on": []},
        {"id": "agent_2", "task": "Do another thing", "depends_on": ["agent_1"]},
    ]


# ── Group 1: agent_jobs module ────────────────────────────────────────────────

def test_create_job_returns_correct_shape():
    from tools.agent_jobs import create_job
    job = create_job("j1", "/some/path")
    assert job["job_id"] == "j1"
    assert job["status"] == "starting"
    assert job["workspace_root"] == "/some/path"
    assert job["agents"] == {}
    assert job["summary"] is None
    assert job["error"] is None


def test_create_job_agents_start_pending(sample_agent_defs):
    from tools.agent_jobs import create_job, register_agents, get_job
    create_job("j2", "/path")
    register_agents("j2", sample_agent_defs)
    job = get_job("j2")
    assert "agent_1" in job["agents"]
    assert job["agents"]["agent_1"]["status"] == "pending"
    assert job["agents"]["agent_2"]["depends_on"] == ["agent_1"]


def test_update_job_status_changes_field():
    from tools.agent_jobs import create_job, update_job_status, get_job
    create_job("j3", "")
    update_job_status("j3", "running")
    assert get_job("j3")["status"] == "running"


def test_update_job_status_sets_finished_at():
    from tools.agent_jobs import create_job, update_job_status, get_job
    create_job("j4", "")
    update_job_status("j4", "done")
    assert get_job("j4")["finished_at"] is not None


def test_update_agent_status_changes_field(sample_agent_defs):
    from tools.agent_jobs import create_job, register_agents, update_agent_status, get_job
    create_job("j5", "")
    register_agents("j5", sample_agent_defs)
    update_agent_status("j5", "agent_1", status="running")
    assert get_job("j5")["agents"]["agent_1"]["status"] == "running"


def test_update_agent_status_sets_started_at_on_running(sample_agent_defs):
    from tools.agent_jobs import create_job, register_agents, update_agent_status, get_job
    create_job("j6", "")
    register_agents("j6", sample_agent_defs)
    update_agent_status("j6", "agent_1", status="running")
    assert get_job("j6")["agents"]["agent_1"]["started_at"] is not None


def test_get_job_returns_none_for_unknown():
    from tools.agent_jobs import get_job
    assert get_job("nonexistent") is None


def test_cleanup_old_jobs_removes_finished():
    from tools.agent_jobs import create_job, update_job_status, cleanup_old_jobs, get_job
    create_job("old_job", "")
    update_job_status("old_job", "done")
    import tools.agent_jobs as aj
    aj._jobs["old_job"]["finished_at"] = time.time() - 9999
    removed = cleanup_old_jobs(max_age_seconds=60)
    assert removed == 1
    assert get_job("old_job") is None


def test_generate_job_id_format():
    from tools.agent_jobs import generate_job_id
    jid = generate_job_id()
    assert jid.startswith("job_")
    assert len(jid) == 12   # "job_" + 8 hex chars


# ── Group 2: handle_complex_task_vscode (mocked) ─────────────────────────────

def _mock_agent_defs():
    return [{"id": "a1", "task": "Task A", "depends_on": []}]


@patch("orchestrator.verify_claude_code_installed", return_value=False)
def test_vscode_handler_marks_failed_when_no_claude_code(mock_verify, tmp_path):
    from tools.agent_jobs import create_job, get_job
    from orchestrator import handle_complex_task_vscode
    create_job("jtest1", str(tmp_path))
    handle_complex_task_vscode("do something complex", str(tmp_path), "jtest1")
    job = get_job("jtest1")
    assert job["status"] == "failed"
    assert "Claude Code" in job["error"]


@patch("orchestrator.verify_claude_code_installed", return_value=True)
@patch("orchestrator.breakdown_into_agents", side_effect=RuntimeError("API error"))
def test_vscode_handler_marks_failed_on_breakdown_error(mock_bkd, mock_ver, tmp_path):
    from tools.agent_jobs import create_job, get_job
    from orchestrator import handle_complex_task_vscode
    create_job("jtest2", str(tmp_path))
    handle_complex_task_vscode("complex task", str(tmp_path), "jtest2")
    job = get_job("jtest2")
    assert job["status"] == "failed"
    assert "API error" in job["error"]


@patch("orchestrator.verify_claude_code_installed", return_value=True)
@patch("orchestrator.breakdown_into_agents", return_value=(_mock_agent_defs(), {"input": 100, "output": 50}))
@patch("tools.project_scanner.scan_project", return_value={})
@patch("tools.project_scanner.get_context_string", return_value="")
@patch("agents.agent_pool.AgentPool.execute_vscode")
@patch("tools.handoff.cleanup_handoff")
@patch("orchestrator.save_task_to_project")
def test_vscode_handler_registers_agents(
    mock_save, mock_cleanup, mock_exec, mock_ctx, mock_scan, mock_bkd, mock_ver, tmp_path
):
    mock_exec.return_value = {"total": 1, "succeeded": 1, "failed": 0, "skipped": 0}
    from tools.agent_jobs import create_job, get_job
    from orchestrator import handle_complex_task_vscode

    create_job("jtest3", str(tmp_path))
    handle_complex_task_vscode("build something", str(tmp_path), "jtest3")

    # execute_vscode was called with the job_id
    assert mock_exec.called


# ── Group 3: server endpoints ─────────────────────────────────────────────────

class _ServerFixture:
    """Minimal test harness for server endpoints using port=0."""
    def __init__(self):
        import server as srv
        self.server = srv.JarvisHTTPServer(("localhost", 0), srv.JarvisHTTPHandler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.handle_request, daemon=True)
        self.thread.start()

    def stop(self):
        self.server.server_close()


def _post(port, path, body):
    import urllib.request
    data = json.dumps(body).encode()
    req = urllib.request.Request(f"http://localhost:{port}{path}", data=data,
                                  headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read())


def _get(port, path):
    import urllib.request
    with urllib.request.urlopen(f"http://localhost:{port}{path}", timeout=5) as r:
        return json.loads(r.read())


@patch("server.start_vscode_agent_job", return_value="job_abc12345")
def test_run_agents_returns_job_id(mock_start):
    fix = _ServerFixture()
    try:
        data = _post(fix.port, "/run-agents", {"message": "build the feature", "workspace_root": "/proj"})
        assert data["job_id"] == "job_abc12345"
        assert data["status"] == "starting"
    finally:
        fix.stop()


@patch("server.start_vscode_agent_job", return_value="job_abc12345")
def test_run_agents_missing_message_returns_400(mock_start):
    import urllib.request, urllib.error
    fix = _ServerFixture()
    try:
        try:
            _post(fix.port, "/run-agents", {"workspace_root": "/proj"})
            assert False, "Should have raised"
        except urllib.error.HTTPError as e:
            assert e.code == 400
    finally:
        fix.stop()


def test_agents_status_returns_job_state():
    from tools.agent_jobs import create_job
    create_job("jobXY", "/path")
    fix = _ServerFixture()
    try:
        data = _get(fix.port, "/agents/status?job_id=jobXY")
        assert data["job_id"] == "jobXY"
        assert data["status"] == "starting"
    finally:
        fix.stop()


def test_agents_status_unknown_job_returns_404():
    import urllib.request, urllib.error
    fix = _ServerFixture()
    try:
        try:
            _get(fix.port, "/agents/status?job_id=nope")
            assert False, "Should have raised"
        except urllib.error.HTTPError as e:
            assert e.code == 404
    finally:
        fix.stop()


@patch("orchestrator.process_for_vscode", return_value="__COMPLEX_TASK__")
@patch("server.start_vscode_agent_job", return_value="job_complex1")
@patch("orchestrator.get_last_session_id", return_value="sess_test")
@patch("orchestrator.get_last_session_name", return_value="Test Session")
@patch("orchestrator.get_last_files_written", return_value=[])
@patch("orchestrator.get_pending_commands", return_value=[])
def test_chat_complex_task_returns_agent_job_id(*mocks):
    fix = _ServerFixture()
    try:
        data = _post(fix.port, "/chat", {"message": "build the whole app", "workspace_root": "/proj"})
        assert data["agent_job_id"] == "job_complex1"
        assert data["response"] is None
    finally:
        fix.stop()


# ── Group 4: AgentPool.execute_vscode ────────────────────────────────────────

@patch("agents.agent.run_claude_code")
def test_execute_vscode_marks_job_running(mock_run, tmp_path):
    mock_run.return_value = {"success": True, "output": "done", "error": "", "tokens": None}
    from tools.agent_jobs import create_job, register_agents, get_job
    from agents.agent import Agent
    from agents.agent_pool import AgentPool

    job_id = "jpool1"
    agent_defs = [{"id": "a1", "task": "task", "depends_on": []}]
    create_job(job_id, str(tmp_path))
    register_agents(job_id, agent_defs)

    agents = [Agent(id="a1", task="task", working_dir=str(tmp_path))]
    pool = AgentPool(agents=agents, working_dir=str(tmp_path))
    pool.execute_vscode(job_id)

    job = get_job(job_id)
    assert job["status"] == "done"


@patch("agents.agent.run_claude_code")
def test_execute_vscode_marks_job_done_after_completion(mock_run, tmp_path):
    mock_run.return_value = {"success": True, "output": "done", "error": "", "tokens": None}
    from tools.agent_jobs import create_job, register_agents, get_job
    from agents.agent import Agent
    from agents.agent_pool import AgentPool

    job_id = "jpool2"
    agent_defs = [
        {"id": "a1", "task": "first", "depends_on": []},
        {"id": "a2", "task": "second", "depends_on": ["a1"]},
    ]
    create_job(job_id, str(tmp_path))
    register_agents(job_id, agent_defs)

    agents = [
        Agent(id="a1", task="first", working_dir=str(tmp_path)),
        Agent(id="a2", task="second", depends_on=["a1"], working_dir=str(tmp_path)),
    ]
    pool = AgentPool(agents=agents, working_dir=str(tmp_path))
    summary = pool.execute_vscode(job_id)

    assert summary["succeeded"] == 2
    assert get_job(job_id)["status"] == "done"


@patch("agents.agent.run_claude_code")
def test_execute_vscode_skips_dependents_on_failure(mock_run, tmp_path):
    # a1 fails → a2 should be skipped
    mock_run.return_value = {"success": False, "output": "", "error": "oops", "tokens": None}
    from tools.agent_jobs import create_job, register_agents, get_job
    from agents.agent import Agent
    from agents.agent_pool import AgentPool

    job_id = "jpool3"
    agent_defs = [
        {"id": "a1", "task": "first", "depends_on": []},
        {"id": "a2", "task": "second", "depends_on": ["a1"]},
    ]
    create_job(job_id, str(tmp_path))
    register_agents(job_id, agent_defs)

    agents = [
        Agent(id="a1", task="first", working_dir=str(tmp_path)),
        Agent(id="a2", task="second", depends_on=["a1"], working_dir=str(tmp_path)),
    ]
    pool = AgentPool(agents=agents, working_dir=str(tmp_path))
    summary = pool.execute_vscode(job_id)

    assert summary["skipped"] >= 1
