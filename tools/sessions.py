# tools/sessions.py
# Phase 10 — Per-project and global chat session persistence.
# Sessions are stored in d:/Personal/Jarvis/sessions/ alongside memory.json.
#
# Layout:
#   sessions/
#     global/
#       _active.json          {"active_session_id": "sess_..."}
#       sess_<id>.json
#     projects/
#       <workspace_hash>/     MD5-12 of normalized workspace_root
#         _summary.json       cumulative project summary + session index
#         sess_<id>.json

import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

from config import MEMORY_FILE

# Jarvis root = directory that contains memory.json
_JARVIS_ROOT = os.path.dirname(os.path.abspath(MEMORY_FILE))


# ── Utilities ─────────────────────────────────────────────────────────────────

def sessions_dir() -> str:
    """Return (and create) the sessions/ root directory."""
    base = os.path.join(_JARVIS_ROOT, "sessions")
    os.makedirs(os.path.join(base, "global"), exist_ok=True)
    os.makedirs(os.path.join(base, "projects"), exist_ok=True)
    return base


def workspace_hash(workspace_root: str) -> str:
    """
    Stable 12-char MD5 hex of the lowercase normalised workspace_root.
    Used as the directory name under sessions/projects/.
    """
    normalized = workspace_root.lower().replace("\\", "/").rstrip("/")
    return hashlib.md5(normalized.encode()).hexdigest()[:12]


def generate_session_id() -> str:
    """Return a new unique session ID: 'sess_<8-char-hex>'."""
    return "sess_" + str(uuid.uuid4()).replace("-", "")[:8]


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


# ── Path helpers ──────────────────────────────────────────────────────────────

def _global_dir() -> str:
    d = os.path.join(sessions_dir(), "global")
    os.makedirs(d, exist_ok=True)
    return d


def _project_sessions_dir(workspace_root: str) -> str:
    d = os.path.join(sessions_dir(), "projects", workspace_hash(workspace_root))
    os.makedirs(d, exist_ok=True)
    return d


def _project_summary_path(workspace_root: str) -> str:
    return os.path.join(_project_sessions_dir(workspace_root), "_summary.json")


def _session_path(session_id: str, workspace_root: str, is_global: bool) -> str:
    if is_global:
        return os.path.join(_global_dir(), f"{session_id}.json")
    return os.path.join(_project_sessions_dir(workspace_root), f"{session_id}.json")


# ── Session CRUD ──────────────────────────────────────────────────────────────

def create_session(
    workspace_root: str,
    is_global: bool = False,
    project_name: str = "",
) -> dict:
    """
    Create and persist a new empty session.
    Returns the full session dict as written to disk.
    """
    if not project_name and workspace_root:
        project_name = os.path.basename(workspace_root.rstrip("/\\")) or workspace_root
    session_id = generate_session_id()
    now = _now_iso()
    session = {
        "id": session_id,
        "name": "",
        "workspace_root": workspace_root,
        "project_name": project_name,
        "is_global": is_global,
        "created_at": now,
        "updated_at": now,
        "messages": [],
        "summary": "",
        "token_total": 0,
    }
    _write_json(_session_path(session_id, workspace_root, is_global), session)
    return session


def get_session(
    session_id: str,
    workspace_root: str,
    is_global: bool,
) -> Optional[dict]:
    """Load a session from disk. Returns None if missing or corrupt."""
    path = _session_path(session_id, workspace_root, is_global)
    return _read_json(path)


def save_session(session: dict) -> None:
    """Persist a session dict to its file."""
    path = _session_path(
        session["id"],
        session.get("workspace_root", ""),
        session.get("is_global", False),
    )
    _write_json(path, session)


def append_message(
    session_id: str,
    workspace_root: str,
    is_global: bool,
    role: str,
    content: str,
    token_count: int = 0,
) -> Optional[dict]:
    """
    Append a message to a session and save.
    Keeps at most the last 100 messages.
    Returns the updated session dict, or None if not found.
    """
    session = get_session(session_id, workspace_root, is_global)
    if session is None:
        return None
    session["messages"].append({
        "role": role,
        "content": content,
        "ts": _now_iso(),
    })
    session["messages"] = session["messages"][-100:]
    session["updated_at"] = _now_iso()
    session["token_total"] = session.get("token_total", 0) + token_count
    save_session(session)
    return session


def update_session_name(
    session_id: str,
    workspace_root: str,
    is_global: bool,
    name: str,
) -> None:
    """Update the session name and save."""
    session = get_session(session_id, workspace_root, is_global)
    if session is None:
        return
    session["name"] = name[:80]
    save_session(session)


def close_session(
    session_id: str,
    workspace_root: str,
    is_global: bool,
) -> str:
    """
    Finalise a session: generate a 2-3 sentence Haiku summary and persist it.
    For project sessions also updates the project _summary.json.
    Returns the generated summary, or "" on failure. Never raises.
    """
    try:
        session = get_session(session_id, workspace_root, is_global)
        if not session or not session.get("messages"):
            return ""

        summary = _generate_session_summary(session["messages"])
        if summary:
            session["summary"] = summary
            save_session(session)

        if not is_global and workspace_root:
            update_project_summary(workspace_root, session)

        return summary
    except Exception:
        return ""


# ── Session listing ───────────────────────────────────────────────────────────

def list_project_sessions(workspace_root: str) -> list:
    """Return all project sessions sorted by updated_at descending."""
    d = _project_sessions_dir(workspace_root)
    return _load_session_files(d, workspace_root, is_global=False)


def list_global_sessions() -> list:
    """Return all global sessions sorted by updated_at descending."""
    d = _global_dir()
    return _load_session_files(d, workspace_root="", is_global=True)


def list_all_sessions() -> dict:
    """
    Return all sessions grouped for the history drawer:
    {
      "global": [...],
      "projects": {
        "D:/path": {"project_name": "...", "sessions": [...]},
        ...
      }
    }
    """
    result = {
        "global": list_global_sessions(),
        "projects": {},
    }

    projects_root = os.path.join(sessions_dir(), "projects")
    if not os.path.isdir(projects_root):
        return result

    for hash_dir in os.scandir(projects_root):
        if not hash_dir.is_dir():
            continue
        summary  = _read_json(os.path.join(hash_dir.path, "_summary.json"))
        sessions = _load_session_files(hash_dir.path, workspace_root="", is_global=False)
        if not sessions:
            continue

        # Prefer _summary.json, fall back to the first session's own workspace_root
        workspace_root = (summary or {}).get("workspace_root", "") or sessions[0].get("workspace_root", "")
        project_name   = (
            (summary or {}).get("project_name", "")
            or sessions[0].get("project_name", "")
            or os.path.basename(workspace_root.rstrip("/\\"))
            or hash_dir.name
        )

        result["projects"][workspace_root or hash_dir.name] = {
            "project_name": project_name,
            "sessions": sessions,
        }

    # Sort project groups by their most-recently-updated session
    result["projects"] = dict(
        sorted(
            result["projects"].items(),
            key=lambda kv: (kv[1]["sessions"][0]["updated_at"] if kv[1]["sessions"] else ""),
            reverse=True,
        )
    )
    return result


def _load_session_files(directory: str, workspace_root: str, is_global: bool) -> list:
    sessions = []
    if not os.path.isdir(directory):
        return sessions
    for entry in os.scandir(directory):
        if not entry.name.endswith(".json"):
            continue
        if entry.name.startswith("_"):
            continue  # skip _summary.json, _active.json
        sess = _read_json(entry.path)
        if sess and "id" in sess:
            sessions.append(sess)
    return sorted(sessions, key=lambda s: s.get("updated_at", ""), reverse=True)


# ── Active session tracking ───────────────────────────────────────────────────

def get_active_session_id(workspace_root: str, is_global: bool) -> str:
    """Return the active session ID for the given context, or "" if not set."""
    if is_global:
        data = _read_json(os.path.join(_global_dir(), "_active.json"))
        return (data or {}).get("active_session_id", "")
    summary = _read_json(_project_summary_path(workspace_root))
    return (summary or {}).get("active_session_id", "")


def set_active_session(
    session_id: str,
    workspace_root: str,
    is_global: bool,
) -> None:
    """Persist the active session ID for the given context."""
    if is_global:
        _write_json(os.path.join(_global_dir(), "_active.json"),
                    {"active_session_id": session_id})
        return
    summary = get_project_summary(workspace_root)
    summary["active_session_id"] = session_id
    _write_json(_project_summary_path(workspace_root), summary)


# ── Project summary ───────────────────────────────────────────────────────────

_DEFAULT_SUMMARY = {
    "workspace_root": "",
    "project_name": "",
    "last_updated": "",
    "cumulative_summary": "",
    "active_session_id": "",
    "sessions": [],
}


def get_project_summary(workspace_root: str) -> dict:
    """Load _summary.json for a project, or return a default structure."""
    data = _read_json(_project_summary_path(workspace_root))
    if data:
        return data
    import copy
    d = copy.deepcopy(_DEFAULT_SUMMARY)
    d["workspace_root"] = workspace_root
    d["project_name"] = os.path.basename(workspace_root.rstrip("/\\")) or workspace_root
    return d


def get_project_summary_text(workspace_root: str) -> str:
    """Return the cumulative_summary string, or '' if none."""
    return get_project_summary(workspace_root).get("cumulative_summary", "")


def update_project_summary(workspace_root: str, session: dict) -> None:
    """
    Update _summary.json after a session closes.
    Re-generates cumulative_summary via Haiku. Best-effort, never raises.
    """
    try:
        summary = get_project_summary(workspace_root)

        # Upsert session index entry
        session_entry = {
            "id":         session["id"],
            "name":       session.get("name", ""),
            "summary":    session.get("summary", ""),
            "created_at": session.get("created_at", ""),
            "updated_at": session.get("updated_at", ""),
        }
        existing_ids = {s["id"] for s in summary["sessions"]}
        if session["id"] in existing_ids:
            summary["sessions"] = [
                session_entry if s["id"] == session["id"] else s
                for s in summary["sessions"]
            ]
        else:
            summary["sessions"].append(session_entry)

        # Re-generate cumulative summary via Haiku
        new_cumulative = _generate_project_summary(
            existing_summary=summary.get("cumulative_summary", ""),
            session_name=session.get("name", ""),
            session_summary=session.get("summary", ""),
        )
        if new_cumulative:
            summary["cumulative_summary"] = new_cumulative

        summary["last_updated"] = _now_iso()
        if not summary.get("workspace_root"):
            summary["workspace_root"] = workspace_root
        if not summary.get("project_name"):
            summary["project_name"] = os.path.basename(workspace_root.rstrip("/\\")) or workspace_root

        _write_json(_project_summary_path(workspace_root), summary)
    except Exception:
        pass


# ── Auto-naming ───────────────────────────────────────────────────────────────

def auto_name_from_first_message(content: str) -> str:
    """Generate a quick session name from the first user message. No API call."""
    name = content.replace("\n", " ").strip()
    return name[:50]


def generate_better_name(messages: list) -> str:
    """
    After a few exchanges, ask Haiku for a concise 6-word title.
    Returns '' on failure.
    """
    try:
        import anthropic
        from config import ANTHROPIC_API_KEY, MODEL_HAIKU
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        excerpt = "\n".join(
            f"{m['role'].upper()}: {m['content'][:150]}"
            for m in messages[:6]
        )
        resp = client.messages.create(
            model=MODEL_HAIKU,
            max_tokens=20,
            system="Give this conversation a short title (max 6 words). Return only the title.",
            messages=[{"role": "user", "content": excerpt}],
        )
        return resp.content[0].text.strip()[:80]
    except Exception:
        return ""


# ── Private Haiku helpers ─────────────────────────────────────────────────────

def _generate_session_summary(messages: list) -> str:
    """Summarise a session in 2-3 sentences using Haiku. Returns '' on failure."""
    try:
        import anthropic
        from config import ANTHROPIC_API_KEY, MODEL_HAIKU
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        excerpt = "\n".join(
            f"{m['role'].upper()}: {m['content'][:200]}"
            for m in messages[-20:]
        )
        resp = client.messages.create(
            model=MODEL_HAIKU,
            max_tokens=150,
            system="Summarise this conversation in 2-3 concise sentences. No filler.",
            messages=[{"role": "user", "content": excerpt}],
        )
        return resp.content[0].text.strip()
    except Exception:
        return ""


def _generate_project_summary(
    existing_summary: str,
    session_name: str,
    session_summary: str,
) -> str:
    """Update a project's cumulative summary via Haiku. Returns '' on failure."""
    try:
        import anthropic
        from config import ANTHROPIC_API_KEY, MODEL_HAIKU
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        prompt = (
            f"Existing project summary:\n{existing_summary or '(none yet)'}\n\n"
            f"New session: {session_name}\n{session_summary}\n\n"
            f"Update the project summary to include this session. "
            f"Keep it 3-5 sentences total. Return only the updated summary."
        )
        resp = client.messages.create(
            model=MODEL_HAIKU,
            max_tokens=200,
            system="You maintain running project summaries. Be concise and factual.",
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.content[0].text.strip()
    except Exception:
        return ""


# ── JSON helpers ──────────────────────────────────────────────────────────────

def _read_json(path: str) -> Optional[dict]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _write_json(path: str, data: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
