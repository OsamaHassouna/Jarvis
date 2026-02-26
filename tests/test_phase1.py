# tests/test_phase1.py
# Phase 1 tests — verifies all core components work correctly
# Run with: pytest tests/test_phase1.py -v

import pytest
import json
import os
import sys

# Add parent directory to path so we can import our modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from memory import (
    load_memory,
    save_memory,
    update_memory,
    add_to_history,
    add_project,
    get_context_summary,
    DEFAULT_MEMORY
)
from config import ANTHROPIC_API_KEY, MODEL_SONNET, MODEL_OPUS, MAX_TOKENS, MEMORY_FILE
from orchestrator import is_complex_task

# ─────────────────────────────────────────
# CONFIG TESTS
# ─────────────────────────────────────────

class TestConfig:
    def test_api_key_exists(self):
        """API key must be loaded from .env"""
        assert ANTHROPIC_API_KEY is not None
        assert ANTHROPIC_API_KEY != ""

    def test_api_key_format(self):
        """API key must start with sk-ant"""
        assert ANTHROPIC_API_KEY.startswith("sk-ant")

    def test_model_set(self):
        """Both models must be defined"""
        assert MODEL_SONNET is not None
        assert MODEL_OPUS is not None
        assert len(MODEL_SONNET) > 0
        assert len(MODEL_OPUS) > 0

    def test_max_tokens_positive(self):
        """Max tokens must be a positive number"""
        assert MAX_TOKENS > 0

# ─────────────────────────────────────────
# MEMORY TESTS
# ─────────────────────────────────────────

class TestMemory:
    TEST_MEMORY_FILE = "test_memory_temp.json"

    def setup_method(self):
        """Use a separate test memory file — never touch real memory.json."""
        import memory as mem
        self._original = mem.MEMORY_FILE
        mem.MEMORY_FILE = self.TEST_MEMORY_FILE
        if os.path.exists(self.TEST_MEMORY_FILE):
            os.remove(self.TEST_MEMORY_FILE)

    def teardown_method(self):
        """Restore real memory file path and clean up test file."""
        import memory as mem
        mem.MEMORY_FILE = self._original
        if os.path.exists(self.TEST_MEMORY_FILE):
            os.remove(self.TEST_MEMORY_FILE)
            
    def test_load_memory_creates_default(self):
        """Loading memory when no file exists should create default."""
        memory = load_memory()
        assert "user" in memory
        assert "projects" in memory
        assert "history" in memory

    def test_save_and_load_memory(self):
        """Save then load should return same data."""
        test_data = DEFAULT_MEMORY.copy()
        test_data["user"]["name"] = "Osama"
        save_memory(test_data)
        loaded = load_memory()
        assert loaded["user"]["name"] == "Osama"

    def test_update_memory(self):
        """Update a specific key in memory."""
        load_memory()  # create default
        update_memory("user", {"name": "Osama", "preferences": [], "experience_level": "intermediate"})
        memory = load_memory()
        assert memory["user"]["name"] == "Osama"

    def test_add_to_history(self):
        """History should grow when messages are added."""
        load_memory()
        add_to_history("user", "Hello Jarvis")
        add_to_history("assistant", "Hello! How can I help?")
        memory = load_memory()
        assert len(memory["history"]) == 2
        assert memory["history"][0]["role"] == "user"
        assert memory["history"][1]["role"] == "assistant"

    def test_history_limit(self):
        """History should never exceed 50 messages."""
        load_memory()
        for i in range(60):
            add_to_history("user", f"message {i}")
        memory = load_memory()
        assert len(memory["history"]) <= 50

    def test_add_project(self):
        """Projects should be added to memory."""
        load_memory()
        add_project({"name": "my-angular-app", "stack": "Angular + .NET"})
        memory = load_memory()
        assert len(memory["projects"]) == 1
        assert memory["projects"][0]["name"] == "my-angular-app"

    def test_no_duplicate_projects(self):
        """Same project should not be added twice."""
        load_memory()
        add_project({"name": "my-app", "stack": "Angular"})
        add_project({"name": "my-app", "stack": "Angular"})
        memory = load_memory()
        assert len(memory["projects"]) == 1

    def test_get_context_summary(self):
        """Context summary should return a non-empty string."""
        load_memory()
        summary = get_context_summary()
        assert isinstance(summary, str)
        assert len(summary) > 0
        assert "Jarvis" in summary

# ─────────────────────────────────────────
# ORCHESTRATOR TESTS
# ─────────────────────────────────────────

class TestOrchestrator:
    def test_simple_task_detected(self):
        """Short questions should be detected as simple."""
        assert is_complex_task("what is a REST API?") == False
        assert is_complex_task("explain async/await") == False
        assert is_complex_task("fix this bug") == False

    def test_complex_task_detected(self):
        """Big tasks should be detected as complex."""
        assert is_complex_task("build a full app with Angular and .NET") == True
        assert is_complex_task("create a whole authentication system") == True
        assert is_complex_task("build me an entire ecommerce platform") == True

    def test_complex_keywords_case_insensitive(self):
        """Detection should work regardless of case."""
        assert is_complex_task("BUILD a new system") == True
        assert is_complex_task("Create Project from scratch") == True

# ─────────────────────────────────────────
# MODEL SELECTION TESTS
# ─────────────────────────────────────────

class TestModelSelection:
    def test_simple_question_uses_sonnet(self):
        """Quick questions should use Sonnet."""
        from orchestrator import select_model
        from config import MODEL_SONNET
        assert select_model("what is a REST API?") == MODEL_SONNET
        assert select_model("explain flexbox") == MODEL_SONNET

    def test_complex_task_uses_opus(self):
        """Complex dev tasks should use Opus."""
        from orchestrator import select_model
        from config import MODEL_OPUS
        assert select_model("build a full authentication system") == MODEL_OPUS
        assert select_model("design the architecture for my app") == MODEL_OPUS

    def test_default_uses_sonnet(self):
        """Unknown tasks should default to Sonnet."""
        from orchestrator import select_model
        from config import MODEL_SONNET
        assert select_model("help me with something") == MODEL_SONNET
        assert select_model("I need assistance") == MODEL_SONNET