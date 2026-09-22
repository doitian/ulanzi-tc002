from enum import StrEnum


class AgentStatus(StrEnum):
    IDLE = "idle"
    RUNNING = "running"
    WAITING = "waiting"
    DONE = "done"


def summarize_counts(counts):
    kind = next((kind for kind in ("ask", "run", "done") if counts[kind]), "idle")
    return kind, counts[kind], counts


def summarize(status_by_id, blocking):
    blocking = set(blocking)
    counts = {"ask": len(blocking), "run": 0, "done": 0, "idle": 0}
    for sid, status in status_by_id.items():
        if sid in blocking:
            continue
        if status in ("busy", "retry", AgentStatus.RUNNING):
            counts["run"] += 1
        elif status == AgentStatus.WAITING:
            counts["ask"] += 1
        elif status == AgentStatus.DONE:
            counts["done"] += 1
        elif status == AgentStatus.IDLE:
            counts["idle"] += 1
    return summarize_counts(counts)
