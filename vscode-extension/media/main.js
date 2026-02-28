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
  let _currentWorkspaceRoot = '';   // Phase 15: tracked for notification polling

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

  // ── Markdown renderer (no external deps) ────────────────────────────────
  function mdInline(raw) {
    // 1. Extract inline code spans so they aren't processed further
    // NOTE: all regex here use \\ (double-backslash) so the template literal
    // produces a single \ in the HTML output, giving correct regex syntax.
    const codes = [];
    let s = raw.replace(/\x60([^\x60\\n]+)\x60/g, (_, c) => { codes.push(c); return '\x01' + (codes.length - 1) + '\x01'; });
    // 2. Escape remaining HTML
    s = s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
    // 3. Inline transforms
    s = s.replace(/\\*\\*\\*(.+?)\\*\\*\\*/g, '<strong><em>$1</em></strong>');
    s = s.replace(/\\*\\*(.+?)\\*\\*/g, '<strong>$1</strong>');
    s = s.replace(/\\*(.+?)\\*/g, '<em>$1</em>');
    s = s.replace(/\\[([^\\]]*)]\\([^)]*\\)/g, '<span class="md-link">$1</span>');
    // 4. Restore code spans
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

      // Fenced code block
      const fence = line.match(/^\x60\x60\x60(\\w*)\\s*$/);
      if (fence) {
        closeList();
        const lang = fence[1] || '';
        const codeLines = [];
        i++;
        while (i < lines.length && !lines[i].match(/^\x60\x60\x60\\s*$/)) { codeLines.push(lines[i]); i++; }
        i++; // skip closing fence
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

      // Headers
      const hm = line.match(/^(#{1,3}) (.+)/);
      if (hm) {
        closeList();
        const lvl = hm[1].length;
        out.push('<h' + lvl + ' class="md-h">' + mdInline(hm[2]) + '</h' + lvl + '>');
        i++; continue;
      }

      // Unordered list
      const ulm = line.match(/^[-*+] (.+)/);
      if (ulm) {
        if (listType !== 'ul') { closeList(); out.push('<ul class="md-ul">'); listType = 'ul'; }
        out.push('<li>' + mdInline(ulm[1]) + '</li>');
        i++; continue;
      }

      // Ordered list
      const olm = line.match(/^\\d+\\. (.+)/);
      if (olm) {
        if (listType !== 'ol') { closeList(); out.push('<ol class="md-ol">'); listType = 'ol'; }
        out.push('<li>' + mdInline(olm[1]) + '</li>');
        i++; continue;
      }

      closeList();

      // Horizontal rule
      if (line.match(/^---+\\s*$/)) { out.push('<div class="md-hr"></div>'); i++; continue; }

      // Blank line
      if (!line.trim()) { out.push('<div class="md-gap"></div>'); i++; continue; }

      // Paragraph
      out.push('<p class="md-p">' + mdInline(line) + '</p>');
      i++;
    }
    closeList();
    return out.join('');
  }

  // Copy code block content to clipboard
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

  // Apply code block to active file
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
        '<span class="tool-icon">✎</span>' +
        '<span class="tool-label">Wrote</span>' +
        '<span class="tool-path">' + name.replace(/&/g,'&amp;').replace(/</g,'&lt;') + '</span>' +
        '<button class="tool-open-btn">Open</button>' +
      '</div>';
    card.querySelector('.tool-open-btn').addEventListener('click', () => {
      vscode.postMessage({ command: 'openFile', path: fullPath });
    });
    messages.appendChild(card);
    messages.scrollTop = messages.scrollHeight;
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

  document.getElementById('minimize-btn')?.addEventListener('click', () => {
    vscode.postMessage({ command: 'minimize' });
  });

  // Click the status dot to manually trigger a reconnect check
  dot?.addEventListener('click', () => {
    _sessionRestored = false;
    _checkServerDirect();
    vscode.postMessage({ command: 'checkServer' });
  });

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

  function _dismissRestoreIndicator() {
    const ind = document.getElementById('restore-indicator');
    if (ind) { ind.remove(); }
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
        '<span class="cmd-card-icon">⬡</span>' +
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
      runBtn.textContent = 'Running…';
      skipBtn.remove();
      const killBtn = document.createElement('button');
      killBtn.className = 'cmd-kill-btn';
      killBtn.textContent = 'Kill';
      killBtn.addEventListener('click', () => {
        killBtn.disabled = true;
        killBtn.textContent = 'Killing…';
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
      actionsDiv.innerHTML = '<span class="cmd-status" style="color:var(--vscode-descriptionForeground);opacity:0.55">— denied</span>';
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
        const icon  = success ? '✓' : killed ? '◼' : '✕';
        const label = success ? 'Done' : killed ? 'Killed' : 'Failed';
        const color = success ? '#4ec9b0' : killed ? '#ce9178' : '#f48771';
        if (actions) {
          actions.innerHTML =
            '<span class="cmd-status" style="color:' + color + '">' +
              '<span>' + icon + '</span>' +
              '<span>' + label + '</span>' +
            '</span>';
        }
        // Update left border color to reflect result
        card.style.borderLeftColor = color;
        if (output) {
          const pre = document.createElement('div');
          pre.className = 'cmd-output ' + (success ? 'success' : 'failure');
          pre.textContent = output;
          const body = card.querySelector('.cmd-card-body');
          if (body) body.appendChild(pre);
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
      const sessionMsgs = session.messages || [];
      sessionMsgs.forEach(m => addMsg(m.content, m.role === 'user' ? 'msg-user' : 'msg-jarvis'));
      if (sessionMsgs.length > 0) {
        addMsg('Session restored \u2014 ' + sessionMsgs.length + ' message' + (sessionMsgs.length === 1 ? '' : 's') + ' loaded. Use \u2013 to minimize without closing.', 'msg-system');
      } else {
        // Empty session — show welcome message
        addMsg('Jarvis is connected to your local server.\nYour active file and workspace are included as context.', 'msg-system');
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
      // If server is offline and we still have the restore indicator, replace with welcome msg
      if (text === 'offline') {
        const ind = document.getElementById('restore-indicator');
        if (ind) { ind.id = ''; ind.style.opacity = '1'; ind.style.fontStyle = 'normal';
          ind.innerHTML = 'Jarvis server is offline. Start it with <code>python server.py</code>.'; }
      }
    } else if (command === 'workspaceInfo') {
      const el = document.getElementById('workspace-name');
      if (el) el.textContent = text ? '\u2014 ' + text : '';
      if (msg.rootPath) { _currentWorkspaceRoot = msg.rootPath; }
    } else if (command === 'startAutoChat') {
      // Extension auto-notifying Jarvis of a command result
      const succeeded = msg.success;
      const label = succeeded ? 'Command done \u2014 getting Jarvis\u2019s take\u2026' : 'Command failed \u2014 notifying Jarvis\u2026';
      addMsg(label, 'msg-system');
      isSending = true;
      sendBtn.disabled = true;
      showTyping();

    } else if (command === 'agentJobStarted') {
      // Phase 12: complex task started — show agent progress panel
      hideTyping();
      createAgentPanel(msg.job_id);

    } else if (command === 'agentStatusUpdate') {
      // Phase 12: poll result — update agent rows
      updateAgentPanel(msg.job);

    } else if (command === 'agentJobDone') {
      // Phase 12: all agents finished
      finalizeAgentPanel(msg.job);
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
      '<span class="agent-panel-icon">\u26c1</span> ' +
      '<span class="agent-panel-title">Running agents\u2026</span>' +
      '</div>' +
      '<div class="agent-rows" id="agent-rows-' + jobId + '"></div>';
    messages.appendChild(div);
    messages.scrollTop = messages.scrollHeight;
  }

  function _agentStatusIcon(status) {
    const icons = { pending: '\u25cb', running: '\u25cf', success: '\u2713', failed: '\u2717', skipped: '\u2212', waiting: '\u25cc' };
    return icons[status] || '\u25cb';
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
    const rowsEl = document.getElementById('agent-rows-' + job.job_id);
    if (!rowsEl) { return; }
    const agents = job.agents || {};
    rowsEl.innerHTML = Object.values(agents).map(function(a) {
      const icon = _agentStatusIcon(a.status);
      const cls  = _agentStatusClass(a.status);
      const time = a.started_at ? ' \u00b7 ' + _elapsed(a.started_at) : '';
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

    // Wire up file clicks to open the file in VS Code
    rowsEl.querySelectorAll('.ag-file').forEach(function(el) {
      el.addEventListener('click', function() {
        vscode.postMessage({ command: 'openFile', path: el.getAttribute('data-path') });
      });
    });

    messages.scrollTop = messages.scrollHeight;
  }

  function finalizeAgentPanel(job) {
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
    // Phase 13: show rating prompt when job is finished
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
      const icon = n.severity === 'warning' ? '⚠' : 'ℹ';
      const div = document.createElement('div');
      div.className = 'notif-banner ' + cls;
      div.innerHTML =
        '<span class="notif-icon">' + icon + '</span>' +
        '<span class="notif-text">' + _esc(n.message) + '</span>' +
        '<button class="notif-close" data-id="' + _esc(n.id) + '" title="Dismiss">✕</button>';
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

  // Direct server check from webview (no extension relay needed — CSP allows it).
  // This avoids the extension ↔ webview message chain being a failure point.
  let _sessionRestored = false;

  async function _checkServerDirect() {
    try {
      const r = await fetch('http://localhost:3131/status');
      if (r.ok) {
        dot.className = 'online';
        if (!_sessionRestored) {
          _sessionRestored = true;
          await _restoreSessionDirect();
        }
      } else {
        dot.className = 'offline';
        _showOfflineMsg();
      }
    } catch (_) {
      dot.className = 'offline';
      _showOfflineMsg();
    }
  }

  async function _restoreSessionDirect() {
    try {
      const ws = encodeURIComponent(_currentWorkspaceRoot || '');
      const r = await fetch('http://localhost:3131/sessions/active?workspace_root=' + ws);
      if (!r.ok) { _showWelcomeMsg(); return; }
      const data = await r.json();
      const session = data.session;
      if (session && session.messages && session.messages.length > 0) {
        clearMessages();
        session.messages.forEach(m => addMsg(m.content, m.role === 'user' ? 'msg-user' : 'msg-jarvis'));
        addMsg('Session restored \u2014 ' + session.messages.length + ' messages. Use \u2013 to minimize.', 'msg-system');
        const nameEl = document.getElementById('session-name');
        if (nameEl && session.name) nameEl.textContent = session.name;
      } else {
        _showWelcomeMsg();
      }
    } catch (_) {
      _showWelcomeMsg();
    }
  }

  function _showWelcomeMsg() {
    const ind = document.getElementById('restore-indicator');
    if (ind) {
      ind.id = '';
      ind.style.opacity = '1';
      ind.style.fontStyle = 'normal';
      ind.textContent = 'Jarvis is connected. Your active file and workspace are included as context.';
    }
  }

  function _showOfflineMsg() {
    const ind = document.getElementById('restore-indicator');
    if (ind) {
      ind.id = '';
      ind.style.opacity = '1';
      ind.style.fontStyle = 'normal';
      ind.textContent = 'Jarvis server is offline. Run: python server.py';
    }
  }

  // Initial check + fast retry for 30s, then 30s heartbeat
  _checkServerDirect();
  let _fastChecks = 0;
  const _fastTimer = setInterval(() => {
    _checkServerDirect();
    if (++_fastChecks >= 10) {
      clearInterval(_fastTimer);
      setInterval(_checkServerDirect, 30000);
    }
  }, 3000);

  // Still send checkServer to extension so it can do workspace info / session tracking
  vscode.postMessage({ command: 'checkServer' });