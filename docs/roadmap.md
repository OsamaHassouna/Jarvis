# Jarvis — Full Roadmap & Vision
**Last Updated:** February 2026
**Current Status:** Phase 15 Complete ✅ | 265/265 tests passing

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

## Phase 9 — Agent Memory & Handoff ✅ Complete

**Goal:** Make multi-agent tasks coherent. Agents share a `.jarvis-handoff.json`
scratchpad so each agent knows exactly what the previous one built.

### What was built:
- `tools/handoff.py` — `read_handoff()`, `write_handoff()`, `build_handoff_context()`, `extract_handoff_data()`, `cleanup_handoff()`
- After each agent succeeds: Haiku (`max_tokens=300`) extracts `{files_created, files_modified, exports, notes}` from the agent output
- Dependent agents get that context injected into their prompt before running
- `orchestrator.py` cleans up `.jarvis-handoff.json` after the full task completes
- **15 tests** — all passing

**See:** [phase9_plan.md](phase9_plan.md)

---

## Phase 10 — Session Persistence + Server Crash Fix ✅ Complete

**Goal:** VS Code chat survives panel close/reopen. Each project gets its own
session history, with a drawer to switch between sessions.

### What was built:
- `tools/sessions.py` — full session CRUD, active session tracking, project cumulative summary
- `JarvisHTTPServer` — `daemon_threads=True` + `allow_reuse_address=True` fixes port 3131 hold after Ctrl+C
- 5 new server endpoints: `/sessions/new`, `/sessions/list`, `/sessions/active`, `/sessions/load`, `/sessions/close`
- `build_vscode_system_prompt()` replaces `get_context_summary()` for VS Code: injects project summary (1 paragraph) instead of full history
- Auto-naming: quick name after first exchange, Haiku title after third
- Session history drawer in VS Code: grouped by project, active session highlighted, click to switch
- **21 tests** — all passing

**See:** [phase10_plan.md](phase10_plan.md)

---

## Phase 11 — Task Templates / Playbooks ✅ Complete

**Goal:** Reusable multi-agent blueprints for patterns that repeat (Angular features, .NET endpoints, EF migrations, auth guards). Skip the AI breakdown — run the template directly.

### What was built:
- `tools/templates.py` — CRUD + trigger phrase matching + formatting helpers
- 4 built-in global templates: `new-angular-feature`, `dotnet-endpoint`, `angular-auth-guard`, `dotnet-ef-migration`
- `handle_template_command()` interceptor in `orchestrator.py` — handles all `/template` subcommands
- `_run_template_in_terminal()` — executes agents directly from template (no AI breakdown step)
- `_last_agent_defs` global — captures every agent breakdown so `/template save` works
- Storage: `templates/global/` + `templates/projects/<hash>/` (mirrors sessions layout)
- **20 tests** — all passing

Commands:
```
/template list
/template info <name>
/template use <name>
/template use <name> for <context>
/template save <name>
/template delete <name>
```

**Post-Phase-12 improvements to templates:**
- `format_template_list()` reformatted — name on its own line, `[global/project]` indented below; scope clarified (`[global]` = all projects, `[project]` = this workspace only)
- `/template rename <old> <new>` — rename any template (also accepts `old to new` phrasing)
- `/template edit <name> description <text>` and `/template edit <name> triggers <p1>, <p2>`
- `find_by_trigger()` wired into both VS Code and terminal chat flows; two-pass matching (exact → keyword ≥60%)
- **14 additional tests** — 34 total in `test_templates.py`

**See:** [phase11_plan.md](phase11_plan.md) · fixes documented in [phase12_plan.md](phase12_plan.md#pre-phase-13-fixes)

---

## Phase 12 — Full VS Code Parity ✅ Complete

**Goal:** VS Code panel becomes a first-class interface equal to the terminal. No more "open a terminal to do complex tasks."

### What was built:

- `tools/agent_jobs.py` — in-memory job store (job_id → state), no disk I/O, thread-safe
- `agents/agent.py` — `on_status_change` callback + `vscode_mode` flag (skips `input()` prompts)
- `agents/agent_pool.py` — `execute_vscode(job_id)` — background-safe parallel execution with job store updates
- `orchestrator.py` — `handle_complex_task_vscode()` + `start_vscode_agent_job()` — daemon thread, no `input()` calls
- `server.py` — `/run-agents` POST, `/agents/status` GET, `__COMPLEX_TASK__` sentinel routing in `/chat`
- `jarvisPanel.ts` — polling (2s interval), live agent panel UI with status icons + file badges
- `__COMPLEX_TASK__` sentinel — returned by `process_for_vscode()` for complex tasks; server routes to agent job
- **20 tests** — all passing

Agent panel shows live status:
```
  ✅ component   create login component     12s
  ✅ service     create auth service        18s
  ⟳ tests       write unit tests           running…
  ⏸ e2e         integration tests          waiting for tests
```

**See:** [phase12_plan.md](phase12_plan.md)

---

## Phase 13 — Learning from Outcomes ✅ Complete

**Goal:** Jarvis learns which agent breakdowns work well and which don't.

### What was built:
- `tools/ratings.py` — `save_rating()`, `get_relevant_ratings()` (keyword Jaccard match), `format_ratings_for_injection()`, `format_ratings_list()`
- Ratings stored in `memory["task_ratings"]` — capped at 50, per-task summary + agent count + score + date
- Relevant past ratings injected into `breakdown_into_agents()` prompt automatically
- Terminal: rating prompt after every `handle_complex_task()` (Enter to skip)
- VS Code: `_pending_rating` global + `rate_prompt` field in `/agents/status`; dimmed hint shown below agent panel
- `/rate 1-5` — save rating for last task; `/ratings` — view history; `/ratings clear` — reset
- **18 tests** — all passing

**See:** [phase13_plan.md](phase13_plan.md)

---

## Phase 14 — Multi-Project Orchestration
**Priority: LOW — nice for large monorepo setups**
**Goal:** Agents can work across multiple repos simultaneously, with cross-project dependency
awareness.

### Use case:
"Update the shared auth library, then update the Angular app and .NET API that consume it"
Currently this requires 3 separate Jarvis runs. Phase 14 would make it one task.

### What to build:
- `working_dirs: list[str]` on Agent (instead of single `working_dir`)
- Agent pool assigns agents to correct directories based on task
- Cross-repo dependency graph: Angular agent waits for library agent to publish

**Estimated tests:** 8-10
**Effort:** 2-3 sessions
**Risk:** Complex. The single-working-dir model is simple and reliable. Multi-dir adds failure
modes. Recommend implementing after Phase 12 (VS Code parity) gives better visibility.

---

## Phase 15 — Proactive Assistant (Background Watcher) ✅ Complete

**Goal:** Transform Jarvis from reactive (answers when asked) to proactive (notices things and surfaces them).

### What was built:
- `tools/notifications.py` — thread-safe in-memory notification store (`add_notification`, `get_notifications`, `dismiss_notification`, `dismiss_all`)
- `tools/watcher.py` — background daemon thread; 3 detectors (stale tests, long-running branch, many uncommitted); no external deps; `_notified_keys` prevents duplicates
- `server.py` — `/notifications` GET + `/notifications/dismiss` POST; `start_watcher()` on startup; `register_workspace()` per chat request
- `jarvisPanel.ts` — dismissible notification banners above chat; polls `/notifications` every 30s; blue for info, orange for warning
- **18 tests** — all passing

**See:** [phase15_plan.md](phase15_plan.md)

---

## My Recommended Priority Order

Given your stack (Angular + .NET, VS Code user) and current state:

| Priority | Item | Why | Effort |
|---|---|---|---|
| 1 | ~~**Phase 11** (templates)~~ | ✅ Done | — |
| 2 | ~~**Phase 12** (VS Code parity)~~ | ✅ Done | — |
| 3 | ~~**Phase 13** (learning)~~ | ✅ Done | — |
| 4 | ~~**Phase 15** (proactive watcher)~~ | ✅ Done | — |
| 5 | **Phase 14** (multi-project) | Only needed for large multi-repo work | 2-3 sessions |

---

## Architecture (Phase 10 Complete)

```
You (terminal, VS Code, any machine)
 │
 └── Jarvis Orchestrator
      ├── Memory Layer
      │    ├── User profile, name, preferences
      │    ├── Top 3 recently active projects (pruned for context efficiency)
      │    ├── Global + project rules
      │    └── GitHub Gist sync (cross-machine)
      │
      ├── Intelligence Layer
      │    ├── AI complexity detection (Sonnet, max_tokens=20)
      │    ├── Model selection (Sonnet/Opus)
      │    ├── Task breakdown → agent definitions
      │    ├── Workspace file tree injection (scan_workspace_files)
      │    ├── Auto-read mentioned files (read_mentioned_files)
      │    └── Preference detection (remember: ...)
      │
      ├── Agent Pool
      │    ├── Dependency graph
      │    ├── Parallel execution (threading)
      │    ├── Live streaming output
      │    ├── Pause/resume (Ctrl+C menu)
      │    ├── Git auto-commit per agent
      │    ├── Git checkpoint + rollback offer on failure
      │    ├── Self-testing + auto-fix
      │    ├── Per-agent token cost printed inline
      │    ├── Handoff scratchpad (.jarvis-handoff.json) — Phase 9
      │    └── Token tracking
      │
      └── Tools
           ├── Claude Code CLI (file creation/editing)
           ├── Git (auto-commit, rollback checkpoint)
           ├── Test Runner (detect + run + report)
           ├── Browser preview (detect dev server)
           ├── Sync (GitHub Gist push/pull)
           ├── Project Scanner (package.json / .csproj)
           ├── Token Tracker (compact per-call display)
           ├── Session Store (sessions/ directory) — Phase 10
           └── VS Code (file context, vision API, apply-code button,
                        session history drawer, session restore)
```

---

## Test Count

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
| Phase 9 | 15 | ✅ All passing |
| Phase 10 | 21 | ✅ All passing |
| Phase 11 | 34 | ✅ All passing (20 original + 14 post-P12 fixes) |
| Phase 12 | 20 | ✅ All passing |
| Phase 13 | 18 | ✅ All passing |
| Phase 15 | 18 | ✅ All passing |
| Phase 16 | 15 | ✅ All passing |
| **Total** | **290 passing** | |

---

## Phase docs
[phase1](phase1_plan.md) · [phase2](phase2_plan.md) · [phase3](phase3_plan.md) · [phase4](phase4_plan.md) · [phase5](phase5_plan.md) · [phase6](phase6_plan.md) · [phase7](phase7_plan.md) · [phase8](phase8_plan.md) · [phase9](phase9_plan.md) · [phase10](phase10_plan.md) · [phase11](phase11_plan.md) · [phase12](phase12_plan.md) · [phase13](phase13_plan.md) · [phase15](phase15_plan.md)

## How to continue in a new session
Start with: `docs/roadmap.md` + the relevant phase doc + specific files.
Say: **"Continue building Jarvis — see roadmap for current state and next priorities"**

**Starting Phase 16–20:** See [phases16-20_plan.md](phases16-20_plan.md) for the full plan.
Say: **"Continue building Jarvis — see phases16-20_plan.md for what's next"**
