"""
tools/templates.py — Phase 11: Task templates / playbooks.

Templates are pre-defined multi-agent breakdowns saved as JSON files.
Storage mirrors the sessions layout:
  templates/global/<slug>.json       — available everywhere
  templates/projects/<hash>/<slug>.json — project-specific

Commands (handled by handle_template_command in orchestrator.py):
  /template list                  — list all templates
  /template info <name>           — show agents in a template
  /template use <name>            — run template (terminal only)
  /template use <name> for <ctx>  — run template with context injected
  /template save <name>           — save last agent breakdown as template
  /template delete <name>         — delete a template
"""

import hashlib
import json
import os
from datetime import datetime, timezone

from config import MEMORY_FILE

_JARVIS_ROOT = os.path.dirname(os.path.abspath(MEMORY_FILE))


# ── Directory helpers ─────────────────────────────────────────────────────────

def templates_dir(workspace_root: str = "") -> str:
    """Return (and create) the appropriate templates directory."""
    if workspace_root:
        h = _workspace_hash(workspace_root)
        base = os.path.join(_JARVIS_ROOT, "templates", "projects", h)
    else:
        base = os.path.join(_JARVIS_ROOT, "templates", "global")
    os.makedirs(base, exist_ok=True)
    return base


def _workspace_hash(workspace_root: str) -> str:
    normalized = workspace_root.lower().replace("\\", "/").rstrip("/")
    return hashlib.md5(normalized.encode()).hexdigest()[:12]


def _slug(name: str) -> str:
    """Convert a template name to a safe filename."""
    return name.lower().replace(" ", "-").replace("/", "-").replace("\\", "-")


def _template_path(name: str, workspace_root: str = "") -> str:
    return os.path.join(templates_dir(workspace_root), f"{_slug(name)}.json")


# ── CRUD ──────────────────────────────────────────────────────────────────────

def list_templates(workspace_root: str = "") -> list:
    """
    Return all templates visible from the given workspace:
    global templates first, then project-scoped ones.
    """
    results = []

    def _load_dir(directory: str, scope: str) -> None:
        if not os.path.isdir(directory):
            return
        for fname in sorted(os.listdir(directory)):
            if not fname.endswith(".json"):
                continue
            try:
                with open(os.path.join(directory, fname), encoding="utf-8") as fh:
                    t = json.load(fh)
                t["scope"] = scope
                results.append(t)
            except Exception:
                pass

    _load_dir(templates_dir(""), "global")
    if workspace_root:
        _load_dir(templates_dir(workspace_root), "project")

    return results


def get_template(name: str, workspace_root: str = "") -> dict | None:
    """
    Load a template by name.
    Checks project-scoped first (if workspace_root given), then global.
    """
    if workspace_root:
        path = _template_path(name, workspace_root)
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                t = json.load(f)
            t["scope"] = "project"
            return t

    path = _template_path(name, "")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            t = json.load(f)
        t["scope"] = "global"
        return t

    return None


def save_template(name: str, agents: list, workspace_root: str = "",
                  description: str = "", trigger_phrases: list | None = None) -> str:
    """
    Save a template. Returns the file path.
    agents: list of {"id": str, "task": str, "depends_on": list}
    """
    template = {
        "name": name,
        "description": description,
        "trigger_phrases": trigger_phrases or [],
        "agents": agents,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "use_count": 0,
    }
    path = _template_path(name, workspace_root)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(template, f, indent=2)
    return path


def delete_template(name: str, workspace_root: str = "") -> bool:
    """Delete a template. Returns True if found and deleted."""
    if workspace_root:
        path = _template_path(name, workspace_root)
        if os.path.exists(path):
            os.remove(path)
            return True
    path = _template_path(name, "")
    if os.path.exists(path):
        os.remove(path)
        return True
    return False


def increment_use_count(name: str, workspace_root: str = "") -> None:
    """Bump use_count on a template after it runs. Best-effort."""
    try:
        path = _template_path(name, workspace_root)
        if not os.path.exists(path):
            path = _template_path(name, "")
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                t = json.load(f)
            t["use_count"] = t.get("use_count", 0) + 1
            with open(path, "w", encoding="utf-8") as f:
                json.dump(t, f, indent=2)
    except Exception:
        pass


# ── Trigger phrase matching ───────────────────────────────────────────────────

def find_by_trigger(user_input: str, workspace_root: str = "") -> dict | None:
    """
    Return the first template whose trigger phrase is found in user_input.
    Project-scoped templates take priority over global.
    Returns None if no match.
    """
    lower = user_input.lower()
    project_templates = []
    global_templates = []

    for t in list_templates(workspace_root):
        if t.get("scope") == "project":
            project_templates.append(t)
        else:
            global_templates.append(t)

    for t in project_templates + global_templates:
        for phrase in t.get("trigger_phrases", []):
            if phrase.lower() in lower:
                return t

    return None


# ── Agent injection helpers ───────────────────────────────────────────────────

def build_agent_defs_from_template(template: dict, context: str = "") -> list:
    """
    Convert template agents into the format expected by AgentPool.
    If context is given (e.g. "user-profile-component"), it's appended
    to each agent task description so agents know what feature to build.
    """
    agents = []
    ctx_suffix = f"\n\nContext / feature name: {context}" if context else ""
    for a in template.get("agents", []):
        agents.append({
            "id": a["id"],
            "task": a["task"] + ctx_suffix,
            "depends_on": a.get("depends_on", []),
        })
    return agents


# ── Formatting helpers ────────────────────────────────────────────────────────

def format_template_list(templates: list) -> str:
    """Return a human-readable list of templates."""
    if not templates:
        return (
            "No templates saved yet.\n\n"
            "Save the last agent breakdown:  `/template save <name>`\n"
            "Or use a built-in:              `/template list` after adding built-ins."
        )
    lines = [f"Templates ({len(templates)}):"]
    for t in templates:
        scope = "[project]" if t.get("scope") == "project" else "[global]"
        n_agents = len(t.get("agents", []))
        desc = f" — {t['description']}" if t.get("description") else ""
        uses = t.get("use_count", 0)
        use_str = f"  (used {uses}x)" if uses else ""
        lines.append(f"  • {t['name']} {scope}  {n_agents} agents{desc}{use_str}")
    lines.append("\nRun:  `/template use <name>`")
    lines.append("Info: `/template info <name>`")
    return "\n".join(lines)


def format_template_info(template: dict) -> str:
    """Return a detailed view of one template."""
    lines = [
        f"Template: {template['name']}",
        f"Scope:    {template.get('scope', 'global')}",
    ]
    if template.get("description"):
        lines.append(f"About:    {template['description']}")
    if template.get("trigger_phrases"):
        lines.append(f"Triggers: {', '.join(template['trigger_phrases'])}")
    lines.append(f"Used:     {template.get('use_count', 0)}x")
    lines.append("")
    lines.append(f"Agents ({len(template.get('agents', []))}):")
    for a in template.get("agents", []):
        deps = f"  (after: {', '.join(a['depends_on'])})" if a.get("depends_on") else ""
        lines.append(f"  [{a['id']}]{deps}")
        lines.append(f"    {a['task']}")
    return "\n".join(lines)
