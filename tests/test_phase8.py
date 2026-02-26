# tests/test_phase8.py
# Phase 8 tests — Global rules, project rules, /rules commands in chat
# Run with: pytest tests/test_phase8.py -v

import os
import sys
import json
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import memory as mem_module
import config

TEMP_FILE = os.path.join(os.path.dirname(__file__), "test_memory_phase8.json")
_ORIG_MEM = mem_module.MEMORY_FILE
_ORIG_CFG = config.MEMORY_FILE


class MemoryTest:
    def setup_method(self, _method):
        if os.path.exists(TEMP_FILE):
            os.remove(TEMP_FILE)
        mem_module.MEMORY_FILE = TEMP_FILE
        config.MEMORY_FILE = TEMP_FILE

    def teardown_method(self, _method):
        mem_module.MEMORY_FILE = _ORIG_MEM
        config.MEMORY_FILE = _ORIG_CFG
        if os.path.exists(TEMP_FILE):
            os.remove(TEMP_FILE)


# ─────────────────────────────────────────
# 8.1 — GLOBAL RULES (memory.py)
# ─────────────────────────────────────────

class TestGlobalRulesCRUD(MemoryTest):
    def test_empty_by_default(self):
        """Fresh memory should have no global rules."""
        assert mem_module.get_global_rules() == []

    def test_add_global_rule(self):
        """add_global_rule should persist a rule."""
        mem_module.add_global_rule("Always use standalone Angular components")
        rules = mem_module.get_global_rules()
        assert len(rules) == 1
        assert rules[0] == "Always use standalone Angular components"

    def test_add_multiple_rules(self):
        """Multiple add calls should accumulate rules."""
        mem_module.add_global_rule("Rule A")
        mem_module.add_global_rule("Rule B")
        assert len(mem_module.get_global_rules()) == 2

    def test_delete_global_rule(self):
        """delete_global_rule should remove by 0-based index and return the text."""
        mem_module.add_global_rule("Rule A")
        mem_module.add_global_rule("Rule B")
        removed = mem_module.delete_global_rule(0)
        assert removed == "Rule A"
        remaining = mem_module.get_global_rules()
        assert remaining == ["Rule B"]

    def test_delete_out_of_range_returns_none(self):
        """delete_global_rule with bad index should return None without crashing."""
        mem_module.add_global_rule("Rule A")
        assert mem_module.delete_global_rule(99) is None


class TestGlobalRulesInContext(MemoryTest):
    def test_rules_appear_in_context_summary(self):
        """Global rules should be visible in the system context sent to Claude."""
        mem_module.add_global_rule("Always respond in English")
        context = mem_module.get_context_summary()
        assert "Always respond in English" in context

    def test_no_rules_section_when_empty(self):
        """Context summary should not mention rules when there are none."""
        context = mem_module.get_context_summary()
        assert "User-defined rules" not in context


# ─────────────────────────────────────────
# 8.2 — PROJECT RULES (memory.py)
# ─────────────────────────────────────────

class TestProjectRulesCRUD(MemoryTest):
    def test_add_project_rule_auto_registers(self):
        """add_project_rule should create a project entry if it doesn't exist."""
        with tempfile.TemporaryDirectory() as d:
            mem_module.add_project_rule(d, "Use JWT auth")
            rules = mem_module.get_project_rules(d)
            assert "Use JWT auth" in rules

    def test_add_project_rule_existing_project(self):
        """add_project_rule should append to an existing project."""
        with tempfile.TemporaryDirectory() as d:
            mem_module.add_project_rule(d, "Rule 1")
            mem_module.add_project_rule(d, "Rule 2")
            rules = mem_module.get_project_rules(d)
            assert "Rule 1" in rules
            assert "Rule 2" in rules

    def test_delete_project_rule(self):
        """delete_project_rule should remove by index and return text."""
        with tempfile.TemporaryDirectory() as d:
            mem_module.add_project_rule(d, "Rule A")
            mem_module.add_project_rule(d, "Rule B")
            removed = mem_module.delete_project_rule(d, 0)
            assert removed == "Rule A"
            remaining = mem_module.get_project_rules(d)
            assert "Rule A" not in remaining

    def test_get_project_rules_reads_jarvisrules_file(self):
        """get_project_rules should include rules from .jarvisrules file."""
        with tempfile.TemporaryDirectory() as d:
            jarvisrules = os.path.join(d, ".jarvisrules")
            with open(jarvisrules, "w", encoding="utf-8") as f:
                f.write("# comment - ignored\n")
                f.write("Use kebab-case filenames\n")
                f.write("Prefer async/await\n")
            rules = mem_module.get_project_rules(d)
            assert "Use kebab-case filenames" in rules
            assert "Prefer async/await" in rules
            assert "# comment — ignored" not in rules

    def test_empty_workspace_returns_empty_list(self):
        """get_project_rules with empty string should return []."""
        assert mem_module.get_project_rules("") == []


# ─────────────────────────────────────────
# 8.3 — /rules COMMANDS (handle_rules_command)
# ─────────────────────────────────────────

class TestHandleRulesCommand(MemoryTest):
    def _cmd(self, msg, workspace=""):
        from orchestrator import handle_rules_command
        return handle_rules_command(msg, workspace)

    def test_non_rules_message_returns_none(self):
        """Normal messages should not be intercepted."""
        assert self._cmd("how do I use NgRx?") is None

    def test_list_empty_rules(self):
        """/rules on empty list should prompt user to add."""
        result = self._cmd("/rules")
        assert result is not None
        assert "No global rules" in result

    def test_add_and_list(self):
        """/rules add then /rules should show the added rule."""
        self._cmd("/rules add Use BEM for CSS")
        result = self._cmd("/rules")
        assert "Use BEM for CSS" in result

    def test_remove_rule(self):
        """/rules remove 1 should remove the first rule."""
        self._cmd("/rules add Rule A")
        self._cmd("/rules add Rule B")
        result = self._cmd("/rules remove 1")
        assert "Rule A" in result
        remaining = self._cmd("/rules")
        assert "Rule A" not in remaining
        assert "Rule B" in remaining

    def test_clear_rules(self):
        """/rules clear should remove all rules."""
        self._cmd("/rules add Rule A")
        self._cmd("/rules add Rule B")
        result = self._cmd("/rules clear")
        assert "2" in result
        assert mem_module.get_global_rules() == []

    def test_project_rules_no_workspace(self):
        """/project rules without workspace should say so."""
        result = self._cmd("/project rules")
        assert "No workspace active" in result

    def test_project_rules_add_and_list(self):
        """/project rules add then /project rules should list the rule."""
        with tempfile.TemporaryDirectory() as d:
            self._cmd("/project rules add Use JWT here", workspace=d)
            result = self._cmd("/project rules", workspace=d)
            assert "Use JWT here" in result

    def test_project_rules_clear(self):
        """/project rules clear should remove memory rules for the project."""
        with tempfile.TemporaryDirectory() as d:
            self._cmd("/project rules add Rule A", workspace=d)
            result = self._cmd("/project rules clear", workspace=d)
            assert "Cleared" in result
            assert mem_module.get_project_rules(d) == []


# ─────────────────────────────────────────
# 8.4 — PROJECT RULES INJECTED INTO CONTEXT
# ─────────────────────────────────────────

class TestProjectRulesInjection(MemoryTest):
    def test_project_rules_in_file_context(self):
        """build_message_with_file_context should inject project rules when workspace is set."""
        with tempfile.TemporaryDirectory() as d:
            mem_module.add_project_rule(d, "Always use DTOs in controllers")
            from orchestrator import build_message_with_file_context
            result = build_message_with_file_context("fix this", workspace_root=d)
            assert "Always use DTOs in controllers" in result

    def test_no_project_rules_when_no_workspace(self):
        """Without workspace_root, no project rules should be injected."""
        from orchestrator import build_message_with_file_context
        result = build_message_with_file_context("fix this", workspace_root="")
        assert "Project rules" not in result
