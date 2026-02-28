# agents/agent_pool.py
# Manages all agents for a complex task
# Fix: Confirm ALL agents first, then execute — no overlapping prompts
# Agents execute in parallel after all confirmations are done

import threading
import time
from typing import List, Dict
from agents.agent import Agent, AgentStatus

class AgentPool:
    """
    Manages a pool of agents working on a complex task.

    Features:
    - Confirm all agents upfront one by one (no overlapping prompts)
    - Dependency graph (agents wait for their parents)
    - Parallel execution (independent agents run simultaneously)
    - Clear error reporting with live streaming
    - Smart retry (retry if dependents exist, skip if not)
    - Live updates as each agent finishes
    - Final summary when all done
    """

    def __init__(self, agents: List[Agent], working_dir: str):
        self.agents = agents
        self.working_dir = working_dir
        self.completed_ids: List[str] = []
        self.failed_ids: List[str] = []
        self.state_lock = threading.Lock()

        # Set working dir for all agents
        for agent in self.agents:
            if not agent.working_dir:
                agent.working_dir = working_dir

    def get_agent_by_id(self, agent_id: str) -> Agent:
        """Find an agent by its ID."""
        return next((a for a in self.agents if a.id == agent_id), None)

    def get_ready_agents(self) -> List[Agent]:
        """Return agents that are PENDING and whose dependencies are all completed."""
        return [
            a for a in self.agents
            if a.status == AgentStatus.PENDING
            and a.can_run(self.completed_ids)
        ]

    def all_done(self) -> bool:
        """Check if all agents are in a terminal state."""
        terminal = {
            AgentStatus.SUCCESS,
            AgentStatus.FAILED,
            AgentStatus.SKIPPED
        }
        return all(a.status in terminal for a in self.agents)

    def _skip_dependents(self, failed_agent_id: str):
        """Skip all agents that depend on a failed agent recursively."""
        for agent in self.agents:
            if failed_agent_id in agent.depends_on:
                agent.status = AgentStatus.SKIPPED
                print(f"⏭️  Agent [{agent.id}] skipped (depends on failed agent)")
                self._skip_dependents(agent.id)

    def _confirm_all_agents(self) -> bool:
        """
        Confirm all agents upfront one by one before any execution starts.
        Returns False if user cancels all agents.
        """
        print("\n📋 Please confirm each agent before execution starts:\n")

        for agent in self.agents:
            print("=" * 55)
            print(f"⚠️  AGENT CONFIRMATION [{agent.id}]")
            print("=" * 55)
            print(f"📋 Task: {agent.task[:120]}")
            print(f"📁 Dir:  {agent.working_dir}")
            deps = f"Waits for: {', '.join(agent.depends_on)}" if agent.depends_on else "Independent — runs immediately"
            print(f"🔗 Deps: {deps}")
            print("=" * 55)

            confirm = input(f"\nAllow agent [{agent.id}] to proceed? (yes/no): ").strip().lower()

            if confirm not in ["yes", "y"]:
                agent.status = AgentStatus.SKIPPED
                print(f"⏭️  Agent [{agent.id}] skipped by user")
                # Cascade skip dependents
                self._skip_dependents(agent.id)

        # Check if all agents were skipped
        all_skipped = all(a.status == AgentStatus.SKIPPED for a in self.agents)
        if all_skipped:
            print("\n🚫 All agents skipped. Task cancelled.")
            return False

        confirmed = [a for a in self.agents if a.status == AgentStatus.PENDING]
        print(f"\n✅ {len(confirmed)} agent(s) confirmed. Starting execution...\n")
        print("=" * 55)
        return True

    def handle_agent_result(self, agent: Agent):
        """
        Handle result after agent runs.
        Apply retry/skip/ask logic based on dependencies.
        """
        with self.state_lock:
            if agent.status == AgentStatus.SUCCESS:
                self.completed_ids.append(agent.id)
                return

            has_dependents = agent.has_dependents(self.agents)

            if has_dependents and agent.retry_count < agent.max_retries:
                print(f"\n⚠️  Agent [{agent.id}] failed but has dependents waiting.")
                print(f"   Error: {agent.error}")
                success = agent.retry()
                if success:
                    self.completed_ids.append(agent.id)
                else:
                    print(f"\n❌ Agent [{agent.id}] failed again after retry.")
                    print(f"   Error: {agent.error}")
                    success = agent.ask_user_for_help()
                    if success:
                        self.completed_ids.append(agent.id)
                    else:
                        self.failed_ids.append(agent.id)
                        self._skip_dependents(agent.id)
            else:
                agent.status = AgentStatus.SKIPPED
                print(f"⏭️  Agent [{agent.id}] skipped (no dependents affected)")

    def run_agent_thread(self, agent: Agent):
        """Run a single agent in a thread — no confirmation here."""
        agent.run()
        self.handle_agent_result(agent)

    def execute(self) -> Dict:
        """
        Main execution loop.
        Phase 1: Confirm ALL agents upfront one by one.
        Phase 2: Execute confirmed agents respecting dependencies in parallel.
        """
        print(f"\n🚀 Agent pool ready — {len(self.agents)} agents planned")
        print("=" * 55)

        # ── PHASE 1: Confirm all upfront ──
        if not self._confirm_all_agents():
            return self.build_summary()

        # ── PHASE 2: Execute respecting dependencies ──
        while not self.all_done():
            ready = [
                a for a in self.agents
                if a.status == AgentStatus.PENDING
                and a.can_run(self.completed_ids)
            ]

            if not ready:
                time.sleep(0.5)
                continue

            # Mark as waiting so we don't pick them up again
            for agent in ready:
                agent.status = AgentStatus.WAITING

            # Launch ready agents in parallel
            threads = []
            for agent in ready:
                t = threading.Thread(
                    target=self.run_agent_thread,
                    args=(agent,)
                )
                threads.append(t)
                t.start()

            # Wait for this batch — catch Ctrl+C for pause/resume (Phase 3.4)
            try:
                for t in threads:
                    t.join()
            except KeyboardInterrupt:
                # Wait for the current batch to finish cleanly before pausing
                print("\n\nPaused — waiting for running agents to finish...")
                for t in threads:
                    t.join()

                print("\nPaused. What would you like to do?")
                print("  1. Continue with remaining agents")
                print("  2. Skip remaining agents (keep completed work)")
                print("  3. Cancel everything")
                choice = input("  Choice (1/2/3): ").strip()

                if choice == "2":
                    for a in self.agents:
                        if a.status == AgentStatus.PENDING:
                            a.status = AgentStatus.SKIPPED
                    break
                elif choice == "3":
                    for a in self.agents:
                        if a.status in (AgentStatus.PENDING, AgentStatus.WAITING):
                            a.status = AgentStatus.FAILED
                    break
                # choice "1" → just continue the while loop

        return self.build_summary()

    # ── Phase 12: VS Code execution path ─────────────────────────────────────

    def execute_vscode(self, job_id: str) -> Dict:
        """
        VS Code variant of execute().
        - No input() calls — all agents auto-approved.
        - Each agent has an on_status_change callback that writes to the job store.
        - Runs in a background thread; caller polls /agents/status for progress.
        """
        from tools.agent_jobs import update_job_status, update_agent_status

        update_job_status(job_id, "running")

        # Wire status callbacks onto every agent
        def make_callback(agent_id: str):
            def cb(aid: str, **kwargs):
                update_agent_status(job_id, aid, **kwargs)
            return cb

        for agent in self.agents:
            agent.on_status_change = make_callback(agent.id)
            agent.vscode_mode = True   # skip input() in ask_user_for_help

        # Dependency-respecting parallel execution loop (same as execute())
        while not self.all_done():
            ready = [
                a for a in self.agents
                if a.status == AgentStatus.PENDING
                and a.can_run(self.completed_ids)
            ]

            if not ready:
                time.sleep(0.5)
                continue

            for agent in ready:
                agent.status = AgentStatus.WAITING

            threads = []
            for agent in ready:
                t = threading.Thread(
                    target=self._run_agent_vscode,
                    args=(agent,),
                    daemon=True,
                )
                threads.append(t)
                t.start()

            for t in threads:
                t.join()

        summary = self.build_summary()
        status = "done"
        update_job_status(job_id, status, summary=summary)
        return summary

    def _run_agent_vscode(self, agent: Agent) -> None:
        """Thread target for a single agent in VS Code mode."""
        agent.run()
        with self.state_lock:
            if agent.status == AgentStatus.SUCCESS:
                self.completed_ids.append(agent.id)
            else:
                # Retry once before giving up (no user prompt)
                if agent.retry_count < agent.max_retries and agent.has_dependents(self.agents):
                    success = agent.retry()
                    if success:
                        self.completed_ids.append(agent.id)
                        return
                self.failed_ids.append(agent.id)
                agent.ask_user_for_help()   # vscode_mode=True → auto-skips
                self._skip_dependents(agent.id)

    def build_summary(self) -> Dict:
        """Build a final summary of all agent results."""
        succeeded = [a for a in self.agents if a.status == AgentStatus.SUCCESS]
        failed = [a for a in self.agents if a.status == AgentStatus.FAILED]
        skipped = [a for a in self.agents if a.status == AgentStatus.SKIPPED]

        print("\n" + "=" * 55)
        print("📊 AGENT POOL SUMMARY")
        print("=" * 55)
        print(f"✅ Succeeded: {len(succeeded)}/{len(self.agents)}")
        print(f"❌ Failed:    {len(failed)}/{len(self.agents)}")
        print(f"⏭️  Skipped:   {len(skipped)}/{len(self.agents)}")
        print("=" * 55)

        for agent in succeeded:
            print(f"\n✅ [{agent.id}] {agent.task[:70]}")

        for agent in failed:
            print(f"\n❌ [{agent.id}] {agent.task[:70]}")
            print(f"   Error: {agent.error}")

        for agent in skipped:
            print(f"\n⏭️  [{agent.id}] {agent.task[:70]}")

        return {
            "total": len(self.agents),
            "succeeded": len(succeeded),
            "failed": len(failed),
            "skipped": len(skipped),
            "results": {
                a.id: {
                    "task": a.task,
                    "status": a.status.value,
                    "output": a.output,
                    "error": a.error
                }
                for a in self.agents
            }
        }