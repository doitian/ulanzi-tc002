from importlib.resources import files
import json
import os
from pathlib import Path
import sys

from ulanzi_tc002.client.agent_status import (
    AgentEvent, AgentEventKind, apply_event, reports, session_key,
)

ASK_EVENTS = {"PermissionRequest"}
IDLE_EVENTS = {"Stop", "Interrupt"}
HOOK_EVENTS = (
    "SessionStart",
    "UserPromptSubmit",
    "PreToolUse",
    "PermissionRequest",
    "PostToolUse",
    "Stop",
    "Interrupt",
    "SubagentStop",
    "SessionEnd",
)
SCRIPT_NAME = "tc002-watch.py"
DEFAULT_BRIDGE_URL = "http://127.0.0.1:8009"


def config_dir(environ=None):
    environ = os.environ if environ is None else environ
    override = environ.get("CODEX_HOME")
    if override:
        return Path(override)
    return Path.home() / ".codex"


def hooks_path(environ=None):
    return config_dir(environ) / "hooks.json"


def script_path(environ=None):
    return config_dir(environ) / "hooks" / SCRIPT_NAME


def session_dirs(environ=None):
    return [config_dir(environ) / "sessions"]


def session_meta(path):
    try:
        with path.open(encoding="utf-8") as handle:
            data = json.loads(handle.readline())
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    payload = data.get("payload") if data.get("type") == "session_meta" else data
    return payload if isinstance(payload, dict) else None


def load_desktop_ids(environ=None, roots=None):
    ids = set()
    for root in roots if roots is not None else session_dirs(environ):
        if not root.is_dir():
            continue
        for path in root.rglob("*.jsonl"):
            payload = session_meta(path)
            if payload is None:
                continue
            origin = payload.get("originator")
            if not isinstance(origin, str) or "desktop" not in origin.lower():
                continue
            for key in ("session_id", "id"):
                value = payload.get(key)
                if isinstance(value, str) and value:
                    ids.add(value)
    return ids


def originator_from(event):
    origin = event.get("originator")
    if isinstance(origin, str) and origin:
        return origin
    path = event.get("transcript_path")
    if not isinstance(path, str) or not path:
        return None
    payload = session_meta(Path(path))
    if payload is None:
        return None
    origin = payload.get("originator")
    return origin if isinstance(origin, str) else None


def source_for(event, desktop_ids=None):
    origin = originator_from(event)
    if isinstance(origin, str) and "desktop" in origin.lower():
        return "desktop"
    sid = event.get("session_id")
    if desktop_ids is None:
        desktop_ids = load_desktop_ids()
    if isinstance(sid, str) and sid in desktop_ids:
        return "desktop"
    return "cli"


def apply_hook(sessions, event, desktop_ids=None):
    if not isinstance(event, dict):
        return
    sid = session_key(event)
    name = event.get("hook_event_name")
    if not isinstance(sid, str) or not sid or not isinstance(name, str):
        return
    kind = {
        "SessionStart": AgentEventKind.SESSION_START,
        "UserPromptSubmit": AgentEventKind.PROMPT_SUBMIT,
        "PreToolUse": AgentEventKind.TOOL_START,
        "PostToolUse": AgentEventKind.TOOL_COMPLETE,
        "SessionEnd": AgentEventKind.SESSION_END,
    }.get(name)
    if name in ASK_EVENTS:
        kind = AgentEventKind.PERMISSION_REQUEST
    elif name in IDLE_EVENTS:
        kind = AgentEventKind.STOP
    elif name == "SubagentStop":
        if not event.get("agent_id"):
            return
        kind = AgentEventKind.SESSION_END
    if kind is None:
        return
    apply_event(sessions, AgentEvent(
        sid, kind, source=source_for(event, desktop_ids), pid=event.get("pid"),
        parent_id=(event.get("session_id") or "") if event.get("agent_id") else None,
    ))


def script_source(bridge_url=DEFAULT_BRIDGE_URL):
    text = files("ulanzi_tc002.plugins").joinpath("codex.py").read_text(encoding="utf-8")
    return text.replace(DEFAULT_BRIDGE_URL, bridge_url.rstrip("/"))


def hook_command(script):
    return f"{sys.executable} {json.dumps(str(script))}"


def hook_handler(script):
    return {"type": "command", "command": hook_command(script), "timeout": 1, "async": True}


def is_ours(handler):
    if not isinstance(handler, dict) or handler.get("type") != "command":
        return False
    return SCRIPT_NAME in str(handler.get("command") or "")


def group_is_ours(group):
    if not isinstance(group, dict):
        return False
    inner = group.get("hooks")
    return isinstance(inner, list) and any(is_ours(handler) for handler in inner)


def install_hooks(bridge_url=DEFAULT_BRIDGE_URL, environ=None):
    dest = hooks_path(environ)
    script = script_path(environ)
    dest.parent.mkdir(parents=True, exist_ok=True)
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(script_source(bridge_url), encoding="utf-8", newline="\n")
    try:
        data = json.loads(dest.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        hooks = {}
        data["hooks"] = hooks
    handler = hook_handler(script)
    for event in HOOK_EVENTS:
        groups = hooks.get(event)
        if not isinstance(groups, list):
            groups = []
        groups = [group for group in groups if not group_is_ours(group)]
        group = {"hooks": [dict(handler)]}
        if event == "SessionEnd":
            group["hooks"][0] = {**handler, "async": False}
        groups.append(group)
        hooks[event] = groups
    dest.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8", newline="\n")
    return dest


def remove_hooks(environ=None):
    script_path(environ).unlink(missing_ok=True)
    dest = hooks_path(environ)
    try:
        data = json.loads(dest.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    if not isinstance(data, dict):
        return
    hooks = data.get("hooks")
    if isinstance(hooks, dict):
        for event in list(hooks):
            groups = hooks.get(event)
            if not isinstance(groups, list):
                continue
            groups = [group for group in groups if not group_is_ours(group)]
            if groups:
                hooks[event] = groups
            else:
                del hooks[event]
        if not hooks:
            data.pop("hooks", None)
    if data:
        dest.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8", newline="\n")
    else:
        dest.unlink(missing_ok=True)
