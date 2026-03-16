import json

from autoclys_runtime import set_observer_bridge
from tools.observer_tools import observer_raise_anomaly


def test_observer_raise_anomaly_uses_runtime_bridge():
    seen = {}

    def handler(payload):
        seen.update(payload)
        return {"ok": True, "session_id": "main_123"}

    set_observer_bridge(handler)
    try:
        result = json.loads(observer_raise_anomaly({"summary": "weird tab"}, task_id="x"))
    finally:
        set_observer_bridge(None)

    assert result["ok"] is True
    assert result["session_id"] == "main_123"
    assert seen["summary"] == "weird tab"
