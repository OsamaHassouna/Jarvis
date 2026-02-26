# Phase 8 — Rules Engine
**Status:** ✅ Complete
**Date:** February 2026
**Tests:** 139/139 passing (18 + 18 + 14 + 12 + 24 + 17 + 14 + 22)

---

## What We Built

A two-tier rules system that lets Jarvis always follow your coding standards
and project conventions without you having to repeat them every message.

- **Global rules** — apply to every conversation, every project, terminal + VS Code
- **Project rules** — scoped to one workspace, injected only when that folder is open
- **`.jarvisrules` file** — drop a plain text file in any project root, auto-detected

Plus: bug fix so Jarvis actually knows about its own interface features (attach,
VS Code + button, apply-code) and can tell you how to use them.

---

## Project Structure (new/changed files)

```
jarvis/
├── memory.py         # +6 rule CRUD functions, rules in get_context_summary(), interface features
├── orchestrator.py   # +handle_rules_command(), project rules injected in file context
├── main.py           # /rules intercept before process()
├── tools/
│   └── token_tracker.py  # Compact one-line summary format
├── tests/
│   └── test_phase8.py    # 22 new tests
└── docs/
    └── phase8_plan.md    # This file
```

---

## Global Rules

Rules that apply to every Claude call regardless of which project you're in.

### Commands (terminal and VS Code chat)

```
/rules                          → list all rules
/rules add Always use standalone Angular components
/rules remove 2                 → remove rule number 2
/rules clear                    → remove all global rules
```

### Storage

```json
{
  "user": {
    "rules": [
      "Always use standalone Angular components",
      "Prefer async/await over .subscribe()"
    ]
  }
}
```

### How they reach Claude

`get_context_summary()` in `memory.py` includes a "User-defined rules" section
when the list is non-empty. This is injected as the system prompt on every call —
no extra work needed per message.

---

## Project Rules

Rules scoped to a single project. Only injected when that workspace folder is active.

### Commands

```
/project rules                  → list rules for current workspace
/project rules add Use JWT with refresh tokens in this project
/project rules remove 1         → remove memory rule number 1
/project rules clear            → clear all memory rules for this project
```

In VS Code the workspace folder is detected automatically from the open folder.
In terminal, `workspace_root` is empty so the command shows a guidance message.

### `.jarvisrules` file (no commands needed)

Drop a plain text file in your project root:

```
# .jarvisrules
# Lines starting with # are ignored

AuthController is the main entry point for auth
Always use DTOs — no raw entity objects in controllers
Use kebab-case for Angular filenames
All API errors must return ProblemDetails format
```

Jarvis reads this file automatically on every message when that workspace is open.
You manage it by editing the file directly. The `/project rules` commands manage
a separate in-memory set that can be added/removed without touching the file.

### Storage

Both sources are merged in `get_project_rules(workspace_path)`:
1. `.jarvisrules` file (read-only via commands)
2. `memory["projects"][i]["rules"]` (managed by commands)

Auto-registration: if you run `/project rules add` for a project that isn't in
memory yet, the project entry is created automatically.

### How they reach Claude

`build_message_with_file_context()` now calls `get_project_rules(workspace_root)`
when a workspace is set, and injects them as a `[Project rules — follow these...]`
section in the user message.

---

## orchestrator.py — `handle_rules_command()`

All `/rules` and `/project rules` commands are intercepted **before** hitting Claude:

```python
# In process_for_vscode() — at the top
rules_response = handle_rules_command(message, workspace_root)
if rules_response is not None:
    return rules_response

# In main.py — in the loop, before process()
if user_input.startswith("/rules") or user_input.lower().startswith("/project rules"):
    rules_response = handle_rules_command(user_input)
    if rules_response is not None:
        print(f"\nJarvis: {rules_response}\n")
        continue
```

Benefits: instant (no API call), works offline, no token cost.

---

## Bug fix: Jarvis knew nothing about its own interface

When asked "how do I upload files?", Jarvis would say "you can't upload files"
despite the `+` button and `attach` command existing.

Fix: added an **Interface features** section to `get_context_summary()`:

```
Interface features (tell the user about these when relevant):
- Terminal: type "attach <filepath>" before a question to include a file as context
- VS Code: use the + button (next to the input) to attach files or images
- VS Code: code responses show an "Apply to active file" button
- VS Code: Jarvis automatically sees the active file and workspace folder
- Commands: /rules (global), /project rules (project-specific)
```

---

## Token tracker — compact format

Before:
```
=======================================================
💰 TOKEN USAGE SUMMARY
=======================================================

📋 Simple task: tell me about X
   Model:  Sonnet
   Tokens: 199 in + 149 out = 348 total
   Cost:   $0.002832
...
```

After:
```
  • Sonnet 4.6  ••  348 tokens  ••  $0.00028
  ──  Remaining credits: $2.50
```

Rules:
- One line per task
- Session total only when > 1 task was logged
- Remaining credits line only shown when the API returns a value (never shows "unavailable")

---

## Key Decisions

| Decision | Reason |
|---|---|
| Two-tier rules (global + project) | Global = personal style; project = architecture decisions that only apply here |
| `.jarvisrules` file read-only via commands | Editing a file is more natural for larger rule sets; easy to commit to git |
| Auto-register project on first rule | No separate "register project" step needed |
| Rules injected at different points | Global → system prompt (always there); project → user message (workspace-scoped) |
| Commands intercepted before Claude | Zero token cost, instant response, works offline |
| Interface features in system prompt | Jarvis can answer "how do I upload files?" correctly without hardcoding it in orchestrator |
| Remaining credits hidden when unavailable | "unavailable" is unhelpful noise; silence is better |

---

## Test Coverage (22 new tests)

| Class | Tests |
|---|---|
| TestGlobalRulesCRUD | empty_by_default, add_global_rule, add_multiple, delete_rule, delete_out_of_range |
| TestGlobalRulesInContext | rules_appear_in_context_summary, no_rules_section_when_empty |
| TestProjectRulesCRUD | add_auto_registers, add_existing_project, delete_rule, reads_jarvisrules_file, empty_workspace |
| TestHandleRulesCommand | non_rules_returns_none, list_empty, add_and_list, remove, clear, no_workspace, project_add_and_list, project_clear |
| TestProjectRulesInjection | project_rules_in_file_context, no_rules_without_workspace |
