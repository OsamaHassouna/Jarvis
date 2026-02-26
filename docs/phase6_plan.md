# Phase 6 — Advanced Agent Capabilities
**Status:** ✅ Complete
**Date:** February 2026
**Tests:** 103/103 passing (18 + 18 + 14 + 12 + 24 + 17)

---

## What We Built

Three new tools that turn agents into autonomous senior developers:
Git integration so agents commit their own work, self-testing so agents
run tests and fix their own failures, and browser preview so frontend
results open automatically when agents finish.

---

## Project Structure (new files)

```
jarvis/
├── tools/
│   ├── git_tools.py              # NEW — is_git_repo(), git_auto_commit()
│   ├── test_runner.py            # NEW — detect_test_command(), run_tests()
│   └── browser.py                # NEW — detect_dev_server_url(), open_browser_preview()
├── agents/
│   └── agent.py                  # Updated — auto_git, auto_test, test_command flags
├── orchestrator.py               # Updated — handle_complex_task() asks git/test/browser Qs
├── tests/
│   └── test_phase6.py            # 17 new tests
└── docs/
    └── phase6_plan.md            # This file
```

---

## How It Works

### 6.1 — Git Integration (`tools/git_tools.py`)

After an agent succeeds, it can auto-commit its own changes:

```
Agent [agent_1] completed task: Create AuthController
  ✅ Files created/modified
  → git add .
  → git commit -m "feat(agent_1): Create AuthController"
  Git: committed successfully
```

| Function | Behaviour |
|---|---|
| `is_git_repo(path)` | Checks for `.git` directory; returns bool. Returns False for invalid paths. |
| `git_auto_commit(working_dir, task)` | Runs `git add .` then `git commit -m "feat(...): {task}"`. Returns `(True, msg)` on success, `(False, msg)` if not a git repo or nothing to commit. |

**Agent opt-in** — only runs when `agent.auto_git = True`. Jarvis asks during `handle_complex_task()`:
```
Auto-commit changes with git? (yes/no):
```

---

### 6.2 — Self-Testing Agents (`tools/test_runner.py`)

After creating code, agents run tests and fix failures automatically:

```
Agent creates component
  → detect_test_command() → "ng test --watch=false"
  → run_tests() → 2 tests failing
  → Agent reads failure output
  → Claude Code: fix the failing tests
  → run_tests() → all passing ✅
```

| Function | Behaviour |
|---|---|
| `detect_test_command(working_dir)` | Inspects project files: `angular.json` → `ng test --watch=false`, `*.csproj` → `dotnet test`, React `package.json` → `npm test`. Returns `None` for unknown projects. |
| `run_tests(working_dir, command, timeout)` | Runs command via `subprocess.run()`. Returns `(True, output)` on exit code 0, `(False, output)` otherwise. |

**Auto-fix loop** in `agents/agent.py` (runs after SUCCESS if `auto_test=True`):
1. Run tests
2. If failing → pass test output to Claude Code with fix instruction
3. Run tests again
4. Report final result (no infinite loop — one fix attempt)

**Agent opt-in** — only runs when `agent.auto_test = True`. Jarvis asks:
```
Auto-run tests after agents complete? (yes/no):
```

---

### 6.3 — Browser Preview (`tools/browser.py`)

For frontend tasks, Jarvis opens a browser tab after all agents succeed:

```
✅ All agents completed
🌐 Opening preview at http://localhost:4200...
```

| Function | Behaviour |
|---|---|
| `detect_dev_server_url(working_dir)` | `angular.json` → `localhost:4200`, React `package.json` → `localhost:3000`, Vue → `localhost:5173`. Returns `None` if not a frontend project. |
| `open_browser_preview(working_dir)` | Calls `detect_dev_server_url()`, then `webbrowser.open(url)`. Returns `(True, url)` or `(False, reason)`. |

Uses Python's built-in `webbrowser` — no new dependencies.

Jarvis offers browser preview at the end of `handle_complex_task()`:
```
Open browser preview? (yes/no):
```

---

## agents/agent.py changes

Three new fields on the `Agent` dataclass:

```python
auto_git: bool = False      # commit after success
auto_test: bool = False     # run tests after success
test_command: str = ""      # override detected command (optional)
```

Post-run hook in `agent.run()` (after SUCCESS):
```python
if self.auto_git and self.working_dir:
    from tools.git_tools import git_auto_commit
    ok, msg = git_auto_commit(self.working_dir, self.task)
    print(f"  Git: {msg}")

if self.auto_test and self.test_command and self.working_dir:
    from tools.test_runner import run_tests
    ok, test_output = run_tests(self.working_dir, self.test_command)
    if not ok:
        # one auto-fix attempt via Claude Code
        fix_task = f"Fix the failing tests.\nTest output:\n{test_output[:2000]}\n\nOriginal task: {self.task}"
        run_claude_code(task=fix_task, working_dir=self.working_dir, ...)
```

---

## orchestrator.py changes

`handle_complex_task()` now asks three questions after task breakdown:

1. **Git auto-commit?** — only if `is_git_repo(working_dir)` returns True
2. **Auto-run tests?** — only if `detect_test_command(working_dir)` returns a command
3. **Browser preview?** — offered after all agents complete, if frontend project detected

Answers are passed into every `Agent` object before `AgentPool.execute()` runs.

---

## Key Decisions

| Decision | Reason |
|---|---|
| Single fix attempt (no retry loop) | Prevents runaway Claude Code calls; one fix is usually enough |
| `detect_test_command` inspects files (not guesses) | Avoids running wrong test framework — checks actual project type |
| Git/test flags default to False | Opt-in only — never auto-commits without asking |
| `webbrowser.open()` (stdlib) | Zero new dependencies; cross-platform |
| Browser preview offered after agents complete | Dev server must be running first (user starts it separately) |

---

## Test Coverage (17 new tests)

| Class | Tests |
|---|---|
| TestIsGitRepo | temp_dir_is_not_git_repo, returns_false_on_invalid_path |
| TestGitAutoCommit | skips_gracefully_when_not_git_repo, returns_tuple, nothing_to_commit_when_clean |
| TestDetectTestCommand | angular_project, dotnet_project, react_project, unknown_project_returns_none |
| TestRunTests | passing_command_returns_true, failing_command_returns_false |
| TestDetectDevServerUrl | angular_json_returns_4200, react_package_json_returns_3000, vue_package_json_returns_5173, unknown_project_returns_none |
| TestOpenBrowserPreview | no_frontend_returns_false, frontend_dir_opens_browser |
