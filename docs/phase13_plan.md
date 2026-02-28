# Phase 13 — Learning from Outcomes ✅ Complete

**Status:** Complete — 18 tests passing (247 total)
**Completed:** February 2026

---

## Goal

Jarvis learns which agent breakdowns work well and which don't, so it
improves its planning over time. After each complex task, the user rates
it 1–5. Relevant past ratings are injected into future breakdowns.

---

## What Was Built

### `tools/ratings.py` (new)

Storage: `memory["task_ratings"]` — list of up to 50 entries (oldest dropped).

```python
save_rating(task_summary, agent_count, rating, workspace_root="")
list_ratings()                         # all stored ratings
clear_ratings()                        # remove all
get_relevant_ratings(task_description, n=3)   # keyword match, top N
format_ratings_for_injection(ratings)  # prompt text for breakdown
format_ratings_list()                  # human-readable for /ratings command
```

**Keyword matching** — `get_relevant_ratings()` extracts non-stopword words from both
the past rating's summary and the current task, scores by Jaccard overlap, returns
top N results. Scores above 0 are included; threshold isn't hard — best N bubble up.

**Prompt injection** — `format_ratings_for_injection()`:
```
Past experience with similar tasks (use to calibrate agent count):
  - "add dotnet endpoint" — rated 2/5 with 4 agents — consider fewer or differently scoped agents next time
  - "create angular component" — rated 5/5 with 3 agents — this breakdown worked well
```

---

### `orchestrator.py` — 5 changes

**1. `breakdown_into_agents()`** — injects relevant past ratings before the API call:
```python
_rating_context = format_ratings_for_injection(get_relevant_ratings(user_input))
if _rating_context:
    breakdown_prompt += f"\n\n{_rating_context}"
```

**2. `handle_complex_task()`** (terminal) — calls `_prompt_for_rating()` after `pool.execute()`:
```
Rate this breakdown (1-5) or Enter to skip: 4
   Rating saved: 4/5 — Jarvis will use this for future tasks.
```

**3. `_prompt_for_rating(task_summary, agent_count, workspace_root)`** — new helper.
Non-blocking: Enter skips, invalid input skips, Ctrl+C skips.

**4. `_pending_rating` global** — set by `handle_complex_task_vscode()` after job completes.
Stores `{task_summary, agent_count, workspace}` so `/rate` can look it up.

**5. `handle_rating_command(message)`** — new interceptor:

| Command | Result |
|---|---|
| `/rate 4` | Save rating for last task (uses `_pending_rating`) |
| `/ratings` | List recent ratings with star display |
| `/ratings clear` | Remove all stored ratings |

Wired into both `process_for_vscode()` and `process()` before Claude call.

---

### `server.py` — `/agents/status` response

When job status is `done` or `failed`, response includes:
```json
{
  "rate_prompt": "How did that go? Rate the agent breakdown: `/rate 1` – `/rate 5`"
}
```

---

### `jarvisPanel.ts`

`finalizeAgentPanel()` reads `job.rate_prompt` and appends a styled hint
below the agent rows:

```
How did that go? Rate the agent breakdown: /rate 1 – /rate 5
```

CSS class `.agent-rate-prompt` — italic, dimmed (opacity 0.65), separated by a border-top.

---

## Full Flow

**Terminal:**
```
[task completes]
Rate this breakdown (1-5) or Enter to skip: 3
   Rating saved: 3/5

[next complex task]
→ breakdown_into_agents() sees: "add dotnet endpoint" rated 3/5 with 4 agents
→ tries fewer or differently scoped agents
```

**VS Code:**
```
[agent panel: 3/4 agents done]
[italic footer]: How did that go? Rate the agent breakdown: /rate 1 – /rate 5

User types: /rate 4
Jarvis: Rating saved: ★★★★☆ (4/5 for "build login feature")
        Jarvis will use this to improve future agent breakdowns.
```

---

## Tests — 18 passing

| Group | Tests |
|---|---|
| **Storage** | `test_save_rating_stores_entry`, `test_save_rating_caps_at_50`, `test_save_rating_rejects_out_of_range`, `test_clear_ratings_removes_all` |
| **Query** | `test_get_relevant_ratings_matches_keywords`, `test_get_relevant_ratings_no_match`, `test_get_relevant_ratings_returns_top_n` |
| **Formatting** | `test_format_ratings_for_injection_low_score`, `test_format_ratings_for_injection_high_score`, `test_format_ratings_for_injection_empty` |
| **/rate command** | `test_handle_rate_command_saves_rating`, `test_handle_rate_command_no_pending`, `test_handle_rate_command_invalid_not_number`, `test_handle_rate_command_out_of_range` |
| **/ratings command** | `test_ratings_command_empty`, `test_ratings_command_lists_entries`, `test_ratings_clear_command`, `test_non_rating_command_returns_none` |

---

## Files Changed

| File | Change |
|---|---|
| `tools/ratings.py` | **New** — ratings storage, query, formatting |
| `orchestrator.py` | `breakdown_into_agents()` injection, `_prompt_for_rating()`, `_pending_rating` global, `handle_rating_command()`, wired into `process()` + `process_for_vscode()` |
| `server.py` | `rate_prompt` field in `/agents/status` response |
| `vscode-extension/src/jarvisPanel.ts` | `finalizeAgentPanel()` shows rate prompt; `.agent-rate-prompt` CSS |
| `tests/test_phase13.py` | **New** — 18 tests |
