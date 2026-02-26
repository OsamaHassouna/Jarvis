# Jarvis — Full Roadmap & Vision
**Last Updated:** February 2026
**Current Status:** Phase 8 Complete ✅

---

## The Vision

Jarvis is a personal AI system that works like Tony Stark's assistant —
it knows you, your projects, and your preferences. Small tasks it handles
directly. Big tasks it breaks down and delegates to specialized agents,
each working in parallel with only the context they need, while Jarvis
supervises and reports back to you.

```
You
 └── Jarvis (Orchestrator — knows the full picture)
      ├── Small task → handles directly, fast and cheap
      └── Big task → breaks down → spawns agents
           ├── Agent A → focused task, isolated context
           ├── Agent B → focused task, isolated context
           └── Agent C → waits for A+B, then executes
                └── All report back → Jarvis summarizes → You
```

---

## Completed Phases

### ✅ Phase 1 — Foundation
- Persistent memory (name, projects, history)
- Single conversational interface
- Smart model selection (Sonnet vs Opus auto)
- 18/18 tests passing

### ✅ Phase 2 — Real Agent Execution
- Real Claude Code agents that create/edit files
- Dependency graph (agents wait for parents)
- Parallel execution (independent agents run simultaneously)
- Live streaming output (no more frozen terminal)
- Upfront confirmation (no overlapping prompts)
- Token tracking per task
- Smart agent count (minimum agents needed)
- 36/36 tests passing

### ✅ Phase 3 — Intelligence Upgrade
- AI-based complexity detection (replaces keyword matching)
- Project auto-detection (Angular, .NET, React from files)
- Project context injected into every agent prompt
- Agent result memory (tasks saved to project history)
- Better JSON error handling in task breakdown
- Dynamic user name in context (not hardcoded)
- 50/50 tests passing

### ✅ Phase 4 — VS Code Integration
- Local HTTP server (`server.py`) on localhost:3131
- VS Code extension with full chat panel (`vscode-extension/`)
- Active file context auto-injected into every message
- Selected code context (Ctrl+Shift+A / right-click menu)
- Status indicator (online/offline dot in panel header)
- Complex tasks redirect to terminal gracefully
- 62/62 tests passing

### ✅ Phase 5 — Full Jarvis Experience
- Multi-project awareness (`get_project_by_name`, `search_projects`, `get_all_projects_summary`)
- Preferences learning — `remember: <pref>` saves style rules that agents follow automatically
- Daily briefing on startup (terminal + VS Code `/briefing` endpoint)
- 86/86 tests passing

### ✅ Phase 6 — Advanced Agent Capabilities
- Git integration — agents auto-commit their work (`tools/git_tools.py`)
- Self-testing agents — run tests, auto-fix failures, report result (`tools/test_runner.py`)
- Browser preview — auto-opens dev server URL after frontend agent completes (`tools/browser.py`)
- 103/103 tests passing

### ✅ Phase 7 — File Upload, Vision & Extensions
- File attachment in VS Code: `+` button, text files injected as context, images sent to Vision API
- File attachment in terminal: `attach <path>` command
- Apply-code button in VS Code panel — one click replaces active file with Jarvis's code suggestion
- Pause/resume agents — Ctrl+C during a run shows continue / skip / cancel menu
- Cross-machine sync — `memory.json` auto-pushed/pulled to private GitHub Gist (`tools/sync.py`)
- 117/117 tests passing

### ✅ Phase 8 — Rules Engine
- **Global rules** — `/rules add <text>` persists rules injected into every Claude call
- **Project rules** — `/project rules add <text>` stores rules that only apply to the current workspace
- `.jarvisrules` file support — drop a file in any project root, auto-detected (no commands needed)
- Commands work identically in terminal and VS Code chat
- Project rules auto-injected into every VS Code message when workspace folder is open
- 139/139 tests passing

---

## Phase 3 — Intelligence Upgrade
**Goal:** Make Jarvis smarter about understanding tasks and remembering context

### 3.1 — AI-Based Complexity Detection
Replace keyword matching with actual Claude intelligence.

**Current (Phase 1-2):**
```python
OPUS_KEYWORDS = ["build", "create project", "full app", ...]
if any(keyword in input for keyword in OPUS_KEYWORDS):
    use_opus()
```

**Phase 3:**
```python
# Ask Claude to evaluate complexity
response = claude.ask("Is this task simple or complex? 
                       Simple = answer directly.
                       Complex = needs agents.
                       Task: {user_input}")
```

**Why:** Keywords miss edge cases. "Help me think through building X"
should be Sonnet (thinking), not Opus (building). Claude understands
intent, keywords don't.

### 3.2 — Project Auto-Detection
Jarvis scans your working directory and remembers project details.

```python
# When user sets a working directory, Jarvis reads:
- package.json → Angular version, dependencies
- .csproj → .NET version, packages
- README.md → project description
- Folder structure → understand what exists
```

**Result:** Agents get real project context, not just task description.
They know your Angular version, existing components, naming conventions.

### 3.3 — Agent Result Memory
Save what each agent built to memory so future sessions know what exists.

```json
{
  "projects": [{
    "name": "login-fullstack",
    "path": "D:\\Personal\\login-fullstack",
    "stack": ["Angular", ".NET"],
    "components": ["LoginFormComponent", "AuthController"],
    "last_updated": "2026-02-26"
  }]
}
```

**Why:** Right now Jarvis forgets what it built. Next time you say
"add a register page to my login project", it should know exactly
what already exists.

### 3.4 — Smarter Task Interruption
Add a proper way to pause/resume/cancel agents mid-execution.

```
You: actually stop, I changed my mind about agent_2

Jarvis: Stopping agent_2... Done.
        agent_1 completed, agent_3 is waiting.
        What would you like to do instead?
```

**Estimated Tests:** 10 new tests
**Estimated Time:** 2-3 sessions

---

## Phase 4 — VS Code Integration
**Goal:** Talk to Jarvis directly from inside VS Code

### 4.1 — VS Code Extension
A simple VS Code extension that opens a Jarvis panel inside the editor.

```
┌─────────────────────────────┐
│  VS Code Editor             │
│  ┌─────────────────────┐    │
│  │  Jarvis Panel       │    │
│  │                     │    │
│  │  You: fix the bug   │    │
│  │  in this component  │    │
│  │                     │    │
│  │  Jarvis: I can see  │    │
│  │  the issue. Line 42 │    │
│  │  has a null check   │    │
│  │  missing...         │    │
│  └─────────────────────┘    │
└─────────────────────────────┘
```

### 4.2 — Active File Context
When you ask Jarvis a question in VS Code, it automatically includes
the file you're currently editing as context.

```python
# Jarvis sees what you see
current_file = vscode.get_active_file()
current_selection = vscode.get_selection()

# So you can just say:
"fix this function" 
# Instead of explaining which file and function
```

### 4.3 — Inline Suggestions
Jarvis can suggest edits directly in the file with VS Code diff view.

**Estimated Tests:** 8 new tests
**Estimated Time:** 3-4 sessions

---

## Phase 5 — Full Jarvis Experience
**Goal:** The complete Jarvis — knows everything, works everywhere

### 5.1 — Multi-Project Awareness
Jarvis knows all your projects and can work across them.

```
You: the login component we built last week — 
     can you reuse it in my new project?

Jarvis: I remember that component. It's in 
        D:\Personal\login-fullstack. I'll copy
        and adapt it for your new project.
```

### 5.2 — Preferences Learning
Jarvis learns your coding style over time.

```json
{
  "preferences": {
    "angular_style": "standalone components",
    "css_approach": "BEM methodology", 
    "api_pattern": "RESTful with JWT",
    "test_framework": "Jest",
    "naming": "camelCase components, kebab-case files"
  }
}
```

Agents automatically follow your style without being told.

### 5.3 — Daily Briefing
When you start Jarvis, it gives you a quick briefing.

```
👋 Good morning, Osama!

📋 Yesterday you worked on: login-fullstack
   └── Created: AuthController, LoginFormComponent

📌 Unfinished: agent_3 (tests) was skipped
   └── Want to pick that up today?

💡 Suggestion: Your Angular version is 17.
   Angular 18 is available with new features.
   Want me to check what's new?
```

### 5.4 — Cross-Machine Sync (Optional)
Sync memory.json to a private GitHub gist or encrypted cloud storage
so Jarvis knows you on any machine.

**Estimated Tests:** 15 new tests
**Estimated Time:** 4-5 sessions

---

## Phase 6 — Advanced Agent Capabilities
**Goal:** Agents that can do anything a senior developer can do

### 6.1 — Git Integration
Agents commit their own work with meaningful messages.

```
Agent [agent_1] completed:
  ✅ Created AuthController.cs
  ✅ git add .
  ✅ git commit -m "feat: add JWT authentication endpoint"
```

### 6.2 — Self-Testing Agents
After creating code, agents run the tests themselves and fix failures.

```
Agent creates component
  → runs: ng test --include login-form.spec.ts
  → 2 tests failing
  → Agent reads failures
  → Agent fixes the code
  → runs tests again
  → All passing ✅
  → Reports back to Jarvis
```

### 6.3 — Browser Preview
For frontend tasks, Jarvis opens a browser preview automatically.

```
✅ Agent completed Angular component
🌐 Opening preview at http://localhost:4200...
```

**Estimated Tests:** 12 new tests
**Estimated Time:** 3-4 sessions

---

## Full Architecture (Phase 7 Complete)

```
You (terminal, VS Code, any machine)
 │
 └── Jarvis Orchestrator
      ├── Memory Layer
      │    ├── Your profile, name & preferences
      │    ├── All projects & task history
      │    ├── Conversation history (50 msgs)
      │    └── GitHub Gist sync (cross-machine)
      │
      ├── Intelligence Layer
      │    ├── AI complexity detection
      │    ├── Model selection (Sonnet/Opus)
      │    ├── Task breakdown (min agents)
      │    ├── Context builder per agent
      │    └── Preference detection (remember: ...)
      │
      ├── Agent Pool
      │    ├── Dependency graph
      │    ├── Parallel execution
      │    ├── Live streaming output
      │    ├── Smart retry + user help
      │    ├── Pause/resume (Ctrl+C menu)
      │    └── Token tracking
      │
      └── Tools
           ├── Claude Code (file creation/editing)
           ├── Git (auto-commit after success)
           ├── Test Runner (run + auto-fix failures)
           ├── Browser (auto-open dev server)
           ├── Sync (push/pull GitHub Gist)
           └── VS Code (file context, vision, apply-code)
```

---

## Priority Order for You (UI/FE Engineer)

Given that you're a UI/FE engineer working with Angular + .NET,
here's the recommended priority:

| Priority | Phase | Why |
|---|---|---|
| 1 | Phase 3.1 — AI Detection | Makes Jarvis much smarter immediately |
| 2 | Phase 3.2 — Project Auto-Detection | Agents know your codebase |
| 3 | Phase 4 — VS Code Integration | Work without leaving your editor |
| 4 | Phase 3.3 — Agent Result Memory | Jarvis remembers what it built |
| 5 | Phase 6.2 — Self-Testing Agents | Agents fix their own bugs |
| 6 | Phase 5 — Full Experience | Complete Jarvis vision |
| 7 | Phase 6.1 — Git Integration | Automated commits |

---

## How To Continue in a New Session

When starting a new conversation to continue this project, share:
1. `docs/roadmap.md` — this file, for full context
2. The phase doc for the most recent phase (e.g. `docs/phase7_plan.md`)
3. The specific files you want to work on

Then say: **"Continue building Jarvis from Phase 8"**

Phase docs: [phase1](phase1_plan.md) · [phase2](phase2_plan.md) · [phase3](phase3_plan.md) · [phase4](phase4_plan.md) · [phase5](phase5_plan.md) · [phase6](phase6_plan.md) · [phase7](phase7_plan.md) · [phase8](phase8_plan.md)

---

## Current Test Count

| Phase | Tests | Status |
|---|---|---|
| Phase 1 | 18 | ✅ All passing |
| Phase 2 | 18 | ✅ All passing |
| Phase 3 | 14 | ✅ All passing |
| Phase 4 | 12 | ✅ All passing |
| Phase 5 | 24 | ✅ All passing |
| Phase 6 | 17 | ✅ All passing |
| Phase 7 | 14 | ✅ All passing |
| Phase 8 | 22 | ✅ All passing |
| **Total** | **139 passing** | |
