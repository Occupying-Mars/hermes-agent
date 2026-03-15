#!/usr/bin/env python3
"""
local desktop service for the tauri frontend.

this is intentionally small and stdlib-only on the transport side. it reuses
hermes' real agent/session/config code rather than shelling out to the cli ui.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

import yaml

from hermes_cli.config import (
    ensure_hermes_home,
    get_config_path,
    get_env_path,
    load_config,
)
from hermes_state import SessionDB
from model_tools import get_tool_definitions
from run_agent import AIAgent
from toolsets import TOOLSETS, get_all_toolsets, resolve_toolset


logger = logging.getLogger(__name__)

ensure_hermes_home()

_DB = SessionDB()
_CHAT_LOCK = threading.Lock()
_COMMON_MODELS = [
    "anthropic/claude-opus-4.6",
    "anthropic/claude-sonnet-4",
    "openai/gpt-5",
    "openai/gpt-5-mini",
    "google/gemini-3-flash-preview",
    "google/gemini-2.5-pro",
    "x-ai/grok-4-fast",
    "moonshotai/kimi-k2",
    "meta-llama/llama-4-maverick",
    "deepseek/deepseek-chat-v3.1",
]


def _default_model() -> str:
    model = load_config().get("model", "anthropic/claude-opus-4.6")
    if isinstance(model, dict):
        return model.get("default", "anthropic/claude-opus-4.6")
    return model


def _new_session_id() -> str:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    short_uuid = uuid.uuid4().hex[:6]
    return f"{timestamp}_{short_uuid}"


def _config_snapshot() -> dict[str, Any]:
    config_path = get_config_path()
    env_path = get_env_path()
    config_text = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
    env_present = env_path.exists()
    return {
        "path": str(config_path),
        "env_path": str(env_path),
        "config": load_config(),
        "config_text": config_text,
        "env_present": env_present,
    }


def _model_options() -> list[str]:
    configured = _default_model()
    seen = set()
    models = []
    for model in [configured, *_COMMON_MODELS]:
        if model and model not in seen:
            seen.add(model)
            models.append(model)
    return models


def _safe_json_load(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    if isinstance(raw, str):
        try:
            loaded = json.loads(raw)
            return loaded if isinstance(loaded, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _toolset_surface() -> list[dict[str, Any]]:
    surfaces = []
    for name in sorted(get_all_toolsets()):
        info = TOOLSETS.get(name, {})
        tools = sorted(resolve_toolset(name))
        available_defs = get_tool_definitions(enabled_toolsets=[name], quiet_mode=True)
        available_names = [tool["function"]["name"] for tool in available_defs]
        surfaces.append(
            {
                "name": name,
                "description": info.get("description", ""),
                "tools": tools,
                "available_tools": available_names,
            }
        )
    return surfaces


def _session_metadata(session: dict[str, Any] | None) -> dict[str, Any]:
    if not session:
        return {}
    model_config = _safe_json_load(session.get("model_config"))
    toolsets = model_config.get("toolsets") or load_config().get("toolsets", ["hermes-cli"])
    return {
        "cwd": model_config.get("cwd") or ".",
        "toolsets": toolsets,
        "max_turns": model_config.get("max_turns") or load_config().get("agent", {}).get("max_turns", 90),
        "model": session.get("model") or _default_model(),
    }


def _message_rows(session_id: str) -> list[dict[str, Any]]:
    rows = _DB.get_messages(session_id)
    messages = []
    for row in rows:
        item = dict(row)
        if item.get("tool_calls"):
            try:
                item["tool_calls"] = json.loads(item["tool_calls"])
            except Exception:
                pass
        messages.append(item)
    return messages


def _session_view(session_id: str) -> dict[str, Any]:
    session = _DB.get_session(session_id)
    if not session:
        raise KeyError(f"session '{session_id}' not found")
    metadata = _session_metadata(session)
    resolved_tools = get_tool_definitions(enabled_toolsets=metadata["toolsets"], quiet_mode=True)
    return {
        "session": session,
        "metadata": metadata,
        "messages": _message_rows(session_id),
        "resolved_tools": [tool["function"]["name"] for tool in resolved_tools],
    }


def _list_sessions() -> list[dict[str, Any]]:
    items = _DB.list_sessions_rich(limit=200)
    sessions = []
    for item in items:
        metadata = _session_metadata(item)
        sessions.append({**item, "metadata": metadata})
    return sessions


def _write_config_text(config_text: str) -> None:
    config_path = get_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    parsed = yaml.safe_load(config_text) if config_text.strip() else {}
    with open(config_path, "w", encoding="utf-8") as handle:
        yaml.safe_dump(parsed or {}, handle, sort_keys=False)
    try:
        os.chmod(config_path, 0o600)
    except OSError:
        pass


def _create_session(payload: dict[str, Any]) -> dict[str, Any]:
    session_id = _new_session_id()
    config = load_config()
    toolsets = payload.get("toolsets") or config.get("toolsets", ["hermes-cli"])
    cwd = payload.get("cwd") or os.getcwd()
    model = payload.get("model") or _default_model()
    max_turns = int(payload.get("max_turns") or config.get("agent", {}).get("max_turns", 90))
    _DB.create_session(
        session_id=session_id,
        source="desktop",
        model=model,
        model_config={
            "cwd": cwd,
            "toolsets": toolsets,
            "max_turns": max_turns,
        },
    )
    title = (payload.get("title") or "").strip()
    if title:
        _DB.set_session_title(session_id, title)
    return _session_view(session_id)


def _update_session_settings(session_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    session = _DB.get_session(session_id)
    if not session:
        raise KeyError(f"session '{session_id}' not found")

    model_config = _safe_json_load(session.get("model_config"))
    next_model = payload.get("model") or session.get("model") or _default_model()
    next_cwd = payload.get("cwd") or model_config.get("cwd") or "."
    next_toolsets = payload.get("toolsets") or model_config.get("toolsets") or load_config().get("toolsets", ["hermes-cli"])
    next_max_turns = int(
        payload.get("max_turns")
        or model_config.get("max_turns")
        or load_config().get("agent", {}).get("max_turns", 90)
    )

    _DB._conn.execute(
        "UPDATE sessions SET model = ?, model_config = ? WHERE id = ?",
        (
            next_model,
            json.dumps(
                {
                    "cwd": next_cwd,
                    "toolsets": next_toolsets,
                    "max_turns": next_max_turns,
                }
            ),
            session_id,
        ),
    )
    _DB._conn.commit()
    return _session_view(session_id)


def _send_message(payload: dict[str, Any]) -> dict[str, Any]:
    session_id = payload["session_id"]
    user_message = payload["message"].strip()
    if not user_message:
        raise ValueError("message cannot be empty")

    session = _DB.get_session(session_id)
    if not session:
        raise KeyError(f"session '{session_id}' not found")

    metadata = _session_metadata(session)
    cwd = payload.get("cwd") or metadata["cwd"] or os.getcwd()
    toolsets = payload.get("toolsets") or metadata["toolsets"]
    model = payload.get("model") or metadata["model"]
    max_turns = int(payload.get("max_turns") or metadata["max_turns"] or 90)
    history = _DB.get_messages_as_conversation(session_id)

    with _CHAT_LOCK:
        previous_cwd = os.environ.get("TERMINAL_CWD")
        os.environ["TERMINAL_CWD"] = cwd
        try:
            agent = AIAgent(
                model=model,
                max_iterations=max_turns,
                enabled_toolsets=toolsets,
                quiet_mode=True,
                platform="desktop",
                session_id=session_id,
                session_db=_DB,
            )
            result = agent.run_conversation(user_message, conversation_history=history)
        finally:
            if previous_cwd is None:
                os.environ.pop("TERMINAL_CWD", None)
            else:
                os.environ["TERMINAL_CWD"] = previous_cwd

    view = _session_view(session_id)
    return {
        "reply": result.get("final_response", ""),
        "session": view["session"],
        "metadata": view["metadata"],
        "messages": view["messages"],
        "resolved_tools": view["resolved_tools"],
    }


class HermesDesktopHandler(BaseHTTPRequestHandler):
    server_version = "HermesDesktop/0.1"

    def log_message(self, fmt: str, *args) -> None:
        logger.debug("%s - %s", self.address_string(), fmt % args)

    def _send_json(self, payload: dict[str, Any], status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8"))

    def _dispatch(self, method: str, path: str, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        if method == "GET" and path == "/api/health":
            return 200, {"ok": True}

        if method == "GET" and path == "/api/bootstrap":
            return 200, {
                "ok": True,
                "sessions": _list_sessions(),
                "toolsets": _toolset_surface(),
                "models": _model_options(),
                "config": _config_snapshot(),
                "cwd": os.getcwd(),
            }

        if method == "GET" and path == "/api/sessions":
            return 200, {"ok": True, "sessions": _list_sessions()}

        if method == "POST" and path == "/api/sessions":
            return 200, {"ok": True, **_create_session(payload)}

        if method == "POST" and path == "/api/chat":
            return 200, {"ok": True, **_send_message(payload)}

        if method == "POST" and path == "/api/config/save":
            _write_config_text(payload.get("config_text", ""))
            return 200, {"ok": True, "config": _config_snapshot()}

        if path.startswith("/api/sessions/"):
            suffix = path[len("/api/sessions/") :]
            if suffix.endswith("/settings") and method == "POST":
                session_id = suffix[: -len("/settings")]
                return 200, {"ok": True, **_update_session_settings(session_id, payload)}
            if suffix.endswith("/rename") and method == "POST":
                session_id = suffix[: -len("/rename")]
                _DB.set_session_title(session_id, (payload.get("title") or "").strip())
                return 200, {"ok": True, **_session_view(session_id)}
            if method == "DELETE":
                deleted = _DB.delete_session(suffix)
                return 200, {"ok": deleted}
            if method == "GET":
                return 200, {"ok": True, **_session_view(suffix)}

        if method == "GET" and path == "/api/search":
            query = payload.get("q", "")
            results = _DB.search_messages(query) if query.strip() else []
            return 200, {"ok": True, "results": results}

        raise KeyError(f"unknown route {method} {path}")

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        payload = {key: values[0] for key, values in parse_qs(parsed.query).items()}
        try:
            status, data = self._dispatch("GET", parsed.path, payload)
            self._send_json(data, status)
        except KeyError as exc:
            self._send_json({"ok": False, "error": str(exc)}, 404)
        except Exception as exc:
            logger.exception("desktop service get failed")
            self._send_json({"ok": False, "error": str(exc)}, 500)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        try:
            status, data = self._dispatch("POST", parsed.path, self._body_json())
            self._send_json(data, status)
        except KeyError as exc:
            self._send_json({"ok": False, "error": str(exc)}, 404)
        except Exception as exc:
            logger.exception("desktop service post failed")
            self._send_json({"ok": False, "error": str(exc)}, 500)

    def do_DELETE(self) -> None:
        parsed = urlparse(self.path)
        try:
            status, data = self._dispatch("DELETE", parsed.path, {})
            self._send_json(data, status)
        except KeyError as exc:
            self._send_json({"ok": False, "error": str(exc)}, 404)
        except Exception as exc:
            logger.exception("desktop service delete failed")
            self._send_json({"ok": False, "error": str(exc)}, 500)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    host = os.getenv("HERMES_DESKTOP_HOST", "127.0.0.1")
    port = int(os.getenv("HERMES_DESKTOP_PORT", "8765"))
    server = ThreadingHTTPServer((host, port), HermesDesktopHandler)
    logger.info("hermes desktop service listening on http://%s:%s", host, port)
    server.serve_forever()


if __name__ == "__main__":
    main()
