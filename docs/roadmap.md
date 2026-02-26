# Jarvis — Full Roadmap & Vision
**Last Updated:** February 2026
**Current Status:** Phase 8 Complete ✅ | 2 active bugs

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

## Known Bugs (fix before next phase)

### Bug 1 — VS Code toolbar not rendering
**Symptom:** New 3-button toolbar (paperclip / commands / send arrow) not visible after redesign.
**Root cause:** Extension Development Host caches the old compiled JS in memory. The new
`out/jarvisPanel.js` is correctly compiled (16:24 timestamp, 23kb, all new CSS classes present),
but the running host window hasn't loaded it yet.
**Fix:** In the Extension Development Host window → `Ctrl+Shift+P` → `Developer: Reload Window`,
then close and reopen the Jarvis panel (`Ctrl+Shift+J`).
**If still broken:** Check if CSP is blocking anything in DevTools (`F12` in the webview).

### Bug 2 — Workspace root not reaching Jarvis
**Symptom:** Jarvis receives no file tree / says it can't see the workspace.
**Root cause (suspected):** `vscode.workspace.workspaceFolders?.[0]?.uri.fsPath` returns empty
when no folder is explicitly opened in VS Code (just a file, not a folder). The value is correctly
sent in the POST body and received by `server.py` → `orchestrator.py`, but if the extension sends
`""`, the `scan_workspace_files()` call is skipped.
**Fix needed:**
- Add a debug `/status` log in `server.py` that echoes what `workspace_root` it received
- Add a visible indicator in the VS Code panel showing which workspace is active (e.g., folder name
  next to the status dot)
- Fallback: if `workspaceFolders` is empty, try `vscode.window.activeTextEditor?.document.uri`
  and walk up to find the workspace root

**Files:** `vscode-extension/src/jarvisPanel.ts`, `server.py`

---

## Improvements to Existing System
*These are fixes/upgrades to what's already built — no new phases needed.*

### Improvement 1 — Agent structured output parsing
**Problem:** Agents are one-shot black boxes. Jarvis only knows "succeeded" or "failed" — it
can't see what files were created/modified, so Agent 2 can't know what Agent 1 actually built.
**Fix:** After each agent succeeds, make a lightweight Claude call to extract:
```json
{ "files_created": ["auth.service.ts"], "files_modified": ["app.module.ts"], "summary": "..." }
```
Store this in a `.jarvis-scratchpad.json` in the working directory. Dependent agents read it before
running. This partially solves the agent communication problem without a full Phase 9 rebuild.
**Effort:** ~1 session | **Impact:** High — every multi-agent task gets smarter

### Improvement 2 — Memory pruning
**Problem:** `get_context_summary()` injects all projects into the system prompt. After 6 months
of use, this could be 3,000+ tokens of project history on every call — degrading quality and
burning money.
**Fix:**
- Cap projects in context to the 3 most recently active (not all 20+)
- Add `last_accessed` timestamp to each project in memory
- Keep full history in `memory.json` but only inject relevant slice
**Effort:** ~2 hours | **Impact:** High — prevents quality decay over time

### Improvement 3 — Per-agent token display
**Problem:** You only see the total token cost after all agents finish. During a 6-agent run you
have no idea if one agent is burning $0.50 alone.
**Fix:** Print cost inline as each agent completes:
```
[Agent 2/4] login-form  ✅ completed  •  1,240 tokens  •  $0.012
[Agent 3/4] auth-guard  ✅ completed  •  890 tokens    •  $0.009
```
This is a small change to `agent_pool.py` — log token data from the agent's output.
**Effort:** ~1 hour | **Impact:** Medium — better visibility into spend

### Improvement 4 — Git-based rollback
**Problem:** If agents 1-3 succeed and agent 4 breaks the build, there's no easy way to revert.
Git commits happen per-agent but rollback is manual.
**Fix:** Before any complex task begins:
1. Record current `git rev-parse HEAD` as a checkpoint SHA
2. If the full task fails (>50% agents failed), offer: "Revert to checkpoint? (yes/no)"
3. On yes: `git reset --hard <checkpoint_sha>`
**Effort:** ~2 hours | **Impact:** High — safety net for risky multi-agent runs

---

## Phase 9 — Agent Memory & Handoff
**Priority: HIGH — do this next**
**Goal:** Make multi-agent tasks coherent. Right now agents share only the filesystem. Agent 2
has no idea what Agent 1 actually created, where it put things, or what naming conventions it used.

### What to build:
A `.jarvis-handoff.json` scratchpad in the working directory that each agent writes to and reads from:
```json
{
  "agent_1": {
    "task": "Create AuthService",
    "files_created": ["src/app/auth/auth.service.ts"],
    "files_modified": ["src/app/app.module.ts"],
    "exports": ["AuthService"],
    "notes": "Used standalone component pattern. Injectable at root."
  }
}
```

Agent 2's prompt gets injected with Agent 1's entry before it runs:
```
Agent 1 completed:
  Created: src/app/auth/auth.service.ts (exports: AuthService)
  Modified: src/app/app.module.ts
  Note: Used standalone component pattern
```

### Implementation plan:
- `tools/handoff.py` — `write_handoff(agent_id, result)`, `read_handoff(depends_on_ids)`
- `agent.py` — after success, write handoff. Before run, read handoff for all `depends_on` agents
- `orchestrator.py` — pass `working_dir` as handoff location, clean up `.jarvis-handoff.json` after task
- Small Claude call post-agent to extract structured result (ties into Improvement 1)

**Estimated tests:** 8-10
**Effort:** 1-2 sessions
**Impact:** Every multi-agent complex task becomes dramatically more coherent

---

## Phase 10 — Proactive Assistant (Background Watcher)
**Priority: MEDIUM — after Phase 9 and VS Code bug fixes**
**Goal:** Transform Jarvis from reactive (answers when asked) to proactive (notices things and surfaces them).

### What to build:
A background watcher process (`watcher.py`) that monitors active project directories and
posts notifications to the VS Code panel or terminal:

**Pattern detection examples:**
- Build failures: "You've run `dotnet build` 6 times since last commit — want me to look at the error?"
- Stale tests: "auth.service.ts was modified 3 days ago but auth.service.spec.ts hasn't changed"
- Token spend summary: "This week: 12,400 tokens / $0.89 — 60% was on the login refactor"
- Long-running branch: "You've been on feature/auth for 8 days with 14 uncommitted files"

### Implementation plan:
- `watcher.py` — uses `watchdog` library to monitor file changes
- Writes events to a queue file read by `server.py`
- VS Code panel polls `/notifications` endpoint every 30s
- Notifications appear as dismissible banners above the chat

**Estimated tests:** 6-8
**Effort:** 2-3 sessions
**Dependencies:** Requires VS Code panel to be running (`server.py` up)
**Risk:** Can be noisy if detection patterns are too aggressive — needs tuning

---

## Phase 11 — Task Templates / Playbooks
**Priority: HIGH for Osama (Angular + .NET patterns repeat constantly)**
**Goal:** Define reusable agent blueprints for patterns you run frequently, so you don't
re-describe the same breakdown every time.

### What to build:
A `templates/` directory with JSON playbooks:
```json
{
  "name": "new-angular-feature",
  "trigger_phrases": ["new angular feature", "new component", "add feature"],
  "agents": [
    { "id": "component", "task": "Create Angular standalone component with HTML/SCSS template" },
    { "id": "service",   "task": "Create service with HTTP calls", "depends_on": [] },
    { "id": "spec",      "task": "Write unit tests for component and service", "depends_on": ["component", "service"] }
  ]
}
```

Commands:
```
/template list                    → list all saved templates
/template use new-angular-feature → run this template for current project
/template save "name"             → save last agent breakdown as a template
/template edit "name"             → open template JSON for editing
```

**Estimated tests:** 8-10
**Effort:** 1-2 sessions
**Impact:** Massive time saver for Angular/`.NET` patterns you repeat 10x per week

---

## Phase 12 — Full VS Code Parity
**Priority: HIGH — this is where Jarvis needs to go**
**Goal:** VS Code panel becomes a first-class interface equal to the terminal. No more
"open a terminal to do complex tasks."

### What to build:

**12.1 — Agent execution from VS Code**
- POST `/run-complex` endpoint in `server.py`
- VS Code sends task → server spawns agent pool → streams progress back via SSE or WebSocket
- Panel shows live agent status instead of "go to terminal"

**12.2 — Agent progress panel**
```
Running: "Build login page"  ━━━━━━━━━━━━━━━━  3/4 agents

  ✅ agent_1  login-component    12s   890 tokens
  ✅ agent_2  auth-service       18s   1,240 tokens
  ⟳ agent_3  unit-tests         running...
  ⏸ agent_4  integration        waiting for agent_3
```

**12.3 — Approve/skip per agent (VS Code buttons)**
Instead of terminal prompts (`yes/no`), VS Code shows inline buttons:
- [Approve Plan] [Cancel] before task starts
- [Skip this agent] during execution

**12.4 — File change preview**
After agent completes, show diff of what changed — with [Apply] / [Revert] buttons.

**Estimated tests:** 12-15
**Effort:** 3-4 sessions
**Risk:** SSE/WebSocket adds complexity. Could start with polling (simpler) then upgrade.

---

## Phase 13 — Learning from Outcomes
**Priority: MEDIUM — needs Phase 9 data first**
**Goal:** Jarvis learns which task breakdowns work well and which don't, so it improves
its agent planning over time.

### What to build:
After every complex task, prompt for feedback:
```
Task complete (3/4 agents succeeded). How did this go?
  [1 Poor] [2] [3 OK] [4] [5 Great]  or skip
```

Store ratings in memory:
```json
{
  "task_ratings": [
    { "task_pattern": "create angular component", "agents": 3, "rating": 4, "date": "2026-02" },
    { "task_pattern": "add dotnet endpoint", "agents": 4, "rating": 2, "notes": "too many agents" }
  ]
}
```

Inject relevant history into `breakdown_into_agents()`:
```
Past experience: "add dotnet endpoint" — rated 2/5 when using 4 agents (2 failed).
Recommended: use 2 agents instead.
```

**Estimated tests:** 6-8
**Effort:** 1-2 sessions
**Dependencies:** Benefits from Phase 9 structured output to know what actually changed

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

## My Recommended Priority Order

Given your stack (Angular + .NET, VS Code user) and current state:

| Priority | Item | Why | Effort |
|---|---|---|---|
| 1 | **Fix Bug 1** (toolbar) | Blocks VS Code UX | 5 min (reload window) |
| 2 | **Fix Bug 2** (workspace) | Blocks file context feature | ~2 hours |
| 3 | **Improvement 2** (memory pruning) | Prevents quality decay silently | 2 hours |
| 4 | **Improvement 1** (structured output) | Foundation for Phase 9 | 1 session |
| 5 | **Improvement 4** (git rollback) | Safety net before running more agents | 2 hours |
| 6 | **Phase 9** (agent handoff) | Highest ROI — fixes core architecture gap | 1-2 sessions |
| 7 | **Phase 11** (templates) | Daily time saver for Angular/.NET patterns | 1-2 sessions |
| 8 | **Phase 12** (VS Code parity) | Makes VS Code a real interface | 3-4 sessions |
| 9 | **Improvement 3** (per-agent tokens) | Nice UX improvement | 1 hour |
| 10 | **Phase 10** (proactive watcher) | Cool but lower urgency | 2-3 sessions |
| 11 | **Phase 13** (learning) | Needs time + data to be useful | 1-2 sessions |
| 12 | **Phase 14** (multi-project) | Only needed for large multi-repo work | 2-3 sessions |

---

## Architecture (Phase 8 Complete)

```
You (terminal, VS Code, any machine)
 │
 └── Jarvis Orchestrator
      ├── Memory Layer
      │    ├── User profile, name, preferences
      │    ├── All projects + task history (needs pruning — Improvement 2)
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
      │    ├── Self-testing + auto-fix
      │    └── Token tracking
      │
      └── Tools
           ├── Claude Code CLI (file creation/editing)
           ├── Git (auto-commit, rollback checkpoint — planned)
           ├── Test Runner (detect + run + report)
           ├── Browser preview (detect dev server)
           ├── Sync (GitHub Gist push/pull)
           ├── Project Scanner (package.json / .csproj)
           ├── Token Tracker (compact per-call display)
           └── VS Code (file context, vision API, apply-code button)
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
| **Total** | **139 passing** | |

---

## Phase docs
[phase1](phase1_plan.md) · [phase2](phase2_plan.md) · [phase3](phase3_plan.md) · [phase4](phase4_plan.md) · [phase5](phase5_plan.md) · [phase6](phase6_plan.md) · [phase7](phase7_plan.md) · [phase8](phase8_plan.md)

## How to continue in a new session
Start with: `docs/roadmap.md` + the relevant phase doc + specific files.
Say: **"Continue building Jarvis — see roadmap for current bugs and next priorities"**
