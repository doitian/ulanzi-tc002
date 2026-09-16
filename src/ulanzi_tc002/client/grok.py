from importlib.resources import files
import json
import os
from pathlib import Path
import sys

from ulanzi_tc002.client.agent_status import (
    AgentEvent, AgentEventKind, apply_event, reports,
)

ASK_EVENTS = {"PermissionRequest"}
IDLE_EVENTS = {"Stop", "StopFailure", "StopCancelled"}
ASK_NOTIFICATIONS = {"permission_prompt", "elicitation_dialog"}
IDLE_NOTIFICATIONS = {"idle_prompt"}
HOOK_EVENTS = (
    "SessionStart",
    "UserPromptSubmit",
    "PreToolUse",
    "PostToolUse",
    "Stop",
    "StopFailure",
    "StopCancelled",
    "Notification",
    "SubagentStop",
    "SessionEnd",
)
HOOK_FILE = "tc002-watch.json"
SCRIPT_NAME = "tc002-watch.py"
DEFAULT_BRIDGE_URL = "http://127.0.0.1:8009"


def config_dir(environ=None):
    environ = os.environ if environ is None else environ
    override = environ.get("GROK_HOME")
    if override:
        return Path(override)
    return Path.home() / ".grok"


def hooks_path(environ=None):
    return config_dir(environ) / "hooks" / HOOK_FILE


def script_path(environ=None):
    return config_dir(environ) / "hooks" / SCRIPT_NAME


def pascal(name):
    if not isinstance(name, str) or not name:
        return ""
    if "_" in name or name == name.lower():
        return "".join(part.capitalize() for part in name.replace("-", "_").split("_") if part)
    return name


def field(event, *names):
    for name in names:
        value = event.get(name)
        if value is not None:
            return value
    return None


def live_ids(environ=None):
    path = config_dir(environ) / "active_sessions.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, list):
        return None
    ids = set()
    for row in data:
        if not isinstance(row, dict):
            continue
        sid = row.get("session_id") or row.get("sessionId")
        if isinstance(sid, str) and sid:
            ids.add(sid)
    return ids


def reap(sessions, live=None):
    if live is None:
        return
    for sid in list(sessions):
        if sid not in live:
            sessions.pop(sid, None)


def apply_hook(sessions, event, desktop_ids=None):
    if not isinstance(event, dict) or field(event, "subagentType", "subagent_type"):
        return
    sid = field(event, "session_id", "sessionId")
    name = pascal(field(event, "hook_event_name", "hookEventName"))
    if not isinstance(sid, str) or not sid or not name:
        return
    kind = {
        "SessionStart": AgentEventKind.SESSION_START,
        "UserPromptSubmit": AgentEventKind.PROMPT_SUBMIT,
        "PreToolUse": AgentEventKind.TOOL_START,
        "PostToolUse": AgentEventKind.TOOL_COMPLETE,
        "SessionEnd": AgentEventKind.SESSION_END,
    }.get(name)
    notify = field(event, "notification_type", "notificationType")
    if name in ASK_EVENTS or (name == "Notification" and notify in ASK_NOTIFICATIONS):
        kind = AgentEventKind.PERMISSION_REQUEST
    elif name in IDLE_EVENTS or (name == "Notification" and notify in IDLE_NOTIFICATIONS):
        kind = AgentEventKind.STOP
    if kind is not None:
        apply_event(sessions, AgentEvent(sid, kind, pid=event.get("pid")))


def script_source(bridge_url=DEFAULT_BRIDGE_URL):
    text = files("ulanzi_tc002.plugins").joinpath("grok.py").read_text(encoding="utf-8")
    return text.replace(DEFAULT_BRIDGE_URL, bridge_url.rstrip("/"))


def hook_command(script):
    return f"{sys.executable} {json.dumps(str(script))}"


def hook_handler(script):
    return {"type": "command", "command": hook_command(script), "timeout": 1}


def is_ours(handler):
    if not isinstance(handler, dict) or handler.get("type") != "command":
        return False
    return SCRIPT_NAME in str(handler.get("command") or "")


def install_hooks(bridge_url=DEFAULT_BRIDGE_URL, environ=None):
    dest = hooks_path(environ)
    script = script_path(environ)
    dest.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(script_source(bridge_url), encoding="utf-8", newline="\n")
    handler = hook_handler(script)
    hooks = {}
    for event in HOOK_EVENTS:
        hooks[event] = [{"hooks": [handler]}]
    dest.write_text(json.dumps({"hooks": hooks}, indent=2) + "\n", encoding="utf-8", newline="\n")
    return dest


def remove_hooks(environ=None):
    script_path(environ).unlink(missing_ok=True)
    hooks_path(environ).unlink(missing_ok=True)
