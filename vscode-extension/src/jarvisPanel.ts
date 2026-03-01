// jarvisPanel.ts
// Phase UX — WebviewViewProvider (sidebar), navigable sessions page, + spinner,
//             +▾ dropdown, jump-to-bottom button, empty-session cleanup.

import * as vscode from 'vscode';
import * as path from 'path';

const JARVIS_SERVER = 'http://localhost:3131';

/**
 * Returns true if a command result is worth sending to Jarvis automatically on success.
 * Trivial commands (dir, ls, echo, type, cat, pwd) are silently dismissed on success;
 * failures are always reported regardless.
 */
function _isMeaningfulCommand(cmd: string): boolean {
    const c = cmd.trim().toLowerCase();
    const trivialPrefixes = ['dir ', 'dir\r', 'dir\n', 'ls ', 'ls\r', 'ls\n',
        'echo ', 'type ', 'cat ', 'pwd', 'cd ', 'clear', 'cls'];
    const trivialExact = ['dir', 'ls', 'pwd', 'clear', 'cls'];
    if (trivialExact.includes(c)) { return false; }
    if (trivialPrefixes.some(p => c.startsWith(p))) { return false; }
    return true;
}

// Shared output channel for debug logging
let _outputChannel: vscode.OutputChannel | undefined;
export function setOutputChannel(ch: vscode.OutputChannel): void { _outputChannel = ch; }
function dbg(msg: string): void { _outputChannel?.appendLine('[JarvisPanel] ' + msg); }

export class JarvisViewProvider implements vscode.WebviewViewProvider {
    public static readonly viewType = 'jarvis.view';
    private static _instance: JarvisViewProvider | undefined;

    private _view?: vscode.WebviewView;
    private _disposables: vscode.Disposable[] = [];
    // Tracks the last real text editor even while the webview has focus
    private _lastKnownEditor: vscode.TextEditor | undefined = vscode.window.activeTextEditor;

    // Phase 10: session tracking
    private _currentSessionId: string = '';
    private _currentIsGlobal: boolean = false;
    private _sessionRestored: boolean = false;

    // Phase 12: agent job polling
    private _agentPollTimer: ReturnType<typeof setInterval> | undefined;

    constructor(private readonly _extensionUri: vscode.Uri) {
        JarvisViewProvider._instance = this;
        vscode.window.onDidChangeActiveTextEditor(editor => {
            if (editor) { this._lastKnownEditor = editor; }
        }, null, this._disposables);
    }

    public static prefillInput(text: string): void {
        JarvisViewProvider._instance?._view?.webview.postMessage({ command: 'prefill', text });
    }

    // ── WebviewViewProvider ──────────────────────────────────────────────────

    public resolveWebviewView(
        webviewView: vscode.WebviewView,
        _context: vscode.WebviewViewResolveContext,
        _token: vscode.CancellationToken
    ): void {
        this._view = webviewView;

        webviewView.webview.options = {
            enableScripts: true,
            localResourceRoots: [this._extensionUri]
        };

        webviewView.webview.html = this._getHtml();

        webviewView.webview.onDidReceiveMessage(async (msg) => {
            if (msg.command === 'send') {
                await this._handleSend(msg.text, msg.attachment);
            } else if (msg.command === 'checkServer') {
                await this._checkServer();
            } else if (msg.command === 'applyCode') {
                await this._applyCode(msg.code);
            } else if (msg.command === 'runCommand') {
                await this._runCommand(msg.command_str, msg.working_dir, msg.card_id,
                    this._currentSessionId, this._currentIsGlobal);
            } else if (msg.command === 'newSession') {
                await this._newSession(msg.isGlobal ?? false);
            } else if (msg.command === 'openSessionDrawer') {
                await this._loadAllSessions();
            } else if (msg.command === 'loadSession') {
                await this._loadSession(msg.sessionId, msg.workspaceRoot, msg.isGlobal ?? false);
            } else if (msg.command === 'deleteSession') {
                await this._deleteSession(msg.sessionId, msg.workspaceRoot, msg.isGlobal ?? false);
            } else if (msg.command === 'renameSession') {
                await this._renameSession(msg.name ?? '');
            } else if (msg.command === 'openFile') {
                try {
                    const uri = vscode.Uri.file(msg.path);
                    const doc = await vscode.workspace.openTextDocument(uri);
                    await vscode.window.showTextDocument(doc);
                } catch { /* file may not exist yet */ }
            }
        }, null, this._disposables);

        webviewView.onDidChangeVisibility(() => {
            if (webviewView.visible) {
                this._postWorkspaceInfo();
            }
        }, null, this._disposables);
    }

    // ── Helpers ──────────────────────────────────────────────────────────────

    private _getWorkspaceRoot(): string {
        const folder = vscode.workspace.workspaceFolders?.[0];
        const editor = this._lastKnownEditor ?? vscode.window.activeTextEditor;
        if (folder) { return folder.uri.fsPath; }
        if (editor && editor.document.uri.scheme === 'file') {
            return path.dirname(editor.document.uri.fsPath);
        }
        return '';
    }

    // ── Message handling ─────────────────────────────────────────────────────

    private async _handleSend(message: string, attachment?: {
        name: string;
        isImage: boolean;
        contentText?: string;
        base64?: string;
        mimeType?: string;
    }): Promise<void> {
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
                    attachment_name: attachment?.name ?? '',
                    attachment_text: (attachment && !attachment.isImage ? attachment.contentText : '') ?? '',
                    attachment_image_base64: (attachment?.isImage ? attachment.base64 : '') ?? '',
                    attachment_image_type: (attachment?.isImage ? attachment.mimeType : '') ?? '',
                    session_id: this._currentSessionId,
                    is_global: this._currentIsGlobal,
                })
            });

            if (!res.ok) {
                const err = await res.json() as { error: string };
                this._post('error', `Server error: ${err.error}`);
                return;
            }

            const data = await res.json() as {
                response: string | null;
                tokens?: object;
                files_written?: string[];
                commands_to_run?: { command: string; working_dir: string; reason: string }[];
                session_id?: string;
                session_name?: string;
                agent_job_id?: string;
                session_token_total?: number;
                compressed_count?: number;
            };

            if (data.session_id) { this._currentSessionId = data.session_id; }

            if (data.agent_job_id) {
                this._post('agentJobStarted', '', { job_id: data.agent_job_id });
                this._startAgentPolling(data.agent_job_id);
                return;
            }

            const filesWritten = data.files_written ?? [];
            const commandsToRun = data.commands_to_run ?? [];
            this._post('response', data.response ?? '', {
                ...(data.tokens ? { tokens: data.tokens } : {}),
                ...(filesWritten.length > 0 ? { filesWritten } : {}),
                ...(commandsToRun.length > 0 ? { commandsToRun } : {}),
                ...(data.session_name !== undefined ? { sessionName: data.session_name } : {}),
                ...(data.session_token_total !== undefined ? { sessionTokenTotal: data.session_token_total } : {}),
                ...(data.compressed_count !== undefined ? { compressedCount: data.compressed_count } : {}),
            });

        } catch {
            this._post('error',
                'Could not connect to Jarvis server.\n\n' +
                'Start it with:  python server.py\n' +
                'Then try again.'
            );
        }
    }

    private async _checkServer(): Promise<void> {
        dbg('_checkServer() called');
        try {
            const res = await fetch(`${JARVIS_SERVER}/status`);
            const data = await res.json() as { status: string };
            const isOnline = data.status === 'running';
            dbg('server status: ' + (isOnline ? 'online' : 'offline'));
            this._post('serverStatus', isOnline ? 'online' : 'offline');
            if (isOnline && !this._sessionRestored) {
                this._sessionRestored = true;
                await this._restoreActiveSession();
            }
        } catch (err) {
            dbg('_checkServer() catch: ' + String(err));
            this._post('serverStatus', 'offline');
        }
        this._postWorkspaceInfo();
    }

    private _postWorkspaceInfo(): void {
        const folder = vscode.workspace.workspaceFolders?.[0];
        const editor = this._lastKnownEditor ?? vscode.window.activeTextEditor;
        let name = '';
        if (folder) {
            name = folder.name;
        } else if (editor && editor.document.uri.scheme === 'file') {
            name = path.basename(path.dirname(editor.document.uri.fsPath));
        }
        this._post('workspaceInfo', name, { rootPath: this._getWorkspaceRoot() });
    }

    private async _restoreActiveSession(): Promise<void> {
        try {
            const workspaceRoot = this._getWorkspaceRoot();
            const res = await fetch(
                `${JARVIS_SERVER}/sessions/active?workspace_root=${encodeURIComponent(workspaceRoot)}`
            );
            if (!res.ok) { return; }
            const data = await res.json() as { session: Record<string, unknown> | null };
            if (data.session) {
                this._currentSessionId = data.session['id'] as string;
                this._currentIsGlobal = (data.session['is_global'] as boolean) ?? false;
                this._post('loadSessionMessages', '', { session: data.session });
            }
        } catch {
            // best-effort
        }
    }

    private async _newSession(isGlobal: boolean): Promise<void> {
        const workspaceRoot = this._getWorkspaceRoot();
        try {
            const res = await fetch(`${JARVIS_SERVER}/sessions/new`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ workspace_root: workspaceRoot, is_global: isGlobal }),
            });
            if (!res.ok) {
                this._post('newSessionFailed', '');
                return;
            }
            const data = await res.json() as { session: Record<string, unknown> };
            this._currentSessionId = data.session['id'] as string;
            this._currentIsGlobal = isGlobal;
            this._post('sessionCreated', '', { session: data.session });
        } catch {
            this._post('newSessionFailed', '');
        }
    }

    private async _loadSession(sessionId: string, workspaceRoot: string, isGlobal: boolean): Promise<void> {
        try {
            const url = `${JARVIS_SERVER}/sessions/load?session_id=${encodeURIComponent(sessionId)}&workspace_root=${encodeURIComponent(workspaceRoot)}&is_global=${isGlobal ? '1' : '0'}`;
            const res = await fetch(url);
            if (!res.ok) { return; }
            const data = await res.json() as { session: Record<string, unknown> };
            this._currentSessionId = sessionId;
            this._currentIsGlobal = isGlobal;
            this._post('loadSessionMessages', '', { session: data.session });
        } catch {
            // best-effort
        }
    }

    private async _loadAllSessions(): Promise<void> {
        try {
            const [sessRes, histRes] = await Promise.all([
                fetch(`${JARVIS_SERVER}/sessions/list`),
                fetch(`${JARVIS_SERVER}/agents/history`).catch(() => null),
            ]);
            if (!sessRes.ok) { return; }
            const data = await sessRes.json() as Record<string, unknown>;
            const histData = (histRes?.ok ? await histRes.json() : null) as Record<string, unknown> | null;
            const jobHistory = (histData?.['jobs'] as unknown[]) ?? [];
            this._post('sessionsListLoaded', '', { sessionsData: data, jobHistory });
        } catch {
            // best-effort
        }
    }

    private async _deleteSession(sessionId: string, workspaceRoot: string, isGlobal: boolean): Promise<void> {
        try {
            await fetch(`${JARVIS_SERVER}/sessions/delete`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ session_id: sessionId, workspace_root: workspaceRoot, is_global: isGlobal }),
            });
        } catch {
            // best-effort
        }
    }

    private async _renameSession(name: string): Promise<void> {
        if (!this._currentSessionId || !name) { return; }
        try {
            await fetch(`${JARVIS_SERVER}/sessions/rename`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    session_id: this._currentSessionId,
                    workspace_root: this._getWorkspaceRoot(),
                    is_global: this._currentIsGlobal,
                    name,
                }),
            });
        } catch {
            // best-effort
        }
    }

    // Phase 7: Apply a code block to the active editor file
    private async _applyCode(code: string): Promise<void> {
        const editor = this._lastKnownEditor ?? vscode.window.activeTextEditor;
        if (!editor) {
            vscode.window.showWarningMessage('Jarvis: No active file to apply code to. Click a file tab first.');
            return;
        }
        await editor.edit(editBuilder => {
            const fullRange = new vscode.Range(
                0, 0,
                editor.document.lineCount - 1,
                editor.document.lineAt(editor.document.lineCount - 1).text.length
            );
            editBuilder.replace(fullRange, code);
        });
        vscode.window.showInformationMessage(`Jarvis applied code to ${editor.document.fileName.split(/[\\/]/).pop()}`);
    }

    // Run an approved terminal command via the server
    private async _runCommand(
        command_str: string, working_dir: string, card_id: string,
        sessionId: string = '', isGlobal: boolean = false
    ): Promise<void> {
        const workspaceRoot = this._getWorkspaceRoot();
        try {
            const res = await fetch(`${JARVIS_SERVER}/run-command`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    command: command_str, working_dir, job_id: card_id,
                    session_id: sessionId, workspace_root: workspaceRoot, is_global: isGlobal,
                }),
            });
            const data = await res.json() as { success: boolean; output: string };
            this._post('commandResult', '', { card_id, success: data.success, output: data.output });

            const shouldNotify = !data.success || _isMeaningfulCommand(command_str);
            if (shouldNotify) {
                const status = data.success ? 'succeeded' : 'FAILED';
                const notify = `Command ${status}.\n\nCommand: \`${command_str}\`\nOutput:\n${data.output || '(no output)'}`;
                this._post('startAutoChat', '', { success: data.success });
                await this._handleSend(notify);
            }
        } catch {
            this._post('commandResult', '', { card_id, success: false, output: 'Could not reach Jarvis server.' });
        }
    }

    // ── Phase 12: Agent job polling ───────────────────────────────────────────

    private _startAgentPolling(jobId: string): void {
        if (this._agentPollTimer) { clearInterval(this._agentPollTimer); }
        this._agentPollTimer = setInterval(async () => {
            try {
                const res = await fetch(
                    `${JARVIS_SERVER}/agents/status?job_id=${encodeURIComponent(jobId)}`
                );
                if (!res.ok) { return; }
                const job = await res.json() as Record<string, unknown>;
                this._post('agentStatusUpdate', '', { job });
                const status = job['status'] as string;
                if (status === 'done' || status === 'failed') {
                    clearInterval(this._agentPollTimer!);
                    this._agentPollTimer = undefined;
                    this._post('agentJobDone', '', { job });
                }
            } catch { /* transient error — keep polling */ }
        }, 2000);
    }

    private _post(command: string, text: string, extra?: Record<string, unknown>): void {
        this._view?.webview.postMessage({ command, text, ...extra });
    }

    // ── Cleanup ──────────────────────────────────────────────────────────────

    public dispose(): void {
        JarvisViewProvider._instance = undefined;
        this._disposables.forEach(d => d.dispose());
        this._disposables = [];
    }

    // ── HTML ─────────────────────────────────────────────────────────────────

    private _getHtml(): string {
        return /* html */`<!DOCTYPE html>
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

  html, body { height: 100%; overflow: hidden; }

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

  /* ── View containers ── */
  #chat-view {
    display: flex;
    flex-direction: column;
    height: 100%;
    overflow: hidden;
  }
  #sessions-view {
    display: none;
    flex-direction: column;
    height: 100%;
    overflow: hidden;
  }

  /* ── Header (chat view) ── */
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
    cursor: pointer;
  }
  #status-dot:hover { opacity: 0.7; }
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
    cursor: pointer;
  }
  #session-name:hover { opacity: 1; }
  .session-name-input {
    font-size: 10px;
    font-family: var(--vscode-font-family);
    background: var(--vscode-input-background);
    color: #4ec9b0;
    border: 1px solid var(--vscode-focusBorder);
    border-radius: 3px;
    padding: 1px 5px;
    outline: none;
    width: 110px;
    letter-spacing: 0;
    text-transform: none;
    font-weight: normal;
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

  /* Phase 16: token budget bar — shown only when >50% of soft budget used */
  #token-bar {
    height: 2px;
    width: 100%;
    display: none;
    background: var(--vscode-sideBar-background, transparent);
    flex-shrink: 0;
  }
  #token-bar-fill {
    height: 100%;
    max-width: 100%;
    background: var(--vscode-notificationsWarningIcon-foreground, #cca700);
    transition: width 0.4s ease;
  }
  #token-bar.critical #token-bar-fill {
    background: var(--vscode-notificationsErrorIcon-foreground, #f44747);
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
    transition: background 0.1s, color 0.1s, opacity 0.15s;
    padding: 0;
  }
  .hdr-btn:hover {
    background: var(--vscode-toolbar-hoverBackground, rgba(128,128,128,0.15));
    color: var(--vscode-editor-foreground);
  }
  .hdr-btn:disabled { opacity: 0.35; cursor: not-allowed; }

  @keyframes spin { to { transform: rotate(360deg); } }
  .spin-anim { display: inline-block; animation: spin 0.7s linear infinite; }

  /* ── Sessions view header ── */
  #sessions-header {
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
  #back-btn {
    display: flex;
    align-items: center;
    justify-content: center;
    background: none;
    border: 1px solid transparent;
    border-radius: 5px;
    cursor: pointer;
    color: var(--vscode-descriptionForeground);
    font-size: 14px;
    font-weight: normal;
    width: 22px;
    height: 20px;
    flex-shrink: 0;
    transition: background 0.1s, color 0.1s;
    padding: 0;
    text-transform: none;
    letter-spacing: 0;
  }
  #back-btn:hover {
    background: var(--vscode-toolbar-hoverBackground, rgba(128,128,128,0.15));
    color: var(--vscode-editor-foreground);
  }
  #sessions-header-right {
    margin-left: auto;
    position: relative;
    flex-shrink: 0;
  }
  #new-sess-dropdown-btn {
    display: flex;
    align-items: center;
    gap: 3px;
    background: none;
    border: 1px solid var(--vscode-panel-border, rgba(128,128,128,0.4));
    border-radius: 5px;
    cursor: pointer;
    color: var(--vscode-descriptionForeground);
    font-size: 11px;
    font-weight: normal;
    text-transform: none;
    letter-spacing: 0;
    padding: 2px 7px;
    height: 22px;
    transition: background 0.1s, color 0.1s;
  }
  #new-sess-dropdown-btn:hover {
    background: var(--vscode-toolbar-hoverBackground, rgba(128,128,128,0.15));
    color: var(--vscode-editor-foreground);
  }
  #new-sess-dropdown {
    display: none;
    position: absolute;
    top: calc(100% + 4px);
    right: 0;
    background: var(--vscode-editorWidget-background, var(--vscode-editor-background));
    border: 1px solid var(--vscode-editorWidget-border, var(--vscode-panel-border));
    border-radius: 7px;
    padding: 4px;
    min-width: 160px;
    box-shadow: 0 4px 16px rgba(0,0,0,0.3);
    z-index: 200;
  }
  #new-sess-dropdown.open { display: block; }
  .ns-opt {
    padding: 7px 10px;
    border-radius: 5px;
    cursor: pointer;
    font-size: 12px;
    font-weight: normal;
    text-transform: none;
    letter-spacing: 0;
    color: var(--vscode-editor-foreground);
  }
  .ns-opt:hover { background: var(--vscode-list-hoverBackground); }

  /* ── Sessions list ── */
  #sessions-list-container {
    flex: 1;
    overflow-y: auto;
    padding: 4px 0;
    min-height: 0;
  }
  .session-group-label {
    padding: 8px 12px 3px;
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.07em;
    color: var(--vscode-descriptionForeground);
    opacity: 0.55;
    font-weight: 600;
  }
  .session-item {
    padding: 6px 12px 6px 14px;
    cursor: pointer;
    border-left: 2px solid transparent;
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .session-item:hover { background: var(--vscode-list-hoverBackground); }
  .session-item.active {
    border-left-color: #4ec9b0;
    background: rgba(78,201,176,0.08);
  }
  .session-item-info {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 1px;
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
  .session-delete-btn {
    display: none;
    background: none;
    border: none;
    cursor: pointer;
    color: var(--vscode-descriptionForeground);
    font-size: 13px;
    line-height: 1;
    padding: 2px 4px;
    border-radius: 3px;
    flex-shrink: 0;
    transition: color 0.1s, background 0.1s;
  }
  .session-item:hover .session-delete-btn { display: flex; align-items: center; }
  .session-delete-btn:hover { color: #f48771; background: rgba(244,135,113,0.1); }

  /* ── Past Jobs section ── */
  #past-jobs-section {
    flex-shrink: 0;
    border-top: 1px solid var(--vscode-panel-border, rgba(128,128,128,0.2));
  }
  #past-jobs-toggle {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 6px 12px;
    cursor: pointer;
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.07em;
    font-weight: 600;
    color: var(--vscode-descriptionForeground);
    opacity: 0.7;
    user-select: none;
  }
  #past-jobs-toggle:hover { opacity: 1; background: var(--vscode-list-hoverBackground); }
  #past-jobs-chevron { font-size: 9px; }
  #past-jobs-list { max-height: 160px; overflow-y: auto; }
  .past-job-item {
    display: flex;
    align-items: flex-start;
    gap: 8px;
    padding: 5px 12px 5px 14px;
    font-size: 11px;
  }
  .pj-icon { flex-shrink: 0; font-size: 11px; line-height: 1.4; }
  .pj-info { min-width: 0; }
  .pj-task {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-size: 11px;
  }
  .pj-meta { font-size: 10px; opacity: 0.45; margin-top: 1px; }

  /* ── Sessions search ── */
  #sessions-search-wrap {
    padding: 6px 10px;
    border-bottom: 1px solid var(--vscode-panel-border, rgba(128,128,128,0.2));
    flex-shrink: 0;
  }
  #sessions-search {
    width: 100%;
    background: var(--vscode-input-background);
    color: var(--vscode-input-foreground);
    border: 1px solid var(--vscode-input-border, rgba(128,128,128,0.35));
    border-radius: 5px;
    padding: 4px 8px;
    font-size: 11px;
    font-family: var(--vscode-font-family);
    outline: none;
    transition: border-color 0.15s;
  }
  #sessions-search:focus { border-color: var(--vscode-focusBorder); }
  #sessions-search::placeholder { color: var(--vscode-input-placeholderForeground); }

  /* ── Messages area ── */
  #messages-wrap {
    flex: 1;
    min-height: 0;
    position: relative;
    display: flex;
    flex-direction: column;
  }

  #messages {
    flex: 1;
    overflow-y: auto;
    padding: 12px 12px 24px;
    display: flex;
    flex-direction: column;
    gap: 10px;
    min-height: 0;
  }

  /* ── Jump-to-bottom button ── */
  #jump-btn {
    display: none;
    position: absolute;
    bottom: 8px;
    right: 12px;
    width: 26px;
    height: 26px;
    border-radius: 50%;
    background: var(--vscode-button-background);
    color: var(--vscode-button-foreground);
    border: none;
    cursor: pointer;
    font-size: 14px;
    align-items: center;
    justify-content: center;
    box-shadow: 0 2px 8px rgba(0,0,0,0.3);
    transition: opacity 0.15s;
    z-index: 10;
  }
  #jump-btn:hover { opacity: 0.8; }

  .msg {
    max-width: 100%;
    padding: 4px 10px 6px;
    border-radius: 6px;
    word-break: break-word;
    line-height: 1.5;
  }
  .msg-user {
    background: var(--vscode-inputOption-activeBackground, rgba(78,201,176,0.08));
    border-left: 3px solid var(--vscode-focusBorder, #4ec9b0);
    align-self: flex-end;
    white-space: pre-wrap;
    padding: 8px 10px;
    font-size: 13px;
  }
  .msg-jarvis {
    background: none;
    border-left: 2px solid rgba(78,201,176,0.4);
    padding-left: 12px;
    padding-top: 2px;
    padding-bottom: 2px;
  }
  .msg-error {
    background: var(--vscode-inputValidation-errorBackground);
    border-left: 3px solid var(--vscode-inputValidation-errorBorder);
    white-space: pre-wrap;
    padding: 8px 10px;
  }
  .msg-system {
    color: var(--vscode-descriptionForeground);
    font-size: 11px;
    text-align: center;
    padding: 4px;
  }

  /* ── Markdown rendered content ── */
  .msg-jarvis .md-p   { margin: 3px 0 5px; font-size: 13px; }
  .msg-jarvis .md-h   { font-weight: 700; margin: 10px 0 4px; color: var(--vscode-editor-foreground); }
  .msg-jarvis h1.md-h { font-size: 15px; }
  .msg-jarvis h2.md-h { font-size: 14px; }
  .msg-jarvis h3.md-h { font-size: 13px; }
  .msg-jarvis .md-ul, .msg-jarvis .md-ol { padding-left: 22px; margin: 4px 0 6px; font-size: 13px; }
  .msg-jarvis .md-ul li, .msg-jarvis .md-ol li { margin: 2px 0; }
  .msg-jarvis .md-gap { height: 6px; }
  .msg-jarvis .md-hr  { border: none; border-top: 1px solid rgba(128,128,128,0.2); margin: 8px 0; }
  .msg-jarvis .md-link { color: #4ec9b0; text-decoration: underline; cursor: default; }
  .md-icode {
    font-family: var(--vscode-editor-font-family, monospace);
    font-size: 11.5px;
    background: rgba(128,128,128,0.18);
    padding: 1px 5px;
    border-radius: 3px;
    color: var(--vscode-editor-foreground);
  }

  /* ── Code block (fenced) ── */
  .md-block {
    margin: 6px 0 8px;
    border-radius: 6px;
    overflow: hidden;
    border: 1px solid rgba(128,128,128,0.2);
    font-size: 12px;
  }
  .md-block-hdr {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 4px 10px;
    background: rgba(0,0,0,0.3);
    border-bottom: 1px solid rgba(128,128,128,0.15);
  }
  .md-lang {
    font-family: var(--vscode-editor-font-family, monospace);
    font-size: 10.5px;
    color: var(--vscode-descriptionForeground);
    text-transform: lowercase;
    letter-spacing: 0.03em;
  }
  .md-block-btns { display: flex; gap: 5px; }
  .md-copy-btn, .apply-btn {
    padding: 2px 8px;
    background: none;
    border: 1px solid rgba(128,128,128,0.35);
    border-radius: 3px;
    color: var(--vscode-descriptionForeground);
    cursor: pointer;
    font-size: 10.5px;
    transition: background 0.1s;
  }
  .md-copy-btn:hover, .apply-btn:hover { background: rgba(128,128,128,0.15); }
  .apply-btn { color: #4ec9b0; border-color: rgba(78,201,176,0.4); }
  .md-pre {
    margin: 0;
    padding: 10px 12px;
    background: var(--vscode-terminal-background, #1e1e1e);
    overflow-x: auto;
    font-family: var(--vscode-editor-font-family, monospace);
    font-size: 12px;
    line-height: 1.55;
    color: var(--vscode-terminal-foreground, #d4d4d4);
  }
  .md-pre code { display: block; white-space: pre; }

  /* ── Tool card (file write) ── */
  .tool-card {
    border: 1px solid rgba(128,128,128,0.2);
    border-left: 3px solid rgba(128,128,128,0.35);
    border-radius: 5px;
    overflow: hidden;
    margin: 2px 0;
  }
  .tool-card-hdr {
    display: flex;
    align-items: center;
    gap: 7px;
    padding: 6px 10px;
    background: rgba(0,0,0,0.2);
    font-size: 11.5px;
  }
  .tool-icon { font-size: 13px; flex-shrink: 0; }
  .tool-label { font-weight: 600; color: var(--vscode-descriptionForeground); flex-shrink: 0; }
  .tool-path {
    font-family: var(--vscode-editor-font-family, monospace);
    font-size: 11px;
    opacity: 0.75;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    flex: 1;
  }
  .tool-open-btn {
    padding: 2px 8px;
    background: none;
    border: 1px solid rgba(128,128,128,0.35);
    border-radius: 3px;
    color: var(--vscode-descriptionForeground);
    cursor: pointer;
    font-size: 10.5px;
    flex-shrink: 0;
    transition: background 0.1s;
  }
  .tool-open-btn:hover { background: rgba(128,128,128,0.12); }

  /* ── Thinking indicator → token summary ── */
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
  .ts-dot { color: #4ec9b0; font-size: 8px; flex-shrink: 0; }

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

  /* ── Terminal command card ── */
  .cmd-card {
    border: 1px solid rgba(78,201,176,0.35);
    border-left: 3px solid #4ec9b0;
    border-radius: 6px;
    background: var(--vscode-editor-inactiveSelectionBackground, rgba(30,30,30,0.6));
    font-size: 12px;
    margin: 2px 0;
  }

  /* ── Phase 12: Agent panel ── */
  .agent-panel {
    border: 1px solid rgba(100,150,255,0.35);
    border-left: 3px solid #569cd6;
    border-radius: 6px;
    background: var(--vscode-editor-inactiveSelectionBackground, rgba(20,30,50,0.6));
    font-size: 12px;
    margin: 6px 0;
    overflow: hidden;
  }
  .agent-panel-header {
    padding: 7px 12px;
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 11px;
    font-weight: 600;
    color: #569cd6;
    border-bottom: 1px solid rgba(100,150,255,0.2);
  }
  .agent-rows { padding: 4px 0; }
  .ag-row {
    display: flex;
    align-items: flex-start;
    flex-wrap: wrap;
    gap: 4px;
    padding: 4px 12px;
    font-size: 11px;
    border-bottom: 1px solid rgba(128,128,128,0.08);
  }
  .ag-row:last-child { border-bottom: none; }
  .ag-icon { flex-shrink: 0; font-size: 12px; min-width: 14px; }
  .ag-id   { font-weight: 600; min-width: 80px; flex-shrink: 0; }
  .ag-task { flex: 1; opacity: 0.8; }
  .ag-deps { font-size: 10px; opacity: 0.5; font-style: italic; }
  .ag-time { font-size: 10px; opacity: 0.5; margin-left: auto; }
  .ag-error {
    width: 100%; margin-top: 3px; padding: 4px 6px;
    background: rgba(244,135,113,0.1); border-radius: 3px;
    color: #f48771; font-size: 10px; word-break: break-all;
  }
  .ag-files { width: 100%; display: flex; gap: 4px; flex-wrap: wrap; margin-top: 3px; }
  .ag-file {
    font-size: 10px; padding: 1px 5px; border-radius: 3px; cursor: pointer;
    transition: opacity 0.15s;
  }
  .ag-file:hover { opacity: 0.7; }
  .ag-created  { background: rgba(78,201,176,0.15); color: #4ec9b0; }
  .ag-modified { background: rgba(206,145,120,0.15); color: #ce9178; }

  /* Phase 15: notification banners */
  #notification-bar { display: flex; flex-direction: column; gap: 4px; padding: 0 8px; }
  .notif-banner {
    display: flex; align-items: flex-start; gap: 8px;
    padding: 7px 10px; border-radius: 5px; font-size: 11px; line-height: 1.4;
    border-left: 3px solid;
  }
  .notif-info    { background: rgba(86,156,214,0.12); border-color: #569cd6; color: var(--vscode-foreground); }
  .notif-warning { background: rgba(220,160,60,0.12); border-color: #dca03c; color: var(--vscode-foreground); }
  .notif-icon  { flex-shrink: 0; font-size: 13px; }
  .notif-text  { flex: 1; }
  .notif-close {
    flex-shrink: 0; background: none; border: none; cursor: pointer;
    opacity: 0.5; font-size: 13px; line-height: 1; color: inherit; padding: 0;
  }
  .notif-close:hover { opacity: 1; }

  /* Phase 13: rating prompt */
  .agent-rate-prompt {
    padding: 6px 12px;
    font-size: 11px;
    opacity: 0.65;
    border-top: 1px solid rgba(128,128,128,0.15);
    font-style: italic;
  }

  .ag-running .ag-icon { color: #4ec9b0; animation: spin 1.4s linear infinite; }
  .ag-success .ag-icon { color: #4ec9b0; }
  .ag-failed  .ag-icon { color: #f48771; }
  .ag-skip    .ag-icon { color: #808080; }
  .ag-waiting .ag-icon { color: #808080; }

  .cmd-card-header {
    padding: 8px 12px 0 12px;
    display: flex;
    align-items: center;
    gap: 7px;
  }
  .cmd-card-icon { font-size: 13px; flex-shrink: 0; line-height: 1; }
  .cmd-card-label {
    font-weight: 600;
    font-size: 11px;
    color: #4ec9b0;
    letter-spacing: 0.03em;
    text-transform: uppercase;
    flex-shrink: 0;
  }
  .cmd-card-body { padding: 6px 12px 10px 12px; }
  .cmd-card-code {
    display: block;
    font-family: var(--vscode-editor-font-family, monospace);
    font-size: 12.5px;
    color: var(--vscode-editor-foreground);
    background: var(--vscode-terminal-background, rgba(0,0,0,0.3));
    padding: 6px 10px;
    border-radius: 4px;
    word-break: break-all;
    margin-bottom: 6px;
    border: 1px solid rgba(128,128,128,0.15);
  }
  .cmd-card-reason {
    font-size: 11px;
    color: var(--vscode-descriptionForeground);
    margin-bottom: 8px;
    line-height: 1.4;
  }
  .cmd-card-actions { display: flex; gap: 6px; align-items: center; }
  .cmd-run-btn {
    padding: 4px 14px;
    background: #4ec9b0;
    color: #1e1e1e;
    border: none;
    border-radius: 4px;
    cursor: pointer;
    font-size: 11.5px;
    font-weight: 600;
    letter-spacing: 0.02em;
    transition: opacity 0.1s;
  }
  .cmd-run-btn:hover { opacity: 0.85; }
  .cmd-run-btn:disabled { opacity: 0.45; cursor: not-allowed; }
  .cmd-skip-btn {
    padding: 4px 12px;
    background: none;
    color: var(--vscode-descriptionForeground);
    border: 1px solid rgba(128,128,128,0.4);
    border-radius: 4px;
    cursor: pointer;
    font-size: 11.5px;
    transition: background 0.1s;
  }
  .cmd-skip-btn:hover { background: rgba(128,128,128,0.12); }
  .cmd-kill-btn {
    padding: 4px 12px;
    background: none;
    color: #f48771;
    border: 1px solid rgba(244,135,113,0.45);
    border-radius: 4px;
    cursor: pointer;
    font-size: 11.5px;
    transition: background 0.1s;
  }
  .cmd-kill-btn:hover { background: rgba(244,135,113,0.1); }
  .cmd-kill-btn:disabled { opacity: 0.4; cursor: not-allowed; }
  .cmd-status {
    font-size: 11px;
    font-weight: 600;
    display: flex;
    align-items: center;
    gap: 5px;
  }
  .cmd-output {
    margin-top: 8px;
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
  .cmd-desc { font-size: 10px; color: var(--vscode-descriptionForeground); }

  /* ── Input wrapper ── */
  #input-wrapper {
    border: 1px solid var(--vscode-input-border, rgba(128,128,128,0.4));
    border-radius: 10px;
    background: var(--vscode-input-background);
    overflow: hidden;
    transition: border-color 0.15s;
  }
  #input-wrapper:focus-within { border-color: var(--vscode-focusBorder); }

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

<!-- ===== CHAT VIEW ===== -->
<div id="chat-view">

  <div id="header">
    <div id="status-dot" title="Click to reconnect"></div>
    <span>Jarvis</span>
    <span id="workspace-name"></span>
    <span id="session-name"></span>
    <div id="header-right">
      <span id="session-tokens"></span>
      <button class="hdr-btn" id="new-session-btn" title="New project session">+</button>
      <button class="hdr-btn" id="history-btn" title="Sessions">&#x2630;</button>
    </div>
  </div>

  <!-- Phase 15: notification banners -->
  <div id="notification-bar"></div>

  <!-- Phase 16: token budget bar -->
  <div id="token-bar"><div id="token-bar-fill" style="width:0%"></div></div>

  <div id="messages-wrap">
    <div id="messages">
      <div class="msg msg-system">
        Jarvis is connected to your local server.<br>
        Your active file and workspace are included as context.
      </div>
    </div>
    <button id="jump-btn" title="Jump to bottom">&#x2193;</button>
  </div>

  <!-- Attachment chip -->
  <div id="attachment-bar">
    <span id="attachment-chip"></span>
    <button id="clear-attach" title="Remove attachment">&#x2715;</button>
  </div>
  <input type="file" id="file-input" style="display:none" accept="*">

  <!-- Bottom input section -->
  <div id="input-outer">
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

    <div id="input-wrapper">
      <textarea id="input" rows="1" placeholder="Ask Jarvis..."></textarea>
      <div id="toolbar">
        <button class="tool-btn" id="attach-btn" title="Attach file or image">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="m21.44 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l8.57-8.57A4 4 0 1 1 18 8.84l-8.59 8.57a2 2 0 0 1-2.83-2.83l8.49-8.48"/>
          </svg>
        </button>
        <button class="tool-btn" id="cmd-btn" title="Commands">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
            <line x1="4" y1="9" x2="20" y2="9"/>
            <line x1="4" y1="15" x2="20" y2="15"/>
            <line x1="10" y1="3" x2="8" y2="21"/>
            <line x1="16" y1="3" x2="14" y2="21"/>
          </svg>
        </button>
        <button id="send" title="Send (Enter)" disabled>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
            <path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/>
          </svg>
        </button>
      </div>
    </div>
  </div>

</div><!-- end #chat-view -->

<!-- ===== SESSIONS VIEW ===== -->
<div id="sessions-view">

  <div id="sessions-header">
    <button id="back-btn" title="Back to chat">&#x2190;</button>
    <span>Sessions</span>
    <div id="sessions-header-right">
      <button id="new-sess-dropdown-btn">+ &#x25BE;</button>
      <div id="new-sess-dropdown">
        <div class="ns-opt" data-global="false">Project Session</div>
        <div class="ns-opt" data-global="true">Global Session</div>
      </div>
    </div>
  </div>

  <div id="sessions-search-wrap">
    <input id="sessions-search" type="text" placeholder="Search sessions…" autocomplete="off" spellcheck="false">
  </div>

  <div id="sessions-list-container"></div>

  <div id="past-jobs-section" style="display:none">
    <div id="past-jobs-toggle">
      <span>Past Agent Jobs</span>
      <span id="past-jobs-chevron">&#x25BC;</span>
    </div>
    <div id="past-jobs-list" style="display:none"></div>
  </div>

</div><!-- end #sessions-view -->

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
  const newSessBtn  = document.getElementById('new-session-btn');
  const histBtn     = document.getElementById('history-btn');
  const jumpBtn     = document.getElementById('jump-btn');
  const chatView    = document.getElementById('chat-view');
  const sessView    = document.getElementById('sessions-view');
  const backBtn     = document.getElementById('back-btn');
  const sessList    = document.getElementById('sessions-list-container');
  const sessSearch  = document.getElementById('sessions-search');
  const newSessDDb  = document.getElementById('new-sess-dropdown-btn');
  const newSessDd   = document.getElementById('new-sess-dropdown');

  let pendingAttachment = null;
  let isSending = false;
  let timerInterval = null;
  let sessionTotalTokens = 0;
  let sessionTotalCost = 0;
  let currentSessionId = '';
  let _currentWorkspaceRoot = '';

  function _esc(s) {
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

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

  // Phase 16: soft token budget (50K). Show bar when >50% used.
  const TOKEN_SOFT_BUDGET = 50000;
  let sessionServerTokenTotal = 0;  // cumulative from server-side session.token_total
  let sessionCompressedCount = 0;   // messages compressed so far

  // ── Update session token counter in header ──
  function updateSessionCounter() {
    const el = document.getElementById('session-tokens');
    if (el && sessionTotalTokens > 0) {
      const cost = sessionTotalCost >= 0.01
        ? '$' + sessionTotalCost.toFixed(2)
        : '$' + sessionTotalCost.toFixed(5).replace(/0+$/, '');
      let label = sessionTotalTokens.toLocaleString() + ' tok \\u2022 ' + cost;
      if (sessionCompressedCount > 0) {
        label += ' \\u2022 ' + sessionCompressedCount + ' compressed';
      }
      el.textContent = label;
    }
    _updateTokenBar();
  }

  // ── Token budget bar ──
  function _updateTokenBar() {
    const bar = document.getElementById('token-bar');
    const fill = document.getElementById('token-bar-fill');
    if (!bar || !fill) { return; }
    const used = sessionServerTokenTotal || sessionTotalTokens;
    const pct = Math.min(100, (used / TOKEN_SOFT_BUDGET) * 100);
    if (pct >= 50) {
      bar.style.display = 'block';
      fill.style.width = pct + '%';
      bar.classList.toggle('critical', pct >= 90);
    } else {
      bar.style.display = 'none';
    }
  }

  // ── Markdown renderer (no external deps) ────────────────────────────────
  function mdInline(raw) {
    const codes = [];
    let s = raw.replace(/\x60([^\x60\\n]+)\x60/g, (_, c) => { codes.push(c); return '\x01' + (codes.length - 1) + '\x01'; });
    s = s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
    s = s.replace(/\\*\\*\\*(.+?)\\*\\*\\*/g, '<strong><em>$1</em></strong>');
    s = s.replace(/\\*\\*(.+?)\\*\\*/g, '<strong>$1</strong>');
    s = s.replace(/\\*(.+?)\\*/g, '<em>$1</em>');
    s = s.replace(/\\[([^\\]]*)]\\([^)]*\\)/g, '<span class="md-link">$1</span>');
    s = s.replace(/\x01(\\d+)\x01/g, (_, i) => {
      const c = codes[+i].replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
      return '<code class="md-icode">' + c + '</code>';
    });
    return s;
  }

  function renderMarkdown(raw) {
    const out = [];
    const lines = raw.split('\\n');
    let i = 0, listType = '';
    const closeList = () => { if (listType) { out.push('</' + listType + '>'); listType = ''; } };

    while (i < lines.length) {
      const line = lines[i];

      const fence = line.match(/^\x60\x60\x60(\\w*)\\s*$/);
      if (fence) {
        closeList();
        const lang = fence[1] || '';
        const codeLines = [];
        i++;
        while (i < lines.length && !lines[i].match(/^\x60\x60\x60\\s*$/)) { codeLines.push(lines[i]); i++; }
        i++;
        const codeRaw = codeLines.join('\\n');
        const codeEsc = codeRaw.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
        const dataCode = codeRaw.replace(/&/g,'&amp;').replace(/"/g,'&quot;');
        out.push(
          '<div class="md-block" data-code="' + dataCode + '">' +
            '<div class="md-block-hdr">' +
              '<span class="md-lang">' + (lang || 'code') + '</span>' +
              '<div class="md-block-btns">' +
                '<button class="md-copy-btn" onclick="mdCopy(this)">Copy</button>' +
                '<button class="apply-btn" onclick="mdApply(this)">Apply to file</button>' +
              '</div>' +
            '</div>' +
            '<pre class="md-pre"><code>' + codeEsc + '</code></pre>' +
          '</div>'
        );
        continue;
      }

      const hm = line.match(/^(#{1,3}) (.+)/);
      if (hm) {
        closeList();
        const lvl = hm[1].length;
        out.push('<h' + lvl + ' class="md-h">' + mdInline(hm[2]) + '</h' + lvl + '>');
        i++; continue;
      }

      const ulm = line.match(/^[-*+] (.+)/);
      if (ulm) {
        if (listType !== 'ul') { closeList(); out.push('<ul class="md-ul">'); listType = 'ul'; }
        out.push('<li>' + mdInline(ulm[1]) + '</li>');
        i++; continue;
      }

      const olm = line.match(/^\\d+\\. (.+)/);
      if (olm) {
        if (listType !== 'ol') { closeList(); out.push('<ol class="md-ol">'); listType = 'ol'; }
        out.push('<li>' + mdInline(olm[1]) + '</li>');
        i++; continue;
      }

      closeList();

      if (line.match(/^---+\\s*$/)) { out.push('<div class="md-hr"></div>'); i++; continue; }
      if (!line.trim()) { out.push('<div class="md-gap"></div>'); i++; continue; }
      out.push('<p class="md-p">' + mdInline(line) + '</p>');
      i++;
    }
    closeList();
    return out.join('');
  }

  function mdCopy(btn) {
    const block = btn.closest('.md-block');
    const code = block.getAttribute('data-code')
      .replace(/&amp;/g,'&').replace(/&quot;/g,'"').replace(/&lt;/g,'<').replace(/&gt;/g,'>');
    navigator.clipboard.writeText(code).then(() => {
      const orig = btn.textContent;
      btn.textContent = 'Copied!';
      setTimeout(() => { btn.textContent = orig; }, 1500);
    }).catch(() => {});
  }

  function mdApply(btn) {
    const block = btn.closest('.md-block');
    const code = block.getAttribute('data-code')
      .replace(/&amp;/g,'&').replace(/&quot;/g,'"').replace(/&lt;/g,'<').replace(/&gt;/g,'>');
    vscode.postMessage({ command: 'applyCode', code });
  }

  // ── File write tool card ──────────────────────────────────────────────────
  function addFileCard(fullPath) {
    const name = fullPath.replace(/\\\\/g, '/').split('/').pop() || fullPath;
    const card = document.createElement('div');
    card.className = 'tool-card';
    card.innerHTML =
      '<div class="tool-card-hdr">' +
        '<span class="tool-icon">\\u270e</span>' +
        '<span class="tool-label">Wrote</span>' +
        '<span class="tool-path">' + name.replace(/&/g,'&amp;').replace(/</g,'&lt;') + '</span>' +
        '<button class="tool-open-btn">Open</button>' +
      '</div>';
    card.querySelector('.tool-open-btn').addEventListener('click', () => {
      vscode.postMessage({ command: 'openFile', path: fullPath });
    });
    messages.appendChild(card);
    scrollToBottom();
  }

  // ── Add message bubble ──
  function addMsg(text, cls) {
    const div = document.createElement('div');
    div.className = 'msg ' + cls;
    if (cls === 'msg-jarvis') {
      div.innerHTML = renderMarkdown(text);
    } else {
      div.textContent = text;
    }
    messages.appendChild(div);
    scrollToBottom();
    return div;
  }

  // ── Jump-to-bottom logic ──
  function scrollToBottom() {
    messages.scrollTop = messages.scrollHeight;
    jumpBtn.style.display = 'none';
  }

  messages.addEventListener('scroll', () => {
    const distFromBottom = messages.scrollHeight - messages.scrollTop - messages.clientHeight;
    jumpBtn.style.display = distFromBottom > 100 ? 'flex' : 'none';
  });

  jumpBtn.addEventListener('click', scrollToBottom);

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
    scrollToBottom();

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
        model + ' \\u2022 ' +
        tokenData.total.toLocaleString() + ' tokens \\u2022 ' +
        cost + ' \\u2022 ' + timeStr;

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
    if (!newSessDd.contains(e.target) && e.target !== newSessDDb) {
      newSessDd.classList.remove('open');
    }
  });

  // ── Attach button ──
  attachBtn.addEventListener('click', () => fileInput.click());
  clearAttach.addEventListener('click', hideChip);

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

  // ── Status dot click ──
  dot?.addEventListener('click', () => {
    vscode.postMessage({ command: 'checkServer' });
  });

  // ── + button (new project session) with spinner ──
  newSessBtn.addEventListener('click', () => {
    if (newSessBtn.disabled) return;
    newSessBtn.disabled = true;
    newSessBtn.innerHTML = '<span class="spin-anim">&#8635;</span>';
    vscode.postMessage({ command: 'newSession', isGlobal: false });
  });

  function _resetNewSessBtn() {
    newSessBtn.disabled = false;
    newSessBtn.textContent = '+';
  }

  // ── Inline session rename (click on session name in header) ──
  document.getElementById('session-name').addEventListener('click', () => {
    if (!currentSessionId) return;
    const nameEl = document.getElementById('session-name');
    const currentName = nameEl.textContent.trim();
    const inp = document.createElement('input');
    inp.type = 'text';
    inp.value = currentName;
    inp.className = 'session-name-input';
    inp.maxLength = 80;
    nameEl.textContent = '';
    nameEl.appendChild(inp);
    inp.focus();
    inp.select();

    let committed = false;
    function commit() {
      if (committed) return;
      committed = true;
      const newName = inp.value.trim();
      nameEl.textContent = newName || currentName;
      if (newName && newName !== currentName) {
        vscode.postMessage({ command: 'renameSession', name: newName });
      }
    }
    inp.addEventListener('blur', commit);
    inp.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') { inp.blur(); }
      if (e.key === 'Escape') { committed = true; nameEl.textContent = currentName; }
    });
  });

  // ── Sessions search / filter ──
  sessSearch.addEventListener('input', () => {
    const q = sessSearch.value.trim().toLowerCase();
    let lastGroupLabel = null;
    let groupHasVisible = false;

    sessList.childNodes.forEach(node => {
      if (!(node instanceof Element)) return;
      if (node.classList.contains('session-group-label')) {
        // Decide visibility of previous group label
        if (lastGroupLabel) {
          lastGroupLabel.style.display = groupHasVisible ? '' : 'none';
        }
        lastGroupLabel = node;
        groupHasVisible = false;
      } else if (node.classList.contains('session-item')) {
        const name = (node.querySelector('.session-item-name')?.textContent || '').toLowerCase();
        const visible = !q || name.includes(q);
        node.style.display = visible ? '' : 'none';
        if (visible) groupHasVisible = true;
      }
    });
    // Handle last group label
    if (lastGroupLabel) {
      lastGroupLabel.style.display = groupHasVisible ? '' : 'none';
    }
  });

  // ── History button → sessions view ──
  histBtn.addEventListener('click', () => {
    showSessionsView();
  });

  // ── Back button → chat view ──
  backBtn.addEventListener('click', () => {
    showChatView();
  });

  // ── Sessions view navigation ──
  function showChatView() {
    chatView.style.display = 'flex';
    sessView.style.display = 'none';
  }

  function showSessionsView() {
    chatView.style.display = 'none';
    sessView.style.display = 'flex';
    sessSearch.value = '';
    vscode.postMessage({ command: 'openSessionDrawer' });
  }

  // ── New session dropdown in sessions view ──
  newSessDDb.addEventListener('click', (e) => {
    e.stopPropagation();
    newSessDd.classList.toggle('open');
  });

  document.querySelectorAll('.ns-opt').forEach(opt => {
    opt.addEventListener('click', () => {
      const isGlobal = opt.dataset.global === 'true';
      newSessDd.classList.remove('open');
      showChatView();
      // Disable + button while creating
      newSessBtn.disabled = true;
      newSessBtn.innerHTML = '<span class="spin-anim">&#8635;</span>';
      vscode.postMessage({ command: 'newSession', isGlobal });
    });
  });

  // ── Sessions list helpers ──
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

  function populateSessionsList(data) {
    sessList.innerHTML = '';

    // Collect all sessions for cleanup check
    const toDelete = [];

    function _addSessions(sessions, wsRoot, isGlobal) {
      sessions.forEach(s => {
        const msgCount = (s.messages || []).length;
        // Auto-delete empty sessions older than 5 min (and not the active one)
        if (msgCount === 0 && s.id !== currentSessionId) {
          const updatedAt = s.updated_at || s.created_at || '';
          if (updatedAt) {
            const ageMin = (Date.now() - new Date(updatedAt + 'Z').getTime()) / 60000;
            if (ageMin > 5) {
              toDelete.push({ sessionId: s.id, workspaceRoot: wsRoot || s.workspace_root || '', isGlobal });
              return; // skip rendering
            }
          }
        }
        sessList.appendChild(createSessionItem(s, wsRoot, isGlobal));
      });
    }

    const globals = (data.global || []);
    if (globals.length > 0) {
      const lbl = document.createElement('div');
      lbl.className = 'session-group-label';
      lbl.textContent = 'Global';
      sessList.appendChild(lbl);
      _addSessions(globals, '', true);
    }

    const projects = data.projects || {};
    Object.entries(projects).forEach(([wsRoot, proj]) => {
      const lbl = document.createElement('div');
      lbl.className = 'session-group-label';
      lbl.textContent = proj.project_name || wsRoot.split(/[\\\\/]/).pop() || wsRoot;
      sessList.appendChild(lbl);
      _addSessions(proj.sessions || [], wsRoot, false);
    });

    // Remove empty session group labels that have no children
    sessList.querySelectorAll('.session-group-label').forEach(lbl => {
      let next = lbl.nextElementSibling;
      if (!next || next.classList.contains('session-group-label')) {
        lbl.remove();
      }
    });

    if (sessList.querySelectorAll('.session-item').length === 0) {
      sessList.innerHTML = '<div style="padding:16px;font-size:11px;opacity:0.5;text-align:center">No sessions yet</div>';
    }

    // Delete empty sessions silently
    toDelete.forEach(d => {
      vscode.postMessage({ command: 'deleteSession', sessionId: d.sessionId, workspaceRoot: d.workspaceRoot, isGlobal: d.isGlobal });
    });
  }

  function createSessionItem(sess, workspaceRoot, isGlobal) {
    const item = document.createElement('div');
    item.className = 'session-item' + (sess.id === currentSessionId ? ' active' : '');

    const msgCount = (sess.messages || []).length;
    const timeStr = formatRelativeTime(sess.updated_at);
    const subLine = [msgCount > 0 ? msgCount + ' msg' + (msgCount !== 1 ? 's' : '') : 'empty', timeStr].filter(Boolean).join(' \u00b7 ');

    item.innerHTML =
      '<div class="session-item-info">' +
        '<div class="session-item-name">' + escHtml(sess.name || '(untitled)') + '</div>' +
        '<div class="session-item-time">' + escHtml(subLine) + '</div>' +
      '</div>' +
      '<button class="session-delete-btn" title="Delete session">&#x1F5D1;</button>';

    // Click on item body → load session
    item.querySelector('.session-item-info').addEventListener('click', () => {
      const effectiveWsRoot = sess.workspace_root || workspaceRoot;
      vscode.postMessage({ command: 'loadSession', sessionId: sess.id, workspaceRoot: effectiveWsRoot, isGlobal });
      showChatView();
    });

    // Click on delete button → delete + remove from DOM
    item.querySelector('.session-delete-btn').addEventListener('click', (e) => {
      e.stopPropagation();
      const effectiveWsRoot = sess.workspace_root || workspaceRoot;
      vscode.postMessage({ command: 'deleteSession', sessionId: sess.id, workspaceRoot: effectiveWsRoot, isGlobal });
      // Capture prev BEFORE remove — once detached, previousElementSibling is null
      const prev = item.previousElementSibling;
      item.remove();
      // If this was the active session, clear header name
      if (sess.id === currentSessionId) {
        const nameEl = document.getElementById('session-name');
        if (nameEl) nameEl.textContent = '';
      }
      // Hide group label if no items left under it
      if (prev && prev.classList.contains('session-group-label')) {
        const next = prev.nextElementSibling;
        if (!next || next.classList.contains('session-group-label')) { prev.remove(); }
      }
    });

    return item;
  }

  // ── Past Jobs section ──
  const pastJobsSection  = document.getElementById('past-jobs-section');
  const pastJobsToggle   = document.getElementById('past-jobs-toggle');
  const pastJobsList     = document.getElementById('past-jobs-list');
  const pastJobsChevron  = document.getElementById('past-jobs-chevron');
  let pastJobsCollapsed  = true;

  if (pastJobsToggle) {
    pastJobsToggle.addEventListener('click', () => {
      pastJobsCollapsed = !pastJobsCollapsed;
      if (pastJobsList) pastJobsList.style.display = pastJobsCollapsed ? 'none' : 'block';
      if (pastJobsChevron) pastJobsChevron.textContent = pastJobsCollapsed ? '\u25BC' : '\u25B2';
    });
  }

  function populatePastJobs(jobs) {
    if (!pastJobsSection || !pastJobsList) return;
    if (!jobs || jobs.length === 0) {
      pastJobsSection.style.display = 'none';
      return;
    }
    pastJobsSection.style.display = 'block';
    pastJobsList.innerHTML = '';
    jobs.forEach(job => {
      const item = document.createElement('div');
      item.className = 'past-job-item';
      const icon = job.outcome === 'success' ? '\u2705' : '\u274C';
      const ts = job.finished_at ? new Date(job.finished_at * 1000).toISOString().slice(0, 19) : '';
      const timeStr = ts ? formatRelativeTime(ts) : '';
      const agentCount = (job.agents || []).length;
      const meta = [agentCount + ' agent' + (agentCount !== 1 ? 's' : ''), timeStr].filter(Boolean).join(' \u00b7 ');
      item.innerHTML =
        '<span class="pj-icon">' + icon + '</span>' +
        '<div class="pj-info">' +
          '<div class="pj-task">' + escHtml(job.task || '(unknown task)') + '</div>' +
          '<div class="pj-meta">' + escHtml(meta) + '</div>' +
        '</div>';
      pastJobsList.appendChild(item);
    });
  }

  function clearMessages() {
    messages.innerHTML = '';
    sessionTotalTokens = 0;
    sessionTotalCost = 0;
    sessionServerTokenTotal = 0;
    sessionCompressedCount = 0;
    document.getElementById('session-tokens').textContent = '';
    const bar = document.getElementById('token-bar');
    if (bar) { bar.style.display = 'none'; }
    jumpBtn.style.display = 'none';
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
        '<span class="cmd-card-icon">\\u2b21</span>' +
        '<span class="cmd-card-label">Run command</span>' +
      '</div>' +
      '<div class="cmd-card-body">' +
        '<code class="cmd-card-code">' + escHtml(cmd.command) + '</code>' +
        (cmd.reason ? '<div class="cmd-card-reason">' + escHtml(cmd.reason) + '</div>' : '') +
        '<div class="cmd-card-actions">' +
          '<button class="cmd-run-btn">Allow</button>' +
          '<button class="cmd-skip-btn">Deny</button>' +
        '</div>' +
      '</div>';

    const runBtn = div.querySelector('.cmd-run-btn');
    const skipBtn = div.querySelector('.cmd-skip-btn');
    const actionsDiv = div.querySelector('.cmd-card-actions');

    runBtn.addEventListener('click', () => {
      runBtn.disabled = true;
      runBtn.textContent = 'Running\\u2026';
      skipBtn.remove();
      const killBtn = document.createElement('button');
      killBtn.className = 'cmd-kill-btn';
      killBtn.textContent = 'Kill';
      killBtn.addEventListener('click', () => {
        killBtn.disabled = true;
        killBtn.textContent = 'Killing\\u2026';
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
      actionsDiv.innerHTML = '<span class="cmd-status" style="color:var(--vscode-descriptionForeground);opacity:0.55">\\u2014 denied</span>';
    });

    messages.appendChild(div);
    scrollToBottom();
  }

  // ── Handle messages from extension ──
  window.addEventListener('message', (e) => {
    const msg = e.data;
    const { command, text, tokens, filesWritten, commandsToRun,
            card_id, success, output, session, sessionsData, jobHistory, sessionName,
            rootPath, job, sessionTokenTotal, compressedCount } = msg;

    if (command === 'commandResult') {
      const card = document.getElementById(card_id);
      if (card) {
        const actions = card.querySelector('.cmd-card-actions');
        const killed = output && output.startsWith('Killed by user');
        const icon  = success ? '\\u2713' : killed ? '\\u25fc' : '\\u2717';
        const label = success ? 'Done' : killed ? 'Killed' : 'Failed';
        const color = success ? '#4ec9b0' : killed ? '#ce9178' : '#f48771';
        if (actions) {
          actions.innerHTML =
            '<span class="cmd-status" style="color:' + color + '">' +
              '<span>' + icon + '</span>' +
              '<span>' + label + '</span>' +
            '</span>';
        }
        card.style.borderLeftColor = color;
        if (output) {
          const pre = document.createElement('div');
          pre.className = 'cmd-output ' + (success ? 'success' : 'failure');
          pre.textContent = output;
          const body = card.querySelector('.cmd-card-body');
          if (body) body.appendChild(pre);
        }
        scrollToBottom();
      }
      return;
    }

    if (command === 'sessionCreated') {
      clearMessages();
      currentSessionId = session.id;
      const nameEl = document.getElementById('session-name');
      if (nameEl) nameEl.textContent = session.name || '';
      addMsg('New session started.', 'msg-system');
      _resetNewSessBtn();
      return;
    }

    if (command === 'newSessionFailed') {
      _resetNewSessBtn();
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
        addMsg('Session restored \\u2014 ' + msgs.length + ' message' + (msgs.length === 1 ? '' : 's') + ' loaded.', 'msg-system');
      }
      return;
    }

    if (command === 'sessionsListLoaded') {
      populateSessionsList(sessionsData);
      populatePastJobs(jobHistory || []);
      return;
    }

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
      // Phase 16: update token bar and compression counter from server-side data
      if (sessionTokenTotal !== undefined) {
        sessionServerTokenTotal = sessionTokenTotal;
        _updateTokenBar();
      }
      if (compressedCount !== undefined && compressedCount > 0) {
        sessionCompressedCount = compressedCount;
        updateSessionCounter();
      }
      if (filesWritten && filesWritten.length > 0) {
        filesWritten.forEach(p => addFileCard(p));
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
      console.log('[Jarvis] serverStatus received:', text);
      dot.className = text === 'online' ? 'online' : 'offline';
    } else if (command === 'workspaceInfo') {
      const el = document.getElementById('workspace-name');
      if (el) el.textContent = text ? '\\u2014 ' + text : '';
      if (rootPath) { _currentWorkspaceRoot = rootPath; }
    } else if (command === 'startAutoChat') {
      const succeeded = success;
      const label = succeeded ? 'Command done \\u2014 getting Jarvis\\u2019s take\\u2026' : 'Command failed \\u2014 notifying Jarvis\\u2026';
      addMsg(label, 'msg-system');
      isSending = true;
      sendBtn.disabled = true;
      showTyping();
    } else if (command === 'agentJobStarted') {
      hideTyping();
      createAgentPanel(msg.job_id);
    } else if (command === 'agentStatusUpdate') {
      updateAgentPanel(job);
    } else if (command === 'agentJobDone') {
      finalizeAgentPanel(job);
      isSending = false;
      sendBtn.disabled = !input.value.trim();
    }
  });

  // ── Phase 12: Agent panel helpers ──────────────────────────────────────────

  let _agentPanelId = '';

  function createAgentPanel(jobId) {
    _agentPanelId = 'agent-panel-' + jobId;
    const div = document.createElement('div');
    div.className = 'agent-panel';
    div.id = _agentPanelId;
    div.innerHTML = '<div class="agent-panel-header">' +
      '<span class="agent-panel-icon">\\u26c1</span> ' +
      '<span class="agent-panel-title">Running agents\\u2026</span>' +
      '</div>' +
      '<div class="agent-rows" id="agent-rows-' + jobId + '"></div>';
    messages.appendChild(div);
    scrollToBottom();
  }

  function _agentStatusIcon(status) {
    const icons = { pending: '\\u25cb', running: '\\u25cf', success: '\\u2713', failed: '\\u2717', skipped: '\\u2212', waiting: '\\u25cc' };
    return icons[status] || '\\u25cb';
  }
  function _agentStatusClass(status) {
    const cls = { pending: 'ag-pending', running: 'ag-running', success: 'ag-success', failed: 'ag-failed', skipped: 'ag-skip', waiting: 'ag-waiting' };
    return cls[status] || 'ag-pending';
  }
  function _elapsed(startedAt) {
    if (!startedAt) { return ''; }
    const secs = Math.round((Date.now() / 1000) - startedAt);
    return secs < 60 ? secs + 's' : Math.floor(secs / 60) + 'm ' + (secs % 60) + 's';
  }

  function updateAgentPanel(job) {
    if (!job) { return; }
    const rowsEl = document.getElementById('agent-rows-' + job.job_id);
    if (!rowsEl) { return; }
    const agents = job.agents || {};
    rowsEl.innerHTML = Object.values(agents).map(function(a) {
      const icon = _agentStatusIcon(a.status);
      const cls  = _agentStatusClass(a.status);
      const time = a.started_at ? ' \\u00b7 ' + _elapsed(a.started_at) : '';
      const deps = a.depends_on && a.depends_on.length ? '<span class="ag-deps">after: ' + a.depends_on.join(', ') + '</span>' : '';
      const files = (a.files_created.length + a.files_modified.length > 0)
        ? '<div class="ag-files">' +
            a.files_created.map(function(f) { return '<span class="ag-file ag-created" data-path="' + f + '">' + f.split(/[\\/]/).pop() + ' +</span>'; }).join('') +
            a.files_modified.map(function(f) { return '<span class="ag-file ag-modified" data-path="' + f + '">' + f.split(/[\\/]/).pop() + ' ~</span>'; }).join('') +
          '</div>'
        : '';
      return '<div class="ag-row ' + cls + '">' +
        '<span class="ag-icon">' + icon + '</span>' +
        '<span class="ag-id">' + a.id + '</span>' +
        '<span class="ag-task">' + (a.task || '').substring(0, 70) + '</span>' +
        deps +
        '<span class="ag-time">' + time + '</span>' +
        files +
        (a.error ? '<div class="ag-error">' + a.error.substring(0, 200) + '</div>' : '') +
      '</div>';
    }).join('');

    rowsEl.querySelectorAll('.ag-file').forEach(function(el) {
      el.addEventListener('click', function() {
        vscode.postMessage({ command: 'openFile', path: el.getAttribute('data-path') });
      });
    });

    scrollToBottom();
  }

  function finalizeAgentPanel(job) {
    if (!job) { return; }
    const panel = document.getElementById(_agentPanelId);
    if (!panel) { return; }
    const titleEl = panel.querySelector('.agent-panel-title');
    const s = job.summary || {};
    const ok = s.succeeded || 0;
    const fail = s.failed || 0;
    const total = s.total || 0;
    if (titleEl) {
      titleEl.textContent = ok + '/' + total + ' agents done' + (fail > 0 ? ' (' + fail + ' failed)' : '');
    }
    updateAgentPanel(job);
    if (job.rate_prompt) {
      let rateEl = panel.querySelector('.agent-rate-prompt');
      if (!rateEl) {
        rateEl = document.createElement('div');
        rateEl.className = 'agent-rate-prompt';
        panel.appendChild(rateEl);
      }
      rateEl.textContent = job.rate_prompt;
    }
  }

  // Phase 15: notification polling (every 30s)
  async function _pollNotifications() {
    try {
      const ws = encodeURIComponent(_currentWorkspaceRoot || '');
      const r = await fetch('http://localhost:3131/notifications?workspace_root=' + ws);
      if (!r.ok) { return; }
      const data = await r.json();
      _renderNotifications(data.notifications || []);
    } catch (_) {}
  }

  function _renderNotifications(notifications) {
    const bar = document.getElementById('notification-bar');
    if (!bar) { return; }
    bar.innerHTML = '';
    for (const n of notifications) {
      const cls = n.severity === 'warning' ? 'notif-warning' : 'notif-info';
      const icon = n.severity === 'warning' ? '\\u26a0' : '\\u2139';
      const div = document.createElement('div');
      div.className = 'notif-banner ' + cls;
      div.innerHTML =
        '<span class="notif-icon">' + icon + '</span>' +
        '<span class="notif-text">' + _esc(n.message) + '</span>' +
        '<button class="notif-close" data-id="' + _esc(n.id) + '" title="Dismiss">\\u2715</button>';
      bar.appendChild(div);
    }
    bar.querySelectorAll('.notif-close').forEach(btn => {
      btn.addEventListener('click', async () => {
        const id = btn.getAttribute('data-id');
        try {
          await fetch('http://localhost:3131/notifications/dismiss', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ id }),
          });
          btn.closest('.notif-banner')?.remove();
        } catch (_) {}
      });
    });
  }

  _pollNotifications();
  setInterval(_pollNotifications, 30000);

  // Check server on load
  console.log('[Jarvis] webview script started, sending checkServer');
  vscode.postMessage({ command: 'checkServer' });
  setInterval(() => vscode.postMessage({ command: 'checkServer' }), 30000);
</script>
</body>
</html>`;
    }
}
