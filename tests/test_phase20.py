"""
tests/test_phase20.py — Phase 20: Deeper Learning (Ratings Upgrade).

Tests:
  - tools/ratings.py: save_rating(roles=), extract_agent_roles(), enhanced format_ratings_for_injection()
  - server.py: POST /rate endpoint, timed rate_prompt (30s after job completion)
"""
import json
import threading
import time

import pytest
import memory


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def isolated_memory(tmp_path):
    orig = memory.MEMORY_FILE
    memory.MEMORY_FILE = str(tmp_path / "memory.json")
    yield
    memory.MEMORY_FILE = orig


# ── tools/ratings: save_rating with roles ─────────────────────────────────────

def test_save_rating_stores_roles():
    from tools.ratings import save_rating, list_ratings
    save_rating("add auth service", 3, 4, roles=["component", "service", "test"])
    entries = list_ratings()
    assert entries[0]["successful_roles"] == ["component", "service", "test"]


def test_save_rating_roles_optional():
    """Passing no roles → no successful_roles key stored."""
    from tools.ratings import save_rating, list_ratings
    save_rating("add auth service", 3, 4)
    entries = list_ratings()
    assert "successful_roles" not in entries[0]


# ── tools/ratings: extract_agent_roles ────────────────────────────────────────

def test_extract_agent_roles_identifies_service():
    from tools.ratings import extract_agent_roles
    defs = [{"id": "agent_1", "task": "create auth service and provider"}]
    assert extract_agent_roles(defs) == ["service"]


def test_extract_agent_roles_identifies_test_and_component():
    from tools.ratings import extract_agent_roles
    defs = [
        {"id": "agent_1", "task": "create login component with form"},
        {"id": "agent_2", "task": "write unit tests for login"},
    ]
    roles = extract_agent_roles(defs)
    assert roles[0] == "component"
    assert roles[1] == "test"


def test_extract_agent_roles_falls_back_to_general():
    from tools.ratings import extract_agent_roles
    defs = [{"id": "agent_1", "task": "do something vague"}]
    assert extract_agent_roles(defs) == ["general"]


# ── tools/ratings: enhanced format_ratings_for_injection ──────────────────────

def test_format_ratings_constraint_for_two_low_rated():
    """≥2 low-rated (≤2) entries → CONSTRAINT injected."""
    from tools.ratings import format_ratings_for_injection
    ratings = [
        {"task_summary": "add feature A", "agent_count": 6, "rating": 1},
        {"task_summary": "add feature B", "agent_count": 5, "rating": 2},
    ]
    result = format_ratings_for_injection(ratings)
    assert "CONSTRAINT" in result
    assert "agents" in result


def test_format_ratings_hint_for_all_high_rated():
    """All relevant entries rated ≥4 → HINT injected."""
    from tools.ratings import format_ratings_for_injection
    ratings = [
        {"task_summary": "add component", "agent_count": 3, "rating": 5},
        {"task_summary": "add service",   "agent_count": 3, "rating": 4},
    ]
    result = format_ratings_for_injection(ratings)
    assert "HINT" in result
    assert "worked well" in result


def test_format_ratings_role_suggestion_from_high_rated():
    """successful_roles from high-rated entries appear as suggestion."""
    from tools.ratings import format_ratings_for_injection
    ratings = [
        {"task_summary": "auth feature", "agent_count": 2, "rating": 5,
         "successful_roles": ["component", "service"]},
    ]
    result = format_ratings_for_injection(ratings)
    assert "work best with" in result
    assert "component" in result


def test_format_ratings_no_constraint_when_mixed():
    """One low-rated, one high-rated → neither CONSTRAINT nor HINT."""
    from tools.ratings import format_ratings_for_injection
    ratings = [
        {"task_summary": "task A", "agent_count": 4, "rating": 2},
        {"task_summary": "task B", "agent_count": 3, "rating": 5},
    ]
    result = format_ratings_for_injection(ratings)
    assert "CONSTRAINT" not in result
    assert "HINT" not in result


# ── server.py: POST /rate endpoint ────────────────────────────────────────────

def _post_json(port, path, body):
    import urllib.request
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req) as r:
        return r.status, json.loads(r.read())


def test_rate_endpoint_saves_rating_and_marks_job_rated():
    """POST /rate saves the rating and marks job so rate_prompt disappears."""
    import server as srv
    import tools.agent_jobs as jobs
    import tools.ratings as rat

    # Manufacture a completed job
    job_id = jobs.generate_job_id()
    jobs.create_job(job_id, "/fake/ws", task="add angular component")
    jobs.register_agents(job_id, [
        {"id": "agent_1", "task": "create login component", "depends_on": []},
    ])
    jobs.update_job_status(job_id, "done", summary={"succeeded": 1, "failed": 0, "total": 1})

    httpd = srv.JarvisHTTPServer(('127.0.0.1', 0), srv.JarvisHTTPHandler)
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.handle_request, daemon=True)
    t.start()

    status, data = _post_json(port, "/rate", {"job_id": job_id, "rating": 4})
    httpd.server_close()

    assert status == 200
    assert data.get("ok") is True
    assert job_id in srv._rated_job_ids
    ratings = rat.list_ratings()
    assert len(ratings) == 1
    assert ratings[0]["rating"] == 4


# ── server.py: timed rate_prompt ──────────────────────────────────────────────

def test_rate_prompt_absent_immediately_after_completion():
    """rate_prompt not returned until 30s have passed."""
    import server as srv
    import tools.agent_jobs as jobs

    job_id = jobs.generate_job_id()
    jobs.create_job(job_id, "/fake/ws", task="do something")
    jobs.update_job_status(job_id, "done", summary={"succeeded": 1, "failed": 0, "total": 1})
    # finished_at is now — 0s elapsed → no rate_prompt yet

    httpd = srv.JarvisHTTPServer(('127.0.0.1', 0), srv.JarvisHTTPHandler)
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.handle_request, daemon=True)
    t.start()

    import urllib.request
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/agents/status?job_id={job_id}") as r:
        data = json.loads(r.read())
    httpd.server_close()

    assert "rate_prompt" not in data


def test_rate_prompt_present_after_30s():
    """rate_prompt=True returned once ≥30s have elapsed since job completion."""
    import server as srv
    import tools.agent_jobs as jobs

    job_id = jobs.generate_job_id()
    jobs.create_job(job_id, "/fake/ws", task="do something")
    jobs.update_job_status(job_id, "done", summary={"succeeded": 1, "failed": 0, "total": 1})
    # Backdate finished_at by 35 seconds
    with jobs._lock:
        jobs._jobs[job_id]["finished_at"] = time.time() - 35

    srv._rated_job_ids.discard(job_id)

    httpd = srv.JarvisHTTPServer(('127.0.0.1', 0), srv.JarvisHTTPHandler)
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.handle_request, daemon=True)
    t.start()

    import urllib.request
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/agents/status?job_id={job_id}") as r:
        data = json.loads(r.read())
    httpd.server_close()

    assert data.get("rate_prompt") is True
