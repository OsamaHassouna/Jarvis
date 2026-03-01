"""
tests/test_phase13.py — Phase 13: Learning from outcomes.

Tests ratings storage, query, injection into breakdown, and /rate command.
"""
import pytest
import memory


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def isolated_memory(tmp_path):
    """Each test gets a fresh memory file with empty task_ratings."""
    orig = memory.MEMORY_FILE
    memory.MEMORY_FILE = str(tmp_path / "memory.json")
    yield
    memory.MEMORY_FILE = orig


# ── tools/ratings: save + list ─────────────────────────────────────────────────

def test_save_rating_stores_entry():
    from tools.ratings import save_rating, list_ratings
    save_rating("add dotnet endpoint", 4, 3)
    entries = list_ratings()
    assert len(entries) == 1
    assert entries[0]["task_summary"] == "add dotnet endpoint"
    assert entries[0]["agent_count"] == 4
    assert entries[0]["rating"] == 3


def test_save_rating_caps_at_100():
    from tools.ratings import save_rating, list_ratings
    for i in range(105):
        save_rating(f"task {i}", 2, 3)
    assert len(list_ratings()) == 100


def test_save_rating_rejects_out_of_range():
    from tools.ratings import save_rating
    with pytest.raises(ValueError):
        save_rating("task", 2, 0)
    with pytest.raises(ValueError):
        save_rating("task", 2, 6)


def test_clear_ratings_removes_all():
    from tools.ratings import save_rating, clear_ratings, list_ratings
    save_rating("task one", 3, 4)
    save_rating("task two", 2, 5)
    clear_ratings()
    assert list_ratings() == []


# ── tools/ratings: get_relevant_ratings ───────────────────────────────────────

def test_get_relevant_ratings_matches_keywords():
    from tools.ratings import save_rating, get_relevant_ratings
    save_rating("add dotnet endpoint", 4, 2)
    results = get_relevant_ratings("create a dotnet controller endpoint")
    assert len(results) == 1
    assert results[0]["task_summary"] == "add dotnet endpoint"


def test_get_relevant_ratings_no_match():
    from tools.ratings import save_rating, get_relevant_ratings
    save_rating("add dotnet endpoint", 4, 2)
    results = get_relevant_ratings("fix angular routing issue")
    assert results == []


def test_get_relevant_ratings_returns_top_n():
    from tools.ratings import save_rating, get_relevant_ratings
    save_rating("angular component feature", 3, 4)
    save_rating("angular service feature", 2, 3)
    save_rating("dotnet endpoint service", 4, 2)
    results = get_relevant_ratings("add angular feature service", n=2)
    assert len(results) == 2
    # Both angular results should rank above dotnet
    names = [r["task_summary"] for r in results]
    assert all("angular" in n for n in names)


# ── tools/ratings: format_ratings_for_injection ───────────────────────────────

def test_format_ratings_for_injection_low_score():
    from tools.ratings import format_ratings_for_injection
    ratings = [{"task_summary": "add endpoint", "agent_count": 4, "rating": 2}]
    result = format_ratings_for_injection(ratings)
    assert "add endpoint" in result
    assert "2/5" in result
    assert "fewer" in result


def test_format_ratings_for_injection_high_score():
    from tools.ratings import format_ratings_for_injection
    ratings = [{"task_summary": "add component", "agent_count": 3, "rating": 5}]
    result = format_ratings_for_injection(ratings)
    assert "5/5" in result
    assert "worked well" in result


def test_format_ratings_for_injection_empty():
    from tools.ratings import format_ratings_for_injection
    assert format_ratings_for_injection([]) == ""


# ── /rate command ─────────────────────────────────────────────────────────────

def test_handle_rate_command_saves_rating():
    import orchestrator
    from tools.ratings import list_ratings
    orchestrator._pending_rating = {
        "task_summary": "build login page",
        "agent_count": 3,
        "workspace": "",
    }
    result = orchestrator.handle_rating_command("/rate 4")
    assert result is not None
    assert "4/5" in result or "★★★★" in result
    entries = list_ratings()
    assert len(entries) == 1
    assert entries[0]["rating"] == 4


def test_handle_rate_command_no_pending():
    import orchestrator
    orchestrator._pending_rating = {}
    result = orchestrator.handle_rating_command("/rate 3")
    assert result is not None
    assert "No recent complex task" in result


def test_handle_rate_command_invalid_not_number():
    import orchestrator
    orchestrator._pending_rating = {"task_summary": "x", "agent_count": 2, "workspace": ""}
    result = orchestrator.handle_rating_command("/rate abc")
    assert result is not None
    assert "Invalid" in result or "invalid" in result


def test_handle_rate_command_out_of_range():
    import orchestrator
    orchestrator._pending_rating = {"task_summary": "x", "agent_count": 2, "workspace": ""}
    result = orchestrator.handle_rating_command("/rate 9")
    assert result is not None
    assert "1" in result and "5" in result


# ── /ratings command ──────────────────────────────────────────────────────────

def test_ratings_command_empty():
    import orchestrator
    result = orchestrator.handle_rating_command("/ratings")
    assert result is not None
    assert "No task ratings" in result


def test_ratings_command_lists_entries():
    from tools.ratings import save_rating
    import orchestrator
    save_rating("build feature", 3, 5)
    result = orchestrator.handle_rating_command("/ratings")
    assert "build feature" in result
    assert "5" in result


def test_ratings_clear_command():
    from tools.ratings import save_rating, list_ratings
    import orchestrator
    save_rating("some task", 2, 4)
    result = orchestrator.handle_rating_command("/ratings clear")
    assert result is not None
    assert "cleared" in result.lower()
    assert list_ratings() == []


def test_non_rating_command_returns_none():
    import orchestrator
    assert orchestrator.handle_rating_command("what time is it") is None
    assert orchestrator.handle_rating_command("/template list") is None
    assert orchestrator.handle_rating_command("/rules") is None
