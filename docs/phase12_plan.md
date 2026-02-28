# Phase 12 — Full VS Code Parity ✅ Complete

**Status:** Complete — 20 tests passing (215 total)
**Completed:** February 2026

---

## Goal

VS Code panel becomes a first-class interface equal to the terminal.
Complex tasks no longer redirect with "open a terminal" — they run
directly from the chat, with a live agent progress panel.

---

## What Was Built

### `tools/agent_jobs.py`
In-memory job store. Thread-safe dict: `job_id → job_state`.

```python
create_job(job_id, workspace_root)    # → {status: "starting", agents: {}, ...}
register_agents(job_id, agent_defs)   # populate agents after breakdown
update_job_status(job_id, status)     # starting | running | done | failed
update_agent_status(job_id, agent_id, **kwargs)  # status, output, files_*
get_job(job_id)                       # shallow copy or None
list_active_jobs()                    # starting + running only
cleanup_old_jobs(max_age_seconds)     # GC for finished jobs
generate_job_id()                     # "job_" + 8 hex chars
```

No disk I/O. State lives only while `server.py` is running.

---

### `agents/agent.py` — two new fields

| Field | Type | Purpose |
|---|---|---|
| `on_status_change` | `Optional[Callable]` | Called at running / success / failed transitions |
| `vscode_mode` | `bool` | When True, `ask_user_for_help()` auto-skips instead of blocking on `input()` |

`_notify(**kwargs)` fires the callback best-effort (exceptions swallowed).

---

### `agents/agent_pool.py` — `execute_vscode(job_id)`

Drop-in replacement for `execute()` that:
- Does NOT call `_confirm_all_agents()` (no `input()`)
- Sets `vscode_mode=True` on every agent
- Wires `on_status_change` → `update_agent_status()` in job store
- Updates job status: `running` at start, `done` or `failed` at end
- Returns `{total, succeeded, failed, skipped}` summary

`_run_agent_vscode(agent)` — thread target: handles retry + skip without prompts.

---

### `orchestrator.py` — two new functions

**`handle_complex_task_vscode(user_input, workspace_root, job_id)`**
Background-thread variant of `handle_complex_task()`:
1. Checks `verify_claude_code_installed()` → marks job `failed` if missing
2. Calls `breakdown_into_agents()` → marks job `failed` on API error
3. Calls `register_agents()` in job store
4. Scans project context (mocked in tests)
5. Calls `pool.execute_vscode(job_id)` — no input() anywhere
6. Sets final job status + summary

**`start_vscode_agent_job(user_input, workspace_root) → str`**
- Generates job_id
- Calls `create_job()`
- Fires `handle_complex_task_vscode` in a daemon thread
- Returns job_id immediately (caller can start polling)

---

### `process_for_vscode()` — `__COMPLEX_TASK__` sentinel

```python
# Before calling Claude — question-intent override
_is_question = any(_lower_msg.startswith(q) for q in _QUESTION_STARTS) or _lower_msg.endswith("?")
if not _is_question and is_complex_task(message):
    return "__COMPLEX_TASK__"
```

The sentinel string propagates to `/chat` handler in `server.py`.

---

### `server.py` — 3 changes

**`/chat` handler** — detects sentinel:
```python
if response == "__COMPLEX_TASK__":
    job_id = start_vscode_agent_job(message, workspace_root)
    send_json({"agent_job_id": job_id, "response": None, ...})
    return
```

**`POST /run-agents`** — explicit trigger (for future "Run in background" button):
```json
{ "message": "build the feature", "workspace_root": "/proj" }
→ { "job_id": "job_abc12345", "status": "starting" }
```

**`GET /agents/status?job_id=...`** — polling endpoint:
```json
{
  "job_id": "job_abc12345",
  "status": "running",
  "agents": {
    "a1": { "status": "success", "output": "...", "files_created": [...] },
    "a2": { "status": "running", "started_at": 1234567.8 },
    "a3": { "status": "pending", "depends_on": ["a2"] }
  }
}
```
Returns 404 if job_id unknown.

---

### `jarvisPanel.ts` — agent panel UI

**Polling**: when `/chat` returns `agent_job_id`, start 2-second polling loop:
```typescript
_startAgentPolling(jobId: string)  // polls /agents/status every 2s
                                   // stops when status == "done" | "failed"
```

**Agent panel HTML** — injected below chat messages:
```
Running: "Build login page"

  ✅ component   create Angular login component    12s   [login.component.ts]
  ✅ service     create auth service               18s   [auth.service.ts]
  ⟳ tests       write unit tests                  running…
  ⏸ e2e         integration tests                 waiting for tests
```

Status icons: `⟳` (spin animation) → `✅` → `❌` → `⏭`
File badges: clickable tags for each created/modified file.

---

## Architecture — Polling vs SSE

Used **polling** (2-second interval) instead of SSE:
- Simpler: no `EventSource` setup, no keep-alive
- Works with existing `BaseHTTPRequestHandler` (no streaming changes needed)
- Sufficient for this use case — 2s lag is imperceptible on agent tasks that take 10-120s
- Can upgrade to SSE in a future phase if needed

---

## Tests — 20 passing

| Group | Tests |
|---|---|
| **Group 1: agent_jobs module** | `test_create_job_returns_correct_shape`, `test_create_job_agents_start_pending`, `test_update_job_status_changes_field`, `test_update_job_status_sets_finished_at`, `test_update_agent_status_changes_field`, `test_update_agent_status_sets_started_at_on_running`, `test_get_job_returns_none_for_unknown`, `test_cleanup_old_jobs_removes_finished`, `test_generate_job_id_format` |
| **Group 2: handle_complex_task_vscode** | `test_vscode_handler_marks_failed_when_no_claude_code`, `test_vscode_handler_marks_failed_on_breakdown_error`, `test_vscode_handler_registers_agents` |
| **Group 3: server endpoints** | `test_run_agents_returns_job_id`, `test_run_agents_missing_message_returns_400`, `test_agents_status_returns_job_state`, `test_agents_status_unknown_job_returns_404`, `test_chat_complex_task_returns_agent_job_id` |
| **Group 4: AgentPool.execute_vscode** | `test_execute_vscode_marks_job_running`, `test_execute_vscode_marks_job_done_after_completion`, `test_execute_vscode_skips_dependents_on_failure` |

---

## Files Changed

| File | Change |
|---|---|
| `tools/agent_jobs.py` | **New** — in-memory job store |
| `agents/agent.py` | Added `on_status_change`, `vscode_mode`, `_notify()` |
| `agents/agent_pool.py` | Added `execute_vscode()`, `_run_agent_vscode()` |
| `orchestrator.py` | Added `handle_complex_task_vscode()`, `start_vscode_agent_job()`, `__COMPLEX_TASK__` return in `process_for_vscode()` |
| `server.py` | `/run-agents`, `/agents/status`, sentinel routing in `/chat`, version=phase12 |
| `vscode-extension/src/jarvisPanel.ts` | `_startAgentPolling()`, agent panel HTML/CSS, `agentJobStarted`/`agentStatusUpdate`/`agentJobDone` handlers |
| `tests/test_phase12.py` | **New** — 20 tests |

---

## Pre-Phase-13 Fixes (applied after Phase 12)

### Fix 1 — Template list clarity

**Problem:** `/template list` showed `angular-auth-guard [global] 4 agents — description` on one line, making users think the full string was the name. Typing `/template info angular-auth-guard [global] 4 agents` returned "not found".

**Fix:** Reformatted `format_template_list()`. Name is now on its own line; `[global/project] · N agents` and description are indented below it. Full command reference shown in footer.

```
Templates (4):

  angular-auth-guard
    [global] · 4 agents
    Auth guard, interceptor, and login page for Angular route protection

  dotnet-endpoint
    [global] · 4 agents
    ...

Commands:
  /template use <name>
  /template rename <old-name> <new-name>
  /template edit <name> description <text>
  /template edit <name> triggers <p1>, <p2>
  ...
```

**Template scopes:**
- `[global]` — available in all projects. The 4 built-ins are global. Created by `/template save` from the global session (no workspace open).
- `[project]` — only visible inside the specific project where it was saved. Created by `/template save` from VS Code when a project folder is open. Stored in `templates/projects/<workspace-hash>/`.

### Fix 2 — Rename and edit commands

New commands in `handle_template_command()`:

```
/template rename <old-name> <new-name>          — rename (also: "old to new")
/template edit <name> description <text>        — update description
/template edit <name> triggers <p1>, <p2>       — update trigger phrases
```

New functions in `tools/templates.py`:
- `rename_template(old_name, new_name, workspace_root)` — creates new file, deletes old
- `update_template_meta(name, workspace_root, **fields)` — updates `description` or `trigger_phrases`

### Fix 3 — Trigger auto-detection wired up + improved matching

`find_by_trigger()` was built in Phase 11 but never connected to the chat flow.

**Now wired in** both `process_for_vscode()` and `process()`: before the complex-task check, if the message matches a template trigger, Jarvis responds instantly:
```
This looks like the angular-auth-guard template (4 agents — Auth guard...).

Run it:       /template use angular-auth-guard
With context: /template use angular-auth-guard for <feature-name>

Or just keep typing and I'll break down the task manually.
```

**Improved matching** — two passes:
1. Exact substring match (original behavior)
2. Keyword match: extract non-stopword words from trigger phrase, require ≥ 60% to appear in the message. Makes "create guard for angular routes" match "add auth guard" without false positives from single-word hits.

**14 new tests** added to `tests/test_templates.py` (34 total). Full suite: **229/229 passing**.
