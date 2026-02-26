# tools/handoff.py
# Phase 9 — Agent handoff scratchpad.
# Agents write structured output (files created/modified, exports, notes)
# to a shared .jarvis-handoff.json in the working directory.
# Dependent agents read this before running so they know exactly what exists.

import json
import os

HANDOFF_FILE = ".jarvis-handoff.json"


def read_handoff(working_dir: str) -> dict:
    """Read the handoff scratchpad for the given directory. Returns {} if missing."""
    path = os.path.join(working_dir, HANDOFF_FILE)
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def write_handoff(agent_id: str, data: dict, working_dir: str) -> None:
    """Merge an agent's result entry into the handoff scratchpad."""
    path = os.path.join(working_dir, HANDOFF_FILE)
    current = read_handoff(working_dir)
    current[agent_id] = data
    with open(path, "w", encoding="utf-8") as f:
        json.dump(current, f, indent=2)


def build_handoff_context(depends_on_ids: list, working_dir: str) -> str:
    """
    Build a context string from all dependency agents' handoff entries.
    Returns "" if no relevant entries exist.
    """
    if not depends_on_ids or not working_dir:
        return ""
    handoff = read_handoff(working_dir)
    lines = []
    for agent_id in depends_on_ids:
        entry = handoff.get(agent_id)
        if not entry:
            continue
        lines.append(f"\n{agent_id} already completed:")
        if entry.get("files_created"):
            lines.append(f"  Created:  {', '.join(entry['files_created'])}")
        if entry.get("files_modified"):
            lines.append(f"  Modified: {', '.join(entry['files_modified'])}")
        if entry.get("exports"):
            lines.append(f"  Exports:  {', '.join(entry['exports'])}")
        if entry.get("notes"):
            lines.append(f"  Notes:    {entry['notes']}")
    if not lines:
        return ""
    return "Context from completed dependency agents:" + "\n".join(lines)


def extract_handoff_data(output: str, task: str) -> dict:
    """
    Use Claude Haiku to extract structured metadata from an agent's output.
    Returns a dict with files_created, files_modified, exports, notes.
    Returns {} on any failure — this is always best-effort.
    """
    try:
        import anthropic
        client = anthropic.Anthropic()
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            system="Extract metadata from agent output. Return ONLY valid JSON, no markdown.",
            messages=[{
                "role": "user",
                "content": (
                    f"Task: {task[:200]}\n\n"
                    f"Output:\n{output[:4000]}\n\n"
                    'Return JSON with these keys (use empty lists/string if unknown):\n'
                    '{"files_created": [], "files_modified": [], "exports": [], "notes": ""}'
                )
            }]
        )
        text = response.content[0].text.strip()
        # Strip accidental markdown fences
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        return json.loads(text)
    except Exception:
        return {}


def cleanup_handoff(working_dir: str) -> None:
    """Remove the handoff scratchpad after the task completes."""
    path = os.path.join(working_dir, HANDOFF_FILE)
    try:
        os.remove(path)
    except FileNotFoundError:
        pass
