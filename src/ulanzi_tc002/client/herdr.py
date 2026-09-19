import json
import subprocess

from ulanzi_tc002.client.agent_status import AgentStatus, summarize
from ulanzi_tc002.client.watch import KNOWN_PROVIDERS, watch_status

COMMAND_TIMEOUT = 5
STATUSES = {
    "idle": AgentStatus.IDLE,
    "working": AgentStatus.WORKING,
    "blocked": AgentStatus.WAITING,
    "done": AgentStatus.DONE,
    "unknown": None,
}


def parse_status(payload):
    if isinstance(payload, dict) and "error" in payload:
        error = payload["error"]
        reason = error.get("message", error) if isinstance(error, dict) else error
        raise ValueError(f"Unable to read herdr agents: {reason}")
    result = payload.get("result") if isinstance(payload, dict) else None
    if not isinstance(result, dict) or result.get("type") != "agent_list" or not isinstance(result.get("agents"), list):
        raise ValueError("Invalid herdr response: expected an agent_list result with an agents array")
    statuses = {}
    for row in result["agents"]:
        if not isinstance(row, dict):
            raise ValueError("Invalid herdr response: expected an agent object")
        pane = row.get("pane_id")
        if not isinstance(pane, str) or not pane.strip():
            raise ValueError("Invalid herdr response: expected a nonempty pane_id string")
        agent = row.get("agent")
        if agent is not None and not isinstance(agent, str):
            raise ValueError("Invalid herdr response: expected an agent name")
        status = row.get("agent_status")
        if not isinstance(status, str) or status not in STATUSES:
            raise ValueError(f"Invalid herdr status for pane {pane}: {status!r}")
        statuses[pane] = (agent.lower() if agent else None, STATUSES[status])
    grouped = {}
    messages = []
    for pane, (agent, status) in statuses.items():
        if agent not in KNOWN_PROVIDERS:
            messages.append(f"Skipping herdr agent {agent or '(unnamed)'}: no matching tc002 provider app.")
            continue
        if status is None:
            messages.append(f"Skipping herdr pane {pane} ({agent}): agent status is unknown.")
            continue
        grouped.setdefault(agent, {})[pane] = status
    states = [(name, *summarize(grouped[name], ())) for name in KNOWN_PROVIDERS if name in grouped]
    return states, tuple(dict.fromkeys(messages))


def read_status(machine=None, session=None):
    command = ["herdr"]
    if machine is not None:
        command.extend(["--machine", machine])
    if session is not None:
        command.extend(["--session", session])
    command.extend(["agent", "list"])
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, encoding="utf-8", errors="replace",
            stdin=subprocess.DEVNULL, timeout=COMMAND_TIMEOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except FileNotFoundError:
        raise ValueError("herdr was not found on PATH; install herdr to use 'tc002 watch herdr'") from None
    except subprocess.TimeoutExpired:
        raise ValueError(f"herdr agent list timed out after {COMMAND_TIMEOUT} seconds") from None
    if result.returncode:
        reason = result.stderr.strip() or result.stdout.strip() or f"exit code {result.returncode}"
        raise ValueError(f"Unable to read herdr agents: {reason}")
    try:
        payload = json.loads(result.stdout)
    except ValueError:
        raise ValueError("Invalid JSON from herdr agent list") from None
    return parse_status(payload)


def watch_herdr(args, api):
    watch_status(args, api, "herdr", lambda: read_status(args.machine, args.session))
