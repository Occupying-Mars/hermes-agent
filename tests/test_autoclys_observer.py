import json
import time

from autoclys_observer import AutoclysObserver, _empty_unified_log


def test_observer_uses_hermes_home_for_storage(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    observer = AutoclysObserver(tmp_path, model_resolver=lambda: "test-model")

    assert observer.observer_root == tmp_path / "desktop-observer"
    assert observer.logs_dir == tmp_path / "desktop-observer" / "logs"


def test_observer_rolls_up_activity_and_persists_log(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    observer = AutoclysObserver(tmp_path, model_resolver=lambda: "test-model")
    observer.goal = "ship the observer port"
    observer.session_id = "session_123"
    observer.log_path = observer.logs_dir / "autoclys_observation_session_123.json"
    observer.unified_log = _empty_unified_log(observer.session_id, observer.goal)
    observer.current_activity = {
        "window_title": "Observer Port - Cursor",
        "app_name": "cursor",
        "category": "Software Development",
        "domain": None,
        "domain_category": None,
        "start_time": "2026-03-16T12:00:00",
        "duration_ms": 0,
        "input_events": 2,
        "keystroke_count": 7,
        "keystrokes": [{"key": "a", "timestamp": 1}],
        "text_inputs": [
            {
                "text": "draft the port",
                "timestamp": "2026-03-16T12:00:02",
                "char_count": 14,
                "word_count": 3,
            }
        ],
        "screen_events": [],
    }
    observer.activity_start_time = time.time() - 5

    observer._track_text_capture("draft the port", "Observer Port - Cursor", "keylogger_sentence")
    observer._finalize_current_activity(now=observer.activity_start_time + 5)
    observer._save_unified_log()

    snapshot = observer.snapshot()

    assert snapshot["stats"]["total_time_seconds"] == 5.0
    assert snapshot["stats"]["total_keystrokes"] == 0
    assert snapshot["stats"]["total_characters_typed"] == 14
    assert snapshot["stats"]["app_count"] == 1
    assert snapshot["top_apps"][0]["app_name"] == "cursor"
    assert snapshot["top_windows"][0]["window_title"] == "Observer Port - Cursor"
    assert snapshot["recent_text_captures"][0]["text"] == "draft the port"
    assert observer.log_path.exists()

    payload = json.loads(observer.log_path.read_text(encoding="utf-8"))
    assert payload["meta"]["sessionId"] == "session_123"
    assert payload["apps"]["cursor"]["timeSpent"] == 5.0
