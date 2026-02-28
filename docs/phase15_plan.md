# Phase 15 — Proactive Background Watcher ✅ Complete

**Status:** Complete — 18 tests passing (265 total)
**Completed:** February 2026

---

## Goal

Transform Jarvis from reactive (answers when asked) to proactive (notices things and
surfaces them). A background daemon thread monitors active project directories and posts
dismissible notification banners to the VS Code panel.

---

## What Was Built

### `tools/notifications.py` (new)

Thread-safe in-memory notification store. Populated by `watcher.py`, consumed via
`/notifications` in `server.py`.

```python
add_notification(type_, message, workspace="", severity="info") -> str  # returns id
get_notifications(workspace="") -> list   # empty workspace = all
dismiss_notification(notif_id) -> bool
dismiss_all(workspace="") -> int
```

Notifications dict shape:
```json
{ "id": "notif_abc12345", "type": "stale_test", "message": "...",
  "workspace": "/path/to/project", "severity": "info", "created_at": 1234567890.0 }
```

---

### `tools/watcher.py` (new)

Background daemon thread (`jarvis-watcher`). No external dependencies — uses `os.walk`,
`subprocess` (git), and `threading`.

**Public API:**
```python
register_workspace(workspace_root)   # called on every /chat request
start_watcher()                      # idempotent — safe to call multiple times
run_checks_once(workspace_root)      # used in tests
```

**3 detectors:**

| # | Name | Condition | Severity |
|---|---|---|---|
| 1 | `stale_test` | Source `.ts`/`.cs` modified <48h ago, matching spec file >24h older | `info` |
| 2 | `long_running_branch` | No git commit for 5+ days AND uncommitted changes exist | `warning` |
| 3 | `many_uncommitted` | 8+ uncommitted files, last commit >24h ago | `warning` |

**Constants:**
```python
_CHECK_INTERVAL = 300        # 5-minute cycle
_STALE_TEST_GAP = 86400      # spec must be > 24h older than source
_SOURCE_RECENT = 172800      # source must have been modified within 48h
_LONG_BRANCH_DAYS = 5
_MANY_FILES_COUNT = 8
_MANY_FILES_HOURS = 24
```

**Duplicate prevention:** `_notified_keys` set — keyed by `type:path:mtime` so the same
notification won't fire again in the same session.

**Spec name mapping (`_get_spec_name`):**
- `foo.ts` → `foo.spec.ts` (skips `.spec.ts` and `.d.ts`)
- `FooService.cs` → `FooServiceTests.cs` (skips `Tests.cs` and `Spec.cs`)

**Skipped directories:** `node_modules`, `.git`, `bin`, `obj`, `dist`, `__pycache__`,
`.angular`, `.next`, `coverage`, `out`

---

### `server.py` — 4 changes

1. **`/notifications` GET** — returns `{"notifications": [...]}` filtered by `workspace_root` query param
2. **`/notifications/dismiss` POST** — body `{"id": "notif_xxx"}` to dismiss one, or `{"workspace": "/path"}` to dismiss all for workspace
3. **`start_server()`** — calls `start_watcher()` on startup (try/except — silent if fails)
4. **`/chat` handler** — calls `register_workspace(workspace_root)` on every request so the watcher knows which dirs to monitor

---

### `vscode-extension/src/jarvisPanel.ts` — notification banners

**HTML** (above `#messages`):
```html
<div id="notification-bar"></div>
```

**CSS** — `.notif-banner`, `.notif-info` (blue), `.notif-warning` (orange), `.notif-close`

**JavaScript:**
- `let _currentWorkspaceRoot = ''` — populated from `workspaceInfo` message
- `function _esc(s)` — HTML-escapes notification text
- `_pollNotifications()` — fetches `/notifications?workspace_root=...` every 30s
- `_renderNotifications(notifications)` — builds dismissible banner divs
- Dismiss button calls `POST /notifications/dismiss` with `{id}` then removes the div

**Extension side:** `_postWorkspaceInfo()` now sends `rootPath` alongside display name.
Webview stores it in `_currentWorkspaceRoot` when `workspaceInfo` message is received.

---

## Tests — 18 passing

| Group | Tests |
|---|---|
| **Notifications store** | `test_add_notification_stores_entry`, `test_get_notifications_filters_by_workspace`, `test_get_notifications_empty_workspace_shows_all`, `test_dismiss_notification_removes_by_id`, `test_dismiss_notification_returns_false_for_unknown`, `test_dismiss_all_removes_all`, `test_dismiss_all_scoped_to_workspace` |
| **Watcher detectors** | `test_stale_test_detector_fires_notification`, `test_stale_test_detector_skips_up_to_date`, `test_stale_test_detector_skips_old_source` |
| **Spec name mapping** | `test_get_spec_name_typescript`, `test_get_spec_name_skips_spec_and_declaration`, `test_get_spec_name_csharp`, `test_get_spec_name_skips_test_files`, `test_get_spec_name_unknown_ext` |
| **Misc** | `test_run_checks_once_ignores_missing_dir` |
| **Server endpoints** | `test_notifications_get_endpoint_returns_list`, `test_notifications_dismiss_endpoint` |

---

## Files Changed

| File | Change |
|---|---|
| `tools/notifications.py` | **New** — thread-safe notification store |
| `tools/watcher.py` | **New** — background daemon, 3 detectors, git helpers |
| `server.py` | `/notifications` + `/notifications/dismiss` endpoints; `start_watcher()` on startup; `register_workspace()` per chat request |
| `vscode-extension/src/jarvisPanel.ts` | Notification bar HTML/CSS; `_pollNotifications()` / `_renderNotifications()`; workspace root tracking |
| `tests/test_phase15.py` | **New** — 18 tests |
