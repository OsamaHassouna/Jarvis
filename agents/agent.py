# agents/agent.py
# Represents a single agent with one focused task
# Each agent knows its task, its dependencies, and its status
# Agents only receive the context they need — not the full picture

from dataclasses import dataclass, field
from typing import Optional, List, Callable
from enum import Enum
from tools.claude_code import run_claude_code

class AgentStatus(Enum):
    PENDING = "pending"       # Waiting to start
    RUNNING = "running"       # Currently executing
    SUCCESS = "success"       # Completed successfully
    FAILED = "failed"         # Failed, may retry
    SKIPPED = "skipped"       # Skipped (no dependents failed)
    WAITING = "waiting"       # Waiting for dependencies

@dataclass
class Agent:
    """
    A single focused agent with one task.
    
    Attributes:
        id: Unique identifier (e.g. "agent_1")
        task: The specific task this agent must complete
        context: Minimal context this agent needs (not full picture)
        depends_on: List of agent IDs this agent waits for
        working_dir: Directory where this agent works
        retry_count: How many times we've retried
        max_retries: Max retries before asking user
        status: Current status
        output: Result from Claude Code
        error: Error message if failed
    """
    id: str
    task: str
    context: str = ""
    depends_on: List[str] = field(default_factory=list)
    working_dir: str = ""
    retry_count: int = 0
    max_retries: int = 1
    status: AgentStatus = AgentStatus.PENDING
    output: str = ""
    error: str = ""
    # Phase 6 flags
    auto_git: bool = False
    auto_test: bool = False
    test_command: str = ""
    # Phase 9: structured output populated after success
    files_created: List[str] = field(default_factory=list)
    files_modified: List[str] = field(default_factory=list)
    # Phase 12: optional callback for VS Code live status updates
    # Signature: (agent_id: str, **kwargs) -> None
    on_status_change: Optional[Callable] = field(default=None, repr=False, compare=False)
    # Phase 12: when True, ask_user_for_help() skips input() and auto-skips
    vscode_mode: bool = False

    def can_run(self, completed_agent_ids: List[str]) -> bool:
        """Check if all dependencies are completed."""
        return all(dep in completed_agent_ids for dep in self.depends_on)

    def has_dependents(self, all_agents: List["Agent"]) -> bool:
        """Check if any other agent depends on this one."""
        return any(self.id in agent.depends_on for agent in all_agents)

    def run(self) -> bool:
        """
        Execute this agent's task using Claude Code.
        Returns True if successful, False if failed.
        """
        self.status = AgentStatus.RUNNING
        self._notify(status="running")
        print(f"\n🤖 Agent [{self.id}] starting: {self.task[:60]}...")

        # Phase 9: inject handoff context from completed dependency agents
        from tools.handoff import build_handoff_context, extract_handoff_data, write_handoff
        handoff_context = build_handoff_context(self.depends_on, self.working_dir)
        task_prompt = self.task
        if handoff_context:
            task_prompt = f"{handoff_context}\n\n{self.task}"
            print(f"   Injecting context from {len(self.depends_on)} dependency agent(s)")

        result = run_claude_code(
            task=task_prompt,
            working_dir=self.working_dir,
            context=self.context if self.context else None,
            timeout=600  # 10 minutes per agent
        )

        if result["success"]:
            self.status = AgentStatus.SUCCESS
            self.output = result["output"]

            # Log token usage if available
            if result.get("tokens"):
                from tools.token_tracker import tracker
                tracker.log(
                    label=f"Agent [{self.id}]: {self.task[:50]}",
                    model=result["tokens"]["model"],
                    input_tokens=result["tokens"]["input"],
                    output_tokens=result["tokens"]["output"]
                )
                last = tracker.get_last()
                if last:
                    cost_str = f"${last['cost_usd']:.4f}" if last['cost_usd'] < 0.01 else f"${last['cost_usd']:.2f}"
                    print(f"   Tokens: {last['total_tokens']:,} ({last['input_tokens']:,} in / {last['output_tokens']:,} out) — {cost_str}")

            # Phase 9: extract structured result and write to handoff scratchpad
            if self.working_dir and self.output:
                handoff_data = extract_handoff_data(self.output, self.task)
                if handoff_data:
                    write_handoff(self.id, handoff_data, self.working_dir)
                    self.files_created = handoff_data.get("files_created", [])
                    self.files_modified = handoff_data.get("files_modified", [])
                    if self.files_created:
                        print(f"   Created:  {', '.join(self.files_created)}")
                    if self.files_modified:
                        print(f"   Modified: {', '.join(self.files_modified)}")

            self._notify(
                status="success",
                output=self.output[:500],
                files_created=self.files_created,
                files_modified=self.files_modified,
            )
            print(f"✅ Agent [{self.id}] completed successfully")

            # Phase 6.1: Auto git commit
            if self.auto_git and self.working_dir:
                from tools.git_tools import git_auto_commit
                ok, msg = git_auto_commit(self.working_dir, self.task)
                print(f"  Git: {msg}")

            # Phase 6.2: Auto test + fix loop
            if self.auto_test and self.test_command and self.working_dir:
                from tools.test_runner import run_tests
                ok, test_output = run_tests(self.working_dir, self.test_command)
                if ok:
                    print(f"  Tests: All passing")
                else:
                    print(f"  Tests: Failures detected — attempting auto-fix...")
                    fix_task = (
                        f"Fix the failing tests. Test output:\n{test_output[:2000]}\n\n"
                        f"Original task: {self.task}"
                    )
                    fix_result = run_claude_code(
                        task=fix_task,
                        working_dir=self.working_dir,
                        context=self.context if self.context else None,
                        timeout=600
                    )
                    if fix_result["success"]:
                        ok2, _ = run_tests(self.working_dir, self.test_command)
                        if ok2:
                            print(f"  Tests: Fixed and passing")
                        else:
                            print(f"  Tests: Still failing after auto-fix attempt")
                    else:
                        print(f"  Tests: Auto-fix run failed")

            return True
        else:
            self.status = AgentStatus.FAILED
            self.error = result["error"]
            self._notify(status="failed", error=self.error)
            print(f"❌ Agent [{self.id}] failed: {self.error}")
            return False

    def retry(self) -> bool:
        """Retry the agent task once."""
        self.retry_count += 1
        print(f"🔄 Agent [{self.id}] retrying (attempt {self.retry_count}/{self.max_retries})...")
        return self.run()

    def _notify(self, **kwargs) -> None:
        """Fire the on_status_change callback if one is set. Best-effort."""
        if self.on_status_change:
            try:
                self.on_status_change(self.id, **kwargs)
            except Exception:
                pass

    def ask_user_for_help(self) -> bool:
        """
        Ask the user for help when agent keeps failing.
        In VS Code mode (vscode_mode=True), skips input() and auto-skips.
        Returns True if user wants to retry, False to skip.
        """
        if self.vscode_mode:
            self.status = AgentStatus.SKIPPED
            self._notify(status="skipped", error=self.error)
            print(f"⏭️  Agent [{self.id}] auto-skipped (VS Code mode)")
            return False

        print(f"\n⚠️  Agent [{self.id}] needs your help!")
        print(f"Task: {self.task}")
        print(f"Error: {self.error}")
        print("\nWhat would you like to do?")
        print("1. I fixed it — retry the agent")
        print("2. Skip this agent")

        while True:
            choice = input("Your choice (1/2): ").strip()
            if choice == "1":
                return self.run()
            elif choice == "2":
                self.status = AgentStatus.SKIPPED
                print(f"⏭️  Agent [{self.id}] skipped by user")
                return False
            else:
                print("Please enter 1 or 2")