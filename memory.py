# memory.py
# Handles persistent memory — this is how Jarvis remembers you
# across sessions. Stores preferences, projects, and history.

import copy
import json
import os
from datetime import datetime
from config import MEMORY_FILE, GITHUB_TOKEN, GIST_ID

# Phase 5.4: Pull memory from Gist only once per process lifetime
_synced_this_session: bool = False

# The real memory.json path — only sync to Gist when writing/reading THIS file.
# Tests change `memory.MEMORY_FILE` to a temp path; we must never push test data to Gist.
_CANONICAL_MEMORY_FILE: str = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "memory.json")
)

# Default memory structure for a new user
DEFAULT_MEMORY = {
    "user": {
        "name": "",
        "preferences": [],
        "experience_level": "intermediate",
        "rules": []            # Global rules — injected into every Claude call
    },
    "projects": [],
    "history": [],
    "last_session": ""
}

def load_memory():
    """Load memory from file, create default if doesn't exist.
    On first call per session, pulls from GitHub Gist if configured."""
    global _synced_this_session

    # Phase 5.4: Pull from Gist once per session (before reading the local file).
    # Guard: only sync when using the canonical memory.json — never during tests.
    _is_canonical = os.path.normpath(MEMORY_FILE) == _CANONICAL_MEMORY_FILE
    if GITHUB_TOKEN and GIST_ID and not _synced_this_session and _is_canonical:
        _synced_this_session = True
        try:
            from tools.sync import pull_memory
            pull_memory(MEMORY_FILE, GITHUB_TOKEN, GIST_ID)
        except Exception:
            pass  # Never crash — sync is optional

    if not os.path.exists(MEMORY_FILE):
        save_memory(copy.deepcopy(DEFAULT_MEMORY))
        return copy.deepcopy(DEFAULT_MEMORY)

    with open(MEMORY_FILE, "r") as f:
        return json.load(f)


def save_memory(memory: dict):
    """Save memory to file and push to GitHub Gist if configured."""
    with open(MEMORY_FILE, "w") as f:
        json.dump(memory, f, indent=2)

    # Phase 5.4: Push to Gist silently on every save.
    # Guard: only sync when using the canonical memory.json — never during tests.
    _is_canonical = os.path.normpath(MEMORY_FILE) == _CANONICAL_MEMORY_FILE
    if GITHUB_TOKEN and GIST_ID and _is_canonical:
        try:
            from tools.sync import push_memory
            push_memory(MEMORY_FILE, GITHUB_TOKEN, GIST_ID)
        except Exception:
            pass  # Never crash — sync is optional

def update_memory(key: str, value):
    """Update a specific key in memory."""
    memory = load_memory()
    memory[key] = value
    save_memory(memory)

def add_to_history(role: str, content: str):
    """Add a message to conversation history."""
    memory = load_memory()
    memory["history"].append({
        "role": role,
        "content": content
    })
    # Keep only last 50 messages to avoid token overflow
    memory["history"] = memory["history"][-50:]
    save_memory(memory)

def add_project(project: dict):
    """Add a new project to memory."""
    memory = load_memory()
    # Avoid duplicates by name
    existing = [p["name"] for p in memory["projects"]]
    if project["name"] not in existing:
        memory["projects"].append(project)
        save_memory(memory)

def save_task_to_project(project_path: str, task: str, agents_succeeded: int, agents_total: int, stack: list = None):
    """
    Save a completed task to the project's history in memory.
    Creates the project entry if it doesn't exist yet.
    """
    memory = load_memory()
    project_name = os.path.basename(project_path.rstrip("/\\")) or project_path

    # Find or create project entry
    project = next((p for p in memory["projects"] if p.get("path") == project_path), None)

    if not project:
        project = {
            "name": project_name,
            "path": project_path,
            "stack": stack or [],
            "tasks_completed": [],
            "last_updated": ""
        }
        memory["projects"].append(project)

    # Append task record
    project["tasks_completed"].append({
        "date": datetime.now().strftime("%Y-%m-%d"),
        "task": task[:200],
        "agents_succeeded": agents_succeeded,
        "agents_total": agents_total
    })
    project["last_updated"] = datetime.now().isoformat()
    if stack:
        project["stack"] = list(set(project.get("stack", []) + stack))

    save_memory(memory)


def learn_preference(key: str, value: str):
    """Save or update a user coding preference. e.g. learn_preference("css", "BEM methodology")"""
    memory = load_memory()
    prefs = memory["user"]["preferences"]
    if isinstance(prefs, list):
        memory["user"]["preferences"] = {}
    memory["user"]["preferences"][key] = value
    save_memory(memory)


def delete_project(name: str) -> str | None:
    """
    Delete a project from memory by name (case-insensitive partial match).
    Returns the deleted project name, or None if not found.
    """
    m = load_memory()
    name_lower = name.lower()
    for i, project in enumerate(m["projects"]):
        if name_lower in project["name"].lower():
            removed = m["projects"].pop(i)
            save_memory(m)
            return removed["name"]
    return None


def delete_all_projects() -> int:
    """Delete all projects from memory. Returns count of deleted projects."""
    m = load_memory()
    count = len(m["projects"])
    m["projects"] = []
    save_memory(m)
    return count


def get_project_by_name(name: str) -> dict | None:
    """Find a project by name (case-insensitive partial match)."""
    memory = load_memory()
    name_lower = name.lower()
    for project in memory["projects"]:
        if name_lower in project["name"].lower():
            return project
    return None


def search_projects(query: str) -> list:
    """Return all projects matching a query string (checks name and stack)."""
    memory = load_memory()
    query_lower = query.lower()
    results = []
    for project in memory["projects"]:
        name_match = query_lower in project["name"].lower()
        stack_match = any(query_lower in s.lower() for s in project.get("stack", []))
        if name_match or stack_match:
            results.append(project)
    return results


def get_all_projects_summary() -> str:
    """Compact multi-line summary of all known projects."""
    memory = load_memory()
    projects = memory["projects"]
    if not projects:
        return "No projects recorded yet."
    lines = []
    for p in projects:
        stack = ", ".join(p.get("stack", [])) or "unknown stack"
        tasks_count = len(p.get("tasks_completed", []))
        last = p.get("last_updated", "")[:10] if p.get("last_updated") else "never"
        lines.append(f"- {p['name']} ({stack}) — {tasks_count} tasks, last: {last}")
    return "\n".join(lines)


def update_last_session():
    """Update last_session timestamp to now."""
    memory = load_memory()
    memory["last_session"] = datetime.now().isoformat()
    save_memory(memory)


def get_daily_briefing() -> dict:
    """Return structured briefing data for startup display."""
    memory = load_memory()
    projects = memory["projects"]

    recent_project = None
    if projects:
        with_dates = [p for p in projects if p.get("last_updated")]
        if with_dates:
            recent_project = max(with_dates, key=lambda p: p["last_updated"])

    last_task = None
    if recent_project and recent_project.get("tasks_completed"):
        last_task = recent_project["tasks_completed"][-1]["task"]

    return {
        "user_name": memory["user"]["name"],
        "last_session": memory.get("last_session", ""),
        "recent_project": recent_project["name"] if recent_project else None,
        "recent_project_stack": recent_project.get("stack", []) if recent_project else [],
        "last_task": last_task,
        "total_projects": len(projects),
    }


def get_context_summary() -> str:
    """Build a context string from memory to feed to the orchestrator."""
    memory = load_memory()
    user = memory["user"]
    projects = memory["projects"]
    history = memory.get("history", [])

    # Format preferences — support both dict (new) and list (legacy) formats
    prefs = user.get("preferences", {})
    if isinstance(prefs, dict) and prefs:
        prefs_text = ", ".join(f"{k}: {v}" for k, v in prefs.items())
    elif isinstance(prefs, list) and prefs:
        prefs_text = ", ".join(prefs)
    else:
        prefs_text = "none set yet"

    # Build recent conversation summary (last 10 exchanges)
    history_text = ""
    if history:
        recent = history[-20:]
        history_text = "\n\nRecent conversation history:\n"
        for msg in recent:
            role = (user["name"] or "User") if msg["role"] == "user" else "Jarvis"
            history_text += f"{role}: {msg['content'][:200]}\n"

    # Global rules set by the user
    rules = user.get("rules", [])
    rules_section = ""
    if rules:
        rules_section = "\nUser-defined rules (always follow these):\n" + "\n".join(f"- {r}" for r in rules)

    # Inject only the 3 most recently active projects to keep the prompt lean
    recent_projects = sorted(
        projects, key=lambda p: p.get("last_updated", ""), reverse=True
    )[:3]

    summary = f"""You are Jarvis, a personal AI assistant for {user['name'] or 'the user'}.
User info: name={user['name'] or 'unknown'}, experience={user['experience_level']}
Known projects (3 most recent): {', '.join([p['name'] for p in recent_projects]) if recent_projects else 'none yet'}
Coding preferences: {prefs_text}{rules_section}
{history_text}
Important: You have persistent memory. You remember past conversations.
If the user asks what you discussed before, refer to the history above.

Interface features (tell the user about these when relevant):
- Terminal: type "attach <filepath>" before a question to include a file as context
- VS Code: use the + button (next to the input) to attach files or images; images go to Vision API
- VS Code: code responses show an "Apply to active file" button to write the code directly
- VS Code: Jarvis automatically sees the active file and workspace folder as context
- Commands (work in both terminal and VS Code chat):
    /rules                     — list, add, remove global rules
    /project rules             — list, add, remove rules for the current project only
    /memory                    — show full memory summary (projects, preferences, history count)
    /memory projects           — list all projects stored in memory
    /memory delete <name>      — permanently delete a project from memory by name
    /memory clear projects     — delete ALL projects from memory at once
    /memory clear history      — clear conversation history
    /memory preferences        — list saved preferences

Behavior rules:
- Be concise and direct. Answer only what was asked.
- Never mention server status, connection info, or whether you are online — the user already knows.
- Greet only once per session. Do not re-greet on every message.
- No filler phrases like "Great question!" or "Sure thing!"
- For CLI operations the user asks about, provide the exact command they should run. Format it in a code block. This is terminal-only mode — do NOT output raw XML or tool-call syntax.
- You CANNOT execute commands in terminal mode. Never say "I'll run it", "Noted", or imply you will execute anything. The user must copy-paste and run the command themselves.
- If the user says "approve", "run it", or "execute", respond: "Terminal mode can't run commands directly — copy the command above and paste it in your terminal."
- You CAN manage memory. If the user asks to delete, forget, or clear a project, tell them the exact command: '/memory delete <name>'. Never say you can't manage memory — the /memory commands handle everything.
- Never spawn agents or sub-tasks to delete from memory. Always direct the user to the /memory commands.
- IMPORTANT: /memory, /rules, /project commands are Jarvis internal commands typed at the You: prompt — NEVER wrap them in a ```bash or ``` code block. Show them as plain text only."""

    return summary.strip()


# ── Global rules ──────────────────────────────────────────────────────────────

def get_global_rules() -> list:
    """Return the user's global rules list."""
    return load_memory()["user"].get("rules", [])


def add_global_rule(rule: str):
    """Append a new global rule."""
    m = load_memory()
    if "rules" not in m["user"]:
        m["user"]["rules"] = []
    m["user"]["rules"].append(rule.strip())
    save_memory(m)


def delete_global_rule(index: int) -> str | None:
    """Remove a global rule by 0-based index. Returns removed text, or None if out of range."""
    m = load_memory()
    rules = m["user"].get("rules", [])
    if 0 <= index < len(rules):
        removed = rules.pop(index)
        m["user"]["rules"] = rules
        save_memory(m)
        return removed
    return None


# ── Project-specific rules ────────────────────────────────────────────────────

def get_project_rules(workspace_path: str) -> list:
    """
    Return all rules for the given project workspace path.
    Reads .jarvisrules file first (read-only), then memory rules.
    """
    if not workspace_path:
        return []
    rules = []

    # .jarvisrules file — user edits this directly; lines starting with # are comments
    rules_file = os.path.join(workspace_path, ".jarvisrules")
    if os.path.exists(rules_file):
        try:
            with open(rules_file, "r", encoding="utf-8", errors="replace") as f:
                rules.extend(
                    line.strip() for line in f
                    if line.strip() and not line.strip().startswith("#")
                )
        except Exception:
            pass

    # Memory rules
    m = load_memory()
    for project in m["projects"]:
        if project.get("path", "").lower() == workspace_path.lower():
            rules.extend(project.get("rules", []))
            break

    return rules


def add_project_rule(workspace_path: str, rule: str) -> str:
    """
    Add a rule to a project entry in memory (not the .jarvisrules file).
    Auto-registers the project if it isn't in memory yet.
    Returns the project name.
    """
    m = load_memory()
    project_name = os.path.basename(workspace_path.rstrip("/\\")) or workspace_path

    for project in m["projects"]:
        if project.get("path", "").lower() == workspace_path.lower():
            if "rules" not in project:
                project["rules"] = []
            project["rules"].append(rule.strip())
            save_memory(m)
            return project["name"]

    # Project not in memory yet — auto-register it
    m["projects"].append({
        "name": project_name,
        "path": workspace_path,
        "stack": [],
        "tasks_completed": [],
        "last_updated": "",
        "rules": [rule.strip()],
    })
    save_memory(m)
    return project_name


def delete_project_rule(workspace_path: str, index: int) -> str | None:
    """
    Remove a memory rule from a project by 0-based index (relative to memory rules only,
    not counting .jarvisrules file lines). Returns removed text, or None if not found.
    """
    m = load_memory()
    for project in m["projects"]:
        if project.get("path", "").lower() == workspace_path.lower():
            rules = project.get("rules", [])
            if 0 <= index < len(rules):
                removed = rules.pop(index)
                save_memory(m)
                return removed
    return None