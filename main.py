# main.py
# Your single entry point to talk to Jarvis
# Run this file to start a session: python main.py

import os
import re
import subprocess
import threading
import time
from orchestrator import process, process_briefing, handle_rules_command, handle_memory_command, _natural_memory_delete
from memory import load_memory, update_memory
from tools.token_tracker import tracker


def _thinking_timer(stop_event: threading.Event) -> None:
    """Prints a live elapsed-time counter while Jarvis processes. Clears itself when done."""
    start = time.time()
    while not stop_event.is_set():
        elapsed = int(time.time() - start)
        if elapsed < 60:
            label = f"  Thinking... {elapsed}s"
        else:
            m, s = divmod(elapsed, 60)
            label = f"  Thinking... {m}m {s:02d}s"
        print(f"\r{label:<35}", end="", flush=True)
        time.sleep(0.5)
    # Clear the timer line
    print(f"\r{' ' * 35}\r", end="", flush=True)

def _extract_bash_blocks(text: str) -> list:
    """Extract commands from ```bash / ``` or ``` / ``` blocks in a response."""
    return re.findall(r"```(?:bash|shell|sh|powershell|cmd)?\n(.*?)```", text, re.DOTALL)


_JARVIS_SLASH_CMDS = ("/memory", "/rules", "/project", "/attach", "/sync")

def _is_jarvis_command(line: str) -> bool:
    """Return True if the line is a Jarvis internal slash command, not a shell command."""
    stripped = line.strip()
    return any(stripped.startswith(prefix) for prefix in _JARVIS_SLASH_CMDS)


def _offer_to_run(response: str) -> None:
    """If response contains real shell commands in code blocks, offer to execute them.
    Skips Jarvis internal /commands — those must be typed directly into the prompt."""
    blocks = _extract_bash_blocks(response)
    if not blocks:
        return
    # Filter: only short blocks (≤3 lines) that are real shell commands
    single_cmds = []
    for block in blocks:
        lines = [l for l in block.strip().splitlines() if l.strip()]
        if not lines or len(lines) > 3:
            continue
        # Skip if any line is a Jarvis slash command
        if any(_is_jarvis_command(l) for l in lines):
            continue
        single_cmds.append(block.strip())
    if not single_cmds:
        return
    try:
        print(f"  Run command? [y/N]: ", end="", flush=True)
        answer = input("").strip().lower()
        if answer in ("y", "yes"):
            for cmd in single_cmds:
                print(f"  > {cmd}")
                result = subprocess.run(cmd, shell=True, text=True, capture_output=False)
                if result.returncode != 0:
                    print(f"  (exited with code {result.returncode})")
    except (EOFError, KeyboardInterrupt):
        pass


def _sync_on_exit():
    """Push memory to GitHub Gist on clean session exit (backup)."""
    try:
        from config import GITHUB_TOKEN, GIST_ID, MEMORY_FILE
        if GITHUB_TOKEN and GIST_ID:
            from tools.sync import push_memory
            push_memory(MEMORY_FILE, GITHUB_TOKEN, GIST_ID)
            print("  (memory synced to Gist)")
    except Exception:
        pass  # Never crash on exit


def setup_user():
    """First time setup — ask for user's name."""
    memory = load_memory()
    if not memory["user"]["name"]:
        print("\nWelcome! I'm Jarvis, your personal AI assistant.")
        name = input("What's your name? ").strip()
        memory["user"]["name"] = name
        update_memory("user", memory["user"])
        print(f"\nNice to meet you, {name}! I'll remember you from now on.\n")

def main():
    """Main conversation loop."""
    print("=" * 50)
    print("          JARVIS - Personal AI Assistant")
    print("=" * 50)

    setup_user()

    # Phase 5.3 — Daily briefing on startup
    print(process_briefing())
    print()

    # Load conversation history for context
    memory = load_memory()
    history = memory.get("history", [])

    print("Type your message below. Type 'exit' to quit.")
    print("Tip: '/attach' or '/attach <path>' to include a file. '/rules' to manage rules.\n")

    # Phase 7 — pending file attachment state
    _attached_content = ""
    _attached_name = ""

    while True:
        try:
            user_input = input("You: ").strip()

            if not user_input:
                continue

            # Intercept /rules, /project rules, /memory commands before Claude
            if user_input.startswith("/rules") or user_input.lower().startswith("/project rules"):
                rules_response = handle_rules_command(user_input)
                if rules_response is not None:
                    print(f"\nJarvis: {rules_response}\n")
                    print("-" * 50)
                    continue
            if user_input.lower().startswith("/memory"):
                mem_response = handle_memory_command(user_input)
                if mem_response is not None:
                    print(f"\nJarvis: {mem_response}\n")
                    print("-" * 50)
                    continue
            nat_mem = _natural_memory_delete(user_input)
            if nat_mem is not None:
                print(f"\nJarvis: {nat_mem}\n")
                print("-" * 50)
                continue

            # /attach — attach a file to the next message
            # Supports:  /attach            → prompts for path
            #            /attach <filepath>  → inline path
            if user_input.lower() == "/attach" or user_input.lower().startswith("/attach "):
                if user_input.lower() == "/attach":
                    path = input("  File path: ").strip().strip('"').strip("'")
                else:
                    path = user_input[8:].strip().strip('"').strip("'")
                if path and os.path.exists(path):
                    try:
                        with open(path, "r", encoding="utf-8", errors="replace") as f:
                            _attached_content = f.read()
                        _attached_name = os.path.basename(path)
                        print(f"  Attached: {_attached_name} ({len(_attached_content):,} chars). Now ask your question.\n")
                    except Exception as e:
                        print(f"  Could not read file: {e}\n")
                elif path:
                    print(f"  File not found: {path}\n")
                continue

            if user_input.lower() in ["exit", "quit", "bye"]:
                tracker.print_summary()
                _sync_on_exit()
                print("\nJarvis: Goodbye. See you next time.")
                break

            # Inject any pending file attachment into the message
            if _attached_content:
                user_input = (
                    f"{user_input}\n\n"
                    f"[Attached file: {_attached_name}]\n"
                    f"```\n{_attached_content[:3000]}\n```"
                )
                _attached_content = ""
                _attached_name = ""

            print()
            stop = threading.Event()
            t = threading.Thread(target=_thinking_timer, args=(stop,), daemon=True)
            t.start()
            try:
                response = process(user_input, history)
            finally:
                stop.set()
                t.join(timeout=1)
            print(f"Jarvis: {response}\n")

            # Offer to run any shell commands Jarvis suggested
            _offer_to_run(response)

            # Show token usage after every task then reset for next
            tracker.print_summary()
            tracker.reset()

            print("-" * 50)

            # Refresh history after each message
            memory = load_memory()
            history = memory.get("history", [])

        except KeyboardInterrupt:
            # Print token summary on forced exit too
            tracker.print_summary()
            _sync_on_exit()
            print("\n\nJarvis: Session ended. Goodbye.")
            break
        except Exception as e:
            print(f"\n⚠️ Error: {e}\n")

if __name__ == "__main__":
    main()