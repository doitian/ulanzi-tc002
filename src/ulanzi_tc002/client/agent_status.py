from dataclasses import dataclass
from enum import StrEnum


class AgentStatus(StrEnum):
    IDLE = "idle"
    WORKING = "working"
    WAITING = "waiting"
    DONE = "done"


class AgentEventKind(StrEnum):
    SESSION_START = "session-start"
    PROMPT_SUBMIT = "prompt-submit"
    TOOL_START = "tool-start"
    TOOL_COMPLETE = "tool-complete"
    PERMISSION_REQUEST = "permission-request"
    QUESTION_ASKED = "question-asked"
    NOTIFICATION = "notification"
    STOP = "stop"
    SESSION_END = "session-end"


@dataclass(frozen=True)
class AgentEvent:
    session_id: str
    kind: AgentEventKind
    source: str = "cli"
    pid: int | None = None
    parent_id: str | None = None
    background_running: bool = False


@dataclass
class AgentSession:
    status: AgentStatus = AgentStatus.IDLE
    source: str = "cli"
    pid: int | None = None
    parent_id: str | None = None
    background_only: bool = False

    def apply(self, event):
        self.source = event.source
        if event.pid is not None:
            self.pid = event.pid
        if event.parent_id is not None:
            self.parent_id = event.parent_id
        match event.kind:
            case AgentEventKind.PROMPT_SUBMIT:
                self.status = AgentStatus.WORKING
                self.background_only = False
            case AgentEventKind.TOOL_START:
                if self.status == AgentStatus.IDLE:
                    self.status = AgentStatus.WORKING
                if self.status == AgentStatus.WORKING:
                    self.background_only = False
            case AgentEventKind.TOOL_COMPLETE:
                if self.status == AgentStatus.WAITING:
                    self.status = AgentStatus.WORKING
                if self.status == AgentStatus.WORKING:
                    self.background_only = False
            case AgentEventKind.PERMISSION_REQUEST | AgentEventKind.QUESTION_ASKED:
                self.status = AgentStatus.WAITING
            case AgentEventKind.NOTIFICATION:
                if self.status == AgentStatus.WORKING:
                    self.status = AgentStatus.WAITING
            case AgentEventKind.STOP:
                self.status = AgentStatus.WORKING if event.background_running else AgentStatus.DONE
                self.background_only = event.background_running


def session_key(event):
    sid = event.get("session_id")
    agent = event.get("agent_id")
    if isinstance(agent, str) and agent:
        return f"{sid}:{agent}" if isinstance(sid, str) and sid else agent
    return sid


def prune(sessions, keep=None, source=None, pid=None):
    for sid, item in list(sessions.items()):
        if sid == keep or item.status in (AgentStatus.WORKING, AgentStatus.WAITING):
            continue
        if source is not None and item.source != source:
            continue
        if item.pid != pid:
            continue
        del sessions[sid]


def apply_event(sessions, event):
    sid, kind = event.session_id, event.kind
    item = sessions.get(sid)
    pid = event.pid if event.pid is not None else item.pid if item else None
    if kind == AgentEventKind.SESSION_END:
        sessions.pop(sid, None)
        for child_id, child in list(sessions.items()):
            if child.parent_id == sid:
                del sessions[child_id]
        return
    if kind == AgentEventKind.SESSION_START:
        prune(sessions, keep=sid, source=event.source, pid=pid)
        return
    if item is None:
        if kind in (AgentEventKind.TOOL_COMPLETE, AgentEventKind.NOTIFICATION):
            return
        if kind == AgentEventKind.STOP and not event.background_running:
            return
        item = sessions[sid] = AgentSession()
    item.apply(event)
    if item.parent_id is not None:
        if item.status == AgentStatus.DONE:
            del sessions[sid]
    elif kind in (AgentEventKind.PROMPT_SUBMIT, AgentEventKind.STOP):
        prune(sessions, keep=sid, source=item.source, pid=item.pid)


def reports(sessions):
    grouped = {}
    for sid, item in sessions.items():
        group = grouped.setdefault(item.source, {"id": item.source, "status": {}, "blocking": []})
        group["status"][sid] = "busy" if item.status == AgentStatus.WORKING else "idle"
        if item.status == AgentStatus.WAITING:
            group["blocking"].append(sid)
    return list(grouped.values())


def summarize_counts(counts):
    kind = next((kind for kind in ("ask", "run") if counts[kind]), "idle")
    return kind, counts[kind], counts


def summarize(status_by_id, blocking):
    blocking = set(blocking)
    counts = {"ask": len(blocking), "run": 0, "idle": 0}
    for sid, status in status_by_id.items():
        if sid in blocking:
            continue
        if status in ("busy", "retry", AgentStatus.WORKING):
            counts["run"] += 1
        elif status == AgentStatus.WAITING:
            counts["ask"] += 1
        elif status in (AgentStatus.IDLE, AgentStatus.DONE):
            counts["idle"] += 1
    return summarize_counts(counts)
