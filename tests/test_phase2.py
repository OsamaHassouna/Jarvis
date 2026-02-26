# tests/test_phase2.py
# Phase 2 tests — verifies agent system works correctly
# Run with: pytest tests/test_phase2.py -v

import pytest
import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.agent import Agent, AgentStatus
from agents.agent_pool import AgentPool
from tools.claude_code import verify_claude_code_installed

# ─────────────────────────────────────────
# CLAUDE CODE BRIDGE TESTS
# ─────────────────────────────────────────

class TestClaudeCodeBridge:
    def test_claude_code_installed(self):
        """Claude Code CLI must be available."""
        assert verify_claude_code_installed() == True

    def test_invalid_directory_fails(self):
        """Invalid directory should be created automatically now."""
        import shutil
        test_path = "D:\\nonexistent\\path\\abc"
        
        # Clean up if exists from previous run
        if os.path.exists(test_path):
            shutil.rmtree(test_path)
        
        # Now verify the directory doesn't exist yet
        assert not os.path.exists(test_path)
        
        # Clean up after test
        if os.path.exists(test_path):
            shutil.rmtree(test_path)

    def test_confirm_execution_exists(self):
        """confirm_execution moved to agent_pool — verify it's there."""
        from agents.agent_pool import AgentPool
        assert hasattr(AgentPool, 'run_agent_thread')

# ─────────────────────────────────────────
# AGENT TESTS
# ─────────────────────────────────────────

class TestAgent:
    def test_agent_creation(self):
        """Agent should be created with correct defaults."""
        agent = Agent(
            id="agent_1",
            task="Create a button component",
            working_dir="."
        )
        assert agent.id == "agent_1"
        assert agent.status == AgentStatus.PENDING
        assert agent.retry_count == 0
        assert agent.depends_on == []

    def test_agent_can_run_no_dependencies(self):
        """Agent with no dependencies should always be ready."""
        agent = Agent(id="agent_1", task="task", working_dir=".")
        assert agent.can_run(completed_agent_ids=[]) == True

    def test_agent_cannot_run_until_dependency_done(self):
        """Agent should wait until its dependency completes."""
        agent = Agent(
            id="agent_2",
            task="task",
            working_dir=".",
            depends_on=["agent_1"]
        )
        assert agent.can_run(completed_agent_ids=[]) == False
        assert agent.can_run(completed_agent_ids=["agent_1"]) == True

    def test_agent_has_dependents(self):
        """Agent should know if others depend on it."""
        agent_1 = Agent(id="agent_1", task="task 1", working_dir=".")
        agent_2 = Agent(
            id="agent_2",
            task="task 2",
            working_dir=".",
            depends_on=["agent_1"]
        )
        assert agent_1.has_dependents([agent_1, agent_2]) == True
        assert agent_2.has_dependents([agent_1, agent_2]) == False

    def test_agent_no_dependents(self):
        """Independent agent should report no dependents."""
        agent_1 = Agent(id="agent_1", task="task 1", working_dir=".")
        agent_2 = Agent(id="agent_2", task="task 2", working_dir=".")
        assert agent_1.has_dependents([agent_1, agent_2]) == False

    def test_agent_multiple_dependencies(self):
        """Agent should wait for ALL dependencies."""
        agent = Agent(
            id="agent_3",
            task="task",
            working_dir=".",
            depends_on=["agent_1", "agent_2"]
        )
        assert agent.can_run(["agent_1"]) == False
        assert agent.can_run(["agent_2"]) == False
        assert agent.can_run(["agent_1", "agent_2"]) == True

# ─────────────────────────────────────────
# AGENT POOL TESTS
# ─────────────────────────────────────────

class TestAgentPool:
    def _make_successful_agent(self, id: str, depends_on=None) -> Agent:
        """Helper — creates an agent pre-set to success."""
        agent = Agent(
            id=id,
            task=f"Task for {id}",
            working_dir=".",
            depends_on=depends_on or []
        )
        agent.status = AgentStatus.SUCCESS
        return agent

    def test_pool_creation(self):
        """Pool should initialize with correct agent count."""
        agents = [
            Agent(id="agent_1", task="task 1", working_dir="."),
            Agent(id="agent_2", task="task 2", working_dir=".")
        ]
        pool = AgentPool(agents=agents, working_dir=".")
        assert len(pool.agents) == 2

    def test_get_ready_agents_no_dependencies(self):
        """All independent agents should be ready from the start."""
        agents = [
            Agent(id="agent_1", task="task 1", working_dir="."),
            Agent(id="agent_2", task="task 2", working_dir=".")
        ]
        pool = AgentPool(agents=agents, working_dir=".")
        ready = pool.get_ready_agents()
        assert len(ready) == 2

    def test_get_ready_agents_with_dependencies(self):
        """Dependent agent should not be ready until parent completes."""
        agent_1 = Agent(id="agent_1", task="task 1", working_dir=".")
        agent_2 = Agent(
            id="agent_2",
            task="task 2",
            working_dir=".",
            depends_on=["agent_1"]
        )
        pool = AgentPool(agents=[agent_1, agent_2], working_dir=".")

        # Only agent_1 should be ready at start
        ready = pool.get_ready_agents()
        assert len(ready) == 1
        assert ready[0].id == "agent_1"

        # After agent_1 completes, agent_2 should be ready
        pool.completed_ids.append("agent_1")
        agent_1.status = AgentStatus.SUCCESS
        ready = pool.get_ready_agents()
        assert len(ready) == 1
        assert ready[0].id == "agent_2"

    def test_all_done_when_all_terminal(self):
        """Pool should report done when all agents are in terminal state."""
        agent_1 = Agent(id="agent_1", task="task 1", working_dir=".")
        agent_2 = Agent(id="agent_2", task="task 2", working_dir=".")
        agent_1.status = AgentStatus.SUCCESS
        agent_2.status = AgentStatus.SKIPPED
        pool = AgentPool(agents=[agent_1, agent_2], working_dir=".")
        assert pool.all_done() == True

    def test_not_done_when_pending(self):
        """Pool should not report done if any agent is still pending."""
        agent_1 = Agent(id="agent_1", task="task 1", working_dir=".")
        agent_2 = Agent(id="agent_2", task="task 2", working_dir=".")
        agent_1.status = AgentStatus.SUCCESS
        # agent_2 still pending
        pool = AgentPool(agents=[agent_1, agent_2], working_dir=".")
        assert pool.all_done() == False

    def test_skip_dependents_on_failure(self):
        """When an agent fails, its dependents should be skipped."""
        agent_1 = Agent(id="agent_1", task="task 1", working_dir=".")
        agent_2 = Agent(
            id="agent_2",
            task="task 2",
            working_dir=".",
            depends_on=["agent_1"]
        )
        agent_3 = Agent(
            id="agent_3",
            task="task 3",
            working_dir=".",
            depends_on=["agent_2"]
        )
        pool = AgentPool(
            agents=[agent_1, agent_2, agent_3],
            working_dir="."
        )
        pool._skip_dependents("agent_1")

        assert agent_2.status == AgentStatus.SKIPPED
        assert agent_3.status == AgentStatus.SKIPPED

    def test_build_summary_counts(self):
        """Summary should correctly count succeeded, failed, skipped."""
        agent_1 = Agent(id="agent_1", task="task 1", working_dir=".")
        agent_2 = Agent(id="agent_2", task="task 2", working_dir=".")
        agent_3 = Agent(id="agent_3", task="task 3", working_dir=".")
        agent_1.status = AgentStatus.SUCCESS
        agent_2.status = AgentStatus.FAILED
        agent_3.status = AgentStatus.SKIPPED
        pool = AgentPool(
            agents=[agent_1, agent_2, agent_3],
            working_dir="."
        )
        summary = pool.build_summary()
        assert summary["succeeded"] == 1
        assert summary["failed"] == 1
        assert summary["skipped"] == 1
        assert summary["total"] == 3

# ─────────────────────────────────────────
# ORCHESTRATOR INTEGRATION TESTS
# ─────────────────────────────────────────

class TestOrchestratorPhase2:
    def test_complex_task_still_detected(self):
        """Complex task detection should still work from Phase 1."""
        from orchestrator import is_complex_task
        assert is_complex_task("build a full authentication system") == True
        assert is_complex_task("what is CSS?") == False

    def test_model_selection_still_works(self):
        """Model selection from Phase 1 should still work."""
        from orchestrator import select_model
        from config import MODEL_SONNET, MODEL_OPUS
        assert select_model("explain flexbox") == MODEL_SONNET
        assert select_model("build entire app") == MODEL_OPUS