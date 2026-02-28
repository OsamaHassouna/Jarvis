"""
tools/ratings.py — Phase 13: Learning from outcomes.

Stores 1-5 task ratings in memory["task_ratings"] and injects relevant
past experience into breakdown_into_agents() so Jarvis learns over time.
"""

import re
from datetime import datetime, timezone

import memory as mem

# ── Keyword helpers ────────────────────────────────────────────────────────────

_STOPWORDS = frozenset({
    "a", "an", "the", "to", "for", "in", "of", "and", "or", "with",
    "i", "me", "my", "we", "you", "it", "is", "are", "was", "be",
    "this", "that", "some", "please", "want", "need",
    "make", "get", "set", "use", "can", "do",
})


def _keywords(text: str) -> list:
    words = re.findall(r'\b[a-z]+\b', text.lower())
    return [w for w in words if w not in _STOPWORDS and len(w) > 2]


# ── Storage ────────────────────────────────────────────────────────────────────

_MAX_RATINGS = 50


def save_rating(task_summary: str, agent_count: int, rating: int,
                workspace_root: str = "") -> None:
    """Save a task rating (1-5) to memory. Keeps the last 50 entries."""
    if not 1 <= rating <= 5:
        raise ValueError(f"Rating must be 1-5, got {rating}")
    data = mem.load_memory()
    ratings = data.setdefault("task_ratings", [])
    ratings.append({
        "task_summary": task_summary[:80],
        "agent_count": agent_count,
        "rating": rating,
        "workspace": workspace_root or "",
        "date": datetime.now(timezone.utc).strftime("%Y-%m"),
    })
    data["task_ratings"] = ratings[-_MAX_RATINGS:]
    mem.save_memory(data)


def list_ratings() -> list:
    """Return all stored ratings."""
    return mem.load_memory().get("task_ratings", [])


def clear_ratings() -> None:
    """Remove all stored ratings."""
    data = mem.load_memory()
    data["task_ratings"] = []
    mem.save_memory(data)


# ── Query ──────────────────────────────────────────────────────────────────────

def get_relevant_ratings(task_description: str, n: int = 3) -> list:
    """
    Return up to N most relevant past ratings by keyword overlap.
    Scores by Jaccard-like overlap between task keywords.
    """
    kw = set(_keywords(task_description))
    if not kw:
        return []
    scored = []
    for r in list_ratings():
        r_kw = set(_keywords(r.get("task_summary", "")))
        if not r_kw:
            continue
        overlap = len(kw & r_kw) / max(len(kw), len(r_kw))
        if overlap > 0:
            scored.append((overlap, r))
    scored.sort(key=lambda x: -x[0])
    return [r for _, r in scored[:n]]


# ── Formatting ─────────────────────────────────────────────────────────────────

def format_ratings_for_injection(ratings: list) -> str:
    """Format relevant past ratings for injection into the breakdown prompt."""
    if not ratings:
        return ""
    lines = ["Past experience with similar tasks (use to calibrate agent count):"]
    for r in ratings:
        n = r["agent_count"]
        score = r["rating"]
        summary = r["task_summary"]
        if score <= 2:
            advice = " — consider fewer or differently scoped agents next time"
        elif score >= 4:
            advice = " — this breakdown worked well"
        else:
            advice = ""
        lines.append(f'  - "{summary}" — rated {score}/5 with {n} agents{advice}')
    return "\n".join(lines)


def format_ratings_list() -> str:
    """Human-readable list of recent ratings for the /ratings command."""
    ratings = list_ratings()
    if not ratings:
        return (
            "No task ratings yet.\n\n"
            "After a complex task completes, use `/rate 1-5` to record how it went.\n"
            "Jarvis uses these ratings to plan better agent breakdowns in future tasks."
        )
    lines = [f"Task ratings ({len(ratings)} total, showing last 10):"]
    for r in reversed(ratings[-10:]):
        stars = r["rating"]
        lines.append(
            f"  [{r['date']}]  {'★' * stars}{'☆' * (5 - stars)}  "
            f"{r['agent_count']} agents  \"{r['task_summary']}\""
        )
    if len(ratings) > 10:
        lines.append(f"\n  ... and {len(ratings) - 10} older entries")
    lines.append("\nCommands:\n  `/rate 1-5`       — rate the last task\n  `/ratings clear`  — remove all ratings")
    return "\n".join(lines)
