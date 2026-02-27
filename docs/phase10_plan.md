# Phase 10 — Session Persistence + Server Crash Fix
**Status:** ✅ Complete
**Date:** February 2026
**Tests:** 175/175 passing (18 + 18 + 14 + 12 + 24 + 17 + 14 + 22 + 15 + 21)

---

## What We Built

Two things that were blocking the VS Code experience:

1. **Server crash fix**: Port 3131 stayed occupied after Ctrl+C. Every fast restart
   failed with "Address already in use." Fixed with a custom `JarvisHTTPServer` subclass.

2. **Session persistence**: VS Code chat had no memory between panel open/close.
   Every session started blank. Built per-project and global chat sessions that survive
   restarts, with a session history drawer, auto-naming, and a project-level cumulative
   summary so Jarvis always has context without re-reading all messages.

---

## Project Structure (new/changed files)

```
jarvis/
├── tools/
│   └── sessions.py           # New — all session + project-summary I/O
├── orchestrator.py           # +session params, +build_vscode_system_prompt
│                             # +_last_session_id, +_last_session_name globals
├── server.py                 # JarvisHTTPServer fix + 5 new session endpoints
├── vscode-extension/
│   └── src/
│       └── jarvisPanel.ts    # Session state, history drawer, restore on load
├── tests/
│   └── test_phase10.py       # 21 new tests
└── docs/
    └── phase10_plan.md       # This file
```

---

## Server Crash Fix

### Problem

`ThreadingHTTPServer` spawns a new thread per request. When `Ctrl+C` is pressed,
running threads (e.g., a blocked `/run-command`) stay alive and hold port 3131 open.
The next `python server.py` fails with "Address already in use."

### Fix: `JarvisHTTPServer`

```python
class JarvisHTTPServer(ThreadingHTTPServer):
    daemon_threads     = True   # request threads die with the process → no port hold
    allow_reuse_address = True  # fast restart without "Address already in use"
```

`start_server()` now uses `JarvisHTTPServer(...)` instead of `ThreadingHTTPServer(...)`.

---

## Session Storage Layout

Sessions live in `d:/Personal/Jarvis/sessions/` alongside `memory.json`.

```
sessions/
├── global/
│   ├── _active.json           # {"active_session_id": "sess_..."}
│   └── sess_<id>.json
└── projects/
    └── <workspace_hash>/      # MD5-12 of lowercase/normalised workspace_root
        ├── _summary.json      # cumulative project summary + session index
        └── sess_<id>.json
```

**`workspace_hash`** is a stable 12-char MD5 hex of the normalised path (lowercased,
forward slashes, trailing slash stripped). Case-insensitive and OS-path-insensitive.

### Session file shape

```json
{
  "id": "sess_3a7f9d1c",
  "name": "Fix auth CORS error",
  "workspace_root": "D:/Projects/MyApp",
  "project_name": "MyApp",
  "is_global": false,
  "created_at": "2026-02-27T14:30:00",
  "updated_at": "2026-02-27T15:45:00",
  "messages": [
    {"role": "user",      "content": "...", "ts": "2026-02-27T14:30:05"},
    {"role": "assistant", "content": "...", "ts": "2026-02-27T14:30:10"}
  ],
  "summary": "",
  "token_total": 0
}
```

Messages are capped at the last 100 entries to prevent unbounded growth.

### Project summary shape (`_summary.json`)

```json
{
  "workspace_root": "D:/Projects/MyApp",
  "project_name": "MyApp",
  "last_updated": "...",
  "cumulative_summary": "Angular 17 task-management app. Set up JWT auth (Feb 25). Fixed CORS (Feb 27).",
  "active_session_id": "sess_3a7f9d1c",
  "sessions": [
    {"id": "sess_3a7f9d1c", "name": "Fix auth CORS error", "summary": "...", "created_at": "...", "updated_at": "..."}
  ]
}
```

---

## `tools/sessions.py` — All Functions

### Utilities
- `sessions_dir()` — returns/creates the `sessions/` root
- `workspace_hash(workspace_root)` — stable 12-char MD5 hex of normalised path
- `generate_session_id()` — returns `"sess_" + uuid4()[:8]`

### Session CRUD
- `create_session(workspace_root, is_global, project_name)` — creates and writes session JSON
- `get_session(session_id, workspace_root, is_global)` — reads file, returns `None` if missing
- `save_session(session)` — derives path from session fields, writes
- `append_message(session_id, workspace_root, is_global, role, content, token_count)` — appends and saves, caps at 100

### Naming
- `update_session_name(session_id, workspace_root, is_global, name)` — truncates to 80 chars, saves
- `auto_name_from_first_message(content)` — first 50 chars, no API call
- `generate_better_name(messages)` — Haiku call (max_tokens=20): 6-word title. Returns `""` on failure

### Active session tracking
- `get_active_session_id(workspace_root, is_global)` — reads `_summary.json` or `_active.json`
- `set_active_session(session_id, workspace_root, is_global)` — writes to appropriate pointer file

### Session lifecycle
- `close_session(session_id, workspace_root, is_global)` — Haiku (max_tokens=150) generates 2-3 sentence summary, saves to session, updates project summary. Returns summary or `""`. Never raises.

### Listing
- `list_project_sessions(workspace_root)` — all sessions for a project, sorted by `updated_at` desc
- `list_global_sessions()` — all global sessions, sorted desc
- `list_all_sessions()` — grouped dict: `{"global": [...], "projects": {"path": {...}}}`

### Project summary
- `get_project_summary(workspace_root)` — loads `_summary.json` or returns default structure
- `get_project_summary_text(workspace_root)` — returns `cumulative_summary` string, or `""`
- `update_project_summary(workspace_root, session)` — upserts session index, re-generates cumulative summary via Haiku. Best-effort, never raises.

---

## `orchestrator.py` Changes

### New module-level globals

```python
_last_session_id:   str = ""
_last_session_name: str = ""

def get_last_session_id()   -> str: return _last_session_id
def get_last_session_name() -> str: return _last_session_name
```

Same pattern as the existing `_vscode_files_written` / `get_last_files_written()`.

### `build_vscode_system_prompt(workspace_root, is_global, session_messages) -> str`

New helper that replaces `get_context_summary()` for the VS Code path only.
Terminal mode still calls `get_context_summary()` — unchanged.

Injects (in order):
1. Jarvis persona + user name/preferences
2. Global rules
3. If `is_global=False`: `get_project_summary_text(workspace_root)` — 1 paragraph, cheap
4. If `is_global=True`: brief summaries of up to 3 recently-updated projects
5. Last 20 messages from the current session (replaces global history)
6. Interface feature hints + behaviour rules

### Updated `process_for_vscode()` signature

```python
def process_for_vscode(
    message, file_path="", file_content="", selection="",
    workspace_root="", attachment_text="", attachment_name="",
    attachment_image_base64="", attachment_image_type="",
    session_id="",      # NEW
    is_global=False,    # NEW
) -> str:
```

### Session resolution block (runs after command intercepts)

```python
global _last_session_id
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
```

### Auto-naming (replaces `add_to_history()` calls)

After each exchange, messages are appended to the session file (not to global history).
After 2nd message (first exchange complete): quick name from first user message.
After 6th message (third exchange): Haiku generates a better 6-word title.

---

## `server.py` — New Endpoints

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/sessions/new` | Closes current session (for summary), creates new one. Body: `{workspace_root, is_global}`. Response: `{session}` |
| `GET` | `/sessions/list` | All sessions grouped by project. Response: `{global:[...], projects:{...}}` |
| `GET` | `/sessions/active?workspace_root=<enc>` | Active session for a workspace. Response: `{session}` or `{session:null}` |
| `GET` | `/sessions/load?session_id=<id>&workspace_root=<enc>&is_global=<0\|1>` | Load and set active. Response: `{session}` |
| `POST` | `/sessions/close` | Summarise session. Body: `{session_id, workspace_root, is_global}`. Response: `{summary}` |

`/chat` response now includes `session_id` and `session_name` so the panel can
update its display after the first message of a new session.

GET endpoints use `urlparse` + `parse_qs` + `unquote` to parse query strings cleanly.

---

## VS Code Panel Changes (`jarvisPanel.ts`)

### New state fields

```typescript
private _currentSessionId:  string  = '';
private _currentIsGlobal:   boolean = false;
private _sessionRestored:   boolean = false;
```

### Session restore on startup

`_checkServer()` calls `_restoreActiveSession()` exactly once when the server first
comes online. The `_sessionRestored` flag prevents it re-running every 30 seconds.

`_restoreActiveSession()` GETs `/sessions/active` and, if a session is found,
populates the chat panel with the session's existing messages so the conversation
continues where it left off.

### Updated `_handleSend()`

```typescript
// In request body
session_id: this._currentSessionId,
is_global:  this._currentIsGlobal,

// On response
if (data.session_id) { this._currentSessionId = data.session_id; }
```

### New header buttons

```
Jarvis — MyApp  [New Session +]  [History ≡]
```

- **`+`** button → calls `_newSession(false)` (creates a project session)
- **`≡`** button → opens the session history drawer

### Session history drawer

```
┌─ Sessions ─────────────────────────────────────── [Global □]  [New]  [✕] ─┐
│                                                                             │
│  MyApp                                                                      │
│  ▶  Fix auth CORS error          •  Feb 27                                 │
│     Set up JWT auth              •  Feb 25                                 │
│                                                                             │
│  Global                                                                     │
│     General questions            •  Feb 24                                 │
└─────────────────────────────────────────────────────────────────────────── ┘
```

- Shows project sessions grouped by project name, and global sessions separately
- Active session highlighted
- Clicking a session loads it: previous messages populate the chat
- "New" button in drawer respects the "Global" checkbox

---

## Key Design Decisions

| Decision | Reason |
|---|---|
| File-based sessions (not DB) | Zero dependencies, survives server restart, easy to inspect/debug |
| `workspace_hash` as directory name | Stable across OS path separator differences and case variations |
| `build_vscode_system_prompt` separate from `get_context_summary` | Terminal mode unchanged; VS Code gets lightweight project summary instead of full global history |
| Session messages replace global history in VS Code | No double-counting; session is the source of truth for conversation history |
| `close_session` called on session switch | Old session gets a Haiku summary automatically — cumulative project context grows without manual work |
| Cap messages at 100 | Prevents unbounded session files; last 100 messages is plenty for context |
| `_sessionRestored` flag | Prevents session restore from re-running every 30-second ping cycle |
| `_last_session_id` / `_last_session_name` globals | Avoids changing `process_for_vscode()` return type; consistent with existing `get_last_files_written()` pattern |

---

## Test Coverage (21 new tests)

All tests redirect `config.MEMORY_FILE` to a `tempfile.mkdtemp()` path so
`sessions_dir()` writes to a temp directory. Haiku calls are monkeypatched via
`unittest.mock.patch`.

| Class | Tests |
|---|---|
| TestUtilities | workspace_hash_is_stable, workspace_hash_case_insensitive, generate_session_id_format |
| TestCreateSession | project_session_creates_file, global_session_creates_file, returns_expected_shape, messages_empty |
| TestAppendMessage | appends_user_message, increments_token_total, updates_timestamp |
| TestSessionNaming | auto_name_truncates, update_name_persists |
| TestActiveSessions | set_get_active_project, set_get_active_global |
| TestListSessions | list_project_empty, list_project_returns_created, list_all_structure |
| TestProjectSummary | text_empty_no_file, text_returns_cumulative, update_creates_file (mocked Haiku) |
| TestCloseSession | stores_summary (mocked Haiku) |
