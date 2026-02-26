"use strict";
// jarvisPanel.ts
// Phase 4/7 — VS Code Webview panel with Jarvis chat UI.
// Phase 7 adds: file/image attachment, apply-code-to-file button.
Object.defineProperty(exports, "__esModule", { value: true });
exports.JarvisPanel = void 0;
const vscode = require("vscode");
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
    constructor(panel, extensionUri) {
        this._disposables = [];
        // Tracks the last real text editor even while the webview has focus
        this._lastKnownEditor = vscode.window.activeTextEditor;
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
        }, null, this._disposables);
        // Clean up on close
        this._panel.onDidDispose(() => this.dispose(), null, this._disposables);
    }
    // ── Message handling ─────────────────────────────────────────────────────
    async _handleSend(message, attachment) {
        // Use _lastKnownEditor so we keep context even when the webview has focus
        const editor = this._lastKnownEditor ?? vscode.window.activeTextEditor;
        const fileContent = editor?.document.getText() ?? '';
        const filePath = editor?.document.fileName ?? '';
        const selection = editor?.document.getText(editor?.selection ?? new vscode.Selection(0, 0, 0, 0)) ?? '';
        // Workspace root — lets Jarvis know the project folder
        const workspaceRoot = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath ?? '';
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
                })
            });
            if (!res.ok) {
                const err = await res.json();
                this._post('error', `Server error: ${err.error}`);
                return;
            }
            const data = await res.json();
            this._post('response', data.response);
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
            this._post('serverStatus', data.status === 'running' ? 'online' : 'offline');
        }
        catch {
            this._post('serverStatus', 'offline');
        }
    }
    // Phase 7: Apply a code block to the active editor file
    async _applyCode(code) {
        const editor = vscode.window.activeTextEditor;
        if (!editor) {
            vscode.window.showWarningMessage('Jarvis: No active file to apply code to.');
            return;
        }
        await editor.edit(editBuilder => {
            const fullRange = new vscode.Range(0, 0, editor.document.lineCount - 1, editor.document.lineAt(editor.document.lineCount - 1).text.length);
            editBuilder.replace(fullRange, code);
        });
        vscode.window.showInformationMessage(`Jarvis applied code to ${editor.document.fileName.split(/[\\/]/).pop()}`);
    }
    _post(command, text) {
        this._panel.webview.postMessage({ command, text });
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

  body {
    font-family: var(--vscode-font-family);
    font-size: var(--vscode-font-size);
    background: var(--vscode-editor-background);
    color: var(--vscode-editor-foreground);
    display: flex;
    flex-direction: column;
    height: 100vh;
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

  /* ── Messages ── */
  #messages {
    flex: 1;
    overflow-y: auto;
    padding: 12px;
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

  /* ── Typing indicator ── */
  .typing {
    display: flex; gap: 4px; align-items: center; padding: 8px 10px;
  }
  .typing span {
    width: 6px; height: 6px; border-radius: 50%;
    background: var(--vscode-descriptionForeground);
    animation: bounce 1.2s ease-in-out infinite;
  }
  .typing span:nth-child(2) { animation-delay: 0.2s; }
  .typing span:nth-child(3) { animation-delay: 0.4s; }
  @keyframes bounce {
    0%, 80%, 100% { transform: translateY(0); opacity: 0.5; }
    40%           { transform: translateY(-6px); opacity: 1; }
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

  let pendingAttachment = null;
  let isSending = false;

  // ── Auto-resize textarea + toggle send button ──
  input.addEventListener('input', () => {
    input.style.height = 'auto';
    input.style.height = Math.min(input.scrollHeight, 160) + 'px';
    sendBtn.disabled = !input.value.trim() || isSending;
  });

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

  // ── Typing indicator ──
  let typingEl = null;
  function showTyping() {
    typingEl = document.createElement('div');
    typingEl.className = 'typing';
    typingEl.innerHTML = '<span></span><span></span><span></span>';
    messages.appendChild(typingEl);
    messages.scrollTop = messages.scrollHeight;
  }
  function hideTyping() {
    typingEl?.remove();
    typingEl = null;
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

  // ── Handle messages from extension ──
  window.addEventListener('message', (e) => {
    const { command, text } = e.data;
    hideTyping();
    isSending = false;
    sendBtn.disabled = !input.value.trim();

    if (command === 'response') {
      addMsg(text, 'msg-jarvis');
    } else if (command === 'error') {
      addMsg(text, 'msg-error');
    } else if (command === 'prefill') {
      input.value = text;
      input.dispatchEvent(new Event('input'));
      input.focus();
    } else if (command === 'serverStatus') {
      dot.className = text === 'online' ? 'online' : 'offline';
      dot.classList.add(text === 'online' ? 'online' : 'offline');
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