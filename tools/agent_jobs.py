"""
tools/agent_jobs.py — Phase 12: In-memory agent job store.
Phase 17: Completed jobs persisted to disk in agent_jobs_history.json.

Tracks the state of every agent execution started from VS Code.
Server threads write updates; /agents/status endpoint reads them.
"""

import json
import os
import threading
import time
import uuid
from typing import Optional

_JARVIS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_HISTORY_FILE = os.path.join(_JARVIS_ROOT, "sessions", "agent_jobs_history.json")
_MAX_HISTORY = 100

# job_id -> job_state dict
_jobs: dict = {}
_lock = threading.Lock()


# ── Job lifecycle ─────────────────────────────────────────────────────────────

def generate_job_id() -> str:
    return "job_" + uuid.uuid4().hex[:8]


def create_job(job_id: str, workspace_root: str, task: str = "") -> dict:
    """
    Register a new job before the background thread starts.
    Agents are populated later once breakdown_into_agents() returns.
    """
    job = {
        "job_id": job_id,
        "task": task,
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
    job_snapshot: Optional[dict] = None
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
            job_snapshot = {k: v for k, v in job.items() if k != "agents"}
            job_snapshot["agents"] = {
                aid: {"id": aid, "task": a["task"], "status": a["status"]}
                for aid, a in job["agents"].items()
            }
    if job_snapshot:
        _append_to_history(job_snapshot)


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
        return dict(job) if job else None


def list_active_jobs() -> list:
    with _lock:
        return [dict(j) for j in _jobs.values()
                if j["status"] in ("starting", "running")]


# ── History ───────────────────────────────────────────────────────────────────

def _append_to_history(job_snapshot: dict) -> None:
    """Append a completed job to the history file, trim to _MAX_HISTORY."""
    try:
        os.makedirs(os.path.dirname(_HISTORY_FILE), exist_ok=True)
        try:
            with open(_HISTORY_FILE, encoding="utf-8") as f:
                history = json.load(f)
            if not isinstance(history, list):
                history = []
        except (FileNotFoundError, json.JSONDecodeError):
            history = []

        agents_list = list(job_snapshot.get("agents", {}).values())
        summary = job_snapshot.get("summary") or {}
        record = {
            "job_id": job_snapshot["job_id"],
            "task": job_snapshot.get("task", ""),
            "workspace": job_snapshot.get("workspace_root", ""),
            "agents": agents_list,
            "outcome": "success" if job_snapshot["status"] == "done" else "failed",
            "started_at": job_snapshot.get("started_at"),
            "finished_at": job_snapshot.get("finished_at"),
            "total_tokens": summary.get("total_tokens", 0),
        }
        history.append(record)
        # Keep only the most recent _MAX_HISTORY entries
        history = history[-_MAX_HISTORY:]
        with open(_HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f)
    except Exception:
        pass


def list_job_history(limit: int = 20) -> list:
    """Return up to `limit` most-recently-completed jobs from history file."""
    try:
        with open(_HISTORY_FILE, encoding="utf-8") as f:
            history = json.load(f)
        if not isinstance(history, list):
            return []
        return history[-limit:][::-1]   # newest first
    except (FileNotFoundError, json.JSONDecodeError):
        return []


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
