"use strict";
// jarvisPanel.ts
// Phase 4/7/8/10 — VS Code Webview panel with Jarvis chat UI.
// Phase 10 adds: per-session persistence, session history drawer, new session button.
Object.defineProperty(exports, "__esModule", { value: true });
exports.JarvisPanel = void 0;
const vscode = require("vscode");
const path = require("path");
const JARVIS_SERVER = 'http://localhost:3131';
class JarvisPanel {
    // ── Static factory ──────────────────────────────────────────────────────
    static createOrShow(extensionUri) {
        // Reuse existing panel if open
        if (JarvisPanel.currentPanel) {
            JarvisPanel.currentPanel._panel.reveal(vscode.ViewColumn.Beside);
            return;
        }
        const panel = vscode.window.createWebviewPanel('jarvis', 'Jarvis', vscode.ViewColumn.Beside, {
            enableScripts: true,
            retainContextWhenHidden: true,
            localResourceRoots: [extensionUri]
        });
        JarvisPanel.currentPanel = new JarvisPanel(panel, extensionUri);
    }
    static prefillInput(text) {
        JarvisPanel.currentPanel?._panel.webview.postMessage({
            command: 'prefill',
            text
        });
    }
    // ── Constructor ──────────────────────────────────────────────────────────
    constructor(panel, _extensionUri) {
        this._disposables = [];
        // Tracks the last real text editor even while the webview has focus
        this._lastKnownEditor = vscode.window.activeTextEditor;
        // Phase 10: session tracking
        this._currentSessionId = '';
        this._currentIsGlobal = false;
        this._sessionRestored = false;
        this._panel = panel;
        this._panel.webview.html = this._getHtml();
        // Keep _lastKnownEditor updated — activeTextEditor becomes undefined when webview gets focus
        vscode.window.onDidChangeActiveTextEditor(editor => {
            if (editor) {
                this._lastKnownEditor = editor;
            }
        }, null, this._disposables);
        // Handle messages from the webview
        this._panel.webview.onDidReceiveMessage(async (msg) => {
            if (msg.command === 'send') {
                await this._handleSend(msg.text, msg.attachment);
            }
            else if (msg.command === 'checkServer') {
                await this._checkServer();
            }
            else if (msg.command === 'applyCode') {
                await this._applyCode(msg.code);
            }
            else if (msg.command === 'runCommand') {
                await this._runCommand(msg.command_str, msg.working_dir, msg.card_id);
            }
            else if (msg.command === 'newSession') {
                await this._newSession(msg.isGlobal ?? false);
            }
            else if (msg.command === 'openSessionDrawer') {
                await this._loadAllSessions();
            }
            else if (msg.command === 'loadSession') {
                await this._loadSession(msg.sessionId, msg.workspaceRoot, msg.isGlobal ?? false);
            }
        }, null, this._disposables);
        // Clean up on close
        this._panel.onDidDispose(() => this.dispose(), null, this._disposables);
    }
    // ── Helpers ──────────────────────────────────────────────────────────────
    _getWorkspaceRoot() {
        const folder = vscode.workspace.workspaceFolders?.[0];
        const editor = this._lastKnownEditor ?? vscode.window.activeTextEditor;
        if (folder) {
            return folder.uri.fsPath;
        }
        if (editor && editor.document.uri.scheme === 'file') {
            return path.dirname(editor.document.uri.fsPath);
        }
        return '';
    }
    // ── Message handling ─────────────────────────────────────────────────────
    async _handleSend(message, attachment) {
        const editor = this._lastKnownEditor ?? vscode.window.activeTextEditor;
        const fileContent = editor?.document.getText() ?? '';
        const filePath = editor?.document.fileName ?? '';
        const selection = editor?.document.getText(editor?.selection ?? new vscode.Selection(0, 0, 0, 0)) ?? '';
        const workspaceRoot = this._getWorkspaceRoot();
        this._postWorkspaceInfo();
        try {
            const res = await fetch(`${JARVIS_SERVER}/chat`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    message,
                    file_path: filePath,
                    file_content: fileContent,
                    selection,
                    workspace_root: workspaceRoot,
                    // Phase 7: attachment fields
                    attachment_name: attachment?.name ?? '',
                    attachment_text: (attachment && !attachment.isImage ? attachment.contentText : '') ?? '',
                    attachment_image_base64: (attachment?.isImage ? attachment.base64 : '') ?? '',
                    attachment_image_type: (attachment?.isImage ? attachment.mimeType : '') ?? '',
                    // Phase 10: session fields
                    session_id: this._currentSessionId,
                    is_global: this._currentIsGlobal,
                })
            });
            if (!res.ok) {
                const err = await res.json();
                this._post('error', `Server error: ${err.error}`);
                return;
            }
            const data = await res.json();
            if (data.session_id) {
                this._currentSessionId = data.session_id;
            }
            const filesWritten = data.files_written ?? [];
            const commandsToRun = data.commands_to_run ?? [];
            this._post('response', data.response, {
                ...(data.tokens ? { tokens: data.tokens } : {}),
                ...(filesWritten.length > 0 ? { filesWritten } : {}),
                ...(commandsToRun.length > 0 ? { commandsToRun } : {}),
                ...(data.session_name !== undefined ? { sessionName: data.session_name } : {}),
            });
        }
        catch {
            this._post('error', 'Could not connect to Jarvis server.\n\n' +
                'Start it with:  python server.py\n' +
                'Then try again.');
        }
    }
    async _checkServer() {
        try {
            const res = await fetch(`${JARVIS_SERVER}/status`);
            const data = await res.json();
            const isOnline = data.status === 'running';
            this._post('serverStatus', isOnline ? 'online' : 'offline');
            if (isOnline && !this._sessionRestored) {
                this._sessionRestored = true;
                await this._restoreActiveSession();
            }
        }
        catch {
            this._post('serverStatus', 'offline');
        }
        this._postWorkspaceInfo();
    }
    _postWorkspaceInfo() {
        const folder = vscode.workspace.workspaceFolders?.[0];
        const editor = this._lastKnownEditor ?? vscode.window.activeTextEditor;
        let name = '';
        if (folder) {
            name = folder.name;
        }
        else if (editor && editor.document.uri.scheme === 'file') {
            name = path.basename(path.dirname(editor.document.uri.fsPath));
        }
        this._post('workspaceInfo', name);
    }
    async _restoreActiveSession() {
        try {
            const workspaceRoot = this._getWorkspaceRoot();
            const res = await fetch(`${JARVIS_SERVER}/sessions/active?workspace_root=${encodeURIComponent(workspaceRoot)}`);
            if (!res.ok) {
                return;
            }
            const data = await res.json();
            if (data.session) {
                this._currentSessionId = data.session['id'];
                this._currentIsGlobal = data.session['is_global'] ?? false;
                this._post('loadSessionMessages', '', { session: data.session });
            }
        }
        catch {
            // best-effort
        }
    }
    async _newSession(isGlobal) {
        const workspaceRoot = this._getWorkspaceRoot();
        try {
            const res = await fetch(`${JARVIS_SERVER}/sessions/new`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ workspace_root: workspaceRoot, is_global: isGlobal }),
            });
            if (!res.ok) {
                return;
            }
            const data = await res.json();
            this._currentSessionId = data.session['id'];
            this._currentIsGlobal = isGlobal;
            this._post('sessionCreated', '', { session: data.session });
        }
        catch {
            // best-effort
        }
    }
    async _loadSession(sessionId, workspaceRoot, isGlobal) {
        try {
            const url = `${JARVIS_SERVER}/sessions/load?session_id=${encodeURIComponent(sessionId)}&workspace_root=${encodeURIComponent(workspaceRoot)}&is_global=${isGlobal ? '1' : '0'}`;
            const res = await fetch(url);
            if (!res.ok) {
                return;
            }
            const data = await res.json();
            this._currentSessionId = sessionId;
            this._currentIsGlobal = isGlobal;
            this._post('loadSessionMessages', '', { session: data.session });
        }
        catch {
            // best-effort
        }
    }
    async _loadAllSessions() {
        try {
            const res = await fetch(`${JARVIS_SERVER}/sessions/list`);
            if (!res.ok) {
                return;
            }
            const data = await res.json();
            this._post('sessionsListLoaded', '', { sessionsData: data });
        }
        catch {
            // best-effort
        }
    }
    // Phase 7: Apply a code block to the active editor file
    async _applyCode(code) {
        const editor = this._lastKnownEditor ?? vscode.window.activeTextEditor;
        if (!editor) {
            vscode.window.showWarningMessage('Jarvis: No active file to apply code to. Click a file tab first.');
            return;
        }
        await editor.edit(editBuilder => {
            const fullRange = new vscode.Range(0, 0, editor.document.lineCount - 1, editor.document.lineAt(editor.document.lineCount - 1).text.length);
            editBuilder.replace(fullRange, code);
        });
        vscode.window.showInformationMessage(`Jarvis applied code to ${editor.document.fileName.split(/[\\/]/).pop()}`);
    }
    // Run an approved terminal command via the server
    async _runCommand(command_str, working_dir, card_id) {
        try {
            const res = await fetch(`${JARVIS_SERVER}/run-command`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ command: command_str, working_dir, job_id: card_id }),
            });
            const data = await res.json();
            this._post('commandResult', '', { card_id, success: data.success, output: data.output });
        }
        catch {
            this._post('commandResult', '', { card_id, success: false, output: 'Could not reach Jarvis server.' });
        }
    }
    _post(command, text, extra) {
        this._panel.webview.postMessage({ command, text, ...extra });
    }
    // ── Cleanup ──────────────────────────────────────────────────────────────
    dispose() {
        JarvisPanel.currentPanel = undefined;
        this._panel.dispose();
        this._disposables.forEach(d => d.dispose());
        this._disposables = [];
    }
    // ── HTML ─────────────────────────────────────────────────────────────────
    _getHtml() {
        return /* html */ `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta http-equiv="Content-Security-Policy"
      content="default-src 'none';
               connect-src http://localhost:3131;
               script-src 'unsafe-inline';
               style-src 'unsafe-inline';">
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }

  html { height: 100%; overflow: hidden; }

  body {
    font-family: var(--vscode-font-family);
    font-size: var(--vscode-font-size);
    background: var(--vscode-editor-background);
    color: var(--vscode-editor-foreground);
    display: flex;
    flex-direction: column;
    height: 100%;
    overflow: hidden;
  }

  /* ── Header ── */
  #header {
    padding: 8px 12px;
    background: var(--vscode-sideBarSectionHeader-background);
    display: flex;
    align-items: center;
    gap: 8px;
    font-weight: bold;
    font-size: 12px;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    flex-shrink: 0;
  }
  #status-dot {
    width: 8px; height: 8px;
    border-radius: 50%;
    background: #888;
    flex-shrink: 0;
  }
  #status-dot.online  { background: #4ec9b0; }
  #status-dot.offline { background: #f48771; }

  #workspace-name {
    font-size: 10px;
    font-weight: normal;
    letter-spacing: 0;
    text-transform: none;
    opacity: 0.5;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    max-width: 90px;
  }

  #session-name {
    font-size: 10px;
    font-weight: normal;
    letter-spacing: 0;
    text-transform: none;
    opacity: 0.7;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    max-width: 110px;
    color: #4ec9b0;
  }

  #header-right {
    margin-left: auto;
    display: flex;
    align-items: center;
    gap: 3px;
    flex-shrink: 0;
  }

  #session-tokens {
    font-size: 10px;
    font-weight: normal;
    letter-spacing: 0;
    text-transform: none;
    opacity: 0.6;
    font-family: var(--vscode-editor-font-family, monospace);
    white-space: nowrap;
    margin-right: 3px;
  }

  .hdr-btn {
    display: flex;
    align-items: center;
    justify-content: center;
    background: none;
    border: 1px solid transparent;
    border-radius: 5px;
    cursor: pointer;
    color: var(--vscode-descriptionForeground);
    font-size: 15px;
    font-weight: normal;
    text-transform: none;
    letter-spacing: 0;
    width: 22px;
    height: 20px;
    line-height: 1;
    flex-shrink: 0;
    transition: background 0.1s, color 0.1s;
    padding: 0;
  }
  .hdr-btn:hover {
    background: var(--vscode-toolbar-hoverBackground, rgba(128,128,128,0.15));
    color: var(--vscode-editor-foreground);
  }

  /* ── Session history drawer ── */
  #session-drawer {
    display: none;
    flex-direction: column;
    border-bottom: 1px solid var(--vscode-panel-border);
    background: var(--vscode-sideBar-background);
    flex-shrink: 0;
  }
  #session-drawer.open { display: flex; }

  #session-drawer-header {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 5px 12px;
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--vscode-descriptionForeground);
    border-bottom: 1px solid var(--vscode-panel-border, rgba(128,128,128,0.2));
    flex-shrink: 0;
  }
  #session-drawer-header label {
    display: flex;
    align-items: center;
    gap: 4px;
    font-weight: normal;
    text-transform: none;
    letter-spacing: 0;
    cursor: pointer;
    margin-left: auto;
    font-size: 11px;
  }
  #drawer-new-btn, #drawer-close-btn {
    background: none;
    border: 1px solid var(--vscode-panel-border, rgba(128,128,128,0.4));
    border-radius: 4px;
    color: var(--vscode-descriptionForeground);
    cursor: pointer;
    font-size: 11px;
    padding: 1px 7px;
    height: 20px;
    line-height: 1;
  }
  #drawer-new-btn:hover, #drawer-close-btn:hover {
    color: var(--vscode-editor-foreground);
    background: var(--vscode-toolbar-hoverBackground, rgba(128,128,128,0.15));
  }
  #session-list-container {
    max-height: 230px;
    overflow-y: auto;
    padding: 4px 0;
  }
  .session-group-label {
    padding: 5px 12px 2px;
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.07em;
    color: var(--vscode-descriptionForeground);
    opacity: 0.55;
    font-weight: 600;
  }
  .session-item {
    padding: 5px 12px 5px 14px;
    cursor: pointer;
    border-left: 2px solid transparent;
    display: flex;
    flex-direction: column;
    gap: 1px;
  }
  .session-item:hover { background: var(--vscode-list-hoverBackground); }
  .session-item.active {
    border-left-color: #4ec9b0;
    background: rgba(78,201,176,0.08);
  }
  .session-item-name {
    font-size: 12px;
    font-weight: 500;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .session-item-time {
    font-size: 10px;
    opacity: 0.45;
  }

  /* ── Messages ── */
  #messages {
    flex: 1;
    overflow-y: auto;
    padding: 12px 12px 24px;
    display: flex;
    flex-direction: column;
    gap: 10px;
    min-height: 0;
  }

  .msg {
    max-width: 100%;
    padding: 8px 10px;
    border-radius: 6px;
    white-space: pre-wrap;
    word-break: break-word;
    line-height: 1.5;
  }
  .msg-user {
    background: var(--vscode-inputOption-activeBackground);
    border-left: 3px solid var(--vscode-focusBorder);
    align-self: flex-end;
  }
  .msg-jarvis {
    background: var(--vscode-editor-inactiveSelectionBackground);
    border-left: 3px solid #4ec9b0;
  }
  .msg-error {
    background: var(--vscode-inputValidation-errorBackground);
    border-left: 3px solid var(--vscode-inputValidation-errorBorder);
  }
  .msg-system {
    color: var(--vscode-descriptionForeground);
    font-size: 11px;
    text-align: center;
    padding: 4px;
  }

  /* ── Apply code button ── */
  .apply-btn {
    display: inline-block;
    margin-top: 6px;
    padding: 3px 8px;
    font-size: 11px;
    background: var(--vscode-button-secondaryBackground, #3a3d41);
    color: var(--vscode-button-secondaryForeground, #cccccc);
    border: 1px solid var(--vscode-button-border, transparent);
    border-radius: 4px;
    cursor: pointer;
  }
  .apply-btn:hover { opacity: 0.85; }

  /* ── Thinking indicator → transforms into token summary ── */
  .msg-thinking {
    display: flex;
    align-items: center;
    gap: 8px;
    color: var(--vscode-descriptionForeground);
    font-style: italic;
    font-size: 11px;
    padding: 4px 10px;
    background: none;
    border: none;
  }
  .thinking-dot {
    width: 6px; height: 6px; border-radius: 50%;
    background: #4ec9b0;
    animation: pulse 1.2s ease-in-out infinite;
    flex-shrink: 0;
  }
  @keyframes pulse {
    0%, 100% { opacity: 0.3; transform: scale(0.85); }
    50%       { opacity: 1;   transform: scale(1.1); }
  }
  #thinking-timer {
    font-family: var(--vscode-editor-font-family, monospace);
    font-size: 11px;
  }

  /* ── Token summary (what the thinking bubble transforms into) ── */
  .msg-token-summary {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 10px;
    color: var(--vscode-descriptionForeground);
    opacity: 0.75;
    padding: 2px 10px 4px;
    font-family: var(--vscode-editor-font-family, monospace);
  }
  .ts-dot {
    color: #4ec9b0;
    font-size: 8px;
    flex-shrink: 0;
  }

  /* ── Attachment chip ── */
  #attachment-bar {
    display: none;
    padding: 4px 12px;
    background: var(--vscode-sideBar-background);
    align-items: center;
    gap: 6px;
    font-size: 11px;
    flex-shrink: 0;
  }
  #attachment-bar.visible { display: flex; }
  #attachment-chip {
    padding: 2px 8px;
    background: var(--vscode-badge-background);
    color: var(--vscode-badge-foreground);
    border-radius: 10px;
    max-width: 220px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  #clear-attach {
    background: none;
    border: none;
    color: var(--vscode-descriptionForeground);
    cursor: pointer;
    font-size: 14px;
    line-height: 1;
    padding: 0 2px;
  }
  #clear-attach:hover { color: var(--vscode-editor-foreground); }

  /* ── Terminal command approval card ── */
  .cmd-card {
    border: 1px solid var(--vscode-panel-border, rgba(128,128,128,0.3));
    border-radius: 6px;
    overflow: hidden;
    background: var(--vscode-editor-inactiveSelectionBackground);
    font-size: 12px;
  }
  .cmd-card-header {
    padding: 5px 10px;
    background: rgba(128,128,128,0.1);
    border-bottom: 1px solid var(--vscode-panel-border, rgba(128,128,128,0.2));
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 11px;
    color: var(--vscode-descriptionForeground);
  }
  .cmd-card-label {
    font-weight: 600;
    color: #4ec9b0;
    flex-shrink: 0;
  }
  .cmd-card-reason {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .cmd-card-body {
    padding: 8px 10px;
  }
  .cmd-card-code {
    display: block;
    font-family: var(--vscode-editor-font-family, monospace);
    font-size: 12px;
    color: var(--vscode-editor-foreground);
    word-break: break-all;
    margin-bottom: 8px;
  }
  .cmd-card-actions {
    display: flex;
    gap: 6px;
  }
  .cmd-run-btn {
    padding: 3px 12px;
    background: var(--vscode-button-background);
    color: var(--vscode-button-foreground);
    border: none;
    border-radius: 4px;
    cursor: pointer;
    font-size: 11px;
  }
  .cmd-run-btn:hover { background: var(--vscode-button-hoverBackground); }
  .cmd-skip-btn {
    padding: 3px 10px;
    background: none;
    color: var(--vscode-descriptionForeground);
    border: 1px solid var(--vscode-panel-border, rgba(128,128,128,0.4));
    border-radius: 4px;
    cursor: pointer;
    font-size: 11px;
  }
  .cmd-skip-btn:hover { background: rgba(128,128,128,0.1); }
  .cmd-kill-btn {
    padding: 3px 10px;
    background: none;
    color: #f48771;
    border: 1px solid rgba(244,135,113,0.5);
    border-radius: 4px;
    cursor: pointer;
    font-size: 11px;
  }
  .cmd-kill-btn:hover { background: rgba(244,135,113,0.1); }
  .cmd-kill-btn:disabled { opacity: 0.4; cursor: not-allowed; }
  .cmd-output {
    margin-top: 6px;
    padding: 6px 8px;
    background: var(--vscode-terminal-background, #1e1e1e);
    color: var(--vscode-terminal-foreground, #d4d4d4);
    font-family: var(--vscode-editor-font-family, monospace);
    font-size: 11px;
    border-radius: 4px;
    white-space: pre-wrap;
    word-break: break-all;
    max-height: 200px;
    overflow-y: auto;
  }
  .cmd-output.success { border-left: 2px solid #4ec9b0; }
  .cmd-output.failure { border-left: 2px solid #f48771; }

  /* ── Input outer (bottom section) ── */
  #input-outer {
    padding: 8px 10px 10px;
    background: var(--vscode-sideBar-background);
    border-top: 1px solid var(--vscode-panel-border);
    position: relative;
    flex-shrink: 0;
  }

  /* ── Commands dropdown ── */
  #cmd-menu {
    display: none;
    position: absolute;
    bottom: calc(100% - 4px);
    left: 10px;
    background: var(--vscode-editorWidget-background, var(--vscode-editor-background));
    border: 1px solid var(--vscode-editorWidget-border, var(--vscode-panel-border));
    border-radius: 8px;
    padding: 4px;
    min-width: 240px;
    box-shadow: 0 -4px 20px rgba(0,0,0,0.35);
    z-index: 100;
  }
  #cmd-menu.open { display: block; }
  .cmd-item {
    padding: 8px 10px;
    border-radius: 5px;
    cursor: pointer;
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  .cmd-item:hover { background: var(--vscode-list-hoverBackground); }
  .cmd-name {
    font-weight: 600;
    font-size: 12px;
    color: var(--vscode-editor-foreground);
    font-family: var(--vscode-editor-font-family, monospace);
  }
  .cmd-desc {
    font-size: 10px;
    color: var(--vscode-descriptionForeground);
  }

  /* ── Input wrapper (bordered card) ── */
  #input-wrapper {
    border: 1px solid var(--vscode-input-border, rgba(128,128,128,0.4));
    border-radius: 10px;
    background: var(--vscode-input-background);
    overflow: hidden;
    transition: border-color 0.15s;
  }
  #input-wrapper:focus-within {
    border-color: var(--vscode-focusBorder);
  }

  #input {
    display: block;
    width: 100%;
    resize: none;
    background: transparent;
    color: var(--vscode-input-foreground);
    border: none;
    outline: none;
    padding: 10px 12px 6px;
    font-family: var(--vscode-font-family);
    font-size: var(--vscode-font-size);
    line-height: 1.5;
    min-height: 38px;
    max-height: 160px;
  }
  #input::placeholder { color: var(--vscode-input-placeholderForeground); }

  /* ── Toolbar row inside the card ── */
  #toolbar {
    display: flex;
    align-items: center;
    padding: 3px 6px 5px;
    gap: 2px;
    border-top: 1px solid var(--vscode-panel-border, rgba(128,128,128,0.2));
  }

  /* Left icon buttons */
  .tool-btn {
    display: flex;
    align-items: center;
    justify-content: center;
    background: none;
    border: 1px solid transparent;
    border-radius: 6px;
    padding: 4px 6px;
    cursor: pointer;
    color: var(--vscode-descriptionForeground);
    line-height: 1;
    font-size: 12px;
    min-width: 28px;
    height: 26px;
    transition: background 0.1s, color 0.1s;
    flex-shrink: 0;
  }
  .tool-btn:hover {
    background: var(--vscode-toolbar-hoverBackground, rgba(128,128,128,0.15));
    color: var(--vscode-editor-foreground);
  }
  .tool-btn.active {
    background: var(--vscode-toolbar-activeBackground, rgba(128,128,128,0.25));
    color: var(--vscode-editor-foreground);
  }

  /* Send button — right side */
  #send {
    margin-left: auto;
    display: flex;
    align-items: center;
    justify-content: center;
    background: var(--vscode-button-background);
    color: var(--vscode-button-foreground);
    border: none;
    border-radius: 7px;
    width: 30px;
    height: 26px;
    cursor: pointer;
    flex-shrink: 0;
    transition: background 0.1s, opacity 0.1s;
  }
  #send:hover:not(:disabled) { background: var(--vscode-button-hoverBackground); }
  #send:disabled { opacity: 0.3; cursor: not-allowed; }
</style>
</head>
<body>

<div id="header">
  <div id="status-dot"></div>
  <span>Jarvis</span>
  <span id="workspace-name"></span>
  <span id="session-name"></span>
  <div id="header-right">
    <span id="session-tokens"></span>
    <button class="hdr-btn" id="new-session-btn" title="New session">+</button>
    <button class="hdr-btn" id="history-btn" title="Session history">&#x2630;</button>
  </div>
</div>

<!-- Session history drawer (hidden until history button clicked) -->
<div id="session-drawer">
  <div id="session-drawer-header">
    <span>History</span>
    <label><input type="checkbox" id="new-global-check"> Global</label>
    <button id="drawer-new-btn">New</button>
    <button id="drawer-close-btn">&#x2715;</button>
  </div>
  <div id="session-list-container"></div>
</div>

<div id="messages">
  <div class="msg msg-system">
    Jarvis is connected to your local server.<br>
    Your active file and workspace are included as context.
  </div>
</div>

<!-- Attachment chip (shown when a file is staged) -->
<div id="attachment-bar">
  <span id="attachment-chip"></span>
  <button id="clear-attach" title="Remove attachment">&#x2715;</button>
</div>
<input type="file" id="file-input" style="display:none" accept="*">

<!-- Bottom input section -->
<div id="input-outer">

  <!-- Commands dropdown (slides up from toolbar) -->
  <div id="cmd-menu">
    <div class="cmd-item" data-cmd="/rules">
      <span class="cmd-name">/rules</span>
      <span class="cmd-desc">Manage global rules for all conversations</span>
    </div>
    <div class="cmd-item" data-cmd="/project rules">
      <span class="cmd-name">/project rules</span>
      <span class="cmd-desc">Manage rules for this project only</span>
    </div>
    <div class="cmd-item" data-cmd="/attach">
      <span class="cmd-name">/attach</span>
      <span class="cmd-desc">Attach a file or image to your message</span>
    </div>
  </div>

  <!-- Bordered input card -->
  <div id="input-wrapper">
    <textarea id="input" rows="1" placeholder="Ask Jarvis..."></textarea>
    <div id="toolbar">

      <!-- Attach button (paperclip) -->
      <button class="tool-btn" id="attach-btn" title="Attach file or image">
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="m21.44 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l8.57-8.57A4 4 0 1 1 18 8.84l-8.59 8.57a2 2 0 0 1-2.83-2.83l8.49-8.48"/>
        </svg>
      </button>

      <!-- Commands button (/) -->
      <button class="tool-btn" id="cmd-btn" title="Commands">
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
          <line x1="4" y1="9" x2="20" y2="9"/>
          <line x1="4" y1="15" x2="20" y2="15"/>
          <line x1="10" y1="3" x2="8" y2="21"/>
          <line x1="16" y1="3" x2="14" y2="21"/>
        </svg>
      </button>

      <!-- Send button (arrow) -->
      <button id="send" title="Send (Enter)" disabled>
        <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
          <path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/>
        </svg>
      </button>

    </div>
  </div>
</div>

<script>
  const vscode      = acquireVsCodeApi();
  const messages    = document.getElementById('messages');
  const input       = document.getElementById('input');
  const sendBtn     = document.getElementById('send');
  const dot         = document.getElementById('status-dot');
  const attachBtn   = document.getElementById('attach-btn');
  const cmdBtn      = document.getElementById('cmd-btn');
  const cmdMenu     = document.getElementById('cmd-menu');
  const fileInput   = document.getElementById('file-input');
  const attachBar   = document.getElementById('attachment-bar');
  const attachChip  = document.getElementById('attachment-chip');
  const clearAttach = document.getElementById('clear-attach');
  const drawer      = document.getElementById('session-drawer');
  const drawerList  = document.getElementById('session-list-container');
  const newSessBtn  = document.getElementById('new-session-btn');
  const histBtn     = document.getElementById('history-btn');
  const drawerClose = document.getElementById('drawer-close-btn');
  const drawerNew   = document.getElementById('drawer-new-btn');
  const globalCheck = document.getElementById('new-global-check');

  let pendingAttachment = null;
  let isSending = false;
  let timerInterval = null;
  let sessionTotalTokens = 0;
  let sessionTotalCost = 0;
  let currentSessionId = '';

  // ── Auto-resize textarea + toggle send button ──
  input.addEventListener('input', () => {
    input.style.height = 'auto';
    input.style.height = Math.min(input.scrollHeight, 160) + 'px';
    sendBtn.disabled = !input.value.trim() || isSending;
  });

  // ── Format model ID → short name ──
  function formatModel(modelId) {
    const m = (modelId || '').match(/claude-(\\w+)-(\\d+)-(\\d+)/);
    if (m) return m[1].charAt(0).toUpperCase() + m[1].slice(1) + ' ' + m[2] + '.' + m[3];
    return modelId || 'Sonnet';
  }

  // ── Update session token counter in header ──
  function updateSessionCounter() {
    const el = document.getElementById('session-tokens');
    if (el && sessionTotalTokens > 0) {
      const cost = sessionTotalCost >= 0.01
        ? '$' + sessionTotalCost.toFixed(2)
        : '$' + sessionTotalCost.toFixed(5).replace(/0+$/, '');
      el.textContent = sessionTotalTokens.toLocaleString() + ' tok \u2022 ' + cost;
    }
  }

  // ── Add message bubble ──
  function addMsg(text, cls) {
    const div = document.createElement('div');
    div.className = 'msg ' + cls;
    div.textContent = text;

    if (cls === 'msg-jarvis') {
      const codeMatch = text.match(/\`\`\`[\\w]*\\n([\\s\\S]+?)\\n\`\`\`/);
      if (codeMatch) {
        const code = codeMatch[1];
        const btn = document.createElement('button');
        btn.className = 'apply-btn';
        btn.textContent = 'Apply to active file';
        btn.onclick = () => vscode.postMessage({ command: 'applyCode', code });
        div.appendChild(document.createElement('br'));
        div.appendChild(btn);
      }
    }

    messages.appendChild(div);
    messages.scrollTop = messages.scrollHeight;
    return div;
  }

  // ── Thinking indicator with live timer ──
  let thinkingEl = null;
  let thinkingStartMs = 0;

  function showTyping() {
    thinkingStartMs = Date.now();
    thinkingEl = document.createElement('div');
    thinkingEl.className = 'msg msg-thinking';
    thinkingEl.innerHTML =
      '<div class="thinking-dot"></div>' +
      '<span>Thinking&hellip;</span>' +
      '<span id="thinking-timer">0s</span>';
    messages.appendChild(thinkingEl);
    messages.scrollTop = messages.scrollHeight;

    const start = Date.now();
    timerInterval = setInterval(() => {
      const el = document.getElementById('thinking-timer');
      if (!el) return;
      const elapsed = Math.floor((Date.now() - start) / 1000);
      if (elapsed < 60) {
        el.textContent = elapsed + 's';
      } else {
        const m = Math.floor(elapsed / 60), s = elapsed % 60;
        el.textContent = m + 'm ' + String(s).padStart(2, '0') + 's';
      }
    }, 500);
  }

  function hideTyping(tokenData) {
    clearInterval(timerInterval);
    timerInterval = null;
    if (!thinkingEl) return;

    const elapsed = Math.round((Date.now() - thinkingStartMs) / 1000);
    const timeStr = elapsed < 60
      ? elapsed + 's'
      : Math.floor(elapsed / 60) + 'm ' + String(elapsed % 60).padStart(2, '0') + 's';

    if (tokenData) {
      const model = formatModel(tokenData.model);
      const cost = tokenData.cost >= 0.01
        ? '$' + tokenData.cost.toFixed(2)
        : '$' + tokenData.cost.toFixed(5).replace(/0+$/, '');

      thinkingEl.className = 'msg-token-summary';
      thinkingEl.innerHTML =
        '<span class="ts-dot">&#9679;</span>' +
        model + ' &bull; ' +
        tokenData.total.toLocaleString() + ' tokens &bull; ' +
        cost + ' &bull; ' + timeStr;

      sessionTotalTokens += tokenData.total;
      sessionTotalCost += tokenData.cost;
      updateSessionCounter();
    } else {
      thinkingEl.remove();
    }
    thinkingEl = null;
  }

  // ── Attachment helpers ──
  function showChip(label) {
    attachChip.textContent = label;
    attachBar.classList.add('visible');
  }
  function hideChip() {
    attachBar.classList.remove('visible');
    attachChip.textContent = '';
    pendingAttachment = null;
    fileInput.value = '';
  }

  // ── Commands dropdown ──
  function toggleCmdMenu() {
    const isOpen = cmdMenu.classList.contains('open');
    cmdMenu.classList.toggle('open', !isOpen);
    cmdBtn.classList.toggle('active', !isOpen);
  }
  function closeCmdMenu() {
    cmdMenu.classList.remove('open');
    cmdBtn.classList.remove('active');
  }

  cmdBtn.addEventListener('click', (e) => { e.stopPropagation(); toggleCmdMenu(); });

  document.querySelectorAll('.cmd-item').forEach(item => {
    item.addEventListener('click', () => {
      const cmd = item.dataset.cmd;
      if (cmd === '/attach') {
        closeCmdMenu();
        fileInput.click();
      } else {
        input.value = cmd + ' ';
        input.dispatchEvent(new Event('input'));
        input.focus();
        closeCmdMenu();
      }
    });
  });

  document.addEventListener('click', (e) => {
    if (!cmdMenu.contains(e.target) && e.target !== cmdBtn) closeCmdMenu();
  });

  // ── Attach button ──
  attachBtn.addEventListener('click', () => fileInput.click());
  clearAttach.addEventListener('click', hideChip);

  // ── File selected ──
  fileInput.addEventListener('change', () => {
    const file = fileInput.files[0];
    if (!file) return;
    const isImage = file.type.startsWith('image/');
    const reader = new FileReader();

    if (isImage) {
      reader.readAsDataURL(file);
      reader.onload = () => {
        const parts = reader.result.split(',');
        pendingAttachment = { name: file.name, isImage: true, base64: parts[1] || '', mimeType: file.type };
        showChip(file.name + ' (image)');
      };
    } else {
      reader.readAsText(file);
      reader.onload = () => {
        pendingAttachment = { name: file.name, isImage: false, contentText: reader.result };
        showChip(file.name);
      };
    }
    reader.onerror = () => showChip('Error reading file');
  });

  // ── Session drawer ──
  function openDrawer() {
    drawer.classList.add('open');
    vscode.postMessage({ command: 'openSessionDrawer' });
  }
  function closeDrawer() {
    drawer.classList.remove('open');
  }

  newSessBtn.addEventListener('click', () => {
    vscode.postMessage({ command: 'newSession', isGlobal: globalCheck.checked });
  });

  histBtn.addEventListener('click', () => {
    drawer.classList.contains('open') ? closeDrawer() : openDrawer();
  });

  drawerClose.addEventListener('click', closeDrawer);

  drawerNew.addEventListener('click', () => {
    closeDrawer();
    vscode.postMessage({ command: 'newSession', isGlobal: globalCheck.checked });
  });

  function formatRelativeTime(isoStr) {
    if (!isoStr) return '';
    try {
      const d = new Date(isoStr + 'Z');
      const diffMin = Math.floor((Date.now() - d.getTime()) / 60000);
      if (diffMin < 1) return 'just now';
      if (diffMin < 60) return diffMin + 'm ago';
      const diffH = Math.floor(diffMin / 60);
      if (diffH < 24) return diffH + 'h ago';
      return Math.floor(diffH / 24) + 'd ago';
    } catch { return ''; }
  }

  function escHtml(str) {
    return String(str)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  function populateDrawer(data) {
    drawerList.innerHTML = '';

    const globals = (data.global || []);
    if (globals.length > 0) {
      const lbl = document.createElement('div');
      lbl.className = 'session-group-label';
      lbl.textContent = 'Global';
      drawerList.appendChild(lbl);
      globals.forEach(s => drawerList.appendChild(createSessionItem(s, '', true)));
    }

    const projects = data.projects || {};
    Object.entries(projects).forEach(([wsRoot, proj]) => {
      const lbl = document.createElement('div');
      lbl.className = 'session-group-label';
      lbl.textContent = proj.project_name || wsRoot.split(/[\\\\/]/).pop() || wsRoot;
      drawerList.appendChild(lbl);
      (proj.sessions || []).forEach(s => drawerList.appendChild(createSessionItem(s, wsRoot, false)));
    });

    if (drawerList.children.length === 0) {
      drawerList.innerHTML = '<div style="padding:12px;font-size:11px;opacity:0.5;text-align:center">No sessions yet</div>';
    }
  }

  function createSessionItem(sess, workspaceRoot, isGlobal) {
    const item = document.createElement('div');
    item.className = 'session-item' + (sess.id === currentSessionId ? ' active' : '');
    item.innerHTML =
      '<div class="session-item-name">' + escHtml(sess.name || '(untitled)') + '</div>' +
      '<div class="session-item-time">' + formatRelativeTime(sess.updated_at) + '</div>';
    item.addEventListener('click', () => {
      closeDrawer();
      // Prefer the session's own workspace_root — the group key may be empty
      // when _summary.json hasn't been written yet (session never explicitly closed).
      const effectiveWsRoot = sess.workspace_root || workspaceRoot;
      vscode.postMessage({ command: 'loadSession', sessionId: sess.id, workspaceRoot: effectiveWsRoot, isGlobal });
    });
    return item;
  }

  function clearMessages() {
    messages.innerHTML = '';
    sessionTotalTokens = 0;
    sessionTotalCost = 0;
    document.getElementById('session-tokens').textContent = '';
  }

  // ── Send message ──
  function send() {
    const text = input.value.trim();
    if (!text || isSending) return;

    const displayText = pendingAttachment
      ? text + '\\n[+ ' + pendingAttachment.name + ']'
      : text;
    addMsg(displayText, 'msg-user');

    input.value = '';
    input.style.height = 'auto';
    isSending = true;
    sendBtn.disabled = true;
    showTyping();
    closeCmdMenu();

    vscode.postMessage({ command: 'send', text, attachment: pendingAttachment });
    hideChip();
  }

  sendBtn.addEventListener('click', send);
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
  });

  // ── Command card helpers ──
  let cardCounter = 0;

  function addCommandCard(cmd) {
    const id = 'cmd-card-' + (++cardCounter);
    const div = document.createElement('div');
    div.className = 'cmd-card';
    div.id = id;
    div.innerHTML =
      '<div class="cmd-card-header">' +
        '<span class="cmd-card-label">Run command?</span>' +
        '<span class="cmd-card-reason">' + escHtml(cmd.reason || '') + '</span>' +
      '</div>' +
      '<div class="cmd-card-body">' +
        '<code class="cmd-card-code">' + escHtml(cmd.command) + '</code>' +
        '<div class="cmd-card-actions">' +
          '<button class="cmd-run-btn">Run</button>' +
          '<button class="cmd-skip-btn">Skip</button>' +
        '</div>' +
      '</div>';

    const runBtn = div.querySelector('.cmd-run-btn');
    const skipBtn = div.querySelector('.cmd-skip-btn');
    const actionsDiv = div.querySelector('.cmd-card-actions');

    runBtn.addEventListener('click', () => {
      runBtn.disabled = true;
      runBtn.textContent = 'Running...';
      skipBtn.remove();
      const killBtn = document.createElement('button');
      killBtn.className = 'cmd-kill-btn';
      killBtn.textContent = 'Kill';
      killBtn.addEventListener('click', () => {
        killBtn.disabled = true;
        killBtn.textContent = 'Killing...';
        fetch('http://localhost:3131/kill-command', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ job_id: id }),
        }).catch(() => {});
      });
      actionsDiv.appendChild(killBtn);
      vscode.postMessage({ command: 'runCommand', command_str: cmd.command, working_dir: cmd.working_dir, card_id: id });
    });

    skipBtn.addEventListener('click', () => {
      actionsDiv.innerHTML = '<span style="font-size:11px;opacity:0.5">Skipped</span>';
    });

    messages.appendChild(div);
    messages.scrollTop = messages.scrollHeight;
  }

  // ── Handle messages from extension ──
  window.addEventListener('message', (e) => {
    const { command, text, tokens, filesWritten, commandsToRun,
            card_id, success, output, session, sessionsData, sessionName } = e.data;

    if (command === 'commandResult') {
      const card = document.getElementById(card_id);
      if (card) {
        const actions = card.querySelector('.cmd-card-actions');
        const killed = output && output.startsWith('Killed by user');
        const label = success ? 'Done' : killed ? 'Killed' : 'Failed';
        const color = success ? '#4ec9b0' : killed ? '#ce9178' : '#f48771';
        if (actions) actions.innerHTML = '<span style="font-size:11px;color:' + color + '">' + label + '</span>';
        if (output) {
          const pre = document.createElement('div');
          pre.className = 'cmd-output ' + (success ? 'success' : 'failure');
          pre.textContent = output;
          card.querySelector('.cmd-card-body').appendChild(pre);
        }
        messages.scrollTop = messages.scrollHeight;
      }
      return;
    }

    if (command === 'sessionCreated') {
      clearMessages();
      currentSessionId = session.id;
      const nameEl = document.getElementById('session-name');
      if (nameEl) nameEl.textContent = session.name || '';
      addMsg('New session started.', 'msg-system');
      return;
    }

    if (command === 'loadSessionMessages') {
      clearMessages();
      currentSessionId = session.id;
      const nameEl = document.getElementById('session-name');
      if (nameEl) nameEl.textContent = session.name || '';
      const msgs = session.messages || [];
      msgs.forEach(m => addMsg(m.content, m.role === 'user' ? 'msg-user' : 'msg-jarvis'));
      if (msgs.length > 0) {
        addMsg('Session restored \u2014 ' + msgs.length + ' message' + (msgs.length === 1 ? '' : 's') + ' loaded.', 'msg-system');
      }
      return;
    }

    if (command === 'sessionsListLoaded') {
      populateDrawer(sessionsData);
      return;
    }

    // Only clear the thinking indicator when an actual response or error arrives.
    if (command === 'response' || command === 'error') {
      hideTyping(tokens || null);
      isSending = false;
      sendBtn.disabled = !input.value.trim();
    }

    if (command === 'response') {
      addMsg(text, 'msg-jarvis');
      if (sessionName) {
        const nameEl = document.getElementById('session-name');
        if (nameEl) nameEl.textContent = sessionName;
      }
      if (filesWritten && filesWritten.length > 0) {
        const names = filesWritten.map(p => p.replace(/\\\\/g, '/').split('/').pop()).join(', ');
        addMsg('Wrote: ' + names, 'msg-system');
      }
      if (commandsToRun && commandsToRun.length > 0) {
        commandsToRun.forEach(cmd => addCommandCard(cmd));
      }
    } else if (command === 'error') {
      addMsg(text, 'msg-error');
    } else if (command === 'prefill') {
      input.value = text;
      input.dispatchEvent(new Event('input'));
      input.focus();
    } else if (command === 'serverStatus') {
      dot.className = text === 'online' ? 'online' : 'offline';
    } else if (command === 'workspaceInfo') {
      const el = document.getElementById('workspace-name');
      if (el) el.textContent = text ? '\u2014 ' + text : '';
    }
  });

  // Check server on load
  vscode.postMessage({ command: 'checkServer' });
  setInterval(() => vscode.postMessage({ command: 'checkServer' }), 30000);
</script>
</body>
</html>`;
    }
}
exports.JarvisPanel = JarvisPanel;
//# sourceMappingURL=jarvisPanel.js.map