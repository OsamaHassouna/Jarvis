# Phase 3 — Intelligence Upgrade
**Status:** ✅ Complete
**Date:** February 2026
**Tests:** 50/50 passing (18 Phase 1 + 18 Phase 2 + 14 Phase 3)

---

## What We Built

Three major intelligence upgrades that make Jarvis smarter, context-aware,
and persistent about what it builds.

---

## Project Structure (new files)

```
jarvis/
├── tools/
│   └── project_scanner.py   # NEW — scans working dir for project context
├── tests/
│   └── test_phase3.py       # NEW — 14 tests for Phase 3 features
└── docs/
    └── phase3_plan.md       # This file
```

**Modified files:**
- `orchestrator.py` — AI classification, project context injection, agent result saving
- `memory.py` — Fixed hardcoded name, added `save_task_to_project()`
- `agents/agent_pool.py` — Added `get_ready_agents()` method (bug fix)

---

## Bug Fixes Applied

| Bug | Fix |
|---|---|
| `test_phase2.py` called `pool.get_ready_agents()` which didn't exist | Added method to `AgentPool` |
| Hardcoded `"Osama"` in `memory.py:74` | Now uses `memory["user"]["name"]` dynamically |
| `json.loads()` in `breakdown_into_agents()` had no error handling | Added try/except with helpful message showing raw response |

---

## 3.1 — AI-Based Complexity Detection

**File:** `orchestrator.py`
**Function:** `ai_classify_task(user_input)`

Uses Claude Sonnet (cheap, max_tokens=20) to classify tasks:
- `SIMPLE` → answer directly with Sonnet
- `COMPLEX` → spawn agents with Opus

Falls back to keyword matching silently if the API call fails.

**Before:**
```python
OPUS_KEYWORDS = ["build", "create project", "full app", ...]
if any(keyword in input for keyword in OPUS_KEYWORDS):
    use_opus()
```

**After:**
```python
response = claude.ask(
    "SIMPLE = answer directly. COMPLEX = needs to create files. Task: {input}"
)
# Falls back to keywords if API fails
```

**Why:** Keywords miss intent. "Help me think through building X" should
be Sonnet (thinking), not Opus (building). Claude understands context,
keywords don't.

---

## 3.2 — Project Auto-Detection

**File:** `tools/project_scanner.py`
**Functions:** `scan_project(directory)`, `get_context_string(project_info)`

Scans a directory for:
- `package.json` → Angular version, React, Vue, package manager
- `*.csproj` → .NET major version
- `angular.json` → Angular project names
- `README.md` → Project description

Returns a structured dict injected into every agent's task prompt:
```
Project context:
- Frontend: Angular 18
- Backend: .NET 8
- Project: my-login-app
- Note: Angular 17+ — prefer standalone components
- Note: Package manager: npm
```

**Why:** Without this, agents had no idea what framework you're using.
Now they automatically use the right Angular version, know if .NET is
present, and follow your project's conventions.

---

## 3.3 — Agent Result Memory

**File:** `memory.py`
**Function:** `save_task_to_project(project_path, task, agents_succeeded, agents_total, stack)`

After every successful complex task, saves to `memory.json`:
```json
{
  "projects": [{
    "name": "my-login-app",
    "path": "D:\\Personal\\my-login-app",
    "stack": ["Angular 18", ".NET 8"],
    "tasks_completed": [{
      "date": "2026-02-26",
      "task": "Build Angular login form with JWT auth",
      "agents_succeeded": 2,
      "agents_total": 2
    }],
    "last_updated": "2026-02-26T..."
  }]
}
```

**Why:** Jarvis can now remember what was built in past sessions.
Future features (Phase 5) will use this to avoid duplicating work
and to suggest relevant context.

---

## Key Decisions

| Decision | Reason |
|---|---|
| Sonnet for AI classification | It's cheap (max 20 tokens) and fast — no need for Opus |
| Keyword fallback if AI fails | Robustness — never crash on classification |
| `import re` inside scan_project | Avoids module-level import for rarely used feature |
| `.NET major version only` | "NET 8" is cleaner than "NET 8.0" |
| `save_task_to_project` merges stack | Running multiple tasks on same dir accumulates stack info |
| `copy.deepcopy(DEFAULT_MEMORY)` in tests | Prevents shared mutable state between test methods |

---

## How To Run

```powershell
# Activate venv
.\venv\Scripts\activate

# Start Jarvis
python main.py

# Run all tests
pytest tests/ -v
```

---

## Test Coverage (50 total)

| Class | Tests |
|---|---|
| Phase 1 tests | 18 ✅ |
| Phase 2 tests | 18 ✅ |
| TestAIComplexityDetection | returns_required_keys, simple_mock, complex_mock, fallback_on_error |
| TestProjectScanner | empty_dir, detects_angular, detects_dotnet, invalid_dir, context_empty, context_with_data |
| TestAgentResultMemory | creates_project, appends_task, stores_stack, dynamic_name |
