# tools/project_scanner.py
# Phase 3.2 — Scans a working directory to detect project context.
# Reads package.json, angular.json, *.csproj, README.md and returns
# structured info so agents know what framework/version they're working with.

import json
import os
import glob


def scan_project(directory: str) -> dict:
    """
    Scan a directory and return detected project context.
    Returns a dict with keys: stack, framework, backend, description, notes.
    """
    if not directory or not os.path.isdir(directory):
        return {}

    info = {
        "stack": [],
        "framework": "",
        "backend": "",
        "description": "",
        "notes": []
    }

    # ── Angular / Node (package.json) ──
    pkg_path = os.path.join(directory, "package.json")
    if os.path.exists(pkg_path):
        try:
            with open(pkg_path, "r", encoding="utf-8") as f:
                pkg = json.load(f)

            deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}

            if "@angular/core" in deps:
                version = deps["@angular/core"].lstrip("^~")
                major = version.split(".")[0]
                info["framework"] = f"Angular {major}"
                info["stack"].append(f"Angular {major}")

                # Detect if standalone components style
                if int(major) >= 17:
                    info["notes"].append("Angular 17+ — prefer standalone components")

            elif "react" in deps:
                version = deps["react"].lstrip("^~")
                info["framework"] = f"React {version}"
                info["stack"].append(f"React {version}")

            elif "vue" in deps:
                version = deps["vue"].lstrip("^~")
                info["framework"] = f"Vue {version}"
                info["stack"].append(f"Vue {version}")

            # Detect package manager
            if os.path.exists(os.path.join(directory, "yarn.lock")):
                info["notes"].append("Package manager: yarn")
            elif os.path.exists(os.path.join(directory, "pnpm-lock.yaml")):
                info["notes"].append("Package manager: pnpm")
            else:
                info["notes"].append("Package manager: npm")

            # Project name from package.json
            if pkg.get("name") and not info["description"]:
                info["description"] = pkg["name"]

        except (json.JSONDecodeError, OSError):
            pass

    # ── .NET (*.csproj) ──
    csproj_files = glob.glob(os.path.join(directory, "**", "*.csproj"), recursive=True)
    if csproj_files:
        try:
            with open(csproj_files[0], "r", encoding="utf-8") as f:
                content = f.read()

            # Extract target framework
            import re
            match = re.search(r"<TargetFramework>(net[\d.]+)</TargetFramework>", content)
            if match:
                framework = match.group(1)  # e.g. "net8.0"
                major = framework.replace("net", "").split(".")[0]  # "8"
                dotnet_version = f".NET {major}"
                info["backend"] = dotnet_version
                info["stack"].append(dotnet_version)

        except OSError:
            pass

    # ── README.md ──
    readme_path = os.path.join(directory, "README.md")
    if os.path.exists(readme_path):
        try:
            with open(readme_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            # Use first non-empty line as description
            for line in lines[:5]:
                line = line.strip().lstrip("#").strip()
                if line:
                    info["description"] = line
                    break
        except OSError:
            pass

    # ── Angular project structure (angular.json) ──
    angular_json = os.path.join(directory, "angular.json")
    if os.path.exists(angular_json):
        try:
            with open(angular_json, "r", encoding="utf-8") as f:
                ng = json.load(f)
            projects = list(ng.get("projects", {}).keys())
            if projects:
                info["notes"].append(f"Angular projects: {', '.join(projects[:3])}")
        except (json.JSONDecodeError, OSError):
            pass

    return info


def get_context_string(project_info: dict) -> str:
    """
    Convert project info dict into a compact string for agent prompts.
    Returns empty string if no useful info was detected.
    """
    if not project_info:
        return ""

    parts = []

    if project_info.get("framework"):
        parts.append(f"- Frontend: {project_info['framework']}")
    if project_info.get("backend"):
        parts.append(f"- Backend: {project_info['backend']}")
    if project_info.get("description"):
        parts.append(f"- Project: {project_info['description']}")
    for note in project_info.get("notes", []):
        parts.append(f"- Note: {note}")

    return "\n".join(parts) if parts else ""
