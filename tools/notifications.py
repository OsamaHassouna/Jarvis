"""
tools/notifications.py — Phase 15: Proactive watcher notification store.
Phase 17: Notifications persisted to disk across server restarts.

Thread-safe in-memory list of notifications. Populated by tools/watcher.py,
consumed via /notifications endpoint in server.py.
"""

import json
import os
import threading
import time
import uuid

_JARVIS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_NOTIFICATIONS_FILE = os.path.join(_JARVIS_ROOT, "sessions", "notifications.json")
_SEVEN_DAYS = 7 * 24 * 3600   # seconds
_MAX_NOTIFICATIONS = 20

_notifications: list = []
_lock = threading.Lock()


# ── Disk helpers ───────────────────────────────────────────────────────────────

def _save_notifications_locked() -> None:
    """Write _notifications to disk. Must be called while _lock is held."""
    try:
        os.makedirs(os.path.dirname(_NOTIFICATIONS_FILE), exist_ok=True)
        with open(_NOTIFICATIONS_FILE, "w", encoding="utf-8") as f:
            json.dump(_notifications[-_MAX_NOTIFICATIONS:], f)
    except Exception:
        pass


def load_notifications() -> None:
    """
    Load persisted notifications from disk.
    Drops entries older than 7 days. Called once on server startup.
    """
    global _notifications
    try:
        if not os.path.exists(_NOTIFICATIONS_FILE):
            return
        with open(_NOTIFICATIONS_FILE, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            return
        cutoff = time.time() - _SEVEN_DAYS
        fresh = [n for n in data if isinstance(n, dict) and n.get("created_at", 0) >= cutoff]
        with _lock:
            _notifications = fresh
            _save_notifications_locked()
    except Exception:
        pass


# ── Public API ─────────────────────────────────────────────────────────────────

def add_notification(type_: str, message: str, workspace: str = "",
                     severity: str = "info") -> str:
    """
    Add a notification. Returns the new notification's id.
    severity: "info" | "warning"
    """
    notif_id = f"notif_{uuid.uuid4().hex[:8]}"
    with _lock:
        _notifications.append({
            "id": notif_id,
            "type": type_,
            "message": message,
            "workspace": workspace,
            "severity": severity,
            "created_at": time.time(),
        })
        _save_notifications_locked()
    return notif_id


def get_notifications(workspace: str = "", expire_hours: float | None = None) -> list:
    """
    Return all notifications, optionally filtered to a workspace.
    Notifications with no workspace are shown everywhere.
    Auto-expires entries older than expire_hours (default 168h / 7 days).
    """
    ttl = (expire_hours * 3600) if expire_hours is not None else _SEVEN_DAYS
    cutoff = time.time() - ttl
    with _lock:
        global _notifications
        before = len(_notifications)
        _notifications = [n for n in _notifications if n.get("created_at", 0) >= cutoff]
        if len(_notifications) < before:
            _save_notifications_locked()
        result = []
        for n in _notifications:
            if not workspace or not n["workspace"] or n["workspace"] == workspace:
                result.append(dict(n))
        return result


def dismiss_notification(notif_id: str) -> bool:
    """Remove a notification by id. Returns True if found."""
    global _notifications
    with _lock:
        before = len(_notifications)
        _notifications = [n for n in _notifications if n["id"] != notif_id]
        changed = len(_notifications) < before
        if changed:
            _save_notifications_locked()
        return changed


def dismiss_all(workspace: str = "") -> int:
    """Remove all notifications (optionally scoped to a workspace). Returns count removed."""
    global _notifications
    with _lock:
        before = len(_notifications)
        if workspace:
            _notifications = [n for n in _notifications if n["workspace"] != workspace]
        else:
            _notifications = []
        removed = before - len(_notifications)
        if removed:
            _save_notifications_locked()
        return removed
