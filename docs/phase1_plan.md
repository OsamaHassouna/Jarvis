# Phase 1 — Foundation
**Status:** ✅ Complete  
**Date:** February 2026  
**Tests:** 18/18 passing

---

## What We Built

A working foundation for Jarvis — a personal AI assistant with memory,
an intelligent orchestrator, smart model selection, and a single conversational interface.

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
│   └── test_phase1.py   # 18 automated tests
└── docs/
    └── phase1_plan.md   # This file
```

---

## Files Explained

### config.py
- Loads the Anthropic API key from `.env` using `python-dotenv`
- Defines TWO models: `MODEL_SONNET` and `MODEL_OPUS`
- Defines max tokens (4096) and memory file path
- Validates that the API key exists on startup
- **Why:** Centralizes all settings in one place. Easy to change models or
  limits without touching other files.

### memory.py
- Stores user info, projects, and conversation history in `memory.json`
- Keeps last 50 messages to avoid token overflow
- Prevents duplicate projects
- Builds a context summary string fed to the orchestrator
- Includes recent conversation history so Jarvis remembers past sessions
- **Why:** Gives Jarvis persistent memory across sessions. Without this,
  every session starts from zero.

### orchestrator.py
- Detects if a task is simple or complex using keyword matching
- Auto-selects model: Sonnet for simple tasks, Opus for complex
- Simple tasks → handled directly via Claude API
- Complex tasks → broken down into subtasks (agents in Phase 2)
- Saves every message to memory history
- **Why:** Core intelligence layer. Decides HOW to handle each request
  and WHICH model to use, keeping simple things fast and cheap.

### main.py
- First-time setup asks for user's name and saves it to memory
- Returning users get a personalized welcome back message
- Runs a continuous conversation loop until user types exit
- Shows token usage summary after every task
- Handles errors gracefully without crashing
- **Why:** Single entry point. One command to start everything.

---

## Smart Model Selection (Phase 1.5 Upgrade)

Jarvis automatically picks the right model based on task complexity.

| Task Type | Model | Example |
|---|---|---|
| Quick questions | Sonnet | "what is flexbox?" |
| Explanations | Sonnet | "explain async/await" |
| Complex dev work | Opus | "build authentication system" |
| Architecture decisions | Opus | "design the system architecture" |
| Default (unknown) | Sonnet | anything else |

**Why this matters:**
- Sonnet is ~5x cheaper than Opus
- For a UI/FE engineer, 80% of daily tasks are Sonnet-level
- Opus is reserved for when it genuinely matters
- $5 API credits lasts much longer

---

## Key Decisions & Why

| Decision | Reason |
|---|---|
| Python for orchestrator | Fastest setup, best AI tooling |
| `.env` for API key | Security — never hardcode secrets |
| Virtual environment (`venv`) | Isolates dependencies per project |
| 50 message history limit | Balances memory vs token cost |
| Dual model (Sonnet/Opus) | Cost efficiency without sacrificing quality |
| Keyword-based complexity detection | Simple and fast for Phase 1, upgraded to AI-based in Phase 3 |
| `pytest` for testing | Industry standard, clean output |

---

## Dependencies

| Package | Version | Purpose |
|---|---|---|
| anthropic | 0.84.0 | Claude API client |
| python-dotenv | 1.2.1 | Load .env variables |
| pytest | 9.0.2 | Automated testing |

---

## Bug Fixes Applied

| Bug | Fix |
|---|---|
| Name asked every session | `get_context_summary()` now loads history so memory persists properly |
| History not loaded on restart | Recent 20 messages included in context summary |

---

## Limitations (Addressed in Later Phases)

- Complex task detection uses simple keywords — can miss edge cases (Phase 3)
- Memory is local only — not synced across machines (Phase 3)
- No VS Code integration yet (Phase 3)
- Token tracking shows estimates only — not live API balance (Phase 2.5)

---

## How To Run

```powershell
# Activate venv
.\venv\Scripts\activate

# Start Jarvis
python main.py

# Run tests
pytest tests/test_phase1.py -v
```

---

## Test Coverage (18 tests)

| Class | Tests |
|---|---|
| TestConfig | API key exists, format, models set, max tokens |
| TestMemory | Load default, save/load, update, history, limit, projects, no duplicates, context summary |
| TestOrchestrator | Simple detected, complex detected, case insensitive |
| TestModelSelection | Simple → Sonnet, complex → Opus, default → Sonnet |
