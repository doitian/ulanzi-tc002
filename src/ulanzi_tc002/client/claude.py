import json
import os
from pathlib import Path
import subprocess

HOOK_EVENTS = (
    "SessionStart",
    "UserPromptSubmit",
    "PreToolUse",
    "PermissionRequest",
    "PostToolUse",
    "Notification",
    "Elicitation",
    "Stop",
    "StopFailure",
    "SessionEnd",
)
ASK_EVENTS = {"PermissionRequest", "Elicitation"}
BUSY_EVENTS = {"UserPromptSubmit", "PreToolUse", "PostToolUse"}
IDLE_EVENTS = {"Stop", "StopFailure"}
SWITCH_EVENTS = {"SessionStart", "UserPromptSubmit"}
ASK_NOTIFICATIONS = {
    "permission_prompt",
    "agent_needs_input",
    "elicitation_dialog",
    "elicitation_url_dialog",
}
NOTIFICATION_MATCHER = "|".join(sorted(ASK_NOTIFICATIONS))
HOOK_SOURCES = ("desktop", "cli")


def config_dir(environ=None):
    environ = os.environ if environ is None else environ
    override = environ.get("CLAUDE_CONFIG_DIR")
    if override:
        return Path(override)
    return Path.home() / ".claude"


def settings_path(environ=None):
    return config_dir(environ) / "settings.json"


def desktop_session_dirs(environ=None):
    environ = os.environ if environ is None else environ
    override = environ.get("CLAUDE_DESKTOP_SESSIONS")
    if override:
        return [Path(override)]
    home = Path.home()
    xdg = Path(environ.get("XDG_CONFIG_HOME") or (home / ".config"))
    dirs = [xdg / "Claude" / "claude-code-sessions"]
    mac = home / "Library" / "Application Support" / "Claude" / "claude-code-sessions"
    if mac not in dirs:
        dirs.append(mac)
    appdata = environ.get("APPDATA")
    if appdata:
        dirs.append(Path(appdata) / "Claude" / "claude-code-sessions")
    return dirs


def load_desktop_ids(environ=None, roots=None):
    ids = set()
    for root in roots if roots is not None else desktop_session_dirs(environ):
        if not root.is_dir():
            continue
        for path in root.rglob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(data, dict):
                continue
            for key in ("cliSessionId", "sessionId"):
                value = data.get(key)
                if isinstance(value, str) and value:
                    ids.add(value)
    return ids


def source_for(event, desktop_ids=None):
    entry = event.get("entrypoint")
    if isinstance(entry, str) and "desktop" in entry.lower():
        return "desktop"
    sid = event.get("session_id")
    if desktop_ids is None:
        desktop_ids = load_desktop_ids()
    if isinstance(sid, str) and sid in desktop_ids:
        return "desktop"
    return "cli"


def prune(sessions, keep=None, source=None, pid=None):
    for sid in list(sessions):
        item = sessions[sid]
        if sid == keep or item.get("status") == "busy" or item.get("blocking"):
            continue
        if source and item.get("source") != source:
            continue
        item_pid = item.get("pid")
        if pid is not None or item_pid is not None:
            if item_pid != pid:
                continue
        sessions.pop(sid, None)


def apply_hook(sessions, event, desktop_ids=None):
    if not isinstance(event, dict):
        return
    sid = event.get("session_id")
    name = event.get("hook_event_name")
    if not isinstance(sid, str) or not sid or not isinstance(name, str):
        return
    if name == "SessionEnd":
        sessions.pop(sid, None)
        return
    source = source_for(event, desktop_ids)
    if name == "SessionStart":
        prune(sessions, keep=sid, source=source)
        return
    notify = event.get("notification_type")
    asking = name in ASK_EVENTS or (name == "Notification" and notify in ASK_NOTIFICATIONS)
    if asking:
        item = sessions.setdefault(sid, {"status": "idle", "blocking": False, "source": source})
        item["source"] = source
        item["blocking"] = True
        if event.get("agent_id"):
            item["child"] = True
        return
    if name in BUSY_EVENTS:
        item = sessions.setdefault(sid, {"status": "idle", "blocking": False, "source": source})
        item["source"] = source
        item["status"] = "busy"
        item["blocking"] = False
        item.pop("background_only", None)
        if event.get("agent_id"):
            item["child"] = True
        elif name in SWITCH_EVENTS:
            prune(sessions, keep=sid, source=source)
        return
    if name in IDLE_EVENTS:
        tasks = event.get("background_tasks")
        background_running = isinstance(tasks, list) and any(
            isinstance(task, dict) and agent_kind(task)[0] == "busy" for task in tasks
        )
        item = sessions.get(sid)
        if item is None and background_running:
            item = {"status": "busy", "blocking": False, "source": source}
            sessions[sid] = item
        if item is None:
            return
        if item.get("child") and not background_running:
            sessions.pop(sid, None)
            return
        item["status"] = "busy" if background_running else "idle"
        item["blocking"] = False
        if background_running:
            item["background_only"] = True
        else:
            item.pop("background_only", None)
        prune(sessions, keep=sid, source=source)


def apply_agents(sessions, rows):
    if not isinstance(rows, list):
        return
    for row in rows:
        if not isinstance(row, dict):
            continue
        sid = row.get("sessionId") or row.get("id")
        if not isinstance(sid, str) or not sid:
            continue
        if row.get("state") in ("done", "failed", "stopped"):
            continue
        kind, blocking = agent_kind(row)
        pid = row.get("pid")
        existing = sessions.get(sid)
        if existing is not None and kind == "idle" and not blocking:
            if pid is not None:
                existing["pid"] = pid
            # An explicit idle presence clears background work after a manual
            # stop, which need not fire another Stop hook. A row with no status
            # is only a presence report and must not clear activity.
            if (existing.get("background_only") and not existing.get("blocking")
                    and (row.get("status") == "idle" or row.get("state") == "idle")):
                existing["status"] = "idle"
                existing.pop("background_only", None)
            continue
        item = existing if existing is not None else {"source": "cli"}
        item.update(status=kind, blocking=blocking)
        if pid is not None:
            item["pid"] = pid
        sessions[sid] = item


def agent_kind(row):
    waiting = row.get("waitingFor")
    status = row.get("status")
    state = row.get("state")
    if waiting or status == "waiting" or state == "blocked":
        return "idle", True
    if state in ("working", "running", "busy") or status in ("busy", "running", "working"):
        return "busy", False
    return "idle", False


def reports(sessions):
    grouped = {source: {"status": {}, "blocking": []} for source in HOOK_SOURCES}
    for sid, item in sessions.items():
        source = item.get("source") if item.get("source") in grouped else "cli"
        grouped[source]["status"][sid] = item.get("status") or "idle"
        if item.get("blocking"):
            grouped[source]["blocking"].append(sid)
    return [
        {"id": source, "status": group["status"], "blocking": group["blocking"]}
        for source, group in grouped.items()
        if group["status"]
    ]


def list_agents():
    try:
        result = subprocess.run(
            ["claude", "agents", "--json"],
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    try:
        data = json.loads(result.stdout or "[]")
    except ValueError:
        return None
    if not isinstance(data, list):
        return None
    return data


def hook_url(bridge_url):
    return bridge_url.rstrip("/") + "/providers/claude"


def hook_handler(bridge_url):
    return {"type": "http", "url": hook_url(bridge_url), "timeout": 1}


def is_ours(handler):
    if not isinstance(handler, dict) or handler.get("type") != "http":
        return False
    return str(handler.get("url") or "").rstrip("/").endswith("/providers/claude")


def group_is_ours(group):
    if not isinstance(group, dict):
        return False
    inner = group.get("hooks")
    return isinstance(inner, list) and any(is_ours(handler) for handler in inner)


def install_hooks(bridge_url, environ=None):
    dest = settings_path(environ)
    dest.parent.mkdir(parents=True, exist_ok=True)
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
    handler = hook_handler(bridge_url)
    for event in HOOK_EVENTS:
        groups = hooks.get(event)
        if not isinstance(groups, list):
            groups = []
        groups = [group for group in groups if not group_is_ours(group)]
        group = {"hooks": [handler]}
        if event == "Notification":
            group["matcher"] = NOTIFICATION_MATCHER
        groups.append(group)
        hooks[event] = groups
    allow = data.get("allowedHttpHookUrls")
    url = handler["url"]
    if isinstance(allow, list) and url not in allow:
        allow.append(url)
    dest.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8", newline="\n")
    return dest


def remove_hooks(environ=None):
    dest = settings_path(environ)
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
    allow = data.get("allowedHttpHookUrls")
    if isinstance(allow, list):
        data["allowedHttpHookUrls"] = [
            url for url in allow if not str(url).rstrip("/").endswith("/providers/claude")
        ]
        if not data["allowedHttpHookUrls"]:
            data.pop("allowedHttpHookUrls", None)
    if data:
        dest.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8", newline="\n")
    else:
        dest.unlink(missing_ok=True)
