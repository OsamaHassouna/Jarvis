"""
tools/notifications.py — Phase 15: Proactive watcher notification store.

Thread-safe in-memory list of notifications. Populated by tools/watcher.py,
consumed via /notifications endpoint in server.py.
"""

import threading
import time
import uuid

_notifications: list = []
_lock = threading.Lock()


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
    return notif_id


def get_notifications(workspace: str = "") -> list:
    """
    Return all notifications, optionally filtered to a workspace.
    Notifications with no workspace are shown everywhere.
    """
    with _lock:
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
        return len(_notifications) < before


def dismiss_all(workspace: str = "") -> int:
    """Remove all notifications (optionally scoped to a workspace). Returns count removed."""
    global _notifications
    with _lock:
        before = len(_notifications)
        if workspace:
            _notifications = [n for n in _notifications if n["workspace"] != workspace]
        else:
            _notifications = []
        return before - len(_notifications)
