# tools/token_tracker.py
# Tracks token usage across all tasks and agents in a session
# Shows per-task breakdown, session total, cost estimate,
# and remaining API credits in the final summary.

import re
import anthropic
from config import ANTHROPIC_API_KEY, MODEL_SONNET, MODEL_OPUS

# Pricing per 1M tokens (as of 2026)
PRICING = {
    MODEL_SONNET: {"input": 3.00,  "output": 15.00},
    MODEL_OPUS:   {"input": 15.00, "output": 75.00},
}


def _model_display_name(model_id: str) -> str:
    """
    Convert a model ID to a short human-readable label.
    'claude-sonnet-4-6'       → 'Sonnet 4.6'
    'claude-opus-4-6'         → 'Opus 4.6'
    'claude-haiku-4-5-...'    → 'Haiku 4.5'
    Unknown format             → model_id as-is (safe fallback)
    """
    m = re.match(r"claude-(\w+)-(\d+)-(\d+)", model_id)
    if m:
        return f"{m.group(1).capitalize()} {m.group(2)}.{m.group(3)}"
    return model_id

class TokenTracker:
    """
    Tracks token usage for the entire session.
    Each entry = one task or agent call.
    """

    def __init__(self):
        self.entries = []  # List of token records
        self.session_input_tokens = 0
        self.session_output_tokens = 0

    def log(self, label: str, model: str, input_tokens: int, output_tokens: int):
        """
        Log token usage for one task or agent.
        
        Args:
            label: Description (e.g. "Simple task" or "Agent [agent_1]")
            model: Model used
            input_tokens: Tokens in the prompt
            output_tokens: Tokens in the response
        """
        cost = self._calculate_cost(model, input_tokens, output_tokens)

        entry = {
            "label": label,
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
            "cost_usd": cost
        }

        self.entries.append(entry)
        self.session_input_tokens += input_tokens
        self.session_output_tokens += output_tokens

    def _calculate_cost(self, model: str, input_tokens: int, output_tokens: int) -> float:
        """Calculate cost in USD for a model call."""
        if model not in PRICING:
            return 0.0
        rates = PRICING[model]
        input_cost = (input_tokens / 1_000_000) * rates["input"]
        output_cost = (output_tokens / 1_000_000) * rates["output"]
        return round(input_cost + output_cost, 6)

    def get_session_total_cost(self) -> float:
        """Total cost for entire session."""
        return round(sum(e["cost_usd"] for e in self.entries), 6)

    def get_session_total_tokens(self) -> int:
        """Total tokens used in session."""
        return self.session_input_tokens + self.session_output_tokens

    def get_remaining_credits(self) -> str | None:
        """
        Fetch remaining API credits from Anthropic.
        Returns formatted string like '$2.50', or None if unavailable.
        """
        try:
            client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
            balance = client.beta.usage.get_credits()
            return f"${balance.available_credits:.2f}"
        except Exception:
            return None

    def print_summary(self):
        """Print compact one-line token summary per task."""
        if not self.entries:
            return

        print()
        for entry in self.entries:
            model_short = _model_display_name(entry["model"])
            cost = entry["cost_usd"]
            # Format cost: drop leading zeros only if >= $0.01, else show 5 sig figs
            cost_str = f"${cost:.2f}" if cost >= 0.01 else f"${cost:.5f}".rstrip("0").rstrip(".")
            print(f"  • {model_short}  ••  {entry['total_tokens']:,} tokens  ••  {cost_str}")

        # Session total — only when multiple tasks were logged
        if len(self.entries) > 1:
            total = self.get_session_total_tokens()
            total_cost = self.get_session_total_cost()
            cost_str = f"${total_cost:.2f}" if total_cost >= 0.01 else f"${total_cost:.5f}".rstrip("0").rstrip(".")
            print(f"  ──  Session: {total:,} tokens, {cost_str}")

        # Remaining credits — only show if the API returns a value
        credits = self.get_remaining_credits()
        if credits:
            print(f"  ──  Remaining credits: {credits}")

    def reset(self):
        """Reset tracker for next task."""
        self.entries = []
        self.session_input_tokens = 0
        self.session_output_tokens = 0

# Global tracker instance — shared across the whole session
tracker = TokenTracker()