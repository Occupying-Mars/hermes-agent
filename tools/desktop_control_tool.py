from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

from autoclys_runtime import COORDINATOR, get_runtime_context
from hermes_cli.config import get_hermes_home
from tools.registry import registry


def _is_macos() -> bool:
    return sys.platform == "darwin"


def _desktop_context() -> dict[str, str]:
    ctx = get_runtime_context()
    return {
        "session_id": str(ctx.get("session_id") or ""),
        "mode": str(ctx.get("mode") or ""),
    }


def _jxa(script: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["osascript", "-l", "JavaScript", "-e", script, *args],
        capture_output=True,
        text=True,
        check=False,
    )


def _notify(title: str, message: str, subtitle: str = "") -> None:
    script = """
function run(argv) {
  const app = Application.currentApplication();
  app.includeStandardAdditions = true;
  app.displayNotification(argv[1] || "", { withTitle: argv[0] || "autoclys", subtitle: argv[2] || "" });
}
"""
    try:
        _jxa(script, title, message, subtitle)
    except Exception:
        pass


def _record_action(status: str, kind: str, title: str, objective: str, why: str, detail: str, tool_name: str) -> dict[str, str]:
    ctx = _desktop_context()
    return COORDINATOR.record_action(
        status=status,
        kind=kind,
        session_id=ctx["session_id"],
        title=title,
        objective=objective,
        why=why,
        detail=detail,
        tool_name=tool_name,
    )


def _begin_action(kind: str, title: str, objective: str, why: str, detail: str, tool_name: str) -> dict[str, str]:
    _notify("autoclys action", title, f"{objective} | {why}")
    return _record_action("pending", kind, title, objective, why, detail, tool_name)


def _complete_action(kind: str, title: str, objective: str, why: str, detail: str, tool_name: str) -> dict[str, str]:
    return _record_action("completed", kind, title, objective, why, detail, tool_name)


def _fail_action(kind: str, title: str, objective: str, why: str, detail: str, tool_name: str) -> dict[str, str]:
    return _record_action("error", kind, title, objective, why, detail, tool_name)


def _result(**payload):
    return json.dumps(payload, ensure_ascii=False)


def _require_action_fields(args: dict, tool_name: str) -> tuple[str, str]:
    objective = str(args.get("objective") or "").strip()
    why = str(args.get("why") or "").strip()
    if not objective or not why:
        raise ValueError(f"{tool_name} requires both 'objective' and 'why'")
    return objective, why


def _run_key_script(mode: str, value: str, modifiers: list[str] | None = None, submit: bool = False) -> None:
    script = """
const MODIFIERS = {
  command: "command down",
  cmd: "command down",
  shift: "shift down",
  option: "option down",
  alt: "option down",
  control: "control down",
  ctrl: "control down",
};
const KEY_CODES = {
  enter: 36,
  return: 36,
  tab: 48,
  space: 49,
  delete: 51,
  escape: 53,
  esc: 53,
  left: 123,
  right: 124,
  down: 125,
  up: 126,
};
function run(argv) {
  const app = Application("System Events");
  const mode = argv[0];
  const value = argv[1] || "";
  const modifierRaw = argv[2] || "";
  const submit = (argv[3] || "") === "1";
  const using = modifierRaw
    .split("+")
    .map((item) => item.trim().toLowerCase())
    .filter(Boolean)
    .map((item) => MODIFIERS[item])
    .filter(Boolean);
  const options = using.length ? { using } : {};
  if (mode === "type") {
    app.keystroke(value, options);
    if (submit) {
      app.keyCode(KEY_CODES.enter);
    }
    return;
  }
  const keyName = value.trim().toLowerCase();
  if (Object.prototype.hasOwnProperty.call(KEY_CODES, keyName)) {
    app.keyCode(KEY_CODES[keyName], options);
    return;
  }
  app.keystroke(value, options);
}
"""
    result = _jxa(script, mode, value, "+".join(modifiers or []), "1" if submit else "0")
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip() or "keyboard script failed"
        raise RuntimeError(detail)


def _run_mouse_script(action: str, x: int, y: int, button: str = "left") -> None:
    script = """
ObjC.import("ApplicationServices");
function mouseEvents(buttonName) {
  if (buttonName === "right") {
    return {
      down: $.kCGEventRightMouseDown,
      up: $.kCGEventRightMouseUp,
      button: $.kCGMouseButtonRight,
    };
  }
  return {
    down: $.kCGEventLeftMouseDown,
    up: $.kCGEventLeftMouseUp,
    button: $.kCGMouseButtonLeft,
  };
}
function post(type, point, buttonRef) {
  const event = $.CGEventCreateMouseEvent(null, type, point, buttonRef);
  $.CGEventPost($.kCGHIDEventTap, event);
}
function run(argv) {
  const action = argv[0];
  const x = Number(argv[1] || 0);
  const y = Number(argv[2] || 0);
  const info = mouseEvents((argv[3] || "left").trim().toLowerCase());
  const point = $.CGPointMake(x, y);
  post($.kCGEventMouseMoved, point, info.button);
  if (action === "move") {
    return;
  }
  post(info.down, point, info.button);
  post(info.up, point, info.button);
  if (action === "double_click") {
    delay(0.08);
    post(info.down, point, info.button);
    post(info.up, point, info.button);
  }
}
"""
    result = _jxa(script, action, str(int(x)), str(int(y)), button)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip() or "mouse script failed"
        raise RuntimeError(detail)


def _capture_screen(reason: str = "") -> str:
    if not _is_macos():
        raise RuntimeError("desktop capture is currently macos-only")
    screenshots_dir = get_hermes_home() / "desktop-actions" / "captures"
    screenshots_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y-%m-%dT%H-%M-%S", time.localtime())
    suffix = reason.strip().replace(" ", "_")[:30] or "capture"
    path = screenshots_dir / f"{stamp}_{suffix}_{uuid.uuid4().hex[:6]}.png"
    result = subprocess.run(["screencapture", "-x", "-t", "png", str(path)], capture_output=True, text=True)
    if result.returncode != 0:
        detail = (result.stderr or "").strip() or "screencapture failed"
        raise RuntimeError(detail)
    return str(path)


def desktop_capture_screen(args, **_kw):
    reason = str(args.get("reason") or "desktop")
    path = _capture_screen(reason=reason)
    _record_action("completed", "screen_capture", "captured desktop screenshot", reason, "screen context for the next tool call", path, "desktop_capture_screen")
    return _result(success=True, path=path, reason=reason)


def desktop_type_text(args, **_kw):
    if not _is_macos():
        return _result(error="desktop typing is currently macos-only")
    objective, why = _require_action_fields(args, "desktop_type_text")
    text = str(args.get("text") or "")
    if not text:
        return _result(error="'text' is required")
    submit = bool(args.get("submit"))
    title = f"type {len(text)} chars"
    detail = text[:120]
    _begin_action("keyboard", title, objective, why, detail, "desktop_type_text")
    try:
        _run_key_script("type", text, submit=submit)
        entry = _complete_action("keyboard", title, objective, why, detail, "desktop_type_text")
        return _result(success=True, action="type", text=text, submit=submit, notice=entry)
    except Exception as exc:
        entry = _fail_action("keyboard", title, objective, why, str(exc), "desktop_type_text")
        return _result(error=str(exc), notice=entry)


def desktop_press_keys(args, **_kw):
    if not _is_macos():
        return _result(error="desktop key presses are currently macos-only")
    objective, why = _require_action_fields(args, "desktop_press_keys")
    keys = args.get("keys")
    if isinstance(keys, str):
        parts = [part.strip() for part in keys.split("+") if part.strip()]
    elif isinstance(keys, list):
        parts = [str(part).strip() for part in keys if str(part).strip()]
    else:
        return _result(error="'keys' must be a string like 'command+shift+p' or a string array")
    if not parts:
        return _result(error="'keys' cannot be empty")
    modifiers = parts[:-1]
    key_value = parts[-1]
    title = f"press {'+'.join(parts)}"
    _begin_action("keyboard", title, objective, why, key_value, "desktop_press_keys")
    try:
        _run_key_script("press", key_value, modifiers=modifiers)
        entry = _complete_action("keyboard", title, objective, why, key_value, "desktop_press_keys")
        return _result(success=True, action="press_keys", keys=parts, notice=entry)
    except Exception as exc:
        entry = _fail_action("keyboard", title, objective, why, str(exc), "desktop_press_keys")
        return _result(error=str(exc), notice=entry)


def desktop_mouse_action(args, **_kw):
    if not _is_macos():
        return _result(error="desktop mouse actions are currently macos-only")
    objective, why = _require_action_fields(args, "desktop_mouse_action")
    action = str(args.get("action") or "move").strip().lower()
    if action not in {"move", "click", "double_click", "right_click"}:
        return _result(error="action must be one of: move, click, double_click, right_click")
    try:
        x = int(args.get("x"))
        y = int(args.get("y"))
    except Exception:
        return _result(error="'x' and 'y' must be integers")
    button = "right" if action == "right_click" else str(args.get("button") or "left").strip().lower()
    title = f"{action.replace('_', ' ')} at {x},{y}"
    detail = f"button={button}"
    _begin_action("mouse", title, objective, why, detail, "desktop_mouse_action")
    try:
        effective_action = "click" if action == "right_click" else action
        _run_mouse_script(effective_action, x, y, button=button)
        entry = _complete_action("mouse", title, objective, why, detail, "desktop_mouse_action")
        return _result(success=True, action=action, x=x, y=y, button=button, notice=entry)
    except Exception as exc:
        entry = _fail_action("mouse", title, objective, why, str(exc), "desktop_mouse_action")
        return _result(error=str(exc), notice=entry)


def _try_tk_popup(title: str, message: str) -> bool:
    script = """
import tkinter as tk
from tkinter import messagebox
root = tk.Tk()
root.withdraw()
messagebox.showinfo(TITLE, MESSAGE)
root.destroy()
"""
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as handle:
        path = Path(handle.name)
        handle.write(f"TITLE = {title!r}\nMESSAGE = {message!r}\n")
        handle.write(script)
    try:
        result = subprocess.run([sys.executable, str(path)], capture_output=True, text=True, timeout=30)
        return result.returncode == 0
    except Exception:
        return False
    finally:
        try:
            path.unlink(missing_ok=True)
        except Exception:
            pass


def _dialog_popup(title: str, message: str) -> None:
    script = """
function run(argv) {
  const app = Application.currentApplication();
  app.includeStandardAdditions = true;
  app.displayDialog(argv[1] || "", { withTitle: argv[0] || "autoclys", buttons: ["ok"], defaultButton: "ok" });
}
"""
    result = _jxa(script, title, message)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip() or "popup failed"
        raise RuntimeError(detail)


def desktop_show_popup(args, **_kw):
    title = str(args.get("title") or "autoclys")
    message = str(args.get("message") or "").strip()
    mood = str(args.get("mood") or "").strip()
    if not message:
        return _result(error="'message' is required")
    popup_title = f"{title} [{mood}]" if mood else title
    detail = message[:140]
    _record_action("pending", "popup", popup_title, "express state to the user", "visible interruption requested by the agent", detail, "desktop_show_popup")
    try:
        backend = "tkinter" if _try_tk_popup(popup_title, message) else "jxa"
        if backend == "jxa":
            _dialog_popup(popup_title, message)
        entry = _complete_action("popup", popup_title, "express state to the user", "visible interruption requested by the agent", detail, "desktop_show_popup")
        return _result(success=True, backend=backend, title=popup_title, notice=entry)
    except Exception as exc:
        entry = _fail_action("popup", popup_title, "express state to the user", "visible interruption requested by the agent", str(exc), "desktop_show_popup")
        return _result(error=str(exc), notice=entry)


DESKTOP_CAPTURE_SCREEN_SCHEMA = {
    "name": "desktop_capture_screen",
    "description": "capture the current desktop as a png and return a local file path so vision tools can inspect the screen before a click or key sequence.",
    "parameters": {
        "type": "object",
        "properties": {
            "reason": {"type": "string", "description": "short label for why the screen is being captured"},
        },
        "required": [],
    },
}

DESKTOP_TYPE_TEXT_SCHEMA = {
    "name": "desktop_type_text",
    "description": "type text into the currently focused desktop app. always include the user's objective and why this exact action is needed.",
    "parameters": {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "text to type into the focused app"},
            "submit": {"type": "boolean", "description": "press enter after typing"},
            "objective": {"type": "string", "description": "what broader goal this action serves"},
            "why": {"type": "string", "description": "why this exact typing action is appropriate now"},
        },
        "required": ["text", "objective", "why"],
    },
}

DESKTOP_PRESS_KEYS_SCHEMA = {
    "name": "desktop_press_keys",
    "description": "press a key or shortcut in the focused desktop app. use this for app shortcuts like command+l, command+shift+p, enter, tab, arrow keys, and escape.",
    "parameters": {
        "type": "object",
        "properties": {
            "keys": {
                "oneOf": [
                    {"type": "string"},
                    {"type": "array", "items": {"type": "string"}},
                ],
                "description": "shortcut as 'command+shift+p' or ['command','shift','p']",
            },
            "objective": {"type": "string", "description": "what broader goal this action serves"},
            "why": {"type": "string", "description": "why this exact key press is appropriate now"},
        },
        "required": ["keys", "objective", "why"],
    },
}

DESKTOP_MOUSE_ACTION_SCHEMA = {
    "name": "desktop_mouse_action",
    "description": "move the mouse or click at exact screen coordinates. use desktop_capture_screen plus vision before this when coordinates are uncertain.",
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["move", "click", "double_click", "right_click"]},
            "x": {"type": "integer", "description": "screen x coordinate in pixels"},
            "y": {"type": "integer", "description": "screen y coordinate in pixels"},
            "button": {"type": "string", "enum": ["left", "right"], "description": "mouse button when action is click-like"},
            "objective": {"type": "string", "description": "what broader goal this action serves"},
            "why": {"type": "string", "description": "why this exact mouse action is appropriate now"},
        },
        "required": ["action", "x", "y", "objective", "why"],
    },
}

DESKTOP_SHOW_POPUP_SCHEMA = {
    "name": "desktop_show_popup",
    "description": "show an on-screen popup so hermes can visibly react, warn, or nudge the user. tries tkinter first and falls back to a native mac dialog.",
    "parameters": {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "popup title"},
            "message": {"type": "string", "description": "popup body text"},
            "mood": {"type": "string", "description": "optional feeling label like worried, proud, annoyed, excited"},
        },
        "required": ["message"],
    },
}


registry.register(
    name="desktop_capture_screen",
    toolset="desktop-control",
    schema=DESKTOP_CAPTURE_SCREEN_SCHEMA,
    handler=desktop_capture_screen,
    check_fn=_is_macos,
    description=DESKTOP_CAPTURE_SCREEN_SCHEMA["description"],
)

registry.register(
    name="desktop_type_text",
    toolset="desktop-control",
    schema=DESKTOP_TYPE_TEXT_SCHEMA,
    handler=desktop_type_text,
    check_fn=_is_macos,
    description=DESKTOP_TYPE_TEXT_SCHEMA["description"],
)

registry.register(
    name="desktop_press_keys",
    toolset="desktop-control",
    schema=DESKTOP_PRESS_KEYS_SCHEMA,
    handler=desktop_press_keys,
    check_fn=_is_macos,
    description=DESKTOP_PRESS_KEYS_SCHEMA["description"],
)

registry.register(
    name="desktop_mouse_action",
    toolset="desktop-control",
    schema=DESKTOP_MOUSE_ACTION_SCHEMA,
    handler=desktop_mouse_action,
    check_fn=_is_macos,
    description=DESKTOP_MOUSE_ACTION_SCHEMA["description"],
)

registry.register(
    name="desktop_show_popup",
    toolset="desktop-control",
    schema=DESKTOP_SHOW_POPUP_SCHEMA,
    handler=desktop_show_popup,
    check_fn=_is_macos,
    description=DESKTOP_SHOW_POPUP_SCHEMA["description"],
)
