# Phase 2 — Real Agent Execution
**Status:** ✅ Complete  
**Date:** February 2026  
**Tests:** 36/36 passing (18 Phase 1 + 18 Phase 2)

---

## What We Built

A full multi-agent execution system where Jarvis breaks complex tasks
into subtasks, spawns real Claude Code agents, manages dependencies,
handles failures intelligently, streams live output, and reports
token usage after every task.

---

## Project Structure

```
jarvis/
├── main.py                  # Entry point — shows token summary after each task
├── orchestrator.py          # Brain — updated with real agent routing
├── memory.py                # Persistent memory
├── config.py                # Settings — dual model support
├── memory.json              # Auto-generated user data
├── .env                     # Secret config
├── .gitignore               # Protects secrets
├── agents/
│   ├── __init__.py
│   ├── agent.py             # Single agent logic with streaming
│   └── agent_pool.py        # Dependency graph + parallel execution
├── tools/
│   ├── __init__.py
│   ├── claude_code.py       # Bridge to Claude Code CLI with live streaming
│   └── token_tracker.py     # Token usage tracking per task + session
├── tests/
│   ├── test_phase1.py       # 18 tests
│   └── test_phase2.py       # 18 tests
└── docs/
    ├── phase1_plan.md
    └── phase2_plan.md       # This file
```

---

## New Files Explained

### tools/claude_code.py
- Bridge between Jarvis and Claude Code CLI
- Runs Claude Code as a subprocess in agent mode (`--dangerously-skip-permissions`)
- **Streams output line by line** so you see exactly what Claude Code is doing
- Handles timeouts (10 minutes per agent)
- Auto-creates working directories if they don't exist
- Asks user where to work (custom path / current directory)
- **Why:** Agents need to actually execute code somewhere. Streaming
  means no more frozen terminal — you see every action in real time.

### tools/token_tracker.py
- Tracks token usage for every task and agent call in a session
- Calculates cost in USD based on model pricing
- Shows per-task breakdown in final summary
- Displays session total tokens and total cost
- Attempts to fetch remaining API credits from Anthropic
- Resets after each task so next task starts fresh
- **Why:** Visibility into cost. You know exactly what each task costs
  and can make informed decisions about model choice.

### agents/agent.py
- Represents one focused agent with one task
- Tracks status: PENDING → RUNNING → SUCCESS/FAILED/SKIPPED
- Knows its dependencies and whether others depend on it
- Retry logic: retries once if dependents exist, asks user if still failing
- 10 minute timeout per agent
- **Why:** Each agent is isolated — only knows its task and minimal
  context. Keeps token usage low and agents focused.

### agents/agent_pool.py
- **Phase 1: Confirms ALL agents upfront one by one** — no overlapping prompts
- **Phase 2: Executes confirmed agents** respecting dependency graph
- Runs independent agents in parallel using threads
- Handles cascading skips when a parent agent fails
- Shows live streaming output during execution
- Builds final summary with counts and results
- **Why:** Separating confirmation from execution eliminates the
  overlapping prompt problem completely.

---

## Agent Execution Flow

```
User gives complex task
        ↓
Jarvis selects Opus (complex task)
        ↓
Jarvis asks Claude to break into MINIMUM agents (JSON)
├── Single component = 1 agent
├── Feature with connected files = 2 agents
├── Full page frontend + backend = 3 agents
└── Full system = 5-6 agents max
        ↓
Jarvis shows plan → user confirms overall plan
        ↓
User selects working directory (Jarvis creates it if needed)
        ↓
AgentPool Phase 1: Confirm each agent one by one
        ↓
AgentPool Phase 2: Execute
├── Independent agents → run in parallel (threads)
└── Dependent agents → wait for parents to complete
        ↓
Live streaming output per agent (you see every action)
        ↓
Each agent result:
├── Success → mark complete, unblock dependents
└── Failure:
    ├── Has dependents → retry once
    │   ├── Success → continue chain
    │   └── Still failing → ask user for help
    │       ├── User fixes → retry → continue
    │       └── User skips → cascade skip dependents
    └── No dependents → skip silently
        ↓
Agent pool summary: succeeded / failed / skipped
        ↓
Token usage summary: per-task cost + session total + remaining credits
```

---

## Smart Agent Count Rules

Jarvis uses MINIMUM agents needed — no over-splitting:

| Task Size | Agents | Example |
|---|---|---|
| Single component/file | 1 | Angular login component |
| Feature with 2-3 connected files | 2 | Component + service |
| Full page frontend + backend | 3 | Angular page + .NET API + tests |
| Complete feature with tests | 3-4 | Full auth feature |
| Full app or system | 5-6 | Complete project scaffold |

**Why:** Using 5 agents for one component was slow and wasteful.
1 agent for a single component is faster and produces the same quality.

---

## Token Tracking

After every task Jarvis shows:

```
═══════════════════════════════════════════════════════
💰 TOKEN USAGE SUMMARY
═══════════════════════════════════════════════════════

📋 Task breakdown: build a login form...
   Model:  Opus
   Tokens: 1,234 in + 567 out = 1,801 total
   Cost:   $0.000245

📋 Agent [agent_1]: Create Angular login component...
   Model:  Opus
   Tokens: 2,100 in + 890 out = 2,990 total
   Cost:   $0.000412

───────────────────────────────────────────────────────
📊 Session Total Tokens: 4,791
💵 Session Total Cost:   $0.000657

🏦 Remaining API Credits: $4.87
═══════════════════════════════════════════════════════
```

---

## Key Decisions & Why

| Decision | Reason |
|---|---|
| Claude Code as subprocess | Most powerful way to execute real code tasks |
| Stream output with Popen | No more frozen terminal — see every action live |
| Threading for parallel agents | Independent tasks shouldn't wait for each other |
| Confirm ALL agents upfront | Eliminates overlapping prompt problem completely |
| Dependency graph | Ensures correct execution order |
| Minimum agent count | Faster execution, less token waste |
| Max 6 agents per task | Prevents runaway token usage |
| 10 min timeout per agent | Heavy tasks (scaffold .NET/Angular) need more time |
| Token tracker resets per task | Each task shows its own cost clearly |
| Auto-create directories | Less friction — Jarvis creates folders it needs |

---

## Failure Handling Logic

```
Agent fails
 └── Has dependents waiting?
      ├── YES
      │    └── Retry once automatically
      │         ├── Success → continue chain ✅
      │         └── Still failing → ask user
      │              ├── User fixes it → retry → continue ✅
      │              └── User skips → cascade skip all dependents ⏭️
      └── NO → skip silently, continue others ⏭️
```

---

## Dependencies Added

| Package | Purpose |
|---|---|
| `threading` (built-in) | Parallel agent execution |
| `subprocess` (built-in) | Run Claude Code CLI |
| `anthropic` (already installed) | Token usage data + API credits |

---

## Bug Fixes Applied During Testing

| Bug | Fix |
|---|---|
| `memory.json` deleted during tests | Tests use isolated `test_memory_temp.json` |
| Invalid directory caused failure | Jarvis auto-creates directories |
| Claude Code in print mode only | Switched to agent mode with `--dangerously-skip-permissions` |
| Parallel confirmation prompts overlapping | Confirm ALL agents upfront before any execution |
| Terminal freezing silently | Switched to streaming output with `Popen` |
| 5 agents for single component | Added minimum agent count rules to breakdown prompt |
| 5 min timeout too short for heavy tasks | Increased to 10 minutes per agent |
| Token summary only on exit | Now shows after every task, resets for next |

---

## Limitations (To Be Addressed in Phase 3)

- No VS Code integration yet
- Memory doesn't auto-detect your projects
- No cross-machine sync
- Agent results not saved to memory for future reference
- No way to pause/resume an agent run mid-execution
- Complexity detection still keyword-based (not AI-based)
- Remaining API credits fetch may not work on all account types

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

## Test Coverage (36 total)

| Class | Tests |
|---|---|
| TestConfig (Phase 1) | API key, format, models, max tokens |
| TestMemory (Phase 1) | All memory operations, history limit, projects |
| TestOrchestrator (Phase 1) | Simple/complex detection, case insensitive |
| TestModelSelection (Phase 1) | Sonnet/Opus routing |
| TestClaudeCodeBridge (Phase 2) | CLI installed, invalid dir, confirm exists |
| TestAgent (Phase 2) | Creation, dependencies, has_dependents, multiple deps |
| TestAgentPool (Phase 2) | Pool creation, ready agents, done state, skip dependents, summary |
| TestOrchestratorPhase2 (Phase 2) | Complex detection, model selection still work |
