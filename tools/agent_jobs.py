"""
tools/agent_jobs.py — Phase 12: In-memory agent job store.

Tracks the state of every agent execution started from VS Code.
Server threads write updates; /agents/status endpoint reads them.
No disk I/O — state lives only while server.py is running.
"""

import threading
import time
import uuid
from typing import Optional

# job_id -> job_state dict
_jobs: dict = {}
_lock = threading.Lock()


# ── Job lifecycle ─────────────────────────────────────────────────────────────

def generate_job_id() -> str:
    return "job_" + uuid.uuid4().hex[:8]


def create_job(job_id: str, workspace_root: str) -> dict:
    """
    Register a new job before the background thread starts.
    Agents are populated later once breakdown_into_agents() returns.
    """
    job = {
        "job_id": job_id,
        "status": "starting",   # starting | running | done | failed
        "workspace_root": workspace_root,
        "started_at": time.time(),
        "finished_at": None,
        "agents": {},           # agent_id -> agent_state (populated during breakdown)
        "summary": None,
        "error": None,
    }
    with _lock:
        _jobs[job_id] = job
    return job


def register_agents(job_id: str, agent_defs: list) -> None:
    """Populate the agents dict once breakdown_into_agents() returns."""
    with _lock:
        job = _jobs.get(job_id)
        if not job:
            return
        # Reset so we get the real defs (not the placeholder from create_job)
        job["agents"] = {
            a["id"]: {
                "id": a["id"],
                "task": a["task"][:120],
                "depends_on": a.get("depends_on", []),
                "status": "pending",   # pending | running | success | failed | skipped
                "output": "",
                "error": "",
                "files_created": [],
                "files_modified": [],
                "started_at": None,
                "finished_at": None,
            }
            for a in agent_defs
        }


def update_job_status(job_id: str, status: str,
                      summary: Optional[dict] = None,
                      error: Optional[str] = None) -> None:
    with _lock:
        job = _jobs.get(job_id)
        if not job:
            return
        job["status"] = status
        if summary is not None:
            job["summary"] = summary
        if error is not None:
            job["error"] = error
        if status in ("done", "failed"):
            job["finished_at"] = time.time()


def update_agent_status(job_id: str, agent_id: str, **kwargs) -> None:
    """
    Update any subset of agent fields.
    Common kwargs: status, output, error, files_created, files_modified.
    Automatically sets started_at / finished_at based on status transitions.
    """
    with _lock:
        job = _jobs.get(job_id)
        if not job or agent_id not in job["agents"]:
            return
        agent = job["agents"][agent_id]
        agent.update(kwargs)
        if kwargs.get("status") == "running" and agent["started_at"] is None:
            agent["started_at"] = time.time()
        if kwargs.get("status") in ("success", "failed", "skipped") and agent["finished_at"] is None:
            agent["finished_at"] = time.time()


# ── Reads ─────────────────────────────────────────────────────────────────────

def get_job(job_id: str) -> Optional[dict]:
    with _lock:
        job = _jobs.get(job_id)
        # Return a shallow-ish copy to avoid external mutation
        return dict(job) if job else None


def list_active_jobs() -> list:
    with _lock:
        return [dict(j) for j in _jobs.values()
                if j["status"] in ("starting", "running")]


# ── Maintenance ───────────────────────────────────────────────────────────────

def cleanup_old_jobs(max_age_seconds: int = 3600) -> int:
    """Remove finished jobs older than max_age_seconds. Returns count removed."""
    now = time.time()
    with _lock:
        stale = [
            jid for jid, j in _jobs.items()
            if j.get("finished_at") and now - j["finished_at"] > max_age_seconds
        ]
        for jid in stale:
            del _jobs[jid]
    return len(stale)
