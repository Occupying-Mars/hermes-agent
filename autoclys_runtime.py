from __future__ import annotations

import json
import os
import threading
import time
from collections import deque
from contextvars import ContextVar, Token
from typing import Any, Callable


_runtime_context: ContextVar[dict[str, Any]] = ContextVar("autoclys_runtime", default={})
_observer_bridge: Callable[[dict[str, Any]], dict[str, Any]] | None = None

def _observer_settings_path() -> str:
    """Return path to the observer settings JSON, respecting HERMES_HOME."""
    hermes_home = os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes"))
    return os.path.join(hermes_home, "autoclys_settings.json")


def set_runtime_context(**values: Any) -> Token:
    current = dict(_runtime_context.get() or {})
    current.update(values)
    return _runtime_context.set(current)


def reset_runtime_context(token: Token) -> None:
    _runtime_context.reset(token)


def get_runtime_context() -> dict[str, Any]:
    return dict(_runtime_context.get() or {})


def set_observer_bridge(handler: Callable[[dict[str, Any]], dict[str, Any]] | None) -> None:
    global _observer_bridge
    _observer_bridge = handler


def dispatch_observer_anomaly(payload: dict[str, Any]) -> dict[str, Any]:
    if not _observer_bridge:
        return {"ok": False, "error": "observer bridge unavailable"}
    return _observer_bridge(payload)


class AutoclysCoordinator:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._action_log: deque[dict[str, Any]] = deque(maxlen=200)
        self._anomaly_log: deque[dict[str, Any]] = deque(maxlen=200)
        self._observer_settings: dict[str, Any] = {
            "guidance": "",
            "target_session_id": "",
            "auto_intervene": True,
        }
        self._load_observer_settings() # Load settings on initialization

    def _load_observer_settings(self) -> None:
        """Loads observer settings from disk."""
        path = _observer_settings_path()
        try:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    loaded_settings = json.load(f)
                for key in self._observer_settings:
                    if key in loaded_settings:
                        self._observer_settings[key] = loaded_settings[key]
        except (OSError, json.JSONDecodeError):
            pass

    def _save_observer_settings(self) -> None:
        """Saves current observer settings to disk."""
        path = _observer_settings_path()
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self._observer_settings, f, indent=2, ensure_ascii=False)
        except OSError:
            pass

    def get_observer_settings(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._observer_settings)

    def update_observer_settings(self, **updates: Any) -> dict[str, Any]:
        with self._lock:
            if "guidance" in updates:
                self._observer_settings["guidance"] = str(updates.get("guidance") or "").strip()
            if "target_session_id" in updates:
                self._observer_settings["target_session_id"] = str(updates.get("target_session_id") or "").strip()
            if "auto_intervene" in updates:
                self._observer_settings["auto_intervene"] = bool(updates.get("auto_intervene"))
            self._save_observer_settings() # Save settings after update
            return dict(self._observer_settings)

    def record_action(self, *, status: str, kind: str, session_id: str = "", title: str = "", objective: str = "", why: str = "", detail: str = "", tool_name: str = "") -> dict[str, Any]:
        entry = {
            "timestamp": int(time.time()),
            "status": status,
            "kind": kind,
            "session_id": session_id,
            "title": title,
            "objective": objective,
            "why": why,
            "detail": detail,
            "tool_name": tool_name,
        }
        with self._lock:
            self._action_log.appendleft(entry)
        return entry

    def list_actions(self, session_id: str | None = None, limit: int = 30) -> list[dict[str, Any]]:
        with self._lock:
            items = list(self._action_log)
        if session_id:
            items = [item for item in items if item.get("session_id") == session_id]
        return items[:limit]

    def record_anomaly(self, payload: dict[str, Any]) -> dict[str, Any]:
        entry = {
            "timestamp": int(time.time()),
            **payload,
        }
        with self._lock:
            self._anomaly_log.appendleft(entry)
        return entry

    def list_anomalies(self, session_id: str | None = None, limit: int = 30) -> list[dict[str, Any]]:
        with self._lock:
            items = list(self._anomaly_log)
        if session_id:
            items = [item for item in items if item.get("session_id") == session_id]
        return items[:limit]


COORDINATOR = AutoclysCoordinator()
