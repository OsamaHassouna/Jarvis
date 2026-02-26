 Jarvis is a personal AI development assistant built on Claude's API. Its core idea: instead of being a dumb chatbot, it intelligently routes tasks —
  answering simple questions with Sonnet (cheap/fast), and for complex tasks, breaking them into specialized sub-agents that run in parallel via the Claude
  Code CLI, with dependency awareness, git integration, and test automation.

  Current State: Phase 8 of 8 complete. 139 passing tests. The architecture is clean and layered — main.py/server.py → orchestrator.py → agent_pool.py →
  agent.py → claude_code.py → Claude Code CLI.

  ---
  What's Built (Phase 1–8)

  ┌───────────────────┬───────────────────────────────────────────────────────────────────────────────────┐
  │       Layer       │                                   What It Does                                    │
  ├───────────────────┼───────────────────────────────────────────────────────────────────────────────────┤
  │ Orchestrator      │ AI-classifies tasks (simple vs complex), routes to correct handler                │
  ├───────────────────┼───────────────────────────────────────────────────────────────────────────────────┤
  │ Agent System      │ Multi-agent task breakdown, parallel execution, dependency graph                  │
  ├───────────────────┼───────────────────────────────────────────────────────────────────────────────────┤
  │ Memory            │ Persistent user prefs, project history, rules, cross-machine sync via GitHub Gist │
  ├───────────────────┼───────────────────────────────────────────────────────────────────────────────────┤
  │ VS Code Extension │ Webview chat panel, file/selection context injection, Vision API                  │
  ├───────────────────┼───────────────────────────────────────────────────────────────────────────────────┤
  │ Tools             │ Git auto-commit, test runner, browser preview, project scanner, token tracker     │
  ├───────────────────┼───────────────────────────────────────────────────────────────────────────────────┤
  │ Rules Engine      │ Global rules + per-project .jarvisrules files, full CRUD via CLI                  │
  ├───────────────────┼───────────────────────────────────────────────────────────────────────────────────┤
  │ Intelligence      │ AI task classification, preference learning (remember: ...), daily briefings      │
  └───────────────────┴───────────────────────────────────────────────────────────────────────────────────┘

  ---
  Honest Assessment

  Strengths:
  - Clean architecture — separation of concerns is excellent
  - Threading is done right (locks, batch execution, dependency graph)
  - Graceful degradation everywhere (sync fails? continues locally. AI classify fails? falls back to keywords)
  - Token efficiency is smart — Sonnet for classification + simple tasks, Opus only when needed
  - 139 tests across all phases is a serious commitment

  Real Limitations:
  1. Agents are one-shot black boxes — they run Claude Code and return output as raw text. Jarvis can't see what files changed, only whether the agent
  succeeded. No structured result parsing.
  2. No undo/rollback — if 3 agents succeed and the 4th breaks things, there's no way to revert. Git commits happen per-agent but there's no rollback
  orchestration.
  3. VS Code is second-class — complex tasks redirect users to the terminal. The VS Code panel can't launch or monitor agents.
  4. Context window risk — get_context_summary() includes all projects + history. As memory grows over months, this system prompt will grow and eventually
  hit limits or degrade quality.
  5. No agent communication — agents share a filesystem but can't pass structured data to each other (e.g., "Agent 1 created auth.service.ts at path X —
  Agent 2, here's where it is"). Dependencies are declared but nothing is shared except files on disk.
  6. Token cost is invisible during agents — you only see total at the end, not per-agent spend mid-execution.

  ---
  Suggestions for Improvement

  These are fixes to existing things, not new phases:

  1. Agent output structured parsing — After each agent succeeds, ask Claude to extract a JSON summary: { "files_created": [], "files_modified": [],
  "summary": "" }. This gives the orchestrator visibility into what actually happened.
  2. Memory pruning — Add a max_projects cap (e.g., 20) and trim the context summary to only inject the most recently active project instead of all of them.
  3. Git-based rollback — Before any complex task, auto-capture git stash or record the HEAD SHA. On full task failure, offer to revert.
  4. Per-agent token display — Stream cost mid-execution: [Agent 2/4] login-form • completed • 1,240 tokens • $0.012.

  ---
  Ideas for Phase 9+

  Here are genuinely new directions, ordered by impact:

  Phase 9 — Agent Memory & Handoff

  Agents currently share nothing except files. Build a lightweight agent scratchpad: a JSON file written by each agent listing what it created/modified,
  which the next dependent agent reads before running. This would make multi-agent tasks dramatically more coherent — Agent 2 wouldn't have to re-discover
  what Agent 1 built.

  Phase 10 — Proactive Assistant (Background Watcher)

  A background process that watches your active projects for patterns and surfaces insights without being asked:
  - "You've run dotnet build 6 times since the last commit — want me to diagnose it?"
  - "This file hasn't been tested in 3 weeks but was modified yesterday"
  - "Your token spend this week is $4.20 — 60% was on the auth refactor"

  This transforms Jarvis from reactive to proactive.

  Phase 11 — Task Templates / Playbooks

  Let you define reusable agent blueprints for common patterns you repeat across projects:
  - "New Angular feature" → always creates component + service + spec + barrel export
  - "Add .NET endpoint" → always creates controller + DTO + service interface + unit test

  Saves you from re-describing the same breakdowns and gives agents battle-tested context.

  Phase 12 — Full VS Code Parity

  Right now VS Code is a lite viewer. Make it equal to terminal:
  - Launch complex tasks directly from VS Code (agent execution panel in sidebar)
  - Visual dependency graph showing agent status in real-time
  - Per-agent streaming output in tabs
  - One-click approve/skip per agent (instead of terminal prompts)

  Phase 13 — Learning from Outcomes

  Currently Jarvis remembers what tasks you ran but not how well the agents did it. Build a feedback loop:
  - After complex tasks: "Did this work well? (1-5 + notes)"
  - Store quality ratings per task type
  - Use low-rated patterns to refine future agent breakdowns ("last time you split auth into 4 agents and 2 failed — try 2 this time")

  Phase 14 — Multi-Project Orchestration

  For bigger workflows spanning multiple repos (e.g., backend API + frontend app + shared library), let agents run across different working directories with
   cross-project dependency awareness. Currently working_dir is one path per run.

  ---
  Bottom line: The foundation is genuinely solid. The most impactful next move is Phase 9 (agent handoff/scratchpad) — it addresses the core architectural
  gap (agent isolation) and would make every complex task work better without changing the user-facing interface at all.