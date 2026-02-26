# main.py
# Your single entry point to talk to Jarvis
# Run this file to start a session: python main.py

import os
from orchestrator import process, process_briefing, handle_rules_command
from memory import load_memory, update_memory
from tools.token_tracker import tracker

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

            # Phase 8 — /rules and /project rules commands (intercepted before Claude)
            if user_input.startswith("/rules") or user_input.lower().startswith("/project rules"):
                rules_response = handle_rules_command(user_input)
                if rules_response is not None:
                    print(f"\nJarvis: {rules_response}\n")
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
                # Print token summary before exiting
                tracker.print_summary()
                print("\nJarvis: Goodbye! See you next time. 👋")
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

            print("\nJarvis: thinking...\n")
            response = process(user_input, history)
            print(f"Jarvis: {response}\n")

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
            print("\n\nJarvis: Session interrupted. Goodbye! 👋")
            break
        except Exception as e:
            print(f"\n⚠️ Error: {e}\n")

if __name__ == "__main__":
    main()