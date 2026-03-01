# config.py
# Handles all configuration and environment variables
# We load the API key from .env so it's never hardcoded in our code

import json
import os
from dotenv import load_dotenv

# Load variables from .env file
load_dotenv()

# Anthropic API key
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

# GITHUB TOKEN + GIST ID — optional, for cross-machine memory sync (Phase 5.4)
# Set these in your .env file or OS environment to enable sync.
# How to set up: github.com/settings/tokens → new token → scope: gist
# Then create a private Gist at gist.github.com (filename: memory.json)
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GIST_ID      = os.getenv("GIST_ID", "")

# Models
# Sonnet for everyday tasks — fast and cost efficient
# Opus for complex tasks — best reasoning and quality
# Haiku for cheap classification / summarisation tasks
MODEL_SONNET = "claude-sonnet-4-6"
MODEL_OPUS   = "claude-opus-4-6"
MODEL_HAIKU  = "claude-haiku-4-5-20251001"

# Max tokens per response
MAX_TOKENS = 4096

# Memory file path
MEMORY_FILE = "memory.json"

# VS Code integration server port (Phase 4)
SERVER_PORT = 3131

# Validate that API key exists
if not ANTHROPIC_API_KEY:
    raise ValueError("ANTHROPIC_API_KEY not found in .env file. Please add it.")

# ── Phase 19: Workspace config ─────────────────────────────────────────────────

_workspace_configs: dict = {}  # workspace_root → merged config dict (with "_mtime" key)

_WATCHER_DEFAULTS = {
    "stale_test_gap_hours": 24,
    "long_branch_days": 5,
    "many_files_count": 8,
    "ignore_branches": ["main", "master", "develop"],
}

_NOTIFICATIONS_DEFAULTS = {
    "expire_hours": 168,
}


def load_workspace_config(workspace_root: str) -> dict:
    """
    Load jarvis.config.json from workspace_root. Merges with defaults.
    Hot-reloads when the file's mtime changes — no server restart needed.
    Returns dict with "watcher" and "notifications" sub-dicts.
    """
    config_path = os.path.join(workspace_root, "jarvis.config.json")

    try:
        mtime = os.path.getmtime(config_path)
    except OSError:
        mtime = None

    cached = _workspace_configs.get(workspace_root)
    if cached is not None and cached.get("_mtime") == mtime:
        return cached

    try:
        with open(config_path, encoding="utf-8") as f:
            raw = json.load(f)
        if not isinstance(raw, dict):
            raw = {}
    except Exception:
        raw = {}

    merged = {
        "watcher": {**_WATCHER_DEFAULTS, **raw.get("watcher", {})},
        "notifications": {**_NOTIFICATIONS_DEFAULTS, **raw.get("notifications", {})},
        "_mtime": mtime,
    }
    _workspace_configs[workspace_root] = merged
    return merged