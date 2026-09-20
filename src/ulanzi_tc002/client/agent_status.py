from enum import StrEnum


class AgentStatus(StrEnum):
    IDLE = "idle"
    WORKING = "working"
    WAITING = "waiting"
    DONE = "done"


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
