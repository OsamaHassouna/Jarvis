# orchestrator.py
# The brain of Jarvis — decides if a task is simple or complex,
# selects the right model, and for complex tasks spawns real agents.
# Phase 2: Full agent execution with dependency graph support.
# Phase 3: AI-based complexity detection, project auto-detection, agent result memory.

import anthropic
import json
import os
import re
from config import ANTHROPIC_API_KEY, MODEL_SONNET, MODEL_OPUS, MAX_TOKENS
from memory import (
    get_context_summary, add_to_history, load_memory, save_memory, save_task_to_project,
    update_last_session, get_daily_briefing, get_all_projects_summary, learn_preference,
    get_global_rules, add_global_rule, delete_global_rule,
    get_project_rules, add_project_rule, delete_project_rule,
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

    return response.content[0].text

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

    # Phase 6.1: Ask about git auto-commit
    from tools.git_tools import is_git_repo
    auto_git = False
    if is_git_repo(working_dir):
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

    # Phase 3.3: Save task results to project memory
    if summary["succeeded"] > 0:
        save_task_to_project(
            project_path=working_dir,
            task=user_input,
            agents_succeeded=summary["succeeded"],
            agents_total=summary["total"],
            stack=project_info.get("stack", [])
        )

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
) -> str:
    """
    Phase 4/7/8 — Process a message from the VS Code panel.
    Supports text file attachments and image attachments (Claude Vision).
    Uses instant keyword check to redirect complex tasks to the terminal.
    Phase 8: /rules and /project rules commands are intercepted before Claude.
    """
    # Intercept rules commands — no Claude call needed, instant response
    rules_response = handle_rules_command(message, workspace_root)
    if rules_response is not None:
        return rules_response

    update_last_session()
    detect_and_save_preference(message)

    augmented = build_message_with_file_context(
        message, file_path, file_content, selection,
        workspace_root, attachment_text, attachment_name
    )

    # Instant keyword check — VS Code never spawns agents
    if is_complex_task(message):
        return (
            "This task needs agent execution. Open a terminal and run:\n\n"
            "  python main.py\n\n"
            f"Then type: {message}"
        )

    context = get_context_summary()

    # Phase 7: Build user content — multimodal if image attached, plain string otherwise
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

    response = client.messages.create(
        model=MODEL_SONNET,
        max_tokens=MAX_TOKENS,
        system=context,
        messages=[{"role": "user", "content": user_content}]
    )

    from tools.token_tracker import tracker
    tracker.log(
        label=f"VS Code: {message[:50]}",
        model=MODEL_SONNET,
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens
    )

    add_to_history("user", message)
    result = response.content[0].text
    add_to_history("assistant", result)
    return result


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