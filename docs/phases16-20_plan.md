# Jarvis — Phases 16–20 Plan
**Authored:** March 2026
**Starting state:** Phase 15 complete, 275/275 tests passing

---

## How to continue in a new session
Start with: `docs/roadmap.md` + `docs/phases16-20_plan.md`
Say: **"Continue building Jarvis — see phases16-20_plan.md for what's next"**

---

## Real-World Pain Points (prioritized)

| # | Problem | Impact |
|---|---------|--------|
| 1 | Sessions hit 100-msg wall → oldest context silently dropped | High |
| 2 | Notifications and agent job history lost on server restart | Medium |
| 3 | No way to search past sessions | Medium |
| 4 | Watcher thresholds hardcoded — too aggressive or too loose | Medium |
| 5 | Workspace file tree rebuilt every message (redundant I/O) | Low-Medium |
| 6 | Ratings advisory-only — doesn't actually change agent count | Low |
| 7 | No session export — sessions trapped in JSON | Low |

---

## Phase 16 — Smart Context Management ✅ COMPLETE

**Goal:** Sessions never silently lose context. Token pressure managed automatically.

### A. Session compression (`tools/sessions.py`)
- When `append_message()` would push session past 80 messages: call Haiku to summarize the oldest 40 messages into 1 compressed chunk — instead of dropping them
- Compressed message stored as `{"role": "summary", "content": "...", "ts": ...}`
- `build_vscode_system_prompt()` in orchestrator renders summary messages as `[Earlier context: ...]` block
- Faint indicator in VS Code session header: "40 earlier messages compressed"

### B. Workspace tree caching (`orchestrator.py`)
- `scan_workspace_files()` result cached per session ID (in-memory dict)
- Cache invalidated when workspace directory mtime changes
- Saves ~50ms + disk I/O per message in active sessions

### C. Token budget indicator (VS Code extension)
- `/status` endpoint adds `session_tokens_used` field
- Extension shows a subtle token bar in the session header — only when >50% of a soft budget used

### Files to change
- `tools/sessions.py` — `append_message()` compression trigger + `get_session()` aware of summary messages
- `orchestrator.py` — `build_vscode_system_prompt()` renders `[Earlier context]` + `scan_workspace_files()` caching
- `server.py` — `/status` adds token fields
- `vscode-extension/src/jarvisPanel.ts` — token bar UI in session header

### Estimated tests: ~14
### Effort: 1 session

---

## Phase 17 — Persistence & History ✅ COMPLETE

**Goal:** Server restarts don't wipe state. Full audit trail for agent jobs.

### A. Notification persistence (`tools/notifications.py`)
- Store notifications in `sessions/notifications.json`
- On server startup: load persisted notifications, drop those older than 7 days
- Auto-expire: notifications older than 7 days dismissed on each `get_notifications()` call
- Cap: ≤ 20 notifications on disk

### B. Agent job history (`tools/agent_jobs.py`)
- On job completion (SUCCESS or FAILED): append to `sessions/agent_jobs_history.json`
- Stored per job: `{job_id, task, workspace, agents[], outcome, started_at, finished_at, total_tokens}`
- New endpoint: `GET /agents/history` — returns last 20 completed jobs
- VS Code: collapsed "Past Jobs" section in sessions drawer
- Auto-cleanup: keep only last 100 jobs in history file

### Files to change
- `tools/notifications.py` — `_NOTIFICATIONS_FILE` path + `load_notifications()` + auto-expire logic
- `tools/agent_jobs.py` — `complete_job()` that writes to history file
- `server.py` — `GET /agents/history` endpoint + call `load_notifications()` on startup
- `vscode-extension/src/jarvisPanel.ts` — Past Jobs section in sessions view

### Estimated tests: ~11
### Effort: 1 session

---

## Phase 18 — Session Intelligence ✅ COMPLETE

**Goal:** Find and use past sessions. Export them.

### A. Session search (`tools/sessions.py` + `server.py`)
- `search_sessions(query, workspace_root)` — searches session name + summary + last 5 messages (case-insensitive substring)
- Returns matching sessions with a snippet showing where the match occurred
- New endpoint: `GET /sessions/search?q=cors&workspace=...`
- VS Code: existing search bar wired to server-side search instead of client-side filter

### B. Session export (`server.py`)
- New endpoint: `GET /sessions/export?session_id=...&format=markdown`
- Returns clean markdown: title, date range, message-by-message transcript
- VS Code: "Export" option in session item (··· button or right-click)

### C. Session quick-pick (`vscode-extension/src/jarvisPanel.ts`)
- `vscode.window.showQuickPick()` invoked when panel already focused (via command)
- Lists sessions with search, arrow-key nav, Enter to load

### Files to change
- `tools/sessions.py` — `search_sessions()` function
- `server.py` — `/sessions/search` + `/sessions/export` endpoints
- `vscode-extension/src/jarvisPanel.ts` — server-side search integration + export button + quick-pick

### Estimated tests: ~9
### Effort: 1 session

---

## Phase 19 — Configurable Watcher & Smart Notifications ✦ START HERE

**Goal:** Watcher thresholds tunable per workspace. Smarter detectors.

### A. Config file (`jarvis.config.json` at workspace root — optional)
```json
{
  "watcher": {
    "stale_test_gap_hours": 24,
    "long_branch_days": 5,
    "many_files_count": 8,
    "ignore_branches": ["main", "master", "develop"]
  },
  "notifications": {
    "expire_hours": 168
  }
}
```
- `config.py` adds `load_workspace_config(workspace_root)` helper
- `tools/watcher.py` reads config on each check cycle (hot reload — no restart needed)

### B. Smarter detector logic (`tools/watcher.py`)
- **Branch filtering**: skip all notifications if current branch matches `ignore_branches`
- **Test framework detection**: check for `jest.config.*`, `vitest.config.*`, `__tests__/`, `*.Test.cs` directories — adapt spec-staleness logic accordingly. Currently only checks `.spec.ts` and `Tests.cs`
- **Notification auto-expire**: drop notifications older than `expire_hours` on each `get_notifications()` call

### Files to change
- `config.py` — `load_workspace_config(workspace_root: str) -> dict`
- `tools/watcher.py` — read config on each cycle, branch filtering, multi-framework spec detection
- `tools/notifications.py` — auto-expire parameter in `get_notifications()`
- `server.py` — pass workspace config to `register_workspace()`

### Estimated tests: ~11
### Effort: 1 session

---

## Phase 20 — Deeper Learning (Ratings Upgrade)

**Goal:** Ratings actually influence agent breakdown decisions, not just add advisory comments.

### A. Automatic agent count adjustment (`tools/ratings.py` + `orchestrator.py`)
- When ≥ 2 relevant ratings with score ≤ 2: inject `CONSTRAINT: use at most N-1 agents` into breakdown prompt
- When relevant ratings all score ≥ 4: inject `HINT: N agents worked well for similar tasks`
- Tracks which agent roles (component, service, test, api, migration) appear in high vs low rated breakdowns

### B. Success pattern tracking (`tools/ratings.py`)
- On `save_rating()`: extract agent role names from the last breakdown and store as `successful_roles: [...]`
- `format_ratings_for_injection()` adds: "Tasks like this work best with: component + service agents"
- Rating retention bumped from 50 → 100 entries

### C. Auto-rating UI in VS Code (`server.py` + `jarvisPanel.ts`)
- `/agents/status` returns `rate_prompt: true` 30s after a job completes (if not already rated)
- VS Code shows inline star rating (★☆☆☆☆) directly in agent panel — 1 click, no confirmation

### Files to change
- `tools/ratings.py` — `successful_roles` field, frequency analysis, `_MAX_RATINGS = 100`
- `orchestrator.py` — use rating constraints in `breakdown_into_agents()` prompt
- `server.py` — timed `rate_prompt` flag in `/agents/status`
- `vscode-extension/src/jarvisPanel.ts` — star rating UI in agent results panel

### Estimated tests: ~9
### Effort: 1–2 sessions

---

## Phase 14 — Multi-Project Orchestration (Deferred, LOW priority)

Only needed when regularly working across multiple repos in one task (e.g., "update shared auth lib + update Angular app that consumes it"). Complex, risk of breaking single-repo model.
**Revisit after Phase 20.**

---

## Suggested Build Order

```
Phase 16 → Phase 17 → Phase 18 → Phase 19 → Phase 20 → (Phase 14 if needed)
```

---

## Test Count Projection

| Phase | New Tests | Running Total |
|-------|-----------|---------------|
| Current (end of P15) | — | 275 |
| Phase 16 | 15 | 290 ✅ |
| Phase 17 | 16 | 306 ✅ |
| Phase 18 | 14  | 320 ✅ |
| Phase 19 | ~11 | ~320 |
| Phase 20 | ~9  | ~329 |
