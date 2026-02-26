# Phase 1 — Foundation
**Status:** ✅ Complete  
**Date:** February 2026  
**Tests:** 15/15 passing

---

## What We Built

A working foundation for Jarvis — a personal AI assistant with memory,
an intelligent orchestrator, and a single conversational interface.

---

## Project Structure
```
jarvis/
├── main.py              # Entry point — run this to talk to Jarvis
├── orchestrator.py      # Brain — routes simple vs complex tasks
├── memory.py            # Persistent memory across sessions
├── config.py            # API keys and settings
├── memory.json          # Auto-generated — stores user data
├── .env                 # Secret config — never share or commit
├── .gitignore           # Protects .env and venv from git
├── tests/
│   └── test_phase1.py   # 15 automated tests
└── docs/
    └── phase1_plan.md   # This file
```

---

## Files Explained

### config.py
- Loads the Anthropic API key from `.env` using `python-dotenv`
- Defines the model (`claude-opus-4-6`), max tokens (4096), and memory file path
- Validates that the API key exists on startup
- **Why:** Centralizes all settings in one place. Easy to change model or
  limits without touching other files.

### memory.py
- Stores user info, projects, and conversation history in `memory.json`
- Keeps last 50 messages to avoid token overflow
- Prevents duplicate projects
- Builds a context summary string fed to the orchestrator
- **Why:** Gives Jarvis persistent memory across sessions. Without this,
  every session starts from zero.

### orchestrator.py
- Detects if a task is simple or complex using keyword matching
- Simple tasks → handled directly via Claude API in the same session
- Complex tasks → broken down into subtasks (agents come in Phase 2)
- Saves every message to memory history
- **Why:** This is the core intelligence layer. It decides HOW to handle
  each request, keeping simple things fast and preparing for agent
  execution in future phases.

### main.py
- First-time setup asks for user's name and saves it to memory
- Returning users get a personalized welcome back message
- Runs a continuous conversation loop until user types exit
- Handles errors gracefully without crashing
- **Why:** Single entry point keeps things simple. One command to start
  everything.

---

## Key Decisions & Why

| Decision | Reason |
|---|---|
| Python over Angular/.NET for orchestrator | Fastest setup, best AI tooling |
| `.env` for API key | Security — never hardcode secrets |
| Virtual environment (`venv`) | Isolates dependencies per project |
| 50 message history limit | Balances memory vs token cost |
| Keyword-based complexity detection | Simple and fast for Phase 1, will be upgraded to AI-based detection in Phase 3 |
| `pytest` for testing | Industry standard, clean output |

---

## Dependencies

| Package | Version | Purpose |
|---|---|---|
| anthropic | 0.84.0 | Claude API client |
| python-dotenv | 1.2.1 | Load .env variables |
| pytest | 9.0.2 | Automated testing |

---

## Limitations (To Be Addressed in Later Phases)

- Complex task detection uses simple keywords — can miss edge cases
- Subagents are planned but not yet executing (Phase 2)
- Memory is local only — not synced across machines (Phase 3)
- No VS Code integration yet (Phase 3)

---

## How To Run
```powershell
# Make sure venv is active
.\venv\Scripts\activate

# Start Jarvis
python main.py

# Run tests
pytest tests/test_phase1.py -v
```

---

## Phase 1.5 Upgrade — Smart Model Selection
**Status:** ✅ Complete  
**Tests:** 18/18 passing

### What Changed
Jarvis now automatically picks the right model based on task complexity.
No more manual switching — it decides for you.

### Logic
| Task Type | Model | Example |
|---|---|---|
| Quick questions | Sonnet | "what is flexbox?" |
| Explanations | Sonnet | "explain async/await" |
| Complex dev work | Opus | "build authentication system" |
| Architecture | Opus | "design the system architecture" |
| Default (unknown) | Sonnet | anything else |

### Why This Matters
- Sonnet is ~5x cheaper than Opus
- For a UI/FE engineer, 80% of daily tasks are Sonnet-level
- Opus is reserved for when it genuinely matters
- $5 API credits will last much longer

### Files Changed
- `config.py` — replaced `MODEL` with `MODEL_SONNET` and `MODEL_OPUS`
- `orchestrator.py` — added `select_model()` function
- `tests/test_phase1.py` — added `TestModelSelection` with 3 new tests

## Phase 2 Preview

- Spawn real Claude Code subagents for complex tasks
- Each subagent gets only the context it needs
- Orchestrator collects results and summarizes back to user
- Git worktrees for isolated agent workspaces

---