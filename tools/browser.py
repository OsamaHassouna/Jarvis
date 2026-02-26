# tools/browser.py
# Phase 6.3 — Browser preview.
# After frontend agents finish, open the dev server in the browser.

import json
import os
import webbrowser


def detect_dev_server_url(working_dir: str) -> str | None:
    """
    Detect the local dev server URL based on the project type.
    Returns URL string or None if not a known frontend project.
    """
    # Angular — angular.json is definitive
    if os.path.exists(os.path.join(working_dir, "angular.json")):
        return "http://localhost:4200"

    # Check package.json for React, Vue, Next.js
    pkg_json_path = os.path.join(working_dir, "package.json")
    if os.path.exists(pkg_json_path):
        try:
            with open(pkg_json_path) as f:
                pkg = json.load(f)
            deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}

            if "next" in deps:
                return "http://localhost:3000"
            if "react" in deps or "react-dom" in deps:
                return "http://localhost:3000"
            if "vue" in deps or "@vue/core" in deps:
                return "http://localhost:5173"
            if "@angular/core" in deps:
                return "http://localhost:4200"
        except Exception:
            pass

    return None


def open_browser_preview(working_dir: str) -> tuple[bool, str]:
    """
    Detect the dev server URL and open it in the default browser.
    Returns (success, message).
    """
    url = detect_dev_server_url(working_dir)
    if not url:
        return False, "Could not detect a frontend dev server for this project."

    try:
        webbrowser.open(url)
        return True, f"Opening browser at {url}"
    except Exception as e:
        return False, f"Failed to open browser: {e}"
