import json

from tools.desktop_control_tool import desktop_press_keys


def test_desktop_press_keys_requires_objective_and_why():
    result = json.loads(desktop_press_keys({"keys": "command+l"}))
    assert "error" in result
    assert "objective" in result["error"]
