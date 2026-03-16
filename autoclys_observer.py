from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
import zlib
from collections import deque
from pathlib import Path
from typing import Any, Callable

from hermes_cli.config import get_hermes_home
from run_agent import AIAgent

logger = logging.getLogger(__name__)

CAPTURE_INTERVAL_SECONDS = 0.5
CHANGE_THRESHOLD = 0.01
INPUT_RECENCY_SECONDS = 1.0
ANALYSIS_COOLDOWN_SECONDS = 2.0
LOG_SAVE_INTERVAL_SECONDS = 30.0
PIXEL_DELTA_THRESHOLD = 5
REGIONS_OF_INTEREST = [
    {
        "name": "Center Screen (for typing)",
        "x": 0.25,
        "y": 0.25,
        "width": 0.5,
        "height": 0.5,
        "sensitivity": 0.005,
    },
    {
        "name": "Top Bar (for menus)",
        "x": 0.0,
        "y": 0.0,
        "width": 1.0,
        "height": 0.05,
        "sensitivity": 0.02,
    },
]
APP_CATEGORIES = {
    "chrome": "Web Browsing",
    "firefox": "Web Browsing",
    "safari": "Web Browsing",
    "edge": "Web Browsing",
    "brave": "Web Browsing",
    "arc": "Web Browsing",
    "discord": "Communication",
    "slack": "Communication",
    "teams": "Communication",
    "zoom": "Communication",
    "meet": "Communication",
    "vscode": "Software Development",
    "code": "Software Development",
    "cursor": "Software Development",
    "intellij": "Software Development",
    "pycharm": "Software Development",
    "webstorm": "Software Development",
    "xcode": "Software Development",
    "android studio": "Software Development",
    "terminal": "Software Development",
    "iterm": "Software Development",
    "ghostty": "Software Development",
    "word": "Office",
    "excel": "Office",
    "powerpoint": "Office",
    "keynote": "Office",
    "numbers": "Office",
    "pages": "Office",
    "spotify": "Entertainment",
    "apple music": "Entertainment",
    "youtube": "Entertainment",
    "netflix": "Entertainment",
    "photos": "Graphics & Design",
    "photoshop": "Graphics & Design",
    "illustrator": "Graphics & Design",
    "figma": "Graphics & Design",
    "sketch": "Graphics & Design",
    "finder": "File Management",
    "explorer": "File Management",
    "mail": "Email",
    "outlook": "Email",
    "gmail": "Email",
    "calendar": "Utilities",
    "system preferences": "Utilities",
    "settings": "Utilities",
}
DOMAIN_CATEGORIES = {
    "google.com": "Search",
    "youtube.com": "Entertainment",
    "github.com": "Software Development",
    "stackoverflow.com": "Software Development",
    "linkedin.com": "Professional Networking",
    "twitter.com": "Social Media",
    "x.com": "Social Media",
    "facebook.com": "Social Media",
    "instagram.com": "Social Media",
    "reddit.com": "Social Media",
    "amazon.com": "Shopping",
    "netflix.com": "Entertainment",
    "notion.so": "Productivity",
    "figma.com": "Design",
    "openai.com": "AI Tools",
    "claude.ai": "AI Tools",
    "perplexity.ai": "AI Tools",
    "jira.com": "Project Management",
}


def _now_ts() -> int:
    return int(time.time())


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())


def _clean_text(raw: Any, limit: int = 240) -> str:
    if raw is None:
        return ""
    text = " ".join(str(raw).split()).strip()
    if not text:
        return ""
    return text[:limit].rstrip()


def _sanitize_filename(raw: str, limit: int = 30) -> str:
    text = re.sub(r"[^a-zA-Z0-9]+", "_", raw or "unknown").strip("_")
    return (text or "unknown")[:limit]


def parse_application_name(window_title: str) -> str:
    if not window_title:
        return "unknown"
    for separator in (" - ", " | ", " — "):
        if separator in window_title:
            return window_title.split(separator)[-1].strip().lower()
    if window_title.endswith("🔊"):
        return "browser"
    lower = window_title.lower()
    for app_name in APP_CATEGORIES:
        if app_name in lower:
            return app_name
    return lower.strip() or "unknown"


def categorize_app(app_name: str) -> str:
    if not app_name:
        return "Uncategorized"
    lower = app_name.lower()
    for key, category in APP_CATEGORIES.items():
        if key in lower:
            return category
    return "Uncategorized"


def extract_url_from_title(window_title: str) -> str | None:
    if not window_title:
        return None
    lower = window_title.lower()
    is_browser = any(name in lower for name in ("chrome", "firefox", "safari", "edge", "opera", "brave", "arc")) or "🔊" in window_title
    if not is_browser:
        return None
    for domain in DOMAIN_CATEGORIES:
        if domain in lower:
            return domain
    match = re.search(r"(https?://[^\s]+)|(www\.[^\s]+)|([\w.-]+\.(?:com|org|net|io|dev|ai|co)[^\s]*)", window_title, re.I)
    if not match:
        return None
    value = match.group(0)
    value = re.sub(r"^[^a-z0-9]+", "", value, flags=re.I)
    value = re.sub(r"[^a-z0-9./:_-]+$", "", value, flags=re.I)
    if "://" not in value:
        value = f"https://{value}"
    try:
        from urllib.parse import urlparse

        parsed = urlparse(value)
        return parsed.hostname or match.group(0)
    except Exception:
        return match.group(0)


def categorize_domain(domain: str | None) -> str | None:
    if not domain:
        return None
    lower = domain.lower()
    for key, category in DOMAIN_CATEGORIES.items():
        if key in lower:
            return category
    return "Uncategorized"


def run_applescript(script: str) -> str:
    output = subprocess.run(
        ["osascript", "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )
    return output.stdout.strip()


def get_frontmost_window_title() -> str:
    if sys.platform != "darwin":
        return "Unknown"
    script = r'''tell application "System Events"
set frontApp to first application process whose frontmost is true
set appName to name of frontApp
set winTitle to ""
try
    if (count of windows of frontApp) > 0 then
        set winTitle to name of front window of frontApp
    end if
end try
return winTitle & " - " & appName
end tell'''
    try:
        value = run_applescript(script)
        return value or "Unknown"
    except Exception as exc:
        logger.warning("frontmost window lookup failed: %s", exc)
        return "Unknown"


def get_frontmost_focused_text() -> str:
    if sys.platform != "darwin":
        return ""
    script = r'''tell application "System Events"
set frontApp to first application process whose frontmost is true
set focusedText to ""
try
    set focusedElement to value of attribute "AXFocusedUIElement" of frontApp
    try
        set focusedText to value of attribute "AXValue" of focusedElement as text
    on error
        try
            set focusedText to value of attribute "AXSelectedText" of focusedElement as text
        end try
    end try
end try
return focusedText
end tell'''
    try:
        return run_applescript(script)
    except Exception:
        return ""


def extract_distracted_flag(raw_content: str) -> bool | None:
    if not raw_content:
        return None
    content = raw_content.strip()
    try:
        data = json.loads(content)
        if isinstance(data, dict) and isinstance(data.get("isDistracted"), bool):
            return data["isDistracted"]
    except json.JSONDecodeError:
        pass

    match = re.search(r'"isDistracted"\s*:\s*(true|false)', content, re.I)
    if match:
        return match.group(1).lower() == "true"
    return None


def build_focus_prompt(goal: str, app_name: str, window_title: str, screenshot_path: str | None, text_chunk: str | None = None, reason: str | None = None, guidance: str | None = None) -> str:
    lines = [
        f'so my goal is to "{goal}"',
        "",
        "you are an active friend who is currently observing every window on my pc which i am focusing on, your job is to tell me if i am distracted.",
        "",
        f"current window focus: {app_name} - {window_title}",
    ]
    if guidance:
        lines.extend(["", f"observer guidance from the user: {guidance.strip()}"])
    if text_chunk:
        lines.extend(
            [
                "",
                f'recent typed chunk in this window: "{_clean_text(text_chunk, 320)}"',
            ]
        )
    if reason:
        lines.extend(
            [
                "",
                f"observation trigger: {reason}",
            ]
        )
    if screenshot_path:
        lines.extend(
            [
                "",
                f"if you need visual confirmation, inspect this screenshot with the vision_analyze tool using this local file path: {screenshot_path}",
            ]
        )
    lines.extend(
        [
            "",
            "generate a json format response:",
            '{ "isDistracted": true | false }',
            "",
            "no text nothing only a json",
            "",
            "good responses example:",
            "{",
            '"isDistracted": false',
            "}",
            "{",
            '"isDistracted": true',
            "}",
            "",
            "bad response example:",
            "here is the json response:",
            "```",
            "{",
            '"isDistracted": false',
            "}",
            "```",
            "",
            "do not have a ``` in your response",
            "",
            "begin generating a json now",
        ]
    )
    return "\n".join(lines)


def _new_observation_session_id() -> str:
    timestamp = time.strftime("%Y%m%dT%H%M%S", time.localtime())
    return f"{timestamp}_{uuid.uuid4().hex[:6]}"


def _empty_unified_log(session_id: str, goal: str) -> dict[str, Any]:
    return {
        "meta": {
            "sessionId": session_id,
            "goal": goal,
            "startTime": _now_iso(),
            "endTime": None,
            "version": "1.0.0",
            "platform": sys.platform,
        },
        "windows": {},
        "apps": {},
        "categories": {},
        "productivity": {
            "productive": 0.0,
            "neutral": 0.0,
            "distracting": 0.0,
        },
        "textCaptures": [],
        "timeline": [],
        "stats": {
            "totalTime": 0.0,
            "totalKeystrokes": 0,
            "totalClicks": 0,
            "totalCharactersTyped": 0,
            "totalWordsTyped": 0,
            "appCount": 0,
            "windowCount": 0,
            "categoryBreakdown": {},
        },
    }


def _rank_rollup_items(items: dict[str, dict[str, Any]], key: str, label_key: str, limit: int = 5) -> list[dict[str, Any]]:
    ranked = sorted(
        ((name, data) for name, data in items.items()),
        key=lambda item: float(item[1].get(key, 0.0)),
        reverse=True,
    )[:limit]
    summary = []
    for name, data in ranked:
        summary.append(
            {
                label_key: name,
                "seconds": round(float(data.get(key, 0.0)), 2),
                "category": data.get("category"),
                "visits": int(data.get("visits", 0)),
                "keystrokes": int(data.get("keystrokes", 0)),
            }
        )
    return summary


class DecodedPng:
    def __init__(self, width: int, height: int, channels: int, pixels: bytes):
        self.width = width
        self.height = height
        self.channels = channels
        self.pixels = pixels
        self.row_stride = width * channels

    def gray_at(self, x: int, y: int) -> int:
        x = max(0, min(self.width - 1, x))
        y = max(0, min(self.height - 1, y))
        offset = y * self.row_stride + x * self.channels
        if self.channels == 1:
            return self.pixels[offset]
        return (self.pixels[offset] + self.pixels[offset + 1] + self.pixels[offset + 2]) // 3


def _paeth(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa = abs(p - a)
    pb = abs(p - b)
    pc = abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    if pb <= pc:
        return b
    return c


def decode_png_bytes(data: bytes) -> DecodedPng:
    signature = b"\x89PNG\r\n\x1a\n"
    if not data.startswith(signature):
        raise ValueError("not a png")

    offset = len(signature)
    width = height = bit_depth = color_type = interlace = None
    idat = bytearray()

    while offset < len(data):
        if offset + 8 > len(data):
            raise ValueError("truncated png chunk")
        length = int.from_bytes(data[offset : offset + 4], "big")
        chunk_type = data[offset + 4 : offset + 8]
        offset += 8
        chunk_data = data[offset : offset + length]
        offset += length + 4
        if chunk_type == b"IHDR":
            width = int.from_bytes(chunk_data[0:4], "big")
            height = int.from_bytes(chunk_data[4:8], "big")
            bit_depth = chunk_data[8]
            color_type = chunk_data[9]
            interlace = chunk_data[12]
        elif chunk_type == b"IDAT":
            idat.extend(chunk_data)
        elif chunk_type == b"IEND":
            break

    if width is None or height is None or bit_depth != 8 or interlace != 0:
        raise ValueError("unsupported png format")

    channels_by_color_type = {0: 1, 2: 3, 6: 4}
    channels = channels_by_color_type.get(color_type)
    if channels is None:
        raise ValueError(f"unsupported png color type: {color_type}")

    decompressed = zlib.decompress(bytes(idat))
    stride = width * channels
    expected = height * (stride + 1)
    if len(decompressed) < expected:
        raise ValueError("truncated png payload")

    pixels = bytearray(height * stride)
    prev = bytearray(stride)
    read_offset = 0
    write_offset = 0

    for _ in range(height):
        filter_type = decompressed[read_offset]
        read_offset += 1
        row = bytearray(decompressed[read_offset : read_offset + stride])
        read_offset += stride
        if filter_type == 1:
            for idx in range(stride):
                left = row[idx - channels] if idx >= channels else 0
                row[idx] = (row[idx] + left) & 0xFF
        elif filter_type == 2:
            for idx in range(stride):
                row[idx] = (row[idx] + prev[idx]) & 0xFF
        elif filter_type == 3:
            for idx in range(stride):
                left = row[idx - channels] if idx >= channels else 0
                row[idx] = (row[idx] + ((left + prev[idx]) // 2)) & 0xFF
        elif filter_type == 4:
            for idx in range(stride):
                left = row[idx - channels] if idx >= channels else 0
                up = prev[idx]
                up_left = prev[idx - channels] if idx >= channels else 0
                row[idx] = (row[idx] + _paeth(left, up, up_left)) & 0xFF
        elif filter_type != 0:
            raise ValueError(f"unsupported png filter: {filter_type}")
        pixels[write_offset : write_offset + stride] = row
        prev = row
        write_offset += stride

    return DecodedPng(width, height, channels, bytes(pixels))


def sampled_difference(previous: DecodedPng, current: DecodedPng, *, x: float, y: float, width: float, height: float, columns: int, rows: int) -> float:
    changed = 0
    total = 0
    for row_idx in range(rows):
        y_norm = y + ((row_idx + 0.5) / rows) * height
        prev_y = int(y_norm * max(previous.height - 1, 1))
        curr_y = int(y_norm * max(current.height - 1, 1))
        for col_idx in range(columns):
            x_norm = x + ((col_idx + 0.5) / columns) * width
            prev_x = int(x_norm * max(previous.width - 1, 1))
            curr_x = int(x_norm * max(current.width - 1, 1))
            if abs(previous.gray_at(prev_x, prev_y) - current.gray_at(curr_x, curr_y)) > PIXEL_DELTA_THRESHOLD:
                changed += 1
            total += 1
    return changed / total if total else 0.0


def compare_screenshots(previous_path: Path, current_path: Path) -> tuple[float, list[dict[str, Any]]]:
    previous = decode_png_bytes(previous_path.read_bytes())
    current = decode_png_bytes(current_path.read_bytes())
    overall = sampled_difference(previous, current, x=0.0, y=0.0, width=1.0, height=1.0, columns=100, rows=75)
    region_results = []
    for region in REGIONS_OF_INTEREST:
        region_results.append(
            {
                "name": region["name"],
                "difference": sampled_difference(
                    previous,
                    current,
                    x=region["x"],
                    y=region["y"],
                    width=region["width"],
                    height=region["height"],
                    columns=60,
                    rows=60,
                ),
                "sensitivity": region["sensitivity"],
            }
        )
    return overall, region_results


class KeyloggerBridge:
    def __init__(self, repo_root: Path, callback: Callable[[dict[str, Any]], None]):
        self.repo_root = repo_root
        self.callback = callback
        self.process: subprocess.Popen[str] | None = None
        self.stdout_thread: threading.Thread | None = None
        self.stderr_thread: threading.Thread | None = None
        self.lock = threading.Lock()
        self.ready_event = threading.Event()
        self.start_error: str | None = None

    def start(self) -> bool:
        with self.lock:
            if self.process and self.process.poll() is None:
                return True
            self.ready_event = threading.Event()
            self.start_error = None
            node = shutil.which("node")
            if not node:
                raise RuntimeError("node is required for the autoclys keylogger bridge")
            script = self.repo_root / "autoclys_keylogger_bridge.js"
            if not script.exists():
                raise RuntimeError(f"missing keylogger bridge at {script}")
            self.process = subprocess.Popen(
                [node, str(script)],
                cwd=str(self.repo_root),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
            self.stdout_thread = threading.Thread(target=self._read_stdout, name="autoclys-keylogger-stdout", daemon=True)
            self.stderr_thread = threading.Thread(target=self._read_stderr, name="autoclys-keylogger-stderr", daemon=True)
            self.stdout_thread.start()
            self.stderr_thread.start()
        deadline = time.time() + 5.0
        while time.time() < deadline:
            process = self.process
            if self.ready_event.wait(timeout=0.1):
                if self.start_error:
                    raise RuntimeError(self.start_error)
                return True
            if process and process.poll() is not None:
                break
        message = self.start_error or "autoclys keylogger bridge failed to start"
        self.stop()
        raise RuntimeError(message)

    def stop(self) -> None:
        with self.lock:
            process = self.process
            self.process = None
            self.ready_event.set()
        if not process:
            return
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)

    def _read_stdout(self) -> None:
        process = self.process
        if not process or not process.stdout:
            return
        for line in process.stdout:
            text = line.strip()
            if not text:
                continue
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                logger.debug("non-json keylogger bridge line: %s", text)
                continue
            if payload.get("type") == "ready":
                self.start_error = None
                self.ready_event.set()
            elif payload.get("type") == "error" and not self.ready_event.is_set():
                self.start_error = _clean_text((payload.get("data") or {}).get("message"), 500) or "autoclys keylogger bridge failed"
                self.ready_event.set()
            self.callback(payload)

    def _read_stderr(self) -> None:
        process = self.process
        if not process or not process.stderr:
            return
        for line in process.stderr:
            text = line.strip()
            if text:
                logger.warning("autoclys keylogger stderr: %s", text)


class AutoclysObserver:
    def __init__(self, repo_root: Path, model_resolver: Callable[[], str], chat_lock: threading.Lock | None = None, guidance_resolver: Callable[[], str] | None = None):
        self.repo_root = repo_root
        self.model_resolver = model_resolver
        self.guidance_resolver = guidance_resolver or (lambda: "")
        self.chat_lock = chat_lock or threading.Lock()
        self.state_lock = threading.Lock()
        self.check_lock = threading.Lock()
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.keylogger = KeyloggerBridge(repo_root, self._handle_keylogger_event)
        self.observer_root = get_hermes_home() / "desktop-observer"
        self.screenshots_dir = self.observer_root / "screenshots"
        self.logs_dir = self.observer_root / "logs"
        self.temp_dir = self.observer_root / "tmp"
        self.screenshots_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.running = False
        self.goal = ""
        self.session_id = ""
        self.started_at: int | None = None
        self.last_check_at: int | None = None
        self.last_saved_at: int | None = None
        self.error = ""
        self.active_window = ""
        self.latest_result: dict[str, Any] | None = None
        self.log_path: Path | None = None
        self.unified_log: dict[str, Any] = _empty_unified_log("", "")
        self.events: deque[dict[str, Any]] = deque(maxlen=120)
        self.activities: deque[dict[str, Any]] = deque(maxlen=40)
        self.current_activity: dict[str, Any] | None = None
        self.activity_start_time: float | None = None
        self.last_input_activity = time.time()
        self.last_keystroke = time.time()
        self.last_key_event_at = 0.0
        self.last_analysis_at = 0.0
        self.last_log_save_at = 0.0
        self.last_accessibility_text_at = 0.0
        self.last_accessibility_text_by_window: dict[str, str] = {}
        self.previous_capture: Path | None = None

    def snapshot(self) -> dict[str, Any]:
        with self.state_lock:
            return {
                "running": self.running,
                "goal": self.goal,
                "model": self.model_resolver(),
                "session_id": self.session_id,
                "started_at": self.started_at,
                "last_check_at": self.last_check_at,
                "last_saved_at": self.last_saved_at,
                "active_window": self.active_window,
                "error": self.error,
                "log_path": str(self.log_path) if self.log_path else "",
                "screenshots_dir": str(self.screenshots_dir),
                "latest_result": dict(self.latest_result) if self.latest_result else None,
                "current_activity": self._activity_preview(self.current_activity, include_live_duration=True),
                "activities": [self._activity_preview(item) for item in list(self.activities)],
                "events": list(self.events),
                "stats": self._stats_snapshot(),
                "top_apps": _rank_rollup_items(self.unified_log.get("apps", {}), "timeSpent", "app_name"),
                "top_windows": _rank_rollup_items(self.unified_log.get("windows", {}), "timeSpent", "window_title"),
                "recent_text_captures": list(self.unified_log.get("textCaptures", [])[-5:]),
                "timeline_count": len(self.unified_log.get("timeline", [])),
            }

    def start(self, goal: str) -> dict[str, Any]:
        goal = goal.strip()
        if not goal:
            raise ValueError("goal is required")
        self.stop()
        session_id = _new_observation_session_id()
        log_path = self.logs_dir / f"autoclys_observation_{session_id}.json"
        with self.state_lock:
            self.running = True
            self.goal = goal
            self.session_id = session_id
            self.started_at = _now_ts()
            self.last_check_at = None
            self.last_saved_at = None
            self.error = ""
            self.active_window = ""
            self.latest_result = None
            self.log_path = log_path
            self.unified_log = _empty_unified_log(session_id, goal)
            self.events.clear()
            self.activities.clear()
            self.current_activity = None
            self.activity_start_time = None
            self.last_input_activity = time.time()
            self.last_keystroke = time.time()
            self.last_key_event_at = 0.0
            self.last_analysis_at = 0.0
            self.last_log_save_at = 0.0
            self.last_accessibility_text_at = 0.0
            self.last_accessibility_text_by_window = {}
        self.stop_event = threading.Event()
        self._record_event("observer_started", goal=goal)
        try:
            self.keylogger.start()
        except Exception as exc:
            self._set_error(str(exc))
            self._record_event("keylogger_error", message=str(exc))
        self.thread = threading.Thread(target=self._run_loop, name="autoclys-observer", daemon=True)
        self.thread.start()
        return self.snapshot()

    def stop(self) -> dict[str, Any]:
        thread = self.thread
        self.thread = None
        self.stop_event.set()
        with self.state_lock:
            self.running = False
        self._record_event("observer_stopped", goal=self.goal)
        self.keylogger.stop()
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=5)
        self._finalize_current_activity()
        self._cleanup_capture(self.previous_capture)
        self.previous_capture = None
        self._save_unified_log(include_end_time=True)
        return self.snapshot()

    def check_now(self) -> dict[str, Any]:
        capture_path = self._capture_screen()
        analysis_path = self._persist_analysis_capture(capture_path, "manual_check")
        try:
            window_title = get_frontmost_window_title()
            app_name = parse_application_name(window_title)
            result = self._analyze_focus(app_name, window_title, analysis_path)
            self._record_event("manual_check", window_title=window_title, is_distracted=result.get("is_distracted"), error=result.get("error"))
            return result
        finally:
            self._cleanup_capture(capture_path)

    def _run_loop(self) -> None:
        try:
            while not self.stop_event.is_set():
                self._capture_cycle()
                self.stop_event.wait(CAPTURE_INTERVAL_SECONDS)
        except Exception as exc:
            logger.exception("autoclys observer loop failed")
            self._set_error(str(exc))
            self._record_event("observer_error", message=str(exc))
        finally:
            try:
                self._save_unified_log()
            except Exception:
                logger.debug("skipping observer log save during shutdown", exc_info=True)
            with self.state_lock:
                self.running = False

    def _capture_cycle(self) -> None:
        if self.stop_event.is_set():
            return
        previous_capture = self.previous_capture
        capture_path = self._capture_screen()
        window_changed = False
        try:
            current_window = get_frontmost_window_title()
            if current_window and current_window != self.active_window:
                previous_window = self.active_window
                self.active_window = current_window
                window_changed = True
                screenshot_path = self._save_screenshot(capture_path, "window_change")
                self._track_activity(current_window)
                self._record_event("window_changed", previous_window=previous_window, window_title=current_window, screenshot_path=screenshot_path)
                analysis_path = Path(screenshot_path) if screenshot_path else self._persist_analysis_capture(capture_path, "window_change")
                self._maybe_analyze_focus(parse_application_name(current_window), current_window, analysis_path, reason="window_changed")

            if current_window and not self.stop_event.is_set():
                self._capture_accessibility_text(current_window)

            if not previous_capture:
                self.previous_capture = capture_path
                capture_path = None
                return

            overall_diff, region_results = compare_screenshots(previous_capture, capture_path)
            now = time.time()
            input_recent = (now - self.last_input_activity) < INPUT_RECENCY_SECONDS
            change_detected = False

            if overall_diff > CHANGE_THRESHOLD:
                if input_recent:
                    screenshot_path = self._save_screenshot(capture_path, "input_change")
                    self._increment_input_event("input_change", screenshot_path)
                    self._record_event("input_change", window_title=self.active_window, difference=round(overall_diff, 4), screenshot_path=screenshot_path)
                    analysis_path = Path(screenshot_path) if screenshot_path else self._persist_analysis_capture(capture_path, "input_change")
                    self._maybe_analyze_focus(parse_application_name(self.active_window), self.active_window, analysis_path, text_chunk=self._latest_text_chunk(), reason="input_change")
                elif not window_changed:
                    screenshot_path = self._save_screenshot(capture_path, f"change_{round(overall_diff * 100)}")
                    self._record_event("screen_change", window_title=self.active_window, difference=round(overall_diff, 4), screenshot_path=screenshot_path)
                change_detected = True

            for result in region_results:
                if result["difference"] > result["sensitivity"] and not change_detected and not window_changed:
                    if "Center" in result["name"]:
                        screenshot_path = self._save_screenshot(capture_path, "typing")
                        self._increment_input_event("typing_detected", screenshot_path)
                        self._record_event("typing_detected", window_title=self.active_window, difference=round(result["difference"], 4), screenshot_path=screenshot_path)
                        analysis_path = Path(screenshot_path) if screenshot_path else self._persist_analysis_capture(capture_path, "typing")
                        self._maybe_analyze_focus(parse_application_name(self.active_window), self.active_window, analysis_path, text_chunk=self._latest_text_chunk(), reason="typing_detected")
                    break
            self._keylogger_healthy()
            self._maybe_save_log()
        finally:
            self._cleanup_capture(previous_capture)
            if capture_path is not None:
                self.previous_capture = capture_path

    def _capture_screen(self) -> Path:
        if sys.platform != "darwin":
            raise RuntimeError("vito-style observation currently requires macos")
        path = self.temp_dir / f"capture_{int(time.time() * 1000)}_{uuid.uuid4().hex[:6]}.png"
        result = subprocess.run(["screencapture", "-x", "-t", "png", str(path)], capture_output=True, text=True)
        if result.returncode != 0:
            detail = (result.stderr or "").strip() or "unknown screencapture error"
            raise RuntimeError(f"screen capture failed: {detail}")
        deadline = time.time() + 2.0
        while time.time() < deadline:
            if path.exists() and path.stat().st_size > 0:
                return path
            time.sleep(0.02)
        raise RuntimeError(f"screen capture missing output: {path}")

    def _save_screenshot(self, source_path: Path, reason: str) -> str | None:
        try:
            timestamp = time.strftime("%Y-%m-%dT%H-%M-%S", time.localtime())
            name = _sanitize_filename(self.active_window or "unknown")
            target = self.screenshots_dir / f"{timestamp}_{name}_{reason}.png"
            shutil.copy2(source_path, target)
            return str(target)
        except Exception as exc:
            logger.warning("failed to persist observer screenshot: %s", exc)
            return None

    def _persist_analysis_capture(self, source_path: Path, reason: str) -> Path:
        saved = self._save_screenshot(source_path, reason)
        if saved:
            return Path(saved)
        return source_path

    def _stats_snapshot(self) -> dict[str, Any]:
        stats = self.unified_log.get("stats", {})
        return {
            "total_time_seconds": round(float(stats.get("totalTime", 0.0)), 2),
            "total_keystrokes": int(stats.get("totalKeystrokes", 0)),
            "total_clicks": int(stats.get("totalClicks", 0)),
            "total_characters_typed": int(stats.get("totalCharactersTyped", 0)),
            "total_words_typed": int(stats.get("totalWordsTyped", 0)),
            "app_count": int(stats.get("appCount", 0)),
            "window_count": int(stats.get("windowCount", 0)),
            "categories": dict(self.unified_log.get("categories", {})),
        }

    def _record_timeline_event(self, kind: str, payload: dict[str, Any]) -> None:
        timeline = self.unified_log.setdefault("timeline", [])
        timeline.append(
            {
                "timestamp": _now_iso(),
                "type": kind,
                "data": payload,
            }
        )
        if len(timeline) > 10000:
            self.unified_log["timeline"] = timeline[-5000:]

    def _track_text_capture(self, text: str, window_title: str, source: str) -> None:
        clean_text = str(text or "").strip()
        if not clean_text:
            return

        capture = {
            "timestamp": _now_iso(),
            "window": window_title or self.active_window or "Unknown",
            "text": clean_text,
            "source": source,
            "charCount": len(clean_text),
            "wordCount": len(clean_text.split()),
        }
        text_captures = self.unified_log.setdefault("textCaptures", [])
        text_captures.append(capture)
        if len(text_captures) > 500:
            self.unified_log["textCaptures"] = text_captures[-250:]

        stats = self.unified_log.setdefault("stats", {})
        stats["totalCharactersTyped"] = int(stats.get("totalCharactersTyped", 0)) + capture["charCount"]
        stats["totalWordsTyped"] = int(stats.get("totalWordsTyped", 0)) + capture["wordCount"]

        self._record_timeline_event(
            "text_capture",
            {
                "window": capture["window"],
                "source": source,
                "textPreview": _clean_text(clean_text, 60),
            },
        )

    def _update_rollups_from_activity(self, activity: dict[str, Any]) -> None:
        duration_seconds = round(int(activity.get("duration_ms", 0)) / 1000.0, 2)
        if duration_seconds < 2:
            return

        window_title = str(activity.get("window_title") or "Unknown")
        app_name = str(activity.get("app_name") or parse_application_name(window_title))
        category = str(activity.get("category") or categorize_app(app_name))
        end_time = str(activity.get("end_time") or _now_iso())
        start_time = str(activity.get("start_time") or _now_iso())
        input_events = int(activity.get("input_events", 0))
        keystrokes = int(activity.get("keystroke_count", 0))
        text_inputs = list(activity.get("text_inputs") or [])
        text_count = len(text_inputs)
        total_chars = sum(int(item.get("char_count", 0)) for item in text_inputs)
        total_words = sum(int(item.get("word_count", 0)) for item in text_inputs)

        windows = self.unified_log.setdefault("windows", {})
        if window_title not in windows:
            windows[window_title] = {
                "appName": app_name,
                "category": category,
                "firstSeen": start_time,
                "lastSeen": end_time,
                "timeSpent": duration_seconds,
                "visits": 1,
                "inputEvents": input_events,
                "mouseClicks": 0,
                "keystrokes": keystrokes,
                "productivity": "neutral",
                "domain": activity.get("domain"),
                "textCount": text_count,
                "totalChars": total_chars,
                "totalWords": total_words,
            }
        else:
            windows[window_title]["timeSpent"] = round(float(windows[window_title].get("timeSpent", 0.0)) + duration_seconds, 2)
            windows[window_title]["visits"] = int(windows[window_title].get("visits", 0)) + 1
            windows[window_title]["lastSeen"] = end_time
            windows[window_title]["inputEvents"] = int(windows[window_title].get("inputEvents", 0)) + input_events
            windows[window_title]["keystrokes"] = int(windows[window_title].get("keystrokes", 0)) + keystrokes
            windows[window_title]["textCount"] = int(windows[window_title].get("textCount", 0)) + text_count
            windows[window_title]["totalChars"] = int(windows[window_title].get("totalChars", 0)) + total_chars
            windows[window_title]["totalWords"] = int(windows[window_title].get("totalWords", 0)) + total_words

        apps = self.unified_log.setdefault("apps", {})
        if app_name not in apps:
            apps[app_name] = {
                "category": category,
                "firstSeen": start_time,
                "lastSeen": end_time,
                "timeSpent": duration_seconds,
                "windows": [window_title],
                "inputEvents": input_events,
                "mouseClicks": 0,
                "keystrokes": keystrokes,
                "productivity": "neutral",
                "textCount": text_count,
                "totalChars": total_chars,
                "totalWords": total_words,
            }
        else:
            apps[app_name]["timeSpent"] = round(float(apps[app_name].get("timeSpent", 0.0)) + duration_seconds, 2)
            apps[app_name]["lastSeen"] = end_time
            apps[app_name]["inputEvents"] = int(apps[app_name].get("inputEvents", 0)) + input_events
            apps[app_name]["keystrokes"] = int(apps[app_name].get("keystrokes", 0)) + keystrokes
            apps[app_name]["textCount"] = int(apps[app_name].get("textCount", 0)) + text_count
            apps[app_name]["totalChars"] = int(apps[app_name].get("totalChars", 0)) + total_chars
            apps[app_name]["totalWords"] = int(apps[app_name].get("totalWords", 0)) + total_words
            if window_title not in apps[app_name].get("windows", []):
                apps[app_name].setdefault("windows", []).append(window_title)

        categories = self.unified_log.setdefault("categories", {})
        categories[category] = round(float(categories.get(category, 0.0)) + duration_seconds, 2)

        productivity = self.unified_log.setdefault("productivity", {})
        productivity["neutral"] = round(float(productivity.get("neutral", 0.0)) + duration_seconds, 2)

        stats = self.unified_log.setdefault("stats", {})
        stats["appCount"] = len(apps)
        stats["windowCount"] = len(windows)
        stats["totalTime"] = round(sum(float(item.get("timeSpent", 0.0)) for item in apps.values()), 2)
        total_time = float(stats["totalTime"])
        stats["categoryBreakdown"] = {
            key: (round((float(value) / total_time) * 100, 2) if total_time > 0 else 0.0)
            for key, value in categories.items()
        }

        self._record_timeline_event(
            "activity_completed",
            {
                "window": window_title,
                "app": app_name,
                "duration": duration_seconds,
                "inputEvents": input_events,
                "keystrokes": keystrokes,
            },
        )

    def _save_unified_log(self, include_end_time: bool = False) -> None:
        if not self.log_path:
            return
        payload = json.loads(json.dumps(self.unified_log))
        payload.setdefault("meta", {})["endTime"] = _now_iso() if include_end_time else None
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.log_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        saved_at = _now_ts()
        self.last_log_save_at = time.time()
        with self.state_lock:
            self.last_saved_at = saved_at

    def _maybe_save_log(self) -> None:
        if not self.log_path:
            return
        if (time.time() - self.last_log_save_at) < LOG_SAVE_INTERVAL_SECONDS:
            return
        try:
            self._save_unified_log()
        except Exception as exc:
            logger.warning("failed to save observation log: %s", exc)

    def _analyze_focus(self, app_name: str, window_title: str, screenshot_path: Path, text_chunk: str | None = None, reason: str | None = None) -> dict[str, Any]:
        with self.check_lock:
            prompt = build_focus_prompt(
                self.goal or "be productive",
                app_name,
                window_title,
                str(screenshot_path),
                text_chunk=text_chunk,
                reason=reason,
                guidance=self.guidance_resolver(),
            )
            reply = ""
            error = ""
            try:
                with self.chat_lock:
                    agent = AIAgent(
                        model=self.model_resolver(),
                        max_iterations=4,
                        enabled_toolsets=["vision"],
                        quiet_mode=True,
                        platform="desktop",
                    )
                    result = agent.run_conversation(prompt, conversation_history=[])
                    reply = (result or {}).get("final_response", "")
            except Exception as exc:
                error = str(exc)
                logger.warning("observer hermes analysis failed: %s", exc)
            is_distracted = extract_distracted_flag(reply)
            payload = {
                "checked_at": _now_ts(),
                "app_name": app_name,
                "window_title": window_title,
                "is_distracted": is_distracted,
                "reply": reply,
                "error": error,
                "reason": reason,
                "text_chunk": _clean_text(text_chunk, 320) if text_chunk else "",
            }
            with self.state_lock:
                self.last_check_at = payload["checked_at"]
                self.latest_result = payload
                if error:
                    self.error = error
                elif is_distracted is not None:
                    self.error = ""
            self._record_event(
                "hermes_check",
                window_title=window_title,
                app_name=app_name,
                is_distracted=is_distracted,
                error=error or None,
                reason=reason or "",
                text=_clean_text(text_chunk, 120) if text_chunk else "",
            )
            if is_distracted:
                self._record_event("distraction_detected", window_title=window_title, app_name=app_name)
                try:
                    from model_tools import handle_function_call

                    escalation = handle_function_call(
                        "observer_raise_anomaly",
                        {
                            "summary": f"{app_name} looked off-task while the user should be working on '{self.goal or 'their goal'}'",
                            "goal": self.goal,
                            "window_title": window_title,
                            "app_name": app_name,
                            "reason": reason or "",
                            "text_chunk": _clean_text(text_chunk, 320) if text_chunk else "",
                            "screenshot_path": str(screenshot_path),
                            "observer_reply": reply,
                            "severity": "medium",
                        },
                    )
                    self._record_event("anomaly_forwarded", window_title=window_title, app_name=app_name, result=escalation[:200])
                except Exception as exc:
                    logger.warning("observer anomaly escalation failed: %s", exc)
                    self._record_event("anomaly_forward_failed", window_title=window_title, app_name=app_name, message=str(exc))
            return payload

    def _maybe_analyze_focus(self, app_name: str, window_title: str, screenshot_path: Path, text_chunk: str | None = None, reason: str | None = None) -> dict[str, Any] | None:
        if not window_title:
            return None
        now = time.time()
        if reason not in {"window_changed", "text_chunk", "manual_check"} and (now - self.last_analysis_at) < ANALYSIS_COOLDOWN_SECONDS:
            return None
        result = self._analyze_focus(app_name, window_title, screenshot_path, text_chunk=text_chunk, reason=reason)
        self.last_analysis_at = time.time()
        return result

    def _latest_text_chunk(self) -> str | None:
        if not self.current_activity:
            return None
        items = self.current_activity.get("text_inputs") or []
        if not items:
            return None
        return str(items[-1].get("text") or "").strip() or None

    def _capture_accessibility_text(self, window_title: str) -> None:
        now = time.time()
        if (now - self.last_accessibility_text_at) < 1.0:
            return
        raw_text = get_frontmost_focused_text()
        clean_text = _clean_text(raw_text, 320)
        if len(clean_text) < 4:
            return

        previous = self.last_accessibility_text_by_window.get(window_title, "")
        if clean_text == previous:
            return

        self.last_accessibility_text_at = now
        self.last_accessibility_text_by_window[window_title] = clean_text
        self.last_input_activity = now

        if self.current_activity and self.current_activity.get("window_title") == window_title:
            text_inputs = self.current_activity.setdefault("text_inputs", [])
            if not text_inputs or text_inputs[-1].get("text") != clean_text:
                text_inputs.append(
                    {
                        "text": clean_text,
                        "timestamp": _now_iso(),
                        "char_count": len(clean_text),
                        "word_count": len(clean_text.split()),
                        "source": "accessibility",
                    }
                )
                self.current_activity["text_inputs"] = text_inputs[-15:]

        self._track_text_capture(clean_text, window_title, "accessibility")
        self._record_event("text_capture", window_title=window_title, text=_clean_text(clean_text, 120), source="accessibility")
        if self.stop_event.is_set():
            return
        capture_path = None
        try:
            capture_path = self._capture_screen()
            analysis_path = self._persist_analysis_capture(capture_path, "text_chunk_ax")
            self._maybe_analyze_focus(parse_application_name(window_title), window_title, analysis_path, text_chunk=clean_text, reason="text_chunk")
        except Exception as exc:
            logger.debug("observer accessibility text capture failed: %s", exc)
        finally:
            self._cleanup_capture(capture_path)

    def _track_activity(self, window_title: str) -> None:
        now = time.time()
        if self.current_activity and self.current_activity.get("window_title") != window_title:
            self._finalize_current_activity(now)
        if self.current_activity and self.current_activity.get("window_title") == window_title:
            return
        app_name = parse_application_name(window_title)
        category = categorize_app(app_name)
        domain = extract_url_from_title(window_title)
        self.current_activity = {
            "window_title": window_title,
            "app_name": app_name,
            "category": category,
            "domain": domain,
            "domain_category": categorize_domain(domain),
            "start_time": _now_iso(),
            "duration_ms": 0,
            "input_events": 0,
            "keystroke_count": 0,
            "keystrokes": [],
            "text_inputs": [],
            "screen_events": [],
        }
        self.activity_start_time = now

    def _finalize_current_activity(self, now: float | None = None) -> None:
        if not self.current_activity or self.activity_start_time is None:
            return
        end_time = now or time.time()
        duration_ms = int((end_time - self.activity_start_time) * 1000)
        if duration_ms >= 2000:
            item = dict(self.current_activity)
            item["duration_ms"] = duration_ms
            item["end_time"] = _now_iso()
            self.activities.appendleft(item)
            self._update_rollups_from_activity(item)
        self.current_activity = None
        self.activity_start_time = None

    def _increment_input_event(self, kind: str, screenshot_path: str | None) -> None:
        if not self.current_activity:
            return
        self.current_activity["input_events"] += 1
        self.current_activity.setdefault("screen_events", []).append(
            {
                "timestamp": _now_iso(),
                "type": kind,
                "window_title": self.active_window,
                "screenshot_path": screenshot_path,
            }
        )
        self.current_activity["screen_events"] = self.current_activity["screen_events"][-25:]

    def _handle_keylogger_event(self, payload: dict[str, Any]) -> None:
        if not self.running and payload.get("type") not in {"error"}:
            return
        kind = payload.get("type")
        data = payload.get("data") or {}
        now = time.time()
        if kind == "keystroke":
            self.last_keystroke = now
            self.last_key_event_at = now
            self.last_input_activity = now
            stats = self.unified_log.setdefault("stats", {})
            stats["totalKeystrokes"] = int(stats.get("totalKeystrokes", 0)) + 1
            event_window = str(data.get("window") or "").strip()
            if event_window and event_window != self.active_window:
                previous_window = self.active_window
                self.active_window = event_window
                self._track_activity(event_window)
                self._record_event("window_changed", previous_window=previous_window, window_title=event_window, source="keylogger")
            if self.current_activity:
                self.current_activity["keystroke_count"] += 1
                self.current_activity.setdefault("keystrokes", []).append(
                    {
                        "key": data.get("key"),
                        "window": data.get("window"),
                        "timestamp": data.get("timestamp") or _now_ts(),
                    }
                )
                self.current_activity["keystrokes"] = self.current_activity["keystrokes"][-50:]
            key = str(data.get("key") or "")
            if key:
                self._record_event("keystroke", window_title=event_window or self.active_window, key=key)
            return
        if kind == "text":
            self.last_key_event_at = now
            self.last_input_activity = now
            event_window = str(data.get("window") or "").strip()
            if event_window and event_window != self.active_window:
                previous_window = self.active_window
                self.active_window = event_window
                self._track_activity(event_window)
                self._record_event("window_changed", previous_window=previous_window, window_title=event_window, source="keylogger")
            if self.current_activity and self.current_activity.get("window_title") == event_window:
                self.current_activity.setdefault("text_inputs", []).append(
                    {
                        "text": data.get("text", ""),
                        "timestamp": data.get("timestamp") or _now_iso(),
                        "char_count": data.get("charCount") or len(data.get("text", "")),
                        "word_count": data.get("wordCount") or len((data.get("text", "") or "").split()),
                    }
                )
                self.current_activity["text_inputs"] = self.current_activity["text_inputs"][-15:]
            chunk_text = _clean_text(data.get("text"), 320)
            if target_window := (event_window or self.active_window):
                self._track_text_capture(chunk_text, target_window, "keylogger_sentence")
            self._record_event("text_capture", window_title=event_window or self.active_window, text=_clean_text(data.get("text"), 120))
            if target_window and chunk_text:
                capture_path = None
                try:
                    capture_path = self._capture_screen()
                    analysis_path = self._persist_analysis_capture(capture_path, "text_chunk")
                    self._maybe_analyze_focus(parse_application_name(target_window), target_window, analysis_path, text_chunk=chunk_text, reason="text_chunk")
                except Exception as exc:
                    logger.warning("observer text-triggered capture failed: %s", exc)
                finally:
                    self._cleanup_capture(capture_path)
            return
        if kind == "error":
            message = _clean_text(data.get("message"), 240)
            self._set_error(message)
            self._record_event("keylogger_error", message=message)
            return
        if kind in {"ready", "status"}:
            self._record_event("keylogger_status", **data)

    def _keylogger_healthy(self) -> bool:
        if not self.running:
            return False
        if self.last_key_event_at > 0:
            return True
        if (time.time() - (self.started_at or _now_ts())) < 5:
            return True
        warning = "keylogger started but no keystrokes received yet. check macos accessibility/input monitoring permissions for the current desktop dev app and its node helper."
        if self.error == warning:
            return False
        if self.error and "keylogger" in self.error.lower():
            return False
        self._set_error(warning)
        self._record_event("keylogger_warning", message=warning)
        return False

    def _set_error(self, message: str) -> None:
        with self.state_lock:
            self.error = message

    def _record_event(self, kind: str, **payload: Any) -> None:
        allowed_when_stopped = {"observer_started", "observer_stopped", "observer_error", "keylogger_error", "keylogger_warning"}
        if not self.running and kind not in allowed_when_stopped:
            return
        event = {"kind": kind, "timestamp": _now_ts(), **payload}
        with self.state_lock:
            self.events.appendleft(event)
        self._record_timeline_event(kind, payload)

    def _cleanup_capture(self, path: Path | None) -> None:
        if not path:
            return
        try:
            if path.exists():
                path.unlink()
        except OSError:
            pass

    def _activity_preview(self, activity: dict[str, Any] | None, include_live_duration: bool = False) -> dict[str, Any] | None:
        if not activity:
            return None
        preview = dict(activity)
        preview["keystrokes"] = preview.get("keystrokes", [])[-10:]
        preview["text_inputs"] = preview.get("text_inputs", [])[-5:]
        preview["screen_events"] = preview.get("screen_events", [])[-8:]
        if include_live_duration and self.activity_start_time is not None:
            preview["duration_ms"] = int((time.time() - self.activity_start_time) * 1000)
        return preview
