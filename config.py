# config.py
# Handles all configuration and environment variables
# We load the API key from .env so it's never hardcoded in our code

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
MODEL_SONNET = "claude-sonnet-4-6"
MODEL_OPUS = "claude-opus-4-6"

# Max tokens per response
MAX_TOKENS = 4096

# Memory file path
MEMORY_FILE = "memory.json"

# VS Code integration server port (Phase 4)
SERVER_PORT = 3131

# Validate that API key exists
if not ANTHROPIC_API_KEY:
    raise ValueError("ANTHROPIC_API_KEY not found in .env file. Please add it.")