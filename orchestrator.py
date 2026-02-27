# orchestrator.py
# The brain of Jarvis — decides if a task is simple or complex,
# selects the right model, and for complex tasks spawns real agents.
# Phase 2: Full agent execution with dependency graph support.
# Phase 3: AI-based complexity detection, project auto-detection, agent result memory.

import anthropic
import json
import os
import re
import sys
from config import ANTHROPIC_API_KEY, MODEL_SONNET, MODEL_OPUS, MAX_TOKENS
from tools.sessions import (
    create_session, get_session,
    append_message as session_append_message,
    update_session_name, close_session as close_session_fn,
    get_active_session_id, set_active_session,
    get_project_summary_text, list_all_sessions, list_project_sessions,
    auto_name_from_first_message, generate_better_name,
    _JARVIS_ROOT,
)
from memory import (
    get_context_summary, add_to_history, load_memory, save_memory, save_task_to_project,
    update_last_session, get_daily_briefing, get_all_projects_summary, learn_preference,
    get_global_rules, add_global_rule, delete_global_rule,
    get_project_rules, add_project_rule, delete_project_rule,
    delete_project, delete_all_projects,
)
from agents.agent import Agent
from agents.agent_pool import AgentPool
from tools.claude_code import get_working_directory, verify_claude_code_installed

# Initialize the Anthropic client
client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

# Tasks that need Opus — complex development work
OPUS_KEYWORDS = [
    "build", "create project", "full app", "entire", "whole",
    "multiple", "system", "architecture", "integrate", "deploy",
    "design pattern", "refactor entire", "migrate", "performance",
    "scalable", "production", "authentication system", "database schema"
]

# Tasks that are clearly simple — always use Sonnet
SONNET_KEYWORDS = [
    "what is", "explain", "how does", "difference between",
    "example of", "quick", "simple", "define", "summarize"
]

def ai_classify_task(user_input: str) -> dict:
    """
    Use Claude to classify a task as SIMPLE or COMPLEX.
    Returns: {"is_complex": bool, "model": str, "used_ai": bool}
    Falls back to keyword matching if the API call fails.
    """
    try:
        response = client.messages.create(
            model=MODEL_SONNET,
            max_tokens=20,
            system="You are a task classifier. Reply with ONLY one word: SIMPLE or COMPLEX.",
            messages=[{
                "role": "user",
                "content": (
                    f"Classify this task:\n"
                    f"SIMPLE = answer directly (questions, explanations, advice)\n"
                    f"COMPLEX = needs to create or edit files, build features, write code\n\n"
                    f"Task: {user_input}"
                )
            }]
        )
        word = response.content[0].text.strip().upper()
        is_complex = "COMPLEX" in word
        model = MODEL_OPUS if is_complex else MODEL_SONNET
        label = "🧠 Using Opus (complex — AI)" if is_complex else "⚡ Using Sonnet (simple — AI)"
        print(label)
        return {"is_complex": is_complex, "model": model, "used_ai": True}
    except Exception:
        # Fall back to keyword-based detection silently
        is_complex = is_complex_task(user_input)
        model = select_model(user_input)
        return {"is_complex": is_complex, "model": model, "used_ai": False}


def select_model(user_input: str) -> str:
    """Automatically select the best model based on task complexity."""
    lower_input = user_input.lower()

    if any(keyword in lower_input for keyword in SONNET_KEYWORDS):
        print("⚡ Using Sonnet (quick task)")
        return MODEL_SONNET

    if any(keyword in lower_input for keyword in OPUS_KEYWORDS):
        print("🧠 Using Opus (complex task)")
        return MODEL_OPUS

    print("⚡ Using Sonnet (default)")
    return MODEL_SONNET

def is_complex_task(user_input: str) -> bool:
    """Determine if a task needs multi-agent handling."""
    lower_input = user_input.lower()
    return any(keyword in lower_input for keyword in OPUS_KEYWORDS)

def _strip_tool_xml(text: str) -> str:
    """
    Strip leaked tool-call XML from terminal-mode responses.
    Terminal mode defines no tools, but the model can occasionally leak
    <function_calls>, <tool_call>, or <invoke> blocks in its text output.
    """
    text = re.sub(r'<function_calls>.*?</function_calls>', '', text, flags=re.DOTALL)
    text = re.sub(r'<tool_call>.*?</tool_call>', '', text, flags=re.DOTALL)
    text = re.sub(r'<tool_response>.*?</tool_response>', '', text, flags=re.DOTALL)
    text = re.sub(r'<invoke\b[^>]*>.*?</invoke>', '', text, flags=re.DOTALL)
    return text.strip()


def handle_simple_task(user_input: str, history: list, model: str) -> str:
    """Handle a simple task directly with the selected model."""
    from tools.token_tracker import tracker

    context = get_context_summary()
    messages = history + [{"role": "user", "content": user_input}]

    response = client.messages.create(
        model=model,
        max_tokens=MAX_TOKENS,
        system=context,
        messages=messages
    )

    # Log token usage
    tracker.log(
        label=f"Simple task: {user_input[:50]}",
        model=model,
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens
    )

    return _strip_tool_xml(response.content[0].text)

def breakdown_into_agents(user_input: str, model: str) -> tuple:
    """
    Ask Claude to break a complex task into the RIGHT number of subtasks.
    Returns (agent_definitions, token_usage_dict)
    """
    memory = load_memory()
    projects = memory.get("projects", [])

    breakdown_prompt = f"""
You are Jarvis, an AI orchestrator. Break this task into the MINIMUM number 
of agents needed. Follow these rules strictly:

AGENT COUNT RULES:
- Single component/file (e.g. one Angular component, one CSS file) = 1 agent
- Single feature with 2-3 connected files = 2 agents max
- Full page with frontend + backend = 3 agents max
- Complete feature with tests = 3-4 agents max
- Full app or system = 5-6 agents max

IMPORTANT: Return ONLY a valid JSON array, no explanation, no markdown.

Format:
[
  {{
    "id": "agent_1",
    "task": "specific task description — be detailed so agent can do it completely",
    "context": "only what this agent needs to know",
    "depends_on": []
  }},
  {{
    "id": "agent_2",
    "task": "specific task description",
    "context": "only what this agent needs to know",
    "depends_on": ["agent_1"]
  }}
]

Rules:
- Each agent must do ONE complete, meaningful piece of work
- A single component with its HTML/CSS/TS = ONE agent (not 4)
- Keep context minimal — agents don't need the full picture
- depends_on must list agent IDs that must complete first
- Independent tasks should have empty depends_on
- NEVER exceed 6 agents

User task: {user_input}
Known projects: {[p['name'] for p in projects] if projects else 'none'}
"""

    response = client.messages.create(
        model=model,
        max_tokens=MAX_TOKENS,
        system="You are a task orchestrator. Return only valid JSON.",
        messages=[{"role": "user", "content": breakdown_prompt}]
    )

    raw = response.content[0].text.strip()

    # Clean up markdown if Claude wrapped it
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()

    token_usage = {
        "input": response.usage.input_tokens,
        "output": response.usage.output_tokens
    }

    try:
        return json.loads(raw), token_usage
    except json.JSONDecodeError:
        raise ValueError(
            f"Claude returned invalid JSON for task breakdown.\n"
            f"Raw response (first 300 chars): {raw[:300]}\n"
            f"Try rephrasing your task more clearly."
        )

def handle_complex_task(user_input: str, model: str) -> str:
    """
    Handle a complex task by spawning real agents.
    1. Break into subtasks
    2. Ask where to work
    3. Run agents with dependency graph
    4. Return summary
    """

    # Check Claude Code is available
    if not verify_claude_code_installed():
        return "⚠️ Claude Code CLI not found. Please make sure 'claude' is installed and in your PATH."

    print("\n🧠 Breaking down your task into subtasks...")

    # Get agent definitions from Claude
    try:
        agent_definitions, breakdown_tokens = breakdown_into_agents(user_input, model)
        from tools.token_tracker import tracker
        tracker.log(
            label=f"Task breakdown: {user_input[:50]}",
            model=model,
            input_tokens=breakdown_tokens["input"],
            output_tokens=breakdown_tokens["output"]
        )
    except Exception as e:
        return f"⚠️ Failed to break down task: {str(e)}"

    # Show the plan to the user first
    print(f"\n📋 Here's the plan ({len(agent_definitions)} agents):")
    print("=" * 50)
    for agent_def in agent_definitions:
        deps = agent_def.get("depends_on", [])
        dep_str = f" (waits for: {', '.join(deps)})" if deps else " (independent)"
        print(f"  🤖 [{agent_def['id']}] {agent_def['task'][:70]}{dep_str}")
    print("=" * 50)

    # Ask user to confirm before proceeding
    confirm = input("\nProceed with this plan? (yes/no): ").strip().lower()
    if confirm not in ["yes", "y"]:
        return "🚫 Task cancelled by user."

    # Ask where to work
    working_dir = get_working_directory(user_input[:50])
    if not working_dir:
        return "🚫 No working directory selected. Task cancelled."

    # Phase 3.2: Scan project for context to inject into agent prompts
    from tools.project_scanner import scan_project, get_context_string
    project_info = scan_project(working_dir)
    project_context = get_context_string(project_info)
    if project_context:
        print(f"\n📁 Project context detected:\n{project_context}\n")

    # Phase 6.1: Ask about git auto-commit + capture rollback checkpoint
    from tools.git_tools import is_git_repo, git_checkpoint, git_rollback
    auto_git = False
    rollback_sha = None
    if is_git_repo(working_dir):
        rollback_sha = git_checkpoint(working_dir)
        if rollback_sha:
            print(f"   Checkpoint: {rollback_sha} (rollback available if task fails)")
        git_answer = input("Auto-commit after each agent completes? (yes/no): ").strip().lower()
        auto_git = git_answer in ["yes", "y"]

    # Phase 6.2: Ask about auto-test
    from tools.test_runner import detect_test_command
    test_command = detect_test_command(working_dir)
    auto_test = False
    if test_command:
        test_answer = input(f"Run tests after each agent ({test_command})? (yes/no): ").strip().lower()
        auto_test = test_answer in ["yes", "y"]

    # Phase 5.2: Load user preferences to inject into every agent
    preferences_context = get_preferences_context()

    # Build Agent objects — inject project context + preferences into each task
    agents = []
    for agent_def in agent_definitions:
        task = agent_def["task"]
        if project_context:
            task = f"{task}\n\nProject context:\n{project_context}"
        if preferences_context:
            task = f"{task}\n\n{preferences_context}"
        agent = Agent(
            id=agent_def["id"],
            task=task,
            context=agent_def.get("context", ""),
            depends_on=agent_def.get("depends_on", []),
            working_dir=working_dir,
            auto_git=auto_git,
            auto_test=auto_test,
            test_command=test_command or ""
        )
        agents.append(agent)

    # Run the agent pool
    pool = AgentPool(agents=agents, working_dir=working_dir)
    summary = pool.execute()

    # Phase 9: clean up handoff scratchpad
    from tools.handoff import cleanup_handoff
    cleanup_handoff(working_dir)

    # Phase 3.3: Save task results to project memory
    if summary["succeeded"] > 0:
        save_task_to_project(
            project_path=working_dir,
            task=user_input,
            agents_succeeded=summary["succeeded"],
            agents_total=summary["total"],
            stack=project_info.get("stack", [])
        )

    # Offer git rollback if agents failed and we have a checkpoint
    if summary["failed"] > 0 and rollback_sha:
        rollback_answer = input(f"\nRoll back all changes to checkpoint {rollback_sha}? (yes/no): ").strip().lower()
        if rollback_answer in ["yes", "y"]:
            ok, msg = git_rollback(working_dir, rollback_sha)
            print(f"   Git: {msg}")

    # Phase 6.3: Offer browser preview for frontend projects
    from tools.browser import detect_dev_server_url, open_browser_preview
    dev_url = detect_dev_server_url(working_dir)
    if dev_url and summary["succeeded"] > 0:
        preview = input(f"\nOpen browser preview at {dev_url}? (yes/no): ").strip().lower()
        if preview in ["yes", "y"]:
            ok, msg = open_browser_preview(working_dir)
            print(msg)

    # Build response for Jarvis
    response = f"""
🎯 Task Complete!

📊 Results: {summary['succeeded']}/{summary['total']} agents succeeded
"""
    if summary['failed'] > 0:
        response += f"❌ {summary['failed']} agent(s) failed\n"
    if summary['skipped'] > 0:
        response += f"⏭️  {summary['skipped']} agent(s) skipped\n"

    response += "\nCheck the output above for full details from each agent."
    return response.strip()

def detect_and_save_preference(message: str) -> str | None:
    """
    If the message contains a preference instruction (e.g. "remember: I use BEM CSS"),
    extract and save it. Returns the saved preference text, or None if no match.
    """
    import re
    match = re.search(r'\bremember[:\s]+(.+)', message, re.IGNORECASE)
    if match:
        pref_text = match.group(1).strip()
        words = pref_text.lower().split()
        key = words[0].rstrip(":") if words else "general"
        learn_preference(key, pref_text)
        return pref_text
    return None


def get_preferences_context() -> str:
    """Return user coding preferences formatted for injection into agent prompts."""
    memory = load_memory()
    prefs = memory["user"].get("preferences", {})
    if isinstance(prefs, dict) and prefs:
        lines = "\n".join(f"- {k}: {v}" for k, v in prefs.items())
        return f"User coding preferences (follow these strictly):\n{lines}"
    elif isinstance(prefs, list) and prefs:
        lines = "\n".join(f"- {p}" for p in prefs)
        return f"User coding preferences (follow these strictly):\n{lines}"
    return ""


def process_briefing() -> str:
    """Generate the daily startup briefing text."""
    briefing = get_daily_briefing()
    name = briefing["user_name"] or "there"

    lines = [f"Good to see you, {name}!"]

    if briefing["last_session"]:
        last = briefing["last_session"][:10]
        lines.append(f"Last session: {last}")

    if briefing["recent_project"]:
        stack_str = ", ".join(briefing["recent_project_stack"]) or "unknown stack"
        lines.append(f"Last project: {briefing['recent_project']} ({stack_str})")
        if briefing["last_task"]:
            lines.append(f"Last task: {briefing['last_task'][:100]}")

    if briefing["total_projects"] > 0:
        lines.append(f"Projects in memory: {briefing['total_projects']}")
    else:
        lines.append("No projects in memory yet. Run a complex task to get started.")

    return "\n".join(lines)


# Directories to skip when scanning the workspace tree
_SCAN_IGNORE_DIRS = {
    '.git', 'node_modules', '__pycache__', '.venv', 'venv',
    'dist', 'build', 'out', '.next', 'bin', 'obj', '.angular',
    'coverage', 'tmp', '.idea', '.vs', 'packages', '.nuget',
    '.pytest_cache', '.mypy_cache', 'wwwroot', 'migrations',
}


def scan_workspace_files(workspace_path: str, max_depth: int = 3, max_lines: int = 60) -> str:
    """
    Generate a compact file tree for a workspace directory.
    Returns empty string if path is invalid.
    """
    if not workspace_path or not os.path.isdir(workspace_path):
        return ""

    root_name = os.path.basename(workspace_path.rstrip('/\\')) or workspace_path
    lines = [root_name + "/"]

    def _walk(path: str, depth: int, prefix: str):
        if depth > max_depth or len(lines) >= max_lines:
            return
        try:
            entries = sorted(os.scandir(path), key=lambda e: (not e.is_dir(), e.name.lower()))
        except PermissionError:
            return

        visible = [e for e in entries if not (e.is_dir() and e.name in _SCAN_IGNORE_DIRS)]

        for i, entry in enumerate(visible):
            if len(lines) >= max_lines:
                lines.append(prefix + "... (more files)")
                return
            is_last = i == len(visible) - 1
            connector = "└── " if is_last else "├── "
            lines.append(f"{prefix}{connector}{entry.name}")
            if entry.is_dir():
                child_prefix = prefix + ("    " if is_last else "│   ")
                _walk(entry.path, depth + 1, child_prefix)

    _walk(workspace_path, 1, "")
    return "\n".join(lines)


def read_mentioned_files(message: str, workspace_root: str, max_files: int = 3) -> list:
    """
    Find files mentioned by name in the message and read them from the workspace.
    Returns list of (rel_path, content) tuples.
    """
    if not workspace_root or not os.path.isdir(workspace_root):
        return []

    pattern = re.compile(
        r'\b([\w\-]+\.(?:ts|js|tsx|jsx|py|cs|html|scss|css|json|yaml|yml|md|'
        r'txt|xml|sql|sh|bat|config|env|csproj|sln|razor|tf|toml|ini))\b'
    )
    names = list(dict.fromkeys(pattern.findall(message)))  # deduplicated, order-preserved

    results = []
    for name in names:
        if len(results) >= max_files:
            break
        for root, dirs, files in os.walk(workspace_root):
            dirs[:] = [d for d in dirs if d not in _SCAN_IGNORE_DIRS]
            if name in files:
                full_path = os.path.join(root, name)
                try:
                    with open(full_path, 'r', encoding='utf-8', errors='replace') as f:
                        content = f.read(3000)
                    rel = os.path.relpath(full_path, workspace_root).replace('\\', '/')
                    results.append((rel, content))
                except Exception:
                    pass
                break

    return results


def _read_jarvisrules_file(workspace_path: str) -> list:
    """Read .jarvisrules from workspace root. Lines starting with # are comments."""
    path = os.path.join(workspace_path, ".jarvisrules")
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            return [l.strip() for l in f if l.strip() and not l.strip().startswith("#")]
    except Exception:
        return []


def _handle_session_rename(
    message: str, session_id: str, workspace_root: str, is_global: bool, session_msgs: list
) -> dict | None:
    """
    Intercept session rename requests — no Claude call needed.
    Returns {"text": str, "name": str} or None.

    Handles two cases:
      1. User suggests a name: "rename this session to X" / "call this session X" / etc.
      2. User wants a generated name: "generate a new name" / "give this session a better name" / etc.
    """
    lower = message.lower().strip()

    # ── Case 1: User-supplied name ────────────────────────────────────────────
    _RENAME_PREFIXES = [
        "rename this session to ",
        "rename session to ",
        "rename to ",
        "name this session ",
        "call this session ",
        "set session name to ",
        "set the session name to ",
        "label this session ",
    ]
    for prefix in _RENAME_PREFIXES:
        if lower.startswith(prefix):
            new_name = message[len(prefix):].strip().strip('"\'')
            if new_name:
                update_session_name(session_id, workspace_root, is_global, new_name)
                return {"text": f'Session renamed to "{new_name}".', "name": new_name}

    # ── Case 2: Generate a name from history ──────────────────────────────────
    _REGEN_PHRASES = [
        "generate a new name",
        "generate a better name",
        "regenerate the session name",
        "regenerate session name",
        "give this session a better name",
        "rename this session",
        "rename the session",
        "suggest a name for this session",
        "generate a name for this session",
        "give this session a name",
        "auto-name this session",
    ]
    if any(p in lower for p in _REGEN_PHRASES):
        new_name = generate_better_name(session_msgs) if session_msgs else ""
        if not new_name:
            first_user = next((m["content"] for m in session_msgs if m.get("role") == "user"), "")
            new_name = auto_name_from_first_message(first_user) if first_user else "New session"
        update_session_name(session_id, workspace_root, is_global, new_name)
        return {"text": f'Session renamed to "{new_name}".', "name": new_name}

    return None


def handle_rules_command(message: str, workspace_root: str = "") -> str | None:
    """
    Intercept /rules and /project rules commands — no Claude call, instant response.
    Returns a response string if the message is a rules command, otherwise None.

    Global rules (/rules):
        /rules                   → list all
        /rules add <text>        → add
        /rules remove <n>        → remove by number
        /rules clear             → clear all

    Project rules (/project rules):  — requires workspace_root in VS Code
        /project rules           → list rules for current workspace
        /project rules add <text>
        /project rules remove <n>
        /project rules clear
    """
    msg = message.strip()
    lower = msg.lower()

    # ── Global rules ──────────────────────────────────────────────────────────

    if lower == "/rules":
        rules = get_global_rules()
        if not rules:
            return (
                "No global rules set yet.\n\n"
                "Add one:  /rules add <your rule>\n"
                "Example:  /rules add Always use standalone Angular components"
            )
        lines = ["Global rules (injected into every conversation):"]
        for i, r in enumerate(rules, 1):
            lines.append(f"  {i}. {r}")
        lines.append("\n/rules add <text>    — add a rule")
        lines.append("/rules remove <n>    — remove by number")
        lines.append("/rules clear         — remove all")
        return "\n".join(lines)

    if lower.startswith("/rules add "):
        rule = msg[11:].strip()
        if not rule:
            return "Usage: /rules add <your rule>"
        add_global_rule(rule)
        count = len(get_global_rules())
        return f"Global rule added ({count} total):\n  → {rule}"

    if lower.startswith("/rules remove "):
        try:
            n = int(lower[14:].strip()) - 1
        except ValueError:
            return "Usage: /rules remove <number>"
        removed = delete_global_rule(n)
        return (f"Removed global rule: {removed}"
                if removed else "No rule at that number. Use /rules to see the list.")

    if lower == "/rules clear":
        m = load_memory()
        count = len(m["user"].get("rules", []))
        m["user"]["rules"] = []
        save_memory(m)
        return f"Cleared {count} global rule(s)."

    # ── Project rules ─────────────────────────────────────────────────────────

    if not lower.startswith("/project rules"):
        return None  # not a rules command — pass to Claude

    after = msg[len("/project rules"):].strip()
    after_lower = after.lower()

    if not workspace_root:
        return (
            "No workspace active.\n\n"
            "In VS Code, open your project folder and project rules will be detected automatically.\n"
            "Then use:  /project rules add <your rule>"
        )

    project_display = os.path.basename(workspace_root.rstrip("/\\")) or workspace_root

    # /project rules  →  list
    if not after or after_lower == "list":
        file_rules = _read_jarvisrules_file(workspace_root)
        mem_rules = [r for r in get_project_rules(workspace_root) if r not in file_rules]
        lines = [f"Project rules for: {project_display}"]
        if file_rules:
            lines.append("  From .jarvisrules file (edit file to change):")
            for r in file_rules:
                lines.append(f"    • {r}")
        if mem_rules:
            offset = len(file_rules) + 1
            lines.append("  From memory (managed with commands below):")
            for i, r in enumerate(mem_rules, offset):
                lines.append(f"    {i}. {r}")
        if not file_rules and not mem_rules:
            lines.append("  No project rules yet.")
        lines.append("\n/project rules add <text>    — add a rule")
        lines.append("/project rules remove <n>    — remove a memory rule by number")
        lines.append("/project rules clear         — remove all memory rules")
        lines.append("\nTip: You can also create a .jarvisrules file in your project root.")
        return "\n".join(lines)

    if after_lower.startswith("add "):
        rule = after[4:].strip()
        if not rule:
            return "Usage: /project rules add <your rule>"
        project_name = add_project_rule(workspace_root, rule)
        return f"Project rule added to {project_name}:\n  → {rule}"

    if after_lower.startswith("remove "):
        try:
            n = int(after[7:].strip()) - 1
        except ValueError:
            return "Usage: /project rules remove <number>"
        # Numbers 1..len(file_rules) are file rules — can't remove via command
        file_rules = _read_jarvisrules_file(workspace_root)
        if n < len(file_rules):
            return "That rule is from .jarvisrules — edit the file directly to remove it."
        mem_index = n - len(file_rules)
        removed = delete_project_rule(workspace_root, mem_index)
        return (f"Removed project rule: {removed}"
                if removed else "Rule not found. Use /project rules to see the list.")

    if after_lower == "clear":
        m = load_memory()
        for project in m["projects"]:
            if project.get("path", "").lower() == workspace_root.lower():
                count = len(project.get("rules", []))
                project["rules"] = []
                save_memory(m)
                return f"Cleared {count} memory rule(s) for {project_display}."
        return f"No memory rules found for {project_display}."

    # Unknown /project rules subcommand — let the user know
    return "Unknown command. Use /project rules to see available options."


def handle_memory_command(message: str) -> str | None:
    """
    Intercept /memory commands — instant response, no Claude call.
    Returns a response string if matched, otherwise None.

    /memory                     → show summary (projects + preferences)
    /memory projects            → list all projects
    /memory delete <name>       → delete a project by name
    /memory clear projects      → delete ALL projects
    /memory clear history       → clear conversation history
    /memory preferences         → list saved preferences
    """
    msg = message.strip()
    lower = msg.lower()

    if not lower.startswith("/memory"):
        return None

    after = msg[len("/memory"):].strip()
    after_lower = after.lower()

    # /memory  or  /memory summary
    if not after or after_lower == "summary":
        m = load_memory()
        projects = m["projects"]
        prefs = m["user"].get("preferences", {})
        lines = ["Memory summary:"]
        lines.append(f"  Projects: {len(projects)}")
        for p in projects:
            tasks = len(p.get("tasks_completed", []))
            lines.append(f"    • {p['name']}  ({', '.join(p.get('stack', [])) or 'unknown stack'})  — {tasks} tasks")
        if not projects:
            lines.append("    (none)")
        pref_count = len(prefs) if isinstance(prefs, dict) else len(prefs) if isinstance(prefs, list) else 0
        lines.append(f"  Preferences: {pref_count} saved")
        lines.append(f"  History: {len(m.get('history', []))} messages")
        lines.append("\nCommands:")
        lines.append("  /memory delete <name>      — delete a project")
        lines.append("  /memory clear projects     — delete all projects")
        lines.append("  /memory clear history      — clear conversation history")
        return "\n".join(lines)

    # /memory projects
    if after_lower == "projects":
        m = load_memory()
        projects = m["projects"]
        if not projects:
            return "No projects in memory.\n\nProjects are added automatically when you run complex tasks."
        lines = [f"Projects in memory ({len(projects)}):"]
        for i, p in enumerate(projects, 1):
            stack = ", ".join(p.get("stack", [])) or "unknown stack"
            tasks = len(p.get("tasks_completed", []))
            last = p.get("last_updated", "")[:10] or "never"
            lines.append(f"  {i}. {p['name']}  ({stack})  — {tasks} tasks, last: {last}")
        lines.append("\nUse '/memory delete <name>' to remove one.")
        return "\n".join(lines)

    # /memory delete <name>
    if after_lower.startswith("delete "):
        name = after[7:].strip()
        if not name:
            return "Usage: /memory delete <project name>"
        removed = delete_project(name)
        if removed:
            return f"Deleted project '{removed}' from memory."
        return f"No project matching '{name}' found.\n\nUse '/memory projects' to see the list."

    # /memory clear projects
    if after_lower == "clear projects":
        count = delete_all_projects()
        return f"Cleared all {count} project(s) from memory."

    # /memory clear history
    if after_lower == "clear history":
        m = load_memory()
        count = len(m.get("history", []))
        m["history"] = []
        save_memory(m)
        return f"Cleared {count} conversation history messages."

    # /memory preferences
    if after_lower in ("preferences", "prefs"):
        m = load_memory()
        prefs = m["user"].get("preferences", {})
        if not prefs:
            return "No preferences saved yet.\n\nSay 'remember: <preference>' and Jarvis will save it."
        if isinstance(prefs, dict):
            lines = ["Saved preferences:"] + [f"  • {k}: {v}" for k, v in prefs.items()]
        else:
            lines = ["Saved preferences:"] + [f"  • {p}" for p in prefs]
        lines.append("\nTo add: say 'remember: <your preference>'")
        return "\n".join(lines)

    return "Unknown /memory command. Use '/memory' to see available options."


def _natural_memory_delete(message: str) -> str | None:
    """
    Detect natural language delete requests and dispatch to delete_project().
    Matches:
      - "delete X from memory", "forget project X", "remove alpha and beta"
      - "remove them both permanently", "delete those", "forget them" (pronoun → lists projects)
    Returns response string if matched, None otherwise.
    """
    lower = message.lower()
    delete_intent = re.search(r'\b(delete|remove|forget|clear|erase)\b', lower)
    if not delete_intent:
        return None

    # Must also mention memory/project context OR use a pronoun ("them", "those", "both")
    memory_target = re.search(r'\b(memory|project|from (your|my|jarvis)|them|those|both|it)\b', lower)
    if not memory_target:
        return None

    # "delete all projects" / "clear all projects from memory" / "remove them all"
    if re.search(r'\b(all projects?|all of (them|the projects?)|them all)\b', lower):
        count = delete_all_projects()
        return f"Cleared all {count} project(s) from memory."

    # Pronoun reference: "remove them both", "delete those", "forget them permanently"
    # → list current projects so user can pick
    if re.search(r'\b(them|those|both|it)\b', lower) and not re.search(r'\b[a-z]{3,}[-_][a-z]+\b', lower):
        mem_data = load_memory()
        projects = mem_data.get("projects", [])
        if not projects:
            return "No projects in memory to delete."
        names = [p["name"] for p in projects]
        lines = ["Which project(s) do you want to delete?"]
        for n in names:
            lines.append(f"  /memory delete {n}")
        lines.append("  /memory clear projects  ← delete all at once")
        return "\n".join(lines)

    # Named project: "delete alpha from memory", "forget the alpha project", "remove alpha and beta"
    _skip = {"the", "my", "your", "all", "this", "that", "them", "those", "both", "permanently",
             "project", "projects", "from", "memory", "jarvis", "tests", "only", "as", "they",
             "were", "for", "just", "tell", "me", "can", "you"}
    patterns = [
        r'(?:delete|remove|forget|erase)\s+(?:the\s+)?["\']?([a-zA-Z0-9_\-\.]+)["\']?\s+(?:from|project)',
        r'(?:forget|remove|delete|erase)\s+(?:project\s+)?["\']?([a-zA-Z0-9_\-\.]+)["\']?',
    ]
    for pat in patterns:
        m = re.search(pat, lower)
        if m:
            name = m.group(1).strip()
            if name in _skip or len(name) < 2:
                continue
            removed = delete_project(name)
            if removed:
                return f"Deleted project '{removed}' from memory."
            mem_data = load_memory()
            candidates = [p["name"] for p in mem_data["projects"] if name in p["name"].lower()]
            if candidates:
                return (f"No exact match for '{name}'. Did you mean:\n"
                        + "\n".join(f"  /memory delete {c}" for c in candidates))
            return f"No project matching '{name}' found. Use '/memory projects' to see the list."

    return None


# ── VS Code session tracking ──────────────────────────────────────────────────

_last_session_id: str = ""
_last_session_name: str = ""


def get_last_session_id() -> str:
    """Return the session_id used in the last process_for_vscode call."""
    return _last_session_id


def get_last_session_name() -> str:
    """Return the session name after the last process_for_vscode call."""
    return _last_session_name


def build_vscode_system_prompt(
    workspace_root: str,
    is_global: bool,
    session_messages: list,
) -> str:
    """
    Build the system prompt for a VS Code session request.
    Replaces get_context_summary() for the VS Code path.
    Injects session-specific history instead of global history.
    """
    memory = load_memory()
    user = memory["user"]

    prefs = user.get("preferences", {})
    if isinstance(prefs, dict) and prefs:
        prefs_text = ", ".join(f"{k}: {v}" for k, v in prefs.items())
    elif isinstance(prefs, list) and prefs:
        prefs_text = ", ".join(prefs)
    else:
        prefs_text = "none set yet"

    rules = user.get("rules", [])
    rules_section = ""
    if rules:
        rules_section = "\nUser-defined rules (always follow these):\n" + "\n".join(f"- {r}" for r in rules)

    # Project context injection
    project_context_section = ""
    if not is_global and workspace_root:
        project_summary = get_project_summary_text(workspace_root)
        if project_summary:
            project_context_section = f"\nProject context:\n{project_summary}"
        else:
            # No cumulative summary yet (no sessions explicitly closed).
            # Inject brief hints from the 3 most recent past sessions so Jarvis
            # isn't completely blind to previous work in this project.
            past_sessions = list_project_sessions(workspace_root)
            past_lines = []
            for ps in past_sessions[:4]:
                msgs = ps.get("messages", [])
                if not msgs:
                    continue
                label = ps.get("name", "").strip()
                if not label:
                    first_user = next(
                        (m["content"][:80] for m in msgs if m["role"] == "user"), ""
                    )
                    label = first_user.strip()
                if label:
                    date = ps.get("updated_at", "")[:10]
                    past_lines.append(f"- {date}: {label}")
            if past_lines:
                project_context_section = (
                    "\nRecent sessions for this project (start new session with + to build full summary):\n"
                    + "\n".join(past_lines[:3])
                )
    elif is_global:
        # Global session: include brief summaries of up to 3 recent projects
        all_sessions = list_all_sessions()
        project_entries = list(all_sessions.get("projects", {}).values())[:3]
        if project_entries:
            lines = []
            for entry in project_entries:
                pname = entry.get("project_name", "Unknown")
                # Try to load summary for this project
                sessions = entry.get("sessions", [])
                if sessions:
                    workspace = sessions[0].get("workspace_root", "")
                    if workspace:
                        summary_text = get_project_summary_text(workspace)
                        if summary_text:
                            lines.append(f"- {pname}: {summary_text[:200]}")
            if lines:
                project_context_section = "\nKnown projects (summaries for cross-project questions):\n" + "\n".join(lines)

    # Recent session messages (last 20)
    history_text = ""
    if session_messages:
        recent = session_messages[-20:]
        history_text = "\n\nRecent conversation history:\n"
        name = user["name"] or "User"
        for msg in recent:
            r = msg["role"]
            if r == "user":
                role_label = name
            elif r == "tool":
                role_label = "[Tool]"
            else:
                role_label = "Jarvis"
            history_text += f"{role_label}: {msg['content'][:300]}\n"

    jarvis_root = _JARVIS_ROOT.replace("\\", "/")
    summary = f"""You are Jarvis, a personal AI assistant for {user['name'] or 'the user'}.
User info: name={user['name'] or 'unknown'}, experience={user['experience_level']}
Coding preferences: {prefs_text}{rules_section}{project_context_section}
{history_text}
Important: You have persistent memory. You remember past conversations.
If the user asks what you discussed before, refer to the history above.

Your local storage (do NOT invent other locations — this is the truth):
- Memory file: {jarvis_root}/memory.json (user prefs, project knowledge, rules)
- Session storage: {jarvis_root}/sessions/ (each project has separate sess_<id>.json files, one per conversation)
- Each session is a separate JSON log — /history drawer shows them all. They are NOT merged or cloud-stored.
- If asked about storage: be factual. Do not say "server-side" or "cloud" — everything is local JSON files.

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
- You CAN manage memory. If the user asks to delete, forget, or clear a project, tell them '/memory delete <name>'. Never say you can't manage memory — the /memory commands handle everything. Never spawn agents to delete from memory.
- IMPORTANT: /memory, /rules, /project commands are Jarvis internal commands — NEVER wrap them in a ```bash or ``` code block. Always show them as plain inline text.
- You CAN run terminal commands. Use the run_terminal_command tool for any CLI operation the user asks for: ng generate, npm install, dotnet build, dotnet run, git commands, etc.
- ALWAYS call run_terminal_command in the same response when the user asks you to run, re-run, modify, or adjust a command. Do not say "I've queued it" or "I'll run it" — just call the tool immediately.
- If the user says "add --o", "run it with --port 4201", "run it again", or any variation → call run_terminal_command with the updated/repeated command right now, in this response.
- If the user says "approve" in chat, explain: "Click the Run button in the command card above — typing 'approve' in chat doesn't execute anything."
- Never describe a command you intend to queue without actually calling the tool in the same message."""

    return summary.strip()


# ── VS Code file tools (read_file / write_file) ───────────────────────────────

# Tracks files written during the current VS Code request (reset each call)
_vscode_files_written: list = []
_vscode_pending_commands: list = []

# Process tracking — keyed by job_id
_active_processes: dict = {}   # job_id -> {"process": Popen, "command": str, "pid": int}
_killed_jobs: set = set()      # job_ids killed by the user (vs natural exit)
_job_counter: int = 0


def get_last_files_written() -> list:
    """Return paths of files written during the last process_for_vscode call."""
    return list(_vscode_files_written)


def get_pending_commands() -> list:
    """Return terminal commands queued for user approval during the last process_for_vscode call."""
    return list(_vscode_pending_commands)


def get_active_processes() -> list:
    """Return currently running commands (for debugging / status)."""
    return [
        {"job_id": jid, "pid": v["pid"], "command": v["command"]}
        for jid, v in _active_processes.items()
    ]


def _next_job_id() -> str:
    global _job_counter
    _job_counter += 1
    return f"job_{_job_counter}"


def _kill_process_tree(proc) -> None:
    """Kill a process and all its children. Uses taskkill on Windows for full tree kill."""
    import subprocess as _sp
    pid = proc.pid
    if sys.platform == "win32":
        _sp.run(f"taskkill /F /T /PID {pid}", shell=True, capture_output=True)
    else:
        import signal
        try:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
        except Exception:
            proc.kill()


def kill_command(job_id: str) -> dict:
    """
    Kill an active command by job_id.
    Returns {success, message}.
    """
    entry = _active_processes.get(job_id)
    if not entry:
        return {"success": False, "message": f"No active command with id '{job_id}'"}
    _killed_jobs.add(job_id)
    _kill_process_tree(entry["process"])
    return {"success": True, "message": f"Killed PID {entry['pid']}: {entry['command'][:60]}"}


def run_single_command(command: str, working_dir: str, job_id: str = "") -> dict:
    """
    Execute a single approved terminal command locally.
    Tracks the PID so the user can kill it via kill_command().
    Returns {success, output, command, working_dir, job_id, pid}.
    """
    import subprocess
    global _active_processes, _killed_jobs

    if not job_id:
        job_id = _next_job_id()

    proc = None
    pid = 0
    output = ""
    success = False

    try:
        proc = subprocess.Popen(
            command,
            shell=True,
            cwd=working_dir or None,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        pid = proc.pid
        _active_processes[job_id] = {"process": proc, "command": command, "pid": pid}
        print(f"   PID {pid}: {command[:70]}")

        try:
            stdout, stderr = proc.communicate(timeout=120)
            output = (stdout + stderr).strip()
            success = proc.returncode == 0
        except subprocess.TimeoutExpired:
            _kill_process_tree(proc)
            stdout, stderr = proc.communicate()
            output = (stdout + stderr).strip()
            output = ("Timed out (120s) — process killed.\n" + output).strip()
            success = False

    except Exception as e:
        output = str(e)
        success = False
    finally:
        _active_processes.pop(job_id, None)
        if job_id in _killed_jobs:
            _killed_jobs.discard(job_id)
            captured = ("\n" + output) if output else ""
            output = f"Killed by user.{captured}"
            success = False

    return {
        "success": success,
        "output": output,
        "command": command,
        "working_dir": working_dir,
        "job_id": job_id,
        "pid": pid,
    }


VSCODE_TOOLS = [
    {
        "name": "read_file",
        "description": (
            "Read the full contents of a file from the workspace. "
            "Always read a file before editing it so you see the current state."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "File path — relative to workspace root, or absolute."
                }
            },
            "required": ["path"]
        }
    },
    {
        "name": "write_file",
        "description": (
            "Write or overwrite a file with new content. "
            "Creates the file (and any missing parent directories) if needed. "
            "Read the file first if it exists — then write the full updated content."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "File path — relative to workspace root, or absolute."
                },
                "content": {
                    "type": "string",
                    "description": "Complete new file content to write."
                }
            },
            "required": ["path", "content"]
        }
    },
    {
        "name": "run_terminal_command",
        "description": (
            "Queue a terminal command for the user to approve and run. "
            "Use this for CLI operations: ng generate, npm install, dotnet build, dotnet run, git commands, etc. "
            "The user will be shown the command and must click Run before it executes. "
            "Commands run in the workspace root directory."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The exact command to run, e.g. 'ng generate component login --standalone'"
                },
                "reason": {
                    "type": "string",
                    "description": "One-line explanation of what this command does and why."
                }
            },
            "required": ["command", "reason"]
        }
    }
]


def _execute_tool(tool_name: str, tool_input: dict, workspace_root: str) -> str:
    """Execute a tool call from Claude and return the result as a string."""
    global _vscode_files_written, _vscode_pending_commands

    def resolve(path: str) -> str:
        if workspace_root and not os.path.isabs(path):
            return os.path.join(workspace_root, path.replace("/", os.sep))
        return path

    if tool_name == "read_file":
        path = tool_input.get("path", "")
        full = resolve(path)
        try:
            with open(full, "r", encoding="utf-8", errors="replace") as f:
                content = f.read(12000)
            truncated = len(content) >= 12000
            result = f"File: {path}\n{content}"
            if truncated:
                result += "\n[... truncated at 12,000 chars ...]"
            return result
        except FileNotFoundError:
            return f"File not found: {path}"
        except Exception as e:
            return f"Error reading {path}: {e}"

    if tool_name == "write_file":
        path = tool_input.get("path", "")
        content = tool_input.get("content", "")
        full = resolve(path)
        try:
            parent = os.path.dirname(full)
            if parent:
                os.makedirs(parent, exist_ok=True)
            with open(full, "w", encoding="utf-8") as f:
                f.write(content)
            rel = os.path.relpath(full, workspace_root).replace("\\", "/") if workspace_root else path
            _vscode_files_written.append(rel)
            return f"Written: {path} ({len(content):,} chars)"
        except Exception as e:
            return f"Error writing {path}: {e}"

    if tool_name == "run_terminal_command":
        command = tool_input.get("command", "").strip()
        reason = tool_input.get("reason", "")
        if not command:
            return "Error: command is required."
        _vscode_pending_commands.append({
            "command": command,
            "working_dir": workspace_root,
            "reason": reason,
        })
        return f"[Queued for approval: {command}]"

    return f"Unknown tool: {tool_name}"


def build_message_with_file_context(
    message: str,
    file_path: str = "",
    file_content: str = "",
    selection: str = "",
    workspace_root: str = "",
    attachment_text: str = "",
    attachment_name: str = "",
) -> str:
    """
    Inject VS Code active-file context and any user-uploaded file into a user message.
    Selection takes priority over full file content.
    Phase 7: attachment_text/attachment_name for uploaded text files.
    """
    parts = [message]
    if workspace_root:
        file_tree = scan_workspace_files(workspace_root)
        if file_tree:
            parts.append(f"[Workspace: {workspace_root}]\n[File tree:\n{file_tree}\n]")
        else:
            parts.append(f"[Workspace: {workspace_root}]")
        project_rules = get_project_rules(workspace_root)
        if project_rules:
            rules_text = "\n".join(f"- {r}" for r in project_rules)
            parts.append(f"[Project rules — follow these for this workspace:\n{rules_text}]")
        # Auto-read files mentioned by name in the message
        for rel_path, content in read_mentioned_files(message, workspace_root):
            parts.append(f"[File: {rel_path}]\n```\n{content}\n```")
    if file_path:
        parts.append(f"[Active file: {file_path}]")
    if selection:
        parts.append(f"[Selected code:\n```\n{selection[:1000]}\n```\n]")
    elif file_content:
        parts.append(f"[File content:\n```\n{file_content[:2000]}\n```\n]")
    if attachment_text:
        label = attachment_name or "uploaded file"
        parts.append(f"[Attached file: {label}]\n```\n{attachment_text[:3000]}\n```")

    if len(parts) == 1:
        return message
    return "\n\n".join(parts)


def process_for_vscode(
    message: str,
    file_path: str = "",
    file_content: str = "",
    selection: str = "",
    workspace_root: str = "",
    attachment_text: str = "",
    attachment_name: str = "",
    attachment_image_base64: str = "",
    attachment_image_type: str = "",
    session_id: str = "",
    is_global: bool = False,
) -> str:
    """
    Phase 4/7/8/10 — Process a message from the VS Code panel.
    Supports text file attachments and image attachments (Claude Vision).
    Uses instant keyword check to redirect complex tasks to the terminal.
    Phase 8: /rules and /project rules commands are intercepted before Claude.
    Phase 10: Per-session message history and project summary injection.
    """
    global _last_session_id, _last_session_name

    # Intercept /rules and /memory commands — no Claude call needed
    rules_response = handle_rules_command(message, workspace_root)
    if rules_response is not None:
        return rules_response
    mem_response = handle_memory_command(message)
    if mem_response is not None:
        return mem_response
    nat_mem_response = _natural_memory_delete(message)
    if nat_mem_response is not None:
        return nat_mem_response

    # Shortcut: trivial social messages need no Claude call (saves ~3k tokens + 19s)
    _TRIVIAL_PHRASES = {
        "thanks", "thank you", "thx", "ty",
        "perfect", "great", "nice", "awesome", "cool", "got it",
        "ok", "okay", "k", "yep", "yes", "nope", "no", "sure",
        "perfect thanks", "sounds good", "you're welcome", "np", "no problem",
    }
    _msg_clean = message.lower().strip().rstrip(".,!? ")
    if _msg_clean in _TRIVIAL_PHRASES:
        import random as _random
        return _random.choice([
            "What do you want to work on?",
            "What's next?",
            "Ready when you are.",
            "Go ahead.",
        ])

    update_last_session()
    detect_and_save_preference(message)

    # ── Session resolution ────────────────────────────────────────────────────
    if not session_id:
        session_id = get_active_session_id(workspace_root, is_global)
    if not session_id:
        sess = create_session(workspace_root, is_global)
        session_id = sess["id"]
        set_active_session(session_id, workspace_root, is_global)
    else:
        sess = get_session(session_id, workspace_root, is_global)
        if sess is None:   # file deleted externally
            sess = create_session(workspace_root, is_global)
            session_id = sess["id"]
            set_active_session(session_id, workspace_root, is_global)
    _last_session_id = session_id
    session_msgs = (sess or {}).get("messages", [])

    # ── Session rename interceptor ────────────────────────────────────────────
    _rename_result = _handle_session_rename(message, session_id, workspace_root, is_global, session_msgs)
    if _rename_result is not None:
        _last_session_name = _rename_result["name"]
        return _rename_result["text"]

    augmented = build_message_with_file_context(
        message, file_path, file_content, selection,
        workspace_root, attachment_text, attachment_name
    )

    # Instant keyword check — VS Code never spawns agents.
    # But skip the redirect if the message is clearly a question/informational request,
    # even if it happens to contain a keyword like "multiple" or "system".
    _QUESTION_STARTS = (
        "what", "where", "when", "why", "who", "which", "how",
        "show", "tell", "explain", "describe", "list", "give",
        "can you", "could you", "do you", "is ", "are ", "does ",
        "ok ", "okay ", "so ", "and ",
    )
    _lower_msg = message.lower().strip()
    _is_question = any(_lower_msg.startswith(q) for q in _QUESTION_STARTS) or _lower_msg.endswith("?")
    if not _is_question and is_complex_task(message):
        return (
            "This task needs agent execution. Open a terminal and run:\n\n"
            "  python main.py\n\n"
            f"Then type: {message}"
        )

    global _vscode_files_written, _vscode_pending_commands
    _vscode_files_written = []      # reset for this request
    _vscode_pending_commands = []   # reset for this request

    context = build_vscode_system_prompt(workspace_root, is_global, session_msgs)

    # Build user content — multimodal if image attached, plain string otherwise
    if attachment_image_base64:
        user_content = [
            {"type": "text", "text": augmented},
            {"type": "image", "source": {
                "type": "base64",
                "media_type": attachment_image_type or "image/png",
                "data": attachment_image_base64
            }}
        ]
    else:
        user_content = augmented

    # Tool use loop — gives Claude real read/write access when a workspace is open.
    # Without a workspace we fall back to a plain single call (no tool overhead).
    from tools.token_tracker import tracker
    use_tools = bool(workspace_root)
    messages = [{"role": "user", "content": user_content}]
    total_input = total_output = 0
    final_text = ""

    for _ in range(10):  # safety cap — never more than 10 tool rounds
        kwargs = dict(
            model=MODEL_SONNET,
            max_tokens=MAX_TOKENS,
            system=context,
            messages=messages,
        )
        if use_tools:
            kwargs["tools"] = VSCODE_TOOLS

        response = client.messages.create(**kwargs)
        total_input  += response.usage.input_tokens
        total_output += response.usage.output_tokens

        if response.stop_reason == "tool_use":
            # Claude wants to call a file tool — execute it and loop
            messages.append({"role": "assistant", "content": response.content})
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    result = _execute_tool(block.name, block.input, workspace_root)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    })
            messages.append({"role": "user", "content": tool_results})
            continue

        # end_turn or any other stop — extract the text and finish
        for block in response.content:
            if hasattr(block, "text"):
                final_text = block.text
                break
        break

    tracker.log(
        label=f"VS Code: {message[:50]}",
        model=MODEL_SONNET,
        input_tokens=total_input,
        output_tokens=total_output,
    )

    # ── Persist to session ────────────────────────────────────────────────────
    session_append_message(session_id, workspace_root, is_global, "user", message, 0)
    session_append_message(session_id, workspace_root, is_global, "assistant", final_text,
                           total_input + total_output)

    # Auto-name: quick name after 1st exchange, better Haiku name after 3rd
    updated_sess = get_session(session_id, workspace_root, is_global)
    msg_count = len((updated_sess or {}).get("messages", []))
    current_name = (updated_sess or {}).get("name", "")
    if msg_count == 2:
        new_name = auto_name_from_first_message(message)
        update_session_name(session_id, workspace_root, is_global, new_name)
        current_name = new_name[:80]
    elif msg_count == 6:
        better = generate_better_name((updated_sess or {}).get("messages", []))
        if better:
            update_session_name(session_id, workspace_root, is_global, better)
            current_name = better[:80]
    _last_session_name = current_name

    return final_text


def process(user_input: str, history: list) -> str:
    """Main entry point — route task to simple or complex handler."""
    update_last_session()
    detect_and_save_preference(user_input)
    add_to_history("user", user_input)

    # Phase 3.1: Use AI to classify complexity and select model
    classification = ai_classify_task(user_input)
    model = classification["model"]

    if classification["is_complex"]:
        response = handle_complex_task(user_input, model)
    else:
        response = handle_simple_task(user_input, history, model)

    add_to_history("assistant", response)
    return response