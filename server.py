# server.py
# Phase 4 — Local HTTP server for VS Code integration.
# The VS Code extension sends chat messages here with active-file context.
#
# Start with:  python server.py
# Then open the Jarvis panel in VS Code (Ctrl+Shift+J)

import json
import sys
import threading
from http.server import HTTPServer, ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, unquote

# Force UTF-8 stdout so emoji in Claude responses don't crash on Windows cp1252
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from config import SERVER_PORT
from orchestrator import (
    process_for_vscode, process_briefing,
    get_last_files_written, get_pending_commands, run_single_command, kill_command,
    get_last_session_id, get_last_session_name,
    start_vscode_agent_job,
)
from tools.sessions import (
    create_session, get_session, list_all_sessions,
    set_active_session, close_session, delete_session,
    get_active_session_id, append_message as session_append_message,
)
from tools.token_tracker import tracker


class JarvisHTTPServer(ThreadingHTTPServer):
    """Threading server with daemon threads so Ctrl+C never leaves the port occupied."""
    daemon_threads     = True   # request threads die with the process → no port hold
    allow_reuse_address = True  # fast restart without "Address already in use"


class JarvisHTTPHandler(BaseHTTPRequestHandler):
    """Handles incoming requests from the VS Code extension."""

    def log_message(self, format, *args):
        # Suppress default request logging (we print our own)
        pass

    def _send_json(self, status: int, data: dict):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length))

    def do_OPTIONS(self):
        """CORS preflight — required for VS Code webview fetch() calls."""
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path   = parsed.path
        qs     = parse_qs(parsed.query)

        if path == "/status":
            self._send_json(200, {"status": "running", "version": "phase15"})

        elif path == "/briefing":
            self._send_json(200, {"briefing": process_briefing()})

        elif path == "/sessions/list":
            self._send_json(200, list_all_sessions())

        elif path == "/sessions/active":
            workspace_root = unquote(qs.get("workspace_root", [""])[0])
            session_id = get_active_session_id(workspace_root, False)
            if session_id:
                sess = get_session(session_id, workspace_root, False)
                self._send_json(200, {"session": sess})
            else:
                self._send_json(200, {"session": None})

        elif path == "/sessions/load":
            session_id     = unquote(qs.get("session_id", [""])[0])
            workspace_root = unquote(qs.get("workspace_root", [""])[0])
            is_global      = qs.get("is_global", ["0"])[0] == "1"
            if not session_id:
                self._send_json(400, {"error": "session_id is required"})
                return
            sess = get_session(session_id, workspace_root, is_global)
            if sess is None:
                self._send_json(404, {"error": "Session not found"})
                return
            set_active_session(session_id, workspace_root, is_global)
            self._send_json(200, {"session": sess})

        elif path == "/notifications":
            # Phase 15 — return pending notifications for this workspace
            workspace_root = unquote(qs.get("workspace_root", [""])[0])
            from tools.notifications import get_notifications
            self._send_json(200, {"notifications": get_notifications(workspace_root)})

        elif path == "/agents/status":
            # Phase 12 — poll for agent job progress
            job_id = qs.get("job_id", [""])[0]
            if not job_id:
                self._send_json(400, {"error": "job_id is required"})
                return
            from tools.agent_jobs import get_job
            job = get_job(job_id)
            if job is None:
                self._send_json(404, {"error": "Job not found"})
                return
            # Phase 13: include rating prompt when job is finished
            result = dict(job)
            if result.get("status") in ("done", "failed"):
                result["rate_prompt"] = "How did that go? Rate the agent breakdown: `/rate 1` – `/rate 5`"
            self._send_json(200, result)

        else:
            self._send_json(404, {"error": "Not found"})

    def do_POST(self):
        if self.path == "/chat":
            try:
                body = self._read_body()

                message = body.get("message", "").strip()
                if not message:
                    self._send_json(400, {"error": "message is required"})
                    return

                print(f"\n[VS Code] {message[:80]}")
                # Phase 15: register workspace with watcher on every chat interaction
                _ws = body.get("workspace_root", "")
                if _ws:
                    try:
                        from tools.watcher import register_workspace
                        register_workspace(_ws)
                    except Exception:
                        pass
                response = process_for_vscode(
                    message=message,
                    file_path=body.get("file_path", ""),
                    file_content=body.get("file_content", ""),
                    selection=body.get("selection", ""),
                    workspace_root=body.get("workspace_root", ""),
                    attachment_text=body.get("attachment_text", ""),
                    attachment_name=body.get("attachment_name", ""),
                    attachment_image_base64=body.get("attachment_image_base64", ""),
                    attachment_image_type=body.get("attachment_image_type", ""),
                    session_id=body.get("session_id", ""),
                    is_global=bool(body.get("is_global", False)),
                )
                # Phase 12: complex tasks return a sentinel — route to background agent job
                if response == "__COMPLEX_TASK__":
                    agent_job_id = start_vscode_agent_job(
                        message, body.get("workspace_root", "")
                    )
                    print(f"   Agent job started: {agent_job_id}")
                    self._send_json(200, {
                        "response": None,
                        "agent_job_id": agent_job_id,
                        "tokens": None,
                        "files_written": [],
                        "commands_to_run": [],
                        "session_id": get_last_session_id(),
                        "session_name": get_last_session_name(),
                    })
                    return

                print(f"   Jarvis: {response[:80]}...")

                last = tracker.get_last()
                token_data = None
                if last:
                    token_data = {
                        "model": last["model"],
                        "input": last["input_tokens"],
                        "output": last["output_tokens"],
                        "total": last["total_tokens"],
                        "cost": last["cost_usd"],
                    }
                self._send_json(200, {
                    "response": response,
                    "tokens": token_data,
                    "files_written": get_last_files_written(),
                    "commands_to_run": get_pending_commands(),
                    "session_id": get_last_session_id(),
                    "session_name": get_last_session_name(),
                })

            except json.JSONDecodeError:
                self._send_json(400, {"error": "Invalid JSON body"})
            except Exception as e:
                self._send_json(500, {"error": str(e)})

        elif self.path == "/sessions/new":
            try:
                body           = self._read_body()
                workspace_root = body.get("workspace_root", "")
                is_global      = bool(body.get("is_global", False))

                # Close current active session first so it gets a summary
                old_id = get_active_session_id(workspace_root, is_global)
                if old_id:
                    close_session(old_id, workspace_root, is_global)

                sess = create_session(workspace_root, is_global)
                set_active_session(sess["id"], workspace_root, is_global)
                print(f"\n[VS Code] New session: {sess['id']}")
                self._send_json(200, {"session": sess})
            except json.JSONDecodeError:
                self._send_json(400, {"error": "Invalid JSON body"})
            except Exception as e:
                self._send_json(500, {"error": str(e)})

        elif self.path == "/sessions/close":
            try:
                body           = self._read_body()
                session_id     = body.get("session_id", "")
                workspace_root = body.get("workspace_root", "")
                is_global      = bool(body.get("is_global", False))
                if not session_id:
                    self._send_json(400, {"error": "session_id is required"})
                    return
                summary = close_session(session_id, workspace_root, is_global)
                self._send_json(200, {"summary": summary})
            except json.JSONDecodeError:
                self._send_json(400, {"error": "Invalid JSON body"})
            except Exception as e:
                self._send_json(500, {"error": str(e)})

        elif self.path == "/sessions/delete":
            try:
                body           = self._read_body()
                session_id     = body.get("session_id", "")
                workspace_root = body.get("workspace_root", "")
                is_global      = bool(body.get("is_global", False))
                if not session_id:
                    self._send_json(400, {"error": "session_id is required"})
                    return
                deleted = delete_session(session_id, workspace_root, is_global)
                self._send_json(200, {"deleted": deleted})
            except json.JSONDecodeError:
                self._send_json(400, {"error": "Invalid JSON body"})
            except Exception as e:
                self._send_json(500, {"error": str(e)})

        elif self.path == "/run-command":
            try:
                body = self._read_body()
                command      = body.get("command", "").strip()
                working_dir  = body.get("working_dir", "")
                job_id       = body.get("job_id", "")
                session_id   = body.get("session_id", "")
                workspace_root = body.get("workspace_root", "")
                is_global    = bool(body.get("is_global", False))
                if not command:
                    self._send_json(400, {"error": "command is required"})
                    return
                print(f"\n[VS Code] Running: {command}")
                result = run_single_command(command, working_dir, job_id)
                status = "OK" if result["success"] else "Failed"
                print(f"   {status} (PID {result.get('pid', '?')}): {result['output'][:60]}")

                # Record command result in session history so Jarvis knows it ran
                if session_id:
                    output_snippet = result["output"][:500] if result["output"] else "(no output)"
                    status_word = "succeeded" if result["success"] else "FAILED"
                    tool_msg = f"[Tool result] Command {status_word}: `{command}`\nOutput:\n{output_snippet}"
                    try:
                        session_append_message(session_id, workspace_root, is_global, "tool", tool_msg)
                    except Exception:
                        pass  # best-effort

                self._send_json(200, result)
            except json.JSONDecodeError:
                self._send_json(400, {"error": "Invalid JSON body"})
            except Exception as e:
                self._send_json(500, {"error": str(e)})

        elif self.path == "/kill-command":
            try:
                body   = self._read_body()
                job_id = body.get("job_id", "").strip()
                if not job_id:
                    self._send_json(400, {"error": "job_id is required"})
                    return
                result = kill_command(job_id)
                print(f"\n[VS Code] Kill {job_id}: {result['message']}")
                self._send_json(200, result)
            except json.JSONDecodeError:
                self._send_json(400, {"error": "Invalid JSON body"})
            except Exception as e:
                self._send_json(500, {"error": str(e)})

        elif self.path == "/run-agents":
            # Phase 12 — explicit endpoint (also usable from templates in VS Code future)
            try:
                body = self._read_body()
                message        = body.get("message", "").strip()
                workspace_root = body.get("workspace_root", "")
                if not message:
                    self._send_json(400, {"error": "message is required"})
                    return
                agent_job_id = start_vscode_agent_job(message, workspace_root)
                print(f"\n[VS Code] /run-agents job: {agent_job_id}")
                self._send_json(200, {"job_id": agent_job_id, "status": "starting"})
            except json.JSONDecodeError:
                self._send_json(400, {"error": "Invalid JSON body"})
            except Exception as e:
                self._send_json(500, {"error": str(e)})

        elif self.path == "/notifications/dismiss":
            # Phase 15 — dismiss a notification by id or dismiss all for workspace
            try:
                body = self._read_body()
                from tools.notifications import dismiss_notification, dismiss_all
                notif_id = body.get("id", "")
                if notif_id:
                    dismissed = dismiss_notification(notif_id)
                    self._send_json(200, {"dismissed": dismissed})
                else:
                    workspace_root = body.get("workspace_root", "")
                    count = dismiss_all(workspace_root)
                    self._send_json(200, {"dismissed": count})
            except json.JSONDecodeError:
                self._send_json(400, {"error": "Invalid JSON body"})
            except Exception as e:
                self._send_json(500, {"error": str(e)})

        else:
            self._send_json(404, {"error": "Not found"})


def start_server(port: int = None, block: bool = True) -> HTTPServer:
    """
    Start the Jarvis HTTP server.
    block=True  → runs forever (for production)
    block=False → returns server instance (for tests / programmatic use)
    """
    port = port or SERVER_PORT
    server = JarvisHTTPServer(("localhost", port), JarvisHTTPHandler)
    # Phase 15: start background watcher (daemon thread — safe to skip in tests)
    try:
        from tools.watcher import start_watcher
        start_watcher()
    except Exception:
        pass
    print(f"\nJarvis server running on http://localhost:{port}")
    print("   Connect from VS Code (Ctrl+Shift+J) to open the panel.")
    print("   Press Ctrl+C to stop.\n")
    if block:
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nServer stopped.")
    return server


if __name__ == "__main__":
    start_server()
