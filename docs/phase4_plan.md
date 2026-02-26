# Phase 4 — VS Code Integration
**Status:** ✅ Complete
**Date:** February 2026
**Tests:** 62/62 passing (18 + 18 + 14 + 12)

---

## What We Built

A local HTTP server and a VS Code extension that lets you talk to Jarvis
without leaving your editor. Every message automatically includes your
active file as context — no copy-pasting.

---

## Project Structure (new files)

```
jarvis/
├── server.py                         # NEW — HTTP JSON server (localhost:3131)
├── config.py                         # Updated — added SERVER_PORT = 3131
├── vscode-extension/                 # NEW — VS Code extension
│   ├── package.json                  # Extension manifest, commands, keybindings
│   ├── tsconfig.json                 # TypeScript → JavaScript compilation
│   ├── .vscodeignore                 # Exclude src from packaged extension
│   └── src/
│       ├── extension.ts              # Activation, registers commands
│       └── jarvisPanel.ts            # Webview chat panel + server communication
├── tests/
│   └── test_phase4.py                # 12 new tests
└── docs/
    └── phase4_plan.md                # This file
```

**Modified files:**
- `orchestrator.py` — added `build_message_with_file_context()` and `process_for_vscode()`
- `config.py` — added `SERVER_PORT = 3131`

---

## How It Works

```
VS Code                      Jarvis
  │                             │
  │  User types in panel        │
  │  ──────────────────────►    │
  │  POST /chat                 │
  │  { message,                 │
  │    file_path,               │   build_message_with_file_context()
  │    file_content,  ──────►   │   ──► augmented message
  │    selection }              │   ──► ai_classify_task()
  │                             │   ──► handle_simple_task() or redirect
  │  ◄────────────────────────  │
  │  { response: "..." }        │
  │                             │
  │  Displayed in chat bubble   │
```

---

## server.py

- Python's built-in `http.server` — no Flask, no extra dependencies
- Routes:
  - `GET /status` → `{ "status": "running", "version": "phase4" }`
  - `POST /chat` → `{ "response": "..." }` (calls `process_for_vscode()`)
  - `OPTIONS *` → CORS preflight for webview `fetch()`
- `start_server(port, block)` can run blocking (production) or return instance (tests)
- Logs each VS Code message to terminal for visibility

---

## orchestrator.py additions

### `build_message_with_file_context()`
Injects VS Code active-file context into the user message:
- Selection takes priority over file content
- File content truncated to 2000 chars (token safety)
- Skips injection if both are empty

### `process_for_vscode()`
Handles VS Code requests:
- Calls `ai_classify_task()` on the original message
- **SIMPLE** → processes with `handle_simple_task()` using augmented message
- **COMPLEX** → returns a redirect message (no agent spawning over HTTP)
- Logs tokens via `tracker.log()`
- Saves to conversation history

---

## VS Code Extension

### Activation
- Command: `Jarvis: Open Panel` — `Ctrl+Shift+J`
- Command: `Jarvis: Ask About Selection` — `Ctrl+Shift+A` (also in right-click menu)

### Panel features
- VS Code-themed UI (adapts to dark/light theme automatically)
- Status dot (green = server online, red = offline)
- Auto-resize textarea (Shift+Enter for newlines)
- Typing indicator (3-dot bounce animation)
- Active file context injected on every send
- Selected code pre-fills the input (`askAboutSelection` command)
- Clear error message when server is not running

### Setup (one time)
```powershell
cd vscode-extension
npm install          # install TypeScript types
npm run compile      # build to out/extension.js

# Load in VS Code:
# 1. Open vscode-extension/ folder in VS Code
# 2. Press F5 to launch Extension Development Host
```

---

## Usage

**Terminal (start server):**
```powershell
.\venv\Scripts\activate
python server.py
```

**VS Code:**
- Press `Ctrl+Shift+J` → Jarvis panel opens beside your editor
- Type a question → gets answered with your current file as context
- Select some code → press `Ctrl+Shift+A` → ask about selection

---

## Key Decisions

| Decision | Reason |
|---|---|
| Built-in `http.server` (no Flask) | Zero new dependencies |
| port=0 in tests | OS picks a free port — no collisions |
| Complex tasks redirect to terminal | Agent spawning needs interactive `input()` — HTTP blocks |
| Selection over file content | More precise — user selected exactly what they want to ask about |
| 2000 char file content limit | Prevents accidental token explosion on large files |
| Polling server status every 30s | Keeps the status dot accurate without overhead |
| `retainContextWhenHidden: true` | Chat history survives panel focus changes |

---

## Test Coverage (12 new tests)

| Class | Tests |
|---|---|
| TestBuildMessageWithFileContext | no_context, empty_strings, file_path, file_content, selection_priority, selection_only, long_content_truncated |
| TestJarvisHTTPServer | status_200, status_has_version, unknown_404, chat_returns_response, chat_missing_400 |
