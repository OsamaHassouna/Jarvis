"use strict";
// extension.ts
// Activates on VS Code startup. Auto-starts Jarvis server, shows status bar.
Object.defineProperty(exports, "__esModule", { value: true });
exports.activate = activate;
exports.deactivate = deactivate;
const vscode = require("vscode");
const cp = require("child_process");
const path = require("path");
const jarvisPanel_1 = require("./jarvisPanel");
let serverProcess;
let statusBar;
let outputChannel;
function activate(context) {
    outputChannel = vscode.window.createOutputChannel('Jarvis Server');
    // Status bar item — bottom right, always visible
    statusBar = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100);
    statusBar.command = 'jarvis.openPanel';
    setStatusBar('starting');
    statusBar.show();
    context.subscriptions.push(statusBar, outputChannel);
    // Commands
    context.subscriptions.push(vscode.commands.registerCommand('jarvis.openPanel', () => {
        jarvisPanel_1.JarvisPanel.createOrShow(context.extensionUri);
    }), vscode.commands.registerCommand('jarvis.restartServer', async () => {
        outputChannel.appendLine('--- Restarting server ---');
        serverProcess?.kill();
        serverProcess = undefined;
        setStatusBar('starting');
        await startServer(context);
    }), vscode.commands.registerCommand('jarvis.askAboutSelection', () => {
        const editor = vscode.window.activeTextEditor;
        if (!editor) {
            vscode.window.showInformationMessage('Jarvis: Open a file first.');
            return;
        }
        const sel = editor.document.getText(editor.selection);
        if (!sel.trim()) {
            vscode.window.showInformationMessage('Jarvis: Select some code first.');
            return;
        }
        jarvisPanel_1.JarvisPanel.createOrShow(context.extensionUri);
        jarvisPanel_1.JarvisPanel.prefillInput(`Explain this code:\n\`\`\`\n${sel}\n\`\`\``);
    }));
    startServer(context);
}
function deactivate() {
    serverProcess?.kill();
}
// ── Status bar helpers ───────────────────────────────────────────────────────
function setStatusBar(state) {
    switch (state) {
        case 'online':
            statusBar.text = '$(hubot) Jarvis';
            statusBar.backgroundColor = undefined;
            statusBar.tooltip = 'Jarvis is running — click to open panel';
            break;
        case 'offline':
            statusBar.text = '$(hubot) Jarvis $(warning)';
            statusBar.backgroundColor = new vscode.ThemeColor('statusBarItem.warningBackground');
            statusBar.tooltip = 'Jarvis server offline — click to open panel';
            break;
        case 'starting':
            statusBar.text = '$(hubot) Jarvis $(sync~spin)';
            statusBar.tooltip = 'Jarvis server starting...';
            break;
    }
}
// ── Server management ────────────────────────────────────────────────────────
async function startServer(context) {
    const config = vscode.workspace.getConfiguration('jarvis');
    const jarvisPath = config.get('serverPath', '').trim();
    if (!jarvisPath) {
        setStatusBar('offline');
        outputChannel.appendLine('jarvis.serverPath is not set in VS Code settings.');
        const choice = await vscode.window.showWarningMessage('Jarvis: Server path not configured. Set "jarvis.serverPath" to your Jarvis folder.', 'Open Settings');
        if (choice === 'Open Settings') {
            vscode.commands.executeCommand('workbench.action.openSettings', 'jarvis.serverPath');
        }
        return;
    }
    // Check if server is already up (e.g. user started manually)
    if (await isServerRunning()) {
        outputChannel.appendLine('Server already running on port 3131.');
        setStatusBar('online');
        return;
    }
    const isWin = process.platform === 'win32';
    const python = isWin
        ? path.join(jarvisPath, 'venv', 'Scripts', 'python.exe')
        : path.join(jarvisPath, 'venv', 'bin', 'python');
    const script = path.join(jarvisPath, 'server.py');
    outputChannel.appendLine(`Starting: ${python} ${script}`);
    serverProcess = cp.spawn(python, [script], {
        cwd: jarvisPath,
        stdio: ['ignore', 'pipe', 'pipe'],
        detached: false
    });
    serverProcess.stdout?.on('data', d => outputChannel.append(d.toString()));
    serverProcess.stderr?.on('data', d => outputChannel.append(d.toString()));
    serverProcess.on('error', err => {
        outputChannel.appendLine(`ERROR: ${err.message}`);
        setStatusBar('offline');
    });
    serverProcess.on('exit', code => {
        outputChannel.appendLine(`Server process exited (code ${code})`);
    });
    context.subscriptions.push({ dispose: () => serverProcess?.kill() });
    // Poll until server responds or give up
    const online = await waitForServer(15);
    if (online) {
        setStatusBar('online');
        outputChannel.appendLine('Server is ready.');
    }
    else {
        setStatusBar('offline');
        outputChannel.appendLine('Server did not respond in time. Check output above for errors.');
        outputChannel.show(); // Auto-open the output channel so user can see the error
    }
}
async function isServerRunning() {
    try {
        const res = await fetch('http://localhost:3131/status');
        return res.ok;
    }
    catch {
        return false;
    }
}
async function waitForServer(retries) {
    for (let i = 0; i < retries; i++) {
        if (await isServerRunning()) {
            return true;
        }
        await new Promise(r => setTimeout(r, 700));
    }
    return false;
}
//# sourceMappingURL=extension.js.map