# Phase 9 — Agent Memory & Handoff
**Status:** ✅ Complete
**Date:** February 2026
**Tests:** 154/154 passing (18 + 18 + 14 + 12 + 24 + 17 + 14 + 22 + 15)

---

## What We Built

A shared scratchpad system (`.jarvis-handoff.json`) that lets agents communicate
what they actually built, so dependent agents can pick up exactly where the
previous one left off — without guessing.

Before Phase 9: Agent 2 had no idea what Agent 1 created, what naming conventions
it used, or where it put things. Every agent started blind.

After Phase 9: Agent 2 reads a structured summary of Agent 1's work before running:
```
Context from completed dependency agents:
agent_1 already completed:
  Created:  src/app/auth/auth.service.ts
  Modified: src/app/app.module.ts
  Exports:  AuthService
  Notes:    Used standalone component pattern. Injectable at root.
```

---

## Project Structure (new/changed files)

```
jarvis/
├── tools/
│   └── handoff.py            # New — all handoff read/write/context/cleanup
├── agents/
│   └── agent.py              # +extract_handoff_data after success
│                             # +build_handoff_context injected in agent prompt
├── orchestrator.py           # +cleanup_handoff after full task completes
├── tests/
│   └── test_phase9.py        # 15 new tests
└── docs/
    └── phase9_plan.md        # This file
```

---

## The Handoff Scratchpad

### File: `.jarvis-handoff.json`

Created in the agent's `working_dir` at the start of a complex task.
Each agent writes its entry after completing successfully.
Deleted by `orchestrator.py` after the full task finishes.

```json
{
  "agent_1": {
    "files_created": ["src/app/auth/auth.service.ts"],
    "files_modified": ["src/app/app.module.ts"],
    "exports": ["AuthService"],
    "notes": "Used standalone component pattern. Injectable at root."
  },
  "agent_2": {
    "files_created": ["src/app/auth/auth.guard.ts"],
    "files_modified": [],
    "exports": ["AuthGuard"],
    "notes": "Injects AuthService. Returns Observable<boolean>."
  }
}
```

---

## `tools/handoff.py` — 5 Functions

### `read_handoff(working_dir) -> dict`
Reads `.jarvis-handoff.json` from the working directory.
Returns `{}` if the file doesn't exist or is corrupt — never raises.

### `write_handoff(agent_id, data, working_dir) -> None`
Merges `{agent_id: data}` into the existing scratchpad.
Creates the file if it doesn't exist. Subsequent writes for the same
`agent_id` overwrite the previous entry.

### `build_handoff_context(depends_on_ids, working_dir) -> str`
Reads the scratchpad and builds a human-readable context string from all
dependency agents' entries. Returns `""` if none of the dependencies are
present in the scratchpad yet — safe to call with partial results.

### `extract_handoff_data(output, task) -> dict`
Uses Haiku (`claude-haiku-4-5-20251001`, `max_tokens=300`) to extract
structured metadata from an agent's raw output:
```json
{"files_created": [], "files_modified": [], "exports": [], "notes": ""}
```
Returns `{}` on any failure — always best-effort, never raises.
Strips accidental markdown code fences from the response.

### `cleanup_handoff(working_dir) -> None`
Removes `.jarvis-handoff.json` after the full task completes.
No-op (no error) if the file was already deleted.

---

## How It Plugs Into `agent.py`

**Before an agent runs** (after its dependencies complete):
```python
# Build context from completed dependency agents
handoff_ctx = build_handoff_context(self.depends_on, self.working_dir)
if handoff_ctx:
    prompt = handoff_ctx + "\n\n" + prompt
```

**After an agent succeeds**:
```python
# Extract and write handoff data for downstream agents
handoff_data = extract_handoff_data(result_output, self.task)
if handoff_data:
    write_handoff(self.id, handoff_data, self.working_dir)
```

---

## How It Plugs Into `orchestrator.py`

After the full agent pool completes, the scratchpad is cleaned up:
```python
# Cleanup handoff scratchpad after all agents finish
if working_dir:
    cleanup_handoff(working_dir)
```

---

## Key Design Decisions

| Decision | Reason |
|---|---|
| File-based scratchpad (not in-memory) | Survives agent crashes; agents in separate threads/processes can all access it |
| Per-directory (in `working_dir`) | Multiple parallel tasks in different directories don't cross-contaminate |
| Haiku for extraction | Cheap (max_tokens=300) — extraction happens per agent after success |
| Best-effort extraction | If Haiku fails, agent still succeeds — degraded context is better than failing the task |
| Cleanup after full task | Keeps project directories clean; doesn't leave stale JSON from old runs |
| Context injected at prompt level | Agent prompt gets the context inline — no changes to the Claude API call structure |

---

## Test Coverage (15 new tests)

| Class | Tests |
|---|---|
| TestReadWriteHandoff | read_returns_empty_when_no_file, write_creates_file, write_merges_multiple_agents, write_overwrites_same_agent, read_handles_corrupted_file |
| TestBuildHandoffContext | returns_empty_when_no_depends_on, returns_empty_when_working_dir_empty, returns_empty_when_agent_not_in_handoff, builds_context_with_files, builds_context_for_multiple_dependencies, partial_dependencies_resolved |
| TestCleanupHandoff | removes_handoff_file, no_crash_when_file_missing |
| TestExtractHandoffData | returns_empty_dict_on_api_failure, returns_dict_with_expected_keys |
