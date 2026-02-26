# tools/claude_code.py
# Bridge between Jarvis and Claude Code CLI
# Runs Claude Code in agent mode so it can actually create/edit files
# and run terminal commands within the user-approved directory only.

import subprocess
import os
from typing import Optional

# Actions Claude Code is allowed to perform
ALLOWED_ACTIONS = [
    "create files",
    "edit files", 
    "delete files",
    "run terminal commands (npm, dotnet, ng, git, etc.)"
]

# def confirm_execution(task: str, working_dir: str) -> bool:
#     """
#     Ask user to confirm before Claude Code makes any changes.
#     Returns True if confirmed, False if cancelled.
#     """
#     print("\n" + "=" * 50)
#     print("⚠️  JARVIS IS ABOUT TO MAKE CHANGES")
#     print("=" * 50)
#     print(f"📋 Task:      {task[:100]}")
#     print(f"📁 Directory: {working_dir}")
#     print(f"🔧 Allowed:   {', '.join(ALLOWED_ACTIONS)}")
#     print("=" * 50)
    
#     confirm = input("\nAllow Jarvis to proceed? (yes/no): ").strip().lower()
#     return confirm in ["yes", "y"]

def run_claude_code(
    task: str,
    working_dir: str,
    context: Optional[str] = None,
    timeout: int = 600  # Increased to 10 minutes
) -> dict:
    """
    Run a task using Claude Code CLI in agent mode.
    Streams output in real time so you can see what's happening.
    NOTE: Confirmation is handled by AgentPool before calling this.
    """

    # Validate or create working directory
    if not os.path.exists(working_dir):
        try:
            os.makedirs(working_dir, exist_ok=True)
            print(f"✅ Created directory: {working_dir}")
        except Exception as e:
            return {
                "success": False,
                "output": "",
                "error": f"Could not create directory: {str(e)}"
            }

    # Build the full prompt
    prompt = task
    if context:
        prompt = f"{context}\n\nYour specific task:\n{task}"

    # Scope restriction
    scoped_prompt = f"""You are working ONLY inside this directory: {working_dir}
Do NOT access or modify files outside this directory.
You are allowed to: create files, edit files, delete files, and run terminal commands.

{prompt}"""

    print(f"\n🤖 Claude Code is working in: {working_dir}")
    print("─" * 50)

    try:
        # Stream output in real time using Popen instead of run
        process = subprocess.Popen(
            [
                "claude",
                "-p", scoped_prompt,
                "--dangerously-skip-permissions",
                "--output-format", "text",
                "--verbose"
            ],
            cwd=working_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,  # Merge stderr into stdout
            text=True,
            bufsize=1  # Line buffered
        )

        output_lines = []
        start_time = __import__("time").time()

        # Stream output line by line
        for line in iter(process.stdout.readline, ""):
            # Check timeout manually
            if __import__("time").time() - start_time > timeout:
                process.kill()
                return {
                    "success": False,
                    "output": "\n".join(output_lines),
                    "error": f"Agent timed out after {timeout} seconds"
                }

            line = line.rstrip()
            if line:
                print(f"  │ {line}")
                output_lines.append(line)

        process.wait()
        print("─" * 50)

        full_output = "\n".join(output_lines)

        if process.returncode == 0:
            return {
                "success": True,
                "output": full_output,
                "error": None
            }
        else:
            print(f"\n⚠️  Claude Code exited with code {process.returncode}")
            return {
                "success": False,
                "output": full_output,
                "error": f"Claude Code exited with code {process.returncode}"
            }

    except FileNotFoundError:
        return {
            "success": False,
            "output": "",
            "error": "Claude Code CLI not found. Make sure 'claude' is in your PATH."
        }
    except Exception as e:
        return {
            "success": False,
            "output": "",
            "error": str(e)
        }

def verify_claude_code_installed() -> bool:
    """Check if Claude Code CLI is available."""
    try:
        result = subprocess.run(
            ["claude", "--version"],
            capture_output=True,
            text=True,
            timeout=10
        )
        return result.returncode == 0
    except Exception:
        return False

def get_working_directory(project_name: str) -> Optional[str]:
    """
    Ask the user where to run the agents.
    Returns the chosen directory path or None if cancelled.
    """
    print(f"\n📁 Where should Jarvis work for: '{project_name}'?")
    print("1. Enter a full path (e.g. D:\\Projects\\my-app)")
    print("2. Use current directory")
    print("3. Cancel")

    choice = input("\nYour choice (1/2/3): ").strip()

    if choice == "1":
        path = input("Enter full path: ").strip()
        if os.path.exists(path):
            return path
        else:
            create = input(f"📁 Folder doesn't exist. Create it? (yes/no): ").strip().lower()
            if create in ["yes", "y"]:
                os.makedirs(path, exist_ok=True)
                print(f"✅ Created folder: {path}")
                return path
            else:
                print("🚫 Folder not created. Task cancelled.")
                return None
    elif choice == "2":
        return os.getcwd()
    else:
        return None