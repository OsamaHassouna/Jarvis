# Jarvis

A personal AI development assistant built on Anthropic's Claude API.

Jarvis isn't another chat wrapper. It routes work between models, breaks complex
asks into specialized sub-agents that run in parallel via the Claude Code CLI,
and ships with a VS Code extension that injects file/selection context into
every prompt. State (preferences, project history, conversation memory) persists
across sessions and can optionally sync between machines via a private GitHub
Gist.

> Status: research project / personal tooling. Stable enough for daily use, not
> packaged for production deployment.

## What it does

- **Smart routing** — A cheap Sonnet call classifies each task as simple or
  complex. Simple = direct answer. Complex = break into agents and run.
- **Multi-agent execution** — Sub-agents run in parallel with a dependency
  graph; results flow through `tools/handoff.py`.
- **Memory** — `memory.json` stores user prefs, rules, project history,
  conversation. Optional cross-machine sync via private GitHub Gist.
- **Project awareness** — Per-project session histories, `.jarvisrules` files,
  templates (`/template use ...`) for repeat workflows.
- **Background watcher** — Detects stale tests, long-running branches, large
  uncommitted change sets; surfaces as in-app notifications.
- **VS Code extension** (`vscode-extension/`) — Sidebar webview that
  auto-starts the local server, injects active-file + selection context,
  supports vision (image analysis), and a session picker.
- **CLI** — `python main.py` for terminal use, with slash commands:
  `/memory`, `/rules`, `/project`, `/attach`, `/sync`.

## Requirements

- Python 3.10 or newer
- An Anthropic API key (https://console.anthropic.com)
- Optional: `claude` CLI on PATH if you want sub-agent file operations
- Optional (VS Code extension): Node 18+, VS Code 1.85+

## Quick start

```bash
# 1. Clone and enter the repo
git clone <your-fork-url> Jarvis
cd Jarvis

# 2. Create a virtual environment and install deps
python -m venv venv
# Windows
venv\Scripts\activate
# macOS / Linux
source venv/bin/activate

pip install anthropic python-dotenv requests

# 3. Add your API key
cp .env.example .env
# then edit .env and paste your ANTHROPIC_API_KEY

# 4. Run
python main.py
```

On Windows you can also double-click `jarvis.bat` once the venv is set up.

### Optional: VS Code extension

```bash
cd vscode-extension
npm install
npm run compile
npx @vscode/vsce package --no-dependencies --allow-missing-repository
code --install-extension jarvis-assistant-*.vsix --force
```

Then set `jarvis.serverPath` in VS Code settings to the absolute path of your
Jarvis folder. The extension auto-starts the local server (port 3131) on VS
Code launch.

## Project layout

```
main.py             CLI entry point
server.py           Local HTTP server (port 3131) used by the VS Code extension
orchestrator.py     Brain: classification, routing, agent breakdown, slash commands
memory.py           Persistent memory + Gist sync
config.py           Env vars, model names, workspace config

agents/             Agent runner + agent pool (parallel + dependency-aware)
tools/              Sessions, templates, watcher, notifications, git helpers,
                    project scanner, test runner, token tracker, Gist sync,
                    Claude Code bridge
templates/          Reusable multi-agent breakdowns
                    global/      shared across all projects
                    projects/    per-project overrides
sessions/           Runtime session/notification storage (gitignored)
tests/              Pytest suite — one file per phase
vscode-extension/   TypeScript VS Code extension (separate package)
docs/               Per-phase plan docs + roadmap
```

## Configuration

All runtime config is environment-driven. See `.env.example` for the full list.

| Variable            | Required | Purpose                                  |
|---------------------|----------|------------------------------------------|
| `ANTHROPIC_API_KEY` | Yes      | All Claude API calls                     |
| `GITHUB_TOKEN`      | No       | Push/pull `memory.json` to private Gist  |
| `GIST_ID`           | No       | Target Gist for cross-machine sync       |

Per-workspace settings (watcher thresholds, branch filters, notification TTL)
live in a `jarvis.config.json` file at the workspace root — hot-reloaded on
edit. See `config.py:load_workspace_config` for the schema and defaults.

## Tests

```bash
venv\Scripts\python -m pytest tests/ -v
```

Each `tests/test_phaseN.py` covers one development phase. The suite hits real
file I/O and process boundaries but mocks all Claude calls.

## Development notes

The `docs/` folder contains the per-phase plan documents written during
construction (phase 1 through phases 16-20) plus `roadmap.md`. Useful as a
reference for what each subsystem is responsible for and why it was built.

`some prompting ideas.md` at the repo root is a loose design doc for the
personality/clarification/autonomy models that shape Jarvis's responses.

## License

MIT — see `LICENSE`.
