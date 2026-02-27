# Phase 11 — Task Templates / Playbooks ✅ Complete

**Status:** Complete — 20 tests passing (195 total)
**Completed:** February 2026

---

## Goal

Define reusable multi-agent blueprints for patterns that repeat constantly
(Angular features, .NET endpoints, EF migrations, auth guards).
Instead of re-describing the same breakdown every time, run a single command
and Jarvis spawns the pre-defined agents immediately — no AI breakdown step needed.

---

## What Was Built

### `tools/templates.py`
Full CRUD layer for template storage. Mirrors the sessions/ directory pattern:

```
templates/
  global/                          ← available in every project
    new-angular-feature.json
    dotnet-endpoint.json
    angular-auth-guard.json
    dotnet-ef-migration.json
  projects/
    <workspace_hash>/              ← project-scoped templates
      my-custom-template.json
```

Key functions:
- `list_templates(workspace_root)` — global + project templates
- `get_template(name, workspace_root)` — project-scoped first, then global fallback
- `save_template(name, agents, workspace_root, description, trigger_phrases)` — write JSON
- `delete_template(name, workspace_root)` — remove JSON file
- `find_by_trigger(user_input, workspace_root)` — match trigger phrases in free text
- `build_agent_defs_from_template(template, context)` — inject optional context into tasks
- `increment_use_count(name)` — best-effort usage counter
- `format_template_list(templates)` / `format_template_info(template)` — display helpers

### 4 Built-in Global Templates

| Name | Agents | Trigger phrases |
|---|---|---|
| `new-angular-feature` | component → service → routing → tests | "new angular feature", "add angular component" |
| `dotnet-endpoint` | dto → service → controller → tests | "new api endpoint", "new controller action" |
| `angular-auth-guard` | guard → interceptor → login-page → tests | "add auth guard", "protect angular routes" |
| `dotnet-ef-migration` | entity → dbcontext → repository → migration | "new ef entity", "add ef migration" |

### `handle_template_command()` in `orchestrator.py`

Interceptor that runs before any Claude call. Handles:

```
/template list                             → show all templates
/template info <name>                      → show agents + details
/template use <name>                       → run template (terminal) / show plan (VS Code)
/template use <name> for <context>         → inject feature name into every agent task
/template save <name>                      → save last agent breakdown as template
/template delete <name>                    → remove template
```

Wired into both `process()` (terminal) and `process_for_vscode()` (VS Code).

### Terminal execution — `_run_template_in_terminal()`

When `/template use <name>` is typed in terminal mode:
1. Loads pre-defined agent defs from `_last_agent_defs` (set by interceptor)
2. Shows the plan — asks for confirmation
3. Asks for working directory
4. Scans project context
5. Asks about git auto-commit
6. Spawns `AgentPool` directly — **skips the AI breakdown step entirely**
7. Offers git rollback if any agents fail
8. Cleans up handoff file

### `_last_agent_defs` global

Set in two places:
- `handle_complex_task()` — after `breakdown_into_agents()` succeeds (so `/template save` works after any normal task)
- `handle_template_command("/template use ...")` — pre-loads template's agents before terminal execution

---

## Commands Reference

### VS Code chat
```
/template list
/template info new-angular-feature
/template use dotnet-endpoint
/template use new-angular-feature for user-profile-feature
/template save my-breakdown
/template delete my-breakdown
```

### Terminal (`python main.py`)
Same commands. `/template use` actually executes the agents in the terminal.

---

## Data Format

```json
{
  "name": "new-angular-feature",
  "description": "Standalone component, service, route wiring, and unit tests",
  "trigger_phrases": ["new angular feature", "add angular component"],
  "agents": [
    { "id": "component", "task": "Create Angular standalone component...", "depends_on": [] },
    { "id": "service",   "task": "Create Angular service...",              "depends_on": [] },
    { "id": "routing",   "task": "Wire up route...",                       "depends_on": ["component"] },
    { "id": "tests",     "task": "Write unit tests...",                    "depends_on": ["component", "service"] }
  ],
  "use_count": 0,
  "created_at": "2026-02-28T00:00:00+00:00"
}
```

---

## Tests — 20 passing

| Test | What it covers |
|---|---|
| `test_save_and_get_global_template` | Save + retrieve, scope = global |
| `test_get_returns_none_for_missing_template` | Missing name → None |
| `test_list_templates_includes_global` | List returns saved templates |
| `test_list_templates_empty` | Empty state → empty list |
| `test_delete_template` | Delete removes file |
| `test_delete_missing_returns_false` | Delete non-existent → False |
| `test_project_scoped_template` | Project scope, isolation from global |
| `test_increment_use_count` | use_count bumps correctly |
| `test_find_by_trigger_matches` | Trigger phrase found in free text |
| `test_find_by_trigger_no_match` | No trigger → None |
| `test_handle_template_list_empty` | `/template list` with no templates |
| `test_handle_template_list_shows_templates` | `/template list` shows names + agent count |
| `test_handle_template_info` | `/template info` shows agent details |
| `test_handle_template_info_missing` | Info for unknown template → error msg |
| `test_handle_template_use_redirects_in_vscode` | `/template use` returns plan in VS Code |
| `test_handle_template_use_with_context` | "for <ctx>" injected into agent tasks |
| `test_handle_template_save_no_breakdown` | Save with no prior breakdown → helpful error |
| `test_handle_template_delete` | Delete via command, double-delete gives error |
| `test_non_template_command_returns_none` | Non-/template messages → None (pass through) |
| `test_builtin_templates_exist` | All 4 built-ins load correctly from disk |

---

## Files Changed

| File | Change |
|---|---|
| `tools/templates.py` | **New** — full CRUD + trigger matching + formatting |
| `templates/global/new-angular-feature.json` | **New** — built-in template |
| `templates/global/dotnet-endpoint.json` | **New** — built-in template |
| `templates/global/angular-auth-guard.json` | **New** — built-in template |
| `templates/global/dotnet-ef-migration.json` | **New** — built-in template |
| `tests/test_templates.py` | **New** — 20 tests |
| `orchestrator.py` | Added `handle_template_command()`, `_run_template_in_terminal()`, `_last_agent_defs` global, wired into `process()` and `process_for_vscode()` |
