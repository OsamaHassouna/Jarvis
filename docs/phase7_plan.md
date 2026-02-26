# Phase 7 — File Upload, Vision & Extensions
**Status:** ✅ Complete
**Date:** February 2026
**Tests:** 117/117 passing (18 + 18 + 14 + 12 + 24 + 17 + 14)

---

## What We Built

Four capabilities that make Jarvis more useful in real coding sessions:
file and image upload in both VS Code and terminal, cross-machine memory
sync via GitHub Gist, pause/resume control for multi-agent runs, and a
one-click "Apply to file" button for code suggestions in VS Code.

---

## Project Structure (new files)

```
jarvis/
├── tools/
│   └── sync.py                   # NEW — push_memory() / pull_memory() via GitHub Gist
├── config.py                     # Updated — GITHUB_TOKEN, GIST_ID (defaults to "")
├── memory.py                     # Updated — auto-sync on load/save
├── orchestrator.py               # Updated — attachment params + Vision API in process_for_vscode()
├── server.py                     # Updated — 4 new attachment fields in POST /chat, version="phase7"
├── main.py                       # Updated — attach <path> command in terminal loop
├── agents/
│   └── agent_pool.py             # Updated — Ctrl+C pause menu in execute()
├── vscode-extension/src/
│   └── jarvisPanel.ts            # Updated — attach button, image support, apply-code button
├── tests/
│   └── test_phase7.py            # 14 new tests
└── docs/
    └── phase7_plan.md            # This file
```

---

## Feature 1 — File & Image Upload (VS Code)

### How to use
1. Click the **+** button in the Jarvis panel (left of the text input)
2. Pick any file — text files (`.py`, `.ts`, `.cs`, etc.) or images (`.png`, `.jpg`, etc.)
3. A chip appears showing the filename — type your question and send

### What happens
- **Text file** → content injected into the message (up to 3 000 chars), sent as context
- **Image** → sent to Claude's Vision API as a multimodal message — Jarvis describes, explains, or reviews the image

### jarvisPanel.ts changes (webview side)
```html
<!-- New elements -->
<input type="file" id="file-input" style="display:none" accept="*">
<button id="attach-btn">+</button>
<div id="attachment-bar" style="display:none">
  <span id="attachment-chip"></span>
  <button id="clear-attach">x</button>
</div>
```

JS state: `let pendingAttachment = null` — set on file selection, cleared after send.

- Text files: `FileReader.readAsText()` → `{ name, isImage: false, contentText }`
- Images: `FileReader.readAsDataURL()` → strip `data:mime;base64,` prefix → `{ name, isImage: true, base64, mimeType }`

### TypeScript (extension host) changes
`_handleSend()` now includes 4 new fields in the POST body:
```typescript
attachment_name: attachment?.name ?? '',
attachment_text: (!attachment?.isImage ? attachment?.contentText : '') ?? '',
attachment_image_base64: (attachment?.isImage ? attachment?.base64 : '') ?? '',
attachment_image_type: (attachment?.isImage ? attachment?.mimeType : '') ?? '',
```

---

## Feature 2 — File Attachment in Terminal (`main.py`)

```
You: attach D:\projects\auth.service.ts
  Attached: auth.service.ts (1842 chars). Now ask your question.

You: what's the issue with the token refresh logic?
Jarvis: [answers with full file context]
```

Implementation — two state variables before the loop:
```python
_attached_content = ""
_attached_name = ""
```

`attach <path>` detected before normal processing:
```python
if user_input.lower().startswith("attach "):
    path = user_input[7:].strip().strip('"').strip("'")
    if os.path.exists(path):
        _attached_content = open(path, encoding="utf-8", errors="replace").read()
        _attached_name = os.path.basename(path)
```

Injected into next message, then cleared:
```python
if _attached_content:
    user_input = f"{user_input}\n\n[Attached file: {_attached_name}]\n```\n{_attached_content[:3000]}\n```"
    _attached_content = _attached_name = ""
```

---

## Feature 3 — Vision API in orchestrator.py

`process_for_vscode()` signature updated:
```python
def process_for_vscode(message, file_path="", file_content="", selection="",
                        attachment_text="", attachment_name="",
                        attachment_image_base64="", attachment_image_type=""):
```

Message building logic:
```python
if attachment_image_base64:
    user_content = [
        {"type": "text", "text": augmented},
        {"type": "image", "source": {
            "type": "base64",
            "media_type": attachment_image_type or "image/png",
            "data": attachment_image_base64
        }}
    ]
else:
    user_content = augmented   # plain string — unchanged behaviour
```

Claude's Vision API handles the rest — no extra libraries needed.

---

## Feature 4 — Apply Code to Active File (VS Code)

After Jarvis replies, if the response contains a code block, an **"Apply to active file"** button appears below the message.

```
Jarvis: Here's the fixed service:

        ```typescript
        export class AuthService { ... }
        ```

        [ Apply to active file ]
```

Clicking it replaces the entire content of the currently open file with the extracted code.

### Implementation
Webview JS — detect code block in response, render button:
```js
const codeMatch = text.match(/```[\w]*\n([\s\S]+?)\n```/);
if (codeMatch) {
    applyBtn.onclick = () => vscode.postMessage({ command: 'applyCode', code: codeMatch[1] });
}
```

Extension host — apply code handler:
```typescript
} else if (msg.command === 'applyCode') {
    const editor = vscode.window.activeTextEditor;
    if (!editor) { vscode.window.showWarningMessage('No active file.'); return; }
    await editor.edit(eb => {
        eb.replace(new vscode.Range(0, 0, editor.document.lineCount, 0), msg.code);
    });
    vscode.window.showInformationMessage('Jarvis applied code to file.');
}
```

---

## Feature 5 — Pause/Resume Agents (agent_pool.py)

Press **Ctrl+C** during a multi-agent run to pause after the current batch finishes:

```
^C

Paused — waiting for running agents to finish...

Paused. What would you like to do?
  1. Continue with remaining agents
  2. Skip remaining agents (keep completed work)
  3. Cancel everything
  Choice (1/2/3):
```

Implementation — wraps `t.join()` calls in `execute()`:
```python
try:
    for t in threads:
        t.join()
except KeyboardInterrupt:
    print("\nPaused — waiting for running agents to finish...")
    for t in threads:
        t.join()   # let current batch finish cleanly
    # show menu, handle choice 1/2/3
```

Running agents always finish cleanly before the menu appears — no partial work lost.

---

## Feature 6 — Cross-Machine Sync (`tools/sync.py`)

Sync `memory.json` to a private GitHub Gist so Jarvis knows you on any machine.

### Setup (one time)
1. Go to `https://github.com/settings/tokens` → "Generate new token (classic)"
2. Scope: check **gist** only
3. Copy the token → set `GITHUB_TOKEN` env var (or paste into `config.py`)
4. Create a new **private** Gist at `https://gist.github.com` — filename: `memory.json`
5. Copy the Gist ID from the URL → set `GIST_ID` env var (or paste into `config.py`)
6. Done — sync is automatic from now on

### How it works

| Function | Behaviour |
|---|---|
| `push_memory(path, token, gist_id)` | PATCH to GitHub Gist API — uploads memory.json content. Returns `(True, msg)`. |
| `pull_memory(path, token, gist_id)` | GET from Gist API — writes content to local path. Returns `(True, msg)`. |
| Both functions | Return `(False, reason)` immediately if token or gist_id is empty. |

Uses only `urllib.request` (stdlib) — **no new pip dependencies**.

### Auto-sync wiring in memory.py
```python
_synced_this_session: bool = False   # module-level flag

def load_memory():
    global _synced_this_session
    if GITHUB_TOKEN and GIST_ID and not _synced_this_session:
        pull_memory(MEMORY_FILE, GITHUB_TOKEN, GIST_ID)   # pull once on first load
        _synced_this_session = True
    ...

def save_memory(data):
    ...
    if GITHUB_TOKEN and GIST_ID:
        push_memory(MEMORY_FILE, GITHUB_TOKEN, GIST_ID)   # push silently on every save
```

The `_synced_this_session` flag prevents re-pulling from Gist on every `load_memory()` call
(which happens dozens of times per session).

---

## Key Decisions

| Decision | Reason |
|---|---|
| stdlib `urllib.request` for Gist API | Zero new dependencies — no `requests` install required |
| `_synced_this_session` flag | Prevents network call on every memory access — only pull once at session start |
| 3 000 char text attachment limit | Keeps token cost reasonable; covers most real files |
| Default media_type `image/png` | Safe fallback when extension sends empty string |
| Pause at batch boundary, not mid-agent | Running agents always finish cleanly — no corrupted partial work |
| Apply-code replaces entire file | Simple and predictable; matches what "apply this fix" means in practice |
| Token/gist_id default to `""` (not `None`) | Avoids `if token is not None` checks — falsy empty string is enough |

---

## Test Coverage (14 new tests)

| Class | Tests |
|---|---|
| TestTextAttachmentProcessing | text_injected_in_message, no_attachment_returns_plain_message, truncated_at_3000_chars |
| TestImageAttachmentProcessing | builds_multimodal_content, no_image_sends_string_content, defaults_media_type_to_png |
| TestSyncTools | push_skips_when_no_token, pull_skips_when_no_token, push_calls_github_api, pull_writes_content_from_gist |
| TestAgentPoolPause | skip_remaining_marks_pending_as_skipped |
| TestServerVersion | status_returns_phase7 |
| TestTerminalAttach | attach_reads_file_content, attach_missing_file_sets_no_content |
