from autoclys_runtime import COORDINATOR
from hermes_desktop_service import (
    _build_desktop_context_prompt,
    _ensure_desktop_control_toolset,
    _normalize_desktop_context,
)


def test_normalize_desktop_context_keeps_only_clean_fields():
    context = _normalize_desktop_context(
        {
            "active_app": "  Google Chrome  ",
            "window_title": "  Pull Request Review   ",
            "browser_tab": {
                "browser": "  Google Chrome ",
                "title": "  repo: failing test  ",
                "domain": " github.com ",
            },
            "draft_text": "  write the regression test first  ",
            "captured_at": 123,
            "ignored": {"x": 1},
        }
    )

    assert context == {
        "active_app": "Google Chrome",
        "window_title": "Pull Request Review",
        "browser_tab": {
            "browser": "Google Chrome",
            "title": "repo: failing test",
            "domain": "github.com",
        },
        "draft_text": "write the regression test first",
        "captured_at": 123,
    }


def test_build_desktop_context_prompt_marks_matching_draft_as_current_turn():
    prompt = _build_desktop_context_prompt(
        {
            "active_app": "Arc",
            "window_title": "review queue",
            "browser_tab": {
                "browser": "Arc",
                "title": "bug fix diff",
                "domain": "github.com",
            },
            "draft_text": "please inspect the failing branch",
        },
        "please inspect the failing branch",
    )

    assert 'active app: "Arc"' in prompt
    assert 'browser tab: "Arc | bug fix diff"' in prompt
    assert 'browser domain: "github.com"' in prompt
    assert "same text as the current user turn" in prompt
    assert "ambient context only" in prompt


def test_desktop_sessions_always_include_desktop_control():
    assert _ensure_desktop_control_toolset(["hermes-cli"]) == ["hermes-cli", "desktop-control"]
    assert _ensure_desktop_control_toolset(["hermes-cli", "desktop-control"]) == ["hermes-cli", "desktop-control"]


def test_observer_settings_round_trip():
    original = COORDINATOR.get_observer_settings()
    try:
        updated = COORDINATOR.update_observer_settings(
            guidance="watch for doomscrolling",
            target_session_id="session_abc",
            auto_intervene=False,
        )
        assert updated["guidance"] == "watch for doomscrolling"
        assert updated["target_session_id"] == "session_abc"
        assert updated["auto_intervene"] is False
    finally:
        COORDINATOR.update_observer_settings(**original)
