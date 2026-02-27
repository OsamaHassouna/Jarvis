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

# Force UTF-8 stdout so emoji in Claude responses don't crash on Windows cp1252
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from config import SERVER_PORT
from orchestrator import (
    process_for_vscode, process_briefing,
    get_last_files_written, get_pending_commands, run_single_command, kill_command,
)
from tools.token_tracker import tracker


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

    def do_OPTIONS(self):
        """CORS preflight — required for VS Code webview fetch() calls."""
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        if self.path == "/status":
            self._send_json(200, {"status": "running", "version": "phase7"})
        elif self.path == "/briefing":
            self._send_json(200, {"briefing": process_briefing()})
        else:
            self._send_json(404, {"error": "Not found"})

    def do_POST(self):
        if self.path == "/chat":
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length))

                message = body.get("message", "").strip()
                if not message:
                    self._send_json(400, {"error": "message is required"})
                    return

                print(f"\n[VS Code] {message[:80]}")
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
                )
                print(f"   Jarvis: {response[:80]}...")

                # Include token data so the VS Code panel can display it
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
                })

            except json.JSONDecodeError:
                self._send_json(400, {"error": "Invalid JSON body"})
            except Exception as e:
                self._send_json(500, {"error": str(e)})

        elif self.path == "/run-command":
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length))
                command = body.get("command", "").strip()
                working_dir = body.get("working_dir", "")
                job_id = body.get("job_id", "")
                if not command:
                    self._send_json(400, {"error": "command is required"})
                    return
                print(f"\n[VS Code] Running: {command}")
                result = run_single_command(command, working_dir, job_id)
                status = "OK" if result["success"] else "Failed"
                print(f"   {status} (PID {result.get('pid', '?')}): {result['output'][:60]}")
                self._send_json(200, result)
            except json.JSONDecodeError:
                self._send_json(400, {"error": "Invalid JSON body"})
            except Exception as e:
                self._send_json(500, {"error": str(e)})

        elif self.path == "/kill-command":
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length))
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

        else:
            self._send_json(404, {"error": "Not found"})


def start_server(port: int = None, block: bool = True) -> HTTPServer:
    """
    Start the Jarvis HTTP server.
    block=True  → runs forever (for production)
    block=False → returns server instance (for tests / programmatic use)
    """
    port = port or SERVER_PORT
    server = ThreadingHTTPServer(("localhost", port), JarvisHTTPHandler)
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
