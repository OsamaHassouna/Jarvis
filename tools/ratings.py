"""
tools/ratings.py — Phase 13: Learning from outcomes.
Phase 20: Ratings actively influence agent breakdown decisions.

Stores 1-5 task ratings in memory["task_ratings"] and injects relevant
past experience into breakdown_into_agents() so Jarvis learns over time.
"""

import re
from collections import Counter
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


# ── Role extraction ────────────────────────────────────────────────────────────

_ROLE_PATTERNS = [
    ("component", ["component", "comp", "widget", "page", "view", "modal", "dialog"]),
    ("service",   ["service", "svc", "provider", "client", "repository"]),
    ("test",      ["test", "tests", "spec", "unit", "e2e", "integration"]),
    ("api",       ["api", "endpoint", "controller", "route", "handler", "rest"]),
    ("migration", ["migration", "migrate", "schema", "database", "seed"]),
    ("guard",     ["guard", "middleware", "interceptor", "auth", "permission"]),
    ("model",     ["model", "entity", "dto", "interface", "type"]),
    ("store",     ["store", "state", "ngrx", "redux", "signal"]),
]


def extract_agent_roles(agent_defs: list) -> list[str]:
    """
    Extract a role name for each agent definition based on task keywords.
    Falls back to "general" if no pattern matches.
    """
    roles = []
    for agent in agent_defs:
        task = agent.get("task", "").lower()
        matched = "general"
        for role_name, keywords in _ROLE_PATTERNS:
            if any(kw in task for kw in keywords):
                matched = role_name
                break
        roles.append(matched)
    return roles


# ── Storage ────────────────────────────────────────────────────────────────────

_MAX_RATINGS = 100


def save_rating(task_summary: str, agent_count: int, rating: int,
                workspace_root: str = "", roles: list | None = None) -> None:
    """Save a task rating (1-5) to memory. Keeps the last 100 entries."""
    if not 1 <= rating <= 5:
        raise ValueError(f"Rating must be 1-5, got {rating}")
    data = mem.load_memory()
    ratings = data.setdefault("task_ratings", [])
    entry = {
        "task_summary": task_summary[:80],
        "agent_count": agent_count,
        "rating": rating,
        "workspace": workspace_root or "",
        "date": datetime.now(timezone.utc).strftime("%Y-%m"),
    }
    if roles:
        entry["successful_roles"] = roles
    ratings.append(entry)
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
    """
    Format relevant past ratings for injection into the breakdown prompt.
    Phase 20: adds CONSTRAINT/HINT lines and role suggestions based on patterns.
    """
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

    low_rated  = [r for r in ratings if r["rating"] <= 2]
    high_rated = [r for r in ratings if r["rating"] >= 4]

    # CONSTRAINT: ≥2 relevant tasks were rated poorly → cap agents
    if len(low_rated) >= 2:
        avg_agents = sum(r["agent_count"] for r in low_rated) / len(low_rated)
        cap = max(1, int(avg_agents) - 1)
        lines.append(
            f"\nCONSTRAINT: use at most {cap} agents for this task "
            f"(past attempts with ~{int(avg_agents)} agents were rated poorly)"
        )
    # HINT: all relevant tasks were rated highly → agents worked well
    elif high_rated and len(high_rated) == len(ratings):
        avg_agents = sum(r["agent_count"] for r in high_rated) / len(high_rated)
        avg_score  = sum(r["rating"]      for r in high_rated) / len(high_rated)
        lines.append(
            f"\nHINT: {int(round(avg_agents))} agents worked well for similar tasks "
            f"(avg rating: {avg_score:.1f}/5)"
        )

    # Role suggestions from high-rated entries
    all_roles = []
    for r in high_rated:
        all_roles.extend(r.get("successful_roles", []))
    if all_roles:
        common_roles = [role for role, _ in Counter(all_roles).most_common(3)]
        lines.append(f"Tasks like this work best with: {' + '.join(common_roles)} agents")

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
