from __future__ import annotations

import json

from autoclys_runtime import dispatch_observer_anomaly
from tools.registry import registry


OBSERVER_RAISE_ANOMALY_SCHEMA = {
    "name": "observer_raise_anomaly",
    "description": "observer-only escalation hook that forwards a suspicious desktop event into the main autoclys session timeline.",
    "parameters": {
        "type": "object",
        "properties": {
            "summary": {"type": "string", "description": "short human summary of the anomaly"},
            "goal": {"type": "string", "description": "current observer goal"},
            "window_title": {"type": "string", "description": "frontmost window title"},
            "app_name": {"type": "string", "description": "frontmost app name"},
            "reason": {"type": "string", "description": "what triggered the escalation"},
            "text_chunk": {"type": "string", "description": "recent typed text if relevant"},
            "screenshot_path": {"type": "string", "description": "saved screenshot path if available"},
            "observer_reply": {"type": "string", "description": "raw observer model reply"},
            "severity": {"type": "string", "description": "light severity label like low, medium, high"},
        },
        "required": ["summary"],
    },
}


def observer_raise_anomaly(args, **_kw):
    result = dispatch_observer_anomaly(dict(args or {}))
    return json.dumps(result, ensure_ascii=False)


registry.register(
    name="observer_raise_anomaly",
    toolset="observer",
    schema=OBSERVER_RAISE_ANOMALY_SCHEMA,
    handler=observer_raise_anomaly,
    description=OBSERVER_RAISE_ANOMALY_SCHEMA["description"],
)
